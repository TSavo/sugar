# SPDX-License-Identifier: MIT OR Apache-2.0
"""#5338 family D: native/extension dig must not hang on cold import.

Residual: sklearn/manifold/tests/test_t_sne.py timeout 30s, mechanism
``other_dig`` tip ``sklearn.manifold._utils._binary_search_perplexity``.

Profile: dig.resolve_value stuck with sequence frozen while
``_resolve_qualified_native_callable`` cold-imported the package extension
(``importlib.import_module("sklearn.manifold._utils")`` pulls sklearn init).
That is dig-body authority seeking, not reduce_body term volume.

Replacement architecture: PathFinder origin alone yields
``NativeCallableValue`` / bodyless ``CallSiteValue`` for package extensions.
Refuse dig body (force_floor missing-body FactoryPanic). Never timeout.
Never soft-complete. Never reclassify a native crash as timeout.

R axis: package-extension cold import during dig.resolve_value (offender=1).
Epsilon R: -1 when nested package extensions resolve without import_module.
"""

from __future__ import annotations

import importlib
import importlib.machinery
import sys
import time
from types import SimpleNamespace

import pytest

from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import CallSiteValue, NativeCallableValue, TermValue
from sugar_lift_py_tests.floor.call_site_value import force_floor
from sugar_lift_py_tests.ir import ctor
from sugar_lift_py_tests.sugar.install_source_dig import (
    INSTALL_SOURCE_VALUE_ORACLE,
    _resolve_qualified_native_callable,
    resolve_install_source_value,
)
from sugar_lift_py_tests.temporal import TemporalContext


def _ctx() -> FactoryBuildContext:
    return FactoryBuildContext(
        filename="t.py",
        catalog=default_catalog(),
        temporal=TemporalContext.empty(),
    )


def _patch_nested_extension(
    monkeypatch: pytest.MonkeyPatch, *, origin: str
) -> None:
    """PathFinder mock that only claims the fixture package tree.

    Dig looks up nested packages as ``find_spec(last_component, parent_path)``.
    All other lookups delegate to the real PathFinder so sugar imports stay live.
    """
    real_find_spec = importlib.machinery.PathFinder.find_spec

    def find_spec(fullname, path=None, target=None):
        name, search_path = fullname, path
        if name == "vendor" and search_path is None:
            return SimpleNamespace(
                submodule_search_locations=["/vendor"], origin=None, loader=None
            )
        if name == "pkg" and search_path == ["/vendor"]:
            return SimpleNamespace(
                submodule_search_locations=["/vendor/pkg"],
                origin=None,
                loader=None,
            )
        if name == "_native" and search_path == ["/vendor/pkg"]:
            return SimpleNamespace(
                submodule_search_locations=None,
                origin=origin,
                loader=importlib.machinery.ExtensionFileLoader(
                    "vendor.pkg._native", origin
                ),
            )
        return real_find_spec(fullname, path, target)

    monkeypatch.setattr(
        importlib.machinery.PathFinder, "find_spec", staticmethod(find_spec)
    )
    for key in list(sys.modules):
        if key == "vendor" or key.startswith("vendor."):
            del sys.modules[key]


def test_nested_package_extension_resolves_native_callable_without_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PathFinder origin is enough; dig must not cold-import package trees."""
    suffix = importlib.machinery.EXTENSION_SUFFIXES[0]
    origin = f"/vendor/pkg/_native{suffix}"
    target = "vendor.pkg._native.exact_symbol"
    import_calls: list[str] = []

    _patch_nested_extension(monkeypatch, origin=origin)

    def ban_import(name, package=None):
        import_calls.append(name)
        raise AssertionError(
            f"dig must not cold-import package extension {name!r}; "
            "return NativeCallableValue from PathFinder origin"
        )

    monkeypatch.setattr(importlib, "import_module", ban_import)

    t0 = time.perf_counter()
    native = _resolve_qualified_native_callable(target)
    elapsed = time.perf_counter() - t0

    assert isinstance(native, NativeCallableValue), (
        f"package extension must be NativeCallableValue (loud coordinate), "
        f"got {type(native).__name__}: {native!r}"
    )
    assert native.qualified_name == target
    assert native.module_origin == origin
    assert import_calls == [], f"cold import forbidden during dig: {import_calls}"
    assert elapsed < 0.25, (
        f"nested native resolve must terminate immediately, took {elapsed:.3f}s "
        "(hang residual was dig.resolve_value frozen on package import)"
    )


def test_install_source_value_oracle_publishes_native_without_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sole constructor door: dig.resolve_value must exit dig.construct.native."""
    suffix = importlib.machinery.EXTENSION_SUFFIXES[0]
    origin = f"/vendor/pkg/_native{suffix}"
    target = "vendor.pkg._native.exact_symbol"

    # Build catalog first so PathFinder mock cannot break sugar package import.
    ctx = _ctx()
    _patch_nested_extension(monkeypatch, origin=origin)

    import_calls: list[str] = []
    real_import = importlib.import_module

    def ban_vendor_import(name, package=None):
        if name == "vendor" or name.startswith("vendor."):
            import_calls.append(name)
            raise AssertionError(f"oracle resolve must not import {name!r}")
        return real_import(name, package)

    monkeypatch.setattr(importlib, "import_module", ban_vendor_import)
    INSTALL_SOURCE_VALUE_ORACLE.clear()

    resolved = resolve_install_source_value(target, ctx)
    assert isinstance(resolved, NativeCallableValue)
    assert resolved.qualified_name == target
    assert import_calls == []
    again = resolve_install_source_value(target, ctx)
    assert again == resolved


def test_native_callsite_refuses_dig_body_loudly_not_timeout() -> None:
    """body=None native CallSiteValue: force_floor is FactoryPanic, not hang."""
    callsite = CallSiteValue(
        target_name="vendor.pkg._native.exact_symbol",
        arg_values=(TermValue(1),),
        parameters=("x",),
        term=ctor(
            "call:vendor.pkg._native.exact_symbol",
            [ctor("1", [])],
            symbol_kind="contract-target",
        ),
        body=None,
        site=None,
    )
    with pytest.raises(FactoryPanic) as raised:
        force_floor(
            callsite,
            _ctx(),
            owner="test_extension_dig_refuse",
        )
    assert raised.value.info.observed == "missing callsite body"
    assert "exact_symbol" in raised.value.info.blame or "exact_symbol" in (
        raised.value.info.fix or ""
    )
