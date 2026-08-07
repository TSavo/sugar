"""Corpus population of context-manager demand kinds, one walk.

Diagnostic only.

A slice of 178 seats understates every population it samples -- it understated
``@contextmanager`` badly. This gives the whole-corpus denominator for the
reasons that are decided at DEMAND time, by minting the same table the census
mints (``_preconstruction_demand_rows``) and counting its ``gapKind``.

What this CAN say: the corpus population of demand-side kinds
(``runtime-selected`` and ``None`` -- i.e. a call row was joined).

What this CANNOT say: the population of reasons produced at DERIVATION time
(``source-body-gap``, ``dynamic-export``, ``call-target-off-population``,
canonicalization refusals). Those exist only once a file is constructed, so
their corpus population needs a full census, not a walk. Do not read a number
from here as if it covered them.

For each demanded manager it also records the callee spelling, so the reasons
can be ranked by what they are actually about.

usage:
  python probe_cm_demand_kinds.py [--examples N]
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections import Counter, defaultdict


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--examples", type=int, default=10)
    args = parser.parse_args(argv)

    from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
    from sugar_lift_py_tests.lift_rpc import _preconstruction_demand_rows
    from sugar_lift_python_source.source_oracle import SourceUnavailable, path_source
    from sugar_source_tree.tree import SourceTree

    corpus = authenticated_pandas_corpus()
    root = corpus.root
    print(f"CORPUS {corpus.distribution} {corpus.version} files={corpus.file_count}")

    seat_by_cid: dict[str, str] = {}
    source_by_cid: dict[str, str] = {}
    for path in SourceTree(root).paths():
        try:
            source, _filename, source_cid = path_source(str(path))
        except SourceUnavailable:
            continue
        seat_by_cid.setdefault(source_cid, path.resolve().relative_to(root).as_posix())
        source_by_cid.setdefault(source_cid, source)

    rows = _preconstruction_demand_rows(root)
    cm_rows = [row for row in rows if row.get("kind") == "context-manager-demand"]
    print(f"CM_DEMANDS {len(cm_rows)}  (of {len(rows)} demand rows)")

    kinds: Counter[str] = Counter()
    symbols: Counter[tuple] = Counter()
    examples: dict[str, list[str]] = defaultdict(list)

    for row in cm_rows:
        kind = row.get("gapKind") or "<joined: a call row was found>"
        kinds[str(kind)] += 1
        symbols[(str(kind), str(row.get("targetSymbol")))] += 1
        site = row["useSite"]
        seat = seat_by_cid.get(site["sourceCid"], "<unknown>")
        if len(examples[str(kind)]) < args.examples:
            text = ""
            source = source_by_cid.get(site["sourceCid"])
            if source is not None:
                lines = source.splitlines()
                if 0 < site["startLine"] <= len(lines):
                    text = "  |" + lines[site["startLine"] - 1].strip()[:88]
            examples[str(kind)].append(
                f"{seat}:{site['startLine']}:{site['startCol']}{text}"
            )

    print("\nDEMAND KIND -- whole corpus")
    for kind, count in kinds.most_common():
        print(f"  {count:>6}  {kind}")
        for line in examples[kind]:
            print(f"           {line}")

    print("\nTOP TARGET SYMBOLS PER KIND")
    for (kind, symbol), count in symbols.most_common(30):
        print(f"  {count:>6}  [{kind}] {symbol}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
