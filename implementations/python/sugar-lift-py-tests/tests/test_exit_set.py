from sugar_lift_py_tests.context_manager_contract import (
    EffectMatcher,
    NeverSuppresses,
    RuntimeSelected,
    Suppresses,
)
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.floor.call_site_value import ExitSuppressionContract
from sugar_lift_py_tests.ir import atomic, make_var, not_, or_
from sugar_lift_py_tests.outcome import Complete, Incomplete
from sugar_lift_py_tests.outcome.exit_set import (
    Completed,
    ExitSet,
    Halted,
    false_guard,
)
from sugar_lift_py_tests.sugar.function_universe_sugar import reduce_block_to_exitset


def _guard(name: str):
    return atomic(name, [make_var("state")])


def test_single_unconditional_completed_collapses_to_complete():
    assert ExitSet.completed("state").collapse() == Complete("state")


def test_single_unconditional_halted_collapses_to_incomplete():
    effect = RaiseEffect(exception_name="ValueError")

    assert ExitSet.halted(effect).collapse() == Incomplete(effect)


def test_conditional_halt_keeps_halted_and_complementary_completed_exits():
    condition = _guard("condition")
    effect = RaiseEffect(exception_name="ValueError")

    exits = ExitSet.conditional_halt(condition, effect, "state")

    assert exits.exits == (
        Halted(condition, effect, "state"),
        Completed(not_(condition), "state"),
    )
    assert exits.collapse() is exits


def test_union_normalize_merges_equal_exits_by_disjoining_their_guards():
    left = _guard("left")
    right = _guard("right")

    exits = ExitSet((Completed(left, "state"),)).union(
        ExitSet((Completed(right, "state"),))
    )

    assert exits.exits == (Completed(or_([left, right]), "state"),)


def test_normalize_drops_unsatisfiable_exit():
    assert ExitSet((Completed(false_guard(), "unreachable"),)).normalize().exits == ()


def test_sequencing_maps_only_completed_exits():
    condition = _guard("condition")
    effect = RaiseEffect(exception_name="ValueError")
    exits = ExitSet.conditional_halt(condition, effect, 1)

    sequenced = exits.sequence(lambda value: ExitSet.completed(value + 1))

    assert sequenced.exits == (
        Halted(condition, effect, 1),
        Completed(not_(condition), 2),
    )


def test_block_reduction_retains_complement_of_guarded_halt():
    condition = _guard("condition")
    effect = RaiseEffect(exception_name="ValueError")

    class GuardedHalt:
        def desugar(self, ctx=None):
            del ctx
            return Incomplete(effect).guarded(condition)

    exits = reduce_block_to_exitset((GuardedHalt(),))

    assert isinstance(exits.exits[0], Halted)
    assert exits.exits[0].guard == condition
    assert isinstance(exits.exits[1], Completed)
    assert exits.exits[1].guard == not_(condition)


def test_and_finally_cleanup_completion_restores_incoming_completed():
    incoming = ExitSet.completed("try-state")
    after = incoming.and_finally(lambda: ExitSet.completed("cleanup-done"))
    assert after.collapse() == Complete("try-state")


def test_and_finally_cleanup_completion_restores_incoming_halted():
    effect = RaiseEffect(exception_name="ValueError")
    incoming = ExitSet.halted(effect)
    after = incoming.and_finally(lambda: ExitSet.completed("cleanup-done"))
    assert after.collapse() == Incomplete(effect)


def test_and_finally_cleanup_halt_supersedes_incoming():
    original = RaiseEffect(exception_name="ValueError")
    cleanup = RaiseEffect(exception_name="RuntimeError")
    incoming = ExitSet.halted(original)
    after = incoming.and_finally(lambda: ExitSet.halted(cleanup))
    assert after.collapse() == Incomplete(cleanup)


def test_and_finally_cleanup_halt_supersedes_completed():
    cleanup = RaiseEffect(exception_name="RuntimeError")
    incoming = ExitSet.completed("ok")
    after = incoming.and_finally(lambda: ExitSet.halted(cleanup))
    assert after.collapse() == Incomplete(cleanup)


def test_and_finally_terminal_cleanup_completion_supersedes():
    incoming = ExitSet.completed("try-state")
    after = incoming.and_finally(
        lambda: ExitSet.completed("return-from-finally"),
        cleanup_restores=lambda value: False,
    )
    assert after.collapse() == Complete("return-from-finally")


