#!/usr/bin/env python3
"""Fleet claim-label contract instrument (dispatch discoverability).

R: count of open issues that are claimed (in-progress) but missing fleet:lane,
or missing the fatal-corpus Python label set.

The dispatcher discovers Python worker lanes via fleet:lane. A claim that only
carries in-progress is invisible — the 2026-07-17 drift to fleet:lane=0.

Modes:
  --self-test   planted shapes trip the contract
  --from-json   score a GH issues JSON export (array of issue objects)
  (default)     --self-test only (no network)

Exit 1 when R > 0. Exit 0 when R = 0.
"""

from __future__ import annotations

import argparse
import json
import re
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
# Minimum for any CLAIMED worker lane.
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
    """Only fatal-corpus / kit:python fleet lanes enter R.

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

    R is driven by **missing labels**. Thin bodies are reported on the same
    offender when labels are already wrong, and as claimed-thin-body only when
    the issue is a fatal-corpus claim with a full label set but no locus text
    (orientation debt — still red so file-time discipline holds).
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


def scoreboard(offenders: list[Offender]) -> dict[str, Any]:
    by_shape: dict[str, int] = {}
    for o in offenders:
        by_shape[o.shape] = by_shape.get(o.shape, 0) + 1
    r = len(offenders)
    return {
        "schema": SCHEMA,
        "R": r,
        "by_shape": dict(sorted(by_shape.items())),
        "offenders": [o.to_json() for o in offenders],
        "replacement": (
            "On CLAIMED: ensure in-progress + fleet:lane "
            "(+ kit:python,idd,north-star for fatal-corpus); "
            "write locus table + hard law in the issue body. "
            "Never claim with only in-progress."
        ),
    }


def render_human(payload: dict[str, Any]) -> str:
    lines = [
        "FLEET CLAIM CONTRACT",
        f"schema: {payload['schema']}",
        f"R={payload['R']}",
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
        lines.append("PASS: R=0 — every open claim is dispatch-discoverable")
    return "\n".join(lines) + "\n"


def self_test() -> int:
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

    print("PASS: fleet claim contract self-test")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument(
        "--from-json",
        type=Path,
        default=None,
        help="Path to JSON array of GitHub issue objects",
    )
    parser.add_argument("--json-only", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test or args.from_json is None:
        if args.from_json is None and not args.self_test:
            # Default path: pure instrument self-test (no network).
            return self_test()
        if args.self_test and args.from_json is None:
            return self_test()

    assert args.from_json is not None
    if not args.from_json.is_file():
        print(f"FAIL: missing {args.from_json}", file=sys.stderr)
        return 2
    data = json.loads(args.from_json.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        print("FAIL: --from-json must be a JSON array of issues", file=sys.stderr)
        return 2
    payload = scoreboard(audit_issues(data))
    if args.json_only:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(render_human(payload), end="")
    return 1 if int(payload["R"]) > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
