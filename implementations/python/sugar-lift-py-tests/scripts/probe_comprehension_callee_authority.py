"""Which authority goes silent for a callee named inside a comprehension.

The frontier row at ``_config/config.py:512:27`` reads
``resolved-not-a-functiondef``. That names the TYPE of the re-derived
definition; it does not say which of the two authorities produced the None.
There are exactly two, and they are consulted in order:

  1. the caller-unit resolver  ``node.unit.source_function_definition_for_call``
  2. the third authority       ``_callee_definition_by_name_in_its_unit``

This probe wraps ``_source_call_identity_fault``, RE-ASKS both authorities at
the refusing seat, and prints each one's answer next to what it was asked --
the enrollment decision, the lexically containing owner, the symtable
classification of the callee name in that owner, and the module-scope binding
table entries in both the caller's unit and the callee's unit. It returns the
original fault unchanged and mutates nothing.

usage:
  python probe_comprehension_callee_authority.py _config/config.py [more...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _describe(node: object) -> object:
    if node is None:
        return None
    unit = getattr(node, "unit", None)
    where = getattr(unit, "filename", None)
    try:
        span = node.line_col_span()
        at = f"{span.start_line}:{span.start_col}"
    except BaseException:  # noqa: BLE001 -- instrument, named below
        at = "<no-span>"
    return {
        "type": type(node).__name__,
        "name": getattr(node, "name", None),
        "file": where,
        "at": at,
    }


def _binding_table(unit: object, name: str) -> object:
    if unit is None or not name:
        return {"table": "<no-unit-or-name>"}
    table = getattr(unit, "module_direct_bindings", None)
    if table is None:
        return {"table": None}
    entries = table.get(name, ())
    return {
        "namesInTable": len(table),
        "entriesForName": len(entries),
        "entries": [_describe(entry) for entry in entries],
    }


def main(argv: list[str] | None = None) -> int:
    seats = list(argv if argv is not None else sys.argv[1:]) or ["_config/config.py"]

    from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
    from sugar_lift_python_source.source_oracle import install_root_for
    from sugar_lift_py_tests.prebuilt_demand_table import (
        install_prebuilt_demand_table,
        mint_prebuilt_demand_table,
    )
    from sugar_lift_py_tests.lift_rpc import install_provisional_contract_refs
    from sugar_source_tree.binding_state import (
        ConstructionTestimonyReporterV1,
        _callee_definition_by_name_in_its_unit,
    )

    import recensus_enumerate_consumer as consumer

    authenticated = authenticated_pandas_corpus()
    corpus = authenticated.root
    table = mint_prebuilt_demand_table(authenticated)
    contract_refs = install_prebuilt_demand_table(table, root=corpus)
    install_provisional_contract_refs(corpus, contract_refs)
    print(
        f"AUTH_DEMAND_TABLE contentCid={table.content_cid} rows={len(table.rows)}",
        flush=True,
    )

    original = ConstructionTestimonyReporterV1._source_call_identity_fault
    seen: set[str] = set()

    def _wrapped(
        self, node, value, definition, resolved_definition, call_occurrence, frame
    ):
        fault = original(
            self, node, value, definition, resolved_definition, call_occurrence, frame
        )
        if fault is not None:
            try:
                record = _report(node, definition, resolved_definition, fault)
                line = json.dumps(record, sort_keys=True, default=str)
                if line not in seen:
                    seen.add(line)
                    print("AUTH_FAULT " + line, flush=True)
            except BaseException as error:  # noqa: BLE001 -- instrument, named
                if isinstance(error, (KeyboardInterrupt, SystemExit, GeneratorExit)):
                    raise
                print(
                    f"AUTH_INSTRUMENT_FAILURE {type(error).__name__}: {error}"[:800],
                    flush=True,
                )
        return fault

    def _report(node, definition, resolved_definition, fault) -> dict:
        span = node.line_col_span()
        callee_name = getattr(getattr(node, "func", None), "id", None)
        caller_unit = node.unit
        record = {
            "fault": fault,
            "coordinate": f"{span.start_line}:{span.start_col}",
            "callerFile": getattr(caller_unit, "filename", None),
            "calleeName": callee_name,
            "definition": _describe(definition),
            "resolvedHandedToGuard": _describe(resolved_definition),
        }

        # ---- ARM 1: the caller-unit resolver, re-asked -----------------
        arm1: dict = {}
        try:
            arm1["answer"] = _describe(
                caller_unit.source_function_definition_for_call(node)
            )
        except BaseException as error:  # noqa: BLE001
            arm1["answer"] = f"<raised {type(error).__name__}: {error}>"
        try:
            enrollment = caller_unit.lexical_call_enrollment(node)
            arm1["enrollment"] = {
                "type": type(enrollment).__name__,
                "reason": getattr(enrollment, "reason", None),
            }
        except BaseException as error:  # noqa: BLE001
            arm1["enrollment"] = f"<raised {type(error).__name__}: {error}>"
        try:
            rows = caller_unit._seated_lexical_call_rows(node)
            arm1["lexicalRows"] = len(rows)
        except BaseException as error:  # noqa: BLE001
            arm1["lexicalRows"] = f"<raised {type(error).__name__}: {error}>"
        # the symtable arm the resolver falls through to
        try:
            containing = []
            for candidate in caller_unit.function_nodes or ():
                owner_span = candidate.line_col_span()
                if (
                    (owner_span.start_line, owner_span.start_col)
                    <= (span.start_line, span.start_col)
                    <= (owner_span.end_line, owner_span.end_col)
                ):
                    containing.append(candidate)
            arm1["containingOwners"] = [_describe(item) for item in containing]
            if containing:
                owner = max(
                    containing, key=lambda item: item.line_col_span().start_line
                )
                arm1["chosenOwner"] = _describe(owner)
                symtable = caller_unit.function_symtable(
                    owner.name, owner.line_col_span().start_line
                )
                try:
                    symbol = symtable.lookup(callee_name)
                except KeyError:
                    arm1["symbol"] = "<KeyError: name not in owner symtable>"
                else:
                    arm1["symbol"] = {
                        "isParameter": symbol.is_parameter(),
                        "isLocal": symbol.is_local(),
                        "isFree": symbol.is_free(),
                        "isNonlocal": symbol.is_nonlocal(),
                        "isGlobal": symbol.is_global(),
                    }
                arm1["symtableChildren"] = [
                    child.get_name() for child in symtable.get_children()
                ]
        except BaseException as error:  # noqa: BLE001
            arm1["symtableArm"] = f"<raised {type(error).__name__}: {error}>"
        arm1["callerBindingTable"] = _binding_table(caller_unit, callee_name or "")
        record["arm1_callerUnitResolver"] = arm1

        # ---- ARM 2: the third authority, re-asked ----------------------
        arm2: dict = {}
        try:
            arm2["answer"] = _describe(
                _callee_definition_by_name_in_its_unit(definition)
            )
        except BaseException as error:  # noqa: BLE001
            arm2["answer"] = f"<raised {type(error).__name__}: {error}>"
        definition_unit = getattr(definition, "unit", None)
        arm2["definitionFile"] = getattr(definition_unit, "filename", None)
        arm2["definitionName"] = getattr(definition, "name", None)
        arm2["calleeBindingTable"] = _binding_table(
            definition_unit, getattr(definition, "name", None) or ""
        )
        record["arm2_thirdAuthority"] = arm2
        return record

    ConstructionTestimonyReporterV1._source_call_identity_fault = _wrapped
    try:
        for seat in seats:
            target = corpus.joinpath(*seat.split("/"))
            if not target.is_file():
                print(f"AUTH_SEAT_ABSENT {seat} resolved={target}", flush=True)
                continue
            installed = install_root_for(str(target))
            locus_root = corpus if installed is None else Path(installed)
            row = consumer.measure_file_via_enumerate(
                workspace_root=corpus,
                file_rel=seat,
                contract_refs=contract_refs,
                distribution="pandas",
                source_workspace_root=locus_root,
            )
            panics = row.get("constructionPanics") or []
            print(
                f"AUTH_SEAT {seat} terminalKind={row.get('terminalKind')} "
                f"panics={len(panics)}",
                flush=True,
            )
    finally:
        ConstructionTestimonyReporterV1._source_call_identity_fault = original
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
