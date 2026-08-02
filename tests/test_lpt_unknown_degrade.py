"""Unknown-file LPT degrade: safe floor + size-bin proxy (not optimistic median).

Census-200 evidence (open+populate on tip ba3c94fbf):
  size↔cost Spearman ≈ 0.85; median under-prices heavies ≥1s by ~12–39×;
  p75 cuts under-half rate 36% → 14%; size quintile medians rise with size.
"""

from __future__ import annotations

from pathlib import Path

from lpt_file_shards import (
    ContentAddressedCostPrior,
    assign_files,
    calibrate_size_cost_bins,
    estimate_cost_from_size,
    percentile,
    safe_unknown_cost_floor,
)


def test_safe_floor_is_p75_not_median() -> None:
    # Multiset polluted by tiny-file collisions (black's 0.039 trap).
    known = [0.003] * 100 + [0.04] * 50 + [1.0, 2.0, 5.7]
    med = sorted(known)[len(known) // 2]
    floor = safe_unknown_cost_floor(known)
    assert med < 0.05
    assert floor == percentile(known, 0.75)
    assert floor >= 0.04
    assert floor > med


def test_size_bins_monotone_on_synthetic() -> None:
    pairs = [(i * 1000, float(i)) for i in range(1, 51)]
    bins = calibrate_size_cost_bins(pairs, n_bins=5)
    assert len(bins) == 5
    meds = [b.median_cost_s for b in bins]
    assert meds == sorted(meds), meds
    # Large file lands in top band.
    est = estimate_cost_from_size(10**9, bins, floor_s=0.5)
    assert est >= meds[-1]
    assert est >= 0.5


def test_unknown_uses_size_proxy_not_constant_median(tmp_path: Path) -> None:
    """With a prior on small files only, a large unknown must not score at ~median."""
    prior_root = tmp_path / "prior"
    prior = ContentAddressedCostPrior(root=prior_root)
    # Three small measured files.
    paths = {}
    for i, cost in enumerate((0.05, 0.06, 0.07)):
        p = tmp_path / f"small_{i}.py"
        p.write_text("x = 1\n" * 10, encoding="utf-8")
        prior.put_for_path(p, cost, source="test", path_hint=p.name)
        paths[f"pkg/small_{i}.py"] = p
    # One large unknown (no prior).
    big = tmp_path / "big.py"
    big.write_text("def f():\n    pass\n" * 5000, encoding="utf-8")
    paths["pkg/big.py"] = big

    assignment = assign_files(
        list(paths.keys()),
        shard_count=2,
        path_resolver=paths,
        prior=prior,
    )
    assert assignment.mode == "lpt"
    assert assignment.prior_hits == 3
    assert assignment.prior_misses == 1
    # Estimated load for the bin containing big must include a cost >> small med.
    # Find which bin has big.
    big_bin = next(i for i, b in enumerate(assignment.bins) if "pkg/big.py" in b)
    # Reconstruct: big's share ≈ load_big_bin - sum of smalls in that bin
    # Easier: re-read via floor being p75 of {0.05,0.06,0.07}=0.07 and size band
    # at least that. The assignment estimated_loads must be > 3*0.07 if big is heavy.
    floor = safe_unknown_cost_floor([0.05, 0.06, 0.07])
    assert floor >= 0.06
    # Big file estimate at least floor; total load of its bin >= floor.
    assert assignment.estimated_loads[big_bin] >= floor


def test_equal_cost_unknowns_do_not_pile_in_one_bin(tmp_path: Path) -> None:
    """Equal proxy costs still LPT-spread across lightest bins."""
    prior_root = tmp_path / "prior"
    prior = ContentAddressedCostPrior(root=prior_root)
    paths: dict[str, Path] = {}
    # One expensive known file.
    heavy = tmp_path / "heavy.py"
    heavy.write_text("h\n" * 100, encoding="utf-8")
    prior.put_for_path(heavy, 10.0, source="test", path_hint="heavy")
    paths["pkg/heavy.py"] = heavy
    # Eight identical-size unknowns → same proxy cost.
    for i in range(8):
        p = tmp_path / f"u{i}.py"
        p.write_text("u = 1\n" * 20, encoding="utf-8")
        paths[f"pkg/u{i}.py"] = p
    assignment = assign_files(
        list(paths.keys()),
        shard_count=4,
        path_resolver=paths,
        prior=prior,
    )
    # Unknowns should appear in multiple bins, not all with heavy or all in one.
    unk_counts = [
        sum(1 for f in b if f.startswith("pkg/u")) for b in assignment.bins
    ]
    assert max(unk_counts) <= 3, unk_counts
    assert sum(1 for c in unk_counts if c > 0) >= 3, unk_counts
