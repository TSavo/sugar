from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.idd import cli
from sugar_lift_py_tests.idd.collect_temporal_dispatch_frontier import (
    collect_temporal_dispatch_frontier,
)

ROOT = Path(__file__).resolve().parents[4]


def test_temporal_dispatch_frontier_names_current_side_doors() -> None:
    report = collect_temporal_dispatch_frontier(ROOT)

    assert report.r.values == {
        "direct_temporal_bindings": 0,
        "direct_temporal_replacements": 0,
        "temporal_rewrite_switches": 0,
    }
    assert report.r.total == 0
    assert report.is_zero
    assert report.offenders == []


def test_temporal_dispatch_frontier_cli_exits_red_until_side_doors_are_gone(
    capsys,
) -> None:
    status = cli.main(["--root", str(ROOT), "--temporal-dispatch-frontier"])

    assert status == 0
    stdout = capsys.readouterr().out
    assert "python temporal dispatch frontier audit" in stdout
    assert "R:" in stdout
    assert "  direct_temporal_bindings: 0" in stdout
    assert "  direct_temporal_replacements: 0" in stdout
    assert "  temporal_rewrite_switches: 0" in stdout
    assert "  total: 0" in stdout
    assert "temporal dispatch side doors:" not in stdout


def test_temporal_dispatch_frontier_accepts_implementations_root() -> None:
    report = collect_temporal_dispatch_frontier(ROOT / "implementations")

    assert report.r.total == 0
