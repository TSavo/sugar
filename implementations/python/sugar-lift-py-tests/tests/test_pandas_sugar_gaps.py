from __future__ import annotations

import ast
import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext
from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.factory.block import Block
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report
from sugar_lift_py_tests.floor import (
    ArrayLiteral,
    BoolValue,
    CallSiteValue,
    FloorValue,
    ImportAliasValue,
    StringValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.idd.sugar_witness_instruments import evaluate_seed_witnesses
from sugar_lift_py_tests.ir import ctor, make_var
from sugar_lift_py_tests.outcome import Complete, Incomplete, complete_value
from sugar_lift_py_tests.sugar.compare_term_sugar import CompareTermSugar
from sugar_lift_py_tests.sugar.generator_exp_sugar import GeneratorExpSugar
from sugar_lift_py_tests.sugar.named_expr_sugar import NamedExprSugar
from sugar_lift_py_tests.sugar.tuple_unpack_assign_sugar import TupleUnpackAssignSugar
from sugar_lift_py_tests.sugar.witnesses import (
    EffectWitnessSource,
    SugarRedEffectWitnessPair,
    TypedRedEffectExpectation,
)
from sugar_lift_py_tests.sugar_body import SugarBody
from sugar_lift_py_tests.temporal import TemporalContext
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver
from sugar_lift_py_tests.witness_harness import _ensure_sugar_bin, _stage_cli_project


def _term_outcome(expr: str, binds: dict[str, FloorValue] | None = None):
    audit_sink: list[dict[str, object]] = []
    ctx = FactoryBuildContext(
        filename="pandas_gap.py",
        catalog=default_catalog(),
        audit_sink=audit_sink,
    )
    temporal = TemporalContext.empty()
    for name, value in (binds or {}).items():
        temporal = temporal.bind_value(name, value)
    ctx = replace(ctx, temporal=temporal)
    body = ctx.build_body(ast.parse(expr, mode="eval").body, SugarRole.TERM)
    return body.reduce(ctx), tuple(
        row["selected"] for row in audit_sink if isinstance(row.get("selected"), str)
    )


def _block_outcome(body_source: str, binds: dict[str, FloorValue] | None = None):
    audit_sink: list[dict[str, object]] = []
    ctx = FactoryBuildContext(
        filename="pandas_gap.py",
        catalog=default_catalog(),
        audit_sink=audit_sink,
    )
    temporal = TemporalContext.empty()
    for name, value in (binds or {}).items():
        temporal = temporal.bind_value(name, value)
    ctx = replace(ctx, temporal=temporal)
    function = ast.parse(f"def f():\n{body_source}").body[0]
    block = Block.of(function.body)  # type: ignore[attr-defined]
    result = build_node(
        block, filename="pandas_gap.py", role=SugarRole.STATEMENT, ctx=ctx
    )
    outcome = SugarBody(
        sugar=result.sugar,
        role=SugarRole.STATEMENT,
        audit_row=result.audit_row,
    ).reduce(ctx)
    return outcome, tuple(
        row["selected"] for row in audit_sink if isinstance(row.get("selected"), str)
    )


def _assert_production_pair(
    tmp_path: Path,
    *,
    name: str,
    truthful: str,
    lying: str,
    selected: tuple[str, ...],
) -> None:
    truthful_result = run_source_through_real_solver(
        tmp_path / f"{name}-truth", truthful
    )
    lying_result = run_source_through_real_solver(tmp_path / f"{name}-lie", lying)

    assert truthful_result.verdict == "sat"
    assert lying_result.verdict == "unsat"
    for sugar in selected:
        assert sugar in truthful_result.selected_sugars
        assert sugar in lying_result.selected_sugars


def test_pandas_array_literal_dict_element_is_typed_red_effect() -> None:
    outcome, selected = _term_outcome("[{'a': 1}]")

    assert "ArrayLiteralSugar" in selected
    assert "DictSugar" in selected
    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, RuntimeEffect)
    assert "array literal non-FOL element runtime boundary" in outcome.effect.reason
    assert "DictLiteralValue is a support carrier" in outcome.effect.reason
    assert "pandas_gap.py:1:1" in outcome.effect.reason


