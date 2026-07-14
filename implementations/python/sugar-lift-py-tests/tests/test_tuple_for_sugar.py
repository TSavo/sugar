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


def test_starred_target_stays_loud() -> None:
    source = "for a, *rest in rows:\n    pass\n"
    ctx = FactoryBuildContext(filename="vendor.py", catalog=default_catalog())
    with pytest.raises(FactoryPanic):
        build_node(
            ast.parse(source).body[0],
            filename="vendor.py",
            role=SugarRole.STATEMENT,
            ctx=ctx,
        )


def test_tuple_for_else_uses_break_projection_owner() -> None:
    source = "for a, b in rows:\n    pass\nelse:\n    pass\n"
    ctx = FactoryBuildContext(filename="vendor.py", catalog=default_catalog())
    built = build_node(
        ast.parse(source).body[0],
        filename="vendor.py",
        role=SugarRole.STATEMENT,
        ctx=ctx,
    )
    assert type(built.sugar).__name__ == "ForElseSugar"


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


@pytest.mark.parametrize("arity", [3, 4, 5, 6])
def test_flat_multi_name_target_binds_each_projection(arity: int) -> None:
    names = [f"item_{index}" for index in range(arity)]
    block = compose_block(
        f"    for {', '.join(names)} in rows:\n        return {names[-1]}\n",
        binds={"rows": SymbolicValue(make_var("rows"))},
    )

    returned = next(
        entry for entry in block.statements if isinstance(entry, ReturnValue)
    )
    element = ctor("py.iter_elem", [make_var("rows")])
    assert returned.value.term == ctor("py.subscript", [element, num(arity - 1)])


def test_flat_all_name_target_owner_accepts_any_arity_from_two_up() -> None:
    catalog = default_catalog()
    for target in ("a, b", "a, b, c", "a, b, c, d, e, f"):
        site = _site(f"for {target} in rows:\n    pass\n")
        assert [
            candidate.name
            for candidate in catalog.candidates_for(SugarRole.STATEMENT, site)
        ] == ["TupleForSugar"]


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


@pytest.mark.parametrize(
    ("target", "returned", "path"),
    [
        ("i, (label, size)", "size", (1, 1)),
        ("(row, col), cell", "row", (0, 0)),
    ],
)
def test_nested_tuple_target_binds_recursive_projection(
    target: str, returned: str, path: tuple[int, ...]
) -> None:
    block = compose_block(
        f"    for {target} in rows:\n        return {returned}\n",
        binds={"rows": SymbolicValue(make_var("rows"))},
    )

    value = next(
        entry.value for entry in block.statements if isinstance(entry, ReturnValue)
    )
    expected = ctor("py.iter_elem", [make_var("rows")])
    for index in path:
        expected = ctor("py.subscript", [expected, num(index)])
    assert value.term == expected


def test_nested_tuple_owner_excludes_starred_and_for_else() -> None:
    from sugar_lift_py_tests.sugar.nested_tuple_for_sugar import NestedTupleForSugar

    assert NestedTupleForSugar.owns(_site("for i, (x, y) in rows:\n    pass\n"))
    assert not NestedTupleForSugar.owns(_site("for i, (x, *rest) in rows:\n    pass\n"))
    assert not NestedTupleForSugar.owns(
        _site("for i, (x, y) in rows:\n    pass\nelse:\n    pass\n")
    )
