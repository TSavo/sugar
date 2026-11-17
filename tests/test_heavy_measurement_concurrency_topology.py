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


# The main scorecard's workflows realize the ruling per commit (#8964,
# #8416): a concurrency group per commit, and a ``supersede`` job that
# cancels the older runs on other commits (tools/main_scorecard_supersede.sh).
SCORECARD_WORKFLOWS = (
    "main-scorecard.yml",
    "main-scorecard-board.yml",
    "main-scorecard-numpy.yml",
)
SUPERSEDE = "tools/main_scorecard_supersede.sh"
# Dispatch-only diagnostics: every dispatch is its own trace (corpus, file,
# function, ref), so the group is the trace's and a re-dispatch of the same
# trace cancels the older one (``test_a_lift_trace_dispatch_supersedes_only_itself``).
DISPATCH_TRACE_WORKFLOWS = ("lift-trace.yml",)


def test_a_newer_push_cancels_the_superseded_run():
    """Owner ruling 2026-11-14, overrules #7118.

    On main a running run finishes first and the newest push replaces the
    queued run; on other refs a newer push cancels the running run.  The
    scorecard workflows are read by
    ``test_a_newer_scorecard_push_cancels_runs_on_older_commits``.
    """
    block = (
        "concurrency:\n"
        "  group: ${{ github.workflow }}-${{ github.ref }}\n"
        "  cancel-in-progress: ${{ github.ref != 'refs/heads/main' }}\n"
    )
    for path in sorted(WORKFLOWS.glob("*.yml")):
        if (
            path.name == "issue-claim-labels.yml"
            or path.name in SCORECARD_WORKFLOWS
            or path.name in DISPATCH_TRACE_WORKFLOWS
        ):
            continue
        assert block in path.read_text(), path.name


@pytest.mark.parametrize("workflow", DISPATCH_TRACE_WORKFLOWS)
def test_a_lift_trace_dispatch_supersedes_only_itself(workflow):
    """A trace runs on dispatch only, never on push or a schedule, and a
    newer dispatch of the same trace cancels the older; two traces of
    different files never queue behind each other."""
    text = _text(workflow)
    on = text[text.index("\non:\n") :].split("\n\n", 1)[0]
    assert "workflow_dispatch:" in on, on
    assert "push:" not in on and "schedule:" not in on and "pull_request" not in on, on
    concurrency = text[text.index("\nconcurrency:\n") :].split("\n\n", 1)[0]
    for name in ("corpus", "path", "function", "ref"):
        assert "${{ inputs.%s }}" % name in concurrency, concurrency
    assert "cancel-in-progress: true" in concurrency, concurrency
    # It posts nothing to the scorecard.
    assert "main_scorecard_post.py" not in text
    assert "issues: write" not in text


@pytest.mark.parametrize("workflow", SCORECARD_WORKFLOWS)
def test_a_newer_scorecard_push_cancels_runs_on_older_commits(workflow):
    """The ruling for the scorecard (#8964): a newer push cancels every run on
    an older commit, waiting or measuring, through the ``supersede`` job; a
    run is never cancelled by a run on its own commit.

    The concurrency group is the commit's, so no run waits behind, or is
    cancelled by, a run on another commit (``cancel-in-progress: false``: a
    second run on the same commit waits).  Every run's ``supersede`` job
    cancels, through the one script, this workflow's older runs on main
    whose commit is not its own."""
    text = _text(workflow)
    concurrency = text[text.index("\nconcurrency:\n") :].split("\n\n", 1)[0]
    assert "${{ github.sha }}" in concurrency, concurrency
    assert "cancel-in-progress: false" in concurrency, concurrency
    assert "${{ github.ref }}" not in concurrency, concurrency

    supersede = text[text.index("\n  supersede:\n") :].split("\n\n", 1)[0]
    assert "actions: write" in supersede, supersede
    runs = [line.strip() for line in supersede.splitlines()]
    assert f"run: bash {SUPERSEDE} {workflow}" in runs, supersede

    script = (ROOT / SUPERSEDE).read_text()
    # Older runs only (run ids only grow), on another commit only.
    assert ".databaseId < $me" in script
    assert '.headSha != \\"$sha\\"' in script
    assert "--branch main" in script
    assert 'gh run cancel "$id"' in script


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