def test_symbolic_attribute_assignment_is_typed_runtime_effect() -> None:
    outcome, selected = _block_outcome(
        "    x.flags = 1\n",
        binds={"x": SymbolicValue(make_var("x"))},
    )

    assert "AttributeAssignSugar" in selected
    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, RuntimeEffect)
    assert "attribute assignment runtime boundary" in outcome.effect.reason
    assert "symbolic receiver" in outcome.effect.reason
    assert "pandas_gap.py:2:4" in outcome.effect.reason


def test_import_alias_attribute_assignment_is_typed_runtime_effect() -> None:
    outcome, selected = _block_outcome(
        "    np.foo = 1\n",
        binds={"np": ImportAliasValue(name="numpy", bound_name="np")},
    )

    assert "AttributeAssignSugar" in selected
    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, RuntimeEffect)
    assert "import alias runtime boundary" in outcome.effect.reason
    assert "`np.foo = ...`" in outcome.effect.reason
    assert "replacement=ImportedModuleAttributeAssignEffect" in outcome.effect.reason
    assert "pandas_gap.py:2:4" in outcome.effect.reason


def test_pandas_symbolic_subscript_assignment_is_typed_runtime_effect() -> None:
    outcome, selected = _block_outcome(
        "    xs[0] = 1\n",
        binds={"xs": SymbolicValue(make_var("xs"))},
    )

    assert "SubscriptAssignSugar" in selected
    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, RuntimeEffect)
    assert "subscript assignment runtime boundary" in outcome.effect.reason
    assert "symbolic receiver" in outcome.effect.reason
    assert "pandas_gap.py:2:4" in outcome.effect.reason


def test_pandas_unary_callsite_without_body_is_typed_runtime_effect() -> None:
    outcome, selected = _term_outcome(
        "-delta",
        binds={
            "delta": CallSiteValue(
                target_name="Timedelta",
                arg_values=(),
                parameters=(),
                term=ctor("call:Timedelta", ()),
                body=None,
            )
        },
    )

    assert "UnaryOpSugar" in selected
    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, RuntimeEffect)
    assert "unary operator runtime boundary" in outcome.effect.reason
    assert "callsite value" in outcome.effect.reason
    assert "Timedelta" in outcome.effect.reason
    assert "pandas_gap.py:1:0" in outcome.effect.reason


def test_pandas_unary_callsite_body_reduces_through_existing_floor() -> None:
    class _ReturnSevenSugar:
        def desugar(self, ctx):
            del ctx
            return Complete(TermValue(7))

    outcome, selected = _term_outcome(
        "-delta",
        binds={
            "delta": CallSiteValue(
                target_name="constant_delta",
                arg_values=(),
                parameters=(),
                term=ctor("call:constant_delta", ()),
                body=SugarBody(_ReturnSevenSugar(), SugarRole.TERM),
            )
        },
    )

    assert "UnaryOpSugar" in selected
    assert complete_value(outcome, owner="unary callsite body") == TermValue(-7)


def test_pandas_py_invert_termvalue_uses_python_integer_floor() -> None:
    outcome, selected = _term_outcome("~x", {"x": TermValue(1)})

    assert "UnaryOpSugar" in selected
    assert complete_value(outcome, owner="py.invert term") == TermValue(-2)


@pytest.mark.parametrize(
    ("expr", "expected"),
    [
        ("~x", -2),
        ("-x", -1),
        ("+x", 1),
    ],
)
def test_pandas_boolvalue_unary_ops_use_python_integer_floor(
    expr: str, expected: int
) -> None:
    outcome, selected = _term_outcome(expr, {"x": BoolValue(True)})

    assert "UnaryOpSugar" in selected
    assert complete_value(outcome, owner="bool unary term") == TermValue(expected)


def test_pandas_function_universe_with_module_global_refuses_before_proofir_scope() -> (
    None
):
    report = build_literal_call_report(
        source=(
            "import os\n\n"
            "def getsize(filename):\n"
            "    return os.stat(filename).st_size\n\n"
            "def test_size():\n"
            "    assert getsize('example.html') == 1\n"
        ),
        filename="pandas/tests/io/test_html.py",
        memento_file="pandas/tests/io/test_html.py",
    )

    assert report is not None
    dig_refusals = [
        row
        for row in report.payload.diagnostics
        if isinstance(row, dict) and row.get("kind") == "dig-refusal"
    ]
    matching = [
        row
        for row in dig_refusals
        if row.get("callee") == "getsize"
        and "open non-formal variable(s): os" in str(row.get("reason"))
    ]
    assert len(matching) == 1
    refusal = matching[0]
    assert refusal["callee"] == "getsize"
    assert refusal["caught"] == "ValueError"
    assert "open non-formal variable(s): os" in refusal["reason"]
    assert "PostCondition" not in refusal["reason"]


