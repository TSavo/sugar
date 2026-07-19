"""Partial/Async callsite must accept the authenticated native_shape coordinate.

#5322 vendor bare-exception surface (31/33 rows) was a pure signature drift:
factory/call paths pass ``native_shape=`` into ``FunctionCallable.callsite``,
but ``PartialFunctionCallable`` and ``AsyncFunctionCallable`` still used the
pre-coordinate signature and leaked bare ``TypeError``.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor.async_function_callable import AsyncFunctionCallable
from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
from sugar_lift_py_tests.floor.function_callable import FunctionCallable
from sugar_lift_py_tests.floor.partial_function_callable import PartialFunctionCallable
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.recognition.native_shape import NativeShape


def test_partial_callable_preserves_authenticated_native_shape() -> None:
    target = FunctionCallable(name="target", body=object())
    partial = PartialFunctionCallable(name="partial", target=target)

    callsite = complete_value(
        partial.callsite(
            (),
            (),
            "partial-native-shape.py:1",
            native_shape=NativeShape.ITERATOR,
        ),
        owner="test_partial_callable_preserves_authenticated_native_shape",
    )

    assert isinstance(callsite, CallSiteValue)
    assert callsite.native_shape is NativeShape.ITERATOR


def test_partial_callable_without_target_stays_typed_loud_with_native_shape() -> None:
    partial = PartialFunctionCallable(name="partial", target=None)

    with pytest.raises(FactoryPanic) as exc:
        partial.callsite(
            (),
            (),
            "partial-native-shape-wrong-twin.py:1",
            native_shape=NativeShape.ITERATOR,
        )

    # Must be structured FactoryPanic, never bare TypeError from **kwargs.
    assert not isinstance(exc.value, TypeError)
    assert "missing partial target" in str(exc.value)


def test_async_callable_preserves_native_shape_without_claiming_termination() -> None:
    callable_value = AsyncFunctionCallable(name="async_target", body=object())

    callsite = complete_value(
        callable_value.callsite(
            (),
            (),
            "async-native-shape.py:1",
            native_shape=NativeShape.ITERATOR,
        ),
        owner="test_async_callable_preserves_native_shape_without_claiming_termination",
    )

    assert isinstance(callsite, CallSiteValue)
    assert callsite.native_shape is NativeShape.ITERATOR
    # Async still refuses to replay a body on bare call.
    assert callsite.body is None
