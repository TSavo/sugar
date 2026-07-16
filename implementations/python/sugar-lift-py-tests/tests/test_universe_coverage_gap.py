from __future__ import annotations

from sugar_lift_py_tests.kit_rpc.factory_walk_row_dto import FactoryWalkRedRowDto
from sugar_lift_py_tests.lift_rpc import lift_file_payload


def _universe_gaps(payload) -> list[FactoryWalkRedRowDto]:
    return [
        row
        for row in payload.factory_walk
        if isinstance(row, FactoryWalkRedRowDto)
        and "callee universe coverage" in row.reason
    ]


def test_universeless_assertion_emits_named_factory_gap() -> None:
    source = "def test_vendor_only():\n    assert vendor_only(1) == 1\n"

    payload = lift_file_payload(source, "vendor_fixture.py")

    # The stated fact remains valid and present; universe visibility is additive.
    assert any(
        contract.name.startswith("vendor_only#euf#c:call:vendor_only")
        and getattr(contract, "inv", None) is not None
        for contract in payload.ir
    )
    assert any(
        edge.get("targetSymbol") == "call:vendor_only" for edge in payload.call_edges
    )

    gaps = _universe_gaps(payload)
    assert len(gaps) == 1
    gap = gaps[0]
    rpc = gap.to_rpc()
    assert gap.file == "vendor_fixture.py"
    assert gap.line == 2
    assert gap.ast_kind == "call:vendor_only"
    assert rpc["verdict"] == "gap"
    assert rpc["gap_kind"] == "Sugar"
    assert rpc["gap_locus"] == "Construction"
    for testimony in (
        "owner=python.factory",
        "no diggable body",
        "no builtin-universe recognizer claim",
        "no bridge-borne contract",
        "no loaded vendor proof",
        "add builtin-universe recognizer",
        "dig body",
        "bridge coverage",
        "load vendor proof",
    ):
        assert testimony in gap.reason


def test_diggable_callee_emits_no_universe_gap() -> None:
    source = (
        "def covered(value):\n"
        "    return value\n"
        "\n"
        "def test_covered():\n"
        "    assert covered(1) == 1\n"
    )

    payload = lift_file_payload(source, "covered_fixture.py")

    assert any(
        getattr(contract, "bridge_source_symbol", None) == "covered"
        and getattr(contract, "post", None) is not None
        for contract in payload.ir
    )
    assert any(
        edge.get("targetSymbol") == "call:covered" for edge in payload.call_edges
    )
    assert _universe_gaps(payload) == []


def test_builtin_covered_callee_emits_no_universe_gap() -> None:
    source = "def test_len(value):\n    assert len(value) >= 0\n"

    payload = lift_file_payload(source, "builtin_covered_fixture.py")

    assert any(edge.get("targetSymbol") == "call:len" for edge in payload.call_edges)
    assert _universe_gaps(payload) == []
