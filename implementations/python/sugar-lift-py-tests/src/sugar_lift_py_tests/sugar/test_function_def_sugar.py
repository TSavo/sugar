from __future__ import annotations

from dataclasses import field as dataclass_field, dataclass, replace

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
    (``@pytest.mark.parametrize``, …) are allowed on owns — body is still
    testimony; decorator effects are not invented as floors. The body becomes
    a TestimonyValue: its asserts are the vendor facts. Comes before
    FunctionDefSugar so testimony wins over the ordinary universe path."""

    name: str
    formals: tuple[str, ...]
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
        # changing the body. Require plain positional arity still; decorators
        # are not reduced (not fabricated) — body asserts remain the facts.
        return min_args == max_args

    @classmethod
    def new(cls, site, ctx) -> "TestFunctionDefSugar":
        # The body is factory-built as ONE Block (audited), never reduced here.
        return cls(
            name=site.function_name(),
            formals=tuple(site.function_params()),
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
        return _call_pair(
            name="test_function_def_return",
            owner_sugar="TestFunctionDefSugar",
            truthful=prefix + "def test_a():\n    assert True\n",
            lying=prefix + "def test_a():\n    assert False\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        # Bind each parameter to its universe variable, reduce the body under
        # that scope, and the result is testimony (facts only, no post).
        from sugar_lift_py_tests.floor import SymbolicValue, TestimonyValue
        from sugar_lift_py_tests.ir import make_var

        temporal = ctx.temporal
        for formal in self.formals:
            temporal = temporal.bind_value(formal, SymbolicValue(make_var(formal)))
        scoped = replace(ctx, temporal=temporal)
        return self.body.reduce(scoped).and_then(
            lambda record: Complete(
                TestimonyValue(name=self.name, formals=self.formals, record=record)
            )
        )

    def walk_children(self):
        return (self.body,)
