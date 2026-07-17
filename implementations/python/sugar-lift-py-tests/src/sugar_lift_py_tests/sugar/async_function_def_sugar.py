from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import AsyncFunctionCallable, FunctionCallable
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.statement_function_def_sugar import (
    StatementFunctionDefSugar,
)
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class AsyncFunctionDefSugar(Sugar, role=SugarRole.STATEMENT):
    """Bind an async function without equating a bare call with body termination."""

    definition: StatementFunctionDefSugar

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "AsyncFunctionDef"

    @classmethod
    def new(cls, site, ctx):
        return cls(StatementFunctionDefSugar.new(site, ctx))

    @classmethod
    def witnesses(cls):
        prefix = (
            "def A():\n"
            "    async def inner():\n"
            "        return 2\n"
            "    return 1\n\n"
        )
        return _call_pair(
            name="async_function_definition_return",
            owner_sugar=cls.__name__,
            truthful=prefix + "def test_a():\n    assert A() == 1\n",
            lying=prefix + "def test_a():\n    assert A() == 2\n",
        )

    def desugar(self, ctx=None):
        return self.definition.desugar(ctx).and_then(self._make_async)

    @staticmethod
    def _make_async(value):
        assert isinstance(value, FunctionCallable)
        return Complete(AsyncFunctionCallable(**value.__dict__))

    def walk_children(self):
        return self.definition.walk_children()
