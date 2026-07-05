from __future__ import annotations

import ast

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory.build import FactoryBuildContext, default_catalog
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.call_sugar import CallSugar
from sugar_lift_py_tests.sugar.slice_sugar import SliceSugar


def _ctx(**kwargs) -> FactoryBuildContext:
    return FactoryBuildContext(filename="t.py", catalog=default_catalog(), **kwargs)


def _expr_site(expr: str) -> SourceFragment:
    return SourceFragment.from_node(ast.parse(expr, mode="eval").body, "t.py")


def _slice_site(expr: str) -> SourceFragment:
    return SourceFragment.from_node(ast.parse(expr, mode="eval").body.slice, "t.py")


def _term_for(site: SourceFragment, ctx: FactoryBuildContext):
    body = ctx.build_body(site, SugarRole.TERM)
    outcome = body.reduce(ctx)
    assert isinstance(outcome, Complete)
    return body.sugar, outcome.value.to_term(owner="test")


def test_builtin_slice_three_args_uses_same_value_as_literal_slice() -> None:
    ctx = _ctx()

    builtin, builtin_term = _term_for(_expr_site("slice(1, 3, 2)"), ctx)
    literal, literal_term = _term_for(_slice_site("xs[1:3:2]"), ctx)

    assert isinstance(builtin, SliceSugar)
    assert isinstance(literal, SliceSugar)
    assert builtin_term == literal_term


def test_builtin_slice_one_arg_maps_to_omitted_lower_and_step() -> None:
    ctx = _ctx()

    _, builtin_term = _term_for(_expr_site("slice(3)"), ctx)
    _, literal_term = _term_for(_slice_site("xs[:3]"), ctx)

    assert builtin_term == literal_term


def test_local_slice_function_is_not_claimed_as_builtin_slice() -> None:
    module = ast.parse("def slice(stop):\n    return stop\nslice(3)")
    local_slice = module.body[0]
    call = module.body[1].value
    ctx = _ctx(name_resolver={"slice": local_slice})

    body = ctx.build_body(SourceFragment.from_node(call, "t.py"), SugarRole.TERM)

    assert isinstance(body.sugar, CallSugar)
