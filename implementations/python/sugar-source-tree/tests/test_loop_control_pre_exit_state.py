from __future__ import annotations

import pytest

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_py_tests.effect import LoopControlEffect
from sugar_lift_py_tests.outcome import Halted
from sugar_source_tree.tree import SourceFile

SOURCE = (
    "def helper(values):\n"
    "    for value in values:\n"
    "        if value:\n"
    "            continue\n"
    "        break\n"
)


def _controls():
    function = next(
        SourceFile(
            (
                SOURCE,
                "tests/loop_control_pre_exit_state.py",
                blake3_512_of(SOURCE.encode()),
            )
        ).functions()
    )
    return tuple(node for node in function.walk() if node.kind in {"Break", "Continue"})


@pytest.mark.parametrize("action", ("break", "continue"))
def test_loop_control_preserves_exact_authenticated_pre_exit_state(action: str) -> None:
    node = next(node for node in _controls() if node.kind.lower() == action)
    pre_exit_state = object()
    foreign_state = object()

    exit_ = node.sugar().desugar(pre_exit_state).exits[0]

    assert isinstance(exit_, Halted)
    assert isinstance(exit_.effect, LoopControlEffect)
    assert exit_.effect.action == action
    assert exit_.effect.occurrence_cid == node.fragment.seal().cid
    assert exit_.state is pre_exit_state
    assert exit_.state is not foreign_state


@pytest.mark.parametrize("action", ("break", "continue"))
def test_loop_control_absent_and_foreign_state_twins_do_not_authenticate(
    action: str,
) -> None:
    node = next(node for node in _controls() if node.kind.lower() == action)
    truthful_state = object()
    foreign_state = object()

    absent = node.sugar().desugar().exits[0]
    foreign = node.sugar().desugar(foreign_state).exits[0]

    assert absent.effect.occurrence_cid == node.fragment.seal().cid
    assert absent.state is not truthful_state
    assert foreign.effect.occurrence_cid == node.fragment.seal().cid
    assert foreign.state is foreign_state
    assert foreign.state is not truthful_state
