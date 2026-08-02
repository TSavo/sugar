"""Teeth for identity+population+body_cid seal (lease gone on main)."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


CM = _load("commit_measurement", "tools/commit_measurement.py")
GATE = _load("commit_measurement_gate", "tools/commit_measurement_gate.py")


def _body(failed: int = 3, collected: int = 12) -> dict:
    return {
        "totals": {"failed": failed, "collected": collected},
        "failedNodeIds": ["x"] * failed,
    }


def test_scoreboard_authority_false() -> None:
    assert CM.SCOREBOARD_AUTHORITY is False


def test_measured_seal_is_identity_population_body_not_lease() -> None:
    m = CM.measured(
        3,
        identity="python-package-suite",
        population_id="pop:suite",
        population_size=12,
        body=_body(3, 12),
        value_field_path="totals.failed",
        exit_code=1,
    )
    assert m.identity == "python-package-suite"
    assert m.population_id == "pop:suite"
    assert m.population_size == 12
    assert m.body_cid == CM.content_cid(_body(3, 12))
    assert not hasattr(m, "receipt_cid")
    import inspect

    sig = inspect.signature(CM.measured)
    assert "receipt_cid" not in sig.parameters
    assert "lease_receipt_cid" not in sig.parameters


def test_measured_requires_body_matching_value() -> None:
    with pytest.raises(CM.CommitMeasurementError, match="parsed body|NoReport"):
        CM.measured(
            3,
            identity="x",
            population_id="p",
            population_size=1,
            body=None,  # type: ignore[arg-type]
            value_field_path="totals.failed",
            exit_code=1,
        )
    with pytest.raises(CM.CommitMeasurementError, match="does not match"):
        CM.measured(
            99,
            identity="x",
            population_id="p",
            population_size=12,
            body=_body(3, 12),
            value_field_path="totals.failed",
            exit_code=1,
        )


def test_empty_artifacts_partial_gate_red(tmp_path: Path) -> None:
    empty = tmp_path / "arts"
    empty.mkdir()
    v = CM.compose_tip_from_artifacts_dir("deadbeef", empty)
    assert isinstance(v, CM.PartialVector)
    path = tmp_path / "cm.json"
    path.write_text(json.dumps(v.to_json()), encoding="utf-8")
    assert GATE.main(["--composition", str(path), "--require-complete"]) == 1


def test_body_without_lease_is_measured(tmp_path: Path) -> None:
    body = {
        "totals": {"failed": 4, "collected": 20},
        "failedNodeIds": ["a", "b", "c", "d"],
        "measurementClass": "python-package-suite",
        "populationId": "pandas-auth-corpus",
        "populationSize": 20,
    }
    (tmp_path / "suite-report.json").write_text(json.dumps(body), encoding="utf-8")
    v = CM.compose_tip_from_artifacts_dir("deadbeef", tmp_path)
    assert isinstance(v, CM.PartialVector)
    axis = v.axes["python-package-suite"]
    assert isinstance(axis, CM.Measured)
    assert axis.value == 4
    assert axis.population_id == "pandas-auth-corpus"


def test_partial_has_no_total() -> None:
    partial = CM.commit_measurement(
        "sha",
        "roster",
        {
            "a": CM.measured(
                1,
                identity="a",
                population_id="p",
                population_size=2,
                body=_body(1, 2),
                value_field_path="totals.failed",
                exit_code=1,
            ),
            "b": CM.unmeasured("NoReport"),
        },
    )
    assert isinstance(partial, CM.PartialVector)
    with pytest.raises(AttributeError):
        _ = partial.total  # type: ignore[attr-defined]
