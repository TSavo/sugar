from __future__ import annotations

from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report


def _assertion_facts(source: str) -> dict[str | None, list[object]]:
    report = build_literal_call_report(
        source=source, filename="t.py", memento_file="t.py"
    )
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


def _dig_refusals(source: str) -> list[dict]:
    report = build_literal_call_report(
        source=source, filename="t.py", memento_file="t.py"
    )
    return [
        row for row in report.payload.diagnostics if row.get("kind") == "dig-refusal"
    ]


def test_try_callee_routes_handled_raise_to_projected_floor() -> None:
    source = (
        "def f(x):\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except ValueError:\n"
        "        return 9\n"
        "def t():\n"
        "    assert f(5) == 9\n"
    )

    facts = _assertion_facts(source)

    assert facts["call:f"].count(9) == 2
    assert _dig_refusals(source) == []


def test_try_callee_unhandled_raise_records_refusal_without_floor_fact() -> None:
    source = (
        "def f(x):\n"
        "    try:\n"
        "        raise KeyError\n"
        "    except ValueError:\n"
        "        return 9\n"
        "def t():\n"
        "    assert f(5) == 9\n"
    )

    facts = _assertion_facts(source)
    refusals = _dig_refusals(source)

    assert facts["call:f"] == [9]
    assert any(
        row.get("callee") == "f"
        and row.get("caught") == "FactoryGap"
        and "callsite floor projection refused this callee" in row.get("reason", "")
        for row in refusals
    )
