from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.floor import ObjectMethodValue, ObjectValue, TermValue
from sugar_lift_py_tests.operations.async_context_manager_operation import (
    AsyncContextManagerOperation,
)
from sugar_lift_py_tests.operations.async_iterator_operation import (
    AsyncIteratorOperation,
)
from sugar_lift_py_tests.operations.await_operation import AwaitOperation
from sugar_lift_py_tests.operations.context_manager_operation import (
    ContextManagerOperation,
)
from sugar_lift_py_tests.outcome import Complete, Incomplete
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class DunderCase:
    label: str
    method_name: str
    invoke: Callable[[ObjectValue, ReduceContext], object]


class MissingDesugarSugar:
    pass


class OpaqueRuntimeSugar:
    def desugar(self, ctx):
        del ctx
        raise TypeError("opaque runtime callsite")


class CompleteZeroSugar:
    def desugar(self, ctx):
        del ctx
        return Complete(TermValue(0))


def _receiver(method_name: str, sugar: object) -> ObjectValue:
    return ObjectValue(
        class_name=f"{method_name}Owner",
        fields=(),
        methods=(
            ObjectMethodValue(
                name=method_name,
                parameters=("self",),
                body=SugarBody(sugar, SugarRole.TERM),
            ),
        ),
    )


def _body() -> SugarBody:
    return SugarBody(CompleteZeroSugar(), SugarRole.TERM)


DUNDER_CASES = (
    DunderCase(
        label="await",
        method_name="__await__",
        invoke=lambda receiver, ctx: AwaitOperation().await_object(receiver, ctx),
    ),
    DunderCase(
        label="async_iter",
        method_name="__aiter__",
        invoke=lambda receiver, ctx: AsyncIteratorOperation(
            body=_body(), target_name="item"
        ).async_iter_object(receiver, ctx),
    ),
    DunderCase(
        label="context_manager",
        method_name="__enter__",
        invoke=lambda receiver, ctx: ContextManagerOperation(
            body=_body()
        ).context_object(receiver, ctx),
    ),
    DunderCase(
        label="async_context_manager",
        method_name="__aenter__",
        invoke=lambda receiver, ctx: AsyncContextManagerOperation(
            body=_body()
        ).async_context_object(receiver, ctx),
    ),
)


@pytest.mark.parametrize(
    "case", DUNDER_CASES, ids=[case.label for case in DUNDER_CASES]
)
def test_dunder_reduction_factory_typeerror_is_loud(case: DunderCase) -> None:
    receiver = _receiver(case.method_name, MissingDesugarSugar())
    ctx = ReduceContext.root(owner=f"{case.label} laundering tooth")

    with pytest.raises(TypeError) as raised:
        case.invoke(receiver, ctx)

    assert "write more Floor for this Construction" in str(raised.value)
    assert "owner=SugarBody" in str(raised.value)


@pytest.mark.parametrize(
    "case", DUNDER_CASES, ids=[case.label for case in DUNDER_CASES]
)
def test_dunder_opaque_runtime_typeerror_stays_incomplete(case: DunderCase) -> None:
    receiver = _receiver(case.method_name, OpaqueRuntimeSugar())
    ctx = ReduceContext.root(owner=f"{case.label} opaque twin")

    outcome = case.invoke(receiver, ctx)

    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, RuntimeEffect)
    assert "opaque runtime callsite" in outcome.reason
