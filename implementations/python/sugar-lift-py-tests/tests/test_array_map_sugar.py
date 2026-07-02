from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from sugar_lift_py_tests.factory import FactoryGap
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.operations import MapOperation, perform_operation

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
    responses = [
        json.loads(line) for line in completed.stdout.splitlines() if line.strip()
    ]
    response = next(item for item in responses if item.get("id") == 2)
    assert "error" not in response, response
    return response["result"]


def _write_twin(project: Path, expected: str) -> None:
    project.mkdir()
    (project / "test_array_map.py").write_text(
        (
            "def test_array_map_sugar():\n"
            f"    assert [1, 2, 3].map(lambda x: x + 1) == {expected}\n"
        ),
        encoding="utf-8",
    )


def _write_native_callable_twin(project: Path, expected: str) -> None:
    project.mkdir()
    (project / "test_array_map.py").write_text(
        (
            "def id(x):\n"
            "    return x\n"
            "\n"
            "def test_array_map_sugar():\n"
            f"    assert list(map(id, range(1, 6))) == {expected}\n"
        ),
        encoding="utf-8",
    )


def _inv_status(contract: dict) -> str:
    inv = contract["inv"]
    assert inv["kind"] == "and"
    equalities = inv["operands"]
    assert all(item["kind"] == "atomic" and item["name"] == "=" for item in equalities)
    values = [
        (item["args"][0]["value"], item["args"][1]["value"]) for item in equalities
    ]
    return "sat" if all(left == right for left, right in values) else "unsat"


def test_array_literal_method_map_sugar_emits_sat_and_unsat_twins(
    tmp_path: Path,
) -> None:
    good = tmp_path / "good"
    bad = tmp_path / "bad"
    _write_twin(good, "[2, 3, 4]")
    _write_twin(bad, "[2, 3, 99]")

    good_doc = _run_lift_rpc(good)
    bad_doc = _run_lift_rpc(bad)

    good_contract = good_doc["ir"][0]
    bad_contract = bad_doc["ir"][0]
    assert _inv_status(good_contract) == "sat"
    assert _inv_status(bad_contract) == "unsat"

    walk = good_doc["factoryAuditSummary"]["factoryWalk"]
    assert [row["selected"] for row in walk] == [
        "ArrayLiteralSugar",
        "LambdaSugar",
        "MapSugar",
    ]
    map_row = walk[-1]
    assert map_row["sourceMemento"]["kind"] == "source-memento"
    assert map_row["sourceMemento"]["file"] == "test_array_map.py"
    assert map_row["sourceMemento"]["sourceFunctionName"] == "test_array_map_sugar"
    assert map_row["sourceMemento"]["source_kind"] == "python.ast-stmt"
    assert map_row["sourceMemento"]["span"]["start_line"] == 2
    assert map_row["emittedFormula"] == good_contract["inv"]
    assert "source" not in walk[-1]
    assert "term" not in walk[-1]
    assert good_contract["sourceWarrants"][0]["kind"] == "source-memento"
    assert good_contract["sourceWarrants"][0]["source_kind"] == "python.ast-stmt"
    assert good_contract["sourceWarrants"][0]["span"]["start_line"] == 2
    assert good_contract["name"].endswith("::array-map-sugar")
    assert good_doc["sourceLedger"] == {
        "source_loci": 1,
        "source_warranted": 1,
        "source_inactive": 0,
        "source_support": 0,
        "source_refused": 0,
        "source_unresolved": 0,
        "unclassified_source": 0,
    }
    assert good_doc["sourceAudits"][0]["role"] == "python.array-map-sugar"
    assert good_doc["sourceAudits"][0]["totals"]["source_warranted"] == 1
    assert good_doc["sourceAudits"][0]["loci"][0]["sourceMemento"]["kind"] == (
        "source-memento"
    )


def test_native_list_map_function_ref_emits_callable_universe(tmp_path: Path) -> None:
    good = tmp_path / "good"
    bad = tmp_path / "bad"
    _write_native_callable_twin(good, "[1, 2, 3, 4, 5]")
    _write_native_callable_twin(bad, "[1, 2, 3, 4, 99]")

    good_doc = _run_lift_rpc(good)
    bad_doc = _run_lift_rpc(bad)

    names = [contract["name"] for contract in good_doc["ir"]]
    assert names == [
        "test_array_map::id::callable",
        "test_array_map::test_array_map_sugar::array-map-sugar",
    ]
    id_contract, good_contract = good_doc["ir"]
    assert id_contract["post"]["name"] == "="
    assert id_contract["post"]["args"][0]["name"] == "out"
    assert id_contract["post"]["args"][1]["name"] == "x"
    assert id_contract["sourceWarrants"][0]["sourceFunctionName"] == "id"
    assert id_contract["sourceWarrants"][0]["span"]["start_line"] == 1
    assert _inv_status(good_contract) == "sat"
    assert _inv_status(bad_doc["ir"][1]) == "unsat"

    walk = good_doc["factoryAuditSummary"]["factoryWalk"]
    assert [row["selected"] for row in walk] == [
        "FunctionRefSugar",
        "RangeSugar",
        "MapBuiltinSugar",
        "ListSugar",
    ]
    assert walk[0]["sourceMemento"]["sourceFunctionName"] == "test_array_map_sugar"
    assert walk[0]["sourceMemento"]["source_kind"] == "python.ast-stmt"
    assert walk[0]["targetFunctionName"] == "id"
    assert walk[-1]["emittedFormula"] == good_contract["inv"]
    assert good_contract["warrantedBy"]["kind"] == "callsite-fact"
    assert good_contract["warrantedBy"]["contractName"] == id_contract["name"]
    assert good_contract["warrantedBy"]["callsite"] == "test_array_map.py:5:16"
    assert good_doc["callEdges"] == [
        {
            "kind": "call-edge",
            "sourceContract": id_contract["name"],
            "targetSymbol": "id",
            "targetContract": good_contract["name"],
            "callsite": "test_array_map.py:5:16",
        }
    ]
    assert good_doc["sourceLedger"]["source_loci"] == 2
    assert good_doc["sourceLedger"]["source_warranted"] == 2


def test_map_operation_missing_floor_names_floor_gap() -> None:
    with pytest.raises(FactoryGap) as raised:
        perform_operation(
            owner="MapSugar",
            blame="x.py:1:0",
            receiver=TermValue(1),
            method_name="map_with",
            operation=MapOperation(mapper=object()),
            ctx=None,
        )

    assert str(raised.value).startswith("write more Floor for this construction: ")
    assert raised.value.info == {
        "owner": "MapSugar",
        "blame": "x.py:1:0",
        "observed": "TermValue",
        "requested": "map_with",
        "fix": "add map_with to TermValue or emit a real effect",
        "gap_kind": "Floor",
        "gap_locus": "construction",
    }
