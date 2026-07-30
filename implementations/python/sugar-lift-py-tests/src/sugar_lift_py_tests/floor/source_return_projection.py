from __future__ import annotations

from .floor_value import FloorValue


def project_authenticated_source_return(value: FloorValue) -> FloorValue:
    """Project only the uniquely authenticated return from a source body.

    A block is control-flow testimony, not a semantic value.  It may be
    unwrapped only when reduction retained one unconditional returned Floor
    and no fall-through or competing control exit.  Every ambiguous or
    nonlinear block remains intact so its consumer stays loudly unpublishable.
    """
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.exceptional_exit_value import ExceptionalExitValue
    from sugar_lift_py_tests.floor.guarded_faces import GuardedFaces
    from sugar_lift_py_tests.floor.guarded_loop_control import GuardedLoopControl
    from sugar_lift_py_tests.floor.guarded_raise import GuardedRaise
    from sugar_lift_py_tests.floor.guarded_return import GuardedReturn
    from sugar_lift_py_tests.floor.loop_control_value import LoopControlValue
    from sugar_lift_py_tests.floor.raise_value import RaiseValue
    from sugar_lift_py_tests.floor.return_value import ReturnValue
    from sugar_lift_py_tests.outcome import Incomplete
    from sugar_lift_py_tests.outcome.exit_set import false_guard, true_guard

    returns = (
        tuple(
            statement
            for statement in value.statements
            if isinstance(statement, (ReturnValue, GuardedReturn))
        )
        if isinstance(value, BlockValue)
        else ()
    )
    control_exits = (
        tuple(
            statement
            for statement in value.statements
            if isinstance(
                statement,
                (
                    ExceptionalExitValue,
                    GuardedFaces,
                    GuardedLoopControl,
                    GuardedRaise,
                    Incomplete,
                    LoopControlValue,
                    RaiseValue,
                ),
            )
        )
        if isinstance(value, BlockValue)
        else ()
    )
    if (
        isinstance(value, BlockValue)
        and not value.can_fall_through
        and (
            not value.fall_through
            or all(guard == false_guard() for guard in value.fall_through)
        )
        and len(returns) == 1
        and not control_exits
        and isinstance(returns[0], ReturnValue)
        and isinstance(returns[0].value, FloorValue)
    ):
        return returns[0].value
    if (
        isinstance(value, BlockValue)
        and not value.can_fall_through
        and (
            not value.fall_through
            or all(guard == false_guard() for guard in value.fall_through)
        )
        and len(returns) == 1
        and not control_exits
        and isinstance(returns[0], GuardedReturn)
        and returns[0].guards
        and all(guard == true_guard() for guard in returns[0].guards)
        and isinstance(returns[0].value, FloorValue)
    ):
        return returns[0].value
    return value
