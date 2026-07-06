# SPDX-License-Identifier: MIT OR Apache-2.0
"""Witness deterministic build script executions.

This is the same witness protocol the pytest seat uses, pointed at a build.
The kit owns the rerun. The Rust verifier owns signature and BLAKE3 recompute.
"""

from __future__ import annotations

import base64
import json
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import nacl.signing

from sugar_lift_py_tests.canonicalizer import (
    blake3_512_of,
    encode_jcs,
    varr,
    vbool,
    vint,
    vnull,
    vobj,
    vstr,
)
from sugar_lift_py_tests.filename import cid_filename

BUILD_WITNESS_KIND = "build-witness"
DEFAULT_MANIFEST = "build-witness.json"
SIGNER_SEED_ENV = "SUGAR_WITNESS_SIGNER_SEED"
BUILD_WITNESS_SIGNER_SEED = bytes([0x62]) * 32


@dataclass(frozen=True)
class BuildWitness:
    manifest_path: str
    manifest_cid: str
    repo_script: str
    repo_script_cid: str
    distributed_script: str
    distributed_script_cid: str
    source_tree_cid: str
    toolchain_id: str
    command: tuple[str, ...]
    outputs: tuple[dict[str, str], ...]
    failures: tuple[str, ...]
    outcome: str
    cid: str


def _to_value(value: Any):
    if value is None:
        return vnull()
    if isinstance(value, bool):
        return vbool(value)
    if isinstance(value, int) and not isinstance(value, bool):
        return vint(value)
    if isinstance(value, str):
        return vstr(value)
    if isinstance(value, list) or isinstance(value, tuple):
        return varr([_to_value(v) for v in value])
    if isinstance(value, dict):
        return vobj([(str(k), _to_value(v)) for k, v in value.items()])
    raise TypeError(f"unsupported canonical value: {type(value)!r}")


def _canonical_bytes(value: Mapping[str, Any]) -> bytes:
    return encode_jcs(_to_value(dict(value))).encode("utf-8")


def _canonical_cid(value: Mapping[str, Any]) -> str:
    return blake3_512_of(_canonical_bytes(value))


def _safe_rel(path: str) -> str:
    if not isinstance(path, str) or not path.strip():
        raise ValueError("path must be a non-empty string")
    p = Path(path)
    if p.is_absolute() or ".." in p.parts:
        raise ValueError(f"path must be project-relative and stay in tree: {path}")
    return path


def _read_manifest(root: Path, manifest_path: str) -> dict[str, Any]:
    rel = _safe_rel(manifest_path)
    data = json.loads((root / rel).read_text(encoding="utf-8"))
    if data.get("kind") != BUILD_WITNESS_KIND:
        raise ValueError(f"{manifest_path} kind must be {BUILD_WITNESS_KIND!r}")
    return data


def _file_cid(root: Path, rel: str) -> str:
    path = root / _safe_rel(rel)
    return blake3_512_of(path.read_bytes()) if path.is_file() else "MISSING"


def _tree_cid(root: Path, rels: Iterable[str]) -> str:
    parts = []
    for rel in sorted(_safe_rel(r) for r in rels):
        path = root / rel
        if not path.is_file():
            parts.append(rel.encode("utf-8") + b"\0MISSING")
        else:
            parts.append(rel.encode("utf-8") + b"\0" + path.read_bytes())
    return blake3_512_of(b"\0".join(parts))


def _toolchain_id(configured: str) -> str:
    desc = (
        f"{configured};python={tuple(sys.version_info[:3])};"
        f"impl={platform.python_implementation()};platform={platform.system()}"
    )
    return blake3_512_of(desc.encode("utf-8"))


def _expand_command(command: list[str]) -> list[str]:
    expanded: list[str] = []
    for part in command:
        if part == "{python}":
            expanded.append(sys.executable)
        else:
            expanded.append(str(part))
    return expanded


def _clean_rebuild_outputs(root: Path, outputs: list[dict[str, str]]) -> None:
    for output in outputs:
        rebuilt = output.get("rebuilt")
        if not rebuilt:
            continue
        rel = _safe_rel(str(rebuilt))
        path = root / rel
        if path.is_file():
            path.unlink()
    shutil.rmtree(root / ".build", ignore_errors=True)


def _witness_value(w: BuildWitness) -> dict[str, Any]:
    return {
        "kind": BUILD_WITNESS_KIND,
        "command": list(w.command),
        "distributedScript": w.distributed_script,
        "distributedScriptCid": w.distributed_script_cid,
        "failures": list(w.failures),
        "manifestCid": w.manifest_cid,
        "manifestPath": w.manifest_path,
        "outcome": w.outcome,
        "outputs": list(w.outputs),
        "repoScript": w.repo_script,
        "repoScriptCid": w.repo_script_cid,
        "sourceTreeCid": w.source_tree_cid,
        "toolchainId": w.toolchain_id,
    }


def witness_body(w: BuildWitness) -> bytes:
    return _canonical_bytes(_witness_value(w))


