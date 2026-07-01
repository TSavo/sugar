"""Module-level emission behavior: imports, gap accounting, CID, function shells."""

from __future__ import annotations

from sugar_emit_python_pytest.emitter import EmitPlan, emit


def _op(name: str, *args: dict) -> dict:
    return {"kind": "op", "name": name, "args": list(args)}


def _var(name: str) -> dict:
    return {"kind": "var", "name": name}


def test_emits_function_per_predicate() -> None:
    plan = EmitPlan(
        contract_id="concept:ge",
        function="clamp",
        params=["x", "lo"],
        param_types=["int", "int"],
        predicates=[
            _op("concept:ge", _var("x"), _var("lo")),
            _op("concept:le", _var("x"), _var("hi")),
        ],
    )
    e = emit(plan)
    assert "def test_verifies_ge_0():" in e.source
    assert "def test_verifies_le_1():" in e.source
    assert "assert x >= lo" in e.source
    assert "assert x <= hi" in e.source
    assert e.emitted_predicates == ["ge", "le"]
    assert e.unsupported_predicates == []
    assert e.is_complete
    assert e.path == "test_clamp_contract.py"
    assert e.artifact_cid.startswith("blake3-512:")


def test_unsupported_predicate_recorded_as_gap_not_emitted() -> None:
    plan = EmitPlan(
        function="f",
        predicates=[
            _op("concept:eq", _var("a"), _var("b")),
            _op("concept:mystery", _var("a")),
        ],
    )
    e = emit(plan)
    assert e.path == "test_f_contract.py"
    assert e.emitted_predicates == ["eq"]
    assert e.unsupported_predicates == ["mystery"]
    assert not e.is_complete
    assert "mystery" not in e.source


def test_cid_deterministic_for_same_source() -> None:
    plan = EmitPlan(
        function="lookup",
        predicates=[_op("concept:option-is-some", _var("o"))],
    )
    assert emit(plan).artifact_cid == emit(plan).artifact_cid


def test_pytest_import_only_when_needed() -> None:
    eq_only = emit(
        EmitPlan(function="f", predicates=[_op("concept:eq", _var("a"), _var("b"))])
    )
    assert "import pytest" not in eq_only.source

    with_raises = emit(
        EmitPlan(function="f", predicates=[_op("concept:fallible-err", _var("g"))])
    )
    assert "import pytest" in with_raises.source


def test_from_params_parses_rpc_object() -> None:
    plan = EmitPlan.from_params(
        {
            "contract_id": "concept:eq",
            "function": "f",
            "params": ["a", "b"],
            "param_types": ["int", "int"],
            "predicates": [_op("concept:eq", _var("a"), _var("b"))],
        }
    )
    assert plan.function == "f"
    assert plan.params == ["a", "b"]
    assert len(plan.predicates) == 1


def test_empty_plan_defaults_to_test_function_name() -> None:
    plan = EmitPlan.from_params({})
    assert plan.function == "test"
    e = emit(plan)
    assert e.emitted_predicates == []
    assert not e.is_complete
