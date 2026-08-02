"""Native, conserved JSON testimony for installed-corpus floor measurements."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

_PACKAGE_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_PACKAGE_SRC) not in sys.path:
    sys.path.insert(0, str(_PACKAGE_SRC))

from sugar_lift_py_tests.conservation_mint import (  # noqa: E402
    ConservationFailure,
    ConservedBody,
    seal_after_validation,
)

SCHEMA = "pandas-floor-summary-v1"
VALIDATOR_STAGE_ID = "pandas-floor-summary.rows-account-for-corpus/v1"


def relative_files(paths: Sequence[Path], root: Path) -> list[str]:
    return sorted(
        path.resolve().relative_to(root.resolve()).as_posix() for path in paths
    )


def corpus_cid(files: Sequence[str]) -> str:
    preimage = json.dumps(list(files), separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(preimage.encode("utf-8")).hexdigest()


def _floor_summary_outcome(
    *,
    floor: str,
    files: Sequence[str],
    rows: Sequence[Mapping[str, Any]],
    totals: Mapping[str, int],
    measured: bool,
    unmeasurable_reasons: Sequence[str] = (),
) -> ConservedBody | ConservationFailure:
    ordered_files = sorted(files)
    ordered_rows = sorted((dict(row) for row in rows), key=lambda row: str(row["file"]))
    reasons = sorted(set(unmeasurable_reasons))
    payload = {
        "kind": SCHEMA,
        "floor": floor,
        "unmeasurableReasons": [],
        "corpus": {
            "files": ordered_files,
            "filesTotal": len(ordered_files),
            "manifestCid": corpus_cid(ordered_files),
        },
        "rows": ordered_rows,
        "totals": dict(sorted(totals.items())),
    }

    def validate() -> None:
        if not measured:
            reason = "; ".join(reasons) or "floor producer marked measurement incomplete"
            raise ValueError(reason)
        if not ordered_files:
            raise ValueError("a floor summary requires a non-empty measured corpus")
        if [str(row["file"]) for row in ordered_rows] != ordered_files:
            raise ValueError("floor rows must account for every corpus file exactly once")
        if reasons:
            raise ValueError("a measured floor cannot carry unmeasurable reasons")

    return seal_after_validation(
        measured_payload=payload,
        input_key_manifest=[{"file": file} for file in ordered_files],
        output_key_manifest=[{"file": str(row["file"])} for row in ordered_rows],
        validator_stage_id=VALIDATOR_STAGE_ID,
        validator_source_path=Path(__file__).resolve(),
        validate=validate,
    )


def floor_summary(
    *,
    floor: str,
    files: Sequence[str],
    rows: Sequence[Mapping[str, Any]],
    totals: Mapping[str, int],
    measured: bool,
    unmeasurable_reasons: Sequence[str] = (),
) -> dict[str, Any]:
    outcome = _floor_summary_outcome(
        floor=floor,
        files=files,
        rows=rows,
        totals=totals,
        measured=measured,
        unmeasurable_reasons=unmeasurable_reasons,
    )
    if isinstance(outcome, ConservationFailure):
        if not measured:
            body = outcome.to_wire()
            body.update(
                {
                    "kind": "floor-unmeasured-v1",
                    "floor": floor,
                    "residualCount": None,
                    "unmeasurableReasons": [outcome.reason],
                }
            )
            return body
        reason = outcome.reason.partition(": ")[2] or outcome.reason
        raise ValueError(reason)
    return outcome.to_wire()


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def write_floor_unmeasured_v1(
    path: Path,
    *,
    residual_key: str,
    floor: str,
    failure: ConservationFailure,
) -> None:
    """Emit an explicit refusal when full-summary conservation cannot seal.

    The producer may already hold an in-memory candidate magnitude, but failed
    conservation makes that candidate non-testimony.  The refusal therefore
    carries no numeric residual for a downstream reader to reseal.
    """
    body = failure.to_wire()
    body.update(
        {
            "kind": "floor-unmeasured-v1",
            "floor": floor,
            "residualKey": residual_key,
            "residualCount": None,
            "unmeasurableReasons": [failure.reason],
        }
    )
    write_json(path, body)


def write_floor_summary_or_unmeasured(
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
    """Emit conserved testimony, otherwise an explicit UNMEASURED envelope.

    ``residual_count`` is deliberately accepted at the shared producer door so
    callers cannot accidentally route around it.  It is serialized only inside
    a conserved full summary (through ``totals``).  A conservation failure must
    never promote the in-memory candidate into a sealed residual body.
    """
    outcome = _floor_summary_outcome(
        floor=floor,
        files=files,
        rows=rows,
        totals=totals,
        measured=measured,
        unmeasurable_reasons=unmeasurable_reasons,
    )
    if isinstance(outcome, ConservationFailure):
        write_floor_unmeasured_v1(
            path,
            residual_key=residual_key,
            floor=floor,
            failure=outcome,
        )
        return "unmeasured"
    write_json(path, outcome.to_wire())
    return "full"
