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
