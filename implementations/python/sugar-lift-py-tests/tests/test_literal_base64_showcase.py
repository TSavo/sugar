from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
PY_TESTS = ROOT / "implementations/python/sugar-lift-py-tests"


def _run_lift_rpc(project: Path) -> dict:
    env = {
        **os.environ,
        "PYTHONPATH": str(PY_TESTS / "src"),
    }
    request = "\n".join(
        json.dumps(message)
        for message in [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "lift",
                "params": {"workspace_root": str(project), "source_paths": ["."]},
            },
            {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": {}},
        ]
    )

    completed = subprocess.run(
        [sys.executable, "-m", "sugar_lift_py_tests.lift_rpc", "--rpc"],
        input=request + "\n",
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert completed.returncode == 0, completed.stderr
    responses = [json.loads(line) for line in completed.stdout.splitlines() if line.strip()]
    response = next(item for item in responses if item.get("id") == 2)
    assert "error" not in response, response
    return response["result"]


def _write_literal_base64_twin(project: Path, expected: str) -> None:
    project.mkdir()
    (project / "test_base64.py").write_text(
        (
            "def encodeBase64(value):\n"
            '    return "YWJj"\n'
            "\n"
            "def test_encode_base64():\n"
            f'    assert encodeBase64("abc") == "{expected}"\n'
        ),
        encoding="utf-8",
    )


def _single_equality_status(contract: dict) -> str:
    inv = contract["inv"]
    assert inv["kind"] == "atomic"
    assert inv["name"] == "="
    left, right = inv["args"]
    return "sat" if left["value"] == right["value"] else "unsat"


def test_literal_encode_base64_assertion_warrants_function_dig(tmp_path: Path) -> None:
    good = tmp_path / "good"
    bad = tmp_path / "bad"
    _write_literal_base64_twin(good, "YWJj")
    _write_literal_base64_twin(bad, "AAAA")

    good_doc = _run_lift_rpc(good)
    bad_doc = _run_lift_rpc(bad)

    names = [contract["name"] for contract in good_doc["ir"]]
    assert names == [
        "test_base64::encodeBase64::callable",
        "test_base64::test_encode_base64::literal-call-sugar",
    ]
    function_contract, assertion_contract = good_doc["ir"]
    assert function_contract["post"]["name"] == "="
    assert function_contract["post"]["args"][0]["name"] == "out"
    assert function_contract["post"]["args"][1]["value"] == "YWJj"
    assert function_contract["sourceWarrants"][0]["sourceFunctionName"] == "encodeBase64"
    assert function_contract["sourceWarrants"][0]["span"]["start_line"] == 1
    assert assertion_contract["sourceWarrants"][0]["sourceFunctionName"] == (
        "test_encode_base64"
    )
    assert assertion_contract["sourceWarrants"][0]["role"] == "python.literal-call-sugar"
    assert assertion_contract["sourceWarrants"][0]["source_kind"] == "python.ast-stmt"
    assert assertion_contract["warrantedBy"]["contractName"] == function_contract["name"]
    assert assertion_contract["warrantedBy"]["callsite"] == "test_base64.py:5:11"
    assert _single_equality_status(assertion_contract) == "sat"
    assert _single_equality_status(bad_doc["ir"][1]) == "unsat"
    assert good_doc["callEdges"] == [
        {
            "kind": "call-edge",
            "sourceContract": function_contract["name"],
            "targetSymbol": "encodeBase64",
            "targetContract": assertion_contract["name"],
            "callsite": "test_base64.py:5:11",
        }
    ]
    assert [row["selected"] for row in good_doc["factoryAuditSummary"]["factoryWalk"]] == [
        "StringLiteralSugar",
        "FunctionCallSugar",
    ]
    assert good_doc["sourceLedger"]["source_loci"] == 2
    assert good_doc["sourceLedger"]["source_warranted"] == 2
