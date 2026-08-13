"""Per-file category profile over a deterministic slice of the enrolled corpus.

Measures each seat through the ONE census entrance
(``recensus_enumerate_consumer.measure_file_via_enumerate``) and reports the
three-way partition the shard partials report:

    panics / completed / instrument-failures

The slice is ``sorted(roster)[start::stride]`` -- a reproducible stand-in for a
shard bin, NOT the LPT bin itself (the LPT plan is derived by the driver from a
demand table this script does not build). Both arms of a before/after
comparison must use the same ``start``/``stride`` for the comparison to mean
anything.

Emits one JSON line per file to stdout (``PROFILE_ROW ...``) so a killed run
still yields a partial profile, and a final ``PROFILE_TOTAL`` line.

usage:
  python profile_enumerate_slice.py --start 0 --stride 8 [--limit N] --out FILE
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _roster(corpus_root: Path) -> list[str]:
    from sugar_source_tree.tree import SourceTree

    paths = list(SourceTree(corpus_root).paths())
    return sorted(
        path.resolve().relative_to(corpus_root).as_posix() for path in paths
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--stride", type=int, default=8)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
    from sugar_lift_python_source.source_oracle import install_root_for

    import recensus_enumerate_consumer as consumer

    # SHARD CONDITIONS, not a cheaper neighbour. A shard measures every file
    # against the ONE prebuilt demand table; `contract_refs=None` measures
    # against provisional per-file demands instead and reports a different
    # (larger) panic population. Deriving the table here is what makes this
    # profile comparable to the shard partials at all.
    from sugar_lift_py_tests.prebuilt_demand_table import (
        install_prebuilt_demand_table,
        mint_prebuilt_demand_table,
    )
    from sugar_lift_py_tests.lift_rpc import install_provisional_contract_refs

    authenticated = authenticated_pandas_corpus()
    corpus = authenticated.root
    table = mint_prebuilt_demand_table(authenticated)
    contract_refs = install_prebuilt_demand_table(table, root=corpus)
    install_provisional_contract_refs(corpus, contract_refs)
    print(
        f"PROFILE_DEMAND_TABLE contentCid={table.content_cid} rows={len(table.rows)}",
        flush=True,
    )

    seats = _roster(corpus)[args.start :: args.stride]
    if args.limit is not None:
        seats = seats[: args.limit]
    # State the bound where the reader meets the rows it produced. A profile
    # that does not say which ceiling was in force cannot be compared with
    # another profile at all.
    from sugar_lift_py_tests.measurement_ceiling import ceiling_seconds

    print(
        f"PROFILE_PLAN start={args.start} stride={args.stride} seats={len(seats)} "
        f"measurementCeilingSeconds={ceiling_seconds()}",
        flush=True,
    )
    # REFUSE AN ABSENT SEAT BY NAME. A slice keyed on a wrong spelling
    # silently measures nobody and reports panics=0 -- a non-measurement that
    # reads exactly like a clean corpus.
    for seat in seats:
        if not corpus.joinpath(*seat.split("/")).is_file():
            raise SystemExit(f"PROFILE_REFUSED absent seat: {seat!r} under {corpus}")
    print("PROFILE_SEATS " + json.dumps(seats), flush=True)

    rows: list[dict] = []
    counts = {
        "construction-panic": 0,
        "constructed": 0,
        "measurement-exhausted": 0,
        "instrument-failure": 0,
    }
    for index, seat in enumerate(seats):
        target = corpus.joinpath(*seat.split("/"))
        installed = install_root_for(str(target))
        locus_root = corpus if installed is None else Path(installed)
        started = time.monotonic()
        try:
            row = consumer.measure_file_via_enumerate(
                workspace_root=corpus,
                file_rel=seat,
                contract_refs=contract_refs,
                distribution="pandas",
                source_workspace_root=locus_root,
            )
        except BaseException as exc:  # the harness itself died on this seat
            row = {
                "terminalKind": "instrument-failure",
                "instrumentFailure": {
                    "message": f"{type(exc).__name__}: {exc}",
                    "traceback": traceback.format_exc()[-2000:],
                },
            }
        kind = str(row.get("terminalKind") or "instrument-failure")
        if kind not in counts:
            counts[kind] = 0
        counts[kind] += 1
        record = {
            "seat": seat,
            "terminalKind": kind,
            # NODE IDS, both directions. One id per countable construction
            # panic: the roll-call identity the audit keys on (owner +
            # coordinate + observed construct). Equal counts hide substitution,
            # so the diff is over these sets, not over len().
            "nodeIds": sorted(
                "{seat}|{owner}|{coordinate}|{observed}".format(
                    seat=seat,
                    owner=panic.get("owner"),
                    coordinate=panic.get("coordinate"),
                    observed=str(panic.get("observed"))[:200],
                )
                for panic in (row.get("constructionPanics") or [])
                if isinstance(panic, dict)
            ),
            "panicCount": len(row.get("constructionPanics") or []),
            "measurementExhaustion": row.get("measurementExhaustion"),
            "instrumentFailure": (
                str((row.get("instrumentFailure") or {}).get("message") or "")[:400]
                or None
            ),
            "elapsedMs": round((time.monotonic() - started) * 1000, 1),
        }
        rows.append(record)
        print("PROFILE_ROW " + json.dumps(record, sort_keys=True), flush=True)
        print(
            f"PROFILE_PROGRESS {index + 1}/{len(seats)} {json.dumps(counts, sort_keys=True)}",
            flush=True,
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(
            {"start": args.start, "stride": args.stride, "counts": counts, "rows": rows},
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    print("PROFILE_TOTAL " + json.dumps(counts, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
