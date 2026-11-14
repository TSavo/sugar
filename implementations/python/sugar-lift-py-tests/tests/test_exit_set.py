from sugar_lift_py_tests.context_manager_contract import (
    EffectMatcher,
    NeverSuppresses,
    RuntimeSelected,
    Suppresses,
)
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.floor.call_site_value import ExitSuppressionContract
from sugar_lift_py_tests.ir import and_, atomic, make_var, not_, or_
from sugar_lift_py_tests.outcome.exit_set import (
    Completed,
    ExitSet,
    Halted,
    false_guard,
)
from sugar_lift_py_tests.sugar.function_universe_sugar import reduce_block_to_exitset


def _guard(name: str):
    return atomic(name, [make_var("state")])


def test_single_unconditional_completed_answers_its_completed_value():
    assert ExitSet.completed("state").completed_value() == "state"


def test_single_unconditional_halted_is_one_halted_arm():
    effect = RaiseEffect.for_builtin(
        "ValueError",
        occurrence="implementations/python/sugar-lift-py-tests/tests/test_exit_set.py:209:0",
    )

    halted = ExitSet.halted(effect)
    assert len(halted.exits) == 1 and halted.halts() == halted.exits
    assert [h.effect for h in halted.halts()] == [effect]
    assert halted.completed_value() is None


def test_conditional_halt_keeps_halted_and_complementary_completed_exits():
    condition = _guard("condition")
    effect = RaiseEffect.for_builtin(
        "ValueError",
        occurrence="implementations/python/sugar-lift-py-tests/tests/test_exit_set.py:198:0",
    )

    exits = ExitSet.conditional_halt(condition, effect, "state")

    assert exits.exits == (
        Halted(condition, effect, "state"),
        Completed(not_(condition), "state"),
    )
    assert exits.completed_value() is None


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
    effect = RaiseEffect.for_builtin(
        "ValueError",
        occurrence="implementations/python/sugar-lift-py-tests/tests/test_exit_set.py:173:0",
    )
    exits = ExitSet.conditional_halt(condition, effect, 1)

    sequenced = exits.sequence(lambda value: ExitSet.completed(value + 1))

    assert sequenced.exits == (
        Halted(condition, effect, 1),
        Completed(not_(condition), 2),
    )


def test_block_reduction_retains_complement_of_guarded_halt():
    condition = _guard("condition")
    effect = RaiseEffect.for_builtin(
        "ValueError",
        occurrence="implementations/python/sugar-lift-py-tests/tests/test_exit_set.py:165:0",
    )

    class GuardedHalt:
        def desugar(self, ctx=None):
            del ctx
            return ExitSet.halted(effect).guarded(condition)

    exits = reduce_block_to_exitset((GuardedHalt(),))

    assert isinstance(exits.exits[0], Halted)
    assert exits.exits[0].guard == condition
    assert isinstance(exits.exits[1], Completed)
    assert exits.exits[1].guard == not_(condition)


def test_and_finally_cleanup_completion_restores_incoming_completed():
    incoming = ExitSet.completed("try-state")
    after = incoming.and_finally(lambda: ExitSet.completed("cleanup-done"))
    assert after == ExitSet.completed("try-state")


def test_and_finally_cleanup_completion_restores_incoming_halted():
    effect = RaiseEffect.for_builtin(
        "ValueError",
        occurrence="implementations/python/sugar-lift-py-tests/tests/test_exit_set.py:131:0",
    )
    incoming = ExitSet.halted(effect)
    after = incoming.and_finally(lambda: ExitSet.completed("cleanup-done"))
    assert after == ExitSet.halted(effect)


def test_and_finally_cleanup_halt_supersedes_incoming():
    original = RaiseEffect.for_builtin(
        "ValueError",
        occurrence="implementations/python/sugar-lift-py-tests/tests/test_exit_set.py:106:0",
    )
    cleanup = RaiseEffect.for_builtin(
        "RuntimeError",
        occurrence="implementations/python/sugar-lift-py-tests/tests/test_exit_set.py:166:0",
    )
    incoming = ExitSet.halted(original)
    after = incoming.and_finally(lambda: ExitSet.halted(cleanup))
    assert after == ExitSet.halted(cleanup)


def test_and_finally_cleanup_halt_supersedes_completed():
    cleanup = RaiseEffect.for_builtin(
        "RuntimeError",
        occurrence="implementations/python/sugar-lift-py-tests/tests/test_exit_set.py:158:0",
    )
    incoming = ExitSet.completed("ok")
    after = incoming.and_finally(lambda: ExitSet.halted(cleanup))
    assert after == ExitSet.halted(cleanup)


def test_and_finally_terminal_cleanup_completion_supersedes():
    incoming = ExitSet.completed("try-state")
    after = incoming.and_finally(
        lambda: ExitSet.completed("return-from-finally"),
        cleanup_restores=lambda value: False,
    )
    assert after == ExitSet.completed("return-from-finally")


def test_and_finally_runs_cleanup_on_every_conditional_exit():
    condition = _guard("condition")
    effect = RaiseEffect.for_builtin(
        "ValueError",
        occurrence="implementations/python/sugar-lift-py-tests/tests/test_exit_set.py:99:0",
    )
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
    assert after == ExitSet.completed("body")


