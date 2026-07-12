from __future__ import annotations

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory import FactoryPanic
from sugar_lift_py_tests.factory.build import build_next, default_catalog
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import ModuleBoundVar, TermValue
from sugar_lift_py_tests.lift_rpc import audit_lift_file
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.temporal import TemporalContext


def test_global_sugar_witness_keeps_default_catalog_importable() -> None:
    catalog = default_catalog()
    root = SourceFragment.from_source(
        "def assign():\n    global shared\n    shared = 7\n",
        "global_catalog.py",
    )
    global_site = next(site for site in root.walk() if site.observed == "Global")

    candidates = catalog.candidates_for(SugarRole.STATEMENT, global_site)
    assert [candidate.name for candidate in candidates] == ["GlobalSugar"]


def test_global_write_routes_through_module_temporal_and_reads_back() -> None:
    source = (
        "shared = 1\n"
        "def set_shared():\n"
        "    global shared\n"
        "    shared = 7\n"
        "    return shared\n"
    )

    payload, gaps = audit_lift_file(source, "global_binding.py")
    assert not gaps
    row = next(row for row in payload.ir if row.name == "set_shared")
    assert row.post["args"][1]["value"] == 7


def test_undeclared_name_remains_loud() -> None:
    with pytest.raises(FactoryPanic, match="observed=missing requested=value"):
        audit_lift_file(
            "def read():\n    return missing\n",
            "undefined.py",
            hold_panic=False,
        )


def test_global_without_static_module_frame_panics() -> None:
    catalog = default_catalog()
    ctx = FactoryBuildContext(filename="dynamic.py", catalog=catalog)
    result = build_next("global shared\n", "dynamic.py", SugarRole.STATEMENT, ctx=ctx)

    with pytest.raises(FactoryPanic, match="statically known module temporal"):
        result.sugar.reduce(ctx)


def test_module_bound_var_updates_live_and_module_temporals() -> None:
    module_temporal = TemporalContext.empty().bind_value("shared", TermValue(1))
    ctx = FactoryBuildContext(
        filename="global_binding.py",
        catalog=default_catalog(),
        temporal=module_temporal,
        module_temporal=module_temporal,
        global_names=frozenset({"shared"}),
    )
    marker = ModuleBoundVar("shared", Complete(TermValue(7)), scope=ctx)

    updated = marker.extend_scope(ctx)
    assert updated.temporal.value_for("shared") is marker
    assert updated.module_temporal is not None
    assert updated.module_temporal.value_for("shared") is marker
