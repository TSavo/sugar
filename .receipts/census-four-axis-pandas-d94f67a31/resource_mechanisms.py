#!/usr/bin/env python3
"""What capability do the 811 resource/protocol With sites REQUIRE?

Same hard constraint as the assertion pass: bucket by missing capability, never
by manager spelling. `open`, `option_context` and `HDFStore` describe the
corpus; they are never admission rules.

The resource contract is: construct manager, run `__enter__`, bind, run body,
run `__exit__` on EVERY completed and halted ExitSet edge, with suppression
disposition taken from authenticated protocol/source evidence -- and unknown
suppression staying loud. The capabilities below are read off what each site
demands of that contract.

  E1 exit-on-every-edge      baseline: __exit__ must run on the completed edge
                             and on every halted edge. Every resource site
                             needs this; it is the contract itself.
  E2 bind-entered-value      `as f` -- __enter__'s result binds to a name the
                             body uses. Requires the entered value, not the
                             manager, to be the bound thing.
  E3 destructure-entered-value
                             `as (a, b)` -- the binding target is not a simple
                             Name. Requires unpack of the entered value.
  E4 sequence-multiple-managers
                             several managers on one statement: entered in
                             order, exited in REVERSE order, each exit running
                             on every edge including edges raised by a later
                             manager's __enter__.
  E5 resolve-manager-from-value
                             the manager expression is not a lexical name/call
                             of a known constructor (variable, subscript,
                             fixture, conditional): the manager identity
                             resolves from a value.
  E6 route-additional-exits  the body carries its own return/break/continue/
                             raise/yield edges, each of which must still run
                             __exit__.
  E7 suppression-disposition-unknown
                             nothing at the site authenticates whether this
                             manager suppresses. Under the ruling this must
                             stay LOUD rather than defaulting to non-suppress.
"""

from __future__ import annotations

import ast
import json
import sys
from collections import Counter
from pathlib import Path

# Managers whose suppression disposition is authenticated by the standard
# library / documented protocol. Everything else is UNKNOWN and stays loud --
# this list is evidence, not an admission arm: absence never admits, it only
# marks the obligation as still owed.
AUTHENTICATED_SUPPRESSORS = {"suppress", "contextlib.suppress"}
AUTHENTICATED_NON_SUPPRESSORS = {
    "open", "TemporaryDirectory", "NamedTemporaryFile", "closing",
    "contextlib.closing", "BytesIO", "StringIO", "ZipFile", "zipfile.ZipFile",
    "catch_warnings", "warnings.catch_warnings",
}

EXIT_NODES = (ast.Return, ast.Break, ast.Continue, ast.Raise,
              ast.Yield, ast.YieldFrom)


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


def resolvable_manager(expr: ast.AST) -> bool:
    target = expr.func if isinstance(expr, ast.Call) else expr
    return isinstance(target, (ast.Name, ast.Attribute))


def body_has_own_exits(node: ast.AST) -> bool:
    for child in ast.walk(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(child, EXIT_NODES):
            return True
    return False


def requirements(node: ast.AST) -> tuple[set[str], list[str]]:
    reqs = {"E1-exit-on-every-edge"}
    heads = []
    if len(node.items) > 1:
        reqs.add("E4-sequence-multiple-managers")
    for item in node.items:
        expr = item.context_expr
        head = head_of(expr)
        heads.append(head)
        tail = head.rsplit(".", 1)[-1]

        if item.optional_vars is not None:
            if isinstance(item.optional_vars, ast.Name):
                reqs.add("E2-bind-entered-value")
            else:
                reqs.add("E3-destructure-entered-value")

        if not resolvable_manager(expr):
            reqs.add("E5-resolve-manager-from-value")

        if (
            head not in AUTHENTICATED_SUPPRESSORS
            and tail not in AUTHENTICATED_SUPPRESSORS
            and head not in AUTHENTICATED_NON_SUPPRESSORS
            and tail not in AUTHENTICATED_NON_SUPPRESSORS
        ):
            reqs.add("E7-suppression-disposition-unknown")

    for stmt in node.body:
        if body_has_own_exits(stmt):
            reqs.add("E6-route-additional-exits")
            break
    return reqs, heads


def main() -> int:
    part = json.loads(Path(sys.argv[1]).read_text())
    dump = json.loads(Path(sys.argv[2]).read_text())
    out = Path(sys.argv[3])
    bucket_name = sys.argv[4] if len(sys.argv) > 4 else "resource-protocol"
    root = Path(dump["root"])

    rows = [r for r in part["detail"] if r["bucket"] == bucket_name]
    by_file: dict[str, list[dict]] = {}
    for r in rows:
        by_file.setdefault(r["file"], []).append(r)

    marginal: Counter = Counter()
    vectors: Counter = Counter()
    per_row = []
    unresolved = 0
    for rel, rs in by_file.items():
        try:
            tree = ast.parse((root / rel).read_text(errors="replace"))
        except Exception:  # noqa: BLE001
            unresolved += len(rs)
            continue
        index = {
            (n.lineno, n.col_offset): n
            for n in ast.walk(tree)
            if isinstance(n, (ast.With, ast.AsyncWith))
        }
        for r in rs:
            node = index.get((r["line"], r["col"]))
            if node is None:
                unresolved += 1
                continue
            reqs, heads = requirements(node)
            for q in reqs:
                marginal[q] += 1
            vectors["+".join(sorted(reqs))] += 1
            per_row.append({**r, "requires": sorted(reqs), "heads": heads})

    total = sum(vectors.values())
    remaining = set(range(len(per_row)))
    cover = []
    while remaining:
        best, gain = None, 0
        for cap in marginal:
            g = sum(1 for i in remaining if cap in per_row[i]["requires"])
            if g > gain:
                best, gain = cap, g
        if best is None:
            break
        cover.append((best, gain))
        remaining = {i for i in remaining if best not in per_row[i]["requires"]}

    payload = {
        "bucket": bucket_name,
        "sitesClassified": total,
        "sitesUnresolved": unresolved,
        "capabilityMarginalCounts": marginal.most_common(),
        "capabilityVectorPartition": vectors.most_common(),
        "distinctCapabilityVectors": len(vectors),
        "greedyMinimalCover": cover,
        "coverSize": len(cover),
        "rows": per_row,
    }
    out.write_text(json.dumps(payload))
    print(f"bucket                 : {bucket_name}")
    print(f"sites classified       : {total}   unresolved: {unresolved}")
    print(f"distinct capability vectors: {len(vectors)}")
    print()
    print("--- MARGINAL ---")
    for cap, n in marginal.most_common():
        print(f"{n:6d}  ({100*n/total:5.1f}%)  {cap}")
    print()
    print(f"--- PARTITION (sums to {total}) ---")
    for vec, n in vectors.most_common(20):
        print(f"{n:6d}  {vec}")
    print()
    print("--- greedy minimal cover ---")
    for cap, gain in cover:
        print(f"  +{gain:6d} sites  {cap}")
    print(f"  => {len(cover)} capabilities cover all {total} sites")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
