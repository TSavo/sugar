# SPDX-License-Identifier: MIT OR Apache-2.0
import os
import io
import json
import contextlib

import pytest

from sugar_pytest_witness import (
    Witness,
    run_and_witness,
    verify,
    emit_witness_proof,
    discharge_from_proof,
    witness_memento,
    write_witness_package,
    read_witness_body,
)
from sugar_pytest_witness.discharge_cli import main as discharge_main
from sugar_lift_py_tests.witness_oracle import (
    WitnessOracleRefusal,
    resolve_witness,
)

GOOD = "def add(a, b):\n    return a + b\n"
BAD = "def add(a, b):\n    return a + b + 1\n"
TESTSRC = "from impl import add\n\ndef test_add():\n    assert add(2, 3) == 5\n"
CODE = ["impl.py"]  # project-relative


def _project(tmp_path, impl_src):
    (tmp_path / "impl.py").write_text(impl_src)
    (tmp_path / "test_add.py").write_text(TESTSRC)
    return str(tmp_path)


# --- The witnessed k(I)=t link ------------------------------------------------


def test_good_code_witness_discharges_and_reproduces(tmp_path):
    proj = _project(tmp_path, GOOD)
    w = run_and_witness(proj, "test_add.py", CODE)
    assert w.outcome == "passed", w
    assert run_and_witness(proj, "test_add.py", CODE).cid == w.cid, "must reproduce"
    assert verify(w, proj)[0] == "DISCHARGED"


def test_bad_code_cannot_borrow_good_witness(tmp_path):
    proj = _project(tmp_path, GOOD)
    w_good = run_and_witness(proj, "test_add.py", CODE)
    (tmp_path / "impl.py").write_text(BAD)  # mutate
    verdict, reason = verify(w_good, proj)
    assert verdict == "REFUSED" and "code CID mismatch" in reason, reason


def test_bad_code_produces_only_a_failed_witness(tmp_path):
    proj = _project(tmp_path, BAD)
    w = run_and_witness(proj, "test_add.py", CODE)
    assert w.outcome == "failed", w
    assert verify(w, proj)[0] == "REFUSED"


# --- Pipeline: .proof memento + discharge-by-recompute ------------------------


def test_emit_proof_is_content_addressed_and_discharges(tmp_path):
    proj = _project(tmp_path, GOOD)
    w = run_and_witness(proj, "test_add.py", CODE)
    out = tmp_path / "out"
    out.mkdir()
    path = emit_witness_proof(w, str(out))
    assert os.path.basename(path).startswith("blake3-512_") and path.endswith(".proof")
    assert discharge_from_proof(path, proj)[0] == "DISCHARGED"


def test_forged_passed_witness_over_failing_code_is_caught_by_recompute(tmp_path):
    proj = _project(tmp_path, BAD)  # add(2,3)==6, test fails
    w_real = run_and_witness(proj, "test_add.py", CODE)
    assert w_real.outcome == "failed"
    forged = Witness(
        w_real.code_cid,
        w_real.runtime_cid,
        w_real.test_id,
        "passed",
        w_real.code_files,
        w_real.cid,
    )
    out = tmp_path / "out"
    out.mkdir()
    path = emit_witness_proof(forged, str(out))
    verdict, reason = discharge_from_proof(path, proj)
    assert verdict == "REFUSED" and "did not reproduce" in reason, reason


# --- The kit MINTS, the Witness Oracle VERIFIES -------------------------------
# The witness lifter is the minter (we ran the test, we sign the mark); the
# Witness Oracle is the verifier (signature always, recompute when re-runnable).
# That minter/verifier pair is WHY the oracle exists: no external author wrote
# the witness, so we sign our own and re-check it.


def test_minted_memento_carries_no_run_body(tmp_path):
    proj = _project(tmp_path, GOOD)
    w = run_and_witness(proj, "test_add.py", CODE)
    m = witness_memento(w)
    # A pointer + hash + signature -- the run body lives in the witness package.
    assert m["witness_cid"] == w.cid
    assert m["signer"].startswith("ed25519:") and m["signature"]
    assert "proof_data" not in m and "ast_template" not in m


