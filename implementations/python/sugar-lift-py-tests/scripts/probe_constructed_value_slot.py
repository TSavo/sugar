"""FULL constructed-value refusal text for named seats.

The frontier profile truncates ``observed`` at 200 chars, which is exactly
where ``constructed_value_cid_v2``'s ``[refused at <slot path> of <type>]``
suffix lives -- so the profile can say a value did not canonicalize but never
which SLOT refused. This probe measures the same seats through the same census
entrance under the same prebuilt demand table and prints the whole string.

usage:
  python probe_constructed_value_slot.py pandas/_config/config.py [more...]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def main(argv: list[str] | None = None) -> int:
    seats = list(argv if argv is not None else sys.argv[1:])
    if not seats:
        seats = ["pandas/_config/config.py"]

    from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
    from sugar_lift_python_source.source_oracle import install_root_for

    import recensus_enumerate_consumer as consumer

    # SHARD CONDITIONS -- the same prebuilt demand table the profile installs.
    # Measuring against provisional per-file demands would report a different
    # population and could not be compared with the frontier rows at all.
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
        f"PROBE_DEMAND_TABLE contentCid={table.content_cid} rows={len(table.rows)}",
        flush=True,
    )

    print(f"PROBE_CORPUS root={corpus} files={authenticated.file_count}", flush=True)

    for seat in seats:
        target = corpus.joinpath(*seat.split("/"))
        # A seat spelling the roster does not use is not a clean measurement,
        # it is no measurement. Say so rather than reporting `panics=0`.
        if not target.is_file():
            print(f"PROBE_SEAT_ABSENT {seat} resolved={target}", flush=True)
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
            f"PROBE_SEAT {seat} terminalKind={row.get('terminalKind')} "
            f"panics={len(panics)} rowKeys={sorted(row)} "
            f"instrumentFailure={str((row.get('instrumentFailure') or {}).get('message') or '')[:400]}",
            flush=True,
        )
        for panic in panics:
            if not isinstance(panic, dict):
                continue
            print(
                "PROBE_PANIC "
                + json.dumps(
                    {
                        "seat": seat,
                        "owner": panic.get("owner"),
                        "coordinate": panic.get("coordinate"),
                        # FULL text. No truncation -- that is the point.
                        "observed": panic.get("observed"),
                        "requested": panic.get("requested"),
                        "fix": panic.get("fix"),
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
