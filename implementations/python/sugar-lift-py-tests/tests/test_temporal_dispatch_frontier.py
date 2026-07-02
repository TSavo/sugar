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
        "direct_context_minting": 0,
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
    assert "  direct_context_minting: 0" in stdout
    assert "  total: 0" in stdout
    assert "temporal dispatch side doors:" not in stdout


def test_temporal_dispatch_frontier_accepts_implementations_root() -> None:
    report = collect_temporal_dispatch_frontier(ROOT / "implementations")

    assert report.r.total == 0


def test_temporal_dispatch_frontier_flags_raw_reduce_context_minting(
    tmp_path,
) -> None:
    kit_src = tmp_path / "src" / "sugar_lift_py_tests" / "factory"
    kit_src.mkdir(parents=True)
    (kit_src / "raw_context.py").write_text(
        "from sugar_lift_py_tests.context import ReduceContext\n"
        "from sugar_lift_py_tests.temporal import TemporalContext\n"
        "ctx = ReduceContext(temporal=TemporalContext.empty())\n",
        encoding="utf-8",
    )

    report = collect_temporal_dispatch_frontier(tmp_path)

    assert report.r.values["direct_context_minting"] == 1
    assert report.r.total == 1
    assert len(report.offenders) == 1
    offender = report.offenders[0]
    assert offender.kind == "direct_context_minting"
    assert offender.path == "factory/raw_context.py"
    assert offender.observed == "ReduceContext(temporal=...)"
