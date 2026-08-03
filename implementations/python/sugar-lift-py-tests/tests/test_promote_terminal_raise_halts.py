"""Terminal raise promotion must not invent a completed sibling arm."""

from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.outcome import (
    Completed,
    ExitSet,
    Halted,
    Incomplete,
    true_guard,
)
from sugar_lift_py_tests.sugar.exit_set_routing import promote_raise_halts
from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock


def test_terminal_raise_with_prior_state_promotes_to_halt_only():
    marker = object()
    effect = RaiseEffect.for_builtin(
        "OSError",
        occurrence="implementations/python/sugar-lift-py-tests/tests/test_promote_terminal_raise_halts.py:39:0",
    )
    exits = ExitSet(
        (
            Completed(
                true_guard(),
                _ReducedBlock((marker, Incomplete(effect)), False, ()),
            ),
        )
    )

    promoted = promote_raise_halts(exits)

    assert len(promoted.exits) == 1
    assert isinstance(promoted.exits[0], Halted)
    assert promoted.exits[0].effect is effect
    assert promoted.exits[0].state.entries == (marker,)


def test_guarded_raise_keeps_its_complementary_completed_arm():
    marker = object()
    condition = make_var("condition")
    effect = RaiseEffect.for_builtin(
        "OSError",
        occurrence="implementations/python/sugar-lift-py-tests/tests/test_promote_terminal_raise_halts.py:18:0",
    )
    exits = ExitSet(
        (
            Completed(
                true_guard(),
                _ReducedBlock(
                    (
                        marker,
                        Incomplete(effect, branch_conditions=(condition,)),
                    ),
                    True,
                    (),
                ),
            ),
        )
    )

    promoted = promote_raise_halts(exits)

    assert sum(isinstance(face, Halted) for face in promoted.exits) == 1
    assert sum(isinstance(face, Completed) for face in promoted.exits) == 1