def test_oracle_verifies_minted_witness_by_signature(tmp_path):
    proj = _project(tmp_path, GOOD)
    m = witness_memento(run_and_witness(proj, "test_add.py", CODE))
    # No package, not re-run here -> signature is the universal check.
    assert resolve_witness(m)["verified_by"] == "signature"


def test_oracle_recomputes_minted_witness_via_rerun(tmp_path):
    proj = _project(tmp_path, GOOD)
    w = run_and_witness(proj, "test_add.py", CODE)
    m = witness_memento(w)

    # The pytest-witness is re-runnable + deterministic: the oracle's recompute_fn
    # re-runs the test and re-derives the CID. Reproduces -> recompute-verified.
    def recompute(_m):
        return run_and_witness(proj, w.test_id, list(w.code_files)).cid

    assert resolve_witness(m, recompute_fn=recompute)["verified_by"] == "recompute"


def test_oracle_refuses_minted_witness_when_code_drifts(tmp_path):
    proj = _project(tmp_path, GOOD)
    w = run_and_witness(proj, "test_add.py", CODE)
    m = witness_memento(w)
    (tmp_path / "impl.py").write_text(BAD)  # the bytes you'd run drifted

    def recompute(_m):
        return run_and_witness(proj, w.test_id, list(w.code_files)).cid

    with pytest.raises(WitnessOracleRefusal, match="recompute misaligned"):
        resolve_witness(m, recompute_fn=recompute)


def test_oracle_refuses_minted_witness_with_tampered_signature(tmp_path):
    proj = _project(tmp_path, GOOD)
    m = witness_memento(run_and_witness(proj, "test_add.py", CODE))
    m["signature"] = "00" * 64  # forge the mark
    with pytest.raises(WitnessOracleRefusal, match="signature invalid"):
        resolve_witness(m)


# --- Witness PACKAGE: CID-named bodies, deployed separately --------------------


def test_package_writes_cid_named_witness_files(tmp_path):
    proj = _project(tmp_path, GOOD)
    w = run_and_witness(proj, "test_add.py", CODE)
    pkg = tmp_path / "wpkg"
    paths = write_witness_package([w], str(pkg))
    # the filename IS the CID (":" -> "_"), extension ".witness"
    assert len(paths) == 1
    assert os.path.basename(paths[0]) == w.cid.replace(":", "_") + ".witness"


def test_package_body_content_addresses_to_the_pinned_cid(tmp_path):
    proj = _project(tmp_path, GOOD)
    w = run_and_witness(proj, "test_add.py", CODE)
    pkg = tmp_path / "wpkg"
    write_witness_package([w], str(pkg))
    body = read_witness_body(w.cid, str(pkg))
    # the Witness Oracle's content-address path: bytes blake3 == pinned CID
    m = witness_memento(w)
    assert resolve_witness(m, witness_content=body)["verified_by"] == "content-address"


def test_package_tamper_is_refused_by_content_address(tmp_path):
    proj = _project(tmp_path, GOOD)
    w = run_and_witness(proj, "test_add.py", CODE)
    pkg = tmp_path / "wpkg"
    paths = write_witness_package([w], str(pkg))
    with open(paths[0], "ab") as f:
        f.write(b" tampered")  # swap the body under the same name
    body = read_witness_body(w.cid, str(pkg))
    with pytest.raises(WitnessOracleRefusal, match="content misaligned"):
        resolve_witness(witness_memento(w), witness_content=body)


# --- The oracle speaks RPC: resolve returns the BODY, not a verdict -----------
# Verification lives in the rust CLI; the kit oracle is untrusted and only hands
# over the body bytes over RPC. The verifier blake3's them and audits.


def _rpc(method, params):
    import subprocess, sys
    from sugar_lift_py_tests.canonicalizer import blake3_512_of  # noqa: F401

    req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
    proc = subprocess.run(
        [sys.executable, "-m", "sugar_pytest_witness.lift_lsp", "--rpc"],
        input=req + "\n",
        capture_output=True,
        text=True,
        timeout=60,
    )
    # the kit may print pytest noise; the RPC reply is the last JSON line
    for line in reversed(proc.stdout.strip().splitlines()):
        try:
            return json.loads(line)
        except json.JSONDecodeError:
            continue
    raise AssertionError(f"no JSON-RPC reply; stderr={proc.stderr}")


