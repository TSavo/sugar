"""#7825 / #7757: arm lists that were assembled by hand now compose or join.

Every rewritten site composes a step with what follows through
``ExitSet.sequence`` (``consume=`` for a halt the composition owns), joins
sibling sets through ``ExitSet.union``, or builds one fresh arm with
``ExitSet.completed`` / ``ExitSet.halted``. Two of the hand assemblies dropped
what an arm carried; each has a test here that it now survives.
"""

from __future__ import annotations

from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.ir import atomic
from sugar_lift_py_tests.outcome.exit_set import (
    Completed,
    ExitSet,
    Halted,
    complement_guard,
    partition,
)


def test_prepended_facts_keep_a_non_block_completions_faces() -> None:
    # The hand rebuild of a completed arm whose value is not a reduced block
    # stated its guard and ``owed`` but not its partition testimony.
    from sugar_lift_py_tests.outcome.resource_bindings import (
        prepend_facts_to_exitset,
    )

    side, _other = partition(("test:prepend-faces", 7825))
    guard = atomic("test:prepend:7825", [])
    arm = Completed(guard, TermValue(1), frozenset({side}), ("debt:arm",))
    (out,) = prepend_facts_to_exitset(ExitSet((arm,)), ("fact",)).exits
    assert isinstance(out, Completed)
    assert out.guard == guard
    assert out.faces == frozenset({side})
    assert out.owed == ("debt:arm",)
    assert out.value.entries == ("fact",)


def test_a_warning_boundary_body_runs_beneath_the_manager_face() -> None:
    # The body was restricted by the manager face's guard alone, so every
    # body arm dropped what the manager face testified and owed.
    from sugar_lift_py_tests.sugar.with_effect_boundary_sugar import (
        _route_no_warning_boundary,
    )

    side, _other = partition(("test:manager-face", 7825))
    guard = atomic("test:manager:7825", [])
    manager = Completed(guard, TermValue(0), frozenset({side}), ("debt:manager",))
    (arm,) = _route_no_warning_boundary(
        body=(),
        ctx=None,
        manager_exit=manager,
        mode=None,
        site="test:warning-site:7825",
    ).exits
    assert isinstance(arm, Completed)
    assert arm.guard == guard
    assert side in arm.faces
    assert arm.owed == ("debt:manager",)


def test_the_one_join_takes_every_sibling_at_once() -> None:
    condition = atomic("test:join:7825", [])
    left = ExitSet((Completed(condition, TermValue(1), owed=("debt:left",)),))
    right = ExitSet(
        (Completed(complement_guard(condition), TermValue(1), owed=("debt:right",)),)
    )
    raised = ExitSet.halted(
        RaiseEffect.for_builtin("ValueError", occurrence="test:join-raise:7825")
    )
    joined = ExitSet(()).union(left, raised, right)
    # One call joins exactly what the pairwise joins do.
    assert joined == left.union(raised).union(right)
    assert [type(arm) for arm in joined.exits] == [Completed, Halted]
    # The merged completed arm owes every sibling's debt.
    assert joined.exits[0].owed == ("debt:left", "debt:right")
