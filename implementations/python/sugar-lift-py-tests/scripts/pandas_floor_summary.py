"""Native, conserved JSON testimony for installed-corpus floor measurements."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

SCHEMA = "pandas-floor-summary-v1"


def relative_files(paths: Sequence[Path], root: Path) -> list[str]:
    return sorted(
        path.resolve().relative_to(root.resolve()).as_posix() for path in paths
    )


def corpus_cid(files: Sequence[str]) -> str:
    preimage = json.dumps(list(files), separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(preimage.encode("utf-8")).hexdigest()


def floor_summary(
    *,
    floor: str,
    files: Sequence[str],
    rows: Sequence[Mapping[str, Any]],
    totals: Mapping[str, int],
    measured: bool,
    unmeasurable_reasons: Sequence[str] = (),
) -> dict[str, Any]:
    ordered_files = sorted(files)
    ordered_rows = sorted((dict(row) for row in rows), key=lambda row: str(row["file"]))
    if not ordered_files:
        raise ValueError("a floor summary requires a non-empty measured corpus")
    if [str(row["file"]) for row in ordered_rows] != ordered_files:
        raise ValueError("floor rows must account for every corpus file exactly once")
    reasons = sorted(set(unmeasurable_reasons))
    if measured and reasons:
        raise ValueError("a measured floor cannot carry unmeasurable reasons")
    return {
        "kind": SCHEMA,
        "floor": floor,
        "measurement": "measured" if measured else "unmeasurable",
        "unmeasurableReasons": reasons,
        "corpus": {
            "files": ordered_files,
            "filesTotal": len(ordered_files),
            "manifestCid": corpus_cid(ordered_files),
        },
        "rows": ordered_rows,
        "totals": dict(sorted(totals.items())),
    }


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def write_floor_residual_v1(
    path: Path,
    *,
    residual_key: str,
    residual_count: int,
    floor: str,
    emission_fallback: str | None = None,
) -> None:
    """Minimal residual body for enrollment mint when full summary cannot seal.

    Enrollment cites residualCount under residualKey — never invents from exit.
    """
    if type(residual_count) is not int or residual_count < 0:
        raise ValueError(
            f"residual_count must be non-negative int; got {residual_count!r}"
        )
    body: dict[str, Any] = {
        "kind": "floor-residual-v1",
        "floor": floor,
        "residualKey": residual_key,
        "residualCount": residual_count,
    }
    if emission_fallback:
        body["emissionFallback"] = emission_fallback
    write_json(path, body)


def write_floor_summary_or_residual(
    path: Path,
    *,
    floor: str,
    residual_key: str,
    residual_count: int,
    files: Sequence[str],
    rows: Sequence[Mapping[str, Any]],
    totals: Mapping[str, int],
    measured: bool = True,
    unmeasurable_reasons: Sequence[str] = (),
) -> str:
    """Always emit residual magnitude for mint; full summary when conservation holds.

    Product residual is already computed (residual_count). A conservation failure
    in floor_summary must not erase that mass — fall back to floor-residual-v1
    so enrollment can cite residualCount (freeze night: exit=1 + no summary).
    """
    try:
        payload = floor_summary(
            floor=floor,
            files=files,
            rows=rows,
            totals=totals,
            measured=measured,
            unmeasurable_reasons=unmeasurable_reasons,
        )
        write_json(path, payload)
        return "full"
    except ValueError as error:
        write_floor_residual_v1(
            path,
            residual_key=residual_key,
            residual_count=residual_count,
            floor=floor,
            emission_fallback=f"{type(error).__name__}: {error}",
        )
        return "residual-only"
