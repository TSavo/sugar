"""DIAGNOSTIC ONLY -- never a production path, never an acceptance instrument.

Answers three questions the sealed board's panics cannot answer about
themselves, because each lumps several distinct causes into one message:

1. ``CollectingReporter.present_construction`` on a constructed
   ``CallSiteSugar`` raises ONE ValueError for a NINE-term disjunction
   (``binding_state.py``). This records WHICH terms were true.

2. ``roll_call.discharge`` converts a ``RecursionError`` into a named gap
   without recording whether the recursion was monotone descent (genuine
   depth against an unset limit) or a CYCLE (the same construction coordinate
   re-entered). This records the frame histogram, the periodic unit, and --
   decisively -- whether any node coordinate REPEATS within the deep tail.

3. ``BuiltinSemanticCallable.python.super`` raises "missing __class__ cell or
   first formal receiver" for ``current_class is None or receiver is None``.
   This records which of the two was actually missing.

Emits one JSON line per finding (``DIAG ...``) so a killed run still yields
partial evidence. Reads the corpus through the SAME entrance the sealed board
reads (``measure_file_via_enumerate``) under the SAME prebuilt demand table --
a cheaper neighbour would diagnose a different population.

usage:
  python diagnose_frontier_misc.py --start 0 --stride 1 [--limit N]
        [--seats a.py,b.py] --out FILE
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

FINDINGS: list[dict] = []


def _emit(record: dict) -> None:
    FINDINGS.append(record)
    print("DIAG " + json.dumps(record, sort_keys=True, default=str), flush=True)


def _coord(node: object) -> str | None:
    """The node's construction coordinate, or None if it has no span."""
    try:
        span = node.line_col_span()  # type: ignore[attr-defined]
        unit = getattr(node, "unit", None)
        where = getattr(unit, "filename", None)
        return f"{where}:{span.start_line}:{span.start_col}-{span.end_line}:{span.end_col}"
    except Exception:
        return None


# --------------------------------------------------------------------------
# 1. present_construction: which of the nine disjuncts fired
# --------------------------------------------------------------------------
def _install_present_construction_probe(seat_ref: dict) -> None:
    from sugar_source_tree import binding_state
    from sugar_source_tree.nodes import Call, FunctionDef, AsyncFunctionDef

    cls = binding_state.ConstructionTestimonyReporterV1
    original = cls.present_construction

    def probed(self, node, value):  # noqa: ANN001
        from sugar_lift_py_tests.sugar.call_site_sugar import CallSiteSugar

        if (
            isinstance(node, Call)
            and isinstance(value, CallSiteSugar)
            and value.expected_definition_ref is not None
        ):
            from sugar_lift_py_tests.context_manager_resolution import (
                SourceFragmentCoordinateV1,
            )

            terms: dict[str, object] = {}
            definition = value.expected_definition_ref
            try:
                resolved = node.unit.source_function_definition_for_call(node)
                resolve_error = None
            except BaseException as exc:  # the resolver itself refused
                resolved = None
                resolve_error = f"{type(exc).__name__}: {exc}"
            span = node.line_col_span()
            call_occurrence = SourceFragmentCoordinateV1(
                node.unit.source_cid,
                span.start_line,
                span.start_col,
                span.end_line,
                span.end_col,
            )
            frame = value.source_call_frame

            def _term(name: str, fn) -> None:
                try:
                    terms[name] = bool(fn())
                except BaseException as exc:
                    terms[name] = f"RAISED {type(exc).__name__}: {exc}"

            _term(
                "definition-not-a-functiondef",
                lambda: not isinstance(definition, (FunctionDef, AsyncFunctionDef)),
            )
            _term(
                "definition-ref-not-materialized",
                lambda: definition.ref not in self._materialized_by_ref,
            )
            _term(
                "call-ref-not-materialized",
                lambda: node.ref not in self._materialized_by_ref,
            )
            _term(
                "definition-foreign-source-cid",
                lambda: definition.unit.source_cid != node.unit.source_cid,
            )
            _term(
                "resolved-not-a-functiondef",
                lambda: not isinstance(resolved, (FunctionDef, AsyncFunctionDef)),
            )
            _term(
                "resolved-seal-mismatch",
                lambda: resolved.fragment.seal() != definition.fragment.seal(),
            )
            _term(
                "call-occurrence-mismatch",
                lambda: value.call_occurrence != call_occurrence,
            )
            _term("frame-is-none", lambda: frame is None)
            _term("frame-owner-ref-mismatch", lambda: frame.owner.ref is not definition.ref)
            _term(
                "frame-definition-site-foreign",
                lambda: frame.definition_site.source_cid != node.unit.source_cid,
            )

            fired = [name for name, hit in terms.items() if hit is True]
            if fired:
                _emit(
                    {
                        "target": "present_construction",
                        "seat": seat_ref.get("seat"),
                        "coordinate": _coord(node),
                        "firedTerms": sorted(fired),
                        "allTerms": {k: str(v) for k, v in terms.items()},
                        "resolverError": resolve_error,
                        "resolvedIsNone": resolved is None,
                        "expectedDefinitionCoordinate": _coord(definition),
                        "valueType": type(value).__name__,
                    }
                )
        return original(self, node, value)

    cls.present_construction = probed

    # The CallSiteSugar identity guard is only ONE of the doors into
    # `_testimony_gap`. The others are the real canonicalization failures --
    # `node_construction_shape_cid` and `cid_of_json(_constructed_preimage())`
    # -- and they fire on node kinds the guard above never inspects
    # (`GuardedBindingRead` among them). Wrapping the shared door is what makes
    # the population complete instead of Call-shaped.
    original_gap = cls._testimony_gap

    def probed_gap(self, node, value, canonicalized, cause, shape=None):  # noqa: ANN001
        _emit(
            {
                "target": "present_construction-door",
                "seat": seat_ref.get("seat"),
                "coordinate": _coord(node),
                "nodeKind": type(node).__name__,
                "door": canonicalized,
                "valueType": type(value).__name__,
                "causeType": type(cause).__name__,
                "cause": str(cause)[:400],
            }
        )
        return original_gap(self, node, value, canonicalized, cause, shape)

    cls._testimony_gap = probed_gap


