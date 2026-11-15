"""A newer push cancels the superseded run; there is no machine-wide measurement lease.

Jobs run in parallel. A global mutex is not a resource model.
"""

from __future__ import annotations

import pytest

from repo_root_test_support import resolve_repo_root

ROOT = resolve_repo_root()
WORKFLOWS = ROOT / ".github" / "workflows"
LEASE_WRAPPER = "tools/heavy_measurement_lease.py"
GATE = "tools/heavy_measurement_lease_gate.py"

HEAVY_WORKFLOWS = (
    "python-package-suite.yml",
    "control-effect-recensus.yml",
)

RETIRED_GROUPS = ("sugar-python-heavy-measurement", "sugar-python-package-suite")


def _text(name):
    return (WORKFLOWS / name).read_text()


@pytest.mark.parametrize("workflow", HEAVY_WORKFLOWS)
def test_heavy_workflows_use_no_retired_group(workflow):
    text = _text(workflow)
    for group in RETIRED_GROUPS:
        assert group not in text


@pytest.mark.parametrize("workflow", HEAVY_WORKFLOWS)
def test_no_workflow_uses_the_deleted_machine_wide_lease(workflow):
    text = _text(workflow)
    assert LEASE_WRAPPER not in text, (
        f"{workflow} still wraps work in {LEASE_WRAPPER}; the machine-wide "
        f"lease is deleted — jobs run in parallel"
    )
    assert GATE not in text, f"{workflow} still calls the deleted lease gate"
    assert "lease-record.json" not in text


def test_lease_tools_are_deleted():
    assert not (ROOT / LEASE_WRAPPER).exists()
    assert not (ROOT / GATE).exists()
    assert not (ROOT / "tools/heavy_measurement_lease_record.py").exists()


def test_a_newer_push_cancels_the_superseded_run():
    """Owner ruling 2026-11-14, overrules #7118.

    On main a running run finishes first and the newest push replaces the
    queued run; on other refs a newer push cancels the running run.
    """
    block = (
        "concurrency:\n"
        "  group: ${{ github.workflow }}-${{ github.ref }}\n"
        "  cancel-in-progress: ${{ github.ref != 'refs/heads/main' }}\n"
    )
    for path in sorted(WORKFLOWS.glob("*.yml")):
        if path.name == "issue-claim-labels.yml":
            continue
        assert block in path.read_text(), path.name


def test_the_authoritative_scoreboard_is_the_sole_seal_door():
    authority = (
        ROOT
        / "implementations/python/sugar-lift-py-tests/scripts/compose_control_effect_board.py"
    )
    worker = (
        ROOT
        / "implementations/python/sugar-lift-py-tests/scripts/control_effect_recensus.py"
    )
    assert "SCOREBOARD_AUTHORITY = True" in authority.read_text()
    assert "SCOREBOARD_AUTHORITY = False" in worker.read_text()
