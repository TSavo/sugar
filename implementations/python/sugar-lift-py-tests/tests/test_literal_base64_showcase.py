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
            '    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"\n'
            "    b0 = ord(value[0])\n"
            "    b1 = ord(value[1])\n"
            "    b2 = ord(value[2])\n"
            "    return (\n"
            "        alphabet[b0 >> 2]\n"
            "        + alphabet[((b0 & 3) << 4) | (b1 >> 4)]\n"
            "        + alphabet[((b1 & 15) << 2) | (b2 >> 6)]\n"
            "        + alphabet[b2 & 63]\n"
            "    )\n"
            "\n"
            "def test_encode_base64():\n"
            f'    assert encodeBase64("abc") == "{expected}"\n'
        ),
        encoding="utf-8",
    )


def _eq_name_value(formula: dict) -> tuple[str, object]:
    assert formula["kind"] == "atomic"
    assert formula["name"] == "="
    left, right = formula["args"]
    return left["name"], right["value"]


def _eq_var_const(formula: dict, name: str, value: object) -> None:
    assert formula["kind"] == "atomic"
    assert formula["name"] == "="
    left, right = formula["args"]
    assert left == {"kind": "var", "name": name}
    assert right["value"] == value


def _base64_payload(formula: dict) -> dict:
    assert formula["kind"] == "atomic"
    assert formula["name"] == "str.eq-bv-blocks"
    subject, payload = formula["args"]
    assert subject == {"kind": "var", "name": "out"}
    assert payload["sort"] == {"kind": "primitive", "name": "String"}
    return json.loads(payload["value"])


def _assert_base64_payload(formula: dict) -> None:
    payload = _base64_payload(formula)
    assert payload["input_bytes"] == [97, 98, 99]
    assert payload["vars"] == ["b0", "b1", "b2"]
    assert len(payload["per_char"]) == 4
    assert payload["table"] == [
        ord(ch) for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    ]


def _assert_assertion_inv(contract: dict, expected: str) -> None:
    inv = contract["inv"]
    assert inv["kind"] == "and"
    operands = inv["operands"]
    assert len(operands) == 6
    _eq_var_const(operands[0], "alphabet", "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/")
    _eq_var_const(operands[1], "b0", 97)
    _eq_var_const(operands[2], "b1", 98)
    _eq_var_const(operands[3], "b2", 99)
    _assert_base64_payload(operands[4])
    _eq_var_const(operands[5], "out", expected)


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
        "test_base64::test_encode_base64::literal-call-sugar::assertion",
    ]
    function_contract, assertion_contract = good_doc["ir"]
    assert function_contract["post"]["kind"] == "and"
    post_operands = function_contract["post"]["operands"]
    assert [_eq_name_value(formula) for formula in post_operands[:4]] == [
        ("alphabet", "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"),
        ("b0", 97),
        ("b1", 98),
        ("b2", 99),
    ]
    _assert_base64_payload(post_operands[4])
    assert function_contract["sourceWarrants"][0]["sourceFunctionName"] == "encodeBase64"
    assert function_contract["sourceWarrants"][0]["span"]["start_line"] == 1
    assert assertion_contract["sourceWarrants"][0]["sourceFunctionName"] == (
        "test_encode_base64"
    )
    assert assertion_contract["sourceWarrants"][0]["role"] == "python.literal-call-sugar"
    assert assertion_contract["sourceWarrants"][0]["source_kind"] == "python.ast-stmt"
    assert assertion_contract["warrantedBy"]["contractName"] == function_contract["name"]
    assert assertion_contract["warrantedBy"]["callsite"] == "test_base64.py:14:11"
    _assert_assertion_inv(assertion_contract, "YWJj")
    _assert_assertion_inv(bad_doc["ir"][1], "AAAA")
    assert good_doc["callEdges"] == [
        {
            "kind": "call-edge",
            "sourceContract": function_contract["name"],
            "targetSymbol": "encodeBase64",
            "targetContract": assertion_contract["name"],
            "callsite": "test_base64.py:14:11",
        }
    ]
    assert [row["selected"] for row in good_doc["factoryAuditSummary"]["factoryWalk"]] == [
        "AlphabetLiteralSugar",
        "OrdSugar",
        "OrdSugar",
        "OrdSugar",
        "BitwiseBase64Sugar",
        "FunctionCallSugar",
    ]
    assert [row["requested_role"] for row in good_doc["factoryAuditSummary"]["factoryWalk"]] == [
        "FunctionBodyConstraint",
        "FunctionBodyConstraint",
        "FunctionBodyConstraint",
        "FunctionBodyConstraint",
        "FunctionBodyConstraint",
        "AssertionSurface",
    ]
    assert [
        _eq_name_value(row["emittedFormula"])
        for row in good_doc["factoryAuditSummary"]["factoryWalk"][:4]
    ] == [
        ("alphabet", "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"),
        ("b0", 97),
        ("b1", 98),
        ("b2", 99),
    ]
    _assert_base64_payload(good_doc["factoryAuditSummary"]["factoryWalk"][4]["emittedFormula"])
    assert (
        good_doc["factoryAuditSummary"]["factoryWalk"][5]["emittedFormula"]
        == assertion_contract["inv"]
    )
    assert good_doc["sourceLedger"]["source_loci"] == 2
    assert good_doc["sourceLedger"]["source_warranted"] == 2
