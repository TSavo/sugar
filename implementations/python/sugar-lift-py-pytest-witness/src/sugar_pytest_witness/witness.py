# SPDX-License-Identifier: MIT OR Apache-2.0
"""pytest witness lifter -- the proofchain-native correctness producer.

Instead of lifting a test's assertions into a symbolic consistency claim, this
RUNS the test: pytest is the deterministic transform ``k``, the code-under-test
is ``I``, the observed pass/fail is ``t``.  The run is content-addressed into a
witness memento with the substrate's own CID machinery (``jcs_hash``).

A witness is a k(I)=t proofchain link.  It pins the code CID + runtime CID +
outcome and is SELF-DESCRIBING about which code it covers (project-relative
paths), so a verifier holding only the project root can recompute.  VERIFICATION
IS RECOMPUTATION -- re-run on the pinned code, rebuild the witness, memcmp.
Nothing is trusted.

Teeth: the witness is cryptographically bound to the exact code.  A wrong impl
has a different code CID (can't borrow a correct program's passing witness) and,
when run, yields a ``failed`` outcome (can mint no passing witness of its own).
You cannot witness code right that runs wrong.
"""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
from dataclasses import dataclass
from typing import List, Tuple

from sugar_lift_py_tests.canonicalizer import (
    blake3_512_of,
    encode_jcs,
    jcs_hash,
    vobj,
    vstr,
)
from sugar_lift_py_tests.filename import cid_filename, proof_filename


def code_cid(project_dir: str, code_files: List[str]) -> str:
    """Content-address the code under test by PROJECT-RELATIVE path + content,
    so the same witness re-runs from any checkout of the same project."""
    parts = []
    for rel in sorted(code_files):
        with open(os.path.join(project_dir, rel), "rb") as f:
            parts.append(rel.encode("utf-8") + b"\0" + f.read())
    return blake3_512_of(b"\0".join(parts))


def runtime_cid() -> str:
    """Pin the runtime that makes the run reproducible.  The witness only holds
    where this CID reproduces -- trivial for pure code; for FP/SIMD kernels it is
    exactly where reproducibility must be earned and stated."""
    desc = (
        f"python={tuple(sys.version_info[:3])};"
        f"impl={platform.python_implementation()};"
        f"platform={platform.platform()}"
    )
    return blake3_512_of(desc.encode("utf-8"))


def _witness_value(
    code: str, runtime: str, test_id: str, outcome: str, code_files: List[str]
):
    return vobj(
        [
            ("kind", vstr("pytest-witness")),
            ("codeCid", vstr(code)),
            ("codeFiles", vstr(",".join(sorted(code_files)))),
            ("outcome", vstr(outcome)),
            ("runtimeCid", vstr(runtime)),
            ("test", vstr(test_id)),
        ]
    )


@dataclass(frozen=True)
class Witness:
    code_cid: str
    runtime_cid: str
    test_id: str
    outcome: str  # "passed" | "failed"
    code_files: Tuple[str, ...]  # project-relative
    cid: str


def run_file_witnesses(
    project_dir: str, test_file: str, code_files: List[str]
) -> List[Witness]:
    """The Oracle's PER-TEST run primitive: run ALL tests in ``test_file`` under
    pytest ONCE -- in the package's own execution context (conftest, fixtures,
    relative imports) -- and content-address EACH test as its own witness, keyed
    by the pytest node id. One file run, N per-test witnesses.

    This is what fixes the coarse per-file witness, where one failing test out of
    thousands refused the whole file. The ``_witness_collect`` plugin records
    every test's outcome from the single run; mint and verify share THIS
    primitive, so lift and recompute agree on outcome under shared file state.
    """
    import json as _json
    import tempfile

    cc = code_cid(project_dir, code_files)
    rc = runtime_cid()
    fd, out_path = tempfile.mkstemp(suffix=".json", prefix="pvk-witness-")
    os.close(fd)
    try:
        # Load the capture plugin STANDALONE (bare module name), with its own
        # directory on PYTHONPATH. `_witness_collect` imports only json/os, so it
        # loads without pulling in the rest of the package (which would need the
        # whole kit dependency chain on the path). This makes the per-test run
        # robust to cwd and to a partial PYTHONPATH.
        plugin_dir = os.path.dirname(os.path.abspath(__file__))
        env_pp = os.pathsep.join(
            p for p in (plugin_dir, os.environ.get("PYTHONPATH", "")) if p
        )
        env = dict(os.environ, SUGAR_WITNESS_OUT=out_path, PYTHONPATH=env_pp)
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                test_file,
                "-q",
                "-p",
                "no:cacheprovider",
                "-p",
                "_witness_collect",
            ],
            cwd=project_dir,
            capture_output=True,
            text=True,
            env=env,
        )
        results: dict = {}
        if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
            with open(out_path, encoding="utf-8") as f:
                try:
                    results = _json.load(f)
                except ValueError:
                    results = {}
    finally:
        if os.path.exists(out_path):
            os.remove(out_path)

    witnesses: List[Witness] = []
    for nodeid, raw in sorted(results.items()):
        if raw == "skipped":
            continue  # a skip is neither a discharge nor a refusal
        outcome = "passed" if raw == "passed" else "failed"
        cid = jcs_hash(_witness_value(cc, rc, nodeid, outcome, code_files))
        witnesses.append(
            Witness(cc, rc, nodeid, outcome, tuple(sorted(code_files)), cid)
        )
    return witnesses


