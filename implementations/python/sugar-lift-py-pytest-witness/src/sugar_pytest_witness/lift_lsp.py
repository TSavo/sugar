# SPDX-License-Identifier: MIT OR Apache-2.0
#
# Witness lift surface (sugar-lift/1 NDJSON). At LIFT time this is the
# PRODUCER: it runs each test under pytest and emits a ContractDecl carrying the
# witnessed run as a `custom` EvidenceTerm. `mint` serializes it into a real
# signed .proof; `prove` then discharges it BY RECOMPUTE (the verifier's custom-
# evidence arm spawns the discharge command).
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, List, Optional

from sugar_lift_py_tests.ir import (
    ContractDecl,
    EvidenceCertificate,
    EvidenceTerm,
    atomic,
    declarations_to_value,
)
from sugar_lift_py_tests.canonicalizer import encode_jcs, blake3_512_of
from sugar_lift_py_tests.filename import cid_filename

import base64

from .witness import (
    Witness,
    run_and_witness,
    run_file_witnesses,
    witness_memento,
    witness_body,
    write_witness_bundle,
    build_suite_bundle,
    witness_package_memento,
    runtime_cid,
)

KIT_ID = "python-pytest-witness"
KIT_VERSION = "0.1.0"
KIT_DECLARATION_RPC_METHOD = "sugar.plugin.kit_declaration"
RESOLVE_WITNESS_RPC_METHOD = "sugar.plugin.resolve_witness"
COMPONENT_PLAN_RPC_METHOD = "sugar.component.plan"
COMPONENT_PROTOCOL_VERSION = "sugar-component/1"
LIFT_PROTOCOL_VERSION = "pep/1.7.0"
PYTEST_WITNESS_SURFACE = "python-pytest-witness"
PYTEST_WITNESS_LIFT_NAME = "pytest-witness-lift"


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


def _iter_python_files(workspace_root: str, source_paths: List[str]) -> List[str]:
    out: List[str] = []
    for sp in source_paths:
        base = sp if os.path.isabs(sp) else os.path.join(workspace_root, sp)
        if os.path.isfile(base) and base.endswith(".py"):
            out.append(base)
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [
                d for d in dirnames if d not in {".git", "__pycache__", ".pytest_cache"}
            ]
            for fn in filenames:
                if fn.endswith(".py"):
                    out.append(os.path.join(dirpath, fn))
    return sorted(set(out))


def _items_from_params(params: dict) -> List[dict]:
    out: List[dict] = []
    for evidence_key in (
        "project_forensics",
        "projectForensics",
        "workspace_evidence",
        "workspaceEvidence",
    ):
        evidence = params.get(evidence_key)
        if not isinstance(evidence, dict):
            continue
        items = evidence.get("items")
        if isinstance(items, list):
            out.extend(item for item in items if isinstance(item, dict))
    return out


def _is_python_test_path(path: Any) -> bool:
    text = str(path)
    return text.endswith(".py") and os.path.basename(text).startswith("test_")


def _item_is_python_test(item: dict) -> bool:
    language = item.get("language_hint", item.get("languageHint"))
    return (
        language == "python" or str(item.get("path", "")).endswith(".py")
    ) and _is_python_test_path(item.get("path", ""))


def _first_pytest_claim(params: dict, workspace_root: str) -> Optional[str]:
    for item in _items_from_params(params):
        if not _item_is_python_test(item):
            continue
        item_id = item.get("id")
        if isinstance(item_id, str) and item_id:
            return item_id
        path = item.get("path")
        if isinstance(path, str) and path:
            return f"file:{path}"

    root = Path(workspace_root)
    if root.is_dir():
        for path in sorted(root.rglob("test_*.py")):
            try:
                relative = path.relative_to(root)
            except ValueError:
                relative = path
            return f"file:{relative.as_posix()}"
    return None


def _runtime_pythonpath() -> str:
    here = Path(__file__).resolve()
    witness_src = here.parents[1]
    python_impl = here.parents[3]
    py_tests_src = python_impl / "sugar-lift-py-tests" / "src"
    py_source_src = python_impl / "sugar-lift-python-source" / "src"
    paths = [str(witness_src), str(py_tests_src), str(py_source_src)]
    existing = os.environ.get("PYTHONPATH")
    if existing:
        paths.append(existing)
    return os.pathsep.join(paths)


def _runtime_module_command(module: str) -> List[str]:
    return [
        "/usr/bin/env",
        f"PYTHONPATH={_runtime_pythonpath()}",
        sys.executable,
        "-m",
        module,
    ]


