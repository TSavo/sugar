"""Recensus write-through: measured file_s → content-addressed LPT prior.

Without this, CI plans degrade to equal-count forever after a hand-seed dies
on a clean runner. #7040 defined the shelf; process-floor enum already
write-throughs; recensus must too.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from repo_root_test_support import resolve_repo_root

ROOT = resolve_repo_root()
sys.path.insert(0, str(ROOT / "tools"))

from lpt_file_shards import ContentAddressedCostPrior, assign_files  # noqa: E402


def test_put_for_path_then_assign_is_lpt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    prior_root = tmp_path / "prior"
    monkeypatch.setenv("SUGAR_LPT_PRIOR_DIR", str(prior_root))
    corpus = tmp_path / "pandas"
    corpus.mkdir()
    costs = {
        "heavy.py": 12.0,
        "mid.py": 5.0,
        "light_a.py": 0.2,
        "light_b.py": 0.2,
    }
    paths: dict[str, Path] = {}
    for name, cost in costs.items():
        p = corpus / name
        p.write_text(f"# {name}\n" + ("x" * int(cost * 10)), encoding="utf-8")
        paths[name] = p
    prior = ContentAddressedCostPrior(prior_root)
    for name, cost in costs.items():
        cid = prior.put_for_path(
            paths[name], cost, source="control-effect-recensus", path_hint=name
        )
        assert cid is not None
    assignment = assign_files(
        list(costs),
        shard_count=2,
        path_resolver=paths,
        prior=prior,
    )
    assert assignment.mode == "lpt"
    assert assignment.prior_hits == 4
    # Heaviest alone or with lights — pole not both mid+heavy.
    assert max(assignment.estimated_loads) < 13.0
