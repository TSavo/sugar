from __future__ import annotations

from sugar_lift_py_tests.census import census
from sugar_source_tree.panic import BackendDefect
from sugar_source_tree.tree import SourceFile


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
            owner="planted census tooth",
            observed="a malformed backend answer",
            requested="a valid constructed source tree",
            fix="repair the backend",
        )

    monkeypatch.setattr(SourceFile, "from_path", backend_crash)

    assert census(tmp_path) != 0


def test_census_returns_zero_when_every_function_constructs(tmp_path) -> None:
    (tmp_path / "clean.py").write_text(
        "def f():\n return 1\n",
        encoding="utf-8",
    )

    assert census(tmp_path) == 0
