from __future__ import annotations

from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report


def test_unconstructible_transitive_body_yields_recorded_dig_refusal() -> None:
    report = build_literal_call_report(
        source=(
            "def f(x):\n" "    return x.missing\n" "def t():\n" "    assert f(1) == 1\n"
        ),
        filename="t.py",
        memento_file="t.py",
    )

    refusals = [
        row for row in report.payload.diagnostics if row.get("kind") == "dig-refusal"
    ]
    assert refusals == [
        {
            "kind": "dig-refusal",
            "callee": "f",
            "blame": "t.py:4:11",
            "caught": "FactoryGap",
            "reason": (
                "callsite floor projection refused this callee: "
                "write more Floor for this Construction: owner=AttributeSugar "
                "blame=t.py:2:11 observed=TermValue requested=attribute_with "
                "fix=add attribute_with to TermValue or emit a real effect"
            ),
        }
    ]