def test_pandas_array_literal_dict_element_typed_red_witness_has_bad_twin(
    tmp_path: Path,
) -> None:
    right_effect = TypedRedEffectExpectation(
        effect_class="RuntimeEffect",
        reason_needle="array literal non-FOL element runtime boundary",
        blame_needle="test_witness.py:2:",
    )
    wrong_effect = TypedRedEffectExpectation(
        effect_class="RuntimeEffect",
        reason_needle="dict subscript runtime boundary",
        blame_needle="test_witness.py:2:",
    )
    seed = SugarRedEffectWitnessPair(
        name="pandas_array_literal_dict_element_runtime_effect",
        owner_sugar="ArrayLiteralSugar",
        family="pandas-floor-gap",
        truthful=EffectWitnessSource(
            source=("def A():\n" "    return [{'a': 1}]\n"),
            expectation=right_effect,
            expected_match=True,
        ),
        lying=EffectWitnessSource(
            source=("def A():\n" "    return [{'a': 1}]\n"),
            expectation=wrong_effect,
            expected_match=False,
        ),
    )

    report = evaluate_seed_witnesses((seed,), tmp_path / "right-red")

    assert report.is_zero

    wrong_truth = replace(
        seed,
        truthful=replace(seed.truthful, expectation=wrong_effect, expected_match=True),
    )
    bad_report = evaluate_seed_witnesses((wrong_truth,), tmp_path / "wrong-red")

    assert bad_report.witness_triples_failing == 1
    assert [
        (failure.seed, failure.variant, failure.axis)
        for failure in bad_report.triple_failures
    ] == [
        (
            "pandas_array_literal_dict_element_runtime_effect",
            "truthful",
            "typed-red-effect",
        )
    ]


def test_pandas_symbolic_subscript_assignment_typed_red_witness_has_bad_twin(
    tmp_path: Path,
) -> None:
    _assert_red_effect_seed_has_wrong_effect_twin(
        _symbolic_subscript_assignment_witness(),
        tmp_path,
    )


def test_pandas_dict_literal_subscript_discharges_and_refutes(
    tmp_path: Path,
) -> None:
    _assert_production_pair(
        tmp_path,
        name="dict-literal-subscript",
        selected=("StringSubscriptSugar", "DictSugar"),
        truthful=(
            "def A():\n"
            "    return {'a': 1}['a']\n\n"
            "def test_dict_literal_subscript():\n"
            "    assert A() == 1\n"
        ),
        lying=(
            "def A():\n"
            "    return {'a': 1}['a']\n\n"
            "def test_dict_literal_subscript():\n"
            "    assert A() == 2\n"
        ),
    )


def test_pandas_integer_invert_discharges_and_refutes(tmp_path: Path) -> None:
    _assert_production_pair(
        tmp_path,
        name="integer-invert",
        selected=("UnaryOpSugar",),
        truthful=(
            "def A():\n"
            "    return ~1\n\n"
            "def test_integer_invert():\n"
            "    assert A() == -2\n"
        ),
        lying=(
            "def A():\n"
            "    return ~1\n\n"
            "def test_integer_invert():\n"
            "    assert A() == 1\n"
        ),
    )


def test_pandas_bool_invert_discharges_and_refutes(tmp_path: Path) -> None:
    _assert_production_pair(
        tmp_path,
        name="bool-invert",
        selected=("UnaryOpSugar",),
        truthful=(
            "def A():\n"
            "    return ~True\n\n"
            "def test_bool_invert():\n"
            "    assert A() == -2\n"
        ),
        lying=(
            "def A():\n"
            "    return ~True\n\n"
            "def test_bool_invert():\n"
            "    assert A() == -1\n"
        ),
    )


