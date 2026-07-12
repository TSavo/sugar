from __future__ import annotations

from factory_reduce import compose_block

from sugar_lift_py_tests.floor import CurriedLoopScope


def test_break_loop_is_a_curried_callable_result_not_an_event_coordinate() -> None:
    block = compose_block(
        "    index = 0\n"
        "    while index < 4:\n"
        "        if index == 2:\n"
        "            break\n"
        "        index += 1\n"
    )

    assert any(isinstance(entry, CurriedLoopScope) for entry in block.statements)
    assert "py.loop_exit" not in repr(block)
    assert "py.loop_skip" not in repr(block)


def test_first_match_loop_carries_prefix_index_through_callable_floor() -> None:
    block = compose_block(
        "    index = 0\n"
        "    while index < 7:\n"
        "        if index == 3:\n"
        "            break\n"
        "        index += 1\n"
        "    answer = index\n"
    )

    assert "call:loop:" in repr(block)
    assert "loop-control:" not in repr(block)