# --------------------------------------------------------------------------
# 2. roll_call.discharge: depth or cycle
# --------------------------------------------------------------------------
def _install_recursion_probe(seat_ref: dict) -> None:
    from sugar_source_tree import roll_call

    original = roll_call.discharge

    del original  # replaced outright, NOT wrapped: see below

    def probed(source_file):  # noqa: ANN001
        """The real discharge, verbatim, plus the traceback of any RecursionError.

        Deliberately NOT a wrapper that delegates. Delegating would attempt
        every root a SECOND time -- doubling the cost of exactly the deep
        constructions under investigation, and re-reporting each gap onto a
        roll that already carries it. This mirrors ``roll_call.discharge``
        exactly (same roots, same order, same typed gap, same ``kind``) so the
        measurement is the one the census reads.
        """
        from sugar_source_tree.panic import SugarNotWritten
        from sugar_source_tree.roll_call import MinorityReport

        for _ in source_file.nodes():
            pass
        for root_node in (source_file.root, *source_file.functions()):
            try:
                root_node.sugar()
            except SugarNotWritten:
                pass
            except RecursionError as exc:
                _emit(_recursion_finding(seat_ref, source_file, root_node, exc))
                lc = root_node.line_col_span()
                gap = SugarNotWritten(
                    owner="roll_call.discharge",
                    blame=root_node.fragment,
                    observed=(
                        f"RecursionError while constructing {root_node.kind} at "
                        f"{source_file.unit.filename}:{lc.start_line}:{lc.start_col}"
                    ),
                    requested=(
                        "bounded construction depth or a written cycle break for "
                        "this root's sugar graph"
                    ),
                    fix=(
                        "name the recursive edge (substitute/sugar loop) and bound "
                        "or split it; refuse specifically as ConstructionRecursionGap "
                        "— do not let RecursionError abort the roll as backend-defect"
                    ),
                )
                gap.kind = "ConstructionRecursionGap"
                source_file.reporter.report_gap(root_node, gap)
                continue
        return MinorityReport(reporter=source_file.reporter)

    roll_call.discharge = probed


def _recursion_finding(seat_ref, source_file, root_node, exc) -> dict:
    frames = traceback.extract_tb(exc.__traceback__)
    tail = frames[-400:]
    sig = [f"{Path(f.filename).name}:{f.name}:{f.lineno}" for f in tail]

    # Smallest period of the deep tail -- a cycle repeats a fixed frame unit.
    period = None
    for candidate in range(1, 41):
        window = sig[-candidate * 6 :] if len(sig) >= candidate * 6 else None
        if window is None:
            continue
        if all(
            window[i] == window[i % candidate] for i in range(len(window))
        ):
            period = candidate
            break

    # THE DECIDING TEST. Walk the live frames and collect the construction
    # coordinate each one is working on. A REPEATED coordinate is a cycle:
    # the same node re-entered its own construction. All-distinct coordinates
    # descending is genuine depth.
    coords: list[str] = []
    tb = exc.__traceback__
    while tb is not None:
        local = tb.tb_frame.f_locals
        for key in ("node", "self", "root_node", "call", "statement"):
            candidate = local.get(key)
            if candidate is None:
                continue
            where = _coord(candidate)
            if where is not None:
                coords.append(f"{key}@{where}")
                break
        tb = tb.tb_next
    deep = coords[-300:]
    seen: dict[str, int] = {}
    for where in deep:
        seen[where] = seen.get(where, 0) + 1
    repeated = sorted(
        ((count, where) for where, count in seen.items() if count > 1), reverse=True
    )[:10]

    histogram = sorted(
        (
            (sum(1 for s in sig if s.split(":")[1] == name), name)
            for name in {s.split(":")[1] for s in sig}
        ),
        reverse=True,
    )[:12]

    return {
        "target": "roll_call.discharge-recursion",
        "seat": seat_ref.get("seat"),
        "rootKind": root_node.kind,
        "rootCoordinate": _coord(root_node),
        "recursionLimit": sys.getrecursionlimit(),
        "framesTotal": len(frames),
        "framePeriod": period,
        "periodicUnit": sig[-period:] if period else None,
        "topFunctions": [{"count": c, "name": n} for c, n in histogram],
        "distinctCoordinatesInDeepTail": len(seen),
        "deepTailLength": len(deep),
        "repeatedCoordinates": [
            {"count": c, "coordinate": w} for c, w in repeated
        ],
        "verdictHint": (
            "CYCLE (a coordinate re-entered its own construction)"
            if repeated
            else "DEPTH (every frame a distinct coordinate)"
        ),
    }


