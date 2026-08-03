"""Starred unpack: authenticated finite members + opaque arity honesty.

Python law:

    head, *tail = rhs

- Over authenticated tuple/list members: bind head and tail (list) in source
  order; too few fixed positions → named ValueError.
- Over opaque / runtime-selected members: retain typed
  ``SequenceUnpackRuntimeEffect``; bind nothing; never fabricate arity or
  complete.
- Later store halt preserves earlier bindings from a completed star unpack
  prefix.
- Arity and reversed-tail lying twins fail.

Producer: ``SequenceProjectionOperation`` (+ ``DynamicUnpackAssignSugar``
submit). Floor: ``TupleValue`` / ``ListValue``.project_sequence_with.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.effect import SequenceUnpackRuntimeEffect
from sugar_lift_py_tests.floor.list_value import ListValue
from sugar_lift_py_tests.floor.scope_rebind import ScopeRebinds
from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
from sugar_lift_py_tests.floor.term_value import TermValue
from sugar_lift_py_tests.floor.tuple_literal_value import TupleLiteralValue
from sugar_lift_py_tests.floor.tuple_value import TupleValue
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.operations import SequenceProjectionOperation
from sugar_lift_py_tests.outcome import Complete, Incomplete
from sugar_lift_py_tests.outcome.exit_set import Completed, Halted, outcome_to_exitset
from sugar_lift_python_source.source_oracle import path_source, workspace_path_source
from sugar_source_tree.tree import SourceFile


def _star_op(
    *,
    prefix: tuple[str, ...] = (),
    star: str = "tail",
    suffix: tuple[str, ...] = (),
    blame: object = "star-site",
) -> SequenceProjectionOperation:
    return SequenceProjectionOperation(
        target_names=(*prefix, *suffix),
        owner="starred-unpack",
        blame=blame,
        star_name=star,
        prefix_names=prefix,
        suffix_names=suffix,
    )


def _function_sugar(tmp_path: Path, source: str, stem: str):
    path = tmp_path / f"{stem}.py"
    path.write_text(source, encoding="utf-8")
    return next(SourceFile(path_source(str(path))).functions()).sugar()


def _workspace_site(tmp_path: Path):
    """Workspace-relative fragment so ground ValueError can cite source."""
    path = tmp_path / "pkg" / "site.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("def f(xs):\n    a, *rest = xs\n    return a\n")
    tree = SourceFile(workspace_path_source(str(path), root=str(tmp_path)))
    function = next(tree.functions())
    return function.body[0].fragment


# ---------------------------------------------------------------------------
# Authenticated finite members: head, *tail in source order
# ---------------------------------------------------------------------------


def test_tuple_head_star_tail_binds_source_order() -> None:
    members = (TermValue(1), TermValue(2), TermValue(3), TermValue(4))
    outcome = _star_op(prefix=("head",)).submit(TupleValue(members), None)
    assert isinstance(outcome, Complete)
    assert outcome.value == ScopeRebinds(
        (
            ("head", TermValue(1)),
            ("tail", ListValue((TermValue(2), TermValue(3), TermValue(4)))),
        )
    )


def test_list_head_star_tail_binds_source_order() -> None:
    members = (TermValue(10), TermValue(20), TermValue(30))
    outcome = _star_op(prefix=("head",)).submit(ListValue(members), None)
    assert isinstance(outcome, Complete)
    assert outcome.value == ScopeRebinds(
        (
            ("head", TermValue(10)),
            ("tail", ListValue((TermValue(20), TermValue(30)))),
        )
    )


def test_head_star_mid_suffix_binds_middle_as_list() -> None:
    members = (TermValue(1), TermValue(2), TermValue(3), TermValue(4))
    outcome = _star_op(prefix=("a",), star="mid", suffix=("b",)).submit(
        TupleLiteralValue(members), None
    )
    assert isinstance(outcome, Complete)
    assert outcome.value == ScopeRebinds(
        (
            ("a", TermValue(1)),
            ("mid", ListValue((TermValue(2), TermValue(3)))),
            ("b", TermValue(4)),
        )
    )


def test_empty_tail_is_empty_list_not_none() -> None:
    """``a, *rest = (1,)``: rest is [] — never None, never omitted."""
    outcome = _star_op(prefix=("a",)).submit(TupleValue((TermValue(1),)), None)
    assert isinstance(outcome, Complete)
    assert outcome.value == ScopeRebinds((("a", TermValue(1)), ("tail", ListValue(()))))


def test_reversed_tail_lying_twin_fails() -> None:
    """Bite: reverse middle members must not match the truthful rebind."""
    members = (TermValue(1), TermValue(2), TermValue(3), TermValue(4))
    outcome = _star_op(prefix=("head",)).submit(TupleValue(members), None)
    truthful = outcome.value
    lying = ScopeRebinds(
        (
            ("head", TermValue(1)),
            ("tail", ListValue((TermValue(4), TermValue(3), TermValue(2)))),
        )
    )
    assert truthful != lying
    with pytest.raises(AssertionError):
        assert truthful == lying


# ---------------------------------------------------------------------------
# Too-few → named ValueError
# ---------------------------------------------------------------------------


def test_too_few_members_named_valueerror(tmp_path: Path) -> None:
    site = _workspace_site(tmp_path)
    # Need two fixed positions (a and b) but only one member.
    op = _star_op(prefix=("a", "b"), star="rest", blame=site)
    outcome = op.submit(TupleValue((TermValue(1),)), None)
    assert isinstance(outcome, Incomplete)
    # RaiseEffect is unconstructible without coordinate; pin identity, not presence.
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect

    assert isinstance(outcome.effect, RaiseEffect)
    expected = RaiseEffect.for_builtin(
        "ValueError",
        occurrence="implementations/python/sugar-lift-py-tests/tests/test_starred_unpack_projection.py:156:0",
    )
    assert (
        outcome.effect.exception_type_coordinate == expected.exception_type_coordinate
    )


def test_too_few_discrimination_is_not_completed_bind(tmp_path: Path) -> None:
    site = _workspace_site(tmp_path)
    op = _star_op(prefix=("a", "b"), star="rest", blame=site)
    outcome = op.submit(ListValue((TermValue(1),)), None)
    with pytest.raises(AssertionError):
        assert isinstance(outcome, Complete), "too-few starred unpack completed"


# ---------------------------------------------------------------------------
# Opaque / runtime-selected: typed obligation, no bind, never completion
# ---------------------------------------------------------------------------


def test_opaque_starred_retains_typed_obligation_no_bind(tmp_path: Path) -> None:
    site = _workspace_site(tmp_path)
    outcome = _star_op(prefix=("head",), blame=site).submit(
        SymbolicValue(make_var("xs")), None
    )
    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, SequenceUnpackRuntimeEffect)
    assert "no authenticated cardinality" in outcome.effect.reason
    assert (
        "at least" in outcome.effect.reason or "starred=True" in outcome.effect.reason
    )


def test_source_opaque_starred_never_completes(tmp_path: Path) -> None:
    outcome = _function_sugar(
        tmp_path, "def f(xs):\n    head, *tail = xs\n    return head\n", "opaque_src"
    ).desugar(None)
    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, SequenceUnpackRuntimeEffect)
    with pytest.raises(AssertionError):
        assert isinstance(outcome, Complete)


def test_opaque_starred_discrimination_display_does_bind(tmp_path: Path) -> None:
    """Display twin completes; opaque does not — so the red is not universal."""
    opaque = _function_sugar(
        tmp_path, "def f(xs):\n    a, *rest = xs\n    return a\n", "op_disc"
    ).desugar(None)
    display = _function_sugar(
        tmp_path,
        "def f(p, q, r):\n    a, *rest = p, q, r\n    return a\n",
        "disp_disc",
    ).desugar(None)
    assert isinstance(opaque, Incomplete)
    assert isinstance(display, Complete)


# ---------------------------------------------------------------------------
# Later store halt preserves earlier starred bindings
# ---------------------------------------------------------------------------


def _workspace_function_sugar(tmp_path: Path, source: str, stem: str):
    """Workspace-relative source so ground TypeError exits can cite the store."""
    path = tmp_path / "pkg" / f"{stem}.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return next(
        SourceFile(workspace_path_source(str(path), root=str(tmp_path))).functions()
    ).sugar()


def test_later_store_halt_preserves_earlier_star_bindings(tmp_path: Path) -> None:
    """Star binds first; later immutable store halts; body is not sole-Completed.

    ``head, *tail = (1, 2, 3)`` is MultiAssign (display); the following
    ``xs[0] = 9`` on a tuple is a decided setitem TypeError. The star binding
    is not rolled back into a body that pretends the store never ran.
    """
    source = (
        "def f():\n"
        "    head, *tail = (1, 2, 3)\n"
        "    xs = (0,)\n"
        "    xs[0] = 9\n"
        "    return head\n"
    )
    raw = _workspace_function_sugar(tmp_path, source, "star_then_store").desugar(None)
    outcome = outcome_to_exitset(raw)
    halted = [e for e in outcome.exits if isinstance(e, Halted)]
    completed = [e for e in outcome.exits if isinstance(e, Completed)]
    assert len(halted) == 1
    assert len(completed) == 0
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect

    assert isinstance(halted[0].effect, RaiseEffect)
    expected = RaiseEffect.for_builtin(
        "TypeError",
        occurrence="implementations/python/sugar-lift-py-tests/tests/test_starred_unpack_projection.py:248:0",
    )
    assert (
        halted[0].effect.exception_type_coordinate == expected.exception_type_coordinate
    )
    # No completed return face — store halt blocked later targets.
    assert not any(isinstance(e, Completed) for e in outcome.exits)


def test_later_store_halt_discrimination_not_sole_completed(tmp_path: Path) -> None:
    source = (
        "def f():\n"
        "    head, *tail = (1, 2, 3)\n"
        "    xs = (0,)\n"
        "    xs[0] = 9\n"
        "    return head\n"
    )
    outcome = outcome_to_exitset(
        _workspace_function_sugar(tmp_path, source, "star_then_store_d").desugar(None)
    )
    with pytest.raises(AssertionError):
        assert len(outcome.exits) == 1 and isinstance(
            outcome.exits[0], Completed
        ), "store halt erased by sole Completed"


# ---------------------------------------------------------------------------
# Arity lying twin
# ---------------------------------------------------------------------------


def test_arity_lying_twin_exact_count_is_not_star_minimum() -> None:
    """Exact-arity of 1 is not the same demand as head,*tail over 3 members."""
    from sugar_lift_py_tests.gap.panic import ConstructionPanic

    exact = SequenceProjectionOperation(
        target_names=("head",), owner="exact", blame="x"
    )
    starred = _star_op(prefix=("head",))
    members = (TermValue(1), TermValue(2), TermValue(3))
    star_ok = starred.submit(TupleValue(members), None)
    assert isinstance(star_ok, Complete)
    # Exact one-name against three members is a mismatch (too many) → gap on prose site.
    with pytest.raises(ConstructionPanic):
        exact.submit(TupleValue(members), None)
    with pytest.raises(AssertionError):
        assert star_ok.value == ScopeRebinds((("head", TermValue(1)),))


def test_source_authenticated_star_binds_through_local_display(tmp_path: Path) -> None:
    """``xs = (1,2,3); head, *tail = xs`` via substitution MultiAssign."""
    outcome = _function_sugar(
        tmp_path,
        "def f():\n    xs = (1, 2, 3)\n    head, *tail = xs\n    return head\n",
        "local_star",
    ).desugar(None)
    assert isinstance(outcome, Complete)
    assert "1" in str(outcome.value.record) or "TermValue(value=1)" in str(
        outcome.value
    )
