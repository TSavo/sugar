"""``a, b = <rhs>`` where the reduced RHS is a GuardedValue or a CallSiteValue.

``SequenceProjectionOperation`` has exactly two lawful answers -- authenticated
finite members, or a runtime unpack retaining an undetermined raise
(``UndeterminedRaiseEffect``) on one arm beside its completed projections --
and tuple,
array, symbolic, object and opaque coordinates all route to one of them. Two
value categories measured on the installed pandas tree had no arm at all and
panicked with ``requested='project_sequence_with'``: ``CallSiteValue`` (6 rows)
and ``GuardedValue`` (2 rows).

Each law below is paired with a discriminating arm that fails when the law is
violated, so a fix that merely stops the panic does not pass:

1. A guarded RHS distributes into BOTH arms and rejoins PER TARGET NAME. ``a``
   binds to the join of the two arms' first members. The crime this excludes is
   joining at the wrong layer -- one ``GuardedValue`` wrapping two whole
   ``ScopeRebinds``, which binds nothing a later statement can read.
2. The rejoin is positional inside each arm as well as across them: the arms'
   members are never transposed and never reused.
3. A guarded arm that answers with an effect keeps that arm's own guard
   polarity, exactly as every other ``GuardedValue`` distribution does. It does
   not become an unguarded effect, and it does not complete.
4. A decidable arity mismatch inside ONE arm is still loud. Distributing does
   not launder an arm's own gap.
5. A callsite RHS retains the typed unpack obligation over the CALLSITE'S OWN
   term -- the count belongs to ``__iter__`` at runtime and no member is
   invented. Discrimination: a different arity is a different obligation.
6. A callsite whose body floors to a display is DECIDABLE and binds the members
   already in hand, rather than falling to the runtime arm. This is the half
   that makes law 5 a routing decision instead of a blanket red.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor.guarded_value import GuardedValue
from sugar_lift_py_tests.floor.scope_rebind import ScopeRebinds
from sugar_lift_py_tests.floor.term_value import TermValue
from sugar_lift_py_tests.floor.tuple_literal_value import TupleLiteralValue
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.ir import atomic, make_var
from sugar_lift_py_tests.operations import SequenceProjectionOperation
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1

GUARD = atomic("py.truthy", [make_var("c")])


def _operation(*names: str) -> SequenceProjectionOperation:
    return SequenceProjectionOperation(
        target_names=names, owner="twin", blame="twin-site"
    )


def _outcome(tmp_path: Path, source: str, stem: str):
    path = tmp_path / f"{stem}.py"
    path.write_text(source, encoding="utf-8")
    functions = list(
        SourceFile(
            path_source(str(path)),
            construction_context=TreeConstructionContextV1.for_test_without_workspace(),
        ).functions()
    )
    return functions[-1].sugar().desugar(None)


# ---------------------------------------------------------------------------
# Laws 1 and 2 -- a guarded RHS rejoins per target name, positionally.
# ---------------------------------------------------------------------------


def test_guarded_rhs_rejoins_per_target_name() -> None:
    value = GuardedValue(
        GUARD,
        TupleLiteralValue((TermValue(1), TermValue(2))),
        TupleLiteralValue((TermValue(3), TermValue(4))),
    )
    outcome = _operation("a", "b").submit(value, None)
    assert outcome.completed_value() is not None, outcome
    assert outcome.completed_value() == ScopeRebinds(
        (
            ("a", GuardedValue(GUARD, TermValue(1), TermValue(3))),
            ("b", GuardedValue(GUARD, TermValue(2), TermValue(4))),
        )
    )


def test_guarded_rhs_does_not_join_at_the_rebinds_layer() -> None:
    """The crime: one GuardedValue wrapping two whole ScopeRebinds.

    That shape type-checks and stops the panic, but binds nothing -- a later
    statement reading ``a`` finds a GuardedValue of rebind records, not the
    joined member. Naming it here so the fix cannot take that shape.
    """
    value = GuardedValue(
        GUARD,
        TupleLiteralValue((TermValue(1), TermValue(2))),
        TupleLiteralValue((TermValue(3), TermValue(4))),
    )
    outcome = _operation("a", "b").submit(value, None)
    rebinds = outcome.completed_value()
    assert isinstance(rebinds, ScopeRebinds), outcome
    for _, bound in rebinds.bindings:
        assert not isinstance(bound, ScopeRebinds), bound


def test_guarded_rejoin_is_positional_within_and_across_arms() -> None:
    value = GuardedValue(
        GUARD,
        TupleLiteralValue((TermValue(1), TermValue(2))),
        TupleLiteralValue((TermValue(3), TermValue(4))),
    )
    bindings = dict(_operation("a", "b").submit(value, None).completed_value().bindings)
    # Discrimination: not transposed across arms, not the same member twice,
    # and not the arms' members swapped within one name.
    assert bindings["a"] != GuardedValue(GUARD, TermValue(3), TermValue(1))
    assert bindings["a"] != GuardedValue(GUARD, TermValue(1), TermValue(1))
    assert bindings["a"] != bindings["b"]


def test_guarded_rejoin_threads_to_the_rest_of_the_block() -> None:
    """The rebind is scope: the joined members are readable by name."""
    from sugar_lift_py_tests.context.reduce_context import ReduceContext
    from sugar_lift_py_tests.temporal.temporal_context import TemporalContext

    value = GuardedValue(
        GUARD,
        TupleLiteralValue((TermValue(1), TermValue(2))),
        TupleLiteralValue((TermValue(3), TermValue(4))),
    )
    outcome = _operation("a", "b").submit(value, None)
    ctx = outcome.completed_value().extend_scope(ReduceContext(TemporalContext.empty()))
    assert ctx.temporal.value_if_bound("a") == GuardedValue(
        GUARD, TermValue(1), TermValue(3)
    )
    # Discrimination: a name the unpack did not bind stays unbound.
    assert ctx.temporal.value_if_bound("c") is None


# ---------------------------------------------------------------------------
# Law 3 -- an arm that answers with an effect keeps that arm's polarity.
# ---------------------------------------------------------------------------


# These two are SOURCE-level on purpose. The runtime-cardinality answer mints a
# typed effect, and `RuntimeEffectWitness` refuses a stringly locus -- it demands
# the fragment that owns the boundary. A synthetic `blame="twin-site"` is exactly
# the reconstructed-evidence shape it exists to reject, so the arm has to come
# from real source rather than a hand-built operation.
GUARDED_SYMBOLIC_ELSE = (
    "def pair(p, q):\n"
    "    return p, q\n"
    "\n"
    "def A(c, p, q):\n"
    "    a, b = (pair(p, q) if c else p)\n"
    "    return a\n"
)


def _halted_unpack_exits(outcome):
    """The halted exits of a partition that carry the retained unpack demand:
    the runtime unpack's undetermined raise (``runtime_unpack_faces``), not
    another operation's (an opaque call's own raise is undetermined too)."""
    from sugar_lift_py_tests.outcome.exit_set import Halted

    return [
        exit_
        for exit_ in outcome.exits
        if isinstance(exit_, Halted)
        and isinstance(exit_.effect, UndeterminedRaiseEffect)
        and str(exit_.effect.producer_node_owner).endswith(".unpack")
    ]


def test_guarded_arm_effect_rides_the_branch_guard(tmp_path: Path) -> None:
    """The retained demand is owed on a FACE, not unconditionally.

    The block reduction lifts each guarded arm's effect into a partition, so
    the observable artifact is an ExitSet whose halted arms carry the typed
    unpack effect, each under its own branch's formula (conjoined with the
    complement of that arm's completes atom).  Both arms are runtime unpacks
    here, and neither arm's halt is dropped for the other's.
    """
    from sugar_lift_py_tests.ir import not_

    outcome = _outcome(tmp_path, GUARDED_SYMBOLIC_ELSE, "guarded_else")
    halted = _halted_unpack_exits(outcome)
    assert len(halted) == 2, outcome
    first, second = (set(getattr(h.guard, "operands", (h.guard,))) for h in halted)
    assert (GUARD in first and not_(GUARD) in second) or (
        GUARD in second and not_(GUARD) in first
    )


def test_guarded_arm_effect_is_not_owed_unconditionally(tmp_path: Path) -> None:
    """Discrimination for the law above: the guard is the branch's, not true.

    An implementation that dropped the arm's guard would owe the unpack on
    every path. `true_guard()` is what "unguarded" looks like in this algebra,
    so naming it here is what makes the assertion above load-bearing.
    """
    from sugar_lift_py_tests.outcome import true_guard

    halted = _halted_unpack_exits(
        _outcome(tmp_path, GUARDED_SYMBOLIC_ELSE, "guarded_else")
    )
    assert halted[0].guard != true_guard()


# ---------------------------------------------------------------------------
# Law 4 -- distributing does not launder one arm's decidable gap.
# ---------------------------------------------------------------------------


def test_guarded_arm_arity_mismatch_stays_loud() -> None:
    value = GuardedValue(
        GUARD,
        TupleLiteralValue((TermValue(1), TermValue(2))),
        TupleLiteralValue((TermValue(3),)),
    )
    with pytest.raises(ConstructionPanic) as raised:
        _operation("a", "b").submit(value, None)
    info = raised.value.info
    assert "not enough" in info.observed
    assert "ValueError" in info.requested


# ---------------------------------------------------------------------------
# Laws 5 and 6 -- a callsite RHS routes, it is not blanket red.
# ---------------------------------------------------------------------------


OPAQUE_CALL_TWO = "def A(o, v):\n    a, b = o.copy()\n    return v\n"
OPAQUE_CALL_THREE = "def A(o, v):\n    a, b, c = o.copy()\n    return v\n"


def _callsite_unpack_halt(outcome):
    """The retained unpack demand: one halted arm, beside the completed arm
    the runtime unpack never claims away."""
    (halt,) = _halted_unpack_exits(outcome)
    assert len(outcome.halts()) < len(outcome.exits), outcome
    return halt


def _discharged_at_an_opaque_receiver(tmp_path: Path, source: str, stem: str):
    """``o.copy()`` on a formal waits for the caller's actual to select the
    method (``NativeOperationExitCarrierV1``, operator ``method_call``): the
    function alone is never a completion.  The caller hands an opaque
    receiver; the call it selects is the callsite the unpack reads."""
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )
    from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue

    carrier = _outcome(tmp_path, source, stem)
    assert isinstance(carrier, NativeOperationExitCarrierV1), type(carrier)
    assert carrier.demand.operator == "method_call"
    (receiver, *_rest) = carrier.demand.operand_coordinate_cids
    return carrier.discharge(None, {receiver: SymbolicValue(make_var("o"))})


def test_callsite_rhs_retains_the_typed_unpack_obligation(tmp_path: Path) -> None:
    outcome = _discharged_at_an_opaque_receiver(
        tmp_path, OPAQUE_CALL_TWO, "callsite_two"
    )
    halt = _callsite_unpack_halt(outcome)
    assert isinstance(halt.effect, UndeterminedRaiseEffect), halt.effect
    assert halt.effect.exception_type_coordinate is None
    # The obligation names the CALLSITE's own term, not a fabricated element.
    assert "python:unpack.destructure" in str(halt.guard)
    assert "call:copy" in str(halt.guard)


def test_callsite_arity_is_the_target_count(tmp_path: Path) -> None:
    two = _callsite_unpack_halt(
        _discharged_at_an_opaque_receiver(tmp_path, OPAQUE_CALL_TWO, "callsite_two")
    )
    three = _callsite_unpack_halt(
        _discharged_at_an_opaque_receiver(
            tmp_path, OPAQUE_CALL_THREE, "callsite_three"
        )
    )
    # Discrimination: a different arity is a different obligation TERM.
    assert str(two.guard) != str(three.guard)


def test_callsite_whose_body_floors_to_a_display_binds_its_members(
    tmp_path: Path,
) -> None:
    """Law 6: ``pair`` is defined in the same file and returns the display
    ``p, q``, so ``a, b = pair(p, q)`` unpacks a 2-tuple into two targets.

    Python never raises there: a 2-tuple always unpacks into two names, and
    building it cannot raise.  The call binds ``pair``'s body (a same-file
    call is applied, step 6), its return floors to the display, and the
    unpack binds the members already in hand.  ``A`` is one completion under
    truth with no halt -- no unpack obligation is owed, because there is no
    raise for it to stand for.  The opaque arm (law 5) is the receiver the
    caller does not have: ``o.copy()`` above.
    """
    source = (
        "def pair(p, q):\n"
        "    return p, q\n"
        "\n"
        "def A(p, q):\n"
        "    a, b = pair(p, q)\n"
        "    return a\n"
    )
    outcome = _outcome(tmp_path, source, "callsite_display")
    assert outcome.halts() == ()
    assert outcome.completed_value() is not None, outcome
    assert "python:unpack.destructure" not in repr(outcome)
