from __future__ import annotations

import importlib

import pytest

from factory_reduce import compose_block

from sugar_lift_py_tests.context import FactoryBuildContext
from sugar_lift_py_tests.factory import FactoryPanic
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.floor import (
    ExceptionClassValue,
    ExceptionValue,
    ImportAliasValue,
    RaiseValue,
)
from sugar_lift_py_tests.sugar.install_source_dig import resolve_install_source_value


def _ctx() -> FactoryBuildContext:
    return FactoryBuildContext(filename="consumer.py", catalog=default_catalog())


def _module(tmp_path, monkeypatch, name: str, source: str) -> str:
    (tmp_path / f"{name}.py").write_text(source, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    return f"{name}.CustomError"


def test_exact_imported_exception_subclass_constructs_routeable_raise(
    tmp_path, monkeypatch
) -> None:
    target = _module(
        tmp_path,
        monkeypatch,
        "source_exception",
        "class CustomError(ValueError):\n" "    pass\n",
    )
    resolved = resolve_install_source_value(target, _ctx())

    assert resolved == ExceptionClassValue(target)

    block = compose_block(
        "    raise CustomError('bad')\n",
        binds={
            "CustomError": ImportAliasValue(
                "CustomError",
                "CustomError",
                import_target=target,
                resolved_value=resolved,
            )
        },
    )

    raised = block.statements[0]
    assert isinstance(raised, RaiseValue)
    assert isinstance(raised.exception, ExceptionValue)
    assert raised.effect.exception_name == target


def test_transitive_same_module_exception_ancestry_is_constructed(
    tmp_path, monkeypatch
) -> None:
    target = _module(
        tmp_path,
        monkeypatch,
        "transitive_exception",
        "class PackageError(Exception):\n"
        "    pass\n"
        "class CustomError(PackageError):\n"
        "    pass\n",
    )

    assert resolve_install_source_value(target, _ctx()) == ExceptionClassValue(target)


def test_imported_ordinary_class_wrong_twin_stays_named_raise_gap(
    tmp_path, monkeypatch
) -> None:
    target = _module(
        tmp_path,
        monkeypatch,
        "source_ordinary",
        "class CustomError(object):\n" "    pass\n",
    )
    resolved = resolve_install_source_value(target, _ctx())

    assert not isinstance(resolved, ExceptionClassValue)
    with pytest.raises(FactoryPanic) as raised:
        compose_block(
            "    raise CustomError('bad')\n",
            binds={
                "CustomError": ImportAliasValue(
                    "CustomError",
                    "CustomError",
                    import_target=target,
                    resolved_value=resolved,
                )
            },
        )

    assert raised.value.info.owner == "RaiseSugar"
    assert raised.value.info.observed == "CallSiteValue"
    assert raised.value.info.requested == "constructed exception floor"
