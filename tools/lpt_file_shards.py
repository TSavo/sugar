#!/usr/bin/env python3
"""LPT file sharding on a content-addressed measured cost prior.

Keep k fixed (suite/floors: 8). Change the SPLIT KEY:

  equal-count (path-index % k)  →  up to ~25× wall imbalance on live suite
  LPT on measured file_s prior →  wall ≈ T/k until the max-file floor

Algorithm (classic multiprocessor LPT):
  1. Sort files by prior cost descending (path asc on ties — deterministic).
  2. Assign each file to the currently lightest shard (lowest index on ties).

Prior:
  Content-addressed by file bytes (same cid vocabulary as process-floor cache).
  Unchanged files keep their cost forever. First cold run has no prior →
  equal-count AND writes the prior so the second run is fast. No silent pretend.

Job log:
  Always print which mode ran (lpt vs equal-count) and prior hit rate.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence


DEFAULT_SHARD_COUNT = 8
PRIOR_SCHEMA = "lpt-file-cost/v1"


def _blake3_512(data: bytes) -> str:
    try:
        import blake3  # type: ignore

        return "blake3-512:" + blake3.blake3(data, max_threads=1).digest(64).hex()
    except Exception:  # noqa: BLE001
        return "sha256:" + hashlib.sha256(data).hexdigest()


def file_content_cid(path: Path) -> str:
    return _blake3_512(Path(path).read_bytes())


def resolve_prior_root() -> Path | None:
    """Durable prior root, or None to disable.

    Prefer ``SUGAR_LPT_PRIOR_DIR``. Default: workspace
    ``.cache/sugar/lpt-file-costs`` (writable in GHA; fleet-shared via
    actions/cache). Disable: ``SUGAR_LPT_PRIOR_DIR=off``.
    """
    explicit = os.environ.get("SUGAR_LPT_PRIOR_DIR")
    if explicit is not None:
        text = explicit.strip()
        if text in {"", "0", "off", "none", "disabled"}:
            return None
        return Path(text).expanduser().resolve()
    workspace = os.environ.get("GITHUB_WORKSPACE")
    if workspace:
        return Path(workspace).resolve() / ".cache" / "sugar" / "lpt-file-costs"
    home = os.environ.get("HOME")
    if home:
        return Path(home).expanduser().resolve() / ".cache" / "sugar" / "lpt-file-costs"
    return Path(".cache/sugar/lpt-file-costs").resolve()


def _cid_filename(cid: str) -> str:
    # Filesystem-safe: drop scheme punctuation.
    return cid.replace(":", "_").replace("/", "_") + ".json"


@dataclass(frozen=True)
class PriorHit:
    content_cid: str
    cost_s: float
    source: str


class ContentAddressedCostPrior:
    """Per-file-content cost shelf. Path is only a lookup handle for bytes."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root if root is not None else resolve_prior_root()

    @property
    def enabled(self) -> bool:
        return self.root is not None

    def _path_for_cid(self, cid: str) -> Path | None:
        if self.root is None:
            return None
        return self.root / _cid_filename(cid)

    def get_by_cid(self, cid: str) -> PriorHit | None:
        path = self._path_for_cid(cid)
        if path is None or not path.is_file():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if data.get("schema") != PRIOR_SCHEMA:
            return None
        try:
            cost = float(data["cost_s"])
        except (KeyError, TypeError, ValueError):
            return None
        if cost < 0:
            return None
        return PriorHit(
            content_cid=str(data.get("contentCid") or cid),
            cost_s=cost,
            source=str(data.get("source") or "unknown"),
        )

    def get_for_path(self, path: Path) -> PriorHit | None:
        try:
            cid = file_content_cid(path)
        except OSError:
            return None
        return self.get_by_cid(cid)

    def put_for_path(
        self,
        path: Path,
        cost_s: float,
        *,
        source: str,
        path_hint: str | None = None,
    ) -> str | None:
        """Write/overwrite prior for this file's content. Returns cid or None."""
        if self.root is None or cost_s < 0:
            return None
        try:
            data = Path(path).read_bytes()
        except OSError:
            return None
        cid = _blake3_512(data)
        self.root.mkdir(parents=True, exist_ok=True)
        out = self._path_for_cid(cid)
        assert out is not None
        payload = {
            "schema": PRIOR_SCHEMA,
            "contentCid": cid,
            "cost_s": round(float(cost_s), 6),
            "source": source,
            "pathHint": path_hint or Path(path).as_posix(),
        }
        tmp = out.with_suffix(out.suffix + ".tmp")
        tmp.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tmp.replace(out)
        return cid

    def costs_for_paths(
        self, paths: Mapping[str, Path]
    ) -> tuple[dict[str, float], int, int]:
        """Map roster key → cost_s for keys with a prior.

        Returns (costs, hits, misses).
        """
        costs: dict[str, float] = {}
        hits = 0
        misses = 0
        for key, path in paths.items():
            hit = self.get_for_path(path)
            if hit is None:
                misses += 1
                continue
            costs[key] = hit.cost_s
            hits += 1
        return costs, hits, misses