def run_and_witness(project_dir: str, test_id: str, code_files: List[str]) -> Witness:
    """Content-address ONE witness for ``test_id`` in ``project_dir``.

    A pytest NODE ID (``file::test`` / ``file::Class::test``) is reproduced via
    its FILE -- the same single-file run the per-test lift used -- so lift and
    recompute agree on outcome under shared file state. A bare FILE path keeps
    the legacy whole-file witness (exit-code outcome). The Oracle owns both."""
    if "::" in test_id:
        test_file = test_id.split("::", 1)[0]
        for w in run_file_witnesses(project_dir, test_file, code_files):
            if w.test_id == test_id:
                return w
        # The node id is gone (test removed/renamed) -> a non-reproducing
        # 'failed' witness, so verify REFUSES rather than inventing a pass.
        cc = code_cid(project_dir, code_files)
        rc = runtime_cid()
        cid = jcs_hash(_witness_value(cc, rc, test_id, "failed", code_files))
        return Witness(cc, rc, test_id, "failed", tuple(sorted(code_files)), cid)

    cc = code_cid(project_dir, code_files)
    rc = runtime_cid()
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", test_id, "-q", "-p", "no:cacheprovider"],
        cwd=project_dir,
        capture_output=True,
        text=True,
    )
    outcome = "passed" if proc.returncode == 0 else "failed"
    cid = jcs_hash(_witness_value(cc, rc, test_id, outcome, code_files))
    return Witness(cc, rc, test_id, outcome, tuple(sorted(code_files)), cid)


# ---------------------------------------------------------------------------
# WitnessMemento: the signed pointer the `.proof` carries INSTEAD of the run body.
# ---------------------------------------------------------------------------

# The DEV witness-signing seed. A witness is OUR signed mark; in PRODUCTION the
# seed MUST come from the prover's provenance key (vault), via the env override
# below. This globally-known default is an INTEGRITY TAG ONLY (it proves the body
# was not altered, not WHO signed it) and is here so mementos are reproducible in
# tests. Set SUGAR_WITNESS_SIGNER_SEED (64 hex chars) for an authoritative key.
WITNESS_SIGNER_SEED = bytes([0x77]) * 32  # 'w' for witness; dev/integrity-tag only
_SIGNER_SEED_ENV = "SUGAR_WITNESS_SIGNER_SEED"


def _resolve_signer_seed(seed: bytes | None) -> bytes:
    """Explicit override wins; else the env-provided authoritative seed; else the
    well-known dev seed (integrity tag only)."""
    if seed is not None:
        return seed
    env = os.environ.get(_SIGNER_SEED_ENV)
    if env:
        raw = bytes.fromhex(env.strip())
        if len(raw) != 32:
            raise ValueError(
                f"{_SIGNER_SEED_ENV} must be 64 hex chars (32 bytes); got {len(raw)}"
            )
        return raw
    return WITNESS_SIGNER_SEED


