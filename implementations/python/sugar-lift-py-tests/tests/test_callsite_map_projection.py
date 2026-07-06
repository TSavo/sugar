from __future__ import annotations

import pytest

from sugar_lift_py_tests.context.reduce_context import ReduceContext
from sugar_lift_py_tests.factory import FactoryGap
from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.operations import MapOperation, perform_operation


def _term_sig(term: dict) -> object:
    if term.get("kind") == "ctor":
        return (term["name"], tuple(_term_sig(arg) for arg in term["args"]))
    if "value" in term:
        return term["value"]
    return term.get("name")


def _assertion_facts(source: str) -> dict[str | None, list[object]]:
    report = build_literal_call_report(
        source=source, filename="t.py", memento_file="t.py"
    )
    out: dict[str | None, list[object]] = {}
    for contract in report.payload.ir:
        if not contract.name.endswith("::assertion"):
            continue
        lhs = contract.inv["args"][0].get("name")
        out.setdefault(lhs, []).append(_term_sig(contract.inv["args"][1]))
    return out


def _dig_refusals(source: str) -> list[dict]:
    report = build_literal_call_report(
        source=source, filename="t.py", memento_file="t.py"
    )
    return [
        row for row in report.payload.diagnostics if row.get("kind") == "dig-boundary"
    ]


def test_map_body_projects_exact_mapped_sequence_floor() -> None:
    facts = _assertion_facts(
        "def f(xs):\n"
        "    return xs.map(lambda x: x + 1)\n"
        "def t():\n"
        "    assert f([1, 2, 3]) == [2, 3, 4]\n"
    )

    assert facts["call:f"].count(("array", (2, 3, 4))) == 1


def test_map_body_lie_twin_conjoins_wrong_vendor_fact_with_derived_floor() -> None:
    facts = _assertion_facts(
        "def f(xs):\n"
        "    return xs.map(lambda x: x + 1)\n"
        "def t():\n"
        "    assert f([1, 2, 3]) == [2, 3, 99]\n"
    )

    assert ("array", (2, 3, 4)) in facts["call:f"]
    assert ("array", (2, 3, 99)) in facts["call:f"]
    assert len(set(facts["call:f"])) > 1


def test_map_body_projection_refusal_emits_no_partial_sequence_fact() -> None:
    facts = _assertion_facts(
        "def f(xs):\n"
        "    return xs.map(lambda x: (x, missing))\n"
        "def t():\n"
        "    assert f([1, 2]) == [(1, 0), (2, 0)]\n"
    )
    refusals = _dig_refusals(
        "def f(xs):\n"
        "    return xs.map(lambda x: (x, missing))\n"
        "def t():\n"
        "    assert f([1, 2]) == [(1, 0), (2, 0)]\n"
    )

    assert facts["call:f"] == [("array", (("tuple", (1, 0)), ("tuple", (2, 0))))]
    assert any(
        row.get("callee") == "f"
        and row.get("caught") == "FactoryGap"
        and "callsite floor projection refused this callee" in row.get("reason", "")
        for row in refusals
    )


def test_map_operation_non_array_receiver_still_refuses() -> None:
    with pytest.raises(FactoryGap) as exc:
        perform_operation(
            owner="MapProjectionTest",
            blame="t.py:1:0",
            receiver=TermValue(1),
            operation=MapOperation(mapper=object()),
            ctx=ReduceContext.root(owner="projection-test"),
        )

    assert exc.value.info.to_json()["observed"] == "TermValue"
    assert exc.value.info.to_json()["requested"] == "map_with"