def component_plan_result(params: dict) -> dict:
    workspace_root = str(params.get("workspace_root", "."))
    claim_item = _first_pytest_claim(params, workspace_root)
    if claim_item is None:
        return {
            "decision": "decline",
            "reason": "no Python pytest test evidence",
        }

    lift_command = _runtime_module_command("sugar_pytest_witness.lift_lsp")
    discharge_command = _runtime_module_command("sugar_pytest_witness.discharge_cli")
    return {
        "decision": "claim",
        "claims": [
            {
                "item": claim_item,
                "role": "witness-producer",
                "surface": PYTEST_WITNESS_SURFACE,
            }
        ],
        "plugins": [
            {
                "name": PYTEST_WITNESS_LIFT_NAME,
                "kind": "lift",
                "surface": PYTEST_WITNESS_SURFACE,
            }
        ],
        "lift_manifests": [
            {
                "surface": PYTEST_WITNESS_SURFACE,
                "name": PYTEST_WITNESS_LIFT_NAME,
                "version": KIT_VERSION,
                "protocol_version": LIFT_PROTOCOL_VERSION,
                "kind": "lift",
                "command": lift_command,
                "discharge_command": discharge_command,
                "witness_tool": "pytest",
                "resolve_witness_command": lift_command,
                "resolve_witness_method": RESOLVE_WITNESS_RPC_METHOD,
                "working_dir": ".",
            }
        ],
        "diagnostics": [],
    }


