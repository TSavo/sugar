#!/usr/bin/env python3
"""Read the durable rows and render the four-axis board. Nothing is inferred.

Every quantity here is a count over `rows.jsonl`. The script REFUSES to render
an axis when conservation fails, because a partial denominator rendered as a
board is exactly how a killed run gets banked as a zero.

THE SPLIT
=========

`R_desugar` as printed by `census.py` is a MIXED number. It sums typed refusals
at the desugar door with typed red effects, and the two mean opposite things:
one is work owed, the other is semantics correctly accounted for. Summing them
overstates the work. The split is taken off the AUTHENTICATED OCCURRENCE-KEY
PREFIX (the coordinate the effect itself carries), never off family names:

  `desugar-call:`   the door REFUSED (SugarNotWritten). Construction gap --
                    work owed, one row per reduction.
  `boundary:`       CoverageGapEffect. An EXPLICIT incomplete obligation the
                    system declares about itself -- owed, and honest about it.
  `site:` /
  `occurrence:` /
  `occurrence-cid:` the effect states its own authenticated source coordinate.
                    A correctly constructed effect: ACCOUNTED SEMANTICS, not
                    work. This is the bucket that inflates the raw figure.
  `blame:`          only a blame locus, no fragment coordinate. Reported on its
                    own -- it is weaker authentication and must not be silently
                    folded into the `site:` bucket.

`desugarConstructionPanics` and `desugarDefects` are NEVER added to R_desugar;
they are the third and fourth axes and are printed separately.
"""

from __future__ import annotations

import ast
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

EXPECTED_FILES = 1421

PREFIX_BUCKET = {
    "desugar-call": "3-construction-gap-refusal",
    "boundary": "2-explicit-incomplete-obligation",
    "site": "1-accounted-semantics",
    "occurrence": "1-accounted-semantics",
    "occurrence-cid": "1-accounted-semantics",
    "blame": "4-blame-only-weak-coordinate",
}

# Enumerated from the corpus (see with_partition.py on the d94f67a31 board):
# 147 distinct manager heads over 8048 with-statements. Not guessed.
ASSERTION = {
    "pytest.raises", "raises", "pytest.warns", "warns",
    "pytest.deprecated_call", "deprecated_call",
    "tm.assert_produces_warning", "assert_produces_warning",
    "tm.raises_chained_assignment_error", "raises_chained_assignment_error",
    "tm.external_error_raised", "external_error_raised",
    "tm.assert_cow_warning", "assert_cow_warning",
    "assert_raises", "assertRaises", "assertWarns",
}
RESOURCE = {
    "option_context", "pd.option_context", "cf.option_context",
    "cf.config_prefix", "config_context", "set_option",
    "np.errstate", "errstate", "warnings.catch_warnings", "catch_warnings",
    "mpl.rc_context", "rc_context", "com.temp_setattr", "temp_setattr",
    "tm.set_timezone", "set_timezone", "monkeypatch.context",
    "ensure_safe_environment_variables",
    "open", "get_handle", "icom.get_handle", "contextlib.closing", "closing",
    "BytesIO", "StringIO", "zipfile.ZipFile", "tarfile.open", "gzip.open",
    "bz2.open", "lzma.open", "tempfile.TemporaryDirectory",
    "tempfile.NamedTemporaryFile", "TemporaryDirectory",
    "NamedTemporaryFile", "tm.ensure_clean", "ensure_clean",
    "ensure_removed", "tm.decompress_file", "decompress_file",
    "subprocess.Popen", "Popen", "tables.open_file", "open_file",
    "ExcelFile", "pd.ExcelFile", "ExcelWriter", "pd.ExcelWriter",
    "HDFStore", "pd.HDFStore", "StataReader", "read_stata", "read_json",
    "read_sas", "pd.read_sas", "TextParser", "parser.read_csv",
    "read_csv", "SASReader",
    "sql.SQLDatabase", "SQLDatabase", "pandasSQL_builder",
    "pandasSQL.run_transaction", "run_transaction", "conn.begin",
    "con.begin", "conn.connect", "conn.cursor", "con.cursor",
    "engine.connect", "contextlib.suppress", "suppress",
}