def test_pandas_callsite_attribute_is_typed_runtime_effect() -> None:
    outcome, selected = _term_outcome(
        "result.dtype",
        {"result": _callsite_floor("constructor")},
    )

    assert "AttributeSugar" in selected
    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, RuntimeEffect)
    assert "callsite attribute runtime boundary" in outcome.effect.reason
    assert "constructor.dtype" in outcome.effect.reason
    assert "pandas_gap.py:1:0" in outcome.effect.reason


def test_pandas_callsite_attribute_wrong_effect_twin_is_rejected() -> None:
    outcome, _selected = _term_outcome(
        "result.dtype",
        {"result": _callsite_floor("constructor")},
    )

    _assert_runtime_effect_matches(
        outcome,
        TypedRedEffectExpectation(
            effect_class="RuntimeEffect",
            reason_needle="callsite attribute runtime boundary",
            blame_needle="pandas_gap.py:1:0",
        ),
    )
    assert not _runtime_effect_matches(
        outcome,
        TypedRedEffectExpectation(
            effect_class="RuntimeEffect",
            reason_needle="array literal non-FOL element runtime boundary",
            blame_needle="pandas_gap.py:1:0",
        ),
    )


def test_pandas_callsite_attribute_production_path_is_typed_red(
    tmp_path: Path,
) -> None:
    source = (
        "def constructor(x):\n"
        "    return x\n\n"
        "def test_callsite_attribute():\n"
        "    result = constructor(5)\n"
        "    assert result.dtype == 5\n"
    )

    doc = _mint_lift_document(tmp_path / "callsite-attribute", source)

    walk = doc["factoryAuditSummary"]["factoryWalk"]
    assert len(walk) == 1
    row = walk[0]
    assert row["selected"] == "ProjectedEqualityAssertionSugar"
    assert row["status"] == "runtime-effect"
    assert row["output"] == {"effect": "RuntimeEffect"}
    assert "AttributeSugar" in {
        audit["selected"]
        for audit in doc["factoryAudits"]
        if isinstance(audit.get("selected"), str)
    }
    assert "callsite attribute runtime boundary" in row["reason"]
    assert "`constructor.dtype`" in row["reason"]


def test_pandas_array_literal_concat_preserves_order_and_items() -> None:
    outcome, selected = _term_outcome("[1] * 2 + [3]")

    value = complete_value(outcome, owner="pandas array concat")
    assert value == ArrayLiteral((TermValue(1), TermValue(1), TermValue(3)))
    assert value != ArrayLiteral((TermValue(1), TermValue(3), TermValue(1)))
    assert "ArrayLiteralSugar" in selected
    assert "BinOpSugar" in selected


def test_pandas_array_literal_concat_discharges_and_refutes(tmp_path: Path) -> None:
    _assert_production_pair(
        tmp_path,
        name="array-literal-concat",
        selected=("BinOpSugar", "StringSubscriptSugar"),
        truthful=(
            "def A(x):\n"
            "    return ([1] * x + [3])[2]\n\n"
            "def test_array_literal_concat():\n"
            "    assert A(2) == 3\n"
        ),
        lying=(
            "def A(x):\n"
            "    return ([1] * x + [3])[2]\n\n"
            "def test_array_literal_concat():\n"
            "    assert A(2) == 4\n"
        ),
    )


def test_pandas_symbolic_string_concat_is_typed_runtime_effect() -> None:
    outcome, selected = _term_outcome(
        'prefix + "US/Eastern"',
        {"prefix": SymbolicValue(make_var("prefix"))},
    )

    assert "BinOpSugar" in selected
    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, RuntimeEffect)
    assert "symbolic string concatenation runtime boundary" in outcome.effect.reason
    assert "SymbolicValue + StringValue" in outcome.effect.reason
    assert "pandas_gap.py:1:0" in outcome.effect.reason


def test_pandas_symbolic_string_concat_typed_red_witness_has_bad_twin(
    tmp_path: Path,
) -> None:
    _assert_red_effect_seed_has_wrong_effect_twin(
        _symbolic_string_concat_witness(),
        tmp_path,
    )


def test_pandas_symbolic_map_receiver_is_typed_runtime_effect() -> None:
    outcome, selected = _term_outcome(
        "values.map(lambda x: x + 1)",
        {"values": SymbolicValue(make_var("values"))},
    )

    assert "MapSugar" in selected
    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, RuntimeEffect)
    assert "map receiver runtime boundary" in outcome.effect.reason
    assert "SymbolicValue.map" in outcome.effect.reason
    assert "pandas_gap.py:1:0" in outcome.effect.reason


