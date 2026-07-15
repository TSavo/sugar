# SPDX-License-Identifier: MIT OR Apache-2.0
"""Resident ownership laws for installed Python source and audit contexts."""

from __future__ import annotations

import dataclasses
import gc
import types
import weakref

import pytest

import sugar_lift_py_tests.sugar.install_source_dig as install_source_dig


def test_installed_source_index_is_bounded_and_evicted_entries_are_collectible(
    monkeypatch,
) -> None:
    """More distinct modules than the cache capacity must release old indexes."""
    install_source_dig._installed_source_index.cache_clear()
    monkeypatch.setattr(
        install_source_dig,
        "_installed_source",
        lambda module_name: (
            f"def owned_{module_name}(value):\n    return value\n",
            f"/{module_name}.py",
        ),
    )

    capacity = install_source_dig.INSTALLED_SOURCE_INDEX_CAPACITY
    first = install_source_dig._installed_source_index("owned_module_0")
    first_ref = weakref.ref(first)
    del first

    for index in range(1, capacity + 2):
        install_source_dig._installed_source_index(f"owned_module_{index}")

    gc.collect()

    cache = install_source_dig._installed_source_index.cache_info()
    assert cache.maxsize == capacity
    assert cache.currsize == capacity
    assert first_ref() is None


def test_installed_source_resolvers_return_fresh_ast_nodes(
    tmp_path, monkeypatch
) -> None:
    """The bounded index owns immutable source data, never caller-mutable ASTs."""
    module_name = "resident_source_alias_fixture"
    (tmp_path / f"{module_name}.py").write_text(
        "def helper(value):\n"
        "    return value\n"
        "\n"
        "class Owner:\n"
        "    def method(self, value):\n"
        "        return helper(value)\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    install_source_dig._installed_source_index.cache_clear()

    first_siblings = install_source_dig.module_sibling_function_nodes(module_name)
    first_function = install_source_dig.resolve_install_source_funcdef(
        f"{module_name}.helper"
    )
    first_method = install_source_dig.resolve_install_source_class_method(
        f"{module_name}.Owner", "method"
    )

    second_siblings = install_source_dig.module_sibling_function_nodes(module_name)
    second_function = install_source_dig.resolve_install_source_funcdef(
        f"{module_name}.helper"
    )
    second_method = install_source_dig.resolve_install_source_class_method(
        f"{module_name}.Owner", "method"
    )

    assert first_siblings["helper"] is not second_siblings["helper"]
    assert first_function is not None and second_function is not None
    assert first_function.node is not second_function.node
    assert first_method is not None and second_method is not None
    assert first_method.node is not second_method.node


def test_cached_audit_seed_panics_are_immutable_data_without_exception_graphs(
    monkeypatch,
) -> None:
    """Resident audit contexts may retain evidence, never exception ownership."""
    from sugar_lift_py_tests import lift_rpc
    from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
    from sugar_lift_py_tests.factory.factory_gap_info import (
        FactoryGapInfo,
        GapKind,
        GapLocus,
    )

    def panic_on_imported_value(*args, **kwargs):
        del args, kwargs
        raise FactoryPanic(
            FactoryGapInfo(
                owner="resident-ownership-test",
                blame="vendor_fixture.py:1:0",
                observed="UnsupportedValue",
                requested="construct imported value",
                fix="add the missing value constructor",
                gap_kind=GapKind.FLOOR,
                gap_locus=GapLocus.CONSTRUCTION,
            )
        )

    monkeypatch.setattr(
        install_source_dig,
        "resolve_install_source_value",
        panic_on_imported_value,
    )
    lift_rpc._AUDIT_FILE_CONTEXTS.clear()
    context = lift_rpc._audit_file_context(
        "from vendor_fixture import owned_value\n",
        "consumer_fixture.py",
        "resident-ownership-context-cid",
    )

    assert context is lift_rpc._AUDIT_FILE_CONTEXTS["resident-ownership-context-cid"]
    assert len(context.seed_panics) == 1
    evidence = context.seed_panics[0]
    assert dataclasses.is_dataclass(evidence)

    def assert_no_runtime_owner(value) -> None:
        assert not isinstance(
            value, (BaseException, types.TracebackType, types.FrameType)
        )
        if dataclasses.is_dataclass(value):
            for field in dataclasses.fields(value):
                assert_no_runtime_owner(getattr(value, field.name))
        elif isinstance(value, (tuple, frozenset)):
            for item in value:
                assert_no_runtime_owner(item)
        elif isinstance(value, dict):
            for key, item in value.items():
                assert_no_runtime_owner(key)
                assert_no_runtime_owner(item)

    assert_no_runtime_owner(evidence)
    with pytest.raises(dataclasses.FrozenInstanceError):
        evidence.locus = "mutated.py:1:0"
