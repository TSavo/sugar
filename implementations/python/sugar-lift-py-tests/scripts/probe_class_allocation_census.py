"""Census of CLASS-INSTANTIATION callees over a slice of the enrolled corpus.

STEP 0 CHECK 2 for the `OptionError(...)` seat: is class construction a
separate door with an in-population `__init__` behind it, or is every class
instantiation an off-population citation case?

The question is answered at the ONE place the answer exists --
``SourceUnit.source_allocation_definition_for_call`` -- by wrapping it and
re-deriving the module binding independently, then classifying the ClassDef's
constructor law. The wrapper NEVER changes what the method returns; it only
records. This is an instrument, not a repair, and is reverted before any
measurement baseline.

Classification, closed set, an unrecognised shape RAISES rather than being
bucketed as "other":

    own-init            the ClassDef body defines `__init__` -- IN POPULATION
    own-new             no `__init__`, but an authenticated `__new__` shape
    inherited-exception no `__init__`, authenticated BaseException ancestry
    inherited-object    no `__init__`, no exception ancestry -- zero formals

and orthogonally the admission gate actually consulted at the call site:

    gate=True/False     source_class_has_authenticated_default_attribute_behavior

usage:
  python probe_class_allocation_census.py --start 0 --stride 8 [--limit N]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _roster(corpus_root: Path) -> list[str]:
    from sugar_source_tree.tree import SourceTree

    paths = list(SourceTree(corpus_root).paths())
    return sorted(path.resolve().relative_to(corpus_root).as_posix() for path in paths)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--stride", type=int, default=8)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--seat", action="append", default=None)
    args = parser.parse_args(argv)

    from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
    from sugar_lift_python_source.source_oracle import install_root_for
    from sugar_lift_py_tests.prebuilt_demand_table import (
        install_prebuilt_demand_table,
        mint_prebuilt_demand_table,
    )
    from sugar_lift_py_tests.lift_rpc import install_provisional_contract_refs
    from sugar_source_tree.nodes import ClassDef, FunctionDef, Name, SourceUnit

    import recensus_enumerate_consumer as consumer

    authenticated = authenticated_pandas_corpus()
    corpus = authenticated.root
    table = mint_prebuilt_demand_table(authenticated)
    contract_refs = install_prebuilt_demand_table(table, root=corpus)
    install_provisional_contract_refs(corpus, contract_refs)
    print(
        f"CENSUS_DEMAND_TABLE contentCid={table.content_cid} rows={len(table.rows)}",
        flush=True,
    )

    roster = _roster(corpus)
    if args.seat:
        seats = []
        for seat in args.seat:
            if seat not in roster:
                # A seat spelling the roster does not use is NO measurement.
                print(f"CENSUS_SEAT_ABSENT {seat}", flush=True)
                return 2
            seats.append(seat)
    else:
        seats = roster[args.start :: args.stride]
        if args.limit is not None:
            seats = seats[: args.limit]
    print(f"CENSUS_CORPUS root={corpus} roster={len(roster)} slice={len(seats)}", flush=True)

    counts: Counter[str] = Counter()
    exemplars: dict[str, list[str]] = {}

    original = SourceUnit.source_allocation_definition_for_call

    def _classify(definition) -> str:
        has_init = any(
            isinstance(member, FunctionDef) and member.name == "__init__"
            for member in definition.body
        )
        if has_init:
            return "own-init"
        if definition._authenticated_new_constructor_shape() is not None:
            return "own-new"
        if definition._inherits_default_exception_constructor():
            return "inherited-exception"
        return "inherited-object"

    def _wrapped(self, call):
        result = original(self, call)
        try:
            if isinstance(call.func, Name) and self.typed_module is not None:
                bindings = (self.module_direct_bindings or {}).get(call.func.id, ())
                if len(bindings) == 1 and isinstance(bindings[0], ClassDef):
                    definition = bindings[0]
                    kind = _classify(definition)
                    if kind not in (
                        "own-init",
                        "own-new",
                        "inherited-exception",
                        "inherited-object",
                    ):
                        raise AssertionError(f"unrecognised constructor law: {kind}")
                    gate = (
                        SourceUnit.source_class_has_authenticated_default_attribute_behavior(
                            definition
                        )
                    )
                    admitted = result is not None
                    key = f"{kind}|gate={gate}|admitted={admitted}"
                    counts[key] += 1
                    span = call.line_col_span()
                    seat = f"{self.source_cid[:12]}:{span.start_line}:{span.start_col}:{call.func.id}"
                    exemplars.setdefault(key, [])
                    if len(exemplars[key]) < 6:
                        exemplars[key].append(seat)
        except BaseException as error:  # noqa: BLE001 -- an instrument, named loudly
            if isinstance(error, (KeyboardInterrupt, SystemExit, GeneratorExit)):
                raise
            counts[f"INSTRUMENT-FAILURE:{type(error).__name__}"] += 1
        return result

    SourceUnit.source_allocation_definition_for_call = _wrapped
    try:
        for index, seat in enumerate(seats):
            target = corpus.joinpath(*seat.split("/"))
            if not target.is_file():
                print(f"CENSUS_SEAT_ABSENT {seat} resolved={target}", flush=True)
                continue
            installed = install_root_for(str(target))
            locus_root = corpus if installed is None else Path(installed)
            try:
                consumer.measure_file_via_enumerate(
                    workspace_root=corpus,
                    file_rel=seat,
                    contract_refs=contract_refs,
                    distribution="pandas",
                    source_workspace_root=locus_root,
                )
            except BaseException as error:  # noqa: BLE001
                if isinstance(error, (KeyboardInterrupt, SystemExit, GeneratorExit)):
                    raise
                print(
                    f"CENSUS_SEAT_ERROR {seat} {type(error).__name__}: {error}"[:400],
                    flush=True,
                )
            if (index + 1) % 20 == 0:
                print(f"CENSUS_PROGRESS {index + 1}/{len(seats)}", flush=True)
    finally:
        SourceUnit.source_allocation_definition_for_call = original

    print("CENSUS_TOTAL " + json.dumps(dict(sorted(counts.items())), sort_keys=True), flush=True)
    for key in sorted(exemplars):
        print(f"CENSUS_EXEMPLAR {key} {exemplars[key]}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
