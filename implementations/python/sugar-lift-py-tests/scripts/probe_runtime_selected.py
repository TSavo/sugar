"""Taxonomy: what does ``gapKind == "runtime-selected"`` actually record?

Diagnostic only -- reports, never repairs.

``lift_rpc._preconstruction_demand_rows`` joins context-manager demands to
call-contract demands on an EXACT serialized use-site coordinate:

    call = calls_by_site.get(site)
    if call is None:
        row["targetSymbol"] = None
        row["gapKind"] = "runtime-selected"
        continue

So ``runtime-selected`` is written by ONE branch: a miss in a dict keyed by a
JSON-serialized span. That is a lookup outcome, not a determination that the
manager is selected at runtime. This probe asks how many distinct facts are
wearing it, by classifying every runtime-selected use site:

  not-a-call            the manager expression is not a Call at all
                        (``with self.lock:``, a Subscript, a Name ...).
                        Nothing could ever have supplied a call row.
  call-no-row-anywhere  the manager IS a Call and no call-contract row touches
                        its span -- the callee is genuinely unenrolled.
  call-row-inside-span  the manager IS a Call and a call-contract row exists
                        STRICTLY INSIDE its span -- i.e. at the callee, not at
                        the call. The demand exists; this join cannot see it.
                        ``source_call_preconstruction`` handles exactly this
                        with ``calls_by_span.get(key) or _call_for_callee_span(
                        calls, key)``. This join has no such fallback.
  call-row-overlapping  some other span relationship -- reported separately
                        rather than folded into any bucket above.

usage:
  python probe_runtime_selected.py [--limit N]
"""

from __future__ import annotations

