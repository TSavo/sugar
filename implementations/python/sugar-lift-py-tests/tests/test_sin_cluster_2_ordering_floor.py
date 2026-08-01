"""SIN CLUSTER 2 — ordering floor must not fabricate a Complete value.

Doctrine: throwing is honorable (code not written yet). Half-writing an answer
outside the tree is the sin. Where operand types are source-decided, construct.
Where they are not, throw named — never ``Complete``.

Also covers:
- undecided binary: nameless halt is forbidden (boundary cannot match TypeError)
- undecided contains: named refusal, not ``Complete(py.in)`` or construction_panic
- undecided attribute: already named refusal; stays that way (not our defect)

GATE: truthful twin, lying twin that must fail, mutation transaction elsewhere.
"""

from __future__ import annotations

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


def _symbolic() -> SymbolicValue:
    return SymbolicValue(make_var("s"))


def _callsite() -> CallSiteValue:
    return CallSiteValue("unknown", (), (), ctor("call:unknown", []), None)


# ---------------------------------------------------------------------------
# Ordering floor: undecided → named throw; decided ground → construct
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


def test_source_decided_int_ordering_constructs_bool() -> None:
    """Truthful twin: two decided numbers fold to a bool completion."""
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    outcome = TermValue(1).less_than(TermValue(2), SITE)
    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, TrueBoolLiteralSugar)


def test_lying_complete_predicate_is_not_the_undecided_answer() -> None:
    """Lying twin: inventing Complete(py.lt) for undecided must be distinguishable.

    If the floor fabricates Complete, this test fails. The honorable answer is
    SugarNotWritten so no consumer can treat the row as green.
    """
    from sugar_lift_py_tests.floor.predicate_value import PredicateValue

    with pytest.raises(SugarNotWritten):
        outcome = _symbolic().less_than(TermValue(1), SITE)
        # If we reach here, the floor half-wrote an answer.
        assert not isinstance(outcome, Complete) or not isinstance(
            getattr(outcome, "value", None), PredicateValue
        )
        raise AssertionError(
            "ordering floor returned a value for undecided operands; "
            "must throw named instead of Complete"
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
