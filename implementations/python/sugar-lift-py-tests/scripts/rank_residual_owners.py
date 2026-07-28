#!/usr/bin/env python3
"""Rank the residual by DISPATCHABLE OWNER, off one pinned baseline.

    python3 rank_residual_owners.py <recensus.json> [--markdown]

A board is a pile of counters. A worklist is a ranking by the unit someone can
actually be handed. This turns the first into the second, and refuses three
ways of lying while doing it.

**Never rank by a mixed total.** ``R_desugar`` is two different things sharing a
counter: typed refusals (owed work) and constructed effects (the correct output
of a reduction that succeeded). Quoted whole it overstated the earlier board by
7.6x. This ranks the parts, and prints the accounted-semantics share beside
them so the total can never be mistaken for a backlog.

**Never rank by raw occurrence.** A panic owner with 283 occurrences across 40
files is one dispatchable row, not 283. The unit is ``(owner x category)``.

**Never merge axes.** Construction R, desugar owed work, desugar constructed
effects, panics, defects, backend defects and factoring gaps have different
denominators and different owners. They are ranked separately and never summed
into a single "R_total" here -- that number belongs to
``reconcile_pandas_floors.py``, which is the corpus authority.

Site prevalence is printed for scale and is labelled as a denominator. It is
never R.
"""

from __future__ import annotations

# Not the board. This module ranks an existing board's rows; the sole
# authoritative Python corpus scoreboard is scripts/control_effect_recensus.py.
# See tests/test_one_authoritative_scoreboard.py.
SCOREBOARD_AUTHORITY = False

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


def _owner_of_panic(row: dict[str, Any]) -> str:
    owner = row.get("owner")
    if isinstance(owner, str) and owner:
        return owner
    # No owner on the row is itself a defect worth seeing, not a silent "other".
    return "UNNAMED-OWNER (panic row carries no owner)"


def _factoring_rows(defects: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in defects if "FactoringGap" in json.dumps(row)]


def _classify_factoring(row: dict[str, Any]) -> str:
    """Read the merged classifier's verdict off the defect text.

    ``#6364`` split ``factoring_gaps`` into remaining work and correct refusal.
    When the run that produced this ledger carried that classifier, its verdict
    is in the detail; when it did not, say so rather than guessing a split.
    """
    # Structured verdict, carried on the row by the census. Never parse the
    # prose message: a repr is not an interface, and the classifier already
    # produced a typed answer.
    verdict = row.get("classification")
    if isinstance(verdict, dict):
        kind = verdict.get("kind", "?")
        merged = " merged-arm" if verdict.get("mergedArm") else ""
        head = (
            "remaining-work" if verdict.get("isRemainingWork") else "correct-refusal"
        )
        return f"{head} ({kind}{merged})"
    return "UNCLASSIFIED (ledger predates #6364 classifier)"


def _owner_from_detail(row: dict[str, Any]) -> str:
    verdict = row.get("classification")
    if isinstance(verdict, dict):
        left, right = verdict.get("leftOwner"), verdict.get("rightOwner")
        if left or right:
            return f"{left} / {right}"
    detail = str(row.get("detail", ""))
    match = re.search(r"owner:\s*([^\n]+)", detail)
    return match.group(1).strip() if match else "unnamed"


def rank(board: dict[str, Any]) -> dict[str, Any]:
    desugar_by_owner = board.get("desugarByCategoryOwner") or {}
    owed = Counter()
    accounted = Counter()
    for key, count in desugar_by_owner.items():
        category, _, owner = key.partition("/")
        (owed if category == "typed-refusal" else accounted)[owner] += count

    panics = board.get("desugarConstructionPanics") or []
    panic_owners = Counter(_owner_of_panic(row) for row in panics)
    panic_files = {}
    for row in panics:
        where = str(row.get("where", ""))
        panic_files.setdefault(_owner_of_panic(row), set()).add(where.split(":")[0])

    defects = board.get("desugarDefects") or []
    factoring = _factoring_rows(defects)
    other_defects = [row for row in defects if row not in factoring]

    backend = board.get("defects") or []
    backend_by_shape = Counter()
    for row in backend:
        message = str(row.get("message", ""))
        # Group by the defect's own owner line, not by file: three files
        # reporting one LineTable bug are ONE defect, not three.
        match = re.search(r"BACKEND DEFECT \[([^\]]+)\]", message)
        backend_by_shape[match.group(1) if match else str(row.get("type", "?"))] += 1

    return {
        "commit": board.get("commit"),
        "corpusPin": board.get("corpusPin", {}),
        "denominator": {
            k: v
            for k, v in (board.get("denominator") or {}).items()
            if k not in ("enrolledFiles", "enrolledFilesOmitted")
        },
        "red": board.get("red"),
        "redReasons": board.get("redReasons"),
        "stableZeroTerms": board.get("controlEffectStableZeroTerms"),
        "controlEffectStableZero": board.get("controlEffectStableZero"),
        "axes": {
            "R_construction": board.get("R_construction"),
            "R_desugar_total_DO_NOT_PUBLISH_RAW": board.get("R_desugar"),
            "R_desugar_owed_work": board.get("R_desugar_owed_work"),
            "R_desugar_accounted_semantics": board.get(
                "R_desugar_accounted_semantics"
            ),
            "R_construction_panics": board.get("R_construction_panics"),
            "R_desugar_construction_panics": board.get(
                "R_desugar_construction_panics"
            ),
            "R_desugar_defects": board.get("R_desugar_defects"),
            "R_backend_defects": board.get("R_backend_defects"),
            "R_unresolvable_dispatch_targets": board.get(
                "R_unresolvable_dispatch_targets"
            ),
        },
        "sitePrevalence_NOT_R": board.get("astSitePrevalence"),
        "rankings": {
            "constructionFamilies": board.get("families"),
            "desugarOwedWorkByOwner": dict(owed.most_common()),
            "desugarAccountedSemanticsByOwner": dict(accounted.most_common()),
            "desugarConstructionPanicsByOwner": [
                {
                    "owner": owner,
                    "occurrences": count,
                    "files": len(panic_files.get(owner, ())),
                }
                for owner, count in panic_owners.most_common()
            ],
            "factoringGaps": [
                {
                    "where": row.get("where"),
                    "owner": _owner_from_detail(row),
                    "classification": _classify_factoring(row),
                }
                for row in factoring
            ],
            "factoringGapSplit": dict(
                Counter(_classify_factoring(row) for row in factoring).most_common()
            ),
            "otherDesugarDefects": len(other_defects),
            "backendDefectsByShape": dict(backend_by_shape.most_common()),
            "withResolutionKinds": board.get("cmResolutions"),
        },
    }