def run_build_witness(
    project_dir: str, manifest_path: str = DEFAULT_MANIFEST
) -> BuildWitness:
    root = Path(project_dir)
    manifest_rel = _safe_rel(manifest_path)
    manifest = _read_manifest(root, manifest_rel)
    repo_script = _safe_rel(str(manifest["repoScript"]))
    distributed_script = _safe_rel(str(manifest["distributedScript"]))
    sources = [_safe_rel(str(p)) for p in manifest.get("sources", [])]
    command = [str(p) for p in manifest["command"]]
    outputs = [
        {
            "distributed": _safe_rel(str(o["distributed"])),
            "rebuilt": _safe_rel(str(o["rebuilt"])),
        }
        for o in manifest.get("outputs", [])
    ]

    repo_script_cid = _file_cid(root, repo_script)
    distributed_script_cid = _file_cid(root, distributed_script)
    source_tree_cid = _tree_cid(root, sources)
    manifest_cid = _canonical_cid(manifest)
    toolchain_id = _toolchain_id(str(manifest.get("toolchain", "build")))
    failures: list[str] = []

    if repo_script_cid != distributed_script_cid:
        failures.append(
            "distributed script CID mismatch: "
            f"repo {repo_script_cid} != distributed {distributed_script_cid}"
        )

    _clean_rebuild_outputs(root, outputs)
    proc = subprocess.run(
        _expand_command(command),
        cwd=root,
        capture_output=True,
        text=True,
        timeout=int(manifest.get("timeoutSeconds", 30)),
    )
    if proc.returncode != 0:
        failures.append(
            f"build command failed with exit {proc.returncode}: "
            f"{(proc.stderr or proc.stdout).strip()[:240]}"
        )

    output_rows: list[dict[str, str]] = []
    for output in outputs:
        distributed_cid = _file_cid(root, output["distributed"])
        rebuilt_cid = _file_cid(root, output["rebuilt"])
        output_rows.append(
            {
                "distributed": output["distributed"],
                "distributedCid": distributed_cid,
                "rebuilt": output["rebuilt"],
                "rebuiltCid": rebuilt_cid,
            }
        )
        if distributed_cid != rebuilt_cid:
            failures.append(
                "output artifact CID mismatch: "
                f"{output['distributed']} {distributed_cid} != "
                f"{output['rebuilt']} {rebuilt_cid}"
            )

    outcome = "passed" if not failures else "failed"
    draft = BuildWitness(
        manifest_path=manifest_rel,
        manifest_cid=manifest_cid,
        repo_script=repo_script,
        repo_script_cid=repo_script_cid,
        distributed_script=distributed_script,
        distributed_script_cid=distributed_script_cid,
        source_tree_cid=source_tree_cid,
        toolchain_id=toolchain_id,
        command=tuple(command),
        outputs=tuple(output_rows),
        failures=tuple(failures),
        outcome=outcome,
        cid="",
    )
    cid = blake3_512_of(witness_body(draft))
    return BuildWitness(**{**draft.__dict__, "cid": cid})


def _resolve_signer_seed(seed: bytes | None = None) -> bytes:
    if seed is not None:
        return seed
    env = os.environ.get(SIGNER_SEED_ENV)
    if env:
        raw = bytes.fromhex(env.strip())
        if len(raw) != 32:
            raise ValueError(f"{SIGNER_SEED_ENV} must be 64 hex chars")
        return raw
    return BUILD_WITNESS_SIGNER_SEED


def build_witness_memento(w: BuildWitness, seed: bytes | None = None) -> dict[str, Any]:
    sk = nacl.signing.SigningKey(_resolve_signer_seed(seed))
    sig = sk.sign(w.cid.encode("utf-8")).signature
    return {
        "kind": "witness-memento",
        "witness_cid": w.cid,
        "witness_kind": BUILD_WITNESS_KIND,
        "signer": "ed25519:" + base64.b64encode(bytes(sk.verify_key)).decode("ascii"),
        "signature": "ed25519:" + base64.b64encode(sig).decode("ascii"),
        "manifest_path": w.manifest_path,
        "manifest_cid": w.manifest_cid,
        "repo_script_cid": w.repo_script_cid,
        "distributed_script_cid": w.distributed_script_cid,
        "source_tree_cid": w.source_tree_cid,
        "toolchain_id": w.toolchain_id,
    }


def write_witness_package(w: BuildWitness, out_dir: str) -> str:
    os.makedirs(out_dir, exist_ok=True)
    body = witness_body(w)
    if blake3_512_of(body) != w.cid:
        raise ValueError("build witness body does not address to its CID")
    path = os.path.join(out_dir, cid_filename(w.cid, ".witness"))
    with open(path, "wb") as f:
        f.write(body)
    return path


def discharge_build_witness(
    witness_cid: str, project_dir: str, manifest_path: str = DEFAULT_MANIFEST
) -> tuple[str, str]:
    w = run_build_witness(project_dir, manifest_path)
    if w.cid != witness_cid:
        detail = "; ".join(w.failures) if w.failures else "build body changed"
        return (
            "REFUSED",
            f"build witness did not reproduce: recomputed {w.cid} != pinned {witness_cid}; {detail}",
        )
    if w.outcome != "passed":
        return ("REFUSED", "; ".join(w.failures) or "build witness recorded failure")
    return (
        "DISCHARGED",
        "build reran; script CID, source-tree CID, toolchain id, and output artifact CIDs reproduced",
    )


def discharge_from_proof(proof_path: str, project_dir: str) -> tuple[str, str]:
    evidence = json.loads(Path(proof_path).read_text(encoding="utf-8"))
    proof_data = json.loads(evidence["certificate"]["proofData"])
    if proof_data.get("kind") != BUILD_WITNESS_KIND:
        return ("REFUSED", "discharge error: proofData is not a build-witness")
    return discharge_build_witness(
        str(proof_data["witnessCid"]),
        project_dir,
        str(proof_data.get("manifestPath", DEFAULT_MANIFEST)),
    )
