"""Flat pair targets bind projections of one loop-element coordinate."""

from __future__ import annotations

import ast

import pytest
from factory_reduce import compose_block

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import CallSiteValue, ReturnValue, SymbolicValue
from sugar_lift_py_tests.ir import ctor, make_var, num
from sugar_lift_py_tests.lift_rpc import audit_lift_file


def _site(source: str) -> SourceFragment:
    return SourceFragment.from_node(ast.parse(source).body[0], "vendor.py")


def test_pair_target_binds_both_iter_element_projections() -> None:
    block = compose_block(
        "    for func_name, expected in rows:\n" "        return func_name\n",
        binds={"rows": SymbolicValue(make_var("rows"))},
    )

    returned = next(
        entry for entry in block.statements if isinstance(entry, ReturnValue)
    )
    assert isinstance(returned.value, CallSiteValue)
    element = ctor("py.iter_elem", [make_var("rows")])
    assert returned.value.term == ctor("py.subscript", [element, num(0)])


def test_nested_other_arity_and_for_else_targets_stay_loud() -> None:
    for source in (
        "for a, b, c in rows:\n    pass\n",
        "for a, (b, c) in rows:\n    pass\n",
        "for a, *rest in rows:\n    pass\n",
        "for a, b in rows:\n    pass\nelse:\n    pass\n",
    ):
        ctx = FactoryBuildContext(filename="vendor.py", catalog=default_catalog())
        with pytest.raises(FactoryPanic):
            build_node(
                ast.parse(source).body[0],
                filename="vendor.py",
                role=SugarRole.STATEMENT,
                ctx=ctx,
            )


def test_pair_for_owner_is_exactly_flat_two_name_no_else_partition() -> None:
    catalog = default_catalog()
    pair = _site("for left, right in rows:\n    pass\n")
    assert [
        candidate.name
        for candidate in catalog.candidates_for(SugarRole.STATEMENT, pair)
    ] == ["TupleForSugar"]

    simple = _site("for value in rows:\n    pass\n")
    assert [
        candidate.name
        for candidate in catalog.candidates_for(SugarRole.STATEMENT, simple)
    ] == ["ForSugar"]


def test_real_testing_file_shape_has_no_pair_for_factory_panic() -> None:
    source = """
def check_functions(func_names_and_expected):
    for func_name, expected in func_names_and_expected:
        return func_name
"""
    recovered = audit_lift_file(
        source,
        "_testing/__init__.py",
        recover_panics=True,
    )
    assert all(panic.gap["observed"] != "For" for panic in recovered.panics)
