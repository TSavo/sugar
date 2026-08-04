"""Acceptance: LPT k=8 on a real recensus file_s prior is flat at T/8.

Validation data (mr_pink, live recensus prior):
  T≈3524s  max_file=152.9s  median=0.98s  top40 share≈76.8%
  path-index%8 wall ≈624s (loads 298–624s)
  LPT k=8 wall ≈440.6s, flat, equal to T/8
  wall speedup ≈1.42x (NOT the 24.8x max/min imbalance figure)

Imbalance (max/min) and wall speedup are different numbers. Both matter;
only wall speedup is the clock gain.

max_file=152.9s: at k=8, T/8 (≈440s) dominates max_file, so work stealing
buys nothing here. Do not raise k for steal room — env tax is why k=8.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from sugar_lift_py_tests.repo_root import resolve_repo_root

ROOT = resolve_repo_root()
sys.path.insert(0, str(ROOT / "tools"))

from lpt_file_shards import equal_count_bins, lpt_bins  # noqa: E402

FIXTURE = ROOT / "tests/fixtures/lpt_recensus_file_s_prior.json"
K = 8


def _load_costs() -> dict[str, float]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    costs = {str(k): float(v) for k, v in data["costs"].items()}
    assert len(costs) >= 500, f"fixture too small: {len(costs)}"
    return costs


def test_lpt_k8_is_perfectly_flat_at_t_over_8() -> None:
    costs = _load_costs()
    files = list(costs)
    T = sum(costs.values())
    bins = lpt_bins(files, costs, K, missing_cost=0.0)
    loads = [sum(costs[f] for f in b) for b in bins]
    wall = max(loads)
    # Perfect LPT pack: wall equals T/k (within 0.1s float noise).
    assert abs(wall - T / K) < 0.1, (wall, T / K, loads)
    assert max(loads) - min(loads) < 0.1, loads


def test_path_index_mod_k_is_materially_worse_wall() -> None:
    costs = _load_costs()
    files = sorted(costs)
    T = sum(costs.values())
    eq_bins = equal_count_bins(files, K)
    eq_loads = [sum(costs[f] for f in b) for b in eq_bins]
    lpt = lpt_bins(files, costs, K, missing_cost=0.0)
    lpt_loads = [sum(costs[f] for f in b) for b in lpt]
    eq_wall = max(eq_loads)
    lpt_wall = max(lpt_loads)
    # Honest wall improvement is ~1.3–1.5x, not the max/min imbalance ratio.
    assert eq_wall / lpt_wall >= 1.25, (eq_wall, lpt_wall)
    assert lpt_wall <= T / K + 0.1
    # Imbalance under path% can be large even when wall speedup is modest.
    assert max(eq_loads) / min(eq_loads) >= 1.5


def test_path_mod_collocates_two_heaviest_frame_tests() -> None:
    """Concrete failure of the old key: two heaviest land on the same shard."""
    costs = _load_costs()
    top2 = sorted(costs.items(), key=lambda x: -x[1])[:2]
    assert top2[0][1] >= 150.0  # max_file ~152.9
    files = sorted(costs)
    s0 = files.index(top2[0][0]) % K
    s1 = files.index(top2[1][0]) % K
    assert s0 == s1, (top2, s0, s1)
    # LPT separates them (or would only share if pack forces it — with flat
    # T/8 >> max_file it always separates the two heaviest).
    bins = lpt_bins(list(costs), costs, K, missing_cost=0.0)
    seats = []
    for name, _ in top2:
        for i, b in enumerate(bins):
            if name in b:
                seats.append(i)
    assert seats[0] != seats[1], seats


def test_max_file_below_t_over_k_so_steal_buys_nothing_at_k8() -> None:
    costs = _load_costs()
    T = sum(costs.values())
    max_file = max(costs.values())
    assert max_file < T / K, (max_file, T / K)
    # Work stealing only helps when T/k < max_file; we refuse to raise k
    # for that regime because env tax is why k=8.
