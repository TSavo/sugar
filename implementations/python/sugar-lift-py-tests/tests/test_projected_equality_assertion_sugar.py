from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report

ROOT = Path(__file__).resolve().parents[4]
PY_TESTS = ROOT / "implementations/python/sugar-lift-py-tests"


def _run_lift_rpc(
    project: Path, *, contract_bindings: list[dict] | None = None
) -> dict:
    env = {
        **os.environ,
        "PYTHONPATH": str(PY_TESTS / "src"),
    }
    params = {"workspace_root": str(project), "source_paths": ["."]}
    if contract_bindings is not None:
        params["contract_bindings"] = contract_bindings
    request = "\n".join(
        json.dumps(message)
        for message in [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            {"jsonrpc": "2.0", "id": 2, "method": "lift", "params": params},
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


def test_projected_equality_lifts_call_result_attribute_fact() -> None:
    report = build_literal_call_report(
        source=(
            "import numpy as np\n"
            "def test_dtype(arr):\n"
            "    assert np.any(arr).dtype == np.bool\n"
        ),
        filename="test_dtype.py",
        memento_file="test_dtype.py",
    )

    assert report is not None
    assert len(report.payload.ir) == 1
    contract = report.payload.ir[0]
    assert contract.name == "test_dtype::test_dtype::assert:3:4::assertion"
    assert (
        contract.source_warrants[0].role == "python.projected-equality-assertion-sugar"
    )
    assert contract.inv == {
        "kind": "atomic",
        "name": "=",
        "args": [
            {
                "kind": "ctor",
                "name": "py.attr",
                "args": [
                    {
                        "kind": "ctor",
                        "name": "call:numpy.any",
                        "args": [{"kind": "var", "name": "arr"}],
                    },
                    {
                        "kind": "const",
                        "sort": {"kind": "primitive", "name": "String"},
                        "value": "dtype",
                    },
                ],
            },
            {
                "kind": "ctor",
                "name": "py.attr",
                "args": [
                    {"kind": "var", "name": "np"},
                    {
                        "kind": "const",
                        "sort": {"kind": "primitive", "name": "String"},
                        "value": "bool",
                    },
                ],
            },
        ],
    }
    assert [row.selected for row in report.payload.factory_walk] == [
        "ProjectedEqualityAssertionSugar"
    ]
    assert report.payload.factory_walk[0].requested_role == "AssertionSurface"


def test_projected_equality_lifts_attribute_to_attribute_fact() -> None:
    report = build_literal_call_report(
        source=(
            "def test_dtype(actual, expected):\n"
            "    assert actual.dtype == expected.dtype\n"
        ),
        filename="test_dtype.py",
        memento_file="test_dtype.py",
    )

    assert report is not None
    fact = report.payload.ir[0].inv
    assert fact["name"] == "="
    assert fact["args"] == [
        {
            "kind": "ctor",
            "name": "py.attr",
            "args": [
                {"kind": "var", "name": "actual"},
                {
                    "kind": "const",
                    "sort": {"kind": "primitive", "name": "String"},
                    "value": "dtype",
                },
            ],
        },
        {
            "kind": "ctor",
            "name": "py.attr",
            "args": [
                {"kind": "var", "name": "expected"},
                {
                    "kind": "const",
                    "sort": {"kind": "primitive", "name": "String"},
                    "value": "dtype",
                },
            ],
        },
    ]


def test_projected_equality_lifts_attribute_to_tuple_fact() -> None:
    report = build_literal_call_report(
        source=("def test_shape(arr):\n" "    assert arr.shape == (1, 1)\n"),
        filename="test_shape.py",
        memento_file="test_shape.py",
    )

    assert report is not None
    contract = report.payload.ir[0]
    assert (
        contract.source_warrants[0].role == "python.projected-equality-assertion-sugar"
    )
    assert contract.inv == {
        "kind": "atomic",
        "name": "=",
        "args": [
            {
                "kind": "ctor",
                "name": "py.attr",
                "args": [
                    {"kind": "var", "name": "arr"},
                    {
                        "kind": "const",
                        "sort": {"kind": "primitive", "name": "String"},
                        "value": "shape",
                    },
                ],
            },
            {
                "kind": "ctor",
                "name": "tuple",
                "args": [
                    {
                        "kind": "const",
                        "sort": {"kind": "primitive", "name": "Int"},
                        "value": 1,
                    },
                    {
                        "kind": "const",
                        "sort": {"kind": "primitive", "name": "Int"},
                        "value": 1,
                    },
                ],
            },
        ],
    }
    assert [row.selected for row in report.payload.factory_walk] == [
        "ProjectedEqualityAssertionSugar"
    ]


def test_projected_equality_keeps_non_constructor_bound_attribute_symbolic() -> None:
    report = build_literal_call_report(
        source=(
            "import numpy as np\n"
            "def test_dtype():\n"
            "    arr = np.array(['a'])\n"
            "    assert arr.dtype == np.str_\n"
        ),
        filename="test_dtype.py",
        memento_file="test_dtype.py",
    )

    assert report is not None
    left = report.payload.ir[0].inv["args"][0]
    assert left["kind"] == "ctor"
    assert left["name"] == "py.attr"
    assert left["args"][0]["kind"] == "var"
    assert left["args"][0]["name"] == "arr"
    assert left["args"][1]["value"] == "dtype"


def test_projected_equality_emits_external_bridge_edge_for_import_without_source() -> (
    None
):
    report = build_literal_call_report(
        source=(
            "import math\n"
            "def test_sqrt(actual):\n"
            "    assert actual.value == math.sqrt(4)\n"
        ),
        filename="test_sqrt.py",
        memento_file="test_sqrt.py",
    )

    assert report is not None
    contract = report.payload.ir[0]
    assert contract.inv == {
        "kind": "atomic",
        "name": "=",
        "args": [
            {
                "kind": "ctor",
                "name": "py.attr",
                "args": [
                    {"kind": "var", "name": "actual"},
                    {
                        "kind": "const",
                        "sort": {"kind": "primitive", "name": "String"},
                        "value": "value",
                    },
                ],
            },
            {
                "kind": "ctor",
                "name": "call:math.sqrt",
                "args": [
                    {
                        "kind": "const",
                        "sort": {"kind": "primitive", "name": "Int"},
                        "value": 4,
                    }
                ],
            },
        ],
    }
    assert report.payload.call_edges == [
        {
            "kind": "call-edge",
            "schemaVersion": "1",
            "sourceContract": contract.name,
            "targetSymbol": "call:math.sqrt",
            "targetContract": None,
            "targetContractCid": None,
            "callSiteLocus": {
                "file": "test_sqrt.py",
                "line": 3,
                "column": 27,
            },
        }
    ]


def test_projected_equality_external_bridge_edge_uses_dependency_binding() -> None:
    report = build_literal_call_report(
        source=(
            "import math\n"
            "def test_sqrt(actual):\n"
            "    assert actual.value == math.sqrt(4)\n"
        ),
        filename="test_sqrt.py",
        memento_file="test_sqrt.py",
        contract_bindings=[
            {
                "name": "native::sqrt::callable",
                "contract_cid": "blake3-512:math-sqrt-contract",
                "target_proof_cid": "blake3-512:math-proof",
                "bridgeSourceSymbol": "call:math.sqrt",
            }
        ],
    )

    assert report is not None
    edge = report.payload.call_edges[0]
    assert edge["targetSymbol"] == "call:math.sqrt"
    assert edge["targetContract"] == "native::sqrt::callable"
    assert edge["targetContractCid"] == "blake3-512:math-sqrt-contract"
    assert edge["targetProofCid"] == "blake3-512:math-proof"


def test_projected_equality_external_bridge_edge_binds_keyword_formal_actuals() -> None:
    report = build_literal_call_report(
        source=(
            "import math\n"
            "def test_round(actual):\n"
            "    assert actual.value == math.floor(x=4)\n"
        ),
        filename="test_round.py",
        memento_file="test_round.py",
        contract_bindings=[
            {
                "name": "native::floor::callable",
                "contract_cid": "blake3-512:floor-contract",
                "target_proof_cid": "blake3-512:math-proof",
                "bridgeSourceSymbol": "call:math.floor",
                "formals": ["x"],
                "has_pre": True,
            }
        ],
    )

    assert report is not None
    edge = report.payload.call_edges[0]
    assert edge["targetSymbol"] == "call:math.floor"
    assert edge["targetContract"] == "native::floor::callable"
    assert edge["targetContractCid"] == "blake3-512:floor-contract"
    assert edge["targetProofCid"] == "blake3-512:math-proof"
    assert edge["callsite"] == {
        "panicSite": False,
        "file": "test_round.py",
        "line": 3,
        "formalActuals": {
            "x": {
                "kind": "const",
                "sort": {"kind": "primitive", "name": "Int"},
                "value": 4,
            },
        },
    }


def test_projected_equality_resolved_post_to_pre_edge_emits_implication() -> None:
    source = (
        "import math\n"
        "def test_sqrt(actual):\n"
        "    assert actual.value == math.sqrt(4)\n"
    )
    first_pass = build_literal_call_report(
        source=source,
        filename="test_sqrt.py",
        memento_file="test_sqrt.py",
    )
    assert first_pass is not None
    source_contract = first_pass.payload.ir[0].name

    report = build_literal_call_report(
        source=source,
        filename="test_sqrt.py",
        memento_file="test_sqrt.py",
        contract_bindings=[
            {
                "name": source_contract,
                "contract_cid": "blake3-512:source-contract",
                "has_post": True,
            },
            {
                "name": "native::sqrt::callable",
                "contract_cid": "blake3-512:math-sqrt-contract",
                "bridgeSourceSymbol": "call:math.sqrt",
                "has_pre": True,
            },
        ],
    )

    assert report is not None
    assert len(report.payload.implications) == 1
    implication = report.payload.implications[0]
    assert implication.antecedent == source_contract
    assert implication.antecedent_slot == "post"
    assert implication.consequent == "native::sqrt::callable"
    assert implication.consequent_slot == "pre"
    assert implication.prover == "python-implications"


def test_projected_equality_resolved_edge_without_target_pre_is_not_implication() -> (
    None
):
    source = (
        "import math\n"
        "def test_sqrt(actual):\n"
        "    assert actual.value == math.sqrt(4)\n"
    )
    first_pass = build_literal_call_report(
        source=source,
        filename="test_sqrt.py",
        memento_file="test_sqrt.py",
    )
    assert first_pass is not None
    source_contract = first_pass.payload.ir[0].name

    report = build_literal_call_report(
        source=source,
        filename="test_sqrt.py",
        memento_file="test_sqrt.py",
        contract_bindings=[
            {
                "name": source_contract,
                "contract_cid": "blake3-512:source-contract",
                "has_post": True,
            },
            {
                "name": "native::sqrt::callable",
                "contract_cid": "blake3-512:math-sqrt-contract",
                "bridgeSourceSymbol": "call:math.sqrt",
                "has_pre": False,
            },
        ],
    )

    assert report is not None
    assert report.payload.call_edges[0]["targetContract"] == "native::sqrt::callable"
    assert report.payload.implications == []


def test_projected_equality_direct_callsite_edge_binds_keyword_formal_actuals() -> None:
    report = build_literal_call_report(
        source=(
            "import math\n" "def test_floor():\n" "    assert math.floor(x=4) == 4\n"
        ),
        filename="test_floor.py",
        memento_file="test_floor.py",
        contract_bindings=[
            {
                "name": "native::floor::callable",
                "contract_cid": "blake3-512:floor-contract",
                "target_proof_cid": "blake3-512:math-proof",
                "bridgeSourceSymbol": "call:math.floor",
                "formals": ["x"],
                "has_pre": True,
            }
        ],
    )

    assert report is not None
    edge = report.payload.call_edges[0]
    assert edge["targetSymbol"] == "call:math.floor"
    assert edge["targetContract"] == "native::floor::callable"
    assert edge["targetContractCid"] == "blake3-512:floor-contract"
    assert edge["targetProofCid"] == "blake3-512:math-proof"
    assert edge["callsite"] == {
        "panicSite": False,
        "file": "test_floor.py",
        "line": 3,
        "formalActuals": {
            "x": {
                "kind": "const",
                "sort": {"kind": "primitive", "name": "Int"},
                "value": 4,
            },
        },
    }


def test_lift_rpc_bindings_backed_pass_returns_implication_consumer_payload(
    tmp_path: Path,
) -> None:
    source = (
        "import math\n"
        "def test_sqrt(actual):\n"
        "    assert actual.value == math.sqrt(4)\n"
    )
    project = tmp_path / "project"
    project.mkdir()
    (project / "test_sqrt.py").write_text(source, encoding="utf-8")
    first_pass = build_literal_call_report(
        source=source,
        filename="test_sqrt.py",
        memento_file="test_sqrt.py",
    )
    assert first_pass is not None
    source_contract = first_pass.payload.ir[0].name

    result = _run_lift_rpc(
        project,
        contract_bindings=[
            {
                "name": source_contract,
                "contract_cid": "blake3-512:source-contract",
                "has_post": True,
            },
            {
                "name": "native::sqrt::callable",
                "contract_cid": "blake3-512:math-sqrt-contract",
                "bridgeSourceSymbol": "call:math.sqrt",
                "has_pre": True,
            },
        ],
    )

    assert result["ir"] == []
    assert result["callEdges"][0]["targetContract"] == "native::sqrt::callable"
    assert result["implications"] == [
        {
            "name": f"{source_contract}.post-implies-native::sqrt::callable.pre",
            "antecedent": source_contract,
            "antecedentSlot": "post",
            "consequent": "native::sqrt::callable",
            "consequentSlot": "pre",
            "prover": "python-implications",
        }
    ]


def test_lift_rpc_producer_pass_includes_source_guard_preconditions(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "guarded.py").write_text(
        "def guarded(x):\n"
        "    if x < 2:\n"
        "        raise ValueError('too small')\n"
        "    return x\n",
        encoding="utf-8",
    )
    (project / "test_guarded.py").write_text(
        "from guarded import guarded\n\n"
        "def test_guarded():\n"
        "    assert guarded(5) == 5\n",
        encoding="utf-8",
    )

    result = _run_lift_rpc(project)

    guarded_contract = next(
        (
            item
            for item in result["ir"]
            if item.get("kind") == "function-contract"
            and item.get("fnName") == "guarded.guarded"
        ),
        None,
    )
    assert guarded_contract is not None, result["ir"]
    assert guarded_contract.get("bridgeSourceSymbol") == "guarded.guarded"
    assert "post" not in guarded_contract
    assert guarded_contract.get("bodyDischargeEligible") is False
    assert guarded_contract["pre"] == {
        "kind": "atomic",
        "name": "≥",
        "args": [
            {"kind": "var", "name": "x"},
            {
                "kind": "const",
                "value": 2,
                "sort": {"kind": "primitive", "name": "Int"},
            },
        ],
    }
    assert result["callEdges"] == [
        {
            "kind": "call-edge",
            "schemaVersion": "1",
            "sourceContract": "guarded.guarded#euf#c:call:guarded.guarded(i:5)::assertion",
            "targetSymbol": "call:guarded.guarded",
            "targetContract": None,
            "targetContractCid": None,
            "callSiteLocus": {"file": "test_guarded.py", "line": 4, "column": 11},
        }
    ]


def test_projected_equality_lifts_fstring_rhs_attribute() -> None:
    report = build_literal_call_report(
        source=(
            "def test_dtype(arr, dt):\n"
            "    assert arr.dtype == dtype(f'{dt}1').itemsize\n"
        ),
        filename="test_dtype.py",
        memento_file="test_dtype.py",
    )

    assert report is not None
    assert report.payload.ir[0].inv == {
        "kind": "atomic",
        "name": "=",
        "args": [
            {
                "kind": "ctor",
                "name": "py.attr",
                "args": [
                    {"kind": "var", "name": "arr"},
                    {
                        "kind": "const",
                        "sort": {"kind": "primitive", "name": "String"},
                        "value": "dtype",
                    },
                ],
            },
            {
                "kind": "ctor",
                "name": "py.attr",
                "args": [
                    {
                        "kind": "ctor",
                        "name": "call:dtype",
                        "args": [
                            {
                                "kind": "ctor",
                                "name": "py.fstring",
                                "args": [
                                    {"kind": "var", "name": "dt"},
                                    {
                                        "kind": "const",
                                        "sort": {
                                            "kind": "primitive",
                                            "name": "String",
                                        },
                                        "value": "1",
                                    },
                                ],
                            }
                        ],
                    },
                    {
                        "kind": "const",
                        "sort": {"kind": "primitive", "name": "String"},
                        "value": "itemsize",
                    },
                ],
            },
        ],
    }


def test_projected_equality_rhs_runtime_effect_stays_typed_effect() -> None:
    report = build_literal_call_report(
        source=(
            "def test_values(arr, xs):\n" "    assert arr.values == [x for x in xs]\n"
        ),
        filename="test_values.py",
        memento_file="test_values.py",
    )

    assert report is not None
    assert report.payload.ir == []
    assert len(report.payload.effects) == 1
    effect = report.payload.effects[0]
    assert isinstance(effect.effect, RuntimeEffect)
    assert "list comprehension runtime boundary" in effect.effect.reason
    assert "runtime iterable `Name`" in effect.effect.reason
    assert [row.selected for row in report.payload.factory_walk] == [
        "ProjectedEqualityAssertionSugar"
    ]