def test_and_exit_halt_supersedes_body_completed():
    exit_halt = RaiseEffect.for_builtin(
        "RuntimeError",
        occurrence="implementations/python/sugar-lift-py-tests/tests/test_exit_set.py:114:0",
    )
    incoming = ExitSet.completed("body")
    after = incoming.and_exit(ExitSet.halted(exit_halt), disposition=NeverSuppresses())
    assert after == ExitSet.halted(exit_halt)


def test_and_exit_halt_supersedes_body_halted():
    body = RaiseEffect.for_builtin(
        "ValueError",
        occurrence="implementations/python/sugar-lift-py-tests/tests/test_exit_set.py:77:0",
    )
    exit_halt = RaiseEffect.for_builtin(
        "RuntimeError",
        occurrence="implementations/python/sugar-lift-py-tests/tests/test_exit_set.py:107:0",
    )
    incoming = ExitSet.halted(body)
    after = incoming.and_exit(ExitSet.halted(exit_halt), disposition=NeverSuppresses())
    assert after == ExitSet.halted(exit_halt)


def test_and_exit_never_suppresses_restores_body_halt():
    body = RaiseEffect.for_builtin(
        "ValueError",
        occurrence="implementations/python/sugar-lift-py-tests/tests/test_exit_set.py:64:0",
    )
    incoming = ExitSet.halted(body)
    after = incoming.and_exit(ExitSet.completed(False), disposition=NeverSuppresses())
    assert after == ExitSet.halted(body)


def test_and_exit_proven_contract_consumes_named_halt():
    from sugar_lift_py_tests.floor.ground_exit import _builtin_exception_identity

    _, mro = _builtin_exception_identity("ValueError")
    body = RaiseEffect.for_builtin(
        "ValueError",
        exception_type_mro=mro,
        occurrence="exit_set.py:2:0",
    )
    incoming = ExitSet.halted(body)
    after = incoming.and_exit(
        ExitSet.completed(True),
        disposition=ExitSuppressionContract.suppresses(("ValueError",)),
    )
    assert after == ExitSet.completed(None)


def test_and_exit_runtime_selected_leaves_open_residual_not_guessed():
    body = RaiseEffect.for_builtin(
        "ValueError",
        occurrence="implementations/python/sugar-lift-py-tests/tests/test_exit_set.py:36:0",
    )
    incoming = ExitSet.halted(body)
    after = incoming.and_exit(
        ExitSet.completed(True),
        disposition=RuntimeSelected(),
    )
    assert after == ExitSet.halted(body)


def test_and_exit_fans_exitset_across_conditional_faces():
    condition = _guard("condition")
    effect = RaiseEffect.for_builtin(
        "ValueError",
        occurrence="implementations/python/sugar-lift-py-tests/tests/test_exit_set.py:29:0",
    )
    incoming = ExitSet.conditional_halt(condition, effect, "state")
    exit_es = ExitSet.completed(False)
    after = incoming.and_exit(exit_es, disposition=NeverSuppresses())
    assert any(isinstance(e, Halted) and e.effect == effect for e in after.exits)
    assert any(isinstance(e, Completed) and e.value == "state" for e in after.exits)


def test_and_exit_proven_contract_suppresses_only_matching_face():
    from sugar_lift_py_tests.floor.ground_exit import _builtin_exception_identity

    condition = _guard("condition")
    _, mro = _builtin_exception_identity("ValueError")
    effect = RaiseEffect.for_builtin(
        "ValueError",
        exception_type_mro=mro,
        occurrence="exit_set.py:3:0",
    )
    incoming = ExitSet.conditional_halt(condition, effect, "state")
    after = incoming.and_exit(
        ExitSet.completed(True),
        disposition=ExitSuppressionContract.suppresses(("ValueError",)),
    )
    assert after == ExitSet.completed("state")


def test_and_exit_membrane_suppresses_matcher_authority():
    from sugar_lift_py_tests.floor.ground_exit import _builtin_exception_identity

    _, mro = _builtin_exception_identity("KeyError")
    body = RaiseEffect.for_builtin(
        "KeyError",
        exception_type_mro=mro,
        occurrence="exit_set.py:1:0",
    )
    incoming = ExitSet.halted(body)
    after = incoming.and_exit(
        ExitSet.completed(True),
        disposition=Suppresses(EffectMatcher(kind="raise", name="KeyError")),
    )
    assert after == ExitSet.completed(None)


def test_sequence_consumes_an_owned_halt_beneath_its_guard_and_debts():
    """A halt the composition owns continues exactly as a completed arm does."""
    owned = RaiseEffect.for_builtin("StopIteration", occurrence="exit_set.py:2:0")
    foreign = RaiseEffect.for_builtin("ValueError", occurrence="exit_set.py:3:0")
    stop_guard = _guard("stop")
    after_guard = _guard("after")
    prefix = ExitSet(
        (
            Halted(stop_guard, owned, None, owed=("stop-debt",)),
            Halted(_guard("foreign"), foreign, None, owed=("foreign-debt",)),
        )
    )
    after = ExitSet((Completed(after_guard, "after", owed=("after-debt",)),))

    result = prefix.sequence(
        ExitSet.completed,
        consume=lambda halt: after if halt.effect is owned else None,
    )

    (continued,) = [arm for arm in result.exits if isinstance(arm, Completed)]
    assert continued.value == "after"
    assert continued.guard == and_([stop_guard, after_guard])
    assert continued.owed == ("stop-debt", "after-debt")
    (stood,) = result.halts()
    assert stood.effect is foreign
    assert stood.owed == ("foreign-debt",)