def test_pandas_symbolic_map_typed_red_witness_has_bad_twin(
    tmp_path: Path,
) -> None:
    _assert_red_effect_seed_has_wrong_effect_twin(
        _symbolic_map_witness(),
        tmp_path,
    )


def test_pandas_literal_call_lambda_keyword_becomes_typed_red_effect() -> None:
    report = build_literal_call_report(
        source=(
            "def test_to_csv(df):\n"
            "    assert df.to_csv(float_format=lambda x: x) == 'x'\n"
        ),
        filename="pandas/tests/frame/methods/test_to_csv.py",
        memento_file="pandas/tests/frame/methods/test_to_csv.py",
    )

    assert report is not None
    red_rows = [
        row for row in report.payload.factory_walk if row.status == "runtime-effect"
    ]
    assert len(red_rows) == 1
    row = red_rows[0]
    assert row.selected == "CallsiteKeywordRuntimeEffect"
    assert row.requested_role == "CallsiteKeywordActual"
    assert row.ast_kind == "Lambda"
    assert "callsite keyword runtime boundary" in row.reason
    assert "kw:float_format:LambdaCallable-unliftable" in row.reason
    assert "pandas/tests/frame/methods/test_to_csv.py:2:" in row.reason
    assert "callsite argument runtime boundary" not in row.reason


def test_pandas_literal_call_lambda_keyword_effect_is_not_green() -> None:
    report = build_literal_call_report(
        source=(
            "def test_to_csv(df):\n"
            "    assert df.to_csv(float_format=lambda x: x) == 'x'\n"
        ),
        filename="pandas/tests/frame/methods/test_to_csv.py",
        memento_file="pandas/tests/frame/methods/test_to_csv.py",
    )

    assert report is not None
    assert not report.payload.ir
    assert len(report.payload.effects) == 1
    assert (
        "callsite keyword runtime boundary" in report.payload.effects[0].effect.reason
    )


def test_pandas_string_repeat_reduces_to_string_value() -> None:
    outcome, selected = _term_outcome("'ab' * 3")

    assert "BinOpSugar" in selected
    assert outcome == Complete(StringValue("ababab"))


def test_pandas_string_repeat_discharges_and_refutes(tmp_path: Path) -> None:
    _assert_production_pair(
        tmp_path,
        name="string-repeat",
        selected=("BinOpSugar",),
        truthful=(
            "def A():\n"
            "    return 'ab' * 3\n\n"
            "def test_string_repeat():\n"
            "    assert A() == 'ababab'\n"
        ),
        lying=(
            "def A():\n"
            "    return 'ab' * 3\n\n"
            "def test_string_repeat():\n"
            "    assert A() == 'ab'\n"
        ),
    )


def test_pandas_string_float_integral_value_reduces_to_number() -> None:
    outcome, selected = _term_outcome("float('3.0')")

    assert "BuiltinCallSugar" in selected
    assert outcome == Complete(TermValue(3.0))


def test_pandas_string_float_integral_value_discharges_and_refutes(
    tmp_path: Path,
) -> None:
    _assert_production_pair(
        tmp_path,
        name="string-float-integral",
        selected=("BuiltinCallSugar",),
        truthful=(
            "def A():\n"
            "    return float('3.0')\n\n"
            "def test_string_float_integral():\n"
            "    assert A() == 3\n"
        ),
        lying=(
            "def A():\n"
            "    return float('3.0')\n\n"
            "def test_string_float_integral():\n"
            "    assert A() == 4\n"
        ),
    )


@pytest.mark.parametrize(
    ("expr", "reason_needle"),
    [
        ("float('nan')", "parsed a non-finite float"),
        ("float('1.5')", "parsed a non-integral Real"),
    ],
)
def test_pandas_string_float_unsafe_shapes_are_typed_red_effects(
    expr: str, reason_needle: str
) -> None:
    outcome, selected = _term_outcome(expr)

    assert "BuiltinCallSugar" in selected
    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, RuntimeEffect)
    assert "string float conversion runtime boundary" in outcome.effect.reason
    assert reason_needle in outcome.effect.reason
    assert "owner=StringValue" in outcome.effect.reason
    assert "pandas_gap.py:1:" in outcome.effect.reason