def test_component_plan_claims_python_pytest_project(tmp_path):
    (tmp_path / "test_base64.py").write_text("def test_ok():\n    assert 1 == 1\n")
    reply = _rpc(
        "sugar.component.plan",
        {
            "workspace_root": str(tmp_path),
            "project_forensics": {
                "items": [
                    {
                        "id": "file:test_base64.py",
                        "kind": "source-file",
                        "path": "test_base64.py",
                        "language_hint": "python",
                        "reason": "python source file",
                    }
                ]
            },
        },
    )

    result = reply["result"]
    assert result["decision"] == "claim"
    assert result["claims"] == [
        {
            "item": "file:test_base64.py",
            "role": "witness-producer",
            "surface": "python-pytest-witness",
        }
    ]
    manifest = result["lift_manifests"][0]
    assert manifest["surface"] == "python-pytest-witness"
    assert manifest["witness_tool"] == "pytest"
    assert manifest["resolve_witness_method"] == "sugar.plugin.resolve_witness"
    assert manifest["command"]
    assert manifest["discharge_command"]
    assert manifest["resolve_witness_command"]


def test_component_plan_declines_python_project_without_pytest_tests(tmp_path):
    (tmp_path / "app.py").write_text("def f():\n    return 1\n")
    reply = _rpc(
        "sugar.component.plan",
        {
            "workspace_root": str(tmp_path),
            "project_forensics": {
                "items": [
                    {
                        "id": "file:app.py",
                        "kind": "source-file",
                        "path": "app.py",
                        "language_hint": "python",
                        "reason": "python source file",
                    }
                ]
            },
        },
    )

    assert reply["result"]["decision"] == "decline"


def test_resolve_witness_rpc_returns_body_that_addresses_to_cid_from_package(tmp_path):
    import base64
    from sugar_pytest_witness import write_witness_package
    from sugar_lift_py_tests.canonicalizer import blake3_512_of

    proj = _project(tmp_path, GOOD)
    w = run_and_witness(proj, "test_add.py", CODE)
    pkg = tmp_path / "wpkg"
    write_witness_package([w], str(pkg))
    reply = _rpc(
        "sugar.plugin.resolve_witness",
        {
            "memento": witness_memento(w),
            "package_dir": str(pkg),
        },
    )
    assert "result" in reply, reply
    body = base64.b64decode(reply["result"]["body_b64"])
    assert reply["result"]["resolved_by"] == "package"
    # the check the rust verifier does: recompute the CID over the resolved body
    assert blake3_512_of(body) == w.cid


def test_resolve_witness_rpc_recompute_reruns_and_returns_body(tmp_path):
    import base64
    from sugar_lift_py_tests.canonicalizer import blake3_512_of

    proj = _project(tmp_path, GOOD)
    w = run_and_witness(proj, "test_add.py", CODE)
    # no package -> the oracle re-runs the pinned test and rebuilds the body
    reply = _rpc(
        "sugar.plugin.resolve_witness",
        {
            "memento": witness_memento(w),
            "workspace_root": proj,
        },
    )
    assert "result" in reply, reply
    assert reply["result"]["resolved_by"] == "recompute"
    body = base64.b64decode(reply["result"]["body_b64"])
    assert blake3_512_of(body) == w.cid


