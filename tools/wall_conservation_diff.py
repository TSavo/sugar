#!/usr/bin/env python3
"""Wall conservation vector + before/after bucket delta (#4263).

Post-merge instrument, not a merge gate. Construction PRs state predicted
Epsilon R cheaply; merged-main wall CI mints the actual vector; this tool
reads Delta R between two recovered frontiers (and optional summary.json
pair) and makes unexplained bucket movement loud.

Buckets (closed conservation vector):
  constructed            clean audit leaves (auditLeavesCompleted minus
                         distinct panicked demanded bodies)
  mandatory_panics       len(frontier.panics) / summary independentPanicCount
  suppressed_descendants len(frontier.suppressedDescendants)
  typed_effects          len(frontier.effects)
  silent                 must be 0 (closed frontier; Conservation gaps in
                         summary are silent accounting and fail the floor)

Unexplained-movement rules (fix-forward red, advisory by default):
  * silent_after > 0
  * panic decrease absorbed by suppressed increase (suppression shift)
  * panic decrease absorbed by effects increase (reclassification)
  * sourceFilesEnumerated shrink (discovery narrowing)
  * auditLeavesCompleted shrink without matching source shrink (incomplete mint)

Pass --explain bucket=reason for each moved bucket the author owns. A panic
drop with no explanation for a simultaneous suppressed rise still fails the
unexplained detector even with other explanations present.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping

SCHEMA = "sugar.wall.conservation-vector.v1"

BUCKETS = (
    "constructed",
    "mandatory_panics",
    "suppressed_descendants",
    "typed_effects",
    "silent",
)

# Denominator / integrity axes reported alongside the conservation buckets.
CENSUS_AXES = (
    "source_files_enumerated",
    "source_bodies_demanded",
    "audit_leaves_completed",
)


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise TypeError(f"{path} must be a JSON object")
    return payload


def _nonneg_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer, got {value!r}")
    return value


def _panic_body_keys(panics: list[Any]) -> set[str]:
    keys: set[str] = set()
    for index, panic in enumerate(panics):
        if not isinstance(panic, Mapping):
            keys.add(f"<row:{index}>")
            continue
        body = panic.get("demandedBody")
        if isinstance(body, Mapping):
            keys.add(json.dumps(body, sort_keys=True, separators=(",", ":")))
            continue
        demanded = panic.get("demandedSource")
        if isinstance(demanded, str) and demanded:
            keys.add(demanded)
            continue
        locus = panic.get("locus")
        if isinstance(locus, str) and locus:
            keys.add(locus)
            continue
        keys.add(f"<row:{index}>")
    return keys


def _silent_from_summary(summary: Mapping[str, Any] | None) -> int:
    if summary is None:
        return 0
    # Complete-mode walls surface conservation violations as Construction gaps
    # with bucket Conservation, or as explicit silent/violation counters.
    for key in ("silent", "silentCount", "conservationViolations"):
        if key in summary:
            return _nonneg_int(summary[key], f"summary.{key}")
    frontier = summary.get("frontier")
    if isinstance(frontier, Mapping):
        for key in ("silent", "silentCount", "conservationViolations"):
            if key in frontier:
                return _nonneg_int(frontier[key], f"summary.frontier.{key}")
    gaps = summary.get("gapsByBucket")
    if not isinstance(gaps, Mapping):
        gaps = summary.get("gaps_by_bucket")
    if isinstance(gaps, Mapping) and "Conservation" in gaps:
        return _nonneg_int(gaps["Conservation"], "summary.gapsByBucket.Conservation")
    return 0


def _cross_check_summary(
    frontier_counts: Mapping[str, int], summary: Mapping[str, Any] | None
) -> None:
    if summary is None:
        return
    block = summary.get("frontier")
    if not isinstance(block, Mapping):
        return
    pairs = (
        ("mandatory_panics", "independentPanicCount"),
        ("suppressed_descendants", "suppressedDescendantCount"),
        ("typed_effects", "effectCount"),
    )
    for bucket, field in pairs:
        if field not in block:
            continue
        observed = _nonneg_int(block[field], f"summary.frontier.{field}")
        if observed != frontier_counts[bucket]:
            raise ValueError(
                f"summary/frontier mismatch on {field}: "
                f"frontier={frontier_counts[bucket]} summary={observed}"
            )


def conservation_vector(
    frontier_path: Path, summary_path: Path | None = None
) -> dict[str, int]:
    """Return the closed conservation vector for one recovered wall mint."""
    frontier = _load_json(frontier_path)
    if frontier.get("kind") != "recovered-construction-audit":
        raise ValueError("frontier kind must be recovered-construction-audit")
    if frontier.get("recoveryOverride") is not True:
        raise ValueError("frontier must carry the recovery override")
    census = frontier.get("census")
    if not isinstance(census, Mapping) or census.get("kind") != "recovered-frontier-census":
        raise ValueError("frontier must carry a recovered census receipt")

    source_files = _nonneg_int(
        census.get("sourceFilesEnumerated"), "census.sourceFilesEnumerated"
    )
    source_bodies = _nonneg_int(
        census.get("sourceBodiesDemanded"), "census.sourceBodiesDemanded"
    )
    audit_leaves = _nonneg_int(
        census.get("auditLeavesCompleted"), "census.auditLeavesCompleted"
    )
    if source_files != source_bodies:
        raise ValueError(
            "frontier source census does not conserve body demands: "
            f"files={source_files} bodies={source_bodies}"
        )

    panics = frontier.get("panics")
    suppressed = frontier.get("suppressedDescendants")
    effects = frontier.get("effects")
    if not isinstance(panics, list):
        raise TypeError("frontier.panics must be a JSON array")
    if not isinstance(suppressed, list):
        raise TypeError("frontier.suppressedDescendants must be a JSON array")
    if not isinstance(effects, list):
        raise TypeError("frontier.effects must be a JSON array")

    status = frontier.get("status")
    if status not in {"valid-empty", "complete", "failed"}:
        raise ValueError(f"frontier terminal status is not closed: {status!r}")
    if status == "valid-empty" and (
        source_files != 0 or audit_leaves != 0 or panics or suppressed or effects
    ):
        raise ValueError("valid-empty frontier requires a zero census and empty lanes")
    if status == "complete" and (source_files == 0 or panics):
        raise ValueError("complete frontier requires a nonempty clean census")
    if status == "failed" and not panics:
        raise ValueError("failed frontier requires typed panic telemetry")

    mandatory_panics = len(panics)
    suppressed_descendants = len(suppressed)
    typed_effects = len(effects)
    panicked_bodies = len(_panic_body_keys(panics))
    constructed = max(0, audit_leaves - panicked_bodies)

    summary = _load_json(summary_path) if summary_path is not None else None
    silent = _silent_from_summary(summary)
    # Closed recovered frontiers already promote conservation violations into
    # panic rows. Any residual silent count is a floor breach.
    vector = {
        "constructed": constructed,
        "mandatory_panics": mandatory_panics,
        "suppressed_descendants": suppressed_descendants,
        "typed_effects": typed_effects,
        "silent": silent,
        "source_files_enumerated": source_files,
        "source_bodies_demanded": source_bodies,
        "audit_leaves_completed": audit_leaves,
    }
    _cross_check_summary(vector, summary)
    return vector


def parse_explanations(raw: list[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in raw:
        if "=" not in item:
            raise ValueError(
                f"explanation must be bucket=reason, got {item!r}; "
                f"buckets={','.join(BUCKETS)}"
            )
        bucket, reason = item.split("=", 1)
        bucket = bucket.strip()
        reason = reason.strip()
        if bucket not in BUCKETS and bucket not in CENSUS_AXES:
            raise ValueError(
                f"unknown explanation bucket {bucket!r}; "
                f"known={','.join(BUCKETS + CENSUS_AXES)}"
            )
        if not reason:
            raise ValueError(f"empty explanation for bucket {bucket}")
        out[bucket] = reason
    return out


def detect_unexplained(
    before: Mapping[str, int],
    after: Mapping[str, int],
    explanations: Mapping[str, str],
) -> list[str]:
    """Return human-readable unexplained movement findings."""
    findings: list[str] = []
    deltas = {key: after[key] - before[key] for key in BUCKETS + CENSUS_AXES}

    if after["silent"] > 0:
        findings.append(
            f"silent floor breached: after={after['silent']} (must be 0); "
            "silent loci are conservation violations that never became loud"
        )
    elif deltas["silent"] != 0 and "silent" not in explanations:
        findings.append(
            f"silent moved {deltas['silent']:+d} without explanation "
            f"(before={before['silent']} after={after['silent']})"
        )

    panic_delta = deltas["mandatory_panics"]
    suppressed_delta = deltas["suppressed_descendants"]
    effects_delta = deltas["typed_effects"]

    # Suppression shift: panics fall while suppressed rises — the classic
    # false-green where work is reparented under a new panic, not constructed.
    if panic_delta < 0 and suppressed_delta > 0:
        if (
            "suppressed_descendants" not in explanations
            and "mandatory_panics" not in explanations
        ):
            findings.append(
                "suppression shift: mandatory_panics "
                f"{panic_delta:+d} while suppressed_descendants "
                f"{suppressed_delta:+d}; a panic drop absorbed by suppressed "
                "growth is not construction — explain both buckets or fix forward"
            )

    # Reclassification into typed effects without owning either side.
    if panic_delta < 0 and effects_delta > 0:
        if (
            "typed_effects" not in explanations
            and "mandatory_panics" not in explanations
        ):
            findings.append(
                "reclassification: mandatory_panics "
                f"{panic_delta:+d} while typed_effects {effects_delta:+d}; "
                "explain the effect class or the panic retirement path"
            )

    if deltas["source_files_enumerated"] < 0 and "source_files_enumerated" not in explanations:
        findings.append(
            "discovery narrowing: source_files_enumerated "
            f"{deltas['source_files_enumerated']:+d} "
            f"(before={before['source_files_enumerated']} "
            f"after={after['source_files_enumerated']}); "
            "a lower panic count from a smaller corpus is not progress"
        )

    if (
        deltas["audit_leaves_completed"] < 0
        and deltas["source_files_enumerated"] >= 0
        and "audit_leaves_completed" not in explanations
    ):
        findings.append(
            "incomplete mint: audit_leaves_completed "
            f"{deltas['audit_leaves_completed']:+d} while source files did not "
            "shrink; partial frontiers are not comparable conservation readings"
        )

    # Any other nonzero bucket move without an explanation is noted so the
    # ledger cannot stay silent about residual motion.
    for bucket in BUCKETS:
        if bucket == "silent":
            continue
        if deltas[bucket] != 0 and bucket not in explanations:
            # Suppression/reclassification already covered when co-moving.
            if (
                bucket == "suppressed_descendants"
                and panic_delta < 0
                and suppressed_delta > 0
            ):
                continue
            if bucket == "typed_effects" and panic_delta < 0 and effects_delta > 0:
                continue
            if bucket == "mandatory_panics" and (
                (suppressed_delta > 0 and panic_delta < 0)
                or (effects_delta > 0 and panic_delta < 0)
            ):
                continue
            findings.append(
                f"unexplained {bucket} move {deltas[bucket]:+d} "
                f"(before={before[bucket]} after={after[bucket]}); "
                f"pass --explain {bucket}=<reason>"
            )

    return findings


def delta_table(
    before: Mapping[str, int], after: Mapping[str, int]
) -> list[tuple[str, int, int, int]]:
    rows: list[tuple[str, int, int, int]] = []
    for key in BUCKETS + CENSUS_AXES:
        rows.append((key, before[key], after[key], after[key] - before[key]))
    return rows


def render_markdown(
    *,
    wall: str,
    before: Mapping[str, int],
    after: Mapping[str, int],
    findings: list[str],
    explanations: Mapping[str, str],
    before_label: str,
    after_label: str,
    run_url: str | None = None,
) -> str:
    lines = [
        f"## {wall} wall conservation vector (ΔR)",
        "",
        f"- schema: `{SCHEMA}`",
        f"- before: {before_label}",
        f"- after: {after_label}",
    ]
    if run_url:
        lines.append(f"- run: {run_url}")
    lines.extend(
        [
            "",
            "| bucket | before | after | Δ |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for key, b, a, d in delta_table(before, after):
        mark = " **floor**" if key == "silent" and a > 0 else ""
        lines.append(f"| `{key}` | {b} | {a} | {d:+d}{mark} |")
    lines.append("")
    if explanations:
        lines.append("### claimed explanations")
        for bucket, reason in sorted(explanations.items()):
            lines.append(f"- `{bucket}`: {reason}")
        lines.append("")
    if findings:
        lines.append("### unexplained movement (fix forward)")
        for finding in findings:
            lines.append(f"- {finding}")
        lines.append("")
        lines.append(
            "A lower panic count alone is not evidence — suppression shifts, "
            "effect reclassification, census regressions, and discovery "
            "narrowing all produce false progress. Own every bucket that moved."
        )
    else:
        lines.append("### unexplained movement")
        lines.append("- none (every nonzero Δ is explained or zero)")
    lines.append("")
    return "\n".join(lines)


def render_json(
    *,
    wall: str,
    before: Mapping[str, int],
    after: Mapping[str, int],
    findings: list[str],
    explanations: Mapping[str, str],
    before_label: str,
    after_label: str,
) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "wall": wall,
        "before_label": before_label,
        "after_label": after_label,
        "before": dict(before),
        "after": dict(after),
        "delta": {key: after[key] - before[key] for key in BUCKETS + CENSUS_AXES},
        "explanations": dict(explanations),
        "unexplained": list(findings),
        "unexplained_count": len(findings),
        "silent_floor_held": after["silent"] == 0,
    }


def load_vector_json(path: Path) -> dict[str, int]:
    payload = _load_json(path)
    # Accept either a bare vector or a telemetry envelope.
    if "vector" in payload and isinstance(payload["vector"], dict):
        payload = payload["vector"]
    out: dict[str, int] = {}
    for key in BUCKETS + CENSUS_AXES:
        if key not in payload:
            raise ValueError(f"vector JSON missing {key}")
        out[key] = _nonneg_int(payload[key], key)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--before-frontier", type=Path, default=None)
    parser.add_argument("--after-frontier", type=Path, default=None)
    parser.add_argument("--before-summary", type=Path, default=None)
    parser.add_argument("--after-summary", type=Path, default=None)
    parser.add_argument(
        "--before-vector-json",
        type=Path,
        default=None,
        help="prior mint vector (ledger extract); alternative to --before-frontier",
    )
    parser.add_argument(
        "--after-vector-json",
        type=Path,
        default=None,
        help="after mint vector; alternative to --after-frontier",
    )
    parser.add_argument("--wall", default="wall")
    parser.add_argument("--before-label", default="before")
    parser.add_argument("--after-label", default="after")
    parser.add_argument("--run-url", default=None)
    parser.add_argument(
        "--explain",
        action="append",
        default=[],
        help="bucket=reason for a moved axis (repeatable)",
    )
    parser.add_argument(
        "--advisory",
        action="store_true",
        help="print findings but exit 0 (CI advisory first; ratchet later)",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="write machine-readable delta receipt",
    )
    parser.add_argument(
        "--markdown-out",
        type=Path,
        default=None,
        help="write markdown delta table",
    )
    parser.add_argument(
        "--vector-only",
        action="store_true",
        help="emit after vector only (no before/delta); still validates after",
    )
    args = parser.parse_args(argv)

    try:
        explanations = parse_explanations(args.explain)
        if args.after_vector_json is not None:
            after = load_vector_json(args.after_vector_json)
        elif args.after_frontier is not None:
            after = conservation_vector(args.after_frontier, args.after_summary)
        else:
            raise ValueError("provide --after-frontier or --after-vector-json")

        if args.vector_only:
            before = {key: after[key] for key in after}
            findings: list[str] = []
            if after["silent"] > 0:
                findings.append(
                    f"silent floor breached: after={after['silent']} (must be 0)"
                )
        elif args.before_vector_json is not None:
            before = load_vector_json(args.before_vector_json)
            findings = detect_unexplained(before, after, explanations)
        elif args.before_frontier is not None:
            before = conservation_vector(args.before_frontier, args.before_summary)
            findings = detect_unexplained(before, after, explanations)
        else:
            raise ValueError(
                "provide --before-frontier, --before-vector-json, or --vector-only"
            )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"wall-conservation-diff: {exc}", file=sys.stderr)
        return 2

    md = render_markdown(
        wall=args.wall,
        before=before,
        after=after,
        findings=findings,
        explanations=explanations,
        before_label=args.before_label,
        after_label=args.after_label,
        run_url=args.run_url,
    )
    print(md, end="")
    if args.markdown_out is not None:
        args.markdown_out.write_text(md, encoding="utf-8")
    if args.json_out is not None:
        payload = render_json(
            wall=args.wall,
            before=before,
            after=after,
            findings=findings,
            explanations=explanations,
            before_label=args.before_label,
            after_label=args.after_label,
        )
        args.json_out.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    if findings and not args.advisory:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