@pytest.mark.parametrize(
    ("name", "source", "right_reason", "wrong_reason"),
    [
        (
            "pandas_string_float_nan_runtime_effect",
            "def A():\n    return float('nan')\n",
            "parsed a non-finite float",
            "parsed a non-integral Real",
        ),
        (
            "pandas_string_float_decimal_runtime_effect",
            "def A():\n    return float('1.5')\n",
            "parsed a non-integral Real",
            "parsed a non-finite float",
        ),
    ],
)
def test_pandas_string_float_typed_red_witnesses_have_bad_twins(
    tmp_path: Path,
    name: str,
    source: str,
    right_reason: str,
    wrong_reason: str,
) -> None:
    seed = SugarRedEffectWitnessPair(
        name=name,
        owner_sugar="BuiltinCallSugar",
        family="pandas-floor-gap",
        truthful=EffectWitnessSource(
            source=source,
            expectation=TypedRedEffectExpectation(
                effect_class="RuntimeEffect",
                reason_needle=right_reason,
                blame_needle="test_witness.py:2:",
            ),
            expected_match=True,
        ),
        lying=EffectWitnessSource(
            source=source,
            expectation=TypedRedEffectExpectation(
                effect_class="RuntimeEffect",
                reason_needle=wrong_reason,
                blame_needle="test_witness.py:2:",
            ),
            expected_match=False,
        ),
    )

    _assert_red_effect_seed_has_wrong_effect_twin(seed, tmp_path)


@pytest.mark.parametrize(
    ("expr", "operator"),
    [
        ('module_name not in ["pandas", "pandas.testing"]', "NotIn"),
        ("item in cat", "In"),
        ("bool(ordered) is bool(ordered2)", "Is"),
        ("item in ci", "In"),
        ('"str" in dir(index)', "In"),
    ],
)
def test_pandas_value_position_compare_rows_are_typed_red_effects(
    expr: str, operator: str
) -> None:
    outcome, selected = (
        _term_outcome(
            'module_name not in ["pandas", "pandas.testing"]',
            {"module_name": SymbolicValue(make_var("module_name"))},
        )
        if expr.startswith("module_name ")
        else _term_outcome(expr)
    )

    assert "CompareTermSugar" in selected
    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, RuntimeEffect)
    assert "value-position comparison runtime boundary" in outcome.effect.reason
    assert f"operator `{operator}`" in outcome.effect.reason
    assert "pandas_gap.py:1:0" in outcome.effect.reason


def test_pandas_value_position_membership_compare_names_shape() -> None:
    outcome, selected = _term_outcome(
        'module_name not in ["pandas", "pandas.testing"]',
        {"module_name": SymbolicValue(make_var("module_name"))},
    )

    assert selected == ("CompareTermSugar",)
    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, RuntimeEffect)
    assert "value-position comparison runtime boundary" in outcome.effect.reason
    assert "operator `NotIn`" in outcome.effect.reason
    assert "pandas_gap.py:1:0" in outcome.effect.reason


def test_pandas_compare_typed_red_witness_accepts_right_red_and_rejects_wrong_red(
    tmp_path: Path,
) -> None:
    _assert_red_effect_seed_has_wrong_effect_twin(
        CompareTermSugar.witnesses(),
        tmp_path,
    )


@pytest.mark.parametrize(
    "expr",
    [
        "(x for x in [0, 1] if x not in axes)",
        "next(x for x in [0, 1] if x not in axes)",
        "(len(line) for line in lines.split('\\n'))",
    ],
)
def test_pandas_generator_exp_rows_are_typed_red_effects(expr: str) -> None:
    outcome, selected = _term_outcome(expr)

    assert "GeneratorExpSugar" in selected
    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, RuntimeEffect)
    assert "generator expression runtime boundary" in outcome.effect.reason
    assert "owner=GeneratorExpSugar" in outcome.effect.reason
    assert "pandas_gap.py:1:" in outcome.effect.reason


def test_pandas_generator_exp_typed_red_witness_accepts_right_red_and_rejects_wrong_red(
    tmp_path: Path,
) -> None:
    _assert_red_effect_seed_has_wrong_effect_twin(
        GeneratorExpSugar.witnesses(),
        tmp_path,
    )


