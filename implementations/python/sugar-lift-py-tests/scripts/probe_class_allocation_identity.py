"""What the identity guard is actually holding when a CLASS is the callee.

The frontier row at ``_config/config.py:131:14`` reads
``definition-not-a-functiondef``. That names the TYPE the guard rejected; it
does not say whether a constructor law was available. Those are different
facts and they ask for opposite repairs: an absent law wants a citation, an
available law wants the guard's type demand widened.

This probe wraps ``_source_call_identity_fault`` and prints, for every refusal
at a named seat, the definition's type, whether a source-visible constructor
frame exists for it, and that frame's parameter law. It changes nothing.

usage:
  python probe_class_allocation_identity.py _config/config.py [more...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def main(argv: list[str] | None = None) -> int:
    seats = list(argv if argv is not None else sys.argv[1:]) or ["_config/config.py"]

    from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
    from sugar_lift_python_source.source_oracle import install_root_for
    from sugar_lift_py_tests.prebuilt_demand_table import (
        install_prebuilt_demand_table,
        mint_prebuilt_demand_table,
    )
    from sugar_lift_py_tests.lift_rpc import install_provisional_contract_refs
    from sugar_source_tree.binding_state import ConstructionTestimonyReporterV1
    from sugar_source_tree.nodes import ClassDef

    import recensus_enumerate_consumer as consumer

    authenticated = authenticated_pandas_corpus()
    corpus = authenticated.root
    table = mint_prebuilt_demand_table(authenticated)
    contract_refs = install_prebuilt_demand_table(table, root=corpus)
    install_provisional_contract_refs(corpus, contract_refs)
    print(
        f"IDENT_DEMAND_TABLE contentCid={table.content_cid} rows={len(table.rows)}",
        flush=True,
    )

    original = ConstructionTestimonyReporterV1._source_call_identity_fault
    seen: set[str] = set()

    def _wrapped(self, node, value, definition, resolved_definition, call_occurrence, frame):
        fault = original(
            self, node, value, definition, resolved_definition, call_occurrence, frame
        )
        if fault is not None:
            try:
                span = node.line_col_span()
                record = {
                    "fault": fault,
                    "coordinate": f"{span.start_line}:{span.start_col}",
                    "definitionType": type(definition).__name__,
                    "definitionName": getattr(definition, "name", None),
                    "resolvedType": type(resolved_definition).__name__,
                    "frame": None,
                }
                if isinstance(definition, ClassDef):
                    record["classBases"] = [
                        getattr(base, "id", type(base).__name__)
                        for base in definition.bases
                    ]
                    record["bodyKinds"] = [
                        type(member).__name__ for member in definition.body
                    ]
                    record["hasOwnInit"] = any(
                        getattr(member, "name", None) == "__init__"
                        for member in definition.body
                    )
                    record["inheritsExceptionCtor"] = (
                        definition._inherits_default_exception_constructor()
                    )
                    ctor = definition.source_visible_constructor_frame()
                    record["ctorFrame"] = {
                        "parameters": list(ctor.parameters),
                        "parameterKinds": list(ctor.parameter_kinds),
                        "ownerType": type(ctor.owner).__name__,
                        "frameCid": ctor.frame_cid,
                    }
                if frame is not None:
                    record["frame"] = {
                        "parameters": list(frame.parameters),
                        "parameterKinds": list(frame.parameter_kinds),
                        "ownerType": type(frame.owner).__name__,
                        "ownerName": getattr(frame.owner, "name", None),
                    }
                line = json.dumps(record, sort_keys=True, default=str)
                if line not in seen:
                    seen.add(line)
                    print("IDENT_FAULT " + line, flush=True)
            except BaseException as error:  # noqa: BLE001 -- instrument, named
                if isinstance(error, (KeyboardInterrupt, SystemExit, GeneratorExit)):
                    raise
                print(
                    f"IDENT_INSTRUMENT_FAILURE {type(error).__name__}: {error}"[:500],
                    flush=True,
                )
        return fault

    ConstructionTestimonyReporterV1._source_call_identity_fault = _wrapped
    try:
        for seat in seats:
            target = corpus.joinpath(*seat.split("/"))
            if not target.is_file():
                print(f"IDENT_SEAT_ABSENT {seat} resolved={target}", flush=True)
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
                f"IDENT_SEAT {seat} terminalKind={row.get('terminalKind')} "
                f"panics={len(panics)}",
                flush=True,
            )
    finally:
        ConstructionTestimonyReporterV1._source_call_identity_fault = original
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
