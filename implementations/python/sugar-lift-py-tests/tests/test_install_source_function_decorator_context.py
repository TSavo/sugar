from __future__ import annotations

import importlib

import pytest

from sugar_lift_py_tests.context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import FunctionCallable, ImportAliasValue, TermValue
from sugar_lift_py_tests.sugar.install_source_dig import resolve_install_source_value
from sugar_lift_py_tests.temporal import TemporalContext


def _ctx(*, temporal: TemporalContext | None = None) -> FactoryBuildContext:
    return FactoryBuildContext(
        filename="consumer.py",
        catalog=default_catalog(),
        temporal=temporal or TemporalContext.empty(),
    )


def _module(tmp_path, monkeypatch, name: str, source: str) -> str:
    (tmp_path / f"{name}.py").write_text(source, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    return f"{name}.managed"


def test_install_source_function_constructs_direct_imported_decorator(
    tmp_path, monkeypatch
) -> None:
    target = _module(
        tmp_path,
        monkeypatch,
        "direct_decorator",
        "from contextlib import contextmanager\n"
        "@contextmanager\n"
        "def managed():\n"
        "    yield None\n",
    )

    resolved = resolve_install_source_value(target, _ctx())

    assert isinstance(resolved, FunctionCallable)
    assert resolved.name == "managed"
    assert len(resolved.decorators) == 1
    assert isinstance(resolved.decorators[0], ImportAliasValue)
    assert resolved.decorators[0].import_target == "contextlib.contextmanager"


def test_install_source_function_constructs_aliased_imported_decorator(
    tmp_path, monkeypatch
) -> None:
    target = _module(
        tmp_path,
        monkeypatch,
        "aliased_decorator",
        "from contextlib import contextmanager as managed_context\n"
        "@managed_context\n"
        "def managed():\n"
        "    yield None\n",
    )

    resolved = resolve_install_source_value(target, _ctx())

    assert isinstance(resolved, FunctionCallable)
    decorator = resolved.decorators[0]
    assert isinstance(decorator, ImportAliasValue)
    assert decorator.bound_name == "managed_context"
    assert decorator.import_target == "contextlib.contextmanager"


def test_defining_module_decorator_shadows_consumer_temporal(
    tmp_path, monkeypatch
) -> None:
    target = _module(
        tmp_path,
        monkeypatch,
        "shadowed_decorator",
        "from contextlib import contextmanager\n"
        "@contextmanager\n"
        "def managed():\n"
        "    yield None\n",
    )
    consumer = TemporalContext.empty().bind_value("contextmanager", TermValue(99))

    resolved = resolve_install_source_value(target, _ctx(temporal=consumer))

    assert isinstance(resolved, FunctionCallable)
    decorator = resolved.decorators[0]
    assert isinstance(decorator, ImportAliasValue)
    assert decorator.import_target == "contextlib.contextmanager"


def test_install_source_function_keeps_unbound_decorator_loud(
    tmp_path, monkeypatch
) -> None:
    target = _module(
        tmp_path,
        monkeypatch,
        "missing_decorator",
        "@missing\n" "def managed():\n" "    yield None\n",
    )

    with pytest.raises(FactoryPanic) as raised:
        resolve_install_source_value(target, _ctx())

    assert raised.value.info.owner == "TemporalContext"
    assert raised.value.info.observed == "missing"
    assert raised.value.info.requested == "value"


def test_install_source_function_constructs_minimal_pandas_option_context_shape(
    tmp_path, monkeypatch
) -> None:
    target = _module(
        tmp_path,
        monkeypatch,
        "pandas_config_shape",
        "from __future__ import annotations\n"
        "from contextlib import contextmanager\n"
        "options = {}\n"
        "@contextmanager\n"
        "def managed(*args) -> None:\n"
        "    old = options\n"
        "    yield args\n",
    )

    resolved = resolve_install_source_value(target, _ctx())

    assert isinstance(resolved, FunctionCallable)
    assert isinstance(resolved.decorators[0], ImportAliasValue)
