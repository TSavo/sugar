from __future__ import annotations

import importlib

from sugar_lift_py_tests.context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.floor import (
    CallSiteValue,
    FunctionCallable,
    PartialFunctionCallable,
)
from sugar_lift_py_tests.sugar.install_source_dig import resolve_install_source_value
from sugar_lift_py_tests.temporal import TemporalContext


def _ctx() -> FactoryBuildContext:
    return FactoryBuildContext(
        filename="consumer.py",
        catalog=default_catalog(),
        temporal=TemporalContext.empty(),
    )


def test_array_function_dispatch_partial_constructs_real_callsite_body(
    tmp_path, monkeypatch
) -> None:
    (tmp_path / "dispatch_owner.py").write_text(
        "import functools\n"
        "\n"
        "def dispatch_factory(dispatcher, module=None):\n"
        "    return dispatcher\n"
        "\n"
        "def dispatcher(value):\n"
        "    return (value,)\n"
        "\n"
        "array_function_dispatch = functools.partial(\n"
        "    dispatch_factory, module='numpy.linalg'\n"
        ")\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    ctx = _ctx()
    dispatch = resolve_install_source_value(
        "dispatch_owner.array_function_dispatch", ctx
    )
    dispatcher = resolve_install_source_value("dispatch_owner.dispatcher", ctx)

    assert isinstance(dispatch, FunctionCallable)
    assert isinstance(dispatcher, FunctionCallable)
    callsite = dispatch.callsite((dispatcher,), (), "decorator.py:1")

    assert isinstance(callsite.value, CallSiteValue)
    assert callsite.value.target_name == "dispatch_owner.dispatch_factory"
    assert callsite.value.body is not None
    assert (
        callsite.value.force_floor(
            ctx,
            owner="array-function-dispatch recognizer",
            project_callsite=False,
        )
        == dispatcher
    )


def test_numpy_array_function_dispatch_resolves_through_factory_callable() -> None:
    ctx = _ctx()
    dispatch = resolve_install_source_value(
        "numpy.linalg._linalg.array_function_dispatch", ctx
    )
    dispatcher = resolve_install_source_value(
        "numpy.linalg._linalg._tensorsolve_dispatcher", ctx
    )

    assert isinstance(dispatch, PartialFunctionCallable)
    assert isinstance(dispatcher, FunctionCallable)
    callsite = dispatch.callsite((dispatcher,), (), "numpy-enumerate.py:1")

    assert isinstance(callsite.value, CallSiteValue)
    assert callsite.value.target_name == "numpy._core.overrides.array_function_dispatch"
    assert callsite.value.body is not None


def test_lookalike_partial_facade_does_not_gain_callable_body(
    tmp_path, monkeypatch
) -> None:
    (tmp_path / "lookalike_dispatch.py").write_text(
        "import lookalike as functools\n"
        "\n"
        "def dispatch_factory(dispatcher, module=None):\n"
        "    return dispatcher\n"
        "\n"
        "array_function_dispatch = functools.partial(\n"
        "    dispatch_factory, module='numpy.linalg'\n"
        ")\n",
        encoding="utf-8",
    )
    (tmp_path / "lookalike.py").write_text("", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()

    resolved = resolve_install_source_value(
        "lookalike_dispatch.array_function_dispatch", _ctx()
    )

    assert isinstance(resolved, CallSiteValue)
    assert not isinstance(resolved, PartialFunctionCallable)
    assert resolved.target_name == "partial"
    assert resolved.body is None