# --------------------------------------------------------------------------
# 3. python.super: which of the two was missing
# --------------------------------------------------------------------------
def _install_super_probe(seat_ref: dict) -> None:
    from sugar_lift_py_tests.floor.builtin_semantic_callable import (
        BuiltinSemanticCallable,
    )

    original = BuiltinSemanticCallable.callable_application_with

    def probed(self, operation, ctx):  # noqa: ANN001
        if (
            self.operation == "python.super.construct"
            and not operation.arguments
            and not operation.keyword_names
            and ctx is not None
        ):
            current_class = ctx.temporal.value_if_bound("__class__")
            bound_names = {
                name: ctx.temporal.value_if_bound(name) is not None
                for name in ("self", "metacls", "cls")
            }
            receiver = any(bound_names.values())
            if current_class is None or not receiver:
                _emit(
                    {
                        "target": "python.super",
                        "seat": seat_ref.get("seat"),
                        "site": str(operation.site),
                        "classCellMissing": current_class is None,
                        "receiverMissing": not receiver,
                        "receiverNamesBound": bound_names,
                        "classCellType": type(current_class).__name__,
                    }
                )
        return original(self, operation, ctx)

    BuiltinSemanticCallable.callable_application_with = probed


def _roster(corpus_root: Path) -> list[str]:
    from sugar_source_tree.tree import SourceTree

    paths = list(SourceTree(corpus_root).paths())
    return sorted(path.resolve().relative_to(corpus_root).as_posix() for path in paths)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--stride", type=int, default=1)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--seats", default=None, help="comma-separated rel paths")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
    from sugar_lift_python_source.source_oracle import install_root_for
    from sugar_lift_py_tests.prebuilt_demand_table import (
        install_prebuilt_demand_table,
        mint_prebuilt_demand_table,
    )
    from sugar_lift_py_tests.lift_rpc import install_provisional_contract_refs

    import recensus_enumerate_consumer as consumer

    authenticated = authenticated_pandas_corpus()
    corpus = authenticated.root
    table = mint_prebuilt_demand_table(authenticated)
    contract_refs = install_prebuilt_demand_table(table, root=corpus)
    install_provisional_contract_refs(corpus, contract_refs)
    print(f"DIAG_DEMAND_TABLE contentCid={table.content_cid}", flush=True)

    if args.seats:
        seats = [s for s in args.seats.split(",") if s]
    else:
        seats = _roster(corpus)[args.start :: args.stride]
    if args.limit is not None:
        seats = seats[: args.limit]
    print(f"DIAG_PLAN seats={len(seats)}", flush=True)

    seat_ref: dict = {"seat": None}
    _install_present_construction_probe(seat_ref)
    _install_recursion_probe(seat_ref)
    _install_super_probe(seat_ref)

    for index, seat in enumerate(seats):
        seat_ref["seat"] = seat
        target = corpus.joinpath(*seat.split("/"))
        installed = install_root_for(str(target))
        locus_root = corpus if installed is None else Path(installed)
        started = time.monotonic()
        try:
            consumer.measure_file_via_enumerate(
                workspace_root=corpus,
                file_rel=seat,
                contract_refs=contract_refs,
                distribution="pandas",
                source_workspace_root=locus_root,
            )
        except BaseException as exc:
            _emit(
                {
                    "target": "harness",
                    "seat": seat,
                    "message": f"{type(exc).__name__}: {exc}",
                }
            )
        print(
            f"DIAG_PROGRESS {index + 1}/{len(seats)} findings={len(FINDINGS)} "
            f"elapsedMs={round((time.monotonic() - started) * 1000, 1)}",
            flush=True,
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps({"findings": FINDINGS}, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    print(f"DIAG_TOTAL findings={len(FINDINGS)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
