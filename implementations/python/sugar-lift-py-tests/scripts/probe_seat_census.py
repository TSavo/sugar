"""Is the enrolled universe truncated, or was the counter wrong?

Diagnostic only. ``probe_runtime_selected`` reported ``SEATS 1316`` against a
1421-file pin. Either 105 files are being silently dropped -- in which case
every slice measurement is over a truncated universe -- or the counter was a
dict keyed by content CID and byte-identical files collapsed into one entry.

Counts the three quantities that tell those apart:

    paths walked          SourceTree(root).paths()
    path_source refusals  SourceUnavailable, by exception text
    DISTINCT content CIDs how many keys a cid-keyed dict would hold
"""

from __future__ import annotations

import sys
from collections import Counter, defaultdict


def main() -> int:
    from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
    from sugar_lift_python_source.source_oracle import SourceUnavailable, path_source
    from sugar_source_tree.tree import SourceTree

    corpus = authenticated_pandas_corpus()
    root = corpus.root
    print(f"CORPUS {corpus.distribution} {corpus.version} pinFileCount={corpus.file_count}")

    paths = list(SourceTree(root).paths())
    print(f"PATHS_WALKED {len(paths)}")

    refusals: Counter[str] = Counter()
    by_cid: dict[str, list[str]] = defaultdict(list)
    read = 0
    for path in paths:
        try:
            _source, _filename, source_cid = path_source(str(path))
        except SourceUnavailable as exc:
            refusals[type(exc).__name__] += 1
            print(f"  REFUSED {path}: {exc}")
            continue
        read += 1
        by_cid[source_cid].append(path.resolve().relative_to(root).as_posix())

    print(f"READ_OK {read}")
    print(f"REFUSED {sum(refusals.values())}")
    print(f"DISTINCT_CIDS {len(by_cid)}")
    print(f"COLLAPSED_BY_CID {read - len(by_cid)}")

    shared = {cid: seats for cid, seats in by_cid.items() if len(seats) > 1}
    print(f"\nCIDS_WITH_MULTIPLE_SEATS {len(shared)}")
    for cid, seats in sorted(shared.items(), key=lambda kv: -len(kv[1]))[:10]:
        print(f"  {len(seats):>4} seats share {cid[:24]}...")
        for seat in sorted(seats)[:6]:
            print(f"         {seat}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
