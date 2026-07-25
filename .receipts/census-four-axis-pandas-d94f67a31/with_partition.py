#!/usr/bin/env python3
"""Partition the `With` construction residual into the TWO RULED CONTRACTS.

A merged 5021 is dishonest (#6248). The census keys construction gaps by
node.kind, so every With lands in one family. This resolves each deduped
(file,line,col) gap site back to its actual `with` head via AST and assigns it
to exactly one of the two ruled buckets:

  ASSERTION / EFFECT-BOUNDARY  consumes or checks an observed effect; routes
                               every outgoing edge; retains undecidable
                               message/category obligations explicitly; no
                               vendor-name admission arms.

  RESOURCE / PROTOCOL          constructs manager, __enter__, binding, body,
                               __exit__; runs exit on every completed and
                               halted edge; suppression disposition from
                               authenticated protocol/source evidence; unknown
                               suppression stays loud.

Both share ONE ExitSet algebra. The split is the dispatch unit, not two
control models.

The vocabulary below was ENUMERATED from the corpus (147 distinct manager
heads over 8048 with-statements), not guessed. Anything unrecognised is
reported as `unclassified` with its head, so the residual stays visible
instead of being absorbed into whichever bucket is larger.

Keyed by occurrence: one row per deduped construction-gap site, so the same
site cannot be tallied under two label prefixes (the 392-vs-196 failure).
"""

from __future__ import annotations

import ast
import json
import sys
from collections import Counter
from pathlib import Path

# --- effect-boundary: the manager's job is to observe/consume an effect ----
ASSERTION = {
    "pytest.raises", "raises", "pytest.warns", "warns",
    "pytest.deprecated_call", "deprecated_call",
    "tm.assert_produces_warning", "assert_produces_warning",
    "tm.raises_chained_assignment_error", "raises_chained_assignment_error",
    "tm.external_error_raised", "external_error_raised",
    "tm.assert_cow_warning", "assert_cow_warning",
    "assert_raises", "assertRaises", "assertWarns",
}

# --- protocol resource: manager/__enter__/__exit__ over a real resource ----
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


def bucket(head: str) -> str:
    tail = head.rsplit(".", 1)[-1]
    if head in ASSERTION or tail in ASSERTION:
        return "assertion-effect-boundary"
    if head in RESOURCE or tail in RESOURCE:
        return "resource-protocol"
    return "unclassified"


def main() -> int:
    dump = json.loads(Path(sys.argv[1]).read_text())
    root = Path(dump["root"])
    out = Path(sys.argv[2])

    sites = [g for g in dump["constructionGaps"] if g["kind"] == "With"]
    by_file: dict[str, list[dict]] = {}
    for g in sites:
        by_file.setdefault(g["file"], []).append(g)

    rows: list[dict] = []
    unresolved = 0
    for rel, gaps in by_file.items():
        try:
            tree = ast.parse((root / rel).read_text(errors="replace"))
        except Exception:  # noqa: BLE001
            unresolved += len(gaps)
            rows.extend({**g, "bucket": "unresolved", "head": None} for g in gaps)
            continue
        index = {
            (n.lineno, n.col_offset): n
            for n in ast.walk(tree)
            if isinstance(n, (ast.With, ast.AsyncWith))
        }
        for g in gaps:
            node = index.get((g["line"], g["col"]))
            if node is None:
                unresolved += 1
                rows.append({**g, "bucket": "unresolved", "head": None})
                continue
            heads = [head_of(it.context_expr) for it in node.items]
            buckets = [bucket(h) for h in heads]
            # A multi-manager With is assertion ONLY if every manager is an
            # assertion manager; any resource participant makes it a resource
            # site, because __exit__ must run on every edge.
            if len(set(buckets)) == 1:
                b = buckets[0]
            elif "resource-protocol" in buckets:
                b = "resource-protocol"
            elif "unclassified" in buckets:
                b = "unclassified"
            else:
                b = buckets[0]
            rows.append(
                {**g, "bucket": b, "head": heads[0], "heads": heads,
                 "managers": len(heads)}
            )

    by_bucket = Counter(r["bucket"] for r in rows)
    by_head = Counter(f"{r['bucket']}\t{r['head']}" for r in rows)
    payload = {
        "totalWithGapSites": len(sites),
        "rows": len(rows),
        "unresolved": unresolved,
        "byBucket": by_bucket.most_common(),
        "multiManagerSites": sum(1 for r in rows if r.get("managers", 1) > 1),
        "topHeads": [
            {"bucket": k.split("\t")[0], "head": k.split("\t")[1], "sites": v}
            for k, v in by_head.most_common(30)
        ],
        "unclassifiedHeads": Counter(
            r["head"] for r in rows if r["bucket"] == "unclassified"
        ).most_common(40),
        "detail": rows,
    }
    out.write_text(json.dumps(payload))
    print(json.dumps({k: v for k, v in payload.items() if k != "detail"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