import argparse
import ast
import pathlib
import json
import sys
from collections import Counter, defaultdict


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--examples", type=int, default=8)
    parser.add_argument(
        "--coords",
        default=None,
        help=(
            "file of 'seat:startLine:startCol-endLine:endCol' With coordinates "
            "(the frontier panic rows). Restricts the taxonomy to the manager "
            "demands INSIDE those With statements, so the report describes the "
            "rows that actually panic rather than every demand in the corpus."
        ),
    )
    args = parser.parse_args(argv)

    from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
    from sugar_lift_py_tests.lift_rpc import (
        _call_contract_demand_rows,
        _context_manager_demand_rows,
    )
    from sugar_lift_python_source.source_oracle import SourceUnavailable, path_source
    from sugar_source_tree.tree import SourceTree

    corpus = authenticated_pandas_corpus()
    root = corpus.root
    print(f"CORPUS {corpus.distribution} {corpus.version} files={corpus.file_count}")

    # source_cid -> relative seat, so a row can name a file a reader can open.
    seat_by_cid: dict[str, str] = {}
    source_by_cid: dict[str, str] = {}
    for path in SourceTree(root).paths():
        try:
            source, _filename, source_cid = path_source(str(path))
        except SourceUnavailable:
            continue
        seat_by_cid[source_cid] = path.resolve().relative_to(root).as_posix()
        source_by_cid[source_cid] = source
    print(f"SEATS {len(seat_by_cid)}")

    call_rows = [
        row
        for row in _call_contract_demand_rows(root)
        if row.get("kind") == "call-contract-demand"
    ]
    cm_rows = _context_manager_demand_rows(root)
    print(f"ROWS cm={len(cm_rows)} call={len(call_rows)}")

    calls_by_site = {
        json.dumps(row["useSite"], sort_keys=True): row for row in call_rows
    }
    calls_by_cid: dict[str, list] = defaultdict(list)
    for row in call_rows:
        calls_by_cid[row["useSite"]["sourceCid"]].append(row["useSite"])

    # The exact join under test.
    unmatched = [
        row
        for row in cm_rows
        if calls_by_site.get(json.dumps(row["useSite"], sort_keys=True)) is None
    ]
    print(f"RUNTIME_SELECTED {len(unmatched)} of {len(cm_rows)} cm demands")
    if args.coords:
        wanted = []
        coord_path = pathlib.Path(args.coords)
        raw = (
            coord_path.read_text().splitlines()
            if coord_path.exists()
            else args.coords.split(";")
        )
        for line in raw:
            line = line.strip()
            if not line:
                continue
            seat, _, rest = line.rpartition(":")
            # 'seat:sl:sc-el:ec'
            head, _, tail = line.partition(":")
            span_text = line[len(head) + 1 :]
            start_text, _, end_text = span_text.partition("-")
            sl, _, sc = start_text.partition(":")
            el, _, ec = end_text.partition(":")
            wanted.append((head, int(sl), int(sc), int(el), int(ec)))
        cid_by_seat = {seat: cid for cid, seat in seat_by_cid.items()}
        selected = []
        for row in unmatched:
            site = row["useSite"]
            seat = seat_by_cid.get(site["sourceCid"])
            for w_seat, w_sl, w_sc, w_el, w_ec in wanted:
                if seat != w_seat:
                    continue
                if (site["startLine"], site["startCol"]) >= (w_sl, w_sc) and (
                    site["endLine"],
                    site["endCol"],
                ) <= (w_el, w_ec):
                    selected.append(row)
                    break
        print(
            f"RESTRICTED to {len(wanted)} panic With coordinates -> "
            f"{len(selected)} runtime-selected manager demands inside them"
        )
        unmatched = selected
    if args.limit is not None:
        unmatched = unmatched[: args.limit]

    # Manager-expression node kind at each coordinate, from the same bytes.
    kinds_by_cid: dict[str, dict[tuple, str]] = {}

    def kind_at(source_cid: str, span: tuple) -> str | None:
        table = kinds_by_cid.get(source_cid)
        if table is None:
            table = {}
            source = source_by_cid.get(source_cid)
            if source is not None:
                try:
                    tree = ast.parse(source)
                except SyntaxError:
                    tree = None
                if tree is not None:
                    for node in ast.walk(tree):
                        if not isinstance(node, (ast.With, ast.AsyncWith)):
                            continue
                        for item in node.items:
                            expression = item.context_expr
                            key = (
                                expression.lineno,
                                expression.col_offset,
                                expression.end_lineno,
                                expression.end_col_offset,
                            )
                            table[key] = type(expression).__name__
            kinds_by_cid[source_cid] = table
        return table.get(span)

    def contains(outer: dict, inner: dict) -> bool:
        """inner span strictly within outer span (same source)."""
        if outer["sourceCid"] != inner["sourceCid"]:
            return False
        start_ok = (inner["startLine"], inner["startCol"]) >= (
            outer["startLine"],
            outer["startCol"],
        )
        end_ok = (inner["endLine"], inner["endCol"]) <= (
            outer["endLine"],
            outer["endCol"],
        )
        return start_ok and end_ok and (inner != outer)

    taxonomy: Counter[str] = Counter()
    kind_counts: Counter[str] = Counter()
    examples: dict[str, list[str]] = defaultdict(list)

    for row in unmatched:
        site = row["useSite"]
        source_cid = site["sourceCid"]
        seat = seat_by_cid.get(source_cid, "<unknown seat>")
        span = (
            site["startLine"],
            site["startCol"],
            site["endLine"],
            site["endCol"],
        )
        node_kind = kind_at(source_cid, span) or "<not-found>"
        kind_counts[node_kind] += 1
        inner = [
            other for other in calls_by_cid.get(source_cid, ()) if contains(site, other)
        ]
        # A call row nested ANYWHERE inside the manager span is not evidence:
        # `with open(pick(x)):` nests a row for `pick` that is an ARGUMENT, not
        # the manager's callee. The manager's own callee is the one that starts
        # exactly where the manager expression starts -- `f(...)` and `a.b(...)`
        # both put the callee at the call's own start offset.
        callee_prefix = [
            other
            for other in inner
            if (other["startLine"], other["startCol"])
            == (site["startLine"], site["startCol"])
        ]
        if node_kind != "Call":
            bucket = "not-a-call"
        elif callee_prefix:
            bucket = "callee-row-at-manager-start"
            inner = callee_prefix
        elif inner:
            bucket = "nested-argument-row-only"
        else:
            overlapping = [
                other
                for other in calls_by_cid.get(source_cid, ())
                if other["startLine"] == site["startLine"] and other != site
            ]
            bucket = (
                "call-row-overlapping" if overlapping else "call-no-row-anywhere"
            )
        taxonomy[bucket] += 1
        where = f"{seat}:{span[0]}:{span[1]}"
        if len(examples[bucket]) < args.examples:
            detail = ""
            source_text = source_by_cid.get(source_cid)
            if source_text is not None:
                lines = source_text.splitlines()
                if 0 < span[0] <= len(lines):
                    detail += "  |" + lines[span[0] - 1].strip()[:90]
            if bucket in ("callee-row-at-manager-start", "nested-argument-row-only"):
                first = inner[0]
                detail = (
                    f"  callee row at {first['startLine']}:{first['startCol']}"
                    f"-{first['endLine']}:{first['endCol']}"
                )
            examples[bucket].append(f"{where} [{node_kind}]{detail}")

    print("\nMANAGER EXPRESSION KIND at runtime-selected sites")
    for kind, count in kind_counts.most_common():
        print(f"  {count:>5}  {kind}")

    print("\nTAXONOMY -- distinct facts wearing one label")
    for bucket, count in taxonomy.most_common():
        print(f"  {count:>5}  {bucket}")
        for line in examples[bucket]:
            print(f"           {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
