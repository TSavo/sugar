"""Process floors refuse empty/defaulted path sets (wrong-population false green).

Historical bug: native_crash / timeout / bare_exception scanners defaulted
``paths`` to ``production_roots`` (kit src + scripts, ~444 files). CI invoked
them with no args; R=0 meant "kit did not crash" while the authenticated
pandas corpus was never scanned.

Tooth: empty roots raise; non-empty roots still require discoverable *.py.
Lying twin: calling require_explicit_scan_roots(()) must fail — that is the
silent-default door reopened.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
_RUNTIME_PATH = _SCRIPTS / "_enum_floor_runtime.py"
_SPEC = importlib.util.spec_from_file_location("_enum_floor_runtime", _RUNTIME_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_RUNTIME = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_RUNTIME)


def test_empty_scan_roots_are_loud() -> None:
    with pytest.raises(ValueError, match="explicit and non-empty"):
        _RUNTIME.require_explicit_scan_roots(())


def test_lying_twin_production_roots_are_not_a_silent_cli_default() -> None:
    """Scanner CLIs must not default paths to production_roots anymore."""
    for name in (
        "native_crash_zero_tolerance.py",
        "timeout_zero_tolerance.py",
        "bare_exception_zero_tolerance.py",
    ):
        source = (_SCRIPTS / name).read_text(encoding="utf-8")
        assert (
            "default=list(production_roots" not in source
        ), f"{name} still silently defaults paths to production_roots"
        assert (
            "require_explicit_scan_roots" in source
        ), f"{name} must refuse empty path sets at the door"


def test_truthful_named_root_discovers_python(tmp_path: Path) -> None:
    (tmp_path / "mod.py").write_text("x = 1\n", encoding="utf-8")
    paths = _RUNTIME.require_explicit_scan_roots((tmp_path,))
    assert paths == [tmp_path / "mod.py"]


def test_missing_named_root_still_loud(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no Python source files"):
        _RUNTIME.require_explicit_scan_roots((tmp_path / "absent",))


def test_production_roots_are_kit_not_pandas(tmp_path: Path) -> None:
    """Document the wrong population so it cannot be confused with corpus."""
    roots = _RUNTIME.production_roots(tmp_path)
    assert roots == (
        tmp_path / "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests",
        tmp_path / "implementations/python/sugar-lift-py-tests/scripts",
    )
    joined = " ".join(str(r) for r in roots)
    assert "pandas" not in joined
