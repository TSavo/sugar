from __future__ import annotations

import pytest

from sugar_lift_py_tests.kit_rpc import (
    AssertionFactDto,
    AssertionSurfaceAuditDto,
    BodyUniverseDto,
    CallsiteFactDto,
    CompilerSelectionDto,
    ComponentPlanMementoDto,
    EffectDto,
    FactoryAuditSummaryDto,
    FactoryWalkCompleteRowDto,
    FactoryWalkStatus,
    ImplicationDto,
    LiftReportPayloadDto,
    PlanAtomDto,
    SourceMementoDto,
    SourceSpanDto,
)
from sugar_lift_py_tests.effect import RuntimeEffect, AppendRuntimeEffect
from sugar_lift_py_tests.effect.runtime_effect import runtime_effect_evidence
from sugar_lift_py_tests.ir import gte, make_var, num
from sugar_lift_py_tests.proofir import (
    ClaimFormula,
    ConstructionSite,
    Derived,
    Provenance,
)
from sugar_lift_py_tests.proofir.scope import claim_formula_from_ir
from sugar_lift_py_tests.proofir.sorts import UnknownSort

CID_A = "blake3-512:" + "a" * 128
CID_B = "blake3-512:" + "b" * 128
CID_C = "blake3-512:" + "c" * 128


def _source_memento() -> SourceMementoDto:
    return SourceMementoDto(
        file="encoder.py",
        span=SourceSpanDto(start_line=1, start_col=0, end_line=2, end_col=20),
        source_cid=CID_A,
        template_cid=CID_B,
        source_function_name="encode_len",
        role="python.body-universe",
        contract_name="encode_len::universe",
        param_names=["data"],
    )


def _post_claim() -> ClaimFormula:
    """``out >= 0`` as a contract's post: a constructed formula with its
    provenance.  The payload writer lowers a claim through its term table
    from the formula it denotes (``ClaimFormula.ir_formula``); a wire-only
    claim (``ClaimFormula.from_rpc``) denotes nothing and is refused by name
    there, never re-serialized from its bytes."""
    return claim_formula_from_ir(
        gte(make_var("out"), num(0)),
        var_sorts={"out": UnknownSort(reason="lift is sort-silent")},
        allowed_vars=("out",),
        provenance=Provenance(
            node_class="FunctionContract",
            construction_site=ConstructionSite(
                path="tests/test_kit_rpc_dtos.py", line=1
            ),
            warrant=Derived(floor_chain=("dto-test",)),
        ),
        role="FunctionContract.post",
    )


def _named_runtime_effect(tmp_path, reason: str) -> RuntimeEffect:
    """A runtime effect as a floor builds one: a named kind, through the one
    evidence bundle, at a real source fragment, over an operand no lift
    decides.  A bare ``RuntimeEffect(reason)`` is unrepresentable."""
    from sugar_lift_python_source.source_oracle import workspace_path_source
    from sugar_source_tree.tree import SourceFile

    path = tmp_path / "encoder.py"
    path.write_text("def store(xs, i, v):\n    xs[i] = v\n")
    function = next(
        SourceFile(workspace_path_source(str(path), root=str(tmp_path))).functions()
    )
    site = function.body[0].fragment
    return AppendRuntimeEffect(
        reason, **runtime_effect_evidence("py.setitem", make_var("i"), site)
    )


def test_a_generic_runtime_effect_is_unrepresentable() -> None:
    with pytest.raises(TypeError):
        RuntimeEffect("write more floor for this effect")  # type: ignore[abstract,call-arg]


