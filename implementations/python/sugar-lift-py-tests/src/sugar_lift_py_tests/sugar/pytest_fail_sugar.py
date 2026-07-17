from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
import hashlib

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.floor import ExceptionValue, RaiseValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class PytestFailSugar(
    Sugar,
    role=SugarRole.TERM,
    comes_before=("KeywordCallSugar", "MethodCallSugar"),
):
    """The exact ``pytest.fail(...)`` call is a constructed exceptional exit.

    ``pytest.fail`` always raises ``pytest.fail.Exception`` after evaluating its
    arguments. It is terminal control-flow data, not runtime dependence and not
    an opaque method-call value.
    """

    args: tuple[SugarBody, ...]
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return (
            site.observed == "Call"
            and site.call_qualified_target_name() == "pytest.fail"
        )

    @classmethod
    def new(cls, site, ctx) -> "PytestFailSugar":
        return cls(
            args=tuple(
                ctx.build_body(argument, SugarRole.TERM)
                for argument in (
                    *site.call_args(),
                    *(keyword.keyword_value() for keyword in site.call_keywords()),
                )
            ),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        source = (
            "def A(z):\n"
            "    if z < 0:\n"
            "        pytest.fail('negative')\n"
            "    return z\n"
            "\n"
        )
        return _call_pair(
            name="pytest_fail_exceptional_exit",
            owner_sugar=cls.__name__,
            truthful=source + "def test_a():\n    assert A(5) == 5\n",
            lying=source + "def test_a():\n    assert A(5) == 6\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self._reduce_args(self.args, (), ctx)

    def _reduce_args(
        self,
        remaining: tuple[SugarBody, ...],
        accumulated: tuple,
        ctx: object,
    ) -> Outcome:
        if remaining:
            return (
                remaining[0]
                .reduce(ctx)
                .and_then(
                    lambda value: self._reduce_args(
                        remaining[1:], (*accumulated, value), ctx
                    )
                )
            )

        source_sha256 = None
        source = getattr(self.site, "source", None)
        if source is not None:
            source_sha256 = hashlib.sha256(source.encode()).hexdigest()
        exception = ExceptionValue("pytest.fail.Exception", accumulated, site=self.site)
        return Complete(
            RaiseValue(
                RaiseEffect(
                    exception_name=exception.exception_name,
                    blame=str(self.site),
                    source_sha256=source_sha256,
                ),
                scope=ctx,
                exception=exception,
            )
        )

    def walk_children(self):
        return self.args