def witness_memento(w: "Witness", seed: bytes | None = None) -> dict:
    """Build a signed WitnessMemento. The `.proof` carries THIS -- a pointer +
    hash + signature -- not the run body. The body (the recorded run) goes to the
    witness package, resolved + re-verified by the Witness Oracle: signature
    always (whose mark), recompute when the runtime pin reproduces. The signing
    seed comes from SUGAR_WITNESS_SIGNER_SEED in production; the dev default is
    an integrity tag only."""
    import base64
    import nacl.signing

    sk = nacl.signing.SigningKey(_resolve_signer_seed(seed))
    sig = sk.sign(w.cid.encode("utf-8")).signature
    # The substrate's canonical ed25519 string form: `ed25519:` + base64, so the
    # rust verifier checks a witness with the SAME primitive (ed25519_verify_string)
    # it uses for every other signature. One signature format across the substrate.
    return {
        "kind": "witness-memento",
        "witness_cid": w.cid,
        "witness_kind": "pytest-witness",
        "signer": "ed25519:" + base64.b64encode(bytes(sk.verify_key)).decode("ascii"),
        "signature": "ed25519:" + base64.b64encode(sig).decode("ascii"),
        "runtime_cid": w.runtime_cid,
        "code_cid": w.code_cid,
        "test": w.test_id,
        "outcome": w.outcome,
        "code_files": list(w.code_files),
    }


# ---------------------------------------------------------------------------
# Witness PACKAGE: the bodies the `.proof` does NOT carry, content-addressed on
# disk. One file per witness, named by its CID, holding the bytes the CID
# addresses. Deployed SEPARATELY from the `.proof` (audit material, not ship
# material). The Witness Oracle's content-address path reads `<cid>.witness`,
# blake3's it, and confirms it equals the pinned witness_cid.
# ---------------------------------------------------------------------------


def witness_body(w: "Witness") -> bytes:
    """The bytes the witness CID addresses: the canonical run record. By
    construction ``blake3_512_of(witness_body(w)) == w.cid`` -- the file content
    IS what was signed for, so the oracle can content-address it."""
    return encode_jcs(
        _witness_value(
            w.code_cid, w.runtime_cid, w.test_id, w.outcome, list(w.code_files)
        )
    ).encode("utf-8")


def write_witness_package(witnesses: List["Witness"], out_dir: str) -> List[str]:
    """Write a witness package: one `<cid>.witness` file per witness, content =
    the bytes the CID addresses. Returns the paths written. This is the
    deploy-separately bundle the Witness Oracle resolves bodies from."""
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for w in witnesses:
        body = witness_body(w)
        # Explicit runtime integrity check (NOT `assert`: must hold under `-O`).
        if blake3_512_of(body) != w.cid:
            raise ValueError(
                f"witness body does not address to its CID: computed "
                f"{blake3_512_of(body)}, pinned {w.cid}"
            )
        path = os.path.join(out_dir, cid_filename(w.cid, ".witness"))
        with open(path, "wb") as f:
            f.write(body)
        paths.append(path)
    return paths


def read_witness_body(witness_cid: str, package_dir: str) -> bytes:
    """Read a witness body from a package by CID. The Witness Oracle hands these
    bytes to its content-address check (blake3 == witness_cid) -- a swapped or
    truncated file is caught there, refused loudly.

    Resolution order: first the legacy one-file-per-CID ``<cid>.witness``; then
    any multi-witness ``.witness`` BUNDLE in the dir (the per-test, whole-suite
    shape). Either way the caller re-blake3's the bytes, so this is just a lookup.
    """
    path = os.path.join(package_dir, cid_filename(witness_cid, ".witness"))
    if os.path.isfile(path):
        with open(path, "rb") as f:
            return f.read()
    for name in sorted(os.listdir(package_dir)):
        if not name.endswith(".witness") or name == cid_filename(
            witness_cid, ".witness"
        ):
            continue
        body = read_witness_from_bundle(witness_cid, os.path.join(package_dir, name))
        if body is not None:
            return body
    raise FileNotFoundError(f"no witness body for {witness_cid} in {package_dir}")


# ---------------------------------------------------------------------------
# Witness BUNDLE: MANY witnesses in ONE `.witness` file. A per-test run of a real
# package yields thousands of witnesses; carrying each as its own file (or inline
# `.proof` memento) does not scale. A bundle is content-addressed JSONL -- ONE
# canonical witness body per line, and ``blake3_512_of(line) == that witness's
# cid``. The content IS the key: no index, nothing to trust. The Oracle resolves
# a body by scanning + blake3-matching, exactly its content-address check.
# ---------------------------------------------------------------------------


