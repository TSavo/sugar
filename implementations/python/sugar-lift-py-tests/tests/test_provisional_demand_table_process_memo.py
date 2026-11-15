"""The per-source With demand table is process-memoized by workspace root.

Opening the door content-addresses every enrolled ``*.py``. Every reader of a
root (each D2 ``level=functions``, the board door, the worker) gets the same
table object, so the open is paid once per process and the sources already
derived are reused.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests import lift_rpc as lr


def test_provisional_contract_refs_second_call_is_same_object(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text(
        "from contextlib import contextmanager\n"
        "@contextmanager\n"
        "def cm():\n"
        "    yield\n"
        "def f():\n"
        "    with cm():\n"
        "        pass\n",
        encoding="utf-8",
    )
    lr.clear_provisional_contract_refs_memo()
    first = lr.provisional_contract_refs_from_demands(tmp_path)
    second = lr.provisional_contract_refs_from_demands(tmp_path)
    assert second is first
    # Different root is a different memo seat.
    other = tmp_path / "other"
    other.mkdir()
    (other / "c.py").write_text("y = 2\n", encoding="utf-8")
    third = lr.provisional_contract_refs_from_demands(other)
    assert third is not first
    lr.clear_provisional_contract_refs_memo()
    fourth = lr.provisional_contract_refs_from_demands(tmp_path)
    assert fourth is not first