def percentile(values: Sequence[float], p: float) -> float:
    """Linear-interpolation-free nearest-rank percentile on a non-empty sequence."""
    if not values:
        raise ValueError("percentile on empty sequence")
    if p <= 0:
        return float(min(values))
    if p >= 1:
        return float(max(values))
    ordered = sorted(float(v) for v in values)
    # nearest-rank: index = ceil(p * n) - 1
    idx = min(len(ordered) - 1, max(0, int(p * len(ordered) + 0.999999999) - 1))
    return ordered[idx]


def safe_unknown_cost_floor(known_costs: Sequence[float]) -> float:
    """Conservative constant floor for files with no prior and no usable proxy.

    Measured census-200 (open+populate): median 0.147s under-prices heavies by
    ~12× (median heavy ≥1s) to 39× (worst). p75 (~0.54s) cuts under-half rate
    from 36% to 14%. Never use the median of hit costs when tiny content-CID
    collisions dominate the hit multiset (that produced the optimistic 0.039s).
    """
    if not known_costs:
        return 1.0  # no evidence — one second, not zero
    return max(percentile(known_costs, 0.75), 0.0)


@dataclass(frozen=True)
class SizeCostBin:
    """One size band → measured median cost (calibrated from prior hits)."""

    max_size: int  # inclusive upper bound (last bin uses a huge sentinel)
    median_cost_s: float


