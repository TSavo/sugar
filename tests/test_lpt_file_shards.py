"""Teeth: LPT packing + content-addressed prior + honest equal-count degrade."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from sugar_lift_py_tests.repo_root import resolve_repo_root

ROOT = resolve_repo_root()
sys.path.insert(0, str(ROOT / "tools"))

from lpt_file_shards import (  # noqa: E402
    ContentAddressedCostPrior,
    assign_files,
    equal_count_bins,
    lpt_bins,
)


def test_lpt_assigns_heaviest_first_to_lightest_bin() -> None:
    files = ["a", "b", "c", "d"]
    costs = {"a": 100.0, "b": 90.0, "c": 10.0, "d": 5.0}
    bins = lpt_bins(files, costs, 2, missing_cost=1.0)
    # a->0, b->1, c->1 (10 on 90), d->0 (5 on 100) => loads 105 / 100
    assert set(bins[0]) == {"a", "d"} or set(bins[0]) == {"a", "c"}
    loads = [sum(costs[x] for x in b) for b in bins]
    assert max(loads) <= 105.0
    assert abs(loads[0] - loads[1]) <= 15.0


def test_equal_count_is_index_mod_k() -> None:
    files = [f"f{i}" for i in range(8)]
    bins = equal_count_bins(files, 4)
    assert bins[0] == ["f0", "f4"]
    assert bins[3] == ["f3", "f7"]


def test_no_prior_degrades_to_equal_count(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("SUGAR_LPT_PRIOR_DIR", str(tmp_path / "prior"))
    files = ["x.py", "y.py", "z.py", "w.py"]
    # no files on disk → no cid hits
    assignment = assign_files(files, shard_count=2, path_resolver={})
    assert assignment.mode == "equal-count"
    assert assignment.prior_hits == 0


def test_prior_write_and_lpt_second_pass(tmp_path: Path, monkeypatch) -> None:
    prior_root = tmp_path / "prior"
    monkeypatch.setenv("SUGAR_LPT_PRIOR_DIR", str(prior_root))
    root = tmp_path / "src"
    root.mkdir()
    paths = {}
    costs = {"heavy.py": 100.0, "mid.py": 50.0, "light.py": 1.0, "tiny.py": 1.0}
    for name, cost in costs.items():
        p = root / name
        p.write_text(f"# {name} {cost}\n" + ("x" * int(cost)), encoding="utf-8")
        paths[name] = p
    prior = ContentAddressedCostPrior(prior_root)
    for name, cost in costs.items():
        prior.put_for_path(paths[name], cost, source="test")
    assignment = assign_files(
        list(costs),
        shard_count=2,
        path_resolver=paths,
        prior=prior,
    )
    assert assignment.mode == "lpt"
    assert assignment.prior_hits == 4
    loads = assignment.estimated_loads
    # LPT packs 100+1 vs 50+1 — far better than dumping both heavies on one bin.
    assert max(loads) < 120.0
    assert min(loads) >= 50.0
    assert sum(loads) == pytest.approx(152.0)



def test_job_log_line_names_mode() -> None:
    files = ["a", "b"]
    a = assign_files(files, shard_count=2, path_resolver={})
    line = a.job_log_line(population="suite-pytest")
    assert "mode=equal-count" in line
    assert "population=suite-pytest" in line
