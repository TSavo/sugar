# SPDX-License-Identifier: MIT OR Apache-2.0
import json
import os
import subprocess
import sys
from pathlib import Path

from sugar_lift_py_tests.canonicalizer import blake3_512_of

from sugar_build_witness.witness import (
    build_witness_memento,
    discharge_build_witness,
    run_build_witness,
    witness_body,
)

SCRIPT = """\
import pathlib
import sys

message = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8").strip()
version = pathlib.Path(sys.argv[2]).read_text(encoding="utf-8").strip()
out = pathlib.Path(sys.argv[3])
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(f"demo-lib\\nmessage={message}\\nversion={version}\\n", encoding="utf-8")
"""


def _rpc_process(root: Path) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, "-m", "sugar_build_witness.lift_lsp"],
        cwd=root,
        env=os.environ.copy(),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _rpc_request(
    proc: subprocess.Popen[str], method: str, params: dict, *, msg_id: int = 1
) -> dict:
    assert proc.stdin is not None
    assert proc.stdout is not None
    proc.stdin.write(
        json.dumps({"jsonrpc": "2.0", "id": msg_id, "method": method, "params": params})
        + "\n"
    )
    proc.stdin.flush()
    line = proc.stdout.readline()
    assert line, proc.stderr.read() if proc.stderr is not None else "no RPC response"
    return json.loads(line)


def _close_rpc(proc: subprocess.Popen[str]) -> None:
    _rpc_request(proc, "shutdown", {}, msg_id=999)
    proc.wait(timeout=5)


