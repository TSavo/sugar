# SPDX-License-Identifier: MIT OR Apache-2.0
"""MethodCallSugar install-source body dig."""

from __future__ import annotations

from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.lift_rpc import lift_file_payload
from sugar_lift_py_tests.sugar.install_source_dig import (
    resolve_install_source_class_method,
    resolve_method_funcdef,
)
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.floor import CallSiteValue
from sugar_lift_py_tests.ir import ctor


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
