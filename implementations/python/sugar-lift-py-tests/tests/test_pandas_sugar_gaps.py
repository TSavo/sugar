from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext
from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.factory.block import Block
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.floor import FloorValue, ImportAliasValue, SymbolicValue
from sugar_lift_py_tests.idd.sugar_witness_instruments import evaluate_seed_witnesses
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.outcome import Incomplete
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


def _has_runtime_effect(outcome, needle: str) -> bool:
    return (
        isinstance(outcome, Incomplete)
        and isinstance(outcome.effect, RuntimeEffect)
        and needle in outcome.effect.reason
    )