def test_witness_package_one_cid_for_the_whole_suite(tmp_path):
    # The proof carries ONE cid for the whole suite: the WitnessPackageMemento.
    # The per-test facts live IN the content-addressed package; discharge re-runs
    # the suite and reproduces the package cid.
    from sugar_pytest_witness.witness import (
        build_suite_bundle,
        discharge_bundle,
        witness_package_memento,
        blake3_512_of,
    )

    (tmp_path / "test_ok.py").write_text(
        "def test_a():\n    assert 1 == 1\ndef test_b():\n    assert 2 == 2\n"
    )
    buf, pkg_cid, ws = build_suite_bundle(str(tmp_path), ["test_ok.py"], [])
    assert blake3_512_of(buf) == pkg_cid  # the package self-addresses
    assert len(ws) == 2 and all(w.outcome == "passed" for w in ws)
    # all-pass suite -> DISCHARGED by reproduce
    verdict, reason = discharge_bundle(pkg_cid, ["test_ok.py"], [], str(tmp_path))
    assert verdict == "DISCHARGED", reason
    # the memento is ONE pointer over the package cid
    m = witness_package_memento(pkg_cid, ["test_ok.py"], [], 2, 2)
    assert (
        m["kind"] == "witness-memento" and m["witness_kind"] == "pytest-witness-package"
    )
    assert m["witness_cid"] == pkg_cid and m["passed"] == 2 and m["count"] == 2


def test_witness_package_refuses_on_a_failing_test(tmp_path):
    # A suite containing a failing test reproduces (honest) but is REFUSED -- a
    # failing test in the package means the package is not a clean discharge.
    from sugar_pytest_witness.witness import build_suite_bundle, discharge_bundle

    (tmp_path / "test_mix.py").write_text(
        "def test_ok():\n    assert 1 == 1\ndef test_bad():\n    assert False\n"
    )
    _, pkg_cid, _ = build_suite_bundle(str(tmp_path), ["test_mix.py"], [])
    verdict, reason = discharge_bundle(pkg_cid, ["test_mix.py"], [], str(tmp_path))
    assert verdict == "REFUSED" and "1/2" in reason and "test_bad" in reason, reason
    # a DRIFTED package (different pinned cid) is refused as non-reproducing
    bad_cid = "blake3-512:" + "0" * 128
    v2, r2 = discharge_bundle(bad_cid, ["test_mix.py"], [], str(tmp_path))
    assert v2 == "REFUSED" and "did not reproduce" in r2, r2


def test_per_test_witnesses_one_per_node_id(tmp_path):
    # The Oracle runs the file ONCE and mints one witness PER TEST -- a single
    # failing test no longer refuses the whole file's passes.
    from sugar_pytest_witness.witness import run_file_witnesses

    (tmp_path / "test_many.py").write_text(
        "def test_a():\n    assert 1 == 1\n"
        "def test_b():\n    assert 2 == 2\n"
        "def test_c():\n    assert False\n"
    )
    ws = run_file_witnesses(str(tmp_path), "test_many.py", [])
    by = {w.test_id.split("::")[-1]: w.outcome for w in ws}
    assert by == {"test_a": "passed", "test_b": "passed", "test_c": "failed"}, by
    # each witness keys to a pytest node id (file::test), distinct per test
    assert all("::" in w.test_id for w in ws)


def test_per_test_recompute_agrees_with_lift(tmp_path):
    # run_and_witness on a NODE ID reproduces the lift CID (lift and verify share
    # the Oracle's single-file run, so they agree under shared file state).
    from sugar_pytest_witness.witness import run_file_witnesses

    (tmp_path / "test_pair.py").write_text(
        "def test_ok():\n    assert 1 == 1\n" "def test_bad():\n    assert False\n"
    )
    ws = {
        w.test_id.rsplit("::", 1)[-1]: w
        for w in run_file_witnesses(str(tmp_path), "test_pair.py", [])
    }
    for name in ("test_ok", "test_bad"):
        re = run_and_witness(str(tmp_path), ws[name].test_id, [])
        assert re.cid == ws[name].cid, name
        assert re.outcome == ws[name].outcome


