"""CI matrix wire for recensus LPT k=8 (banked law #7055; matrix was follow-up).

The compose door, plan tool, and worker --plan-json/--shard-index path already
exist. This tooth locks the workflow fan-out so the serial walk cannot return
silently:

  plan → matrix shard s00..s07 (fail-fast: false) → compose sole seal

CRITICAL: compose runs when shards fail; missing seat → UNMEASURED, never a
partial seal of the seats that finished.
"""

from __future__ import annotations

from pathlib import Path

from repo_root_test_support import resolve_repo_root

ROOT = resolve_repo_root()
WORKFLOW = ROOT / ".github/workflows/control-effect-recensus.yml"


def test_recensus_workflow_is_lpt_k8_matrix_not_serial_monolith() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    # Three jobs: plan, shard matrix, compose.
    assert "jobs:" in text
    assert "plan:" in text
    assert "shard:" in text
    assert "compose:" in text
    # LPT k fixed at 8 (same constant as tools/lpt_file_shards.DEFAULT_SHARD_COUNT).
    assert "RECENSUS_SHARD_COUNT: \"8\"" in text or "RECENSUS_SHARD_COUNT: '8'" in text
    assert "matrix:" in text
    assert "shard: [0, 1, 2, 3, 4, 5, 6, 7]" in text
    assert "fail-fast: false" in text
    # Workers emit partials only.
    assert "--plan-json" in text
    assert "--shard-index" in text
    assert "plan_control_effect_recensus_shards.py" in text
    # Sole seal door.
    assert "compose_control_effect_board.py" in text
    # Compose must not be gated on all shards green (UNMEASURED path).
    assert "if: always()" in text
    assert "needs.plan.result" in text
    # No single serial measure job without matrix (the pre-wire shape).
    # The old name "Phase: recensus measure (production CLI; no lease)" was one job.
    assert "Phase: recensus measure (production CLI; no lease)" not in text
    assert "Phase: measure shard partial only" in text


def test_compose_unmeasured_law_still_named_in_workflow() -> None:
    """Workflow copy must restate: never seal over finished shards alone."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "UNMEASURED" in text
    assert "missing" in text.lower()
    # Attendance dual-belt only on sealed board.
    assert "measurementClass" in text
    assert "bodyCid" in text


def test_lpt_prior_shelf_is_actions_cached_and_pin_keyed() -> None:
    """CI runners start clean — without actions/cache the shelf dies every run.

    Key must include corpus pin aggregate so a different pin is not the exact
    restore hit. Entries remain content-addressed by file bytes (#7040).
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "actions/cache/restore@v4" in text
    assert "actions/cache/save@v4" in text
    assert "SUGAR_LPT_PRIOR_DIR" in text
    assert ".cache/sugar/lpt-file-costs" in text
    assert "lpt-recensus-file-costs-" in text
    # Pin identity in the key (not tip-only).
    assert "aggregate_hash" in text
    assert "lpt-recensus-file-costs-${{ steps.pin.outputs.aggregate_hash }}" in text or (
        "lpt-recensus-file-costs-${{ needs.plan.outputs.aggregate_hash }}" in text
    )
    # Compose unions seat deltas so one full run fills the fleet shelf.
    assert "lpt-prior-union" in text or "union LPT prior" in text
    assert "control-effect-recensus-lpt-prior-" in text


def test_recensus_write_through_file_s_to_lpt_prior() -> None:
    """Every measured file_s must land on the CA prior — not only a hand-seed."""
    recensus = (
        ROOT
        / "implementations/python/sugar-lift-py-tests/scripts/control_effect_recensus.py"
    )
    src = recensus.read_text(encoding="utf-8")
    assert "ContentAddressedCostPrior" in src
    assert "put_for_path" in src
    assert "control-effect-recensus" in src
    assert "file_s" in src
    # Buffer during the lift; flush once at end (not per-file on hot path).
    assert "lpt_prior_rows" in src
    assert "mode=batch-end-of-lift" in src
    assert "lpt_prior_rows.append" in src
    # One put_for_path call site (the batch flush), not a per-file call.
    assert src.count("prior.put_for_path(") == 1
