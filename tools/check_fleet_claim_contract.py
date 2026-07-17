#!/usr/bin/env python3
"""Fleet claim-label contract instrument (dispatch discoverability).

R: open claimed fleet lanes that are not dispatch-discoverable.

The dispatcher discovers Python worker lanes via ``fleet:lane``. A claim that
only carries ``in-progress`` is invisible — the 2026-07-17 drift to
``fleet:lane`` open count = 0.

Hard law for this instrument:
  - **No fake zero.** Self-test proves the classifier; it does not mint R=0.
  - Live R is read from GitHub (or an explicit ``--from-json`` snapshot).
  - Missing live evidence is red (exit 2), not green.
  - Empty issue list without an explicit empty snapshot is not R=0.

Modes:
  --self-test     planted shapes trip the classifier (no R=0 claim)
  --live          fetch open in-progress issues via ``gh`` and score R
  --from-json P   score a GH issues JSON export (array of issue objects)
  (default)       --self-test then --live (make/CI path)

Exit 0 only when live R = 0 with measured evidence.
Exit 1 when R > 0.
Exit 2 when live measurement is unavailable / invalid.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA = "sugar.fleet.claim-contract.v1"

FATAL_TITLE = re.compile(r"^fatal-corpus\b", re.I)
CLAIM_FIRST_LINE = re.compile(r"^CLAIMED(?:\b|\s|:)", re.I)
RELEASE_FIRST_LINE = re.compile(r"^(?:RELEASED|COMPLETED)(?:\b|\s|:)", re.I)

# Labels a CLAIMED fatal-corpus Python lane must carry for dispatch + orientation.
FATAL_CLAIM_LABELS = frozenset(
    {"in-progress", "fleet:lane", "kit:python", "idd", "north-star"}
)
# Minimum for any CLAIMED worker lane that already carries fleet:lane.
BASE_CLAIM_LABELS = frozenset({"in-progress", "fleet:lane"})

# Body must name measured work, not only "Part of #N".
LOCUS_MARKERS = re.compile(
    r"\b(owner|observed|requested|locus|Hard law|File\s*\|)\b"
    r"|```[\s\S]*\|[\s\S]*\|",
    re.I,
)


@dataclass(frozen=True)
class Offender:
    number: int
    title: str
    missing_labels: tuple[str, ...]
    thin_body: bool
    shape: str

    def to_json(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "title": self.title,
            "missing_labels": list(self.missing_labels),
            "thin_body": self.thin_body,
            "shape": self.shape,
        }


def labels_of(issue: dict[str, Any]) -> set[str]:
    raw = issue.get("labels") or []
    out: set[str] = set()
    for item in raw:
        if isinstance(item, str):
            out.add(item)
        elif isinstance(item, dict) and item.get("name"):
            out.add(str(item["name"]))
    return out


def required_labels_for(title: str, labels: set[str]) -> frozenset[str]:
    if FATAL_TITLE.match(title or "") or "kit:python" in labels:
        return FATAL_CLAIM_LABELS
    return BASE_CLAIM_LABELS


def body_is_thin(title: str, body: str) -> bool:
    if not FATAL_TITLE.match(title or ""):
        return False
    text = body or ""
    if len(text) >= 280:
        return False
    return LOCUS_MARKERS.search(text) is None


def is_fleet_dispatch_issue(title: str, labels: set[str]) -> bool:
    """Only fatal-corpus / already-tagged fleet lanes enter R.

    Historical in-progress epics without fleet:lane are not this instrument's
    offenders — the 2026-07-17 failure mode was Python fatal claims dropping
    to bare in-progress and becoming undiscoverable.
    """
    if FATAL_TITLE.match(title or ""):
        return True
    if "fleet:lane" in labels:
        return True
    return False


def audit_issue(issue: dict[str, Any]) -> Offender | None:
    """Return an offender when an open claimed fleet lane violates the contract.

    R is driven by missing labels and thin fatal bodies. Thin body alone is
    still R (orientation debt), not a soft note.
    """
    if str(issue.get("state", "open")).lower() != "open":
        return None
    labels = labels_of(issue)
    if "in-progress" not in labels:
        return None
    title = str(issue.get("title") or "")
    if not is_fleet_dispatch_issue(title, labels):
        return None
    required = required_labels_for(title, labels)
    missing = tuple(sorted(required - labels))
    thin = body_is_thin(title, str(issue.get("body") or ""))
    if not missing and not thin:
        return None
    if missing and "fleet:lane" in missing:
        shape = "claimed-without-fleet-lane"
    elif missing:
        shape = "claimed-missing-kit-labels"
    else:
        shape = "claimed-thin-body"
    number = int(issue.get("number") or issue.get("n") or 0)
    return Offender(
        number=number,
        title=title,
        missing_labels=missing,
        thin_body=thin,
        shape=shape,
    )


def audit_issues(issues: list[dict[str, Any]]) -> list[Offender]:
    offenders: list[Offender] = []
    for issue in issues:
        hit = audit_issue(issue)
        if hit is not None:
            offenders.append(hit)
    return offenders


def claim_transition_labels(
    *,
    first_line: str,
    title: str,
    body: str,
    current: set[str],
) -> tuple[str, set[str], set[str]]:
    """Pure model of the issue-claim-labels workflow.

    Returns (action, labels_to_add, labels_to_remove).
    """
    del body  # orientation is scored on the issue, not the claim comment
    if CLAIM_FIRST_LINE.match(first_line.strip()):
        required = set(BASE_CLAIM_LABELS)
        if FATAL_TITLE.match(title) or "kit:python" in current:
            required |= set(FATAL_CLAIM_LABELS)
        add = required - current
        remove = {"available"} & current
        return ("claimed", add, remove)
    if RELEASE_FIRST_LINE.match(first_line.strip()):
        remove = {"in-progress", "fleet:lane"} & current
        add = set() if "available" in current else {"available"}
        return ("released", add, remove)
    return ("noop", set(), set())


def fleet_lane_open_count(issues: list[dict[str, Any]]) -> int:
    n = 0
    for issue in issues:
        if str(issue.get("state", "open")).lower() != "open":
            continue
        if "fleet:lane" in labels_of(issue):
            n += 1
    return n


def claimed_fatal_open_count(issues: list[dict[str, Any]]) -> int:
    n = 0
    for issue in issues:
        if str(issue.get("state", "open")).lower() != "open":
            continue
        labels = labels_of(issue)
        if "in-progress" not in labels:
            continue
        if FATAL_TITLE.match(str(issue.get("title") or "")):
            n += 1
    return n


def scoreboard(
    offenders: list[Offender],
    *,
    issues: list[dict[str, Any]] | None = None,
    evidence: str,
) -> dict[str, Any]:
    by_shape: dict[str, int] = {}
    for o in offenders:
        by_shape[o.shape] = by_shape.get(o.shape, 0) + 1
    r = len(offenders)
    lane_open = fleet_lane_open_count(issues or [])
    fatals_open = claimed_fatal_open_count(issues or [])
    # Universe-level shape: claimed fatals exist but zero fleet:lane labels.
    # Covered per-issue too; surface as its own axis so the fog cannot hide.
    if fatals_open > 0 and lane_open == 0 and r == 0:
        # Should be unreachable if per-issue audit is sound; pin loudly if not.
        r = fatals_open
        by_shape["fleet-lane-universe-empty"] = fatals_open
    return {
        "schema": SCHEMA,
        "R": r,
        "evidence": evidence,
        "fleet_lane_open": lane_open,
        "claimed_fatal_open": fatals_open,
        "by_shape": dict(sorted(by_shape.items())),
        "offenders": [o.to_json() for o in offenders],
        "replacement": (
            "On CLAIMED: ensure in-progress + fleet:lane "
            "(+ kit:python,idd,north-star for fatal-corpus); "
            "write locus table + hard law in the issue body. "
            "Never claim with only in-progress. "
            "Never report R=0 without live issue evidence."
        ),
    }


def render_human(payload: dict[str, Any]) -> str:
    lines = [
        "FLEET CLAIM CONTRACT",
        f"schema: {payload['schema']}",
        f"evidence: {payload.get('evidence', '?')}",
        f"R={payload['R']}",
        f"fleet_lane_open={payload.get('fleet_lane_open', '?')}  "
        f"claimed_fatal_open={payload.get('claimed_fatal_open', '?')}",
    ]
    by_shape = payload.get("by_shape") or {}
    if by_shape:
        lines.append("by_shape:")
        for shape, count in by_shape.items():
            lines.append(f"  {count:4d}  {shape}")
    for o in payload.get("offenders") or []:
        assert isinstance(o, dict)
        lines.append(
            f"  #{o['number']} [{o['shape']}] missing={o['missing_labels']} "
            f"thin_body={o['thin_body']} | {o['title'][:80]}"
        )
    if int(payload["R"]) > 0:
        lines.append(f"FAIL: R must be 0 — {payload['replacement']}")
    else:
        lines.append(
            "PASS: measured R=0 — every open fleet claim is dispatch-discoverable"
        )
    return "\n".join(lines) + "\n"


def fetch_live_issues() -> list[dict[str, Any]]:
    """Pull open in-progress issues via gh. Fail loud if measurement cannot run."""
    if shutil.which("gh") is None:
        raise RuntimeError("gh not on PATH; cannot measure live fleet claim R")
    cmd = [
        "gh",
        "issue",
        "list",
        "--state",
        "open",
        "--label",
        "in-progress",
        "--limit",
        "100",
        "--json",
        "number,title,body,labels,state",
    ]
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("gh issue list timed out measuring live claim R") from exc
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        raise RuntimeError(f"gh issue list failed: {err}")
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("gh issue list returned non-JSON") from exc
    if not isinstance(data, list):
        raise RuntimeError("gh issue list JSON must be an array")
    return data


def self_test() -> int:
    """Classifier proof only. Must never claim live R=0."""
    # Illegal: claimed fatal with only in-progress (the 2026-07-17 shape).
    bad = {
        "number": 5019,
        "state": "open",
        "title": "fatal-corpus: append_with ComprehensionValue (2 verified-live)",
        "body": "Part of #4684",
        "labels": [{"name": "in-progress"}],
    }
    good = {
        "number": 5019,
        "state": "open",
        "title": "fatal-corpus: append_with ComprehensionValue (2 verified-live)",
        "body": (
            "## R / loci\n| File | Owner | Observed |\n|---|---|---|\n"
            "| pandas/x.py | AppendWith | ComprehensionValue |\n"
            "## Hard law\n- Do not weaken to RuntimeEffect\n"
        ),
        "labels": [
            {"name": "in-progress"},
            {"name": "fleet:lane"},
            {"name": "kit:python"},
            {"name": "idd"},
            {"name": "north-star"},
        ],
    }
    closed = {**bad, "state": "closed", "number": 1}

    offenders = audit_issues([bad, good, closed])
    if len(offenders) != 1 or offenders[0].number != 5019:
        print(f"FAIL: expected one offender #5019, got {offenders}", file=sys.stderr)
        return 1
    if "fleet:lane" not in offenders[0].missing_labels:
        print(
            f"FAIL: expected fleet:lane missing, got {offenders[0].missing_labels}",
            file=sys.stderr,
        )
        return 1
    if not offenders[0].thin_body:
        print("FAIL: expected thin_body on Part-of-only issue", file=sys.stderr)
        return 1
    if audit_issues([good]):
        print("FAIL: good issue scored red", file=sys.stderr)
        return 1

    # Workflow pure model: CLAIMED restores fleet:lane.
    action, add, remove = claim_transition_labels(
        first_line="CLAIMED (codex fleet)",
        title=bad["title"],
        body=bad["body"],
        current={"in-progress"},
    )
    if action != "claimed" or "fleet:lane" not in add:
        print(
            f"FAIL: CLAIMED must add fleet:lane, got action={action} add={add}",
            file=sys.stderr,
        )
        return 1
    for name in ("kit:python", "idd", "north-star"):
        if name not in add:
            print(f"FAIL: CLAIMED fatal must add {name}, got {add}", file=sys.stderr)
            return 1
    if "available" in add:
        print("FAIL: CLAIMED must not add available", file=sys.stderr)
        return 1

    action, add, remove = claim_transition_labels(
        first_line="RELEASED",
        title=good["title"],
        body=good["body"],
        current=set(FATAL_CLAIM_LABELS),
    )
    if action != "released":
        print(f"FAIL: expected released, got {action}", file=sys.stderr)
        return 1
    if "in-progress" not in remove or "fleet:lane" not in remove:
        print(f"FAIL: RELEASED must drop claim labels, got {remove}", file=sys.stderr)
        return 1
    if "available" not in add:
        print(f"FAIL: RELEASED must restore available, got {add}", file=sys.stderr)
        return 1

    # Planted snapshot must stay red (no fake zero on known offenders).
    planted = scoreboard(offenders, issues=[bad, good, closed], evidence="self-test-planted")
    if int(planted["R"]) != 1:
        print(f"FAIL: planted R must be 1, got {planted['R']}", file=sys.stderr)
        return 1

    # Explicit empty snapshot is measured R=0 only with evidence=empty-snapshot.
    empty = scoreboard([], issues=[], evidence="self-test-empty-snapshot")
    if int(empty["R"]) != 0:
        print(f"FAIL: empty snapshot R must be 0, got {empty['R']}", file=sys.stderr)
        return 1

    print(
        "PASS: fleet claim contract classifier "
        "(self-test only — does not mint live R=0)"
    )
    return 0


def emit_payload(payload: dict[str, Any], *, json_only: bool) -> int:
    if json_only:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(render_human(payload), end="")
    return 1 if int(payload["R"]) > 0 else 0


def score_from_json(path: Path, *, json_only: bool) -> int:
    if not path.is_file():
        print(f"FAIL: missing {path}", file=sys.stderr)
        return 2
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        print("FAIL: --from-json must be a JSON array of issues", file=sys.stderr)
        return 2
    payload = scoreboard(
        audit_issues(data),
        issues=data,
        evidence=f"from-json:{path}",
    )
    return emit_payload(payload, json_only=json_only)


def score_live(*, json_only: bool) -> int:
    try:
        issues = fetch_live_issues()
    except RuntimeError as exc:
        print(f"FAIL: live measurement unavailable — {exc}", file=sys.stderr)
        print(
            "replacement: install/auth gh, or pass --from-json with a fresh export; "
            "do not treat self-test as R=0",
            file=sys.stderr,
        )
        return 2
    payload = scoreboard(
        audit_issues(issues),
        issues=issues,
        evidence="gh:issue.list:label=in-progress:state=open",
    )
    return emit_payload(payload, json_only=json_only)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="classifier proof only; never claims live R=0",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="measure R from live GitHub issues via gh",
    )
    parser.add_argument(
        "--from-json",
        type=Path,
        default=None,
        help="Path to JSON array of GitHub issue objects",
    )
    parser.add_argument("--json-only", action="store_true")
    args = parser.parse_args(argv)

    # Explicit single modes.
    if args.self_test and not args.live and args.from_json is None:
        return self_test()
    if args.from_json is not None and not args.live and not args.self_test:
        return score_from_json(args.from_json, json_only=args.json_only)
    if args.live and not args.self_test and args.from_json is None:
        return score_live(json_only=args.json_only)

    # Default make/CI path: classifier proof, then live R. Self-test green alone
    # is never enough (no fake zero).
    if not args.self_test and not args.live and args.from_json is None:
        rc = self_test()
        if rc != 0:
            return rc
        return score_live(json_only=args.json_only)

    # Combined flags: self-test then live/json.
    if args.self_test:
        rc = self_test()
        if rc != 0:
            return rc
    if args.from_json is not None:
        return score_from_json(args.from_json, json_only=args.json_only)
    if args.live:
        return score_live(json_only=args.json_only)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