def head_of(node: ast.AST) -> str:
    if isinstance(node, ast.Call):
        node = node.func
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts)) if parts else type(node).__name__


def with_bucket(head: str) -> str:
    tail = head.rsplit(".", 1)[-1]
    if head in ASSERTION or tail in ASSERTION:
        return "assertion-effect-boundary"
    if head in RESOURCE or tail in RESOURCE:
        return "resource-protocol"
    return "unclassified"


def main() -> int:
    rows_path = Path(sys.argv[1])
    corpus_root = Path(sys.argv[2])
    out_path = Path(sys.argv[3]) if len(sys.argv) > 3 else None

    rows = [json.loads(ln) for ln in rows_path.read_text().splitlines() if ln.strip()]

    # ---- conservation, stated before any axis is rendered -----------------
    keys = [(r["idx"], r["rel"], r["sha256"]) for r in rows]
    dup_keys = [k for k, n in Counter(keys).items() if n > 1]
    dup_idx = [i for i, n in Counter(r["idx"] for r in rows).items() if n > 1]
    cids = {r.get("corpusCid") for r in rows}
    status = Counter(r["status"] for r in rows)
    measured_once = len(set(keys))

    conserved = (
        measured_once == EXPECTED_FILES
        and not dup_keys
        and not dup_idx
        and len(cids) == 1
    )

    contamination = [
        r["rel"]
        for r in rows
        if "No module named 'sugar" in (r.get("stderrTail") or "")
        or "No module named 'sugar" in (r.get("fileCrash") or "")
    ]

    completed = [r for r in rows if r["status"] == "completed"]
    timeouts = [r for r in rows if r["status"] == "timeout"]
    crashes = [r for r in rows if r["status"] == "crash"]
    malformed = [r for r in rows if r["status"] == "malformed"]

    # ---- axis 1: construction --------------------------------------------
    con_families = Counter()
    for r in completed:
        for kind, _l, _c in r["constructionGaps"]:
            con_families[kind] += 1
    r_construction = sum(con_families.values())

    # ---- axis 2: desugar, and its four disjoint quantities ---------------
    pairs = set()
    per_file_pair_total = 0
    for r in completed:
        per_file_pair_total += len(r["desugarPairs"])
        for owner, occ in r["desugarPairs"]:
            pairs.add((owner, occ))
    r_desugar = len(pairs)
    cross_file_dupes = per_file_pair_total - r_desugar

    split = Counter()
    split_owners = defaultdict(Counter)
    unknown_prefix = Counter()
    for owner, occ in pairs:
        prefix = occ.split(":", 1)[0]
        bucket = PREFIX_BUCKET.get(prefix)
        if bucket is None:
            unknown_prefix[prefix] += 1
            bucket = "0-UNKNOWN-PREFIX"
        split[bucket] += 1
        split_owners[bucket][owner] += 1

    # ---- axes 3 and 4 -----------------------------------------------------
    desugar_panics = [p for r in completed for p in r["desugarPanics"]]
    desugar_defects = [d for r in completed for d in r["desugarDefects"]]
    file_panics = [
        {"rel": r["rel"], **r["fileConstructionPanic"]}
        for r in completed
        if r.get("fileConstructionPanic")
    ]

    # ---- With partition, fresh -------------------------------------------
    with_sites = defaultdict(list)
    for r in completed:
        for kind, line, col in r["constructionGaps"]:
            if kind in ("With", "AsyncWith"):
                with_sites[r["rel"]].append((line, col))
    with_buckets = Counter()
    with_heads = Counter()
    with_unresolved = 0
    for rel, sites in with_sites.items():
        try:
            tree = ast.parse((corpus_root / rel).read_text(errors="replace"))
        except Exception:  # noqa: BLE001
            with_unresolved += len(sites)
            continue
        index = {
            (n.lineno, n.col_offset): n
            for n in ast.walk(tree)
            if isinstance(n, (ast.With, ast.AsyncWith))
        }
        for line, col in sites:
            node = index.get((line, col))
            if node is None:
                with_unresolved += 1
                continue
            heads = [head_of(it.context_expr) for it in node.items]
            buckets = [with_bucket(h) for h in heads]
            # Any resource participant makes the site a resource site:
            # __exit__ must run on every edge.
            if len(set(buckets)) == 1:
                b = buckets[0]
            elif "resource-protocol" in buckets:
                b = "resource-protocol"
            elif "unclassified" in buckets:
                b = "unclassified"
            else:
                b = buckets[0]
            with_buckets[b] += 1
            if b == "unclassified":
                with_heads[heads[0]] += 1

    loads = [r["loadAfter"] for r in rows if isinstance(r.get("loadAfter"), (int, float))]
    payload = {
        "measuredCommit": "a02ebbe3ed37d6d7cdd6b3108ba1da09504ba0d4",
        "evidenceStatus": "completed, commit-pinned, provisional",
        "corpusCid": sorted(c for c in cids if c),
        "corpusRoot": str(corpus_root),
        "conservation": {
            "expectedFiles": EXPECTED_FILES,
            "rowsWritten": len(rows),
            "distinctKeys": measured_once,
            "conserved": conserved,
            "method": "(corpusCid, idx, rel, sha256) -- sha256 of file bytes "
                      "authenticates the thing measured; position is not identity",
            "duplicateKeys": dup_keys,
            "duplicateIndices": dup_idx,
            "distinctCorpusCids": len(cids),
        },
        "terminalStatus": dict(status),
        "R_timeout": len(timeouts),
        "timeoutFiles": [{"idx": r["idx"], "rel": r["rel"], "bound": r.get("timeoutBound")} for r in timeouts],
        "crashes": [{"idx": r["idx"], "rel": r["rel"], "detail": r.get("fileCrash")} for r in crashes],
        "malformed": [{"idx": r["idx"], "rel": r["rel"], "exit": r.get("exit")} for r in malformed],
        "contaminationRows": contamination,
        "loadDuringRun": {
            "min": min(loads) if loads else None,
            "max": max(loads) if loads else None,
            "note": "the box was shared; counter ratios survive contention, wall times do not. No timing is claimed.",
        },
        "axes": {
            "R_construction": r_construction,
            "R_desugar": r_desugar,
            "desugarConstructionPanics": len(desugar_panics),
            "desugarDefects": len(desugar_defects),
            "fileLevelConstructionPanics": len(file_panics),
        },
        "R_desugar_split": {
            "raw": r_desugar,
            "buckets": dict(split),
            "owed": split["3-construction-gap-refusal"] + split["2-explicit-incomplete-obligation"],
            "accountedSemantics": split["1-accounted-semantics"],
            "byBucketOwners": {k: v.most_common(15) for k, v in split_owners.items()},
            "unknownPrefixes": dict(unknown_prefix),
        },
        "crossFileOccurrenceCollisions": cross_file_dupes,
        "constructionFamilies": con_families.most_common(40),
        "desugarOwners": Counter(o for o, _ in pairs).most_common(40),
        "desugarPanicOwners": Counter(
            p.get("owner") or "unknown" for p in desugar_panics
        ).most_common(40),
        "desugarDefectKinds": Counter(
            f"{d['kind']}:{d['detail']}" for d in desugar_defects
        ).most_common(40),
        "fileConstructionPanicOwners": Counter(
            p.get("owner") or "unknown" for p in file_panics
        ).most_common(40),
        "withPartition": {
            "sites": sum(with_buckets.values()),
            "byBucket": dict(with_buckets),
            "unresolved": with_unresolved,
            "unclassifiedHeads": with_heads.most_common(40),
        },
    }

    if not conserved:
        payload["REFUSED"] = (
            f"conservation failed: {measured_once} distinct keys against "
            f"{EXPECTED_FILES} corpus files. Axes above are PARTIAL and must not "
            f"be read as a board."
        )

    text = json.dumps(payload, indent=2)
    if out_path:
        out_path.write_text(text)
    print(text)
    return 0 if conserved else 1


if __name__ == "__main__":
    raise SystemExit(main())