def calibrate_size_cost_bins(
    size_cost_pairs: Sequence[tuple[int, float]],
    *,
    n_bins: int = 5,
) -> tuple[SizeCostBin, ...]:
    """Build size→cost bins from measured (size_bytes, cost_s) pairs.

    Spearman size↔cost on census-200 was ~0.85 (rank); linear R² only ~0.18.
    Quintile medians capture the monotone lift without pretending linearity.
    """
    if n_bins < 1:
        raise ValueError("n_bins must be >= 1")
    pairs = [(int(s), float(c)) for s, c in size_cost_pairs if s >= 0 and c >= 0]
    if not pairs:
        return (SizeCostBin(max_size=2**62, median_cost_s=1.0),)
    pairs.sort(key=lambda t: (t[0], t[1]))
    n = len(pairs)
    bins: list[SizeCostBin] = []
    for i in range(n_bins):
        lo = (i * n) // n_bins
        hi = ((i + 1) * n) // n_bins
        chunk = pairs[lo:hi]
        if not chunk:
            continue
        costs = sorted(c for _, c in chunk)
        med = costs[len(costs) // 2]
        max_size = chunk[-1][0] if i < n_bins - 1 else 2**62
        bins.append(SizeCostBin(max_size=max_size, median_cost_s=med))
    if not bins:
        return (SizeCostBin(max_size=2**62, median_cost_s=1.0),)
    # Ensure last bin is open-ended.
    last = bins[-1]
    bins[-1] = SizeCostBin(max_size=2**62, median_cost_s=last.median_cost_s)
    return tuple(bins)


def estimate_cost_from_size(
    size_bytes: int,
    bins: Sequence[SizeCostBin],
    *,
    floor_s: float,
) -> float:
    """Proxy cost for an unknown file: size-bin median, floored at p75 known."""
    if size_bytes < 0:
        size_bytes = 0
    est = floor_s
    for band in bins:
        if size_bytes <= band.max_size:
            est = band.median_cost_s
            break
    return max(float(floor_s), float(est))


def equal_count_bins(files: Sequence[str], shard_count: int) -> list[list[str]]:
    """Path-index % k on the given order (caller should sort for stability)."""
    if shard_count < 1:
        raise ValueError("shard_count must be >= 1")
    bins: list[list[str]] = [[] for _ in range(shard_count)]
    for i, path in enumerate(files):
        bins[i % shard_count].append(path)
    return bins


def lpt_bins(
    files: Sequence[str],
    costs: Mapping[str, float],
    shard_count: int,
    *,
    missing_cost: float,
) -> list[list[str]]:
    """Longest-processing-time-first multiprocessor packing."""
    if shard_count < 1:
        raise ValueError("shard_count must be >= 1")
    if missing_cost < 0:
        raise ValueError("missing_cost must be >= 0")

    def sort_key(path: str) -> tuple[float, str]:
        cost = costs.get(path, missing_cost)
        return (-float(cost), path)

    ordered = sorted(files, key=sort_key)
    bins: list[list[str]] = [[] for _ in range(shard_count)]
    loads = [0.0] * shard_count
    for path in ordered:
        cost = float(costs.get(path, missing_cost))
        # Lightest bin; lowest index on ties — deterministic.
        target = min(range(shard_count), key=lambda i: (loads[i], i))
        bins[target].append(path)
        loads[target] += cost
    return bins


@dataclass(frozen=True)
class ShardAssignment:
    bins: list[list[str]]
    mode: str  # "lpt" | "equal-count"
    prior_hits: int
    prior_misses: int
    shard_count: int
    estimated_loads: list[float]

    def job_log_line(self, *, population: str) -> str:
        loads = ",".join(f"{x:.1f}" for x in self.estimated_loads)
        return (
            f"JOB_LOG phase=lpt-shard-assign population={population} "
            f"mode={self.mode} k={self.shard_count} "
            f"prior_hits={self.prior_hits} prior_misses={self.prior_misses} "
            f"est_load_s=[{loads}]"
        )


def assign_files(
    files: Sequence[str],
    *,
    shard_count: int = DEFAULT_SHARD_COUNT,
    path_resolver: Mapping[str, Path] | None = None,
    prior: ContentAddressedCostPrior | None = None,
) -> ShardAssignment:
    """Assign files to shards: LPT when any prior exists, else equal-count.

    ``path_resolver`` maps roster key → filesystem path for content cid.
    When omitted, equal-count only (no path bytes to hash).

    Unknown-file degrade (no prior entry) — safety law from census-200:
      * Floor at **p75 of known costs**, never the median of the hit multiset
        (tiny content-CID collisions made median ≈ 0.039s while heavies are 1–5s).
      * When a filesystem path is available, score the unknown at
        ``max(floor, size-bin median)`` calibrated from hit (size, cost) pairs
        (Spearman size↔cost ≈ 0.85; size quintile medians rise 0.015→0.88s).
      * LPT then packs known + estimated unknowns together — equal-cost unknowns
        naturally fan across lightest bins (not one pile). No separate RR pass
        required when estimates differ by size.
    """
    ordered = list(files)
    prior = prior if prior is not None else ContentAddressedCostPrior()
    costs: dict[str, float] = {}
    hits = 0
    misses = len(ordered)
    prior_disabled = not prior.enabled
    path_map: dict[str, Path] = {}
    if path_resolver is not None and prior.enabled and ordered:
        path_map = {f: path_resolver[f] for f in ordered if f in path_resolver}
        costs, hits, misses = prior.costs_for_paths(path_map)
        # Files without a resolvable path count as misses.
        for f in ordered:
            if f not in path_resolver and f not in costs:
                misses += 1

    if hits == 0:
        bins = equal_count_bins(sorted(ordered), shard_count)
        loads = [float(len(b)) for b in bins]  # unit cost under equal-count
        # Tag mode so callers can narrate shelf-disabled vs empty shelf.
        mode = "equal-count-prior-disabled" if prior_disabled else "equal-count"
        return ShardAssignment(
            bins=bins,
            mode=mode,
            prior_hits=0,
            prior_misses=misses if ordered else 0,
            shard_count=shard_count,
            estimated_loads=loads,
        )

    known = list(costs.values())
    floor_s = safe_unknown_cost_floor(known)
    # Calibrate size bins from hits that still have a resolvable path.
    size_pairs: list[tuple[int, float]] = []
    for key, cost in costs.items():
        path = path_map.get(key)
        if path is None:
            continue
        try:
            size_pairs.append((path.stat().st_size, float(cost)))
        except OSError:
            continue
    size_bins = calibrate_size_cost_bins(size_pairs)

    # Fill per-file estimates for misses (do not leave them on a single constant
    # that both under-prices heavies and clusters equal-weight unknowns).
    estimated = dict(costs)
    for f in ordered:
        if f in estimated:
            continue
        path = path_map.get(f) if path_map else None
        if path is not None:
            try:
                size = path.stat().st_size
            except OSError:
                estimated[f] = floor_s
            else:
                estimated[f] = estimate_cost_from_size(
                    size, size_bins, floor_s=floor_s
                )
        else:
            estimated[f] = floor_s

    # missing_cost is only a residual fallback inside lpt_bins for keys absent
    # from ``estimated`` (should be none); keep it at the safe floor.
    bins = lpt_bins(ordered, estimated, shard_count, missing_cost=floor_s)
    loads = [sum(float(estimated.get(p, floor_s)) for p in b) for b in bins]
    return ShardAssignment(
        bins=bins,
        mode="lpt",
        prior_hits=hits,
        prior_misses=misses,
        shard_count=shard_count,
        estimated_loads=loads,
    )


def narrate_assignment(assignment: ShardAssignment, *, population: str) -> None:
    """Emit assignment mode to the job log on stderr.

    Suite path emission prints paths on stdout for ``mapfile``; mixing JOB_LOG
    onto stdout would feed the log line into pytest as a fake test path.
    """
    line = assignment.job_log_line(population=population)
    print(line, file=sys.stderr, flush=True)
    if assignment.mode in {"equal-count", "equal-count-prior-disabled"}:
        if assignment.mode == "equal-count-prior-disabled":
            reason = (
                "prior-shelf-disabled (SUGAR_LPT_PRIOR_DIR=off or no root); "
                "equal-count is the only packer — not LPT"
            )
        else:
            reason = (
                "no prior hits for this population; degraded=equal-count "
                "(next run is LPT only if a prior write succeeds this campaign)"
            )
        print(
            f"JOB_LOG phase=lpt-shard-assign status=degraded "
            f"mode={assignment.mode} population={population} "
            f"prior_hits={assignment.prior_hits} "
            f"prior_misses={assignment.prior_misses} "
            f"reason={reason}",
            file=sys.stderr,
            flush=True,
        )


def load_costs_from_running_counts_jsonl(
    path: Path,
) -> dict[str, float]:
    """Parse recensus running-counts.jsonl → relative file → file_s (last wins)."""
    costs: dict[str, float] = {}
    if not path.is_file():
        return costs
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            file_key = row.get("file")
            file_s = row.get("file_s")
            if not isinstance(file_key, str) or file_s is None:
                continue
            try:
                costs[file_key] = float(file_s)
            except (TypeError, ValueError):
                continue
    return costs


def ingest_running_counts_into_prior(
    jsonl_path: Path,
    *,
    corpus_root: Path,
    prior: ContentAddressedCostPrior | None = None,
    source: str = "recensus-running-counts",
) -> int:
    """Materialize path-keyed running counts into content-addressed prior.

    Returns number of files written.
    """
    prior = prior if prior is not None else ContentAddressedCostPrior()
    if not prior.enabled:
        return 0
    costs = load_costs_from_running_counts_jsonl(jsonl_path)
    written = 0
    root = corpus_root.resolve()
    for rel, cost in costs.items():
        # running-counts may use "pandas/foo.py" or "foo.py"
        candidates = [root / rel, root / Path(rel).name]
        if "/" in rel:
            # strip leading package dir if present
            parts = rel.split("/", 1)
            if len(parts) == 2:
                candidates.append(root / parts[1])
        path = next((p for p in candidates if p.is_file()), None)
        if path is None:
            continue
        if prior.put_for_path(path, cost, source=source, path_hint=rel):
            written += 1
    return written


def filter_paths_for_shard(
    paths: Sequence[Path],
    *,
    root: Path,
    shard_index: int,
    shard_count: int = DEFAULT_SHARD_COUNT,
    population: str = "corpus",
    narrate: bool = True,
) -> list[Path]:
    """LPT/equal-count filter of absolute paths under ``root`` for one shard."""
    root = root.resolve()
    rels: list[str] = []
    by_rel: dict[str, Path] = {}
    for path in paths:
        path = path.resolve()
        rel = path.relative_to(root).as_posix()
        rels.append(rel)
        by_rel[rel] = path
    assignment = assign_files(
        rels,
        shard_count=shard_count,
        path_resolver=by_rel,
        prior=ContentAddressedCostPrior(),
    )
    if narrate:
        narrate_assignment(assignment, population=population)
    chosen = assignment.bins[shard_index]
    return [by_rel[rel] for rel in chosen]


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo-lpt", action="store_true")
    args = parser.parse_args(argv)
    if args.demo_lpt:
        files = [f"f{i}" for i in range(10)]
        costs = {f"f{i}": float(10 - i) for i in range(10)}
        bins = lpt_bins(files, costs, 3, missing_cost=1.0)
        print(json.dumps(bins))
        return 0
    parser.error("pass --demo-lpt or import as a library")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
