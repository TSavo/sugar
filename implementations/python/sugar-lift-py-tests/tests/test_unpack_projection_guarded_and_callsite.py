"""``a, b = <rhs>`` where the reduced RHS is a GuardedValue or a CallSiteValue.

``SequenceProjectionOperation`` has exactly two lawful answers -- authenticated
finite members, or a retained ``SequenceUnpackRuntimeEffect`` -- and tuple,
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

from sugar_lift_py_tests.effect import SequenceUnpackRuntimeEffect
from sugar_lift_py_tests.floor.guarded_value import GuardedValue
from sugar_lift_py_tests.floor.scope_rebind import ScopeRebinds
from sugar_lift_py_tests.floor.term_value import TermValue
from sugar_lift_py_tests.floor.tuple_literal_value import TupleLiteralValue
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.ir import atomic, make_var
from sugar_lift_py_tests.operations import SequenceProjectionOperation
from sugar_lift_py_tests.outcome import Complete, Incomplete
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile

GUARD = atomic("py.truthy", [make_var("c")])


def _operation(*names: str) -> SequenceProjectionOperation:
    return SequenceProjectionOperation(
        target_names=names, owner="twin", blame="twin-site"
    )


def _outcome(tmp_path: Path, source: str, stem: str):
    path = tmp_path / f"{stem}.py"
    path.write_text(source, encoding="utf-8")
    functions = list(SourceFile(path_source(str(path))).functions())
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
    assert isinstance(outcome, Complete), outcome
    assert outcome.value == ScopeRebinds(
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
    assert isinstance(outcome.value, ScopeRebinds), outcome.value
    for _, bound in outcome.value.bindings:
        assert not isinstance(bound, ScopeRebinds), bound


def test_guarded_rejoin_is_positional_within_and_across_arms() -> None:
    value = GuardedValue(
        GUARD,
        TupleLiteralValue((TermValue(1), TermValue(2))),
        TupleLiteralValue((TermValue(3), TermValue(4))),
    )
    bindings = dict(_operation("a", "b").submit(value, None).value.bindings)
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
    ctx = outcome.value.extend_scope(ReduceContext(TemporalContext.empty()))
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
    """The halted exits of a partition that carry the retained unpack demand."""
    from sugar_lift_py_tests.outcome.exit_set import Halted, outcome_to_exitset

    return [
        exit_
        for exit_ in outcome_to_exitset(outcome).exits
        if isinstance(exit_, Halted)
        and isinstance(exit_.effect, SequenceUnpackRuntimeEffect)
    ]


def test_guarded_arm_effect_rides_the_branch_guard(tmp_path: Path) -> None:
    """The retained demand is owed on a FACE, not unconditionally.

    The block reduction lifts the guarded arm's effect into a partition, so the
    observable artifact is an ExitSet whose halted arm carries the typed unpack
    effect under the branch's own formula.
    """
    outcome = _outcome(tmp_path, GUARDED_SYMBOLIC_ELSE, "guarded_else")
    halted = _halted_unpack_exits(outcome)
    assert len(halted) == 1, outcome
    assert halted[0].guard == GUARD


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


def test_callsite_rhs_retains_the_typed_unpack_obligation(tmp_path: Path) -> None:
    outcome = _outcome(tmp_path, OPAQUE_CALL_TWO, "callsite_two")
    assert isinstance(outcome, Incomplete), outcome
    effect = outcome.effect
    assert isinstance(effect, SequenceUnpackRuntimeEffect), effect
    assert "exactly 2 members" in effect.reason
    assert "no authenticated cardinality" in effect.reason
    # The obligation names the CALLSITE's own term, not a fabricated element.
    assert "call:copy" in str(effect.witness.operation)


def test_callsite_arity_is_the_target_count(tmp_path: Path) -> None:
    two = _outcome(tmp_path, OPAQUE_CALL_TWO, "callsite_two").effect
    three = _outcome(tmp_path, OPAQUE_CALL_THREE, "callsite_three").effect
    assert "exactly 2 members" in two.reason
    assert "exactly 3 members" in three.reason
    # Discrimination: a different arity is a different obligation TERM, not the
    # same term with different prose.
    assert str(two.witness.operation) != str(three.witness.operation)


def test_callsite_with_no_reachable_body_takes_the_opaque_arm(
    tmp_path: Path,
) -> None:
    """When the dig cannot fire, the answer is the obligation -- never a member.

    ``_dig_floor_or_none`` returns ``None`` as soon as ``self.body`` is absent,
    and this harness reduces with ``desugar(None)``, so no callee body is
    attached even for a function defined in the same file. That makes the
    opaque arm the one under test here.

    The decidable half -- a dug callee whose body floors to a display, binding
    the members already in hand -- is NOT exercised by this module, because
    this harness supplies no reduce context for the dig. It is stated in
    ``CallSiteValue.project_sequence_with`` and covered by the corpus run, not
    asserted here; claiming it from this fixture would be asserting a path the
    fixture never reaches.
    """
    source = (
        "def pair(p, q):\n"
        "    return p, q\n"
        "\n"
        "def A(p, q):\n"
        "    a, b = pair(p, q)\n"
        "    return a\n"
    )
    outcome = _outcome(tmp_path, source, "callsite_opaque")
    assert isinstance(outcome, Incomplete), outcome
    effect = outcome.effect
    assert isinstance(effect, SequenceUnpackRuntimeEffect), effect
    # The obligation names the callsite coordinate, not an invented element.
    assert "call:pair" in str(effect.witness.operation)
    assert "exactly 2 members" in effect.reason
