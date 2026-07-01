from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.idd import cli
from sugar_lift_py_tests.idd.collect_dunder_frontier import collect_dunder_frontier

ROOT = Path(__file__).resolve().parents[4]


def test_dunder_frontier_vector_names_current_missing_families() -> None:
    report = collect_dunder_frontier(ROOT)

    assert report.r.values == {
        "call_container_slots": 1,
        "mutation_container_slots": 4,
        "inplace_binary_slots": 13,
        "display_conversion_slots": 4,
        "attribute_descriptor_slots": 9,
        "context_async_slots": 7,
    }
    assert report.r.total == 38
    assert not report.is_zero


def test_dunder_frontier_distinguishes_owned_and_missing_slots() -> None:
    report = collect_dunder_frontier(ROOT)
    by_name = {slot.name: slot for slot in report.slots}

    for name in (
        "__call__",
        "__getitem__",
        "__contains__",
        "__iter__",
        "__bool__",
        "__len__",
        "__hash__",
        "__eq__",
        "__ge__",
        "__truediv__",
        "__divmod__",
        "__rdivmod__",
        "__rxor__",
        "__invert__",
        "__abs__",
        "__round__",
        "__floor__",
        "__ceil__",
        "__trunc__",
        "__int__",
        "__float__",
        "__complex__",
        "__index__",
    ):
        assert by_name[name].status == "owned", name
        assert by_name[name].owner

    for name in (
        "__next__",
        "__setitem__",
        "__iadd__",
        "__str__",
        "__getattr__",
        "__enter__",
    ):
        assert by_name[name].status == "missing", name
        assert by_name[name].fix.startswith("write ")


def test_dunder_frontier_cli_exits_red_until_tracked_slots_are_owned(
    capsys,
) -> None:
    status = cli.main(["--root", str(ROOT), "--dunder-frontier"])

    assert status == 1
    stdout = capsys.readouterr().out
    assert "python dunder frontier audit" in stdout
    assert "R:" in stdout
    assert "  inplace_binary_slots: 13" in stdout
    assert "  total: 38" in stdout
    assert "missing dunder slots:" in stdout
    assert "  - inplace_binary __iadd__" in stdout
    assert "  - display_conversion __str__" in stdout
