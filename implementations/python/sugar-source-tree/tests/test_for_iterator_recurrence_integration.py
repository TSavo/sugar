"""Real ``for`` recurrence consumes the retained synchronous iterator Floor."""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.context.reduce_context import ReduceContext
from sugar_lift_py_tests.floor.term_value import TermValue
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet
from sugar_lift_py_tests.sugar.loop_recurrence_sugar import LoopRecurrenceSugar
from sugar_lift_py_tests.temporal import bind_temporal
from sugar_source_tree.tree import SourceFile


def _function(source: str):
    return next(
        SourceFile(
            (
                source,
                "tests/for_iterator_recurrence_integration.py",
                blake3_512_of(source.encode()),
            )
        ).functions()
    )


def _completed_post(outcome):
    if isinstance(outcome, Complete):
        return outcome.value.post()
    assert isinstance(outcome, ExitSet), outcome
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    assert len(completed) == 1, completed
    return completed[0].value.post()


def test_retained_list_iterates_to_named_exhaustion_then_runs_else() -> None:
    values = tuple(range(1, 130))
    display = ", ".join(str(value) for value in values)
    source = (
        "def helper():\n"
        "    total = 0\n"
        f"    for item in [{display}]:\n"
        "        total += item\n"
        "    else:\n"
        "        total += 1000\n"
        "    return total\n"
    )

    outcome = _function(source).sugar().desugar()

    post = _completed_post(outcome)
    assert post.args[1].value == sum(values) + 1000


def test_break_bypasses_later_next_calls_and_loop_else() -> None:
    values = ", ".join(str(value) for value in range(129))
    source = (
        "def helper():\n"
        "    total = 0\n"
        f"    for item in [{values}]:\n"
        "        total += item\n"
        "        break\n"
        "    else:\n"
        "        total += 1000\n"
        "    return total\n"
    )

    post = _completed_post(_function(source).sugar().desugar())
    assert post.args[1].value == 0


def test_continue_preserves_current_state_before_the_next_iteration() -> None:
    source = (
        "def helper():\n"
        "    total = 0\n"
        "    for item in [1, 2, 3]:\n"
        "        total = total + item\n"
        "        continue\n"
        "    else:\n"
        "        total = total + 10\n"
        "    return total\n"
    )

    post = _completed_post(_function(source).sugar().desugar())
    assert post.args[1].value == 16


def test_loop_control_state_accepts_only_the_exact_iteration_binding_identity() -> None:
    value = TermValue(7)
    ambient = ReduceContext.root(owner="loop-control-ambient")
    exact = bind_temporal(
        ambient,
        "item",
        value,
        owner="loop-control-exact",
        blame="loop-control-exact",
    )
    exact = bind_temporal(
        exact,
        "blake3-512:" + "a" * 128,
        value,
        owner="loop-control-coordinate",
        blame="loop-control-coordinate",
    )
    foreign = bind_temporal(
        ambient,
        "item",
        TermValue(7),
        owner="loop-control-foreign",
        blame="loop-control-foreign",
    )

    assert (
        LoopRecurrenceSugar._require_loop_control_state(
            exact,
            target_bindings=(("item", "blake3-512:" + "a" * 128, value),),
        )
        is exact
    )
    with pytest.raises(TypeError, match="exact iteration target identity"):
        LoopRecurrenceSugar._require_loop_control_state(
            ambient,
            target_bindings=(("item", "blake3-512:" + "a" * 128, value),),
        )
    with pytest.raises(TypeError, match="exact iteration target identity"):
        LoopRecurrenceSugar._require_loop_control_state(
            foreign,
            target_bindings=(("item", "blake3-512:" + "a" * 128, value),),
        )
