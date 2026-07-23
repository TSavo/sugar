"""#4013: live isolation measure module + receipt writer."""

from __future__ import annotations

import json
from pathlib import Path

from sugar_lift_py_tests.idd.live_construction_panic_isolation import (
    assert_bearing_py_files,
    factory_engaged_empty_report,
    maybe_write_isolation_receipt_from_env,
    panic_owner_from_message,
    write_isolation_receipt,
)


def test_assert_bearing_py_files_finds_only_assert_sources(tmp_path: Path) -> None:
    with_assert = tmp_path / "a.py"
    with_assert.write_text("def f():\n    assert 1 == 1\n", encoding="utf-8")
    without = tmp_path / "b.py"
    without.write_text("def g():\n    return 0\n", encoding="utf-8")
    nested = tmp_path / "pkg"
    nested.mkdir()
    nested_assert = nested / "c.py"
    nested_assert.write_text("assert True\n", encoding="utf-8")
    (nested / "__pycache__").mkdir()
    (nested / "__pycache__" / "x.py").write_text("assert False\n", encoding="utf-8")

    found = assert_bearing_py_files(tmp_path)
    assert found == [with_assert, nested_assert]


def test_panic_owner_fallback_and_engaged_report_shape() -> None:
    assert panic_owner_from_message("no owner here") == "unknown"
    assert (
        panic_owner_from_message(
            "ConstructionPanic: owner=TemporalContext observed=result"
        )
        == "TemporalContext"
    )
    engaged = factory_engaged_empty_report()
    assert engaged["factoryAuditSummary"]["statusCounts"]["unresolved"] == 1
    assert engaged["auditOnlyGaps"] == []


def test_write_isolation_receipt_and_env_gate(tmp_path: Path, monkeypatch) -> None:
    payload = {
        "package": "numpy",
        "R_live_construction_panic_files": 2,
        "owners": {"TemporalContext": 2},
        "exact_fronts": [],
    }
    out = write_isolation_receipt(payload, tmp_path / "r.json")
    body = json.loads(out.read_text(encoding="utf-8"))
    assert body["R_live_construction_panic_files"] == 2
    assert body["owners"]["TemporalContext"] == 2

    monkeypatch.delenv("SUGAR_4013_ISOLATION_OUT", raising=False)
    assert maybe_write_isolation_receipt_from_env(payload) is None

    target = tmp_path / "from_env.json"
    monkeypatch.setenv("SUGAR_4013_ISOLATION_OUT", str(target))
    written = maybe_write_isolation_receipt_from_env(payload)
    assert written == target
    assert json.loads(target.read_text(encoding="utf-8"))["package"] == "numpy"
