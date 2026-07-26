"""``a, b = <non-display rhs>``: the unpack demand submitted to the RHS value.

Python's unpacking assignment materializes the right-hand side and demands
EXACTLY the arity the target spells, binding only after that demand is met.
These twins name that law and assert the constructed artifact carrying it, each
paired with a discriminating arm that fails when the law is violated:

1. The arity submitted IS the target count -- two targets and three targets
   construct different obligations.
2. The RHS is REDUCED before the unpack; its reduced term is what the
   obligation names. Two different RHS expressions project differently.
3. Unauthenticated cardinality retains the typed
   ``SequenceUnpackRuntimeEffect``; it never completes with invented members.
4. Nothing binds on that arm -- a later read of a target is not satisfied by a
   fabricated value. The discriminating arm is a display unpack, which DOES
   bind, so this is not "everything is red".
5. Authenticated finite members bind POSITIONALLY, member-by-member, to the
   values already in hand (asserted at the layer that owns the members: the
   projection operation and the ``ScopeRebinds`` it constructs).
6. A DECIDABLE arity mismatch stays loud -- the exact ``ValueError`` exit is
   unwritten, so it panics rather than guessing an exit or a member.
7. A floor value with no ``project_sequence_with`` stays loud, naming the
   frontier (``TupleValue`` / ``ListValue`` / ``CallSiteValue``) instead of
   silently succeeding.

Arm/outcome structure is read through ``outcome_to_exitset``; this module reads
arms, it does not claim how many exits the control algebra has.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from sugar_lift_py_tests.effect import SequenceUnpackRuntimeEffect
from sugar_lift_py_tests.floor.array_literal import ArrayLiteral
from sugar_lift_py_tests.floor.scope_rebind import ScopeRebinds
from sugar_lift_py_tests.floor.term_value import TermValue
from sugar_lift_py_tests.floor.tuple_literal_value import TupleLiteralValue
from sugar_lift_py_tests.operations import SequenceProjectionOperation
from sugar_lift_py_tests.outcome import Complete, Incomplete
from sugar_lift_py_tests.sugar.dynamic_unpack_assign_sugar import (
    DynamicUnpackAssignSugar,
)
from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_source_tree.tree import SourceFile


def _function_sugar(tmp_path: Path, source: str, stem: str):
    path = tmp_path / f"{stem}.py"
    path.write_text(source, encoding="utf-8")
    functions = list(SourceFile(path_source(str(path))).functions())
    return functions[-1].sugar()


def _statement(tmp_path: Path, source: str, stem: str):
    sugar = _function_sugar(tmp_path, source, stem)
    return next(
        statement
        for statement in sugar.statements
        if isinstance(statement, DynamicUnpackAssignSugar)
    )


def _outcome(tmp_path: Path, source: str, stem: str):
    return _function_sugar(tmp_path, source, stem).desugar(None)


def _unpack_effect(tmp_path: Path, source: str, stem: str):
    outcome = _outcome(tmp_path, source, stem)
    assert isinstance(outcome, Incomplete), outcome
    effect = outcome.effect
    assert isinstance(effect, SequenceUnpackRuntimeEffect), effect
    return effect


def _obligation(tmp_path: Path, source: str, stem: str) -> tuple[str, str, str]:
    """Site-free projection of the retained unpack obligation.

    (effect class, reason without site, the constructed operation term). Any
    change of arity, of RHS coordinate, or of target roster must move this.
    """
    effect = _unpack_effect(tmp_path, source, stem)
    return (
        type(effect).__name__,
        re.sub(r" site=.*$", "", effect.reason),
        str(effect.witness.operation),
    )


TWO_TARGETS = "def A(o, v):\n    a, b = o\n    return v\n"
THREE_TARGETS = "def A(o, v):\n    a, b, c = o\n    return v\n"
OTHER_RHS = "def A(o, v):\n    a, b = v\n    return v\n"
ATTRIBUTE_RHS = "def A(o, v):\n    a, b = o.shape\n    return v\n"
OTHER_ATTRIBUTE_RHS = "def A(o, v):\n    a, b = o.size\n    return v\n"


# ---------------------------------------------------------------------------
# Law 1 -- the arity submitted is the target count.
# ---------------------------------------------------------------------------


def test_target_count_is_the_submitted_arity(tmp_path: Path) -> None:
    two = _statement(tmp_path, TWO_TARGETS, "two")
    three = _statement(tmp_path, THREE_TARGETS, "three")
    assert two.target_names == ("a", "b")
    assert three.target_names == ("a", "b", "c")

    two_obligation = _obligation(tmp_path, TWO_TARGETS, "two")
    three_obligation = _obligation(tmp_path, THREE_TARGETS, "three")
    assert "exactly 2 members" in two_obligation[1]
    assert "exactly 3 members" in three_obligation[1]
    # Discrimination: a different arity is a different obligation term, not the
    # same term with different prose.
    assert two_obligation[2] != three_obligation[2]
    assert two_obligation[2].count("ConstInt") == 1


def test_target_roster_is_retained(tmp_path: Path) -> None:
    """The names the unpack must satisfy are named, in order."""
    reason = _obligation(tmp_path, TWO_TARGETS, "two")[1]
    assert "targets (a, b)" in reason
    assert "targets (b, a)" not in reason


# ---------------------------------------------------------------------------
# Law 2 -- the RHS is reduced first, and IS what the obligation names.
# ---------------------------------------------------------------------------


def test_reduced_rhs_is_the_unpacked_term(tmp_path: Path) -> None:
    same_arity_other_rhs = _obligation(tmp_path, OTHER_RHS, "other_rhs")
    two = _obligation(tmp_path, TWO_TARGETS, "two")
    # Same arity, same targets, different RHS coordinate: the obligation term
    # must differ, or the unpack is not naming what it unpacks.
    assert two[1] == same_arity_other_rhs[1]
    assert two[2] != same_arity_other_rhs[2]


def test_rhs_expression_is_reduced_not_quoted(tmp_path: Path) -> None:
    attribute = _obligation(tmp_path, ATTRIBUTE_RHS, "attr_rhs")
    other = _obligation(tmp_path, OTHER_ATTRIBUTE_RHS, "attr_rhs_other")
    # The reduced attribute coordinate rides in the obligation ...
    assert "shape" in attribute[2]
    # ... and a different attribute is a different obligation.
    assert attribute[2] != other[2]
    assert "shape" not in other[2]


# ---------------------------------------------------------------------------
# Law 3/4 -- runtime cardinality stays typed red, and binds nothing.
# ---------------------------------------------------------------------------


def test_runtime_cardinality_retains_the_typed_unpack_effect(tmp_path: Path) -> None:
    effect = _unpack_effect(tmp_path, TWO_TARGETS, "two")
    assert "no authenticated cardinality" in effect.reason
    assert "name='python:unpack.destructure'" in str(effect.witness.operation)


def test_nothing_binds_on_the_runtime_arm(tmp_path: Path) -> None:
    """A later read of a target is NOT satisfied by an invented member."""
    read_target = "def A(o):\n    a, b = o\n    return a\n"
    outcome = _outcome(tmp_path, read_target, "read_target")
    assert isinstance(outcome, Incomplete), outcome
    assert isinstance(outcome.effect, SequenceUnpackRuntimeEffect)

    # Discrimination: a display unpack DOES bind, and returns the paired
    # member -- so the assertion above is about this shape, not about
    # everything being red.
    display = "def A(p, q):\n    a, b = p, q\n    return a\n"
    display_outcome = _outcome(tmp_path, display, "display")
    assert isinstance(display_outcome, Complete), display_outcome
    assert "p" in str(display_outcome.value.record)
    assert "q" not in str(display_outcome.value.record)


# ---------------------------------------------------------------------------
# Law 5 -- authenticated finite members bind positionally.
# ---------------------------------------------------------------------------


def _operation(*names: str) -> SequenceProjectionOperation:
    return SequenceProjectionOperation(
        target_names=names, owner="twin", blame="twin-site"
    )


def test_authenticated_tuple_members_bind_positionally() -> None:
    members = (TermValue(1), TermValue(2))
    outcome = _operation("a", "b").submit(TupleLiteralValue(members), None)
    assert isinstance(outcome, Complete), outcome
    assert outcome.value == ScopeRebinds((("a", TermValue(1)), ("b", TermValue(2))))
    # Discrimination: the pairing is positional, not the reversed one, and not
    # the same member twice.
    assert outcome.value != ScopeRebinds((("a", TermValue(2)), ("b", TermValue(1))))
    assert outcome.value != ScopeRebinds((("a", TermValue(1)), ("b", TermValue(1))))


def test_authenticated_array_members_bind_positionally() -> None:
    members = (TermValue(7), TermValue(8), TermValue(9))
    outcome = _operation("a", "b", "c").submit(ArrayLiteral(members), None)
    assert isinstance(outcome, Complete), outcome
    assert outcome.value == ScopeRebinds(
        (("a", TermValue(7)), ("b", TermValue(8)), ("c", TermValue(9)))
    )


def test_bound_members_thread_to_the_rest_of_the_block() -> None:
    """The rebind is scope: later statements resolve the names it bound."""
    from sugar_lift_py_tests.context.reduce_context import ReduceContext
    from sugar_lift_py_tests.temporal.temporal_context import TemporalContext

    outcome = _operation("a", "b").submit(
        TupleLiteralValue((TermValue(1), TermValue(2))), None
    )
    ctx = outcome.value.extend_scope(ReduceContext(TemporalContext.empty()))
    assert ctx.temporal.value_if_bound("a") == TermValue(1)
    assert ctx.temporal.value_if_bound("b") == TermValue(2)
    # Discrimination: a name the unpack did not bind stays unbound.
    assert ctx.temporal.value_if_bound("c") is None


# ---------------------------------------------------------------------------
# Law 6 -- a decidable mismatch stays loud.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("members", "names", "relation"),
    [
        ((TermValue(1), TermValue(2)), ("a", "b", "c"), "not enough"),
        ((TermValue(1), TermValue(2), TermValue(3)), ("a", "b"), "too many"),
    ],
)
def test_decidable_arity_mismatch_stays_loud(members, names, relation) -> None:
    with pytest.raises(ConstructionPanic) as raised:
        _operation(*names).submit(TupleLiteralValue(members), None)
    info = raised.value.info
    assert relation in info.observed
    assert "ValueError" in info.requested
    assert str(len(members)) in info.observed
    assert str(len(names)) in info.observed


# ---------------------------------------------------------------------------
# Law 7 -- an unwritten floor stays loud, and names the frontier.
# ---------------------------------------------------------------------------


def test_unwritten_projection_floor_stays_loud(tmp_path: Path) -> None:
    """``a, b = xs[0]`` over a list display: ``ListValue`` has no unpack port.

    The members ARE authenticated here, so this is not an undecidable shape --
    it is an unwritten floor, and it says so. Next owner: the floor value's
    ``project_sequence_with``.
    """
    source = "def A(p, q, r, s):\n    xs = [[p, q], [r, s]]\n    a, b = xs[0]\n    return a\n"
    with pytest.raises(ConstructionPanic) as raised:
        _outcome(tmp_path, source, "list_floor")
    info = raised.value.info
    assert info.requested == "project_sequence_with"
    assert info.observed == "ListValue"
    assert info.owner == "DynamicUnpackAssignSugar"