def test_pandas_starred_tuple_unpack_assign_is_typed_red_effect() -> None:
    outcome, selected = _block_outcome(
        "    header, separator, first_line, *rest, last_line = table\n",
        {"table": SymbolicValue(make_var("table"))},
    )

    assert "TupleUnpackAssignSugar" in selected
    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, RuntimeEffect)
    assert "starred tuple-unpack assignment runtime boundary" in outcome.effect.reason
    assert "owner=TupleUnpackAssignSugar" in outcome.effect.reason
    assert "pandas_gap.py:2:4" in outcome.effect.reason


def test_pandas_named_expr_term_is_typed_red_effect() -> None:
    outcome, selected = _term_outcome("(u := uuid4())")

    assert "NamedExprSugar" in selected
    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, RuntimeEffect)
    assert "named expression runtime boundary" in outcome.effect.reason
    assert "owner=NamedExprSugar" in outcome.effect.reason
    assert "pandas_gap.py:1:" in outcome.effect.reason


def test_pandas_starred_tuple_unpack_typed_red_witness_accepts_right_red_and_rejects_wrong_red(
    tmp_path: Path,
) -> None:
    _assert_red_effect_seed_has_wrong_effect_twin(
        _red_seed_from_tuple_unpack_witnesses(),
        tmp_path,
    )


def test_pandas_named_expr_typed_red_witness_accepts_right_red_and_rejects_wrong_red(
    tmp_path: Path,
) -> None:
    _assert_red_effect_seed_has_wrong_effect_twin(
        NamedExprSugar.witnesses(),
        tmp_path,
    )


def test_pandas_typed_red_templates_flip_when_blocking_construct_is_removed() -> None:
    compare_outcome, compare_selected = _term_outcome(
        "module_name",
        {"module_name": SymbolicValue(make_var("module_name"))},
    )
    generator_outcome, generator_selected = _term_outcome("[0, 1]")
    starred_outcome, starred_selected = _block_outcome(
        "    header, rest = table\n",
        {"table": SymbolicValue(make_var("table"))},
    )
    named_outcome, named_selected = _term_outcome("1")

    assert "CompareTermSugar" not in compare_selected
    assert "GeneratorExpSugar" not in generator_selected
    assert "NamedExprSugar" not in named_selected
    assert not _has_runtime_effect(compare_outcome, "value-position comparison")
    assert not _has_runtime_effect(generator_outcome, "generator expression")
    assert not _has_runtime_effect(
        starred_outcome,
        "starred tuple-unpack assignment",
    )
    assert not _has_runtime_effect(named_outcome, "named expression")
    assert "TupleUnpackAssignSugar" in starred_selected


def _assert_red_effect_seed_has_wrong_effect_twin(
    seed: SugarRedEffectWitnessPair,
    tmp_path: Path,
) -> None:
    report = evaluate_seed_witnesses((seed,), tmp_path / f"{seed.name}-right-red")

    assert report.is_zero

    wrong_truth = replace(
        seed,
        truthful=replace(
            seed.truthful,
            expectation=seed.lying.expectation,
            expected_match=True,
        ),
    )
    bad_report = evaluate_seed_witnesses(
        (wrong_truth,),
        tmp_path / f"{seed.name}-wrong-red",
    )

    assert bad_report.witness_triples_failing == 1
    assert [
        (failure.seed, failure.variant, failure.axis)
        for failure in bad_report.triple_failures
    ] == [
        (
            seed.name,
            "truthful",
            "typed-red-effect",
        )
    ]


def _red_seed_from_tuple_unpack_witnesses() -> SugarRedEffectWitnessPair:
    for seed in TupleUnpackAssignSugar.witnesses():
        if isinstance(seed, SugarRedEffectWitnessPair):
            return seed
    raise AssertionError("TupleUnpackAssignSugar must expose a red-effect seed")