def test_python_dtos_emit_rpc_report_shapes(tmp_path) -> None:
    source = _source_memento()
    fact_source = SourceMementoDto(
        file="test_encoder.py",
        span=SourceSpanDto(start_line=5, start_col=4, end_line=5, end_col=38),
        source_cid=CID_C,
        source_function_name="test_encode_len",
        role="python.fact",
        claim_name="test_encoder::test_encode_len::fact",
    )
    callsite_fact = CallsiteFactDto(
        contract_name="test_encoder::test_encode_len::fact",
        callsite="encode_len(b'abc')",
        fact={"kind": "atomic", "name": "=", "args": []},
        source_memento=fact_source,
    )
    assertion_fact = AssertionFactDto(
        contract="test_encoder::test_encode_len::fact",
        kind="warranted",
        claim_count=1,
        source_path="test_encoder.py",
        source_mementos=[fact_source],
    )
    assertion_surface = AssertionSurfaceAuditDto(
        assertion_source="test_encoder::test_encode_len",
        file="test_encoder.py",
        line=5,
        source_status="warranted",
        status="facts-emitted",
        facts=[assertion_fact],
        source_memento=fact_source,
    )
    body_universe = BodyUniverseDto(
        name="encode_len::universe",
        out_binding="out",
        post=_post_claim(),
        source_warrants=[source],
        warranted_by=callsite_fact,
    )
    walk = FactoryWalkCompleteRowDto(
        file="encoder.py",
        line=2,
        requested_role="BodyUniverse",
        ast_kind="Return",
        selected="LenReturnSugar",
        status=FactoryWalkStatus.WARRANTED,
        output="predicate",
        source_memento=source,
    )
    effect = EffectDto(
        name="python.red.effect",
        effect=_named_runtime_effect(tmp_path, "write more floor for this effect"),
        source_memento=source,
    )
    implication = ImplicationDto(
        name="encode_len.post-implies-callsite.pre",
        antecedent="encode_len::universe",
        consequent="test_encoder::test_encode_len::fact",
        antecedent_slot="post",
        consequent_slot="pre",
        prover="python-implications",
    )
    compiler = CompilerSelectionDto(
        name="z3",
        surface="smtlib-z3",
        version="0.1.0",
        command=["sugar-z3-compiler", "--rpc"],
    )
    plan = ComponentPlanMementoDto(
        workspace_root="/workspace",
        plan_atoms=[
            PlanAtomDto(
                role="unit-test-assertions",
                surface="python",
                plugin_name="python-lift",
                version="0.1.0",
                binary_path="/workspace/python-lift-rpc",
                binary_cid=CID_A,
            ),
            compiler.to_plan_atom(),
        ],
        expected_output_cids=[CID_C],
    )
    payload = LiftReportPayloadDto(
        ir=[body_universe],
        source_mementos=[source, fact_source],
        assertion_surface_audits=[assertion_surface],
        factory_walk=[walk],
        plan_mementos=[plan],
        implications=[implication],
        effects=[effect],
    )

    rpc = payload.to_rpc()

    assert rpc["kind"] == "ir-document"
    assert rpc["ir"][0]["sourceWarrants"][0]["kind"] == "source-memento"
    assert rpc["ir"][0]["warrantedBy"]["kind"] == "callsite-fact"
    assert rpc["sourceMementos"][0]["sourceFunctionName"] == "encode_len"
    assert rpc["sourceMementos"][0]["paramNames"] == ["data"]
    assert "body_text" not in rpc["sourceMementos"][0]
    assert "ast_template" not in rpc["sourceMementos"][0]
    assert rpc["assertionSurfaceAudits"][0]["facts"][0]["sourceMemento"]["file"] == (
        "test_encoder.py"
    )
    assert rpc["factoryAuditSummary"]["factoryWalk"][0]["verdict"] == "complete"
    assert rpc["factoryAuditSummary"]["factoryWalk"][0]["sourceMemento"]["file"] == (
        "encoder.py"
    )
    assert rpc["planMementos"][0]["planAtoms"][1]["role"] == "proofir-compiler"
    assert rpc["implications"][0]["antecedentSlot"] == "post"
    assert rpc["effects"][0]["kind"] == "effect"
    assert rpc["effects"][0]["status"] == "runtime-effect"
    assert rpc["effects"][0]["reason"] == "write more floor for this effect"


def test_factory_walk_dto_refuses_inline_side_doors() -> None:
    with pytest.raises(
        ValueError, match="factory walk rows must carry SourceMemento pins"
    ):
        FactoryWalkCompleteRowDto(
            file="encoder.py",
            line=2,
            requested_role="BodyUniverse",
            ast_kind="Return",
            selected="LenReturnSugar",
            status=FactoryWalkStatus.WARRANTED,
            output="predicate",
            source_memento=_source_memento(),
            extra={"term": "return len(data)"},
        ).to_rpc()
