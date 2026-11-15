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
6. A display is DECIDABLE and binds the members already in hand, rather than
   falling to the runtime arm. This is the half that makes law 5 a routing
   decision instead of a blanket red. A call of a same-file function is no
   display: it is its coordinate and edge, joined at prove (#7757 steps 5 and
   6, #8705), so its result is unpacked by law 5 like any callsite's.
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
#
# The ``if`` arm is the display ``(p, q)`` itself.  It used to be ``pair(p, q)``
# with ``def pair(p, q): return p, q``, whose body the call applied; a same-file
# call is now its coordinate and edge (#7757 steps 5 and 6, #8705), so its
# result is a callsite unpacked at runtime (law 5) and the arm would owe an
# unpack of its own.  The display keeps the law under test: only the ``else``
# arm is a runtime unpack.
GUARDED_SYMBOLIC_ELSE = "def A(c, p, q):\n    a, b = ((p, q) if c else p)\n    return a\n"


def _discharged_on_an_undecided_condition(tmp_path: Path, source: str, stem: str):
    """``... if c else ...`` on a formal ``c`` waits for the caller's actual to
    answer ``bool(c)`` (``NativeOperationExitCarrierV1``, operator ``truth``),
    as the statement form does: the function alone is never a completion.
    The caller hands a value nothing decides, whose truth is ``py.truthy(c)``;
    the arms join under that formula."""
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )
    from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue

    carrier = _outcome(tmp_path, source, stem)
    assert isinstance(carrier, NativeOperationExitCarrierV1), type(carrier)
    assert carrier.demand.operator == "truth"
    (condition,) = carrier.demand.operand_coordinate_cids
    return carrier.discharge(None, {condition: SymbolicValue(make_var("c"))})


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


def _conjuncts(guard) -> set:
    """Every conjunct of ``guard``, nested conjunctions flattened."""
    operands = getattr(guard, "operands", None)
    if getattr(guard, "kind", None) == "and" and operands is not None:
        return {conjunct for operand in operands for conjunct in _conjuncts(operand)}
    return {guard}


def test_guarded_arm_effect_rides_the_branch_guard(tmp_path: Path) -> None:
    """The retained demand is owed on a FACE, not unconditionally.

    The block reduction lifts each guarded arm's effect into a partition, so
    the observable artifact is an ExitSet whose halted arms carry the typed
    unpack effect under its own branch's formula (conjoined with the
    complement of that arm's completes atom).

    Only the ``else`` arm is a runtime unpack: ``p``, a value no caller has
    supplied.  The ``if`` arm is the display ``(p, q)``, and a 2-tuple
    always unpacks into two names -- Python never raises there, so no
    unpack halt is owed on that arm (law 6).  The one halt rides
    ``not py.truthy(c)``, never ``py.truthy(c)``.
    """
    from sugar_lift_py_tests.ir import not_

    outcome = _discharged_on_an_undecided_condition(
        tmp_path, GUARDED_SYMBOLIC_ELSE, "guarded_else"
    )
    halted = _halted_unpack_exits(outcome)
    assert len(halted) == 1, outcome
    (halt,) = halted
    conjuncts = _conjuncts(halt.guard)
    assert not_(GUARD) in conjuncts, halt.guard
    assert GUARD not in conjuncts, halt.guard
    # Both arms complete on their faces: the halts never claim every exit.
    assert len(outcome.halts()) < len(outcome.exits), outcome


def test_guarded_arm_effect_is_not_owed_unconditionally(tmp_path: Path) -> None:
    """Discrimination for the law above: the guard is the branch's, not true.

    An implementation that dropped the arm's guard would owe the unpack on
    every path. `true_guard()` is what "unguarded" looks like in this algebra,
    so naming it here is what makes the assertion above load-bearing.
    """
    from sugar_lift_py_tests.outcome import true_guard

    halted = _halted_unpack_exits(
        _discharged_on_an_undecided_condition(
            tmp_path, GUARDED_SYMBOLIC_ELSE, "guarded_else"
        )
    )
    assert halted, "the guarded arms' unpack halts were dropped"
    assert all(halt.guard != true_guard() for halt in halted)


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
    """``o.copy()`` on a formal whose class is the function's ``class:o``
    input is the dispatched call (#7757 step 8): its coordinate and edge,
    whichever class a caller binds at prove.  The function alone is never a
    completion of it: the call is the callsite the unpack reads."""
    from sugar_lift_py_tests.outcome import ExitSet

    outcome = _outcome(tmp_path, source, stem)
    assert isinstance(outcome, ExitSet), type(outcome)
    return outcome


def test_callsite_rhs_retains_the_typed_unpack_obligation(tmp_path: Path) -> None:
    outcome = _discharged_at_an_opaque_receiver(
        tmp_path, OPAQUE_CALL_TWO, "callsite_two"
    )
    halt = _callsite_unpack_halt(outcome)
    assert isinstance(halt.effect, UndeterminedRaiseEffect), halt.effect
    assert halt.effect.exception_type_coordinate is None
    # The obligation names the CALLSITE's own term, not a fabricated element.
    assert "python:unpack.destructure" in str(halt.guard)
    assert "call:dispatch:copy" in str(halt.guard)


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


def test_a_same_file_call_rhs_is_a_callsite_unpack(tmp_path: Path) -> None:
    """Law 5 for a call of a function defined in this file.

    ``pair`` returns the display ``p, q``.  This used to be law 6: the call
    applied ``pair``'s body, its return floored to the display, and ``A``
    completed with no halt.  A same-file call is now its coordinate and edge,
    joined at prove (#7757 steps 5 and 6, the owner's ruling "Edge, join at
    prove", #8705): the lifter never reads ``pair``'s body at the call, so the
    unpack retains its obligation over the call's own term, and whether it
    can raise is decided at prove, where ``pair``'s contract joins the edge.
    The call's own halt (the unanswered call's complement face) stands
    beside it.

    The obligation is read off the guard's terms, never its ``repr`` (which
    elides long terms): the unpack destructures the call's result,
    ``python:call_result(call:<target>(p, q), <occurrence>)`` (#7808,
    #8753), whose call term carries ``A``'s formals as written.
    """
    from sugar_lift_py_tests.ir import make_var

    source = (
        "def pair(p, q):\n"
        "    return p, q\n"
        "\n"
        "def A(p, q):\n"
        "    a, b = pair(p, q)\n"
        "    return a\n"
    )
    outcome = _outcome(tmp_path, source, "callsite_display")
    halt = _callsite_unpack_halt(outcome)
    assert halt.effect.exception_type_coordinate is None
    destructures = [
        term
        for term in _guard_terms(halt.guard)
        if getattr(term, "name", None) == "python:unpack.destructure"
    ]
    assert destructures, halt.guard
    operands = {destructure.args[0] for destructure in destructures}
    assert len(operands) == 1, operands
    (result,) = operands
    assert result.name == "python:call_result", result
    call = result.args[0]
    assert call.name.startswith("call:"), call
    assert list(call.args[:2]) == [make_var("p"), make_var("q")], call


def _guard_terms(formula) -> list:
    """Every term under ``formula``'s atoms, nested terms included."""
    found = []
    stack = [formula]
    while stack:
        item = stack.pop()
        operands = getattr(item, "operands", None)
        if operands is not None:
            stack.extend(operands)
            continue
        args = getattr(item, "args", None)
        if args is None:
            continue
        if not hasattr(item, "kind"):
            found.append(item)
        stack.extend(args)
    return found
