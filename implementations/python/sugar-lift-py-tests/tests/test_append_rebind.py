"""Mutation is a rebind: `xs.append(v)` rebinds xs to the updated list. Concrete
history folds; the append statement contributes nothing to the block record
(scope only). Aliasing stays a loud gap -- not this PR."""

from __future__ import annotations

import ast
from dataclasses import replace

import pytest

from factory_reduce import compose_block

from sugar_lift_py_tests.claim import SugarCatalog, SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import (
    BlockValue,
    CallSiteValue,
    ListValue,
    ReturnValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.lift_rpc import audit_lift_file


def test_append_folds_history_into_returned_list() -> None:
    record = compose_block("    xs = [1]\n    xs.append(2)\n    return xs\n")
    assert record == BlockValue((ReturnValue(ListValue((TermValue(1), TermValue(2)))),))


def test_append_statement_contributes_nothing_to_the_record() -> None:
    record = compose_block("    xs = [1]\n    xs.append(2)\n    return xs\n")
    assert len(record.statements) == 1


def test_append_on_unbound_name_panics() -> None:
    with pytest.raises(FactoryPanic):
        compose_block("    xs.append(2)\n    return xs\n")


def test_append_on_term_value_panics() -> None:
    with pytest.raises(FactoryPanic):
        compose_block("    x = 1\n    x.append(2)\n    return x\n")


def test_two_appends_compose() -> None:
    record = compose_block(
        "    xs = [1]\n    xs.append(2)\n    xs.append(3)\n    return xs\n"
    )
    assert record == BlockValue(
        (ReturnValue(ListValue((TermValue(1), TermValue(2), TermValue(3)))),)
    )


def test_append_owner_precedes_the_general_method_owner() -> None:
    site = SourceFragment.from_node(
        ast.parse("xs.append(2)", mode="eval").body, "append.py"
    )
    catalog = default_catalog()
    ctx = FactoryBuildContext(filename="append.py", catalog=catalog)

    built = build_node(site, filename="append.py", role=SugarRole.TERM, ctx=ctx)

    assert type(built.sugar).__name__ == "AppendCallSugar"
    assert set(built.audit_row.candidates) == {
        "MethodCallSugar",
        "AppendCallSugar",
    }


def test_simultaneous_append_owners_without_edge_name_missing_order() -> None:
    site = SourceFragment.from_node(
        ast.parse("xs.append(2)", mode="eval").body, "append.py"
    )
    claims = [
        replace(candidate.claim, comes_before=())
        for candidate in default_catalog().candidates_for(SugarRole.TERM, site)
    ]
    catalog = SugarCatalog(claims)
    ctx = FactoryBuildContext(filename="append.py", catalog=catalog)

    with pytest.raises(FactoryPanic) as raised:
        build_node(site, filename="append.py", role=SugarRole.TERM, ctx=ctx)

    message = str(raised.value)
    assert "MethodCallSugar" in message
    assert "AppendCallSugar" in message
    assert "missing comes_before edge" in message


def test_append_on_callsite_rebinds_to_list_append_coordinate() -> None:
    """Opaque split/slice results rebind through py.list_append, never panic."""
    record = compose_block(
        '    xs = s.split(".")[:3]\n    xs.append("0")\n    return xs\n',
        binds={"s": SymbolicValue(make_var("s"))},
    )

    assert isinstance(record, BlockValue)
    assert len(record.statements) == 1
    returned = record.statements[0]
    assert isinstance(returned, ReturnValue)
    assert isinstance(returned.value, CallSiteValue)
    assert returned.value.target_name == "list.append"
    assert returned.value.term.name == "py.list_append"


def test_requests_check_compatibility_asserts_lift_through_append() -> None:
    """Part of #4103: the five requests __init__ asserts speak after append floor.

    Vendor shape (requests 2.34.2 ``check_compatibility``): symbolic
    ``version.split(".")[:3]`` then a guarded ``.append("0")`` before the
    version-gate asserts. Before CallSiteValue.append_with, the append panic
    poisoned the whole definition (0 lifted). After: 5 lifted, 0 silent.
    """
    source = """
def check_compatibility(urllib3_version, chardet_version, charset_normalizer_version):
    urllib3_version_list = urllib3_version.split(".")[:3]
    assert urllib3_version_list != ["dev"]

    if len(urllib3_version_list) == 2:
        urllib3_version_list.append("0")

    major, minor, patch = urllib3_version_list
    major, minor, patch = int(major), int(minor), int(patch)
    assert major >= 1
    if major == 1:
        assert minor >= 21

    if chardet_version:
        major, minor, patch = chardet_version.split(".")[:3]
        major, minor, patch = int(major), int(minor), int(patch)
        assert (3, 0, 2) <= (major, minor, patch) < (8, 0, 0)
    elif charset_normalizer_version:
        major, minor, patch = charset_normalizer_version.split(".")[:3]
        major, minor, patch = int(major), int(minor), int(patch)
        assert (2, 0, 0) <= (major, minor, patch) < (4, 0, 0)
"""
    payload, _gaps = audit_lift_file(source, "requests/__init__.py")
    axis = account_lift_coverage(
        census_source(source, file="requests/__init__.py"), payload.to_rpc()
    ).to_json()["assertions"]

    assert axis["stated"] == 5
    assert axis["lifted_cited"] == 5
    assert axis["refused_loud"] == 0
    assert axis["silently_unaccounted"] == 0
    assert [locus["line"] for locus in axis["lifted_loci"]] == [4, 11, 13, 18, 22]
