"""A live ``for``'s target is read through its per-item key (#7757 item 7).

The target is bound per item under its own key (``_loop_target_evaluation_key``),
never under its name; a target bound before the loop is carried and published
under its binding coordinate; a nested loop whose target is a name the outer
loop carries publishes that target, which the outer latch reads.  A display of
more than ``For._UNROLL_FUEL`` items keeps the loop live.
"""

from __future__ import annotations

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.outcome import Completed, ExitSet
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.tree import SourceFile

ITEMS = tuple(range(1, 130))
DISPLAY = "[" + ", ".join(str(item) for item in ITEMS) + "]"
PAIRS = "[" + ", ".join(f"({item}, {item + 1})" for item in ITEMS) + "]"


def _returned(source: str):
    function = next(
        SourceFile(
            (
                source,
                "tests/live_loop_target_key.py",
                blake3_512_of(source.encode()),
            ),
            construction_context=TreeConstructionContextV1.for_test_without_workspace(),
        ).functions()
    )
    outcome = function.sugar().desugar()
    assert isinstance(outcome, ExitSet), outcome
    value = outcome.completed_value()
    if value is None:
        completed = [face for face in outcome.exits if isinstance(face, Completed)]
        assert len(completed) == 1, completed
        value = completed[0].value
    return value.post().args[1].value


def test_a_nested_loop_rebinding_the_outer_target_hands_on_its_last_value() -> None:
    # Python: after the last outer item, ``x`` is the inner loop's last 8,
    # not the outer item's 129.  The inner loop unrolls: each iteration's
    # keyed store ``x = <element>`` is a write the outer latch reads.
    source = (
        "def helper():\n"
        "    x = 0\n"
        f"    for x in {DISPLAY}:\n"
        "        for x in (7, 8):\n"
        "            pass\n"
        "    return x\n"
    )
    assert _returned(source) == 8


def test_a_loop_target_read_after_the_loop_is_the_last_item() -> None:
    source = (
        "def helper():\n"
        "    x = 0\n"
        f"    for x in {DISPLAY}:\n"
        "        pass\n"
        "    return x\n"
    )
    assert _returned(source) == ITEMS[-1]


def test_a_target_the_body_rewrites_is_read_after_the_loop_as_written() -> None:
    source = (
        "def helper():\n"
        "    x = 0\n"
        f"    for x in {DISPLAY}:\n"
        "        x += 1000\n"
        "    return x\n"
    )
    assert _returned(source) == ITEMS[-1] + 1000


def test_a_walrus_in_a_live_loop_is_read_after_it() -> None:
    source = (
        "def helper():\n"
        "    t = 0\n"
        f"    for v in {DISPLAY}:\n"
        "        (t := v)\n"
        "    return t\n"
    )
    assert _returned(source) == ITEMS[-1]


def test_an_unpack_in_a_live_loop_is_read_after_it() -> None:
    source = (
        "def helper():\n"
        "    a = 0\n"
        f"    for p in {PAIRS}:\n"
        "        a, b = p\n"
        "    return a\n"
    )
    assert _returned(source) == ITEMS[-1]


def test_the_outer_target_is_read_inside_a_nested_loop() -> None:
    # The inner loop's body reads the outer item's ``row`` through its key;
    # ``c``, bound before the loops, is the outer loop's write too.
    source = (
        "def helper():\n"
        "    total = 0\n"
        "    c = 0\n"
        f"    for row in {DISPLAY}:\n"
        "        for c in (1, 2):\n"
        "            total += row\n"
        "    return total\n"
    )
    assert _returned(source) == 2 * sum(ITEMS)
