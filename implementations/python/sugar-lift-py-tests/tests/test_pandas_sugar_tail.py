from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path

from factory_reduce import reduce_value

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext, ReduceContext
from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report
from sugar_lift_py_tests.floor import (
    ImportAliasValue,
    StringValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.idd.sugar_witness_instruments import evaluate_seed_witnesses
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.outcome import Incomplete
from sugar_lift_py_tests.sugar.witnesses import (
    EffectWitnessSource,
    SugarRedEffectWitnessPair,
    TypedRedEffectExpectation,
)
from sugar_lift_py_tests.temporal import TemporalContext


def _term_outcome(expr: str, binds: dict | None = None):
    temporal = TemporalContext.empty()
    for name, value in (binds or {}).items():
        temporal = temporal.bind_value(name, value)
    build_ctx = FactoryBuildContext(
        filename="pandas_tail.py",
        catalog=default_catalog(),
        temporal=temporal,
    )
    audit_sink: list[dict[str, object]] = []
    build_ctx = replace(build_ctx, audit_sink=audit_sink)
    body = build_ctx.build_body(ast.parse(expr, mode="eval").body, SugarRole.TERM)
    outcome = body.reduce(ReduceContext(temporal=temporal))
    selected = tuple(
        row["selected"] for row in audit_sink if isinstance(row.get("selected"), str)
    )
    return outcome, selected


def _assertion_outcome(source: str, binds: dict | None = None):
    temporal = TemporalContext.empty()
    for name, value in (binds or {}).items():
        temporal = temporal.bind_value(name, value)
    build_ctx = FactoryBuildContext(
        filename="pandas_tail.py",
        catalog=default_catalog(),
        temporal=temporal,
    )
    body = build_ctx.build_body(ast.parse(source).body[0], SugarRole.ASSERTION)
    return body.reduce(ReduceContext(temporal=temporal))


def test_pandas_unary_not_term_is_typed_red_effect() -> None:
    outcome, selected = _term_outcome(
        "not closed",
        {"closed": SymbolicValue(make_var("closed"))},
    )

    assert "UnaryOpSugar" in selected
    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, RuntimeEffect)
    assert "value-position unary not runtime boundary" in outcome.effect.reason
    assert "owner=UnaryOpSugar" in outcome.effect.reason
    assert "pandas_tail.py:1:0" in outcome.effect.reason


def test_pandas_unary_not_typed_red_witness_rejects_wrong_effect(
    tmp_path: Path,
) -> None:
    right_effect = TypedRedEffectExpectation(
        effect_class="RuntimeEffect",
        reason_needle="value-position unary not runtime boundary",
        blame_needle="test_witness.py:2:11",
    )
    wrong_effect = TypedRedEffectExpectation(
        effect_class="RuntimeEffect",
        reason_needle="import alias runtime boundary",
        blame_needle="test_witness.py:2:11",
    )
    seed = SugarRedEffectWitnessPair(
        name="pandas_unary_not_term_runtime_effect",
        owner_sugar="UnaryOpSugar",
        family="pandas-sugar-tail",
        truthful=EffectWitnessSource(
            source=("def A(closed):\n" "    return not closed\n"),
            expectation=right_effect,
            expected_match=True,
        ),
        lying=EffectWitnessSource(
            source=("def A(closed):\n" "    return not closed\n"),
            expectation=wrong_effect,
            expected_match=False,
        ),
    )

    report = evaluate_seed_witnesses((seed,), tmp_path / "unary-not-right-red")

    assert report.is_zero

    wrong_truth = replace(
        seed,
        truthful=replace(seed.truthful, expectation=wrong_effect, expected_match=True),
    )
    bad_report = evaluate_seed_witnesses(
        (wrong_truth,), tmp_path / "unary-not-wrong-red"
    )

    assert bad_report.witness_triples_failing == 1
    assert [
        (failure.seed, failure.variant, failure.axis)
        for failure in bad_report.triple_failures
    ] == [
        (
            "pandas_unary_not_term_runtime_effect",
            "truthful",
            "typed-red-effect",
        )
    ]


def test_pandas_literal_call_nested_call_arg_becomes_typed_red_effect() -> None:
    report = build_literal_call_report(
        source=(
            "import numpy as np\n"
            "\n"
            "class BlockPlacement:\n"
            "    def __init__(self, value):\n"
            "        self.value = value\n"
            "    def add(self, other):\n"
            "        return other\n"
            "\n"
            "def test_blockplacement_add():\n"
            "    bpl = BlockPlacement(slice(0, 5))\n"
            "    assert list(bpl.add(np.arange(5, 0, -1))) == [5, 5, 5, 5, 5]\n"
        ),
        filename="tests/internals/test_internals.py",
        memento_file="tests/internals/test_internals.py",
    )

    assert report is not None
    red_rows = [
        row for row in report.payload.factory_walk if row.status == "runtime-effect"
    ]
    assert len(red_rows) == 1
    row = red_rows[0]
    assert row.selected == "CallsiteArgRuntimeEffect"
    assert row.requested_role == "CallsiteArg"
    assert row.ast_kind == "Call"
    assert "callsite argument runtime boundary" in row.reason
    assert "AddSugar operand must reduce to TermValue" in row.reason


