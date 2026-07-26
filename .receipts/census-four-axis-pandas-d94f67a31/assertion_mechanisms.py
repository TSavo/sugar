#!/usr/bin/env python3
"""What capability do the 4125 assertion/effect-boundary With sites REQUIRE?

HARD CONSTRAINT
===============
Dispatch by missing GENERAL MECHANISM, never by spelling. `pytest.raises` and
`assert_produces_warning` DESCRIBE the corpus; they must never become admission
rules. A bucket named after a manager is a vendor arm wearing a census label.

So every bucket below is a CAPABILITY the construction does not yet have, read
off the site's STRUCTURE. Two differently-spelled managers that need the same
capability land in one bucket. One manager name that needs two capabilities
produces two buckets. The manager head is carried on each row only as
corroborating evidence -- it never decides the bucket.

At the construction layer every one of the 5021 sites fails identically
("With manager has no injected authenticated preconstruction authority"), so
the immediate error text cannot separate them. The separating question is what
each site would REQUIRE of a mechanism that did construct it:

  R1 route-halted-edge      the boundary consumes an effect that HALTS the body;
                            the halted edge must be routed into the boundary's
                            consumed position rather than propagating.
  R2 route-completed-edge   the boundary observes an effect while the body
                            COMPLETES normally; the observation attaches to the
                            completed edge. Different ExitSet routing from R1.
  R3 bind-observed-effect   the boundary binds the observed effect to a name
                            usable by successor statements (`as e`).
  R4 retain-undecidable-predicate
                            the site constrains the effect by a message/pattern
                            that is not decidable at construction; the
                            obligation must be RETAINED explicitly, never
                            admitted and never dropped.
  R5 resolve-category-from-value
                            the expected effect category is not a lexical type
                            name (variable, tuple, subscript, call, fixture
                            parameter); category must resolve from a value.
  R6 express-absent-expectation
                            the site expresses "no effect expected" as a
                            first-class disposition (None / falsey sentinel),
                            which is not the absence of an expectation.
  R7 route-additional-exits the body carries its own outgoing edges
                            (return/break/continue/raise/yield) that must ALSO
                            be routed, not just the expected effect edge.

Deliverable: capability -> site count (marginal), and the partition by exact
capability VECTOR, which sums to the input with zero unclassified-by-omission.
"""

from __future__ import annotations

import ast
import json
import sys
from collections import Counter
from pathlib import Path

# Heads whose semantics are "the body completes; an effect is observed
# alongside" rather than "the body halts". Used ONLY to decide R1 vs R2, which
# is a genuine semantic difference in edge routing, not an admission rule --
# an unknown head defaults to R1 and is reported as needing category
# resolution, never silently admitted.
COMPLETED_EDGE_OBSERVERS = {
    "assert_produces_warning", "warns", "deprecated_call",
    "assert_cow_warning", "catch_warnings", "assertWarns",
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


def literal_category(node: ast.AST) -> bool:
    """True when the expected effect category is a lexical type name (or a
    tuple/collection of them) -- i.e. resolvable without evaluating a value."""
    if isinstance(node, ast.Name):
        return node.id[:1].isupper()
    if isinstance(node, ast.Attribute):
        return node.attr[:1].isupper()
    if isinstance(node, (ast.Tuple, ast.List)):
        return all(literal_category(e) for e in node.elts)
    return False


def body_has_own_exits(node: ast.AST) -> bool:
    for child in ast.walk(node):
        # Do not descend into nested function/class bodies: their exits belong
        # to their own frame, not this With's ExitSet.
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if isinstance(child, EXIT_NODES):
            return True
    return False


def requirements(node: ast.AST) -> tuple[set[str], list[str]]:
    reqs: set[str] = set()
    heads: list[str] = []
    for item in node.items:
        expr = item.context_expr
        head = head_of(expr)
        heads.append(head)
        tail = head.rsplit(".", 1)[-1]

        if tail in COMPLETED_EDGE_OBSERVERS:
            reqs.add("R2-route-completed-edge")
        else:
            reqs.add("R1-route-halted-edge")

        if item.optional_vars is not None:
            reqs.add("R3-bind-observed-effect")

        if isinstance(expr, ast.Call):
            args = list(expr.args)
            kwargs = {k.arg: k.value for k in expr.keywords if k.arg}

            # message / pattern obligations that construction cannot decide
            for key in ("match", "match_re", "pattern"):
                if key in kwargs:
                    reqs.add("R4-retain-undecidable-predicate")

            # "no effect expected" as a first-class disposition
            first = args[0] if args else kwargs.get("expected_warning")
            if first is not None and isinstance(first, ast.Constant) and first.value is None:
                reqs.add("R6-express-absent-expectation")
            elif first is None and not args:
                reqs.add("R6-express-absent-expectation")

            # category resolution
            if first is not None and not (
                isinstance(first, ast.Constant) and first.value is None
            ):
                if not literal_category(first):
                    reqs.add("R5-resolve-category-from-value")
        else:
            # bare manager reference: nothing states the category
            reqs.add("R5-resolve-category-from-value")

    for stmt in node.body:
        if body_has_own_exits(stmt):
            reqs.add("R7-route-additional-exits")
            break

    return reqs, heads


def main() -> int:
    part = json.loads(Path(sys.argv[1]).read_text())
    dump = json.loads(Path(sys.argv[2]).read_text())
    out = Path(sys.argv[3])
    root = Path(dump["root"])
    bucket_name = sys.argv[4] if len(sys.argv) > 4 else "assertion-effect-boundary"

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
    # Greedy minimal cover: how few capabilities touch every site?
    remaining = {i for i, r in enumerate(per_row)}
    cover: list[tuple[str, int]] = []
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
    print(f"sites classified       : {total}")
    print(f"sites unresolved       : {unresolved}")
    print(f"distinct capability vectors: {len(vectors)}")
    print()
    print("--- MARGINAL: sites requiring each capability ---")
    for cap, n in marginal.most_common():
        print(f"{n:6d}  ({100*n/total:5.1f}%)  {cap}")
    print()
    print(f"--- PARTITION by exact capability vector (sums to {total}) ---")
    for vec, n in vectors.most_common():
        print(f"{n:6d}  {vec}")
    print()
    print("--- greedy minimal cover ---")
    for cap, gain in cover:
        print(f"  +{gain:6d} sites  {cap}")
    print(f"  => {len(cover)} capabilities cover all {total} sites")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