def handle_lift(msg_id: Any, params: dict) -> None:
    ws = str(params.get("workspace_root", "."))
    sps = params.get("source_paths", ["."])
    try:
        pyfiles = _iter_python_files(ws, sps)
        rels = [os.path.relpath(p, ws) for p in pyfiles]
        code_rels = [r for r in rels if not os.path.basename(r).startswith("test_")]
        test_rels = [r for r in rels if os.path.basename(r).startswith("test_")]
        decls: List[ContractDecl] = []
        mementos: List[dict] = []
        if test_rels:
            # PER-TEST run, but ONE proof member. The whole suite is a WITNESS
            # PACKAGE: a content-addressed `.witness` bundle of per-test bodies,
            # cid = blake3(bundle). The proof carries ONE WitnessPackageMemento
            # (64 bytes) + ONE contract whose evidence pins the package cid -- not
            # N mementos. The verifier asks the oracle to discharge by re-running
            # the suite and reproducing the package cid (`discharge_bundle`).
            bundle_bytes, bundle_cid, witnesses = build_suite_bundle(
                ws, test_rels, code_rels
            )
            passed = sum(1 for w in witnesses if w.outcome == "passed")
            try:
                bundle_dir = os.path.join(ws, ".sugar", "witnesses")
                os.makedirs(bundle_dir, exist_ok=True)
                with open(
                    os.path.join(bundle_dir, cid_filename(bundle_cid, ".witness")),
                    "wb",
                ) as f:
                    f.write(bundle_bytes)
            except OSError:
                pass  # the package is audit material; never fail the lift on a write error
            proof_data = json.dumps(
                {
                    "kind": "witness-package",
                    "packageCid": bundle_cid,
                    "testFiles": sorted(test_rels),
                    "codeFiles": sorted(code_rels),
                    "count": len(witnesses),
                    "passed": passed,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            cert = EvidenceCertificate(
                tool="pytest",
                version=runtime_cid(),
                formula_hash=bundle_cid,
                proof_data=proof_data,
            )
            ev = EvidenceTerm(proof_type="custom", certificate=cert)
            decls.append(
                ContractDecl(
                    name=f"witness-package:{bundle_cid}",
                    inv=atomic("witnessed", []),
                    evidence=ev,
                )
            )
            mementos.append(
                witness_package_memento(
                    bundle_cid, test_rels, code_rels, len(witnesses), passed
                )
            )
        ir = json.loads(encode_jcs(declarations_to_value(decls))) if decls else []
        # The signed WitnessMementos flow as `ir` members (kind "witness-memento"):
        # mint envelopes each into the .proof via its per-kind dispatch, so the
        # .proof carries the signed pointer the rust verifier enumerates. (Also
        # surfaced as `witness_mementos` for non-mint consumers.)
        ir = ir + mementos
        _send(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "kind": "ir-document",
                    "ir": ir,
                    "witness_mementos": mementos,
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
    """The ORACLE'S RPC resolve surface. Given a WitnessMemento (and where its
    body lives), RESOLVE the body bytes and return them base64-encoded. The
    oracle returns CONTENT, not a verdict: verification lives in the rust CLI,
    which blake3's these bytes itself and compares to the pinned witness_cid. The
    oracle is untrusted -- it must be verified -- so it only hands over the body.

    Resolution order:
      - PACKAGE: the body is a CID-named file in the witness package (a witness
        of ANY kind -- poem, CI log, compiler report -- resolves this way).
      - RECOMPUTE: a re-runnable pytest-witness is reproduced by re-running the
        pinned test and rebuilding the canonical body.
    A body that cannot be resolved -> error; the verifier treats that as refusal."""
    try:
        memento = params.get("memento") or {}
        cid = memento.get("witness_cid") or params.get("witness_cid")
        if not cid:
            raise RuntimeError("resolve_witness requires a witness_cid")
        ws = params.get("workspace_root")
        package_dir = params.get("package_dir")
        body: Optional[bytes] = None
        resolved_by: Optional[str] = None
        # 1. PACKAGE -- CID-named witness body, deployed separately.
        if package_dir:
            pdir = (
                package_dir
                if os.path.isabs(package_dir)
                else os.path.join(ws or ".", package_dir)
            )
            path = os.path.join(pdir, cid_filename(cid, ".witness"))
            if os.path.isfile(path):
                with open(path, "rb") as f:
                    body = f.read()
                resolved_by = "package"
        # 2a. PACKAGE RECOMPUTE -- a whole-suite WitnessPackageMemento reproduces
        # by re-running the suite and rebuilding the content-addressed bundle.
        if (
            body is None
            and ws
            and memento.get("witness_kind") == "pytest-witness-package"
        ):
            from .witness import build_suite_bundle

            buf, rcid, _ = build_suite_bundle(
                ws,
                list(memento.get("test_files", [])),
                list(memento.get("code_files", [])),
            )
            if rcid != cid:
                raise RuntimeError(
                    f"witness package did not reproduce: recomputed {rcid}, pinned {cid}"
                )
            body = buf
            resolved_by = "recompute"
        # 2. RECOMPUTE -- re-run the pinned test, rebuild the canonical body.
        # `code_files` is PRESENT-not-truthy: an all-tests project pins an EMPTY
        # code_files (the code under test is the installed library, not a local
        # file), and `[]` is falsy -- gating on truthiness would wrongly declare
        # a trivially re-runnable witness "not re-runnable". The reconstruction
        # below pins the empty list into the witness body, so this stays sound.
        if (
            body is None
            and ws
            and memento.get("test")
            and memento.get("code_files") is not None
        ):
            # Don't execute attacker-supplied paths on a memento whose own fields
            # don't even hash to its pinned CID. The witness body is a pure
            # function of (code_cid, runtime_cid, test, outcome, code_files), so a
            # consistent memento MUST reconstruct to `cid` before we run anything.
            probe = Witness(
                code_cid=str(memento.get("code_cid", "")),
                runtime_cid=str(memento.get("runtime_cid", "")),
                test_id=str(memento["test"]),
                outcome=str(memento.get("outcome", "")),
                code_files=tuple(sorted(str(c) for c in memento["code_files"])),
                cid=cid,
            )
            if blake3_512_of(witness_body(probe)) != cid:
                raise RuntimeError(
                    f"memento fields do not reconstruct witness_cid {cid}; "
                    "refusing to re-run a tampered memento"
                )
            w = run_and_witness(ws, memento["test"], list(memento["code_files"]))
            body = witness_body(w)
            resolved_by = "recompute"
        if body is None:
            raise RuntimeError(
                f"cannot resolve witness body for {cid}: no package file and not re-runnable"
            )
        _send(
            {
                "jsonrpc": "2.0",
                "id": msg_id,
                "result": {
                    "witness_cid": cid,
                    "body_b64": base64.b64encode(body).decode("ascii"),
                    "resolved_by": resolved_by,
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
                        "name": "sugar-lsp-pytest-witness",
                        "version": KIT_VERSION,
                        "protocol_version": "sugar-lsp-shared/1",
                        "kit_id": KIT_ID,
                        "capabilities": {
                            "source_surfaces": ["python-pytest-witness"],
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
                            "language": "python",
                            "version": KIT_VERSION,
                        },
                        "rpc": {
                            "methods": [
                                {"name": "initialize", "required": True},
                                {"name": KIT_DECLARATION_RPC_METHOD, "required": True},
                                {"name": COMPONENT_PLAN_RPC_METHOD, "required": False},
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
        elif method == COMPONENT_PLAN_RPC_METHOD:
            _send(
                {
                    "jsonrpc": "2.0",
                    "id": mid,
                    "result": component_plan_result(msg.get("params", {})),
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
