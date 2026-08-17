"""THE CONTENT-ADDRESS ARM for #7411's substitution sharing.

An empty node-ID diff does NOT prove the product's identity held: node IDs are
built from owner + coordinate + observed text, and a CID can move while every
one of them stays put. So this probe addresses the thing itself.

For each seat it drives construction through the SAME door the roll-call audit
uses -- ``open_source_file_for_construction`` + ``discharge``, which is what
makes ``.sugar()`` run over the whole tree -- carrying a reporter that records,
for every PRESENT construction, the pair

    <node kind>@<file>:<start>-<end>  ->  constructed_value_cid_v2(value)

``constructed_value_cid_v2`` is the repository's own Merkle content address for
a constructed semantic value (``binding_state.py:1710``): a pure function of
the value's semantic type, its authenticated scalar leaves, and its children's
V2 CIDs. It is exactly the identity that would move if a shared term hashed
differently from the duplicated one it replaced.

Emits one ``CID_ROW`` JSON line per seat, sorted, so two runs diff directly and
a killed run still yields a partial. Run BEFORE and AFTER on the same
``--start``/``--stride``; the diff must be empty IN BOTH DIRECTIONS.

usage:
  python probe_constructed_value_addresses.py --start 0 --stride 8 [--limit N]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


class _AddressingReporter:
    """A roll-call reporter that keeps the CONTENT ADDRESS of each answer.

    ``CollectingReporter`` drops the constructed value on the floor
    (``present_construction`` returns None), which is right for counting the
    minority and useless for addressing the product. This one keeps the pair
    and nothing else.

    A value whose address cannot be minted is recorded as
    ``unaddressable:<ExceptionType>`` rather than skipped: a silently dropped
    row would make two runs agree by omission, which is the failure mode this
    whole probe exists to rule out.
    """

    __slots__ = ("rows", "gaps")

    def __init__(self) -> None:
        self.rows: list[str] = []
        self.gaps: list[tuple] = []

    def register(self, node) -> None:
        return None

    def present_fact(self, node) -> None:
        return None

    def present_inert(self, node) -> None:
        return None

    def present_construction(self, node, value) -> None:
        from sugar_source_tree.binding_state import constructed_value_cid_v2

        try:
            span = node.span
            where = f"{node.kind}@{node.unit.filename}:{span.start}-{span.end}"
        except BaseException as error:  # noqa: BLE001 -- named, never silent
            where = f"{node.kind}@uncoordinated:{type(error).__name__}"
        try:
            address = constructed_value_cid_v2(value)
        except BaseException as error:  # noqa: BLE001 -- named, never silent
            address = f"unaddressable:{type(error).__name__}"
        self.rows.append(f"{where} -> {address}")

    def report_gap(self, node, panic) -> None:
        self.gaps.append((node, panic))


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
    args = parser.parse_args(argv)

    from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
    from sugar_lift_python_source.source_oracle import install_root_for
    from sugar_lift_py_tests.lift_rpc import (
        audit_frontier_construction_context,
        open_source_file_for_construction,
    )
    from sugar_source_tree.roll_call import discharge

    handle = authenticated_pandas_corpus()
    corpus = Path(handle.root)
    print(f"ENV OK ({handle.distribution} {handle.version})", flush=True)

    seats = _roster(corpus)[args.start :: args.stride]
    if args.limit is not None:
        seats = seats[: args.limit]
    print(
        f"CID_PLAN start={args.start} stride={args.stride} seats={len(seats)}",
        flush=True,
    )

    for index, seat in enumerate(seats):
        target = corpus.joinpath(*seat.split("/"))
        installed = install_root_for(str(target))
        locus_root = corpus if installed is None else Path(installed)
        reporter = _AddressingReporter()
        started = time.monotonic()
        outcome = "constructed"
        try:
            source_file = open_source_file_for_construction(
                target,
                root=corpus,
                reporter=reporter,
                construction_context=audit_frontier_construction_context(corpus),
                source_workspace_root=locus_root,
                populate_derived=True,
                distribution="pandas",
            )
            discharge(source_file)
        except BaseException as error:  # noqa: BLE001 -- named, never silent
            outcome = f"raised:{type(error).__name__}:{str(error)[:200]}"
            del error
        record = {
            "seat": seat,
            "outcome": outcome,
            "addressCount": len(reporter.rows),
            "gapCount": len(reporter.gaps),
            # SORTED SET, both directions diffable. Equal counts with a
            # non-empty diff is exactly the substitution this arm exists to
            # catch, and only the set shows it.
            "addresses": sorted(set(reporter.rows)),
            "elapsedMs": round((time.monotonic() - started) * 1000, 1),
        }
        print("CID_ROW " + json.dumps(record, sort_keys=True), flush=True)
        print(f"CID_PROGRESS {index + 1}/{len(seats)}", flush=True)
    print("CID_DONE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