def _symbolic_subscript_assignment_witness() -> SugarRedEffectWitnessPair:
    right_effect = TypedRedEffectExpectation(
        effect_class="RuntimeEffect",
        reason_needle="subscript assignment runtime boundary",
        blame_needle="test_witness.py:2:4",
    )
    wrong_effect = TypedRedEffectExpectation(
        effect_class="RuntimeEffect",
        reason_needle="attribute assignment runtime boundary",
        blame_needle="test_witness.py:2:4",
    )
    return SugarRedEffectWitnessPair(
        name="pandas_symbolic_subscript_assignment_runtime_effect",
        owner_sugar="SubscriptAssignSugar",
        family="pandas-floor-gap",
        truthful=EffectWitnessSource(
            source=("def A(xs):\n" "    xs[0] = 1\n" "    return xs\n"),
            expectation=right_effect,
            expected_match=True,
        ),
        lying=EffectWitnessSource(
            source=("def A(xs):\n" "    xs[0] = 1\n" "    return xs\n"),
            expectation=wrong_effect,
            expected_match=False,
        ),
    )


def _symbolic_string_concat_witness() -> SugarRedEffectWitnessPair:
    right_effect = TypedRedEffectExpectation(
        effect_class="RuntimeEffect",
        reason_needle="symbolic string concatenation runtime boundary",
        blame_needle="test_witness.py:2:",
    )
    wrong_effect = TypedRedEffectExpectation(
        effect_class="RuntimeEffect",
        reason_needle="map receiver runtime boundary",
        blame_needle="test_witness.py:2:",
    )
    return SugarRedEffectWitnessPair(
        name="pandas_symbolic_string_concat_runtime_effect",
        owner_sugar="BinOpSugar",
        family="pandas-floor-gap",
        truthful=EffectWitnessSource(
            source=('def A(prefix):\n    return prefix + "US/Eastern"\n'),
            expectation=right_effect,
            expected_match=True,
        ),
        lying=EffectWitnessSource(
            source=('def A(prefix):\n    return prefix + "US/Eastern"\n'),
            expectation=wrong_effect,
            expected_match=False,
        ),
    )


def _symbolic_map_witness() -> SugarRedEffectWitnessPair:
    right_effect = TypedRedEffectExpectation(
        effect_class="RuntimeEffect",
        reason_needle="map receiver runtime boundary",
        blame_needle="test_witness.py:2:",
    )
    wrong_effect = TypedRedEffectExpectation(
        effect_class="RuntimeEffect",
        reason_needle="symbolic string concatenation runtime boundary",
        blame_needle="test_witness.py:2:",
    )
    return SugarRedEffectWitnessPair(
        name="pandas_symbolic_map_runtime_effect",
        owner_sugar="MapSugar",
        family="pandas-floor-gap",
        truthful=EffectWitnessSource(
            source=("def A(values):\n    return values.map(lambda x: x + 1)\n"),
            expectation=right_effect,
            expected_match=True,
        ),
        lying=EffectWitnessSource(
            source=("def A(values):\n    return values.map(lambda x: x + 1)\n"),
            expectation=wrong_effect,
            expected_match=False,
        ),
    )


def _callsite_floor(target_name: str) -> CallSiteValue:
    return CallSiteValue(
        target_name=target_name,
        arg_values=(),
        parameters=(),
        term=make_var(f"call:{target_name}"),
        body=None,
    )


def _mint_lift_document(project: Path, source: str) -> dict:
    _stage_cli_project(project, source)
    sugar = _ensure_sugar_bin()
    capture = project / ".sugar" / "lift" / "python" / "lift-rpc-capture.jsonl"
    completed = subprocess.run(
        [str(sugar), "mint", "--out", ".", "--quiet"],
        cwd=project,
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    responses = [
        json.loads(line) for line in capture.read_text(encoding="utf-8").splitlines()
    ]
    primary = [
        item
        for item in responses
        if item.get("id") == 2 and isinstance(item.get("result"), dict)
    ]
    assert len(primary) == 1
    return primary[0]["result"]


def _assert_runtime_effect_matches(
    outcome,
    expectation: TypedRedEffectExpectation,
) -> None:
    assert _runtime_effect_matches(outcome, expectation)


def _runtime_effect_matches(
    outcome,
    expectation: TypedRedEffectExpectation,
) -> bool:
    return (
        isinstance(outcome, Incomplete)
        and type(outcome.effect).__name__ == expectation.effect_class
        and expectation.reason_needle in outcome.effect.reason
        and expectation.blame_needle in outcome.effect.reason
    )


def _has_runtime_effect(outcome, needle: str) -> bool:
    return (
        isinstance(outcome, Incomplete)
        and isinstance(outcome.effect, RuntimeEffect)
        and needle in outcome.effect.reason
    )
