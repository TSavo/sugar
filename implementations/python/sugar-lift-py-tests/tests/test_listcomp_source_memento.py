# SPDX-License-Identifier: MIT OR Apache-2.0
"""Static loop unfolding must preserve nested comprehension mementos."""

from __future__ import annotations

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.lift_rpc import lift_file_payload
from sugar_lift_py_tests.sugar_body import SugarBody

SOURCE = (
    "def test_values():\n"
    "    for conv in [lambda x: [(i, i) for i in x]]:\n"
    "        assert 1 == 1\n"
)


def _for_site(*, carry_source: bool) -> SourceFragment:
    root = SourceFragment.from_source(SOURCE, "t.py")
    site = next(child for child in root.walk() if child.observed == "For")
    if carry_source:
        return site
    return SourceFragment.from_node(site.node, "<missing-source-test>")


def _factory_walk(site: SourceFragment) -> tuple:
    ctx = FactoryBuildContext(filename=site.filename, catalog=default_catalog())
    result = build_node(site, filename=site.filename, role=SugarRole.STATEMENT, ctx=ctx)
    return SugarBody(
        sugar=result.sugar, role=SugarRole.STATEMENT, audit_row=result.audit_row
    ).factory_walk_rows()


def test_static_iterable_preserves_listcomp_source_memento() -> None:
    rows = _factory_walk(_for_site(carry_source=True))
    listcomp = next(row for row in rows if row.ast_kind == "ListComp")
    assert listcomp.source_memento.source_cid


def test_static_iterable_does_not_invent_missing_source() -> None:
    try:
        _factory_walk(_for_site(carry_source=False))
    except FactoryPanic as caught:
        assert caught.info.owner == "SourceFragment"
        assert caught.info.observed == "For"
    else:
        raise AssertionError("source-less ListComp memento must panic")


def test_static_iterable_listcomp_conserves_assertion_mass() -> None:
    rpc = lift_file_payload(SOURCE, "t.py").to_rpc()
    assertions = account_lift_coverage(
        census_source(SOURCE, file="t.py"), rpc
    ).to_json()["assertions"]
    assert assertions["stated"] == 1
    assert assertions["silently_unaccounted"] == 0