def _write_project(
    root: Path, *, dist_script: str = SCRIPT, dist_output: str | None = None
) -> None:
    (root / "repo").mkdir()
    (root / "dist").mkdir()
    (root / "src").mkdir()
    (root / "repo" / "configure.py").write_text(SCRIPT, encoding="utf-8")
    (root / "dist" / "configure.py").write_text(dist_script, encoding="utf-8")
    (root / "src" / "message.txt").write_text("hello\n", encoding="utf-8")
    (root / "src" / "version.txt").write_text("1\n", encoding="utf-8")
    expected = "demo-lib\nmessage=hello\nversion=1\n"
    (root / "dist" / "libdemo.txt").write_text(
        dist_output or expected, encoding="utf-8"
    )
    (root / "build-witness.json").write_text(
        json.dumps(
            {
                "kind": "build-witness",
                "repoScript": "repo/configure.py",
                "distributedScript": "dist/configure.py",
                "sources": ["src/message.txt", "src/version.txt"],
                "command": [
                    "{python}",
                    "dist/configure.py",
                    "src/message.txt",
                    "src/version.txt",
                    ".build/libdemo.txt",
                ],
                "outputs": [
                    {
                        "distributed": "dist/libdemo.txt",
                        "rebuilt": ".build/libdemo.txt",
                    }
                ],
                "toolchain": "python-script",
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )


def test_good_build_records_matching_input_and_output_cids(tmp_path):
    _write_project(tmp_path)

    w = run_build_witness(str(tmp_path))
    body = witness_body(w)

    assert w.outcome == "passed"
    assert w.failures == ()
    assert blake3_512_of(body) == w.cid
    assert w.repo_script_cid == w.distributed_script_cid
    assert w.outputs[0]["distributedCid"] == w.outputs[0]["rebuiltCid"]
    assert build_witness_memento(w)["witness_kind"] == "build-witness"


def test_distributed_script_mismatch_is_named_failure(tmp_path):
    _write_project(tmp_path, dist_script=SCRIPT + "\n# injected tarball delta\n")

    w = run_build_witness(str(tmp_path))
    verdict, reason = discharge_build_witness(w.cid, str(tmp_path))

    assert w.outcome == "failed"
    assert any("distributed script CID mismatch" in f for f in w.failures)
    assert verdict == "REFUSED"
    assert "distributed script CID mismatch" in reason


def test_post_mint_distributed_script_tamper_refuses_stale_witness(tmp_path):
    _write_project(tmp_path)
    good = run_build_witness(str(tmp_path))
    script_path = tmp_path / "dist" / "configure.py"
    script_path.write_text(SCRIPT + "\n# post-mint script tamper\n", encoding="utf-8")

    verdict, reason = discharge_build_witness(good.cid, str(tmp_path))

    assert verdict == "REFUSED"
    assert "build witness did not reproduce" in reason
    assert "distributed script CID mismatch" in reason


def test_lift_emits_cid_equalities_with_recomputable_custom_evidence(tmp_path):
    _write_project(tmp_path, dist_script=SCRIPT + "\n# injected tarball delta\n")
    proc = subprocess.Popen(
        [sys.executable, "-m", "sugar_build_witness.lift_lsp"],
        cwd=tmp_path,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    msg = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "lift",
        "params": {"workspace_root": str(tmp_path), "source_paths": ["."]},
    }
    out, err = proc.communicate(json.dumps(msg) + "\n", timeout=10)
    assert proc.returncode == 0, err
    reply = json.loads(out.strip().splitlines()[-1])
    ir = reply["result"]["ir"]
    contracts = [row for row in ir if row.get("kind") == "contract"]
    mementos = [row for row in ir if row.get("kind") == "witness-memento"]

    assert mementos and mementos[0]["witness_kind"] == "build-witness"
    assert contracts
    for row in contracts:
        evidence = row["evidence"]
        assert evidence["proofType"] == "custom"
        certificate = evidence["certificate"]
        assert certificate["tool"] == "build-witness"
        proof_data = json.loads(certificate["proofData"])
        assert proof_data == {
            "kind": "witness-package",
            "packageCid": mementos[0]["witness_cid"],
            "testFiles": [],
            "codeFiles": [],
            "count": 1,
            "passed": 0,
        }
    script_rows = [
        row
        for row in contracts
        if row["name"].endswith("::repo-script-cid-equals-distributed-script-cid")
    ]
    assert len(script_rows) == 1
    script_inv = script_rows[0]["inv"]
    assert script_inv["name"] == "="
    left, right = script_inv["args"]
    assert left["sort"]["name"] == "String"
    assert right["sort"]["name"] == "String"
    assert left["value"] != right["value"]


def test_tampered_distributed_output_is_named_failure(tmp_path):
    _write_project(tmp_path, dist_output="demo-lib\nmessage=owned\nversion=1\n")

    w = run_build_witness(str(tmp_path))
    verdict, reason = discharge_build_witness(w.cid, str(tmp_path))

    assert w.outcome == "failed"
    assert any("output artifact CID mismatch" in f for f in w.failures)
    assert verdict == "REFUSED"
    assert "output artifact CID mismatch" in reason


def test_build_witness_declaration_advertises_enumerate_and_retires_lift(
    tmp_path: Path,
) -> None:
    _write_project(tmp_path)
    proc = _rpc_process(tmp_path)
    try:
        reply = _rpc_request(proc, "sugar.plugin.kit_declaration", {})
        methods = {row["name"] for row in reply["result"]["rpc"]["methods"]}
        assert "sugar.enumerate" in methods
        assert "lift" not in methods
    finally:
        _close_rpc(proc)


def test_build_witness_source_files_seals_authenticated_input_population(
    tmp_path: Path,
) -> None:
    _write_project(tmp_path)
    proc = _rpc_process(tmp_path)
    try:
        reply = _rpc_request(
            proc,
            "sugar.enumerate",
            {"level": "source_files", "workspace_root": str(tmp_path)},
        )
        nodes = reply["result"]["nodes"]
        assert [node["memento"]["file"] for node in nodes] == [
            "build-witness.json",
            "dist/configure.py",
            "dist/libdemo.txt",
            "repo/configure.py",
            "src/message.txt",
            "src/version.txt",
        ]
        assert reply["result"]["gaps"] == []
        assert all(node["memento"]["source_cid"] for node in nodes)
    finally:
        _close_rpc(proc)


def test_build_witness_population_fold_equals_whole_population_legacy(
    tmp_path: Path,
) -> None:
    """#7261 promotion proof: whole legacy == sealed per-file fold."""
    _write_project(tmp_path)
    proc = _rpc_process(tmp_path)
    try:
        legacy = _rpc_request(
            proc,
            "lift",
            {"workspace_root": str(tmp_path), "source_paths": ["."]},
        )["result"]["ir"]
        census = _rpc_request(
            proc,
            "sugar.enumerate",
            {"level": "source_files", "workspace_root": str(tmp_path)},
        )["result"]
        folded: list[dict] = []
        non_empty: list[str] = []
        for file_node in census["nodes"]:
            memento = file_node["memento"]
            universe = _rpc_request(
                proc,
                "sugar.enumerate",
                {
                    "level": "universe",
                    "workspace_root": str(tmp_path),
                    "at": memento,
                },
            )["result"]
            assert universe["gaps"] == []
            if universe["nodes"]:
                non_empty.append(memento["file"])
            folded.extend(node["audit"] for node in universe["nodes"])

        assert len(legacy) == 3, "the promotion control must carry real claim mass"
        assert non_empty == ["build-witness.json"]
        assert folded == legacy
    finally:
        _close_rpc(proc)


def test_build_witness_universe_requires_prepared_population(tmp_path: Path) -> None:
    _write_project(tmp_path)
    proc = _rpc_process(tmp_path)
    try:
        reply = _rpc_request(
            proc,
            "sugar.enumerate",
            {
                "level": "universe",
                "workspace_root": str(tmp_path),
                "at": {"file": "build-witness.json"},
            },
        )
        assert reply["result"]["nodes"] == []
        assert len(reply["result"]["gaps"]) == 1
        assert "prepared source_files census" in reply["result"]["gaps"][0]["reason"]
    finally:
        _close_rpc(proc)


def test_build_witness_universe_refuses_population_drift(tmp_path: Path) -> None:
    _write_project(tmp_path)
    proc = _rpc_process(tmp_path)
    try:
        census = _rpc_request(
            proc,
            "sugar.enumerate",
            {"level": "source_files", "workspace_root": str(tmp_path)},
        )["result"]
        anchor = next(
            node["memento"]
            for node in census["nodes"]
            if node["memento"]["file"] == "build-witness.json"
        )
        (tmp_path / "src" / "message.txt").write_text("changed\n", encoding="utf-8")

        reply = _rpc_request(
            proc,
            "sugar.enumerate",
            {
                "level": "universe",
                "workspace_root": str(tmp_path),
                "at": anchor,
            },
        )["result"]
        assert reply["nodes"] == []
        assert len(reply["gaps"]) == 1
        assert "src/message.txt" in reply["gaps"][0]["reason"]
        assert "sealed source_files census" in reply["gaps"][0]["reason"]
    finally:
        _close_rpc(proc)


def test_build_witness_enumeration_refuses_false_empty_levels(tmp_path: Path) -> None:
    _write_project(tmp_path)
    proc = _rpc_process(tmp_path)
    try:
        link_units = _rpc_request(
            proc,
            "sugar.enumerate",
            {
                "level": "parameter-contract-link-units",
                "workspace_root": str(tmp_path),
            },
        )
        assert link_units["result"] == {"rows": []}

        unknown = _rpc_request(
            proc,
            "sugar.enumerate",
            {"level": "facts", "workspace_root": str(tmp_path)},
        )
        assert unknown["error"]["code"] == -32602
        assert "false zero" in unknown["error"]["message"]
    finally:
        _close_rpc(proc)
