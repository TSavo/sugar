"""JoinedStrSugar: f-string concatenates every part; interpolations ride."""

from __future__ import annotations

import ast

import pytest

from factory_reduce import fol, reduce_term, reduce_value

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.effect import DynamicFormatRuntimeEffect
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import StringValue, SymbolicValue
from sugar_lift_py_tests.ir import ctor, make_var, num, str_const
from sugar_lift_py_tests.outcome import Incomplete
from sugar_lift_py_tests.sugar.joined_str_sugar import JoinedStrSugar


def _site(expr: str):
    return SourceFragment.from_node(ast.parse(expr, mode="eval").body, "t.py")


def test_literal_only_fstring_folds() -> None:
    """(1) All-literal f-string folds to the concrete string."""
    assert reduce_value("f'numpy-totality'") == StringValue("numpy-totality")


def test_ground_interpolation_folds() -> None:
    """(1) Ground formatted value folds into the joined string."""
    assert reduce_value("f'a{1}b'") == StringValue("a1b")


def test_symbolic_interpolation_carries_the_value() -> None:
    """(2) f'x{a}' and f'x{b}' produce different terms -- value is carried."""
    with_a = reduce_term("f'x{a}'", binds={"a": SymbolicValue(make_var("a"))})
    with_b = reduce_term("f'x{b}'", binds={"b": SymbolicValue(make_var("b"))})
    assert fol(with_a) != fol(with_b)
    assert "py.fstring" in repr(with_a) or "py.format" in repr(with_a)
    # The free var rides inside the format coordinate.
    assert fol(with_a) == fol(
        ctor(
            "py.fstring",
            [
                str_const("x"),
                ctor(
                    "py.format",
                    [make_var("a"), str_const(""), num(-1)],
                ),
            ],
        )
    )


def test_literal_only_change_discriminates() -> None:
    """(2) f'x' vs f'y' differ (literal parts not dropped/constant-collapsed)."""
    assert reduce_value("f'x'") == StringValue("x")
    assert reduce_value("f'y'") == StringValue("y")
    assert reduce_value("f'x'") != reduce_value("f'y'")


def test_owns_joined_str_not_plain_str_or_binop() -> None:
    """(3) owns fires on JoinedStr, not plain str Constant or string +."""
    assert JoinedStrSugar.owns(_site("f'hi'")) is True
    assert JoinedStrSugar.owns(_site("f'{x}'")) is True
    assert JoinedStrSugar.owns(_site("'hi'")) is False
    assert JoinedStrSugar.owns(_site("'a' + 'b'")) is False

    catalog = default_catalog()
    cands = [c.name for c in catalog.candidates_for(SugarRole.TERM, _site("f'z'"))]
    assert "JoinedStrSugar" in cands


def test_format_spec_rides_in_the_coordinate() -> None:
    result = reduce_term("f'{x:.2f}'", binds={"x": SymbolicValue(make_var("x"))})
    assert fol(result) == fol(
        ctor(
            "py.fstring",
            [
                ctor(
                    "py.format",
                    [make_var("x"), str_const(".2f"), num(-1)],
                ),
            ],
        )
    )


def test_dynamic_format_spec_is_a_named_runtime_effect() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    body = ctx.build_body(_site("f'{x:{width}}'"), SugarRole.TERM)
    ctx = ctx.with_temporal(
        ctx.temporal.bind_value("x", SymbolicValue(make_var("x"))).bind_value(
            "width", SymbolicValue(make_var("width"))
        )
    )

    outcome = body.reduce(ctx)

    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, DynamicFormatRuntimeEffect)
    witness = outcome.effect.witness
    assert witness is not None
    assert witness.operation == ctor("py.format.dynamic_spec", [witness.operand])
    assert fol(witness.operand) == fol(
        ctor(
            "py.format.arguments",
            [
                make_var("x"),
                ctor(
                    "py.fstring",
                    [
                        ctor(
                            "py.format",
                            [make_var("width"), str_const(""), num(-1)],
                        )
                    ],
                ),
                num(-1),
            ],
        )
    )
