from pathlib import Path

from sugar_lift_py_tests.lift_rpc import _build_lift_coverage, lift_file_payload
from sugar_lift_py_tests.ir import TermTableBuilder
from sugar_lift_py_tests.kit_rpc.source_function_contract_dto import (
    SourceFunctionContractDto,
)


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
