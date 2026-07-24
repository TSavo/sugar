"""Heavy Python measurement: one orchestrator, not six workflows in one group.

GitHub concurrency keeps only one running + one pending per group. Multiple
PR workflows sharing `sugar-python-heavy-measurement` cancel each other even
with cancel-in-progress: false. Corpus floors must run under one orchestrator.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
GROUP = "sugar-python-heavy-measurement"

# PR-triggered floor scanners that used to fight for the group.
STANDALONE_FLOOR_WORKFLOWS = (
    "bare-exception-zero-tolerance.yml",
    "timeout-zero-tolerance.yml",
    "native-crash-zero-tolerance.yml",
)

ORCHESTRATOR = "factory-zero-tolerance.yml"


def test_standalone_floor_workflows_do_not_claim_heavy_concurrency_group() -> None:
    for name in STANDALONE_FLOOR_WORKFLOWS:
        text = (WORKFLOWS / name).read_text()
        assert GROUP not in text, (
            f"{name} must not use {GROUP}; full corpus floors run only under "
            f"{ORCHESTRATOR}"
        )
        # Discrimination only — no full-corpus script invocation.
        assert "zero_tolerance.py\n" not in text or "discrimination" in text.lower()


def test_orchestrator_owns_heavy_group_and_runs_corpus_floors() -> None:
    text = (WORKFLOWS / ORCHESTRATOR).read_text()
    assert f"group: {GROUP}" in text
    assert "cancel-in-progress: false" in text
    for script in (
        "native_crash_zero_tolerance.py",
        "bare_exception_zero_tolerance.py",
        "timeout_zero_tolerance.py",
        "silent_zero_tolerance.py",
    ):
        assert script in text, f"{ORCHESTRATOR} must invoke {script}"
