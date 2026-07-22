from sugar_lift_py_tests.effect import RaiseEffect
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
        Halted(condition, effect),
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
        Halted(condition, effect),
        Completed(not_(condition), 2),
    )


def test_block_reduction_retains_complement_of_guarded_halt():
    condition = _guard("condition")
    effect = RaiseEffect(exception_name="ValueError")

    class GuardedHalt:
        def desugar(self):
            return Incomplete(effect).guarded(condition)

    exits = reduce_block_to_exitset((GuardedHalt(),))

    assert isinstance(exits.exits[0], Halted)
    assert exits.exits[0].guard == condition
    assert isinstance(exits.exits[1], Completed)
    assert exits.exits[1].guard == not_(condition)