def test_pandas_literal_call_nested_call_arg_effect_is_not_green() -> None:
    report = build_literal_call_report(
        source=(
            "import numpy as np\n"
            "\n"
            "class BlockPlacement:\n"
            "    def __init__(self, value):\n"
            "        self.value = value\n"
            "    def add(self, other):\n"
            "        return other\n"
            "\n"
            "def test_blockplacement_add():\n"
            "    bpl = BlockPlacement(slice(0, 5))\n"
            "    assert list(bpl.add(np.arange(5, 0, -1))) == [5, 5, 5, 5, 5]\n"
        ),
        filename="tests/internals/test_internals.py",
        memento_file="tests/internals/test_internals.py",
    )

    assert report is not None
    assert not report.payload.ir
    assert len(report.payload.effects) == 1
    assert (
        "callsite argument runtime boundary" in report.payload.effects[0].effect.reason
    )


def test_pandas_bound_string_format_method_uses_string_floor() -> None:
    value = reduce_value(
        "href.format('text')",
        {"href": StringValue('<a href="{0}" target="_blank">{0}</a>')},
    )

    assert value == StringValue('<a href="text" target="_blank">text</a>')


def test_pandas_bound_string_format_method_discriminates_wrong_value() -> None:
    value = reduce_value(
        "href.format('text')",
        {"href": StringValue('<a href="{0}" target="_blank">{0}</a>')},
    )

    assert value == StringValue('<a href="text" target="_blank">text</a>')
    assert value != StringValue('<a href="other" target="_blank">other</a>')


def test_pandas_import_alias_membership_is_typed_red_effect() -> None:
    outcome = _assertion_outcome(
        "assert closed in VALID_CLOSED",
        {
            "closed": SymbolicValue(make_var("closed")),
            "VALID_CLOSED": ImportAliasValue(
                name="pandas._typing.IntervalClosedType",
                bound_name="VALID_CLOSED",
            ),
        },
    )

    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, RuntimeEffect)
    assert "import alias runtime boundary" in outcome.effect.reason
    assert "contains membership over imported module binding" in outcome.effect.reason
    assert "VALID_CLOSED -> pandas._typing.IntervalClosedType" in outcome.effect.reason


def test_pandas_import_alias_membership_routes_report_to_typed_effect() -> None:
    report = build_literal_call_report(
        source=(
            "from pandas._typing import IntervalClosedType as VALID_CLOSED\n"
            "\n"
            "def test_closed(closed):\n"
            "    assert closed in VALID_CLOSED\n"
        ),
        filename="pandas/core/arrays/arrow/extension_types.py",
        memento_file="pandas/core/arrays/arrow/extension_types.py",
    )

    assert report is not None
    assert not report.payload.ir
    assert len(report.payload.effects) == 1
    effect = report.payload.effects[0].effect
    assert isinstance(effect, RuntimeEffect)
    assert "import alias runtime boundary" in effect.reason
    assert "contains membership over imported module binding" in effect.reason


def test_pandas_array_literal_negative_index_uses_python_sequence_floor() -> None:
    value = reduce_value("[1, 2][-1]")

    assert value == TermValue(2)


def test_pandas_array_literal_negative_index_flips_through_production() -> None:
    source = (
        "def test_array_negative_index():\n"
        "    values = [1, 2]\n"
        "    assert values[-1] == EXPECTED\n"
    )
    truthful = build_literal_call_report(
        source=source.replace("EXPECTED", "2"),
        filename="pandas/tests/config/test_config.py",
        memento_file="pandas/tests/config/test_config.py",
    )
    lying = build_literal_call_report(
        source=source.replace("EXPECTED", "1"),
        filename="pandas/tests/config/test_config.py",
        memento_file="pandas/tests/config/test_config.py",
    )

    assert truthful is not None
    assert lying is not None
    assert _first_contract_inv(truthful) == {
        "kind": "atomic",
        "name": "=",
        "args": [_int_const(2), _int_const(2)],
    }
    assert _first_contract_inv(lying) == {
        "kind": "atomic",
        "name": "=",
        "args": [_int_const(2), _int_const(1)],
    }


def _int_const(value: int) -> dict:
    return {
        "kind": "const",
        "sort": {"kind": "primitive", "name": "Int"},
        "value": value,
    }


def _first_contract_inv(report) -> dict:
    contracts = [row for row in report.payload.ir if row.kind == "contract"]
    assert contracts
    return contracts[0].inv
