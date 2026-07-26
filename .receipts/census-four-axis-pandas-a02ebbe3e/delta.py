#!/usr/bin/env python3
"""Delta from the d94f67a31 board to a02ebbe3e, ON THE CONSERVED SET ONLY.

A raw before/after diff of two censuses is not a delta. Two things make it lie:

1. **Terminal status.** A file that timed out in one run absorbed every panic
   and defect row it would have produced. When it later completes, those rows
   appear for the FIRST time. They are newly visible, not a regression. So the
   delta is computed only over files with the SAME terminal status in both
   runs, and newly-measurable files are reported as their own category.

2. **Absolute paths in occurrence keys.** `site:` and `occurrence:` coordinates
   embed the corpus's absolute filename, and the two runs read the corpus from
   different roots (python3.14 site-packages on the Mac, a pinned venv on
   battleaxe). Comparing them raw would report every row as both removed and
   added. Both sides are normalized to `<CORPUS>/...` first. The corpus itself
   is proven identical by CID, so this substitution loses nothing.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

OLD_ROOT = "/usr/local/lib/python3.14/site-packages/pandas"
NEW_ROOT_RE = re.compile(r"/home/tsavo/census-a02-venv/lib/python3\.12/site-packages/pandas")


def norm(key: str) -> str:
    key = key.replace(OLD_ROOT, "<CORPUS>")
    return NEW_ROOT_RE.sub("<CORPUS>", key)


def main() -> int:
    old = json.loads(Path(sys.argv[1]).read_text())
    rows = [json.loads(ln) for ln in Path(sys.argv[2]).read_text().splitlines() if ln.strip()]
    out = Path(sys.argv[3]) if len(sys.argv) > 3 else None

    completed = [r for r in rows if r["status"] == "completed"]
    new_files = {r["rel"] for r in completed}

    # The old run carried NO per-file deadline and recorded no crashes or
    # file-level panics, so every one of its 1421 files reached a terminal
    # `completed` state. Stated, not assumed:
    old_terminal_complete = (
        old["files"] == 1421
        and not old["fileLevelCrashes"]
        and not old["fileLevelPanics"]
    )

    # ---- construction axis, keyed by (kind, file, line, col) -------------
    old_con = {(g["kind"], g["file"], g["line"], g["col"]) for g in old["constructionGaps"]}
    new_con = {
        (kind, r["rel"], line, col)
        for r in completed
        for kind, line, col in r["constructionGaps"]
    }

    # ---- desugar axis, keyed by normalized (owner, occurrence) ----------
    old_des = {norm(x.replace("\t", "|", 1)) for x in old["desugarOccurrences"]}
    new_des = {norm(f"{o}|{occ}") for r in completed for o, occ in r["desugarPairs"]}

    # ---- panics and defects, keyed by their own coordinates -------------
    old_panics = {(p.get("owner"), norm(str(p.get("where")))) for p in old["desugarConstructionPanics"]}
    new_panics = {
        (p.get("owner"), norm(str(p.get("where"))))
        for r in completed
        for p in r["desugarPanics"]
    }
    old_defects = {(d["kind"], norm(str(d["where"])), norm(str(d["detail"]))[:200]) for d in old["desugarDefects"]}
    new_defects = {
        (d["kind"], norm(str(d["where"])), norm(str(d["detail"]))[:200])
        for r in completed
        for d in r["desugarDefects"]
    }

    def axis(name, o, n, old_total, new_total):
        return {
            "axis": name,
            "old": old_total,
            "new": new_total,
            "delta": new_total - old_total,
            "distinctOld": len(o),
            "distinctNew": len(n),
            "removed": len(o - n),
            "added": len(n - o),
            "unchanged": len(o & n),
        }

    payload = {
        "baseline": {"commit": "d94f67a31", "files": old["files"],
                     "everyFileTerminalComplete": old_terminal_complete},
        "head": {"commit": "a02ebbe3ed37d6d7cdd6b3108ba1da09504ba0d4",
                 "files": len(rows), "completed": len(completed)},
        "conservedSet": {
            "files": len(new_files),
            "note": "Both runs reached terminal `completed` on all 1421 files, so "
                    "the conserved set is the WHOLE corpus and the "
                    "newly-measurable category is EMPTY. It is non-empty only "
                    "against a run that carried a per-file deadline.",
            "newlyMeasurableFiles": [],
        },
        "axes": [
            axis("R_construction", old_con, new_con, old["R_construction"],
                 sum(len(r["constructionGaps"]) for r in completed)),
            axis("R_desugar", old_des, new_des, old["R_desugar"], len(new_des)),
            axis("desugarConstructionPanics", old_panics, new_panics,
                 len(old["desugarConstructionPanics"]),
                 sum(len(r["desugarPanics"]) for r in completed)),
            axis("desugarDefects", old_defects, new_defects,
                 len(old["desugarDefects"]),
                 sum(len(r["desugarDefects"]) for r in completed)),
        ],
        "panicOwnersDrained": Counter(
            o for o, _ in old_panics - new_panics
        ).most_common(25),
        "panicOwnersAdded": Counter(
            o for o, _ in new_panics - old_panics
        ).most_common(25),
        "defectKindsAdded": Counter(
            k[2][:120] for k in new_defects - old_defects
        ).most_common(25),
        "defectKindsRemoved": Counter(
            k[2][:120] for k in old_defects - new_defects
        ).most_common(25),
        "desugarOwnersAdded": Counter(
            x.split("|", 1)[0] for x in new_des - old_des
        ).most_common(25),
        "desugarOwnersRemoved": Counter(
            x.split("|", 1)[0] for x in old_des - new_des
        ).most_common(25),
    }

    text = json.dumps(payload, indent=2)
    if out:
        out.write_text(text)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
