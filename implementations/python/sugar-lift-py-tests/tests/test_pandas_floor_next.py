from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver

_PANDAS_POST_CONSTRUCTOR_ATTRIBUTE_SOURCE = (
    "class T:\n"
    "    pass\n"
    "\n"
    "def test_mixin():\n"
    "    t = T()\n"
    "    t.a = 'test'\n"
    "    assert t.a == 'test'\n"
)


def test_pandas_constructor_attribute_assignment_replays_prior_mutation() -> None:
    report = build_literal_call_report(
        source=_PANDAS_POST_CONSTRUCTOR_ATTRIBUTE_SOURCE,
        filename="pandas/tests/base/test_constructors.py",
        memento_file="pandas/tests/base/test_constructors.py",
    )

    assert report is not None
    assert not report.payload.effects
    assert _single_inv(report) == {
        "kind": "atomic",
        "name": "=",
        "args": [_string_const("test"), _string_const("test")],
    }


def test_pandas_constructor_attribute_assignment_lie_reaches_report() -> None:
    report = build_literal_call_report(
        source=_PANDAS_POST_CONSTRUCTOR_ATTRIBUTE_SOURCE.replace(
            "assert t.a == 'test'",
            "assert t.a == 'other'",
        ),
        filename="pandas/tests/base/test_constructors.py",
        memento_file="pandas/tests/base/test_constructors.py",
    )

    assert report is not None
    assert not report.payload.effects
    assert _single_inv(report) == {
        "kind": "atomic",
        "name": "=",
        "args": [_string_const("test"), _string_const("other")],
    }


def test_pandas_constructor_attribute_assignment_flips_through_production(
    tmp_path: Path,
) -> None:
    source = (
        "class T:\n"
        "    pass\n"
        "\n"
        "def A(z):\n"
        "    t = T()\n"
        "    t.a = 'test'\n"
        "    return t.a\n"
        "\n"
        "def test_mixin():\n"
        "    assert A(0) == 'EXPECTED'\n"
    )
    truthful = run_source_through_real_solver(
        tmp_path / "post-constructor-attribute-truth",
        source.replace("EXPECTED", "test"),
    )
    lying = run_source_through_real_solver(
        tmp_path / "post-constructor-attribute-lie",
        source.replace("EXPECTED", "other"),
    )

    assert truthful.verdict == "sat"
    assert lying.verdict == "unsat"
    assert "AttributeAssignSugar" in truthful.selected_sugars
    assert "AttributeSugar" in truthful.selected_sugars
    assert "AttributeAssignSugar" in lying.selected_sugars
    assert "AttributeSugar" in lying.selected_sugars


def _single_inv(report) -> dict:
    contracts = [row for row in report.payload.ir if row.kind == "contract"]
    assert len(contracts) == 1
    return contracts[0].inv


def _string_const(value: str) -> dict:
    return {
        "kind": "const",
        "sort": {"kind": "primitive", "name": "String"},
        "value": value,
    }
