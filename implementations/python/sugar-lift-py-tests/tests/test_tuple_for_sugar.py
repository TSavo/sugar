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


def _nditer_cleanup_source(*, extent: int) -> str:
    return f"""
import numpy as np

def rewrite():
    arr = np.arange({extent}).astype(">i,O")
    mask = np.random.randint(0, 2, size={extent}).astype(bool)
    it = np.nditer(
        [arr, mask],
        ["buffered", "refs_ok"],
        [["readwrite", "writemasked"], ["readonly", "arraymask"]],
        op_dtypes=["<i,O", "?"],
    )
    for buf, mask_buf in it:
        buf[...] = (3, object())
    del buf, mask_buf, it
    return 1
"""


def test_proven_nonempty_nditer_tuple_targets_survive_for_cleanup() -> None:
    recovered = audit_lift_file(
        _nditer_cleanup_source(extent=3),
        "numpy/_core/tests/test_nditer.py",
        recover_panics=True,
    )

    assert all(
        not (
            panic.gap["owner"] == "TemporalContext"
            and panic.gap["observed"] in {"buf", "mask_buf"}
        )
        for panic in recovered.panics
    )


def test_empty_nditer_does_not_invent_post_loop_tuple_bindings() -> None:
    recovered = audit_lift_file(
        _nditer_cleanup_source(extent=0),
        "numpy/_core/tests/test_nditer.py",
        recover_panics=True,
    )

    assert any(
        panic.gap["owner"] == "TemporalContext" and panic.gap["observed"] == "buf"
        for panic in recovered.panics
    )


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


def test_nested_tuple_empty_list_skips_body_so_fallthrough_digs() -> None:
    """#4387 nested residual: empty ListValue must not invent py.subscript returns.

    The catalog witness is ``A([])`` with fall-through ``return 0``. Dig must
    surface TermValue(0) so Derived EUF dual-refutes the lying arm.
    """
    from sugar_lift_py_tests.context import ReduceContext
    from sugar_lift_py_tests.floor import FunctionCallable, ListValue, TermValue
    from sugar_lift_py_tests.floor.call_site_value import force_floor
    from sugar_lift_py_tests.outcome import complete_value
    from sugar_lift_py_tests.temporal import TemporalContext

    source = (
        "def A(rows):\n"
        "    for i, (label, size) in rows:\n"
        "        return size\n"
        "    return 0\n"
    )
    module = ast.parse(source)
    fn = module.body[0]
    ctx = FactoryBuildContext(
        filename="t.py",
        catalog=default_catalog(),
        name_resolver={"A": fn},
    )
    built = build_node(fn, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)
    fn_val = complete_value(
        built.sugar.desugar(ReduceContext(temporal=TemporalContext.empty())),
        owner="nested-tuple-empty-def",
    )
    assert isinstance(fn_val, FunctionCallable)
    callsite = complete_value(
        fn_val.callsite((ListValue(()),), (), "site"),
        owner="nested-tuple-empty-call",
    )
    floor = force_floor(
        callsite,
        ReduceContext(temporal=TemporalContext.empty()),
        owner="nested-tuple-empty-dig",
    )
    assert floor == TermValue(0)
