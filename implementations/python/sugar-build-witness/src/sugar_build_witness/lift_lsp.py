# SPDX-License-Identifier: MIT OR Apache-2.0
from __future__ import annotations

import base64
import json
import os
import sys
from typing import Any, Optional

from sugar_lift_py_tests.canonicalizer import encode_jcs
from sugar_lift_py_tests.ir import (
    ContractDecl,
    declarations_to_value,
    eq,
    str_const,
)

from .witness import (
    BUILD_WITNESS_KIND,
    DEFAULT_MANIFEST,
    build_witness_memento,
    run_build_witness,
    witness_body,
    write_witness_package,
)

KIT_ID = "build-witness"
KIT_VERSION = "0.1.0"
KIT_DECLARATION_RPC_METHOD = "sugar.plugin.kit_declaration"
RESOLVE_WITNESS_RPC_METHOD = "sugar.plugin.resolve_witness"


def build_witness_proofir_provenance(bundle_cid: str, manifest_cid: str) -> dict:
    """Mirror of the rust `witness_package_contract_ir` stamp (sugar-lift-rust-
    cargo-test-witness, #3601): every recompute-discharged witness contract
    must carry a `proofirProvenance` so `verify_consistency`'s ambient-
    testimony gate classifies it instead of refusing with
    `provenance-kind-required`. `sugar_build_witness`'s ContractDecls never
    got this stamp when #3601 fixed the rust mirror -- a third, unstamped
    emission path (#3587 recurrence, recensus4)."""
    return {
        "kind": "proofir-provenance",
        "nodeClass": "WitnessPackage",
        "constructionSite": {
            "tool": "build-witness",
            "runtimeCid": manifest_cid,
        },
        "warrants": [
            {
                "kind": "Derived",
                "floorChain": ["build-witness", "rebuild-recompute"],
                "packageCid": bundle_cid,
            }
        ],
    }


def _send(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, separators=(",", ":"), ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _recv() -> Optional[dict]:
    line = sys.stdin.readline()
    if not line:
        return None
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


def handle_lift(msg_id: Any, params: dict) -> None:
    ws = str(params.get("workspace_root", "."))
    manifest_path = DEFAULT_MANIFEST
    if not os.path.isfile(os.path.join(ws, manifest_path)):
        _send(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "kind": "ir-document",
                    "ir": [],
                    "witness_mementos": [],
                    "implications": [],
                    "diagnostics": [],
                    "warnings": [{"message": "build-witness.json not found"}],
                },
            }
        )
        return
    try:
        w = run_build_witness(ws, manifest_path)
        package_dir = os.path.join(ws, ".sugar", "witnesses")
        write_witness_package(w, package_dir)
        decls = [
            ContractDecl(
                name=f"build-witness:{w.cid}::repo-script-cid-equals-distributed-script-cid",
                inv=eq(
                    str_const(w.repo_script_cid), str_const(w.distributed_script_cid)
                ),
            )
        ]
        for out in w.outputs:
            decls.append(
                ContractDecl(
                    name=(
                        f"build-witness:{w.cid}"
                        f"::distributed-output-cid-equals-rebuilt-output-cid::{out['distributed']}"
                    ),
                    inv=eq(
                        str_const(out["distributedCid"]), str_const(out["rebuiltCid"])
                    ),
                )
            )
        memento = build_witness_memento(w)
        ir = json.loads(encode_jcs(declarations_to_value(decls)))
        for member in ir:
            if member.get("kind") == "contract" and member.get("name", "").startswith(
                f"build-witness:{w.cid}"
            ):
                member["proofirProvenance"] = build_witness_proofir_provenance(
                    w.cid, w.manifest_cid
                )
        ir = ir + [memento]
        _send(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "kind": "ir-document",
                    "ir": ir,
                    "witness_mementos": [memento],
                    "implications": [],
                    "diagnostics": [],
                    "warnings": [],
                },
            }
        )
    except Exception as e:
        import traceback

        _send(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": -32603,
                    "message": str(e),
                    "data": traceback.format_exc(),
                },
            }
        )


def handle_resolve_witness(msg_id: Any, params: dict) -> None:
    try:
        memento = params.get("memento") or {}
        cid = memento.get("witness_cid") or params.get("witness_cid")
        if not cid:
            raise RuntimeError("resolve_witness requires a witness_cid")
        if memento.get("witness_kind") != BUILD_WITNESS_KIND:
            raise RuntimeError("not a build-witness memento")
        ws = params.get("workspace_root")
        if not ws:
            raise RuntimeError("build-witness resolve requires workspace_root")
        manifest_path = str(memento.get("manifest_path", DEFAULT_MANIFEST))
        w = run_build_witness(str(ws), manifest_path)
        body = witness_body(w)
        _send(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "witness_cid": cid,
                    "body_b64": base64.b64encode(body).decode("ascii"),
                    "resolved_by": "recompute",
                },
            }
        )
    except Exception as e:
        import traceback

        _send(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": -32603,
                    "message": str(e),
                    "data": traceback.format_exc(),
                },
            }
        )


def main() -> None:
    while True:
        msg = _recv()
        if msg is None:
            break
        method = msg.get("method")
        mid = msg.get("id")
        if method == "initialize":
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": mid,
                    "result": {
                        "name": "sugar-build-witness",
                        "version": KIT_VERSION,
                        "protocol_version": "sugar-lsp-shared/1",
                        "kit_id": KIT_ID,
                        "capabilities": {
                            "source_surfaces": ["build-witness"],
                            "entry_kinds": [],
                            "diagnostic_codes": [],
                            "status_kinds": ["prove"],
                        },
                    },
                }
            )
        elif method == KIT_DECLARATION_RPC_METHOD:
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": mid,
                    "result": {
                        "kit": {
                            "id": KIT_ID,
                            "language": "build",
                            "version": KIT_VERSION,
                        },
                        "rpc": {
                            "methods": [
                                {"name": "initialize", "required": True},
                                {"name": KIT_DECLARATION_RPC_METHOD, "required": True},
                                {"name": "lift", "required": True},
                                {"name": RESOLVE_WITNESS_RPC_METHOD, "required": False},
                                {"name": "shutdown", "required": False},
                            ]
                        },
                        "proofResolution": {"strategy": "pip"},
                        "effectKinds": [],
                        "effectLeaves": [],
                        "guardPredicates": [],
                        "controlCarriers": [],
                        "residueCategories": [],
                    },
                }
            )
        elif method == "lift":
            handle_lift(mid, msg.get("params", {}))
        elif method == RESOLVE_WITNESS_RPC_METHOD:
            handle_resolve_witness(mid, msg.get("params", {}))
        elif method == "shutdown":
            _send({"jsonrpc": "2.0", "id": mid, "result": None})
            break
        elif mid is not None:
            _send({"jsonrpc": "2.0", "id": mid, "result": None})


if __name__ == "__main__":
    main()
