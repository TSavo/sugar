"""#7825 / #7757: manager arm lists that were assembled by hand now compose.

Every rewritten site in ``sugar_lift_python_source`` composes a step with
what follows through ``ExitSet.sequence`` (``consume=`` for a halt the
composition owns), joins sibling sets through ``ExitSet.union``, or builds one
fresh arm with ``ExitSet.completed``. The hand assemblies dropped what an arm
carried (its guard, its partition testimony or what it owed); each remaining
one has a test here that it now survives.
"""

from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
from sugar_lift_py_tests.floor import (
    ObjectField,
    ObjectValue,
    ReceiverStatePartitionValue,
    TermValue,
)
from sugar_lift_py_tests.ir import and_, atomic
from sugar_lift_py_tests.outcome.exit_set import (
    Completed,
    ExitSet,
    Halted,
    complement_guard,
    partition,
)

from frame_fresh import FRAME_FRESH


def _raise(name: str) -> RaiseEffect:
    return RaiseEffect.for_builtin("ValueError", occurrence=f"test:{name}:7825")


def test_a_nested_receiver_leaf_keeps_its_whole_path() -> None:
    # A nested leaf was rebuilt under the enclosing face's guard alone: the
    # leaf's own guard, both faces' testimony and the leaf's debts dropped.
    from sugar_lift_python_source.manager_protocol_construction import (
        _completed_receiver_exits,
    )

    outer_side, _outer_other = partition(("test:outer-receiver", 7825))
    inner_side, _inner_other = partition(("test:inner-receiver", 7825))
    outer = atomic("test:outer:7825", [])
    inner = atomic("test:inner:7825", [])
    leaf = ObjectValue("Manager", (), allocation=FRAME_FRESH)
    nested = ReceiverStatePartitionValue(
        ExitSet(
            (
                Completed(inner, leaf, frozenset({inner_side}), ("debt:inner",)),
                Halted(complement_guard(inner), _raise("inner-halt")),
            )
        )
    )
    state = ReceiverStatePartitionValue(
        ExitSet(
            (
                Completed(outer, nested, frozenset({outer_side}), ("debt:outer",)),
                Halted(complement_guard(outer), _raise("outer-halt")),
            )
        )
    )

    (arm,) = _completed_receiver_exits(state).exits

    assert isinstance(arm, Completed)
    assert arm.value is leaf
    assert arm.guard == and_([outer, inner])
    assert arm.faces == frozenset({outer_side, inner_side})
    assert arm.owed == ("debt:outer", "debt:inner")
