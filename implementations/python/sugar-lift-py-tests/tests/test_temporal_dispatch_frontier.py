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
        "direct_temporal_bindings": 10,
        "direct_temporal_replacements": 8,
        "temporal_rewrite_switches": 1,
    }
    assert report.r.total == 19
    assert not report.is_zero

    offenders = {offender.kind: [] for offender in report.offenders}
    for offender in report.offenders:
        offenders[offender.kind].append(offender)

    assert any(
        offender.path.endswith("sugar/block_sugar.py")
        for offender in offenders["direct_temporal_bindings"]
    )
    assert any(
        offender.path.endswith("floor/call_site_value.py")
        for offender in offenders["direct_temporal_replacements"]
    )
    assert any(
        offender.path.endswith("temporal/temporal_context.py")
        for offender in offenders["temporal_rewrite_switches"]
    )


def test_temporal_dispatch_frontier_cli_exits_red_until_side_doors_are_gone(
    capsys,
) -> None:
    status = cli.main(["--root", str(ROOT), "--temporal-dispatch-frontier"])

    assert status == 1
    stdout = capsys.readouterr().out
    assert "python temporal dispatch frontier audit" in stdout
    assert "R:" in stdout
    assert "  direct_temporal_bindings: 10" in stdout
    assert "  direct_temporal_replacements: 8" in stdout
    assert "  temporal_rewrite_switches: 1" in stdout
    assert "  total: 19" in stdout
    assert "temporal dispatch side doors:" in stdout
    assert "fix: route temporal binding through temporal dispatch floor" in stdout


def test_temporal_dispatch_frontier_accepts_implementations_root() -> None:
    report = collect_temporal_dispatch_frontier(ROOT / "implementations")

    assert report.r.total == 19