def write_witness_bundle(witnesses: List["Witness"], path: str) -> str:
    """Write MANY witness bodies into ONE `.witness` bundle (content-addressed
    JSONL, one canonical body per line). Returns the path written."""
    parent = os.path.dirname(os.path.abspath(path))
    os.makedirs(parent, exist_ok=True)
    with open(path, "wb") as f:
        for w in witnesses:
            body = witness_body(w)  # JCS: compact, single line, no embedded newline
            if blake3_512_of(body) != w.cid:
                raise ValueError(
                    f"witness body does not address to its CID: computed "
                    f"{blake3_512_of(body)}, pinned {w.cid}"
                )
            f.write(body)
            f.write(b"\n")
    return path


def build_suite_bundle(
    project_dir: str, test_files: List[str], code_files: List[str]
) -> "Tuple[bytes, str, List[Witness]]":
    """Run EVERY test file per-test and assemble ONE content-addressed bundle.

    Returns ``(bundle_bytes, bundle_cid, witnesses)``. The bundle is a
    witness-of-witnesses: ``bundle_cid = blake3_512_of(bundle_bytes)``, so the
    `.proof` can pin the ENTIRE suite run with ONE cid, and the oracle reproduces
    it by re-running. Deterministic: witnesses are sorted by node id so the bytes
    -- and the cid -- are reproducible across runs.
    """
    witnesses: List[Witness] = []
    for tf in sorted(test_files):
        witnesses.extend(run_file_witnesses(project_dir, tf, code_files))
    witnesses.sort(key=lambda w: w.test_id)
    buf = b"".join(witness_body(w) + b"\n" for w in witnesses)
    return buf, blake3_512_of(buf), witnesses


def witness_package_memento(
    bundle_cid: str,
    test_files: List[str],
    code_files: List[str],
    count: int,
    passed: int,
    seed: bytes | None = None,
) -> dict:
    """The ONE memento the `.proof` carries for a WHOLE SUITE: a WitnessPackageMemento.

    Instead of N per-test mementos, mint stores ONE pointer to the witness
    PACKAGE (the content-addressed `.witness` bundle): hash + signature over the
    package cid, plus the `test_files`/`code_files` the oracle needs to RESOLVE
    and REPRODUCE the package by re-running the suite. The per-test bodies live in
    the package, addressed by `witness_cid`; the proof carries 64 bytes, not 48k.

    The envelope `kind` stays ``witness-memento`` so the verifier's signed
    dimension processes it unchanged (it resolves the body by cid and
    content-addresses it -- the body IS the bundle). ``witness_kind`` marks it as
    the package variant."""
    import base64
    import nacl.signing

    sk = nacl.signing.SigningKey(_resolve_signer_seed(seed))
    sig = sk.sign(bundle_cid.encode("utf-8")).signature
    return {
        "kind": "witness-memento",
        "witness_cid": bundle_cid,
        "witness_kind": "pytest-witness-package",
        "signer": "ed25519:" + base64.b64encode(bytes(sk.verify_key)).decode("ascii"),
        "signature": "ed25519:" + base64.b64encode(sig).decode("ascii"),
        "test_files": sorted(test_files),
        "code_files": sorted(code_files),
        "count": count,
        "passed": passed,
    }


def discharge_bundle(
    bundle_cid: str, test_files: List[str], code_files: List[str], project_dir: str
) -> Tuple[str, str]:
    """Discharge a whole-suite bundle BY RECOMPUTE: re-run the suite, rebuild the
    bundle, and confirm it reproduces the pinned cid. DISCHARGED iff the suite
    reproduced AND every per-test witness passed; else REFUSED with the breakdown
    (which is what a failing test in the package means)."""
    buf, cid, witnesses = build_suite_bundle(project_dir, test_files, code_files)
    n = len(witnesses)
    if cid != bundle_cid:
        return (
            "REFUSED",
            f"suite did not reproduce the pinned bundle: recomputed "
            f"{cid[:28]}... != pinned {bundle_cid[:28]}... ({n} tests re-run)",
        )
    failed = [w.test_id for w in witnesses if w.outcome != "passed"]
    if failed:
        shown = ", ".join(t.rsplit("::", 1)[-1] for t in failed[:6])
        more = f" (+{len(failed) - 6} more)" if len(failed) > 6 else ""
        return (
            "REFUSED",
            f"bundle reproduced but {len(failed)}/{n} tests failed: {shown}{more}",
        )
    return (
        "DISCHARGED",
        f"suite re-ran; all {n} per-test witnesses reproduced and passed",
    )


def read_witness_bundle(path: str) -> "dict[str, bytes]":
    """Load a `.witness` bundle as {witness_cid: body}, content-addressing each
    line itself (the cid IS blake3 of the body) -- a tampered line simply keys to
    a different cid and never satisfies a lookup."""
    out: "dict[str, bytes]" = {}
    with open(path, "rb") as f:
        for line in f:
            body = line.rstrip(b"\n")
            if not body:
                continue
            out[blake3_512_of(body)] = body
    return out


