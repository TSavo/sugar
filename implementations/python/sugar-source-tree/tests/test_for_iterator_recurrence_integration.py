"""Real ``for`` recurrence consumes the retained synchronous iterator Floor."""

from __future__ import annotations

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet
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
