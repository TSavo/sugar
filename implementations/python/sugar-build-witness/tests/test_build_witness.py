# SPDX-License-Identifier: MIT OR Apache-2.0
import json
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


def test_lift_emits_solver_checked_cid_equalities_not_custom_verdict(tmp_path):
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
    assert all("evidence" not in row for row in contracts)
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
