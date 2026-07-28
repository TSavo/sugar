from __future__ import annotations

from sugar_lift_py_tests import lift_rpc
from sugar_lift_py_tests.census import census
from sugar_source_tree.panic import BackendDefect


def test_census_returns_nonzero_when_construction_hits_backend_defect(
    tmp_path, monkeypatch
) -> None:
    (tmp_path / "crash.py").write_text(
        "def f():\n return 1\n",
        encoding="utf-8",
    )

    def backend_crash(*args, **kwargs):
        del args, kwargs
        raise BackendDefect(
            blame=tmp_path / "crash.py",
            owner="planted census tooth",
            observed="a malformed backend answer",
            requested="a valid constructed source tree",
            fix="repair the backend",
        )

    # Plant the defect at the door the census actually opens. The census now
    # opens files through ``open_source_file_for_construction``; this tooth
    # used to patch ``SourceFile.from_path``, which that door never calls, so
    # it would have gone green while measuring nothing.
    monkeypatch.setattr(lift_rpc, "open_source_file_for_construction", backend_crash)

    assert census(tmp_path) != 0


def test_census_returns_zero_when_every_function_constructs(tmp_path) -> None:
    (tmp_path / "clean.py").write_text(
        "def f():\n return 1\n",
        encoding="utf-8",
    )

    assert census(tmp_path) == 0
