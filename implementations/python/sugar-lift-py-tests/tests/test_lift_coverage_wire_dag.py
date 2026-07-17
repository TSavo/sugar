from pathlib import Path

import pytest

from sugar_lift_py_tests.lift_rpc import _build_lift_coverage, lift_file_payload
from sugar_lift_py_tests.ir import TermTableBuilder, eq, make_var, num
from sugar_lift_py_tests.kit_rpc import BodyUniverseDto
from sugar_lift_py_tests.kit_rpc.source_function_contract_dto import (
    SourceFunctionContractDto,
)
from sugar_lift_py_tests.proofir import ConstructionSite, Derived, Provenance, UniverseMint
from sugar_lift_py_tests.proofir.scope import claim_formula_from_ir
from sugar_lift_py_tests.proofir.sorts import IntSort


def test_coverage_projection_uses_the_payload_term_table_door(tmp_path: Path) -> None:
    source = "def f(x):\n    assert x == 1\n    return x\n"
    path = tmp_path / "demo.py"
    path.write_text(source, encoding="utf-8")
    payload = lift_file_payload(source, "demo.py")

    payload_rpc = payload.to_rpc()
    coverage = _build_lift_coverage(
        root=tmp_path, paths=[path], payload_rpc=payload_rpc
    )

    assert coverage["totals"]["stated"] == 1


def test_source_lifter_contract_terms_enter_the_shared_term_table() -> None:
    contract = SourceFunctionContractDto(
        {
            "kind": "function-contract",
            "fnName": "guarded",
            "pre": {
                "kind": "atomic",
                "name": "=",
                "args": [
                    {"kind": "var", "name": "x"},
                    {
                        "kind": "ctor",
                        "name": "py.len",
                        "args": [{"kind": "var", "name": "xs"}],
                    },
                ],
            },
        }
    )
    table = TermTableBuilder()

    wire = contract.to_rpc_with_term_table(table)

    assert all(arg["kind"] == "term-ref" for arg in wire["pre"]["args"])
    assert len(table.nodes) == 3


def test_body_universe_to_rpc_stays_closed_and_member_declaration_uses_term_refs() -> None:
    """#4406 residual: no bare BodyUniverseDto.to_rpc side door; members emit refs.

    After the payload term-table flip, EqualityFact/UniverseMint/FunctionContract
    to_declaration() still called the banned expanded door. Wire declarations
    must go through the term table; semantic identity may expand locally.
    """
    site = ConstructionSite(path="test_lift_coverage_wire_dag.py", line=1)
    provenance = Provenance(
        node_class="UniverseMint",
        construction_site=site,
        warrant=Derived(floor_chain=("wire-dag",)),
    )
    formula = claim_formula_from_ir(
        eq(make_var("out"), num(0)),
        var_sorts={"out": IntSort()},
        allowed_vars=("out",),
        provenance=provenance,
        role="wire-dag",
    )
    dto = BodyUniverseDto(name="module::wire::assertion", inv=formula)

    with pytest.raises(RuntimeError, match="term-table writer"):
        dto.to_rpc()

    table = TermTableBuilder()
    wire = dto.to_rpc_with_term_table(table)
    assert all(arg["kind"] == "term-ref" for arg in wire["inv"]["args"])
    assert len(table.nodes) == 2  # var out + const 0

    mint = UniverseMint(
        name="module::wire::assertion",
        slot="inv",
        formula=formula,
        provenance=provenance,
    )
    declaration = mint.to_declaration()
    assert all(arg["kind"] == "term-ref" for arg in declaration["inv"]["args"])

    semantic = dto.to_semantic_rpc()
    assert semantic["inv"]["args"][0]["kind"] == "var"
    assert semantic["inv"]["args"][1]["kind"] == "const"
