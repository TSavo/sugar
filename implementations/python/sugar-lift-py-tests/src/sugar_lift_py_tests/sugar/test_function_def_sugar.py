from __future__ import annotations

from dataclasses import field as dataclass_field, dataclass, replace
from itertools import product
from typing import Any

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class TestFunctionDefSugar(
    Sugar, role=SugarRole.DEFINITION, comes_before=("FunctionDefSugar",)
):
    """`def test_*(...): body` is TESTIMONY, not a contract. The pytest
    `test_` prefix IS syntax; recognition stays syntactic. Decorators
    are allowed on owns — body is still testimony. Exact literal
    ``@pytest.mark.parametrize`` rows reduce independently; dynamic decorator
    effects are not invented as floors. The body becomes a TestimonyValue:
    its asserts are the vendor facts. Comes before FunctionDefSugar so
    testimony wins over the ordinary universe path."""

    name: str
    formals: tuple[str, ...]
    parameter_rows: tuple[tuple[tuple[str, object], ...], ...]
    body: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "FunctionDef":
            return False
        if not site.function_name().startswith("test_"):
            return False
        min_args, max_args = site.function_positional_arity()
        # Deeper floors: pytest.mark.* (and similar) decorate testimony without
        # changing owns. Require plain positional arity still; only exact
        # literal parametrize rows are constructed by new().
        return min_args == max_args

    @classmethod
    def new(cls, site, ctx) -> "TestFunctionDefSugar":
        parameter_groups = site.literal_pytest_parametrize_rows()
        parameter_rows = tuple(
            tuple(
                (name, value)
                for names, values in selected
                for name, value in zip(names, values, strict=True)
            )
            for selected in product(
                *(
                    tuple((names, row) for row in rows)
                    for names, rows in parameter_groups
                )
            )
        )
        # The body is factory-built as ONE Block (audited), never reduced here.
        return cls(
            name=site.function_name(),
            formals=tuple(site.function_params()),
            parameter_rows=parameter_rows,
            body=ctx.build_body(site.function_body_block(), SugarRole.STATEMENT),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        # A test asserts what the callee does: the truthful twin agrees with
        # the callee's post, the lying twin contradicts -- the pair discriminates.
        prefix = (
            "def enc(x):\n"
            "    return x\n"
            "\n"
            "def test_enc():\n"
            '    assert enc("a") == "a"\n'
            "\n"
        )
        parametrized = (
            "import pytest\n"
            "def identity(value):\n"
            "    return value\n"
            "\n"
            "@pytest.mark.parametrize(\n"
            "    ('kind', 'expected'),\n"
            "    [('first', 1), ('middle', 2), ('last', 3)],\n"
            ")\n"
            "def test_choice(kind, expected):\n"
            "    if kind == 'first':\n"
            "        result = 1\n"
            "    elif kind == 'middle':\n"
            "        result = 2\n"
            "    elif kind == 'last':\n"
            "        result = 3\n"
        )
        return (
            _call_pair(
                name="test_function_def_return",
                owner_sugar="TestFunctionDefSugar",
                truthful=prefix + "def test_a():\n    assert True\n",
                lying=prefix + "def test_a():\n    assert False\n",
            ),
            _call_pair(
                name="test_function_literal_parametrize_rows",
                owner_sugar="TestFunctionDefSugar",
                truthful=parametrized + "    assert identity(result) == expected\n",
                lying=parametrized + "    assert identity(result) == expected + 1\n",
                family="literal-parametrize",
            ),
        )

    def desugar(self, ctx: Any = None) -> Outcome:
        # Bind each parameter to its universe variable, reduce the body under
        # that scope, and the result is testimony (facts only, no post).
        from sugar_lift_py_tests.floor import (
            BlockValue,
            NoneValue,
            StringValue,
            SymbolicValue,
            TermValue,
            TestimonyValue,
        )
        from sugar_lift_py_tests.ir import make_var

        def floor_literal(value):
            if isinstance(value, str):
                return StringValue(value)
            if value is None:
                return NoneValue()
            return TermValue(value)

        rows: tuple[tuple[tuple[str, object], ...], ...] = self.parameter_rows or ((),)

        def reduce_row(index, statements):
            if index == len(rows):
                return Complete(
                    TestimonyValue(
                        name=self.name,
                        formals=self.formals,
                        record=BlockValue(tuple(statements)),
                    )
                )
            temporal = ctx.temporal
            for formal in self.formals:
                temporal = temporal.bind_value(formal, SymbolicValue(make_var(formal)))
            for formal, value in rows[index]:
                temporal = temporal.bind_value(formal, floor_literal(value))
            scoped = replace(ctx, temporal=temporal)
            return self.body.reduce(scoped).and_then(
                lambda record: reduce_row(index + 1, (*statements, *record.statements))
            )

        return reduce_row(0, ())

    def walk_children(self):
        return (self.body,)
