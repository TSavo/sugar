"""Unit tests for the verify-facing Python lift surface (Go-parity, PR #1445).

Covers the three transform halves and the cardinal-sin division guard:
  - to_verify_dialect lowers a `double` contract to `result == (* x 2)` / Int.
  - division ops stay NAMESPACED (uninterpreted) so the bridge is still written
    and wp refuses -> Undecidable, NEVER a false discharge.
  - an unannotated arithmetic body refuses (no `Value`-sorted obligation).
  - leaf harvester lifts `assert double(3) == 6` -> `=(double(3), 6)`.
  - the `contracts` surface gates emission on `@sugar.boundary`/`@sugar`.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
PKG_SRC = ROOT / "implementations/python/sugar-lift-python-source/src"
if str(PKG_SRC) not in sys.path:
    sys.path.insert(0, str(PKG_SRC))

from sugar_lift_python_source.leaf_assertions import harvest_source
from sugar_lift_python_source.canonical import cid_of_json
from sugar_lift_python_source.lifter import lift_source
from sugar_lift_python_source.verify_dialect import (
    VerifyDialectRefusal,
    collect_int_signatures,
    to_verify_dialect,
)
from sugar_lift_python_source.verify_rpc import dispatch, initialize_result, lift_workspace

KIT_DECLARATION_RPC_METHOD = "sugar.plugin.kit_declaration"


def _parse_top_level_toml(path: Path) -> dict[str, object]:
    values: dict[str, object] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("[") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        raw_value = value.strip()
        if raw_value == "true":
            values[key.strip()] = True
        elif raw_value == "false":
            values[key.strip()] = False
        else:
            values[key.strip()] = ast.literal_eval(raw_value)
    return values


def _plugin_entries(path: Path) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line == "[[plugins]]":
            current = {}
            entries.append(current)
            continue
        if current is not None and "=" in line:
            key, value = line.split("=", 1)
            current[key.strip()] = ast.literal_eval(value.strip())
    return entries


def _build_kit_declaration_session() -> str:
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": KIT_DECLARATION_RPC_METHOD},
        {"jsonrpc": "2.0", "id": 3, "method": "shutdown"},
    ]
    return "\n".join(json.dumps(message) for message in messages) + "\n"


def _python_verify_manifest() -> dict[str, object]:
    return _parse_top_level_toml(
        ROOT / "implementations/python/.sugar/lift/python-verify/manifest.toml"
    )


def _fn_contract(source: str, source_path: str = "m.py"):
    result = lift_source(source, source_path)
    for item in result.ir:
        if item.get("kind") == "function-contract" and not str(item["fnName"]).startswith(
            "<source-unit"
        ):
            return item
    raise AssertionError("no function-contract lifted")


def _flatten_and(formula: dict[str, object]) -> list[dict[str, object]]:
    if formula.get("kind") != "and":
        return [formula]
    atoms: list[dict[str, object]] = []
    for operand in formula["operands"]:
        atoms.extend(_flatten_and(operand))
    return atoms


def _call_term(name: str, *args: dict[str, object]) -> dict[str, object]:
    return {"kind": "ctor", "name": name, "args": list(args)}


def _none_term() -> dict[str, object]:
    return {"kind": "ctor", "name": "None", "args": []}


def _atoms_named(formula: dict[str, object], name: str) -> list[dict[str, object]]:
    return [atom for atom in _flatten_and(formula) if atom.get("name") == name]


def _int(value: int) -> dict[str, object]:
    return {"kind": "const", "value": value, "sort": {"kind": "primitive", "name": "Int"}}


def _var(name: str) -> dict[str, object]:
    return {"kind": "var", "name": name}


def _atom(name: str, lhs: dict[str, object], rhs: dict[str, object]) -> dict[str, object]:
    return {"kind": "atomic", "name": name, "args": [lhs, rhs]}


def test_double_lowers_to_dischargeable_core_form():
    source = "def double(x: int) -> int:\n    return x * 2\n"
    contract = _fn_contract(source)
    sorts = collect_int_signatures(source)["double"]
    out = to_verify_dialect(contract, sorts)

    assert out["bridgeSourceSymbol"] == "double"
    assert out["formalSorts"] == [{"kind": "primitive", "name": "Int"}]
    assert out["returnSort"] == {"kind": "primitive", "name": "Int"}
    post = out["post"]
    assert post["name"] == "="
    assert post["args"][0] == {"kind": "var", "name": "result"}
    value = post["args"][1]
    assert value["name"] == "*"  # python:mul normalized to SMT-core
    assert value["args"][0] == {"kind": "var", "name": "x"}
    assert value["args"][1]["value"] == 2


def test_if_raise_body_guard_lowers_to_rust_shaped_precondition_cid():
    source = (
        "def bounded_digit(x: int) -> int:\n"
        "    if x < 2 or x > 36:\n"
        "        raise ValueError('x out of range')\n"
        "    return x\n"
    )
    contract = _fn_contract(source)
    out = to_verify_dialect(contract, collect_int_signatures(source)["bounded_digit"])

    rust_equivalent_pre = {
        "kind": "and",
        "operands": [
            _atom("≥", _var("x"), _int(2)),
            _atom("≤", _var("x"), _int(36)),
        ],
    }
    assert out["pre"] == rust_equivalent_pre
    assert cid_of_json(out["pre"]) == cid_of_json(rust_equivalent_pre)
    assert "panicLoci" not in out
    assert out["effects"] == []


def test_single_if_raise_body_guard_lowers_to_negated_comparison_precondition():
    source = (
        "def at_least_two(x: int) -> int:\n"
        "    if x < 2:\n"
        "        raise ValueError\n"
        "    return x\n"
    )
    contract = _fn_contract(source)
    out = to_verify_dialect(contract, collect_int_signatures(source)["at_least_two"])

    assert out["pre"] == _atom("≥", _var("x"), _int(2))


def test_precondition_guard_residual_does_not_emit_partial_prefix():
    source = (
        "def at_least_two(x: int) -> int:\n"
        "    if helper(x):\n"
        "        raise ValueError\n"
        "    if x < 2:\n"
        "        raise ValueError\n"
        "    return x\n"
    )
    result = lift_source(source, "m.py")
    contract = next(
        item
        for item in result.ir
        if item.get("kind") == "function-contract"
        and not str(item.get("fnName", "")).startswith("<source-unit")
    )

    assert contract["pre"] == {"kind": "atomic", "name": "true", "args": []}
    assert any(item.get("kind") == "precondition-guard-skipped" for item in result.diagnostics)


def test_addition_and_comparison_normalize():
    source = "def f(x: int, y: int) -> int:\n    return x + y\n"
    contract = _fn_contract(source)
    out = to_verify_dialect(contract, collect_int_signatures(source)["f"])
    assert out["post"]["args"][1]["name"] == "+"


def test_floordiv_stays_namespaced_not_refused():
    # CARDINAL SIN GUARD: `//` has no faithful core mapping. It must STAY
    # namespaced (so the bridge is written + wp refuses -> Undecidable), NOT be
    # refused (which would drop the bridge and risk a vacuous-pass fall-through).
    source = "def halve(x: int) -> int:\n    return x // 2\n"
    contract = _fn_contract(source)
    out = to_verify_dialect(contract, collect_int_signatures(source)["halve"])
    assert out["bridgeSourceSymbol"] == "halve"
    assert out["post"]["args"][1]["name"] == "python:floordiv"


def test_truediv_and_mod_stay_namespaced():
    for op, expected in (("/", "python:div"), ("%", "python:mod")):
        source = f"def g(x: int) -> int:\n    return x {op} 2\n"
        contract = _fn_contract(source)
        out = to_verify_dialect(contract, collect_int_signatures(source)["g"])
        assert out["post"]["args"][1]["name"] == expected


def test_unannotated_arithmetic_body_refuses():
    # No `: int` annotation -> a `Value`-sorted obligation z3 cannot discharge.
    # Refuse rather than emit it.
    source = "def double(x):\n    return x * 2\n"
    contract = _fn_contract(source)
    sorts = collect_int_signatures(source)["double"]
    with pytest.raises(VerifyDialectRefusal):
        to_verify_dialect(contract, sorts)


def test_multistatement_body_refuses():
    # A body that is not a single `return <expr>` is not a value-op.
    source = "def f(x: int) -> int:\n    y = x + 1\n    return y * 2\n"
    contract = _fn_contract(source)
    with pytest.raises(VerifyDialectRefusal):
        to_verify_dialect(contract, collect_int_signatures(source)["f"])


def test_leaf_harvester_lifts_call_eq():
    source = "def test_double():\n    assert double(3) == 6\n"
    result = harvest_source(source, "test_m.py")
    assert len(result.ir) == 1
    contract = result.ir[0]
    assert contract["kind"] == "contract"
    assert contract["name"] == "test_double"
    inv = contract["inv"]
    assert inv["name"] == "="
    call = inv["args"][0]
    assert call == {
        "kind": "ctor",
        "name": "double",
        "args": [{"kind": "const", "value": 3, "sort": {"kind": "primitive", "name": "Int"}}],
    }
    assert inv["args"][1]["value"] == 6


def test_leaf_harvester_lifts_is_none_with_substrate_guard():
    source = "def test_missing():\n    assert maybe_none() is None\n"
    result = harvest_source(source, "test_m.py")
    assert result.diagnostics == []
    assert len(result.ir) == 1

    inv = result.ir[0]["inv"]
    call = _call_term("maybe_none")
    assert {
        "kind": "atomic",
        "name": "=",
        "args": [call, _none_term()],
    } in _flatten_and(inv)
    assert {
        "kind": "atomic",
        "name": "is_none",
        "args": [call],
    } in _flatten_and(inv)


def test_leaf_harvester_lifts_is_not_none_with_substrate_guard():
    source = "def test_present():\n    assert maybe_value() is not None\n"
    result = harvest_source(source, "test_m.py")
    assert result.diagnostics == []
    assert len(result.ir) == 1

    inv = result.ir[0]["inv"]
    call = _call_term("maybe_value")
    assert {
        "kind": "atomic",
        "name": "≠",
        "args": [call, _none_term()],
    } in _flatten_and(inv)
    assert {
        "kind": "atomic",
        "name": "is_some",
        "args": [call],
    } in _flatten_and(inv)


def test_leaf_harvester_emits_bare_substrate_guard_heads():
    source = (
        "def test_option_guards():\n"
        "    assert maybe_none() is None\n"
        "    assert maybe_value() is not None\n"
    )
    result = harvest_source(source, "test_m.py")
    guard_names = [
        atom["name"]
        for atom in _flatten_and(result.ir[0]["inv"])
        if atom.get("name") in {"is_none", "is_some"}
    ]

    assert guard_names == ["is_none", "is_some"]
    assert all(":" not in name for name in guard_names)


def test_leaf_harvester_plain_equality_does_not_emit_option_guard():
    source = "def test_count():\n    assert count() == 0\n"
    result = harvest_source(source, "test_m.py")
    assert len(result.ir) == 1

    assert _atoms_named(result.ir[0]["inv"], "is_none") == []
    assert _atoms_named(result.ir[0]["inv"], "is_some") == []


def test_leaf_harvester_eq_none_does_not_emit_option_guard():
    source = "def test_missing():\n    assert maybe_none() == None\n"
    result = harvest_source(source, "test_m.py")
    assert result.diagnostics == []
    assert len(result.ir) == 1

    inv = result.ir[0]["inv"]
    assert inv == {
        "kind": "atomic",
        "name": "=",
        "args": [_call_term("maybe_none"), _none_term()],
    }
    assert _atoms_named(inv, "is_none") == []
    assert _atoms_named(inv, "is_some") == []


def test_leaf_harvester_ne_none_does_not_emit_option_guard():
    source = "def test_present():\n    assert maybe_value() != None\n"
    result = harvest_source(source, "test_m.py")
    assert result.diagnostics == []
    assert len(result.ir) == 1

    inv = result.ir[0]["inv"]
    assert inv == {
        "kind": "atomic",
        "name": "≠",
        "args": [_call_term("maybe_value"), _none_term()],
    }
    assert _atoms_named(inv, "is_none") == []
    assert _atoms_named(inv, "is_some") == []


def test_leaf_harvester_non_none_identity_skips_instead_of_lowering_to_equality():
    source = "def test_alias(left, right):\n    assert left is right\n"
    result = harvest_source(source, "test_m.py")
    assert result.ir == []
    assert result.diagnostics == [
        {
            "kind": "leaf-assertion-skipped",
            "message": "identity comparison is only supported against None",
            "path": "test_m.py",
            "line": 2,
        }
    ]


def test_leaf_harvester_mixed_assertions_guard_only_none_comparison():
    source = (
        "def test_mixed():\n"
        "    assert maybe_none() is None\n"
        "    assert count() == 0\n"
    )
    result = harvest_source(source, "test_m.py")
    assert len(result.ir) == 1

    inv = result.ir[0]["inv"]
    assert len(_atoms_named(inv, "is_none")) == 1
    assert _atoms_named(inv, "is_some") == []
    assert len(_atoms_named(inv, "=")) == 2


def test_leaf_harvester_negative_int_literal():
    source = "def test_halve():\n    assert halve(-7) == -4\n"
    result = harvest_source(source, "test_m.py")
    inv = result.ir[0]["inv"]
    assert inv["args"][0]["args"][0]["value"] == -7
    assert inv["args"][1]["value"] == -4


def test_contracts_surface_gates_on_boundary_declaration(tmp_path):
    # The `contracts` (ir-document) surface emits a function-contract ONLY for
    # functions carrying a `@sugar.boundary`/`@boundary` declaration.
    (tmp_path / "lib.py").write_text(
        "import sugar\n\n\n"
        "@sugar.boundary(concept='concept:mul')\n"
        "def declared(x: int) -> int:\n    return x * 2\n\n\n"
        "def undeclared(x: int) -> int:\n    return x + 1\n"
    )
    ir, _diag = lift_workspace(str(tmp_path), "contracts")
    fn_names = [i["fnName"].rsplit(".", 1)[-1] for i in ir if i.get("kind") == "function-contract"]
    assert "declared" in fn_names
    assert "undeclared" not in fn_names
    declared = next(i for i in ir if i.get("kind") == "function-contract")
    assert declared["opCid"]
    assert declared["authoringKind"] == "boundary"


def test_bare_surface_emits_all_functions(tmp_path):
    (tmp_path / "lib.py").write_text("def double(x: int) -> int:\n    return x * 2\n")
    ir, _diag = lift_workspace(str(tmp_path), "bare")
    fn_names = [i["fnName"].rsplit(".", 1)[-1] for i in ir if i.get("kind") == "function-contract"]
    assert fn_names == ["double"]


def test_verify_rpc_initialize_declares_python_verify_surface():
    result = initialize_result()

    assert result["name"] == "sugar-lift-python-verify"
    assert result["version"] == "0.1.0"
    assert result["protocol_version"] == "sugar-lift/1"
    assert result["dialect"] == "python-verify"
    assert result["capabilities"] == {
        "authoring_surfaces": ["python-verify"],
        "ir_version": "v1.1.0",
        "emits_signed_mementos": False,
    }


def test_checked_in_project_registers_python_verify_contract_surface():
    entries = _plugin_entries(ROOT / "implementations/python/.sugar/config.toml")

    assert {
        "name": "python-verify",
        "kind": "lift",
        "surface": "python-verify",
        "emit": "ir-document",
    } in entries


def test_checked_in_python_verify_manifest_invokes_module_form_and_declares_kit():
    manifest = _python_verify_manifest()

    assert manifest["command"] == [
        "python3",
        "-m",
        "sugar_lift_python_source.verify_rpc",
        "--rpc",
    ]
    assert manifest["working_dir"] == "sugar-lift-python-source/src"

    completed = subprocess.run(
        manifest["command"],
        cwd=ROOT / "implementations/python" / str(manifest["working_dir"]),
        input=_build_kit_declaration_session(),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    responses = [
        json.loads(line) for line in completed.stdout.splitlines() if line.strip()
    ]
    declaration = next(response for response in responses if response.get("id") == 2)
    assert "error" not in declaration, declaration
    assert declaration["result"]["kit"]["id"] == "python-verify"


def test_verify_rpc_kit_declaration_returns_python_verify_surface():
    response = dispatch({"jsonrpc": "2.0", "id": 2, "method": KIT_DECLARATION_RPC_METHOD})

    assert "error" not in response, response
    result = response["result"]
    assert result["kit"] == {
        "id": "python-verify",
        "language": "python",
        "version": "0.1.0",
    }
    required_by_name = {
        method["name"]: method["required"] for method in result["rpc"]["methods"]
    }
    assert required_by_name == {
        "initialize": True,
        KIT_DECLARATION_RPC_METHOD: True,
        "lift": True,
        "shutdown": False,
    }
    assert result["proofResolution"] == {"strategy": "pip"}
    assert result["effectKinds"] == ["panic-freedom"]
    assert result["effectLeaves"] == []
    assert result["guardPredicates"] == [
        {
            "surface": "python-verify",
            "local": "is_some",
            "concept": "concept:panic-freedom.option.some",
        },
        {
            "surface": "python-verify",
            "local": "is_none",
            "concept": "concept:panic-freedom.option.none",
        },
    ]
    assert result["controlCarriers"] == []
    assert result["residueCategories"] == []


def test_verify_rpc_module_command_produces_output():
    completed = subprocess.run(
        [
            "python3",
            "-m",
            "sugar_lift_python_source.verify_rpc",
            "--rpc",
        ],
        cwd=ROOT / "implementations/python/sugar-lift-python-source/src",
        input='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n',
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip(), "verify_rpc module command silently produced no RPC output"