def test_witness_bundle_is_content_addressed_jsonl(tmp_path):
    # MANY witnesses in ONE .witness file; each line self-addresses
    # (blake3(line) == cid), so the reader needs no index and trusts nothing.
    from sugar_pytest_witness.witness import (
        run_file_witnesses,
        write_witness_bundle,
        read_witness_bundle,
        read_witness_from_bundle,
    )
    from sugar_lift_py_tests.canonicalizer import blake3_512_of

    (tmp_path / "test_b.py").write_text(
        "def test_a():\n    assert 1 == 1\n" "def test_b():\n    assert 2 == 2\n"
    )
    ws = run_file_witnesses(str(tmp_path), "test_b.py", [])
    bundle = str(tmp_path / "all.witness")
    write_witness_bundle(ws, bundle)
    loaded = read_witness_bundle(bundle)
    assert set(loaded) == {w.cid for w in ws}
    for cid, body in loaded.items():
        assert blake3_512_of(body) == cid  # the line IS the key
    # a tampered line keys to a different cid -> single lookup misses, no false hit
    assert read_witness_from_bundle("blake3-512:" + "0" * 128, bundle) is None


def test_resolve_witness_rpc_recompute_with_empty_code_files(tmp_path):
    # REGRESSION: an all-tests project pins an EMPTY code_files (the code under
    # test is the installed library, e.g. numpy/pandas, not a local file). An
    # empty list is FALSY, so a truthiness guard on `code_files` wrongly declared
    # such a witness "not re-runnable". It is trivially re-runnable -- just rerun
    # the test -- and the empty list reconstructs into the pinned witness body.
    import base64
    from sugar_lift_py_tests.canonicalizer import blake3_512_of

    (tmp_path / "test_solo.py").write_text("def test_solo():\n    assert 1 == 1\n")
    w = run_and_witness(str(tmp_path), "test_solo.py", [])  # empty code_files
    assert w.code_files == ()
    reply = _rpc(
        "sugar.plugin.resolve_witness",
        {
            "memento": witness_memento(w),
            "workspace_root": str(tmp_path),
        },
    )
    assert "result" in reply, reply  # NOT an error ("not re-runnable")
    assert reply["result"]["resolved_by"] == "recompute"
    assert blake3_512_of(base64.b64decode(reply["result"]["body_b64"])) == w.cid


def test_resolve_witness_rpc_refuses_recompute_on_tampered_memento(tmp_path):
    # The body is a pure function of the memento's own fields, so a memento whose
    # fields don't reconstruct its pinned CID is tampered. The oracle must refuse
    # BEFORE executing the (attacker-controlled) test path, not after.
    proj = _project(tmp_path, GOOD)
    w = run_and_witness(proj, "test_add.py", CODE)
    m = witness_memento(w)
    m["outcome"] = "failed"  # cid still pins the passing run -> no longer reconstructs
    reply = _rpc("sugar.plugin.resolve_witness", {"memento": m, "workspace_root": proj})
    assert "error" in reply and "do not reconstruct" in reply["error"]["message"], reply


def test_resolve_witness_rpc_errors_when_unresolvable(tmp_path):
    proj = _project(tmp_path, GOOD)
    w = run_and_witness(proj, "test_add.py", CODE)
    m = witness_memento(w)
    m.pop("test")
    m.pop("code_files")  # not re-runnable, no package
    reply = _rpc("sugar.plugin.resolve_witness", {"memento": m})
    assert "error" in reply and "cannot resolve" in reply["error"]["message"]


# --- The verifier<->kit contract: the discharge command -----------------------


def _run_discharge(proof_path, proj):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = discharge_main([proof_path, proj])
    return rc, json.loads(buf.getvalue())


def test_discharge_command_good(tmp_path):
    proj = _project(tmp_path, GOOD)
    out = tmp_path / "out"
    out.mkdir()
    path = emit_witness_proof(run_and_witness(proj, "test_add.py", CODE), str(out))
    rc, j = _run_discharge(path, proj)
    assert rc == 0 and j["verdict"] == "DISCHARGED", j


def test_discharge_command_refuses_mutated(tmp_path):
    proj = _project(tmp_path, GOOD)
    out = tmp_path / "out"
    out.mkdir()
    path = emit_witness_proof(run_and_witness(proj, "test_add.py", CODE), str(out))
    (tmp_path / "impl.py").write_text(BAD)
    rc, j = _run_discharge(path, proj)
    assert rc == 1 and j["verdict"] == "REFUSED", j
