"""GitHub retains every run; the BX lease decides who measures.

WHAT REPLACED WHAT
==================

This file used to assert the opposite topology: one GitHub concurrency group
(`sugar-python-heavy-measurement`) owned by one orchestrator, on the theory
that a group with `cancel-in-progress: false` queues rather than drops.

It does not. GitHub keeps exactly ONE pending run per concurrency group, so a
third queued run EVICTS the second. The evidence is not theoretical:

  * `python-package-suite` — five runs (dea47f1f8, e0a78ec52, d243fcacf,
    6d9db3a8f, f0cddfd76) cancelled before starting, zero artifacts ever.
  * `Python sole-construction floors` — three runs cancelled inside two
    minutes on a single PR's rapid pushes, while the light jobs completed.

`cancel-in-progress: false` only protects a run that has already STARTED. It
has nothing to say about the pending slot, and the pending slot is where our
merge rate was killing our heaviest instruments.

So the two responsibilities are split, and this file pins the split:

    GitHub queue: preserve every requested measurement  → NO concurrency group
    BX lease:     only one heavy measurement executes   → the flock wrapper

A heavy workflow that declares a concurrency group is back in the eviction
path. A heavy workflow that runs its measurement outside the lease is back to
two censuses fighting over one box. Both are red here.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
LEASE_WRAPPER = "tools/heavy_measurement_lease.py"
GATE = "tools/heavy_measurement_lease_gate.py"

# Every heavy measurement class: workflow file -> the --class name it leases
# under. This is the same roster tools/heavy_measurement_attendance.py calls
# the roll from, and the two are checked against each other below.
HEAVY_WORKFLOWS = {
    "python-package-suite.yml": "python-package-suite",
    "factory-zero-tolerance.yml": "python-sole-construction-floors",
    "numpy-wall.yml": "numpy-wall",
    "pandas-wall.yml": "pandas-wall",
    "restored-suite-scoreboard.yml": "restored-suite-scoreboard",
}

# The dead group. Nothing may claim it again.
RETIRED_GROUPS = ("sugar-python-heavy-measurement", "sugar-python-package-suite")

# PR-triggered floor scanners that must stay discrimination-only.
STANDALONE_FLOOR_WORKFLOWS = (
    "bare-exception-zero-tolerance.yml",
    "timeout-zero-tolerance.yml",
    "native-crash-zero-tolerance.yml",
)


def _text(name):
    return (WORKFLOWS / name).read_text()


@pytest.mark.parametrize("workflow", sorted(HEAVY_WORKFLOWS))
def test_heavy_workflows_declare_no_concurrency_group(workflow):
    """No group means no pending slot means nothing to evict."""
    text = _text(workflow)
    assert not re.search(r"^concurrency:", text, re.MULTILINE), (
        f"{workflow} declares a GitHub concurrency group. GitHub keeps ONE "
        f"pending run per group and evicts the rest -- that is how five suite "
        f"runs and three floor runs were lost. Serialize on the BX lease "
        f"({LEASE_WRAPPER}) instead; let GitHub retain every run."
    )
    for group in RETIRED_GROUPS:
        assert group not in text, f"{workflow} claims the retired group {group}"


@pytest.mark.parametrize("workflow,lease_class", sorted(HEAVY_WORKFLOWS.items()))
def test_heavy_workflows_measure_under_the_lease(workflow, lease_class):
    text = _text(workflow)
    assert LEASE_WRAPPER in text, (
        f"{workflow} is a heavy measurement and must run its measured command "
        f"through {LEASE_WRAPPER}; nothing else serializes the box"
    )
    assert f"--class {lease_class}" in text, (
        f"{workflow} must lease under --class {lease_class} so its receipt is "
        f"attributable and the attendance roll call can miss it when absent"
    )
    assert GATE in text, (
        f"{workflow} must run {GATE}: a timing claim from a run that never "
        f"acquired the lease is not a measurement, and that has to be checked"
    )


def test_no_heavy_workflow_cancels_a_superseded_run():
    """Even outside the heavy classes: a superseded run may still be the only
    evidence we will get for its commit. `ci.yml` was the last canceller."""
    for path in sorted(WORKFLOWS.glob("*.yml")):
        text = path.read_text()
        assert "cancel-in-progress: true" not in text, (
            f"{path.name} cancels superseded runs. A run already producing "
            f"evidence outlives the push that superseded it."
        )


def test_no_workflow_shares_a_concurrency_group_across_commits():
    """The eviction hole is not exclusive to the heavy classes.

    `ci.yml` grouped by `github.ref`, so a merge train into main replaced each
    queued run with the next push's. Four merged commits (329576c3d,
    ef19b8175, c11767c5e, df408100e) ended up with no CI vector at all, and
    `cancel-in-progress: false` did nothing about it -- that flag governs
    STARTED runs, not the pending slot.

    A group is only safe if its key is immutable per commit, i.e. keyed by
    `github.sha`. Anything else lets a later commit inherit an earlier
    commit's slot and throw the earlier measurement away.
    """
    for path in sorted(WORKFLOWS.glob("*.yml")):
        text = path.read_text()
        match = re.search(r"^concurrency:\n(?:[ \t]+.*\n?)+", text, re.MULTILINE)
        if match is None:
            continue
        assert "github.sha" in match.group(0), (
            f"{path.name} declares a concurrency group that is not keyed by "
            f"github.sha. GitHub keeps ONE pending run per group, so a newer "
            f"commit evicts the queued run of an older one and that commit "
            f"never gets a CI vector. Drop the block, or key it "
            f"`ci-${{{{ github.sha }}}}` with cancel-in-progress: false."
        )


def test_attendance_roster_matches_the_heavy_workflows():
    """A heavy workflow missing from the roster is an instrument that can go
    quiet without the roll call noticing -- the exact defect that let eight
    cancelled runs pass unremarked."""
    from importlib import util

    spec = util.spec_from_file_location(
        "heavy_measurement_attendance", ROOT / "tools" / "heavy_measurement_attendance.py"
    )
    module = util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert set(module.HEAVY_ROSTER) == set(HEAVY_WORKFLOWS.values())
    for workflow, lease_class in HEAVY_WORKFLOWS.items():
        name = re.search(r"^name:\s*(.+)$", _text(workflow), re.MULTILINE).group(1).strip()
        assert module.HEAVY_ROSTER[lease_class] == name, (
            f"roster name for {lease_class} does not match {workflow}'s `name:`; "
            f"the roll call would never match this workflow's runs"
        )


def test_standalone_floor_workflows_stay_discrimination_only():
    for name in STANDALONE_FLOOR_WORKFLOWS:
        text = _text(name)
        for group in RETIRED_GROUPS:
            assert group not in text
        assert "zero_tolerance.py\n" not in text or "discrimination" in text.lower()


def test_orchestrator_still_runs_the_corpus_floors():
    """The floor set moved into one leased script -- ONE lease interval for the
    whole set, so no census interleaves between two axes and the complete set
    still comes from one pinned run. It must not have lost an axis on the way."""
    text = _text("factory-zero-tolerance.yml")
    assert "tools/run_sole_construction_floors.sh" in text
    floors = (ROOT / "tools" / "run_sole_construction_floors.sh").read_text()
    for script in (
        "native_crash_zero_tolerance.py",
        "bare_exception_zero_tolerance.py",
        "timeout_zero_tolerance.py",
        "silent_zero_tolerance.py",
        "factory_ownership_law.py",
        "construction_side_door_law.py",
    ):
        assert script in floors, f"the leased floor set must invoke {script}"
