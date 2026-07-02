from __future__ import annotations

import inspect

from sugar_lift_py_tests.factory import literal_call_report
from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report


def _assertion_facts(src: str) -> dict[str | None, list[object]]:
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    out: dict[str | None, list[object]] = {}
    for contract in report.payload.ir:
        if not contract.name.endswith("::assertion"):
            continue
        lhs = contract.inv["args"][0].get("name")
        rhs = contract.inv["args"][1]
        out.setdefault(lhs, []).append(
            rhs.get("name") if rhs.get("kind") == "ctor" else rhs.get("value")
        )
    return out


def _assertion_contracts(src: str):
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    return [contract for contract in report.payload.ir if contract.name.endswith("::assertion")]


def _diagnostics(src: str) -> list[dict]:
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    return report.payload.diagnostics


def test_assert_consumer_reads_callsite_floor_from_the_factory_term() -> None:
    source = inspect.getsource(literal_call_report._lift_assert)

    assert "_construct_callsite(" not in source


def test_transitive_literal_floor_catches_top_level_lie() -> None:
    facts = _assertion_facts(
        "def B():\n"
        "    return 0\n"
        "def A():\n"
        "    return B()\n"
        "def t():\n"
        "    assert A() == 1\n"
    )

    assert 1 in facts["call:A"]
    assert 0 in facts["call:A"]
    assert len(set(facts["call:A"])) > 1


def test_truthful_transitive_literal_floor_stays_consistent() -> None:
    source = (
        "def B():\n"
        "    return 0\n"
        "def A():\n"
        "    return B()\n"
        "def t():\n"
        "    assert A() == 0\n"
    )
    facts = _assertion_facts(source)

    assert facts["call:A"].count(0) == 1
    assert "call:B" in facts["call:A"]
    assert 1 not in facts["call:A"]
    truthful_rows = [
        contract
        for contract in _assertion_contracts(source)
        if contract.inv["args"][1].get("value") == 0
    ]
    assert len(truthful_rows) == 1
    provenance = truthful_rows[0].proofir_provenance
    assert provenance["kind"] == "proofir-provenance"
    assert provenance["nodeClass"] == "EqualityFact"
    assert {warrant["kind"] for warrant in provenance["warrants"]} == {
        "Derived",
        "Stated",
    }


def test_effectful_callee_records_refusal_and_emits_no_floor_fact() -> None:
    source = (
        "def A():\n"
        "    return 1 // 0\n"
        "def t():\n"
        "    assert A() == 1\n"
    )

    assert _assertion_facts(source)["call:A"] == [1]
    refusals = [row for row in _diagnostics(source) if row.get("kind") == "dig-refusal"]
    assert any(
        row.get("callee") == "A"
        and row.get("caught") == "FactoryGap"
        and "force callsite floor" in row.get("reason", "")
        for row in refusals
    )
