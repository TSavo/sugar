"""Pinned pandas Subscript helpers have no source caller to discharge them."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

import pytest

from frame_fresh import fresh
from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
from sugar_lift_py_tests.caller_parameter_contract import (
    NativeOperationExitCarrierV1,
)
from sugar_lift_py_tests.context_manager_contract import (
    AuthenticatedRaiseMatcher,
    EffectBoundaryDisposition,
)
from sugar_lift_py_tests.context_manager_resolution import (
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.effect.expectation_not_met_effect import (
    ExpectationNotMetEffect,
)
from sugar_lift_py_tests.floor import ListValue, SymbolicValue, TermValue
from sugar_lift_py_tests.formal_parameter import FormalParameterCoordinateV1
from sugar_lift_py_tests.ir import PrimitiveSort, ctor, make_var, str_const
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Subscript
from sugar_source_tree.tree import SourceFile

MANIFEST_CID = (
    "blake3-512:6f317a5a489eb7e730064d79792f0d1656723130603309e2f2ed9cbedb604eda"
    "1c4b77a26dc90c980411292ea3994af9015da4cd850b5a307af5a4998b563530"
)


@dataclass(frozen=True)
class _Candidate:
    relative_path: str
    helper_name: str
    helper_line: int
    with_line: int
    operation_line: int
    receiver_name: str
    index_name: str


EXPECTED_CANDIDATES = (
    _Candidate(
        "tests/extension/base/getitem.py",
        "test_getitem_integer_with_missing_raises",
        256,
        258,
        259,
        "data",
        "idx",
    ),
    _Candidate(
        "tests/indexes/test_any_index.py",
        "test_getitem_error",
        149,
        161,
        162,
        "index",
        "item",
    ),
)


def _read(path: Path, relative_path: str, overrides: dict[str, str]) -> str:
    return overrides.get(relative_path, path.read_text(encoding="utf-8"))


def _direct_formal_candidates(
    root: Path, *, overrides: dict[str, str] | None = None
) -> tuple[_Candidate, ...]:
    """Find the exact ``with pytest.raises(...): receiver[index]`` shape."""
    overrides = {} if overrides is None else overrides
    candidates = []
    for path in root.rglob("*.py"):
        relative_path = path.relative_to(root).as_posix()
        source = _read(path, relative_path, overrides)
        if "pytest.raises" not in source:
            continue
        tree = ast.parse(source, filename=relative_path)
        for helper in ast.walk(tree):
            if not isinstance(helper, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            formals = {
                argument.arg
                for argument in (
                    *helper.args.posonlyargs,
                    *helper.args.args,
                    *helper.args.kwonlyargs,
                )
            }
            for statement in ast.walk(helper):
                if not isinstance(statement, (ast.With, ast.AsyncWith)):
                    continue
                is_pytest_raises = any(
                    isinstance(item.context_expr, ast.Call)
                    and isinstance(item.context_expr.func, ast.Attribute)
                    and isinstance(item.context_expr.func.value, ast.Name)
                    and item.context_expr.func.value.id == "pytest"
                    and item.context_expr.func.attr == "raises"
                    for item in statement.items
                )
                if (
                    not is_pytest_raises
                    or len(statement.body) != 1
                    or not isinstance(statement.body[0], ast.Expr)
                    or not isinstance(statement.body[0].value, ast.Subscript)
                ):
                    continue
                operation = statement.body[0].value
                if (
                    not isinstance(operation.ctx, ast.Load)
                    or not isinstance(operation.value, ast.Name)
                    or not isinstance(operation.slice, ast.Name)
                    or operation.value.id not in formals
                    or operation.slice.id not in formals
                    or operation.value.id == operation.slice.id
                ):
                    continue
                candidates.append(
                    _Candidate(
                        relative_path,
                        helper.name,
                        helper.lineno,
                        statement.lineno,
                        operation.lineno,
                        operation.value.id,
                        operation.slice.id,
                    )
                )
    return tuple(sorted(candidates, key=lambda candidate: candidate.relative_path))


def _explicit_calls(
    root: Path,
    candidates: tuple[_Candidate, ...],
    *,
    overrides: dict[str, str] | None = None,
) -> tuple[tuple[str, int, str], ...]:
    overrides = {} if overrides is None else overrides
    names = {candidate.helper_name for candidate in candidates}
    calls = []
    for path in root.rglob("*.py"):
        relative_path = path.relative_to(root).as_posix()
        source = _read(path, relative_path, overrides)
        if not any(f"{name}(" in source for name in names):
            continue
        tree = ast.parse(source, filename=relative_path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = (
                node.func.id
                if isinstance(node.func, ast.Name)
                else node.func.attr if isinstance(node.func, ast.Attribute) else None
            )
            if name in names:
                calls.append((relative_path, node.lineno, name))
    return tuple(sorted(calls))


def _assert_no_source_caller(
    root: Path, *, overrides: dict[str, str] | None = None
) -> None:
    candidates = _direct_formal_candidates(root, overrides=overrides)
    assert candidates == EXPECTED_CANDIDATES
    assert _explicit_calls(root, candidates, overrides=overrides) == ()


def _authenticated_root() -> Path:
    corpus = authenticated_pandas_corpus()
    assert (corpus.version, corpus.file_count, corpus.manifest_cid) == (
        "3.0.3",
        1421,
        MANIFEST_CID,
    )
    return corpus.root


def test_pinned_pandas_has_no_subscript_helper_caller_pair_to_discharge() -> None:
    """The corpus has helpers, but no source call supplies both actuals.

    Pytest fixture/parametrization injection is not a source call edge.  Until
    one definition-coordinate door projects ``__getitem__`` through a real
    formal-to-actual binding, these helpers must remain undischarged rather
    than borrow the exception expected by ``pytest.raises``.
    """
    _assert_no_source_caller(_authenticated_root())


def test_lying_inserted_caller_makes_the_absence_claim_fail() -> None:
    """Mutation tooth: a real call makes the honest-negative ratchet bite."""
    root = _authenticated_root()
    relative_path = "tests/indexes/test_any_index.py"
    source = (root / relative_path).read_text(encoding="utf-8")
    lying = source + "\n\ntest_getitem_error([1], 2)\n"

    with pytest.raises(AssertionError):
        _assert_no_source_caller(root, overrides={relative_path: lying})


def _formal_coordinate(
    site: object, name: str, ordinal: int
) -> FormalParameterCoordinateV1:
    span = site.line_col_span
    owner = SourceFragmentCoordinateV1(
        site.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )
    return FormalParameterCoordinateV1.mint(
        owner_source_identity_cid=site.source_cid,
        owner_definition_locus=owner,
        declaration_locus=owner,
        ordinal=ordinal,
        parameter_kind="positional-or-keyword",
        declared_name=name,
        sort=PrimitiveSort("Value"),
    )


def _synthetic_formals() -> tuple[
    object,
    FormalParameterCoordinateV1,
    FormalParameterCoordinateV1,
]:
    """The producer-only helper's ``obj[key]`` site and its two formals;
    pandas absence is tested above."""
    source = "def helper(obj, key):\n    return obj[key]\n"
    tree = SourceFile(
        (source, "synthetic-subscript-helper.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    node = next(item for item in tree.nodes() if isinstance(item, Subscript))
    obj_coordinate = _formal_coordinate(node.fragment, "obj", 0)
    key_coordinate = _formal_coordinate(node.fragment, "key", 1)
    return node.fragment, obj_coordinate, key_coordinate


def _assert_two_faced_read(exits, owner: str) -> None:
    """The one two-faced unanswered read, no carrier: completes under the
    subscript's completes atom, else an undetermined raise owned by
    ``owner``; the read is owed at its site.  No KeyError or IndexError is
    guessed."""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.unanswered_calls import owed_calls

    assert not isinstance(exits, NativeOperationExitCarrierV1), type(exits)
    (halt,) = [arm for arm in exits.exits if isinstance(arm, Halted)]
    (done,) = [arm for arm in exits.exits if isinstance(arm, Completed)]
    assert type(halt.effect) is UndeterminedRaiseEffect
    assert halt.effect.producer_node_owner == owner
    assert "python:subscript_op.completes" in repr(done.guard)
    assert any(item.site is not None for item in owed_calls(exits))


def _subscript_read(receiver, index, site):
    from sugar_lift_py_tests.operations.subscript_operation import (
        discharge_subscript,
    )

    return discharge_subscript(receiver, index, site, None, owner="SubscriptSugar")


def test_synthetic_formals_read_is_the_two_faced_unanswered_read() -> None:
    """Synthetic boundary: formal ``obj[key]`` mints no carrier waiting on a
    caller's actual (#7757, audit 2 row NEW-1).  Nothing decides
    ``type(obj)`` or its ``__getitem__``, so the read is the one undecided
    read, owed at its site, its halt kept."""
    site, obj_coordinate, key_coordinate = _synthetic_formals()

    exits = SymbolicValue(make_var("obj"), obj_coordinate).subscript(
        SymbolicValue(make_var("key"), key_coordinate), site
    )

    _assert_two_faced_read(exits, "SymbolicValue.subscript")


def test_swapped_receiver_and_index_is_the_same_undecided_read() -> None:
    site, obj_coordinate, key_coordinate = _synthetic_formals()

    swapped = SymbolicValue(make_var("key"), key_coordinate).subscript(
        SymbolicValue(make_var("obj"), obj_coordinate), site
    )

    _assert_two_faced_read(swapped, "SymbolicValue.subscript")


def test_coordinate_free_subscript_is_the_two_faced_unanswered_read() -> None:
    site, _, _ = _synthetic_formals()

    exits = SymbolicValue(make_var("obj")).subscript(SymbolicValue(make_var("key")), site)

    _assert_two_faced_read(exits, "SymbolicValue.subscript")


def test_helper_alone_owes_its_read() -> None:
    """With no caller the read is the cited unanswered face (#7825): owed at
    its site, no value chosen."""
    from sugar_lift_py_tests.unanswered_calls import owed_calls, unanswered_call

    site, obj_coordinate, key_coordinate = _synthetic_formals()
    exits = SymbolicValue(make_var("obj"), obj_coordinate).subscript(
        SymbolicValue(make_var("key"), key_coordinate), site
    )

    assert unanswered_call(None, site) in owed_calls(exits)
    assert exits.completed_value() is None


def test_a_decided_list_and_key_complete_the_read() -> None:
    """The floor's own read where the lift decides both operands: what a
    caller's actuals used to be projected onto."""
    site, _, _ = _synthetic_formals()

    exits = _subscript_read(fresh(ListValue, (TermValue(7),)), TermValue(0), site)

    assert exits.exits == (Completed(exits.exits[0].guard, TermValue(7)),)


def _index_error_read():
    site, _, _ = _synthetic_formals()
    return site, _subscript_read(fresh(ListValue, (TermValue(7),)), TermValue(1), site)


def test_a_decided_out_of_range_key_names_an_exception_at_the_subscript() -> None:
    site, exits = _index_error_read()

    assert len(exits.exits) == 1
    halted = exits.exits[0]
    assert isinstance(halted, Halted)
    # ListValue[1] on len-1 list is IndexError (not TypeError). Presence-only
    # used to green either; the value pin must name IndexError or it is a false tooth.
    assert halted.effect.exception_type_coordinate == _Expected("IndexError").identity
    assert halted.effect.occurrence_id == f"{site.filename}:{site.line}:{site.col}"


class _Expected:
    def __init__(self, name: str):
        self.identity = ctor(
            "python:exception_type_identity",
            [str_const("builtins"), str_const(name)],
        )

    def exception_type_identity(self):
        return self.identity


def test_lying_boundary_exception_type_leaves_operation_halted_and_unconsumed() -> None:
    site, exits = _index_error_read()

    routed = exits.and_exit(
        ExitSet.completed(object()),
        disposition=EffectBoundaryDisposition(
            matcher=AuthenticatedRaiseMatcher(expected=_Expected("ValueError")),
            unmet=ExpectationNotMetEffect("raise", "assertion-site"),
        ),
    )

    assert len(routed.exits) == 1
    assert isinstance(routed.exits[0], Halted)
    assert (
        routed.exits[0].effect.occurrence_id
        == f"{site.filename}:{site.line}:{site.col}"
    )
    assert (
        routed.exits[0].effect.exception_type_coordinate
        != _Expected("ValueError").identity
    )


def test_undecided_receiver_is_the_two_faced_unanswered_read() -> None:
    site, _, _ = _synthetic_formals()

    exits = _subscript_read(SymbolicValue(make_var("actual_obj")), TermValue(0), site)

    _assert_two_faced_read(exits, "SymbolicValue.subscript")


def test_undecided_key_on_a_decided_list_is_the_lists_two_faced_read() -> None:
    site, _, _ = _synthetic_formals()

    exits = _subscript_read(
        fresh(ListValue, (TermValue(7),)), SymbolicValue(make_var("actual_key")), site
    )

    _assert_two_faced_read(exits, "ListValue.subscript")


# ---------------------------------------------------------------------------
# A formal's subscript has one way: the undecided read, owed, its halt kept
# (#7757, audit 2 row NEW-1)
# ---------------------------------------------------------------------------


def _subscript_operation(site):
    from sugar_lift_py_tests.operations.subscript_operation import (
        SubscriptOperation,
    )

    return SubscriptOperation(index=TermValue(0), owner="SubscriptSugar", blame=site)


def test_a_formal_subscript_through_its_operation_is_the_undecided_read() -> None:
    """``SymbolicValue.subscript_with`` (every source ``formal[k]``) answers
    as ``SymbolicValue.subscript`` does: the callee's undecided read, never a
    carrier waiting on the caller's actual."""
    site, obj_coordinate, _ = _synthetic_formals()
    formal = SymbolicValue(make_var("obj"), obj_coordinate)

    _assert_two_faced_read(
        _subscript_operation(site).submit(formal, None), "SymbolicValue.subscript"
    )
    _assert_two_faced_read(
        formal.subscript(TermValue(0), site), "SymbolicValue.subscript"
    )


def _source_function_outcome(source: str, name: str):
    from sugar_source_tree.nodes import FunctionDef

    tree = SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    return function.sugar().desugar(None)


def _assert_read_with_its_halt(outcome) -> None:
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect

    assert not isinstance(outcome, NativeOperationExitCarrierV1), type(outcome)
    assert any(
        isinstance(arm, Halted) and type(arm.effect) is UndeterminedRaiseEffect
        for arm in outcome.exits
    ), outcome


def test_a_source_formal_subscript_is_the_undecided_read() -> None:
    """``def helper(obj, key): return obj[key]`` from source: the callee
    answers the undecided read, its halt kept, instead of deferring it."""
    _assert_read_with_its_halt(
        _source_function_outcome(
            "def helper(obj, key):\n    return obj[key]\n",
            "formal-subscript-helper.py",
        )
    )


def test_the_one_subscript_door_asks_the_operation_edge() -> None:
    """A floor that owns only the ``subscript_with`` edge answers through
    that edge (the legacy ``subscript`` path refused it as a construction
    gap)."""
    from sugar_lift_py_tests.floor.floor_value import FloorValue

    @dataclass(frozen=True)
    class _OperationEdgeOnly(FloorValue):
        def subscript_with(self, operation, ctx):
            del ctx
            assert operation.index == TermValue(0)
            return ExitSet.completed(TermValue(42))

    site, _, _ = _synthetic_formals()

    exits = _subscript_read(_OperationEdgeOnly(), TermValue(0), site)

    assert len(exits.exits) == 1
    assert isinstance(exits.exits[0], Completed)
    assert exits.exits[0].value == TermValue(42)


# ---------------------------------------------------------------------------
# A parameter index on a decided receiver: the receiver's own read with the
# symbolic key (#7757, audit 2 row NEW-1)
# ---------------------------------------------------------------------------


def test_a_formal_index_on_a_known_list_is_the_lists_own_read() -> None:
    """``[1, 2][i]`` with ``i`` a parameter: the list is decided, the index is
    not, so the list reads it as the undecided read, its halt kept -- never a
    carrier, never an element chosen for it."""
    site, _, key_coordinate = _synthetic_formals()

    exits = _subscript_read(
        fresh(ListValue, (TermValue(1), TermValue(2))),
        SymbolicValue(make_var("key"), key_coordinate),
        site,
    )

    _assert_two_faced_read(exits, "ListValue.subscript")


def test_a_formal_index_through_a_symbolic_receiver_is_the_same_read() -> None:
    """The receiver's own ``subscript`` and the door answer the one read."""
    site, _, key_coordinate = _synthetic_formals()
    receiver = SymbolicValue(make_var("obj"))
    index = SymbolicValue(make_var("key"), key_coordinate)

    _assert_two_faced_read(receiver.subscript(index, site), "SymbolicValue.subscript")
    _assert_two_faced_read(
        _subscript_read(receiver, index, site), "SymbolicValue.subscript"
    )


def test_a_source_formal_index_is_the_lists_own_read() -> None:
    _assert_read_with_its_halt(
        _source_function_outcome(
            "def consume(i):\n    return [1, 2][i]\n", "formal-index-helper.py"
        )
    )
