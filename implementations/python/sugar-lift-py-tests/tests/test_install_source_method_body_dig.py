# SPDX-License-Identifier: MIT OR Apache-2.0
"""MethodCallSugar install-source body dig."""

from __future__ import annotations

import importlib

import pytest

from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.lift_rpc import lift_file_payload
from sugar_lift_py_tests.sugar.install_source_dig import (
    bind_positional_defaults,
    build_dig_body,
    dig_parameters_for_body,
    resolve_install_source_class_method,
    resolve_method_funcdef,
)
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.floor import CallSiteValue, TermValue
from sugar_lift_py_tests.ir import ctor
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def test_resolve_signer_sign_method() -> None:
    fn = resolve_install_source_class_method("itsdangerous.Signer", "sign")
    assert fn is not None
    assert fn.function_name() == "sign"
    params = fn.function_params()
    assert "self" in params
    assert "value" in params
    assert getattr(fn.node, "_sugar_file", None)


def test_resolve_method_via_from_imports_and_ctor_receiver() -> None:
    ctx = FactoryBuildContext(
        filename="t.py",
        catalog=default_catalog(),
        from_imports={"Signer": ("itsdangerous", "Signer")},
    )
    recv = CallSiteValue(
        target_name="Signer",
        arg_values=(),
        parameters=(),
        term=ctor("call:Signer", []),
        body=None,
        site=None,
    )
    fn = resolve_method_funcdef("sign", recv, ctx)
    assert fn is not None
    assert fn.function_name() == "sign"


def test_same_module_class_method_lifts() -> None:
    src = (
        "class Box:\n"
        "    def get(self, x):\n"
        "        return x\n"
        "def test_b():\n"
        "    b = Box()\n"
        "    assert b.get(7) == 7\n"
    )
    rpc = lift_file_payload(src, "t.py").to_rpc()
    ax = account_lift_coverage(census_source(src, file="t.py"), rpc).to_json()[
        "assertions"
    ]
    assert ax["silently_unaccounted"] == 0
    assert ax["lifted_cited"] == 1, ax


def test_signer_sign_unsign_coordinate_still_lifts() -> None:
    """Vendor method path remains lifted (body dig or coordinate)."""
    src = (
        "from itsdangerous import Signer\n"
        "def test_s():\n"
        "    s = Signer('secret-key')\n"
        "    assert s.unsign(s.sign('value')) == b'value'\n"
    )
    rpc = lift_file_payload(src, "t.py").to_rpc()
    ax = account_lift_coverage(census_source(src, file="t.py"), rpc).to_json()[
        "assertions"
    ]
    assert ax["silently_unaccounted"] == 0
    assert ax["lifted_cited"] == 1, ax


def test_nested_external_bridge_default_false() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    assert ctx.nested_external_bridge is False


def _dig_installed_zero_arg_method(qualified_class: str, method_name: str):
    ctx = FactoryBuildContext(filename="consumer.py", catalog=default_catalog())
    fn = resolve_install_source_class_method(qualified_class, method_name)
    assert fn is not None
    body = build_dig_body(fn, ctx, require_attachable=True)
    assert body is not None
    receiver = CallSiteValue(
        target_name=qualified_class,
        arg_values=(),
        parameters=(),
        term=ctor(f"call:{qualified_class}", []),
        body=None,
        site=None,
    )
    completed = bind_positional_defaults(fn, (receiver,), ctx)
    arg_values = completed.value[1]
    parameters = dig_parameters_for_body(fn, len(arg_values), ())
    call = CallSiteValue(
        target_name=method_name,
        arg_values=arg_values,
        parameters=parameters,
        term=ctor(
            f"call:{method_name}",
            [value.to_term(owner="test") for value in arg_values],
        ),
        body=body,
        site=fn,
    )
    return call._dig_floor_or_none(ctx, owner="installed-method-module-context")


def test_installed_method_constructs_defining_module_import(
    tmp_path, monkeypatch
) -> None:
    (tmp_path / "method_helper.py").write_text("TOKEN = 7\n", encoding="utf-8")
    (tmp_path / "method_origin.py").write_text(
        "import method_helper as lib\n"
        "TOKEN = 7\n"
        "class Base:\n"
        "    def imported(self, value=TOKEN):\n"
        "        lib\n"
        "        return value\n",
        encoding="utf-8",
    )
    (tmp_path / "method_module.py").write_text(
        "from method_origin import Base\n" "class Box(Base):\n" "    pass\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()

    dug = _dig_installed_zero_arg_method("method_module.Box", "imported")

    assert dug == TermValue(7)


def test_installed_method_keeps_missing_module_binding_loud(
    tmp_path, monkeypatch
) -> None:
    (tmp_path / "missing_method_module.py").write_text(
        "class Box:\n" "    def missing(self):\n" "        return absent\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()

    with pytest.raises(FactoryPanic) as raised:
        _dig_installed_zero_arg_method("missing_method_module.Box", "missing")

    assert raised.value.info.owner == "TemporalContext"
    assert raised.value.info.observed == "absent"


def test_installed_method_module_default_truthful_and_lying_twins(
    tmp_path,
) -> None:
    def project(name: str):
        root = tmp_path / name
        root.mkdir()
        (root / "method_helper.py").write_text("TOKEN = 7\n", encoding="utf-8")
        (root / "method_origin.py").write_text(
            "from method_helper import TOKEN as lib\n"
            "DEFAULT = 7\n"
            "class Base:\n"
            "    def imported(self, value=DEFAULT):\n"
            "        lib\n"
            "        return value\n"
            "def observed():\n"
            "    return Base().imported() + 0\n",
            encoding="utf-8",
        )
        (root / "method_module.py").write_text(
            "from method_origin import Base\n" "class Box(Base):\n" "    pass\n",
            encoding="utf-8",
        )
        return root

    def source(expected: int) -> str:
        return (
            "from method_origin import observed\n"
            "def test_imported_default():\n"
            f"    assert observed() == {expected}\n"
        )

    truthful = run_source_through_real_solver(project("truthful"), source(7))
    lying = run_source_through_real_solver(project("lying"), source(8))

    assert truthful.verdict == "sat"
    assert lying.verdict == "unsat"