def read_witness_from_bundle(witness_cid: str, path: str) -> "bytes | None":
    """Return the body for ``witness_cid`` from a `.witness` bundle, or None.
    Matches by re-blake3'ing each line, so the lookup IS the integrity check."""
    with open(path, "rb") as f:
        for line in f:
            body = line.rstrip(b"\n")
            if body and blake3_512_of(body) == witness_cid:
                return body
    return None


def verify(witness: Witness, project_dir: str) -> Tuple[str, str]:
    """Verify a witness BY RECOMPUTATION against ``project_dir``.

    DISCHARGED iff the project's code (at the witness's own code paths) hashes to
    the witness's ``codeCid`` (binding), re-running reproduces the witness CID,
    and the witnessed outcome is ``passed``.  Anything else is REFUSED.
    """
    actual = code_cid(project_dir, list(witness.code_files))
    if actual != witness.code_cid:
        return ("REFUSED", "code CID mismatch -- this witness is not about this code")
    recomputed = run_and_witness(project_dir, witness.test_id, list(witness.code_files))
    if recomputed.cid != witness.cid:
        return (
            "REFUSED",
            f"witness did not reproduce (re-run outcome: {recomputed.outcome})",
        )
    if witness.outcome != "passed":
        return ("REFUSED", f"witnessed outcome is {witness.outcome!r}, not a discharge")
    return (
        "DISCHARGED",
        "re-ran on pinned code; assertions held; witness CID reproduced",
    )


# ---------------------------------------------------------------------------
# Pipeline-native: persist as a content-addressed .proof memento (the IR
# EvidenceTerm{proofType:"custom"} shape) and discharge BY RECOMPUTE.
# ---------------------------------------------------------------------------


def _witness_envelope_value(w: Witness):
    proof_data = json.dumps(
        {
            "codeCid": w.code_cid,
            "runtimeCid": w.runtime_cid,
            "test": w.test_id,
            "outcome": w.outcome,
            "codeFiles": list(w.code_files),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    cert = vobj(
        [
            ("tool", vstr("pytest")),
            ("version", vstr(w.runtime_cid)),
            ("formulaHash", vstr(w.cid)),
            ("proofData", vstr(proof_data)),
        ]
    )
    return vobj(
        [
            ("kind", vstr("evidence")),
            ("proofType", vstr("custom")),
            ("certificate", cert),
        ]
    )


def emit_witness_proof(w: Witness, out_dir: str) -> str:
    """Write the witness as a content-addressed ``.proof`` (filename = its CID)."""
    val = _witness_envelope_value(w)
    envelope_cid = jcs_hash(val)
    path = os.path.join(out_dir, proof_filename(envelope_cid))
    with open(path, "w", encoding="utf-8") as f:
        f.write(encode_jcs(val))
    return path


def load_witness_from_proof(proof_path: str) -> Witness:
    env = json.loads(open(proof_path, encoding="utf-8").read())
    pd = json.loads(env["certificate"]["proofData"])
    code_files = tuple(sorted(pd["codeFiles"]))
    cid = jcs_hash(
        _witness_value(
            pd["codeCid"], pd["runtimeCid"], pd["test"], pd["outcome"], list(code_files)
        )
    )
    return Witness(
        pd["codeCid"], pd["runtimeCid"], pd["test"], pd["outcome"], code_files, cid
    )


def discharge_from_proof(proof_path: str, project_dir: str) -> Tuple[str, str]:
    """Pipeline discharge: load the witness memento and settle it BY RECOMPUTE.

    A forged ``passed`` envelope over failing code is caught here -- the re-run
    mints a ``failed`` witness whose CID will not match the forged one.

    A WHOLE-SUITE package (proofData ``kind == "witness-package"``) settles by
    re-running the suite and reproducing the package cid (``discharge_bundle``).
    """
    env = json.loads(open(proof_path, encoding="utf-8").read())
    pd = json.loads(env["certificate"]["proofData"])
    if pd.get("kind") == "witness-package":
        return discharge_bundle(
            pd["packageCid"],
            list(pd.get("testFiles", [])),
            list(pd.get("codeFiles", [])),
            project_dir,
        )
    w = load_witness_from_proof(proof_path)
    return verify(w, project_dir)
