#!/usr/bin/env python3
"""Partition and_then / outcome_to_exitset construction panics from a LIVE board.

## Why this exists

The Deferred Exit design (third Exit variant) would relocate panics that today
fire mid-composition inside ``ExitSet.sequence`` / ``and_then`` →
``outcome_to_exitset``. A stale 9a board split was quoted as
``native=0, pending-contract=283, guarded=25 of 502`` — which **refuted** the
claim that the 283 mass is NativeOperationExitCarrierV1 (Deferred). That split
is stale; tip mass is unknown until control_effect_recensus produces a board.

This script is the **measurement instrument**, not a recensus. It does not
desugar the corpus. It classifies panics already recorded on a board artifact.

## Live recognition (not a curated offender list)

1. **Mouth census** — AST-walk production modules that own and_then / exit
   conversion panic mouths. Offenders classes are **named by those owners and
   observed strings** as they appear in source today. If a mouth moves, the
   classifier re-derives on next run.
2. **Board rows** — ``desugarConstructionPanics`` + ``constructionPanics`` from
   ``recensus.json`` (control_effect_recensus sole scoreboard). Each row is
   partitioned by matching the live mouths.

## Partition buckets

| Bucket | Meaning |
| --- | --- |
| ``native_deferred`` | ``NativeOperationExitCarrierV1`` undischarged at ``outcome_to_exitset`` or carrier-internal Deferred mouths |
| ``pending_contract`` | multi-demand / pending parameter-contract joins (ContractConditionalConstruction / rewrap_pending law) |
| ``guarded`` | GuardedValue / guarded-arm single-outcome law failures |
| ``other`` | remaining construction panics at the conversion boundary (unknown outcome variant, etc.) |

## Deferred design acceptance (owner ruling)

Deferred is a typed "not yet discharged". An undischarged Deferred that reaches
a terminus must still **panic** loud. Acceptance:

    count(loud named incompleteness) after Deferred ≥ count before
    (same mass relocated, never silenced)

This instrument reports the TIP split so that claim can be checked when Deferred
lands. It does not implement Deferred.

## Usage (when board exists)

```text
python3 implementations/python/sugar-lift-py-tests/scripts/and_then_construction_panic_partition.py \\
  --board /path/to/recensus.json
# prints R_* counts; EXIT=0 always if board readable (partition is measurement)
# EXIT=2 if --board missing or unreadable
# EXIT=1 if --require-and-then-mass and zero and_then-related rows (empty measure)
```

Self-check (no board, no corpus): ``--self-check`` plants synthetic rows from
live mouths and asserts classification. That is a tooth for the classifier,
not a corpus R.

SCOREBOARD_AUTHORITY = False
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

SCOREBOARD_AUTHORITY = False

# Production modules that own and_then / exit-conversion panic mouths.
# Paths relative to repo root. Enrollment is existence: missing path → red.
_MOUTH_MODULES = (
    "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/outcome/exit_set.py",
    "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/caller_parameter_contract.py",
    "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/single_outcome_law.py",
    "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/guarded_value.py",
)

BUCKETS = (
    "native_deferred",
    "pending_contract",
    "guarded",
    "other",
)


@dataclass(frozen=True)
class PanicMouth:
    """One construction_panic_gap call site derived from production AST."""

    path: str
    line: int
    owner: str | None
    observed: str | None
    bucket: str


@dataclass(frozen=True)
class BoardPanicRow:
    source: str  # desugarConstructionPanics | constructionPanics
    owner: str | None
    message: str
    where: str | None
    raw: dict[str, Any]


def repo_root_from_here() -> Path:
    here = Path(__file__).resolve()
    # .../sugar-lift-py-tests/scripts/this.py → repo root = parents[3]
    for parent in here.parents:
        if (
            (parent / "implementations" / "python").is_dir()
            and (parent / "Agents.md").is_file()
            or (parent / "AGENTS.md").is_file()
        ):
            return parent
    return here.parents[3]


def _const_str(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        # f-string — best-effort join of constant parts
        parts = []
        for v in node.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                parts.append(v.value)
            else:
                parts.append("*")
        return "".join(parts) if parts else None
    return None


def _call_name(node: ast.Call) -> str | None:
    f = node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return None


def extract_panic_mouths(repo: Path) -> list[PanicMouth]:
    """LIVE instrument: every construction_panic_gap in enrolled mouth modules."""
    mouths: list[PanicMouth] = []
    missing: list[str] = []
    for rel in _MOUTH_MODULES:
        path = repo / rel
        if not path.is_file():
            missing.append(rel)
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if _call_name(node) not in {"construction_panic_gap", "_gap"}:
                continue
            owner = None
            observed = None
            for kw in node.keywords:
                if kw.arg == "owner":
                    owner = _const_str(kw.value)
                    if owner is None and isinstance(kw.value, ast.Name):
                        # owner=owner variable — retain symbolic
                        owner = f"${kw.value.id}"
                if kw.arg == "observed":
                    observed = _const_str(kw.value)
            mouths.append(
                PanicMouth(
                    path=rel,
                    line=getattr(node, "lineno", 0),
                    owner=owner,
                    observed=observed,
                    bucket=classify_mouth(owner, observed),
                )
            )
    if missing:
        raise FileNotFoundError(
            "and_then panic mouth modules missing (enrollment is existence): "
            + ", ".join(missing)
        )
    return mouths


def classify_mouth(owner: str | None, observed: str | None) -> str:
    """Partition one production panic mouth (source-derived)."""
    o = (owner or "").strip()
    obs = (observed or "").lower()
    text = f"{o} {obs}".lower()

    # Deferred / native carrier — the object under design
    if o == "outcome_to_exitset" and "undischarged native" in obs:
        return "native_deferred"
    if "nativeoperationexitcarrier" in o.lower():
        return "native_deferred"
    if "native operation" in obs and "undischarged" in obs:
        return "native_deferred"

    # Pending-contract multi-demand joins
    if "contractconditionalconstruction" in o.lower():
        return "pending_contract"
    if "pending parameter contract" in text or "pending_contract" in text:
        return "pending_contract"
    if "distinct pending" in text or "demand set" in text:
        return "pending_contract"
    if "rewrap_pending" in text or o.endswith(".and_then") and "contract" in o.lower():
        return "pending_contract"

    # Guarded arm laws (owner often "GuardedValue.*" or call-site law name)
    if o.startswith("GuardedValue") or "guardedvalue" in o.lower():
        return "guarded"
    if "guarded" in o.lower():
        return "guarded"
    if "single_outcome" in o.lower() or "require_single_value" in text:
        return "guarded"
    if "arm answered with" in text and "partition" in text:
        return "guarded"
    if "no surviving face to carry" in text and "pending" in text:
        return "pending_contract"

    # outcome_to_exitset unknown variant (not native carrier)
    if o == "outcome_to_exitset":
        return "other"

    return "other"


def classify_board_row(row: BoardPanicRow) -> str:
    """Same predicates as mouths, applied to board testimony."""
    return classify_mouth(row.owner, row.message)


def load_board_panic_rows(board_path: Path) -> list[BoardPanicRow]:
    data = json.loads(board_path.read_text(encoding="utf-8"))
    rows: list[BoardPanicRow] = []

    def pull(key: str, items: Any) -> None:
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            owner = item.get("owner")
            if owner is not None and not isinstance(owner, str):
                owner = str(owner)
            message = item.get("message") or item.get("observed") or ""
            if not isinstance(message, str):
                message = str(message)
            where = item.get("where") or item.get("blame")
            if where is not None and not isinstance(where, str):
                where = str(where)
            # Nested ConstructionGap-style fields
            info = item.get("info")
            if isinstance(info, dict):
                owner = info.get("owner", owner)
                if isinstance(info.get("observed"), str) and not message:
                    message = info["observed"]
                message = (
                    f"owner={info.get('owner')} observed={info.get('observed')} "
                    f"requested={info.get('requested')} fix={info.get('fix')} "
                    f"{message}"
                )
            rows.append(
                BoardPanicRow(
                    source=key,
                    owner=owner if isinstance(owner, str) else None,
                    message=message,
                    where=where if isinstance(where, str) else None,
                    raw=item,
                )
            )

    pull("desugarConstructionPanics", data.get("desugarConstructionPanics"))
    pull("constructionPanics", data.get("constructionPanics"))
    # Some boards nest under floor result
    for nested_key in ("result", "controlEffect", "floor"):
        nested = data.get(nested_key)
        if isinstance(nested, dict):
            pull(
                f"{nested_key}.desugarConstructionPanics",
                nested.get("desugarConstructionPanics"),
            )
            pull(
                f"{nested_key}.constructionPanics",
                nested.get("constructionPanics"),
            )
    return rows


def is_and_then_related(row: BoardPanicRow) -> bool:
    """Whether this panic participates in the and_then / exit conversion mass.

    Derived from live mouth owners, not a hand-curated file list.
    """
    o = (row.owner or "").lower()
    m = (row.message or "").lower()
    if "outcome_to_exitset" in o or "outcome_to_exitset" in m:
        return True
    if "nativeoperationexitcarrier" in o:
        return True
    if "contractconditionalconstruction" in o:
        return True
    if "and_then" in o:
        return True
    if "pending parameter contract" in m:
        return True
    if "undischarged native" in m:
        return True
    if o.startswith("guardedvalue"):
        return True
    if "single_outcome" in o or "require_single_value" in m:
        return True
    return False


def partition_board(rows: Iterable[BoardPanicRow]) -> dict[str, list[BoardPanicRow]]:
    out: dict[str, list[BoardPanicRow]] = {b: [] for b in BUCKETS}
    for row in rows:
        if not is_and_then_related(row):
            continue
        bucket = classify_board_row(row)
        if bucket not in out:
            bucket = "other"
        out[bucket].append(row)
    return out


def format_report(
    *,
    mouths: list[PanicMouth],
    partition: dict[str, list[BoardPanicRow]],
    board_path: Path | None,
    total_board_panics: int,
) -> str:
    lines = [
        "AND_THEN CONSTRUCTION PANIC PARTITION",
        "class=and_then / outcome_to_exitset conversion mass",
        "recognition=live mouths (AST) + board rows (control_effect_recensus)",
        f"board={board_path if board_path else '<none>'}",
        "",
        "=== live panic mouths (production AST) ===",
    ]
    by_bucket = Counter(m.bucket for m in mouths)
    for b in BUCKETS:
        lines.append(f"mouths_{b}={by_bucket.get(b, 0)}")
    for m in sorted(mouths, key=lambda x: (x.bucket, x.path, x.line)):
        lines.append(
            f"  mouth {m.bucket} {m.path}:{m.line} owner={m.owner!r} observed={m.observed!r}"
        )
    lines.append("")
    lines.append("=== board partition (and_then-related only) ===")
    related = sum(len(v) for v in partition.values())
    lines.append(f"R_and_then_related={related}")
    lines.append(f"R_board_panics_total={total_board_panics}")
    for b in BUCKETS:
        rows = partition[b]
        lines.append(f"R_{b}={len(rows)}")
        owners = Counter(r.owner or "<no-owner>" for r in rows)
        for owner, n in owners.most_common(20):
            lines.append(f"  {n:5d}  owner={owner}")
    lines.append("")
    lines.append("=== Deferred design check (manual after Deferred lands) ===")
    lines.append(
        "Accept Deferred only if loud incompleteness mass is preserved or increased "
        "(relocated to undischarged terminus), never converted to silence."
    )
    lines.append(
        f"baseline_tip_native_deferred={len(partition['native_deferred'])} "
        f"pending_contract={len(partition['pending_contract'])} "
        f"guarded={len(partition['guarded'])} "
        f"other={len(partition['other'])}"
    )
    # Explicit refutation of stale claim
    lines.append("")
    lines.append("=== stale-claim guard ===")
    lines.append(
        "If R_native_deferred==0 and R_pending_contract>>0, the claim "
        "'mass is Deferred (NativeOperationExitCarrierV1)' is REFUTED for this board."
    )
    return "\n".join(lines)


def self_check() -> int:
    """Tooth: synthetic board rows from live mouth shapes classify correctly."""
    planted = [
        BoardPanicRow(
            "plant",
            "outcome_to_exitset",
            "undischarged native operation demand",
            "f.py:1:0",
            {},
        ),
        BoardPanicRow(
            "plant",
            "NativeOperationExitCarrierV1.compose_prefix",
            "incompatible native-operation demands beneath one prefix",
            "f.py:2:0",
            {},
        ),
        BoardPanicRow(
            "plant",
            "ContractConditionalConstructionV1.and_then",
            "pending parameter contract demands (abc) joined onto a ExitSet",
            "f.py:3:0",
            {},
        ),
        BoardPanicRow(
            "plant",
            "GuardedValue._map(add)",
            "the true arm answered with ExitSet, violating: one value",
            "f.py:4:0",
            {},
        ),
        BoardPanicRow(
            "plant",
            "outcome_to_exitset",
            "SomeWeirdOutcome is not an Outcome the exit algebra knows",
            "f.py:5:0",
            {},
        ),
    ]
    expect = [
        "native_deferred",
        "native_deferred",
        "pending_contract",
        "guarded",
        "other",
    ]
    got = [classify_board_row(r) for r in planted]
    if got != expect:
        print("SELF_CHECK_FAIL", got, "!=", expect)
        return 1
    part = partition_board(planted)
    if len(part["native_deferred"]) != 2:
        print("SELF_CHECK_FAIL native count", len(part["native_deferred"]))
        return 1
    print("SELF_CHECK_OK")
    print(
        f"R_native_deferred={len(part['native_deferred'])} "
        f"R_pending_contract={len(part['pending_contract'])} "
        f"R_guarded={len(part['guarded'])} "
        f"R_other={len(part['other'])}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        type=Path,
        default=None,
        help="repo root (default: discover from script location)",
    )
    parser.add_argument(
        "--board",
        type=Path,
        default=None,
        help="control_effect_recensus recensus.json (required for tip split)",
    )
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="plant synthetic rows; assert classifier teeth (no board, no corpus)",
    )
    parser.add_argument(
        "--require-and-then-mass",
        action="store_true",
        help="EXIT=1 if board has zero and_then-related panics (empty measure)",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="optional machine-readable partition JSON",
    )
    args = parser.parse_args(argv)

    if args.self_check:
        return self_check()

    repo = (args.repo or repo_root_from_here()).resolve()
    try:
        mouths = extract_panic_mouths(repo)
    except FileNotFoundError as exc:
        print(f"RED enrollment: {exc}")
        return 2

    if args.board is None:
        print("BLOCKED: no --board given")
        print(
            "Pass the control_effect_recensus recensus.json when the tip board lands."
        )
        print(f"Live mouths enrolled: {len(mouths)}")
        for m in mouths:
            print(
                f"  {m.bucket} {m.path}:{m.line} owner={m.owner!r} observed={m.observed!r}"
            )
        print("Run --self-check for classifier tooth without a board.")
        return 2

    board_path = args.board.resolve()
    if not board_path.is_file():
        print(f"RED: board not a file: {board_path}")
        return 2

    rows = load_board_panic_rows(board_path)
    partition = partition_board(rows)
    report = format_report(
        mouths=mouths,
        partition=partition,
        board_path=board_path,
        total_board_panics=len(rows),
    )
    print(report)

    if args.json_out is not None:
        payload = {
            "board": str(board_path),
            "R_board_panics_total": len(rows),
            "R_and_then_related": sum(len(v) for v in partition.values()),
            "R": {b: len(partition[b]) for b in BUCKETS},
            "mouths": [
                {
                    "path": m.path,
                    "line": m.line,
                    "owner": m.owner,
                    "observed": m.observed,
                    "bucket": m.bucket,
                }
                for m in mouths
            ],
            "by_owner": {
                b: dict(Counter(r.owner or "<no-owner>" for r in partition[b]))
                for b in BUCKETS
            },
        }
        args.json_out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {args.json_out}")

    related = sum(len(v) for v in partition.values())
    if args.require_and_then_mass and related == 0:
        print("RED: and_then-related mass is zero — board may lack panic rows")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