def test_and_finally_runs_cleanup_on_every_conditional_exit():
    condition = _guard("condition")
    effect = RaiseEffect(exception_name="ValueError")
    incoming = ExitSet.conditional_halt(condition, effect, "state")
    seen = []

    def cleanup():
        seen.append(1)
        return ExitSet.completed("done")

    after = incoming.and_finally(cleanup)
    # cleanup invoked once per construction of cleanup ExitSet — and_finally
    # calls cleanup() once then fans the resulting exits across incoming.
    assert len(seen) == 1
    assert len(after.exits) == 2
    assert any(isinstance(e, Halted) and e.effect == effect for e in after.exits)
    assert any(isinstance(e, Completed) and e.value == "state" for e in after.exits)


# --- resource with: and_exit (typed disposition, ExitSet not callbacks) -----


def test_and_exit_completion_keeps_body_completed():
    incoming = ExitSet.completed("body")
    after = incoming.and_exit(ExitSet.completed(False), disposition=NeverSuppresses())
    assert after.collapse() == Complete("body")


def test_and_exit_halt_supersedes_body_completed():
    exit_halt = RaiseEffect(exception_name="RuntimeError")
    incoming = ExitSet.completed("body")
    after = incoming.and_exit(ExitSet.halted(exit_halt), disposition=NeverSuppresses())
    assert after.collapse() == Incomplete(exit_halt)


def test_and_exit_halt_supersedes_body_halted():
    body = RaiseEffect(exception_name="ValueError")
    exit_halt = RaiseEffect(exception_name="RuntimeError")
    incoming = ExitSet.halted(body)
    after = incoming.and_exit(ExitSet.halted(exit_halt), disposition=NeverSuppresses())
    assert after.collapse() == Incomplete(exit_halt)


def test_and_exit_never_suppresses_restores_body_halt():
    body = RaiseEffect(exception_name="ValueError")
    incoming = ExitSet.halted(body)
    after = incoming.and_exit(ExitSet.completed(False), disposition=NeverSuppresses())
    assert after.collapse() == Incomplete(body)


def test_and_exit_proven_contract_consumes_named_halt():
    body = RaiseEffect(exception_name="ValueError")
    incoming = ExitSet.halted(body)
    after = incoming.and_exit(
        ExitSet.completed(True),
        disposition=ExitSuppressionContract.suppresses(("ValueError",)),
    )
    assert after.collapse() == Complete(None)


def test_and_exit_runtime_selected_leaves_open_residual_not_guessed():
    body = RaiseEffect(exception_name="ValueError")
    incoming = ExitSet.halted(body)
    after = incoming.and_exit(
        ExitSet.completed(True),
        disposition=RuntimeSelected(),
    )
    assert after.collapse() == Incomplete(body)


def test_and_exit_fans_exitset_across_conditional_faces():
    condition = _guard("condition")
    effect = RaiseEffect(exception_name="ValueError")
    incoming = ExitSet.conditional_halt(condition, effect, "state")
    exit_es = ExitSet.completed(False)
    after = incoming.and_exit(exit_es, disposition=NeverSuppresses())
    assert any(isinstance(e, Halted) and e.effect == effect for e in after.exits)
    assert any(isinstance(e, Completed) and e.value == "state" for e in after.exits)


def test_and_exit_proven_contract_suppresses_only_matching_face():
    condition = _guard("condition")
    effect = RaiseEffect(exception_name="ValueError")
    incoming = ExitSet.conditional_halt(condition, effect, "state")
    after = incoming.and_exit(
        ExitSet.completed(True),
        disposition=ExitSuppressionContract.suppresses(("ValueError",)),
    )
    assert after.collapse() == Complete("state")


def test_and_exit_membrane_suppresses_matcher_authority():
    from sugar_lift_py_tests.floor.ground_exit import _builtin_exception_identity

    coordinate, mro = _builtin_exception_identity("KeyError")
    body = RaiseEffect(
        exception_name="KeyError",
        exception_type_coordinate=coordinate,
        exception_type_mro=mro,
        occurrence="exit_set.py:1:0",
    )
    incoming = ExitSet.halted(body)
    after = incoming.and_exit(
        ExitSet.completed(True),
        disposition=Suppresses(EffectMatcher(kind="raise", name="KeyError")),
    )
    assert after.collapse() == Complete(None)
