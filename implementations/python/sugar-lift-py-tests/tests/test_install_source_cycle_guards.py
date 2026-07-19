"""#5368: install-source recursion guards terminate loudly, never opaquely."""

from __future__ import annotations

import ast
import importlib

import pytest

import sugar_lift_py_tests.sugar.install_source_dig as install_source_dig
from sugar_lift_py_tests.context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.sugar.install_source_dig import (
    _base_is_exception,
    _installed_class_is_exception,
    _resolve_install_source_class_bases,
    _resolve_qualified_function_fragment,
    _resolve_qualified_native_callable,
    build_dig_body,
    resolve_install_source_value,
)


def _ctx(*, building: frozenset[str] = frozenset()) -> FactoryBuildContext:
    return FactoryBuildContext(
        filename="cycle_guard.py",
        catalog=default_catalog(),
        building=building,
    )


@pytest.mark.parametrize(
    ("resolver", "guard"),
    (
        (_resolve_qualified_native_callable, "native-callable"),
        (_resolve_qualified_function_fragment, "function-fragment"),
    ),
)
def test_qualified_resolver_cycle_guards_are_typed_loud(resolver, guard) -> None:
    target = "cycle_guard_pkg.value"

    with pytest.raises(FactoryPanic) as panic:
        resolver(target, resolving=frozenset({target}))

    assert panic.value.info.owner == "install_source_cycle_guard"
    assert panic.value.info.observed == f"{guard} cycle: {target}"


def test_reexport_cycle_is_typed_loud(tmp_path, monkeypatch) -> None:
    (tmp_path / "cycle_left.py").write_text(
        "from cycle_right import VALUE\n", encoding="utf-8"
    )
    (tmp_path / "cycle_right.py").write_text(
        "from cycle_left import VALUE\n", encoding="utf-8"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()

    with pytest.raises(FactoryPanic) as panic:
        resolve_install_source_value("cycle_left.VALUE", _ctx())

    assert panic.value.info.owner == "install_source_cycle_guard"
    assert panic.value.info.observed == "native-callable cycle: cycle_left.VALUE"


def test_reexport_value_guard_itself_is_typed_loud(tmp_path, monkeypatch) -> None:
    (tmp_path / "cycle_left.py").write_text(
        "from cycle_right import VALUE\n", encoding="utf-8"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    monkeypatch.setattr(
        install_source_dig,
        "_resolve_qualified_native_callable",
        lambda *_args, **_kwargs: None,
    )

    with pytest.raises(FactoryPanic) as panic:
        install_source_dig._construct_install_source_value(
            "cycle_left.VALUE",
            _ctx(),
            _resolving=frozenset({"cycle_left.VALUE", "cycle_right.VALUE"}),
        )

    assert panic.value.info.owner == "install_source_cycle_guard"
    assert panic.value.info.observed == "re-export cycle: cycle_right.VALUE"


def test_installed_class_base_cycle_guard_is_typed_loud() -> None:
    target = "cycle_guard_pkg.Node"

    with pytest.raises(FactoryPanic) as panic:
        _resolve_install_source_class_bases(target, frozenset({target}))

    assert panic.value.info.owner == "install_source_cycle_guard"
    assert panic.value.info.observed == f"class-bases cycle: {target}"


def test_exception_ancestry_cycle_guards_are_typed_loud() -> None:
    parsed = ast.parse("class Node(Exception):\n    pass\n")
    qualified = "cycle_guard_pkg.Node"

    with pytest.raises(FactoryPanic) as class_panic:
        _installed_class_is_exception(
            "cycle_guard_pkg",
            "Node",
            parsed,
            resolving=frozenset({qualified}),
        )
    assert class_panic.value.info.owner == "install_source_cycle_guard"
    assert class_panic.value.info.observed == f"exception-ancestry cycle: {qualified}"

    target = "cycle_guard_other.Node"
    with pytest.raises(FactoryPanic) as base_panic:
        _base_is_exception(
            ast.Name(id="Alias"),
            module_name="cycle_guard_pkg",
            parsed=parsed,
            classes={},
            imports={"Alias": target},
            resolving=frozenset({target}),
        )
    assert base_panic.value.info.owner == "install_source_cycle_guard"
    assert base_panic.value.info.observed == f"exception-base cycle: {target}"


def test_dig_body_build_cycle_guard_is_typed_loud() -> None:
    fn = SourceFragment.from_node(
        ast.parse("def recurse():\n    return recurse()\n").body[0],
        "cycle_guard.py",
    )

    with pytest.raises(FactoryPanic) as panic:
        build_dig_body(fn, _ctx(building=frozenset({"recurse"})))

    assert panic.value.info.owner == "install_source_cycle_guard"
    assert panic.value.info.observed == "dig-body cycle: recurse"
