"""Teeth: one supervised pass → three projections; full path coverage required."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
_SPEC = importlib.util.spec_from_file_location(
    "_process_floor_shared_pass",
    _SCRIPTS / "_process_floor_shared_pass.py",
)
assert _SPEC is not None and _SPEC.loader is not None
_SHARED = importlib.util.module_from_spec(_SPEC)
# Register before exec so dataclasses can resolve __module__.
import sys

sys.modules[_SPEC.name] = _SHARED
# Supervisor import path lives beside this module.
sys.path.insert(0, str(_SCRIPTS))
_SPEC.loader.exec_module(_SHARED)


def _terminal(
    file: str,
    category: str,
    *,
    returncode: int | None = 0,
    signal_name: str | None = None,
    stderr: str = "",
):
    from _supervised_enum_supervisor import FileTerminal

    return FileTerminal(
        file=file,
        category=category,
        returncode=returncode,
        signal_name=signal_name,
        stderr_tail=stderr,
        terminal=None,
        worker_restarts=0,
    )


def test_projections_partition_terminal_categories() -> None:
    native = _terminal("a.py", "native-crash", returncode=-6, signal_name="SIGABRT")
    bare = _terminal("b.py", "bare-exception", returncode=1, stderr="boom")
    timeout = _terminal("c.py", "timeout", returncode=None)
    done = _terminal("d.py", "completed", returncode=0)

    n = _SHARED.project_native_crash(native)
    assert n is not None and n.signal == "SIGABRT"
    assert _SHARED.project_native_crash(bare) is None
    assert _SHARED.project_native_crash(done) is None

    b = _SHARED.project_bare_exception(bare)
    assert b is not None and b.returncode == 1
    assert _SHARED.project_bare_exception(native) is None

    t = _SHARED.project_timeout(timeout, file_timeout=30.0)
    assert t is not None and t.timeout_seconds == 30.0
    assert _SHARED.project_timeout(done, file_timeout=30.0) is None


def test_coverage_breach_is_loud(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = [tmp_path / "a.py", tmp_path / "b.py"]
    for path in paths:
        path.write_text("x = 1\n", encoding="utf-8")

    def fake_scan(paths_arg, *, root, file_timeout=30.0, demand_table_path=None):
        del root, file_timeout, demand_table_path
        # Only one terminal for two paths — the forbidden under-coverage.
        return [_terminal("a.py", "completed")]

    monkeypatch.setattr(_SHARED, "scan_paths", fake_scan)
    with pytest.raises(RuntimeError, match="coverage breach"):
        _SHARED.shared_process_floor_pass(paths, root=tmp_path, file_timeout=5.0)


def test_shared_pass_projects_all_three_without_second_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = [tmp_path / "a.py", tmp_path / "b.py", tmp_path / "c.py"]
    for path in paths:
        path.write_text("x = 1\n", encoding="utf-8")

    calls = {"n": 0}

    def fake_scan(paths_arg, *, root, file_timeout=30.0, demand_table_path=None):
        del root, demand_table_path
        calls["n"] += 1
        rels = [p.name for p in paths_arg]
        return [
            _terminal(rels[0], "native-crash", returncode=-6, signal_name="SIGABRT"),
            _terminal(rels[1], "bare-exception", returncode=1, stderr="e"),
            _terminal(rels[2], "timeout", returncode=None),
        ]

    monkeypatch.setattr(_SHARED, "scan_paths", fake_scan)
    result = _SHARED.shared_process_floor_pass(paths, root=tmp_path, file_timeout=30.0)
    assert calls["n"] == 1
    assert result.discovered == 3
    assert result.r_native_crashes() == 1
    assert result.r_bare_exceptions() == 1
    assert result.r_timeouts() == 1
    assert result.any_red() is True


def test_binding_floor_set_uses_shared_pass_not_three_lifts() -> None:
    """CI must not re-invoke three solo zero-tolerance corpus lifts."""
    root = Path(__file__).resolve().parents[4]
    floors = (root / "tools" / "run_sole_construction_floors.sh").read_text(
        encoding="utf-8"
    )
    assert "process_floor_shared_pass.py" in floors
    # Solo CLIs may still exist for discrimination; they must not each appear
    # as a separate corpus axis in the leased floor set.
    for solo in (
        'axis "R_native_crashes"',
        'axis "R_bare_exceptions"',
        'axis "R_timeouts"',
    ):
        assert solo not in floors, (
            f"{solo} must not be a separate serial corpus lift; use shared pass"
        )
    # Still bind silent separately (different door).
    assert 'axis "R_silent"' in floors
    assert "silent_zero_tolerance.py" in floors
