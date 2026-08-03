# SPDX-License-Identifier: MIT OR Apache-2.0
from __future__ import annotations

import base64
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from sugar_lift_py_tests.canonicalizer import blake3_512_of, encode_jcs
from sugar_lift_py_tests.ir import (
    ContractDecl,
    declarations_to_value,
    eq,
    str_const,
)

from .witness import (
    BUILD_WITNESS_KIND,
    DEFAULT_MANIFEST,
    BuildWitness,
    build_witness_memento,
    load_build_witness_plan,
    run_build_witness,
    witness_body,
    write_witness_package,
)

KIT_ID = "build-witness"
KIT_VERSION = "0.1.0"
KIT_DECLARATION_RPC_METHOD = "sugar.plugin.kit_declaration"
RESOLVE_WITNESS_RPC_METHOD = "sugar.plugin.resolve_witness"
ENUMERATE_RPC_METHOD = "sugar.enumerate"


@dataclass(frozen=True)
class _PopulationContext:
    root: Path
    anchor: str
    sealed_cids: tuple[tuple[str, str], ...]

    def cid_for(self, rel_path: str) -> str | None:
        return dict(self.sealed_cids).get(rel_path)


_POPULATION_CONTEXTS: dict[str, _PopulationContext] = {}


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


def build_witness_evidence(witness: BuildWitness) -> dict[str, Any]:
    """Commit a contract to the package Rust must resolve and recompute."""
    proof_data = json.dumps(
        {
            "kind": "witness-package",
            "packageCid": witness.cid,
            "testFiles": [],
            "codeFiles": [],
            "count": 1,
            "passed": 1 if witness.outcome == "passed" else 0,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return {
        "kind": "evidence",
        "proofType": "custom",
        "certificate": {
            "tool": BUILD_WITNESS_KIND,
            "version": witness.toolchain_id,
            "formulaHash": witness.cid,
            "proofData": proof_data,
        },
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


def _build_ir_document(ws: str, manifest_path: str = DEFAULT_MANIFEST) -> dict:
    """The one build-witness construction, shared by legacy proof and adapter."""
    if not os.path.isfile(os.path.join(ws, manifest_path)):
        return {
            "kind": "ir-document",
            "ir": [],
            "witness_mementos": [],
            "implications": [],
            "diagnostics": [],
            "warnings": [{"message": "build-witness.json not found"}],
        }
    w = run_build_witness(ws, manifest_path)
    package_dir = os.path.join(ws, ".sugar", "witnesses")
    write_witness_package(w, package_dir)
    decls = [
        ContractDecl(
            name=f"build-witness:{w.cid}::repo-script-cid-equals-distributed-script-cid",
            inv=eq(str_const(w.repo_script_cid), str_const(w.distributed_script_cid)),
        )
    ]
    for out in w.outputs:
        decls.append(
            ContractDecl(
                name=(
                    f"build-witness:{w.cid}"
                    f"::distributed-output-cid-equals-rebuilt-output-cid::{out['distributed']}"
                ),
                inv=eq(str_const(out["distributedCid"]), str_const(out["rebuiltCid"])),
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
            member["evidence"] = build_witness_evidence(w)
    ir = ir + [memento]
    return {
        "kind": "ir-document",
        "ir": ir,
        "witness_mementos": [memento],
        "implications": [],
        "diagnostics": [],
        "warnings": [],
    }


def handle_lift(msg_id: Any, params: dict) -> None:
    ws = str(params.get("workspace_root", "."))
    try:
        _send(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": _build_ir_document(ws),
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


def _file_memento(rel_path: str, source_cid: str | None = None) -> dict[str, Any]:
    return {
        "kind": "source-memento",
        "file": rel_path,
        "function_name": "",
        "span": None,
        "param_names": [],
        "source_cid": source_cid,
        "template_cid": None,
    }


def _enumerate_result(
    msg_id: Any, nodes: list[dict[str, Any]], gaps: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "result": {"nodes": nodes, "gaps": gaps},
    }


def _enumerate_error(msg_id: Any, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": msg_id,
        "error": {"code": -32602, "message": message},
    }


def _sealed_input_cid(root: Path, rel_path: str) -> str:
    full_path = (root / rel_path).resolve(strict=True)
    try:
        full_path.relative_to(root)
    except ValueError as exc:
        raise ValueError(
            f"build-witness input '{rel_path}' escapes workspace root '{root}'"
        ) from exc
    if not full_path.is_file():
        raise FileNotFoundError(
            f"build-witness input '{rel_path}' is not a file required by the manifest"
        )
    return blake3_512_of(full_path.read_bytes())


def _prepare_population(root: Path) -> tuple[_PopulationContext | None, list[dict]]:
    manifest_file = root / DEFAULT_MANIFEST
    if not manifest_file.is_file():
        _POPULATION_CONTEXTS.pop(str(root), None)
        return None, []

    plan = load_build_witness_plan(str(root), DEFAULT_MANIFEST)
    sealed: list[tuple[str, str]] = []
    gaps: list[dict] = []
    for rel_path in plan.authenticated_input_paths:
        try:
            cid = _sealed_input_cid(root, rel_path)
        except (OSError, ValueError) as exc:
            gaps.append({"memento": _file_memento(rel_path), "reason": str(exc)})
            continue
        sealed.append((rel_path, cid))

    if gaps:
        _POPULATION_CONTEXTS.pop(str(root), None)
        return None, gaps
    context = _PopulationContext(
        root=root,
        anchor=plan.manifest_path,
        sealed_cids=tuple(sealed),
    )
    _POPULATION_CONTEXTS[str(root)] = context
    return context, []


def _population_drift(context: _PopulationContext) -> str | None:
    for rel_path, sealed_cid in context.sealed_cids:
        try:
            observed_cid = _sealed_input_cid(context.root, rel_path)
        except (OSError, ValueError) as exc:
            return (
                f"build-witness input '{rel_path}' cannot be authenticated against "
                f"the sealed source_files census: {exc}"
            )
        if observed_cid != sealed_cid:
            return (
                f"build-witness input '{rel_path}' changed since the sealed "
                f"source_files census: {sealed_cid} != {observed_cid}"
            )
    return None


def handle_enumerate(msg_id: Any, params: dict) -> None:
    """Project one whole-workspace witness at its sealed manifest anchor."""
    level = str(params.get("level", ""))
    root = Path(str(params.get("workspace_root", "."))).resolve()
    at = params.get("at") if isinstance(params.get("at"), dict) else None

    try:
        if level == "parameter-contract-link-units":
            _send({"jsonrpc": "2.0", "id": msg_id, "result": {"rows": []}})
            return

        if level == "source_files":
            context, gaps = _prepare_population(root)
            if context is None:
                _send(_enumerate_result(msg_id, [], gaps))
                return
            seek = bool(params.get("seek", False))
            nodes = [
                {
                    "memento": _file_memento(rel_path, cid),
                    "audit": None,
                    "payload": None,
                }
                for rel_path, cid in context.sealed_cids
                if not seek
                or at is None
                or (
                    at.get("file") == rel_path
                    and (
                        not (at.get("source_cid") or at.get("sourceCid"))
                        or (at.get("source_cid") or at.get("sourceCid")) == cid
                    )
                )
            ]
            _send(_enumerate_result(msg_id, nodes, []))
            return

        if level == "universe":
            rel_path = at.get("file") if at else None
            if not isinstance(rel_path, str) or not rel_path:
                _send(
                    _enumerate_result(
                        msg_id,
                        [],
                        [
                            {
                                "memento": at,
                                "reason": (
                                    "sugar.enumerate level='universe' requires at.file"
                                ),
                            }
                        ],
                    )
                )
                return
            context = _POPULATION_CONTEXTS.get(str(root))
            if context is None:
                _send(
                    _enumerate_result(
                        msg_id,
                        [],
                        [
                            {
                                "memento": at,
                                "reason": (
                                    "build-witness universe requires a prepared "
                                    "source_files census for this workspace"
                                ),
                            }
                        ],
                    )
                )
                return
            sealed_cid = context.cid_for(rel_path)
            if sealed_cid is None:
                _send(
                    _enumerate_result(
                        msg_id,
                        [],
                        [
                            {
                                "memento": at,
                                "reason": (
                                    f"build-witness input '{rel_path}' is not a member "
                                    "of the sealed source_files census"
                                ),
                            }
                        ],
                    )
                )
                return
            requested_cid = at.get("source_cid") or at.get("sourceCid")
            if requested_cid and requested_cid != sealed_cid:
                _send(
                    _enumerate_result(
                        msg_id,
                        [],
                        [
                            {
                                "memento": at,
                                "reason": (
                                    f"build-witness input '{rel_path}' does not match "
                                    "the sealed source_files identity"
                                ),
                            }
                        ],
                    )
                )
                return
            drift = _population_drift(context)
            if drift is not None:
                _send(
                    _enumerate_result(
                        msg_id,
                        [],
                        [{"memento": at, "reason": drift}],
                    )
                )
                return
            if rel_path != context.anchor:
                _send(_enumerate_result(msg_id, [], []))
                return

            document = _build_ir_document(str(root))
            drift = _population_drift(context)
            if drift is not None:
                _send(
                    _enumerate_result(
                        msg_id,
                        [],
                        [{"memento": at, "reason": drift}],
                    )
                )
                return
            memento = _file_memento(context.anchor, sealed_cid)
            nodes = [
                {"memento": memento, "audit": row, "payload": None}
                for row in document["ir"]
            ]
            _send(_enumerate_result(msg_id, nodes, []))
            return

        _send(
            _enumerate_error(
                msg_id,
                f"sugar.enumerate: level {level!r} is not served by surface "
                f"'{KIT_ID}'; answering an unowned level with an empty census "
                "would be a false zero",
            )
        )
    except Exception as exc:
        import traceback

        _send(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "error": {
                    "code": -32603,
                    "message": str(exc),
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
                                {"name": ENUMERATE_RPC_METHOD, "required": True},
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
        elif method == ENUMERATE_RPC_METHOD:
            handle_enumerate(mid, msg.get("params", {}))
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