def _markdown(report: dict[str, Any]) -> str:
    axes = report["axes"]
    rank_ = report["rankings"]
    out: list[str] = []
    add = out.append
    pin = report["corpusPin"]
    add(f"# Ranked residual owners — {pin.get('distribution')} {pin.get('version')}\n")
    add(f"Commit `{report['commit']}`, corpus pin `{pin.get('aggregateHash','')[:16]}…`, "
        f"{pin.get('fileCount')} files.\n")

    denominator = report["denominator"]
    add("## Denominator\n")
    add("```")
    for key, value in denominator.items():
        add(f"{key:24} {value}")
    add("```\n")

    add("## stableZero vector\n")
    add(f"`controlEffectStableZero` = **{report['controlEffectStableZero']}**, "
        f"`red` = **{report['red']}**\n")
    add("```")
    for key, value in (report["stableZeroTerms"] or {}).items():
        add(f"{key:32} {value}")
    add("```\n")
    for reason in report["redReasons"] or []:
        add(f"- {reason}")
    add("")

    add("## R_desugar is two numbers\n")
    total = axes["R_desugar_total_DO_NOT_PUBLISH_RAW"] or 0
    work = axes["R_desugar_owed_work"]
    semantics = axes["R_desugar_accounted_semantics"]
    if work is None or semantics is None:
        # An ABSENT split is not a split of zero. Saying "0 accounted
        # semantics" here would be a fabricated measurement -- the same
        # misleading-zero shape this instrument exists to refuse.
        add(f"Total {total}. **SPLIT UNAVAILABLE** — this ledger predates the "
            "occurrence-key split, so the owed-work share is unmeasured, not "
            "zero. Re-run to obtain it; do not publish the total as work.\n")
    elif work:
        add(f"Total {total} = **{work} owed work** + {semantics} accounted "
            f"semantics. Publishing the total as work overstates it by "
            f"**{total / work:.1f}x**.\n")
    else:
        add(f"Total {total} = **0 owed work** + {semantics} accounted "
            "semantics. Every row is the correct output of a reduction that "
            "succeeded; none of it is a backlog.\n")
    add("### Owed work, by owner\n")
    add("```")
    for owner, count in list(rank_["desugarOwedWorkByOwner"].items())[:20]:
        add(f"{count:6d}  {owner}")
    add("```\n")

    add("## Desugar construction panics, by (owner × files)\n")
    add("```")
    for row in rank_["desugarConstructionPanicsByOwner"][:20]:
        add(f"{row['occurrences']:6d}  in {row['files']:4d} files  {row['owner']}")
    add("```\n")

    add("## Factoring gaps\n")
    add("```")
    for key, count in rank_["factoringGapSplit"].items():
        add(f"{count:6d}  {key}")
    add("```\n")

    add("## Backend defects, by shape (not by file)\n")
    add("```")
    for shape, count in rank_["backendDefectsByShape"].items():
        add(f"{count:6d}  {shape}")
    add("```\n")

    add("## Site prevalence — a DENOMINATOR, never R\n")
    add("```")
    for site, count in (report["sitePrevalence_NOT_R"] or {}).items():
        add(f"{count:6d}  {site}")
    add("```\n")
    add(f"Construction R over the whole corpus: **{axes['R_construction']}**.\n")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("board", type=Path)
    parser.add_argument("--markdown", action="store_true")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    report = rank(json.loads(args.board.read_text(encoding="utf-8")))
    rendered = _markdown(report) if args.markdown else json.dumps(report, indent=2)
    if args.out:
        args.out.write_text(rendered + "\n", encoding="utf-8")
    else:
        print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
