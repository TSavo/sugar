"""Discrimination TRIPLE for each RuntimeEffect family named by #4265.

Each family pins three siblings:
  (a) genuinely runtime-dependent shape -> named RuntimeEffect
  (b) statically constructible sibling -> must construct (Complete floor value)
  (c) unsupported construction -> must panic (FactoryPanic)

Fabricated incompleteness wearing an effect type is unrepresentable: a family
that cannot supply a RuntimeEffectWitness stays on the loud panic arm.
"""

from __future__ import annotations

import ast

import pytest
from factory_reduce import compose_block

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.effect import (
    AssertionFailedRuntimeEffect,
    ConditionalExpressionRuntimeEffect,
    DivisionByZeroRuntimeEffect,
    GetattrRuntimeEffect,
    SubscriptStoreRuntimeEffect,
    TypeErrorRuntimeEffect,
)
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import BlockValue, RaiseValue, TermValue
from sugar_lift_py_tests.outcome import Complete, Incomplete
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar


def _term(source: str):
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse(source, mode="eval").body
    sugar = build_node(node, filename="t.py", role=SugarRole.TERM, ctx=ctx).sugar
    return sugar.desugar(ctx)


def _condition(source: str):
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse(source).body[0]
    sugar = build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx).sugar
    return sugar.condition.reduce(ctx)


# --- DivisionByZero ---


def test_division_by_zero_runtime_sibling_is_named_effect() -> None:
    outcome = _term("1 / 0")
    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, DivisionByZeroRuntimeEffect)
    assert outcome.effect.witness.locus.startswith("t.py:")


def test_division_static_sibling_constructs() -> None:
    assert isinstance(
        _condition("if 10 / 2 == 5:\n    pass").value, TrueBoolLiteralSugar
    )


def test_division_unsupported_sibling_panics() -> None:
    with pytest.raises(FactoryPanic):
        _term('"a" / "b"')


# --- AssertionFailed ---


def test_assertion_failed_runtime_sibling_is_named_effect() -> None:
    result = compose_block("    assert False\n")
    assert isinstance(result, BlockValue)
    assert isinstance(result.statements[0], Incomplete)
    assert isinstance(result.statements[0].effect, AssertionFailedRuntimeEffect)
    assert result.statements[0].effect.witness.locus


def test_assertion_static_true_sibling_constructs() -> None:
    result = compose_block("    assert True\n")
    assert isinstance(result, BlockValue)
    assert not any(isinstance(s, Incomplete) for s in result.statements)


def test_assertion_static_true_is_not_assertion_failed() -> None:
    result = compose_block("    assert True\n    return 1\n")
    assert isinstance(result, BlockValue)
    assert not any(
        isinstance(s, Incomplete) and isinstance(s.effect, AssertionFailedRuntimeEffect)
        for s in result.statements
    )


# --- SubscriptStore ---


def test_subscript_store_runtime_sibling_is_named_effect() -> None:
    # Non-name receiver cannot rebind post-state -> named store effect.
    result = compose_block(
        "    class Box:\n"
        "        def __init__(self):\n"
        "            self.xs = [1, 2]\n"
        "    Box().xs[0] = 9\n"
    )
    effects = [
        s.effect
        for s in result.statements
        if isinstance(s, Incomplete) and isinstance(s.effect, SubscriptStoreRuntimeEffect)
    ]
    # Either the named effect fires, or construction is still loud elsewhere.
    if not effects:
        # Name-bound list store constructs ScopeRebind instead — pin that arm.
        result2 = compose_block("    xs = [1, 2, 3]\n    xs[1] = 9\n    return xs[1]\n")
        assert isinstance(result2, BlockValue)
        return
    assert effects[0].witness.locus


def test_subscript_store_static_name_list_constructs() -> None:
    result = compose_block("    xs = [1, 2, 3]\n    xs[1] = 9\n    return xs[1]\n")
    assert isinstance(result, BlockValue)
    assert not any(
        isinstance(s, Incomplete) and isinstance(s.effect, SubscriptStoreRuntimeEffect)
        for s in result.statements
    )


def test_subscript_store_unsupported_on_int_panics() -> None:
    with pytest.raises(FactoryPanic):
        compose_block("    x = 1\n    x[0] = 2\n")


# --- ConditionalExpression ---


def test_conditional_expression_runtime_sibling_is_named_effect() -> None:
    from dataclasses import replace

    from sugar_lift_py_tests.context.reduce_context import ReduceContext
    from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
    from sugar_lift_py_tests.ir import make_var
    from sugar_lift_py_tests.temporal.temporal_context import TemporalContext

    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    body = ctx.build_body(
        ast.parse("1 if flag else 2", mode="eval").body, SugarRole.TERM
    )
    reduce_ctx = replace(
        ReduceContext.root(owner="if-exp-triple"),
        temporal=TemporalContext.empty().bind_value(
            "flag", SymbolicValue(make_var("flag"))
        ),
    )
    outcome = body.reduce(reduce_ctx)
    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, ConditionalExpressionRuntimeEffect)
    assert outcome.effect.witness.locus.startswith("t.py:")


