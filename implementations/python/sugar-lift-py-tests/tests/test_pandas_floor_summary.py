from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SUMMARY = _load("pandas_floor_summary")
RECONCILE = _load("reconcile_pandas_floors")


def _floor(name: str, *, r: int = 0, measured: bool = True) -> dict:
    return SUMMARY.floor_summary(
        floor=name,
        files=["renamed/pkg/non_vendor.py"],
        rows=[{"file": "renamed/pkg/non_vendor.py", "category": "completed"}],
        totals={f"R_{name.replace('-', '_')}": r},
        measured=measured,
        unmeasurable_reasons=() if measured else ("planted-terminal",),
    )


def test_five_measured_native_floors_reconcile_on_identical_corpus() -> None:
    reports = {name: _floor(name) for name in RECONCILE.FLOORS}

    result = RECONCILE.reconcile(reports)

    assert result["measurement"] == "measured"
    assert result["verdict"] == "green"
    assert result["errors"] == []
    assert set(result["floors"]) == set(RECONCILE.FLOORS)


def test_absent_floor_is_loud_not_an_implicit_zero() -> None:
    reports = {name: _floor(name) for name in RECONCILE.FLOORS if name != "silent"}

    result = RECONCILE.reconcile(reports)

    assert result["measurement"] == "unmeasurable"
    assert "missing floor: silent" in result["errors"]


def test_unmeasurable_terminal_is_loud_even_when_reported_r_is_zero() -> None:
    reports = {name: _floor(name) for name in RECONCILE.FLOORS}
    reports["silent"] = _floor("silent", r=0, measured=False)

    result = RECONCILE.reconcile(reports)

    assert result["measurement"] == "unmeasurable"
    assert "silent: measurement is not complete" in result["errors"]


def test_measured_nonzero_floor_is_still_a_red_verdict() -> None:
    reports = {name: _floor(name) for name in RECONCILE.FLOORS}
    reports["timeout"] = _floor("timeout", r=1)

    result = RECONCILE.reconcile(reports)

    assert result["measurement"] == "measured"
    assert result["R_total"] == 1
    assert result["verdict"] == "red"


def test_per_site_conservation_rejects_a_lying_summary() -> None:
    with pytest.raises(ValueError, match="account for every corpus file"):
        SUMMARY.floor_summary(
            floor="timeout",
            files=["renamed/a.py", "renamed/b.py"],
            rows=[{"file": "renamed/a.py", "category": "completed"}],
            totals={"R_timeouts": 0},
            measured=True,
        )


def test_different_corpus_identity_cannot_reconcile() -> None:
    reports = {name: _floor(name) for name in RECONCILE.FLOORS}
    reports["timeout"] = SUMMARY.floor_summary(
        floor="timeout",
        files=["renamed/other.py"],
        rows=[{"file": "renamed/other.py", "category": "completed"}],
        totals={"R_timeouts": 0},
        measured=True,
    )

    result = RECONCILE.reconcile(reports)

    assert result["measurement"] == "unmeasurable"
    assert "five floors do not name one identical corpus manifest" in result["errors"]
