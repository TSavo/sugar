from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.idd import cli
from sugar_lift_py_tests.idd.collect_gap_swallow_frontier import (
    collect_gap_swallow_frontier,
)

ROOT = Path(__file__).resolve().parents[4]


# Stable-zero ratchet: every quiet gap was drained (#4203). A new swallow turns
# this red until the site panics, records via a sanctioned recorder, or is
# rewritten as a pre-check / named IncompleteFunctionBody membrane.
EXPECTED_FRONTIER: tuple[tuple[str, int, str, str], ...] = ()


def test_frontier_matches_known_offenders_exactly() -> None:
    report = collect_gap_swallow_frontier(ROOT)
    observed = tuple(
        (site.file, site.line, site.caught, site.disposition)
        for site in report.offenders
    )

    assert observed == EXPECTED_FRONTIER, report.to_json()


def test_frontier_is_stable_zero() -> None:
    report = collect_gap_swallow_frontier(ROOT)

    assert report.is_zero
    assert report.total == 0


def test_gap_swallow_frontier_cli_exits_green_at_stable_zero(
    capsys,
) -> None:
    status = cli.main(["--root", str(ROOT), "--gap-swallow-frontier"])

    assert status == 0
    stdout = capsys.readouterr().out
    assert '"total": 0' in stdout
    assert '"is_zero": true' in stdout


def test_sanctioned_recorders_are_not_offenders() -> None:
    report = collect_gap_swallow_frontier(ROOT)
    offenders = {(site.file, site.caught) for site in report.offenders}

    # Recovery-gated FactoryPanic holds in lift_rpc are lawful under #4203.
    assert ("lift_rpc.py", "FactoryPanic") not in offenders
    assert "audit_only/collect_construction_gaps.py" not in {
        site.file for site in report.offenders
    }
    # NameSugar no longer swallows FactoryPanic from force_floor.
    assert "sugar/name_sugar.py" not in {site.file for site in report.offenders}


def test_silent_factory_panic_continue_is_an_offender(tmp_path: Path) -> None:
    """#4203 red instrument: bare except FactoryPanic: pass is never lawful."""
    kit_src = tmp_path / "src" / "sugar_lift_py_tests"
    kit_src.mkdir(parents=True)
    (kit_src / "quiet_panic.py").write_text(
        "def planted(value):\n"
        "    try:\n"
        "        return force_floor(value)\n"
        "    except FactoryPanic:\n"
        "        pass\n",
        encoding="utf-8",
    )

    report = collect_gap_swallow_frontier(tmp_path)

    assert report.total == 1
    assert report.offenders[0].file == "quiet_panic.py"
    assert report.offenders[0].caught == "FactoryPanic"
    assert report.offenders[0].disposition == "passes"


def test_recovery_gated_factory_panic_is_not_gap_swallow(tmp_path: Path) -> None:
    """Explicit recovery sink may continue after re-raising when absent."""
    kit_src = tmp_path / "src" / "sugar_lift_py_tests"
    kit_src.mkdir(parents=True)
    (kit_src / "gated.py").write_text(
        "def planted(value, recovered_panics):\n"
        "    try:\n"
        "        return value.reduce()\n"
        "    except FactoryPanic as panic:\n"
        "        if recovered_panics is None:\n"
        "            raise\n"
        "        recovered_panics.append(panic)\n"
        "        continue\n",
        encoding="utf-8",
    )

    report = collect_gap_swallow_frontier(tmp_path)

    assert report.total == 0


def test_runtime_effect_boundary_is_not_gap_swallow(tmp_path: Path) -> None:
    kit_src = tmp_path / "src" / "sugar_lift_py_tests"
    kit_src.mkdir(parents=True)
    (kit_src / "typed_red.py").write_text(
        "def planted(value):\n"
        "    try:\n"
        "        return value.reduce()\n"
        "    except FactoryGap as exc:\n"
        "        observed = str(exc)\n"
        "        return Incomplete(RuntimeEffect(observed))\n",
        encoding="utf-8",
    )

    report = collect_gap_swallow_frontier(tmp_path)

    assert report.total == 0


def test_plain_gap_default_still_flags_gap_swallow(tmp_path: Path) -> None:
    kit_src = tmp_path / "src" / "sugar_lift_py_tests"
    kit_src.mkdir(parents=True)
    (kit_src / "quiet.py").write_text(
        "def planted(value):\n"
        "    try:\n"
        "        return value.reduce()\n"
        "    except FactoryGap as exc:\n"
        "        observed = str(exc)\n"
        "        return None\n",
        encoding="utf-8",
    )

    report = collect_gap_swallow_frontier(tmp_path)

    assert report.total == 1
    assert report.offenders[0].file == "quiet.py"
    assert report.offenders[0].line == 4
    assert report.offenders[0].caught == "FactoryGap"
    assert report.offenders[0].disposition == "returns-default"
