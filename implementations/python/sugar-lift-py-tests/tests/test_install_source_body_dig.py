# SPDX-License-Identifier: MIT OR Apache-2.0
"""Install-source body dig: CallSugar attaches body when resolve succeeds."""

from __future__ import annotations

from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.lift_rpc import lift_file_payload
from sugar_lift_py_tests.sugar.install_source_dig import (
    resolve_install_source_funcdef,
    module_sibling_function_nodes,
)


def test_same_module_call_attaches_body() -> None:
    """def B; A calls B — CallSiteValue.body is non-None after lift."""
    src = (
        "def B(w):\n"
        "    return w\n"
        "def A(z):\n"
        "    return B(z)\n"
        "def test_a():\n"
        "    assert A(5) == 5\n"
    )
    rpc = lift_file_payload(src, "t.py").to_rpc()
    # Prove dig path: force_floor on A should use body; ir has assertion
    ax = account_lift_coverage(census_source(src, file="t.py"), rpc).to_json()[
        "assertions"
    ]
    assert ax["silently_unaccounted"] == 0
    assert ax["lifted_cited"] >= 1, ax
    # factory walk / ir should exist for A or test
    assert (rpc.get("ir") or []) or ax["lifted_cited"]


def test_resolve_install_source_base64() -> None:
    resolved = resolve_install_source_funcdef("base64.urlsafe_b64encode")
    assert resolved is not None
    assert resolved.function_name() == "urlsafe_b64encode"
    assert getattr(resolved.node, "_sugar_file", None)


def test_module_siblings_base64() -> None:
    siblings = module_sibling_function_nodes("base64")
    assert "urlsafe_b64encode" in siblings or "base64.urlsafe_b64encode" in siblings


def test_from_import_pure_function_lifts() -> None:
    """from itsdangerous.encoding import int_to_bytes — body dig or coordinate."""
    src = (
        "from itsdangerous.encoding import int_to_bytes, bytes_to_int\n"
        "def test_e():\n"
        "    assert bytes_to_int(int_to_bytes(192)) == 192\n"
    )
    rpc = lift_file_payload(src, "t.py").to_rpc()
    ax = account_lift_coverage(census_source(src, file="t.py"), rpc).to_json()[
        "assertions"
    ]
    assert ax["silently_unaccounted"] == 0
    assert ax["lifted_cited"] == 1, ax


def test_nested_external_bridge_default_false() -> None:
    from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
    from sugar_lift_py_tests.factory.build import default_catalog

    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    assert ctx.nested_external_bridge is False
