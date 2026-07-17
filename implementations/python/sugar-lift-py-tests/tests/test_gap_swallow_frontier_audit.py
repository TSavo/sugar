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
#
# #4203 residual: reduce-adjacent continues and Exception defaults still soft-
# swallow construction failures. Replacement: re-raise / FactoryPanic, or gate
# behind the explicit recovered-audit sink (recover_panics / recovered_panics).
# FactoryPanic silent continues are not permitted on this list — they must be
# deleted, not ratcheted.
EXPECTED_FRONTIER: tuple[tuple[str, int, str, str], ...] = (
    (
        "factory/sugar_constructors.py",
        441,
        "(TypeError, ValueError, AssertionError)",
        "continues",
    ),
    ("factory/sugar_constructors.py", 447, "Exception", "continues"),
    ("lift/pydantic.py", 238, "Exception", "passes"),
    ("lift_rpc.py", 331, "Exception", "returns-default"),
    (
        "lift_rpc.py",
        1428,
        "(TypeError, ValueError, AssertionError)",
        "continues",
    ),
    ("lift_rpc.py", 1454, "Exception", "continues"),
    ("proof_envelope.py", 138, "Exception", "returns-default"),
    ("proof_envelope.py", 168, "Exception", "returns-default"),
    ("signing.py", 87, "Exception", "returns-default"),
    ("signing.py", 97, "Exception", "returns-default"),
    (
        "sugar/install_source_dig.py",
        275,
        "(ImportError, OSError, TypeError, UnicodeError)",
        "returns-default",
    ),
    (
        "sugar/install_source_dig.py",
        1022,
        "(ImportError, AttributeError, OSError, TypeError)",
        "returns-default",
    ),
    ("sugar/install_source_dig.py", 1184, "Exception", "returns-default"),
    ("sugar/install_source_dig.py", 1397, "Exception", "returns-default"),
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
