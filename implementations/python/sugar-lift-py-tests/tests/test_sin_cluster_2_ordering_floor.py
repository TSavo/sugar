"""SIN CLUSTER 2 + LAW_OF_ONE — ordering meaning is Sugar, never a floor invent.

LAW_OF_ONE: AST shadows → temporal rewrite → Sugar → meaning. No other
mechanism. An ordering OUTCOME is meaning, so minting
``Complete(PredicateValue(py.lt/…))`` from a Python floor helper is a second
mechanism even when the atom would be "right".

Throwing is honorable. Undecided must never become a value. Decided ground
pairs construct Sugar (TrueBool/FalseBool/RaiseValue) on owned arms only.

Also covers:
- undecided binary: nameless halt is forbidden
- undecided contains: named refusal
- undecided attribute: named refusal (already correct)

NOTE: ``tests/law_of_one_auditor.py`` audits SourceFile construction ownership
and cannot see this floor-meaning sin. The AST tooth below is the instrument
that names the offender until a stronger substrate exists.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
from sugar_lift_py_tests.floor.none_value import NoneValue
from sugar_lift_py_tests.floor.string_value import StringValue
from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
from sugar_lift_py_tests.floor.term_value import TermValue
from sugar_lift_py_tests.ir import ctor, make_var
from sugar_lift_py_tests.outcome import Complete
from sugar_source_tree.panic import SugarNotWritten

SITE = "sin-cluster-2-ordering-site"

_ORDERING_METHODS = frozenset(
    {
        "less_than",
        "less_than_from_left",
        "less_equal",
        "greater_than",
        "greater_equal",
        "_refuse_ordering_meaning",
        "_undecided_ordering_law",
    }
)


def _symbolic() -> SymbolicValue:
    return SymbolicValue(make_var("s"))


def _callsite() -> CallSiteValue:
    return CallSiteValue("unknown", (), (), ctor("call:unknown", []), None)


# ---------------------------------------------------------------------------
# LAW_OF_ONE tooth: FloorValue ordering defaults never mint PredicateValue
# ---------------------------------------------------------------------------


def _floor_value_path() -> Path:
    return (
        Path(__file__).resolve().parents[1]
        / "src"
        / "sugar_lift_py_tests"
        / "floor"
        / "floor_value.py"
    )


def test_law_of_one_auditor_cannot_see_ordering_floor_meaning_sin() -> None:
    """LOUD: repository LAW_OF_ONE auditor is SourceFile-owner scoped only.

    It does not AST-walk floor ordering doors for Complete(PredicateValue).
    This package tooth is the instrument for that axis until the auditor
    gains a floor-meaning denominator — do not pretend the shared auditor
    closed this sin.
    """
    auditor = Path(__file__).resolve().parents[4] / "tests" / "law_of_one_auditor.py"
    assert auditor.is_file(), "law_of_one_auditor.py must exist"
    text = auditor.read_text(encoding="utf-8")
    assert "less_than_from_left" not in text
    assert "resolve_comparison_atom" not in text
    assert "PredicateValue" not in text
    assert "SourceFile" in text


def test_floor_value_ordering_defaults_never_mint_predicate_complete() -> None:
    """AST tooth: FloorValue ordering methods must not call resolve_comparison_atom
    or construct Complete(PredicateValue(...)).
    """
    tree = ast.parse(_floor_value_path().read_text(encoding="utf-8"))
    offenders: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != "FloorValue":
            continue
        for item in node.body:
            if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if item.name not in _ORDERING_METHODS:
                continue
            for child in ast.walk(item):
                if isinstance(child, ast.Name) and child.id == "resolve_comparison_atom":
                    offenders.append(f"{item.name}:{child.lineno}:resolve_comparison_atom")
                if isinstance(child, ast.Call):
                    func = child.func
                    if isinstance(func, ast.Name) and func.id == "Complete":
                        # Complete(...) inside ordering door is the FOL invent shape
                        # when its argument is PredicateValue — ban any Complete mint
                        # on the default doors (ground arms live on subclasses).
                        offenders.append(f"{item.name}:{child.lineno}:Complete(...)")
                    if isinstance(func, ast.Name) and func.id == "PredicateValue":
                        offenders.append(f"{item.name}:{child.lineno}:PredicateValue(...)")
                    if isinstance(func, ast.Attribute) and func.attr == "PredicateValue":
                        offenders.append(
                            f"{item.name}:{child.lineno}:…PredicateValue(...)"
                        )
    assert not offenders, (
        "LAW_OF_ONE floor-meaning sin R_ordering_default_predicate_mint="
        f"{len(offenders)}:\n" + "\n".join(offenders)
    )


# ---------------------------------------------------------------------------
# Ordering floor: undecided → named throw; decided ground → construct Sugar
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method",
    ("less_than", "less_equal", "greater_than", "greater_equal"),
)
def test_undecided_ordering_operand_throws_named_never_complete(method: str) -> None:
    """Truthful: undecided left never becomes Complete(PredicateValue)."""
    left = _symbolic()
    right = TermValue(1)
    with pytest.raises(SugarNotWritten) as raised:
        getattr(left, method)(right, SITE)
    assert "undecided" in raised.value.observed.lower()
    assert "ordering" in raised.value.observed.lower() or "ordering" in (
        raised.value.requested or ""
    ).lower()


@pytest.mark.parametrize(
    "method",
    ("less_than", "less_equal", "greater_than", "greater_equal"),
)
def test_undecided_ordering_callsite_throws_named(method: str) -> None:
    with pytest.raises(SugarNotWritten):
        getattr(_callsite(), method)(TermValue(0), SITE)


def _relative_fragment(source: str, filename: str):
    """Workspace-relative fragment so ground exits can re-read source."""
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_source_tree.nodes import Compare, BinOp
    from sugar_source_tree.tree import SourceFile

    tree = SourceFile(
        (source, filename, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    for node in tree.nodes():
        if isinstance(node, (Compare, BinOp)):
            return node.fragment
    raise AssertionError(f"no Compare/BinOp in {filename!r}")


def test_source_decided_number_string_ordering_emits_type_error() -> None:
    """Truthful twin: decided unorderable pair constructs TypeError RaiseValue."""
    from sugar_lift_py_tests.floor import RaiseValue

    site = _relative_fragment('def f():\n    return 1.0 < "a"\n', "number-lt-string.py")
    outcome = TermValue(1.0).less_than(StringValue("a"), site)
    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, RaiseValue)
    assert outcome.value.effect.exception_name == "TypeError"


def test_source_decided_int_ordering_constructs_bool_sugar() -> None:
    """Truthful twin: two decided numbers construct TrueBoolLiteralSugar."""
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    outcome = TermValue(1).less_than(TermValue(2), SITE)
    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, TrueBoolLiteralSugar)


def test_decided_default_pair_without_sugar_arm_throws_named() -> None:
    """LAW_OF_ONE: decided types with no ground arm refuse — no FOL invent."""
    from sugar_lift_py_tests.floor.list_value import ListValue

    # ListValue has no ordering arm; both types are source-decided.
    with pytest.raises(SugarNotWritten) as raised:
        ListValue((TermValue(1),)).less_than(ListValue((TermValue(2),)), SITE)
    assert "LAW_OF_ONE" in (raised.value.fix or "")
    assert "Complete(PredicateValue)" in (raised.value.fix or "")


def test_lying_complete_predicate_is_not_ordering_meaning() -> None:
    """Lying twin: Complete(PredicateValue) is never the ordering answer."""
    from sugar_lift_py_tests.floor.predicate_value import PredicateValue

    with pytest.raises(SugarNotWritten):
        outcome = _symbolic().less_than(TermValue(1), SITE)
        assert not isinstance(getattr(outcome, "value", None), PredicateValue)
        raise AssertionError(
            "ordering floor returned a value; must throw named (LAW_OF_ONE)"
        )


# ---------------------------------------------------------------------------
# Undecided binary: throw named — never nameless dual-edge halt
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "method",
    (
        "add",
        "subtract",
        "multiply",
        "divide",
        "bitwise_and",
    ),
)
def test_undecided_binary_throws_named_never_nameless_halt(method: str) -> None:
    """Nameless Halted faces route outside TypeError boundaries — refuse instead."""
    with pytest.raises(SugarNotWritten) as raised:
        getattr(_symbolic(), method)(TermValue(2), SITE)
    owner = raised.value.owner or ""
    observed = raised.value.observed or ""
    assert "binary" in owner.lower() or "undecided" in observed.lower()
    # Must not look like a completed dual-edge partition.
    assert "TypeError" not in observed  # do not invent exception identity


def test_source_decided_int_float_bitand_emits_type_error() -> None:
    """Truthful twin: decided ground pair still constructs TypeError."""
    from sugar_lift_py_tests.floor import RaiseValue

    site = _relative_fragment("def f():\n    return 1 & 3.14\n", "int-bitand-float.py")
    outcome = TermValue(1).bitwise_and(TermValue(3.14), site)
    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, RaiseValue)
    assert outcome.value.effect.exception_name == "TypeError"


def test_lying_dual_edge_is_not_undecided_binary_answer() -> None:
    """Lying twin: dual-edge ExitSet with nameless RaiseEffect must not appear."""
    from sugar_lift_py_tests.outcome import ExitSet
    from sugar_lift_py_tests.outcome.exit_set import Halted

    with pytest.raises(SugarNotWritten):
        outcome = _symbolic().subtract(TermValue(1), SITE)
        if isinstance(outcome, ExitSet):
            for face in outcome.exits:
                if isinstance(face, Halted) and getattr(
                    face.effect, "exception_name", "missing"
                ) is None:
                    raise AssertionError(
                        "nameless binary halt is the SIN: TypeError boundary "
                        "can never match it"
                    )
        raise AssertionError("undecided binary must throw named, not return")


# ---------------------------------------------------------------------------
# Undecided contains / attribute
# ---------------------------------------------------------------------------


def test_undecided_contains_is_named_refusal_not_complete_or_panic() -> None:
    """Membership over an undecided container is a third value, not our defect.

    construction_panic would count this as a missing Floor arm (OUR bug).
    Complete(py.in) fabricates membership. Named refusal is honest.
    """
    from sugar_lift_py_tests.gap.panic import ConstructionPanic

    with pytest.raises(SugarNotWritten) as raised:
        _symbolic().contains(TermValue(1), SITE)
    assert "membership" in (raised.value.requested or "").lower() or "contain" in (
        raised.value.observed or ""
    ).lower()
    # Not a construction panic harness failure.
    assert not isinstance(raised.value, ConstructionPanic)


def test_undecided_callsite_contains_is_named_refusal() -> None:
    with pytest.raises(SugarNotWritten):
        _callsite().contains(TermValue(1), SITE)


def test_undecided_attribute_remains_named_refusal() -> None:
    """Attribute over undecided receiver stays SugarNotWritten (already correct)."""
    with pytest.raises(SugarNotWritten) as raised:
        _symbolic().attribute("x", SITE)
    assert raised.value.owner == "SymbolicValue.attribute"
    assert "undecided" in raised.value.observed


def test_source_decided_none_contains_emits_type_error() -> None:
    """Truthful twin: decided non-container constructs TypeError."""
    from sugar_lift_py_tests.floor import RaiseValue

    site = _relative_fragment("def f():\n    return 1 in None\n", "in-none.py")
    outcome = NoneValue().contains(TermValue(1), site)
    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, RaiseValue)
    assert outcome.value.effect.exception_name == "TypeError"
