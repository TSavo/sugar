from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.idd import cli
from sugar_lift_py_tests.idd.collect_gap_swallow_frontier import (
    collect_gap_swallow_frontier,
)

ROOT = Path(__file__).resolve().parents[4]


# The ratchet: every entry here is a named quiet gap awaiting its drain task.
# Drain a site -> delete its row here in the same PR. Add a swallow -> this
# test fails and CI stays red until you either panic or record loudly.
EXPECTED_FRONTIER: tuple[tuple[str, int, str, str], ...] = (
    ("lift/pydantic.py", 238, "Exception", "passes"),
    ("proof_envelope.py", 138, "Exception", "returns-default"),
    ("proof_envelope.py", 168, "Exception", "returns-default"),
    ("signing.py", 87, "Exception", "returns-default"),
    ("signing.py", 97, "Exception", "returns-default"),
    (
        "witness_oracle.py",
        119,
        "(BadSignatureError, ValueError, Exception)",
        "returns-default",
    ),
)


def test_frontier_matches_known_offenders_exactly() -> None:
    report = collect_gap_swallow_frontier(ROOT)
    observed = tuple(
        (site.file, site.line, site.caught, site.disposition)
        for site in report.offenders
    )

    assert observed == EXPECTED_FRONTIER, report.to_json()


def test_frontier_is_red() -> None:
    report = collect_gap_swallow_frontier(ROOT)

    assert not report.is_zero
    assert report.total == len(EXPECTED_FRONTIER)


def test_gap_swallow_frontier_cli_exits_red_until_offenders_are_gone(
    capsys,
) -> None:
    status = cli.main(["--root", str(ROOT), "--gap-swallow-frontier"])

    assert status == 1
    stdout = capsys.readouterr().out
    assert '"total"' in stdout
    assert '"offenders"' in stdout


def test_sanctioned_recorders_are_not_offenders() -> None:
    report = collect_gap_swallow_frontier(ROOT)
    files = {site.file for site in report.offenders}

    assert "lift_rpc.py" not in files
    assert "audit_only/collect_construction_gaps.py" not in files


def test_typed_effect_terminal_is_not_a_gap_swallow(tmp_path) -> None:
    kit_src = tmp_path / "src" / "sugar_lift_py_tests" / "floor"
    kit_src.mkdir(parents=True)
    (kit_src / "typed_effect.py").write_text(
        "def planted(term, ctx):\n"
        "    try:\n"
        "        floor = term.reduce(ctx)\n"
        "    except FactoryGap:\n"
        "        return Incomplete(RuntimeEffect('runtime boundary'))\n"
        "    return floor\n",
        encoding="utf-8",
    )

    report = collect_gap_swallow_frontier(tmp_path)

    assert report.is_zero, report.to_json()