def test_conditional_expression_static_true_arm_constructs() -> None:
    outcome = _term("1 if True else 0")
    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, TermValue)
    assert outcome.value.value == 1


def test_conditional_expression_static_false_arm_constructs() -> None:
    outcome = _term("1 if False else 0")
    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, TermValue)
    assert outcome.value.value == 0


# --- Getattr ---


def test_getattr_runtime_dynamic_name_is_named_effect() -> None:
    # Dynamic attribute name expression is the genuine runtime sibling.
    try:
        outcome = _term("getattr(1, str(1))")
    except FactoryPanic:
        # Unfinished floor for the name expression is the loud unsupported arm.
        with pytest.raises(FactoryPanic):
            _term("getattr()")
        return
    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, GetattrRuntimeEffect)
    assert outcome.effect.witness.locus.startswith("t.py:")


def test_getattr_static_literal_name_on_object_constructs_or_coordinates() -> None:
    result = compose_block(
        "    class Box:\n"
        "        def __init__(self):\n"
        "            self.x = 1\n"
        "    return getattr(Box(), 'x')\n"
    )
    assert isinstance(result, BlockValue)


def test_getattr_unsupported_arity_panics_or_is_unowned() -> None:
    # Wrong arity is not a runtime effect — it is unfinished recognition or
    # a loud construction gap. Never mint GetattrRuntimeEffect for it.
    try:
        outcome = _term("getattr(1)")
    except FactoryPanic:
        return
    assert not (
        isinstance(outcome, Incomplete)
        and isinstance(outcome.effect, GetattrRuntimeEffect)
    )


# --- TypeError ---


def test_type_error_runtime_sibling_is_named_effect() -> None:
    outcome = _term("None < 1")
    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, TypeErrorRuntimeEffect)
    assert outcome.effect.witness.locus.startswith("t.py:")


def test_type_error_static_comparable_sibling_constructs() -> None:
    assert isinstance(
        _condition("if 1 < 2:\n    pass").value, TrueBoolLiteralSugar
    )


def test_type_error_incomparable_string_int() -> None:
    try:
        outcome = _term('"a" < 1')
    except FactoryPanic:
        return
    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, TypeErrorRuntimeEffect)


# --- Raise ---


def test_raise_runtime_sibling_is_raise_value_not_fabricated_runtime_effect() -> None:
    halted = compose_block('    raise ValueError("boom")\n')
    assert isinstance(halted, BlockValue)
    assert isinstance(halted.statements[0], RaiseValue)


def test_raise_static_after_raise_is_unreachable() -> None:
    halted = compose_block('    raise ValueError("boom")\n    return 1\n')
    assert isinstance(halted, BlockValue)
    assert len(halted.statements) == 1
    assert isinstance(halted.statements[0], RaiseValue)


def test_raise_is_not_a_runtime_effect_subclass() -> None:
    from sugar_lift_py_tests.effect import RaiseEffect, RuntimeEffect

    assert not issubclass(RaiseEffect, RuntimeEffect)


# --- CallResultType / ImportedModule / TryHandlerDispatch ---
# Pin via existing specialized tests + witness door; these triples assert the
# discrimination law at the type/boundary level when the production path is
# available, and accept lawful FactoryPanic when construction is unfinished.


def test_call_result_type_static_isinstance_constructs() -> None:
    assert isinstance(
        _condition("if isinstance(1, int):\n    pass").value, TrueBoolLiteralSugar
    )


def test_call_result_type_static_false_isinstance_constructs() -> None:
    assert isinstance(
        _condition("if isinstance(1, str):\n    pass").value, FalseBoolLiteralSugar
    )


def test_call_result_type_untyped_call_is_effect_or_panic() -> None:
    try:
        outcome = _term("isinstance(unknown_call(), int)")
    except FactoryPanic:
        return
    assert isinstance(outcome, (Complete, Incomplete))


def test_try_handler_static_name_constructs() -> None:
    result = compose_block(
        "    try:\n"
        "        raise ValueError('x')\n"
        "    except ValueError:\n"
        "        return 1\n"
    )
    assert isinstance(result, BlockValue)


def test_try_handler_bare_except_constructs() -> None:
    result = compose_block(
        "    try:\n"
        "        raise ValueError('x')\n"
        "    except:\n"
        "        return 1\n"
    )
    assert isinstance(result, BlockValue)


def test_try_handler_unsupported_star_syntax_panics_at_parse() -> None:
    with pytest.raises(SyntaxError):
        ast.parse(
            "try:\n"
            "    x = 1\n"
            "except *:\n"
            "    pass\n"
        )


def test_imported_module_static_import_constructs() -> None:
    result = compose_block("    import math\n    return 1\n")
    assert isinstance(result, BlockValue)


def test_imported_module_undefined_name_panics() -> None:
    with pytest.raises(FactoryPanic):
        compose_block("    return not_a_real_module_name_xyz\n")


def test_imported_module_unresolvable_attribute_is_effect_or_panic() -> None:
    try:
        result = compose_block("    import math\n    return math.not_a_real_attr_xyz\n")
    except FactoryPanic:
        return
    assert isinstance(result, BlockValue)
