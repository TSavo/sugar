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
    StringValue,
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


def test_append_sugar_enrolls_mutated_length_witness() -> None:
    from sugar_lift_py_tests.sugar.append_call_sugar import AppendCallSugar

    assert any(
        pair.name == "append_length_return" for pair in AppendCallSugar.witnesses()
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


def test_append_on_loop_callsite_rebinds_through_list_append() -> None:
    """Curried For list post-state (``loop:…``) stays list-shaped for append.

    Red residual after #5574 compact projection: public_api's second
    ``module_names.append`` hit ``CallSiteValue(loop:…)`` and panicked.
    """
    from sugar_lift_py_tests.ir import ctor
    from sugar_lift_py_tests.outcome import Complete

    prior = CallSiteValue(
        target_name="loop:f.py:1",
        arg_values=(ListValue((TermValue(1),)),),
        parameters=("xs",),
        term=ctor("call:loop:f.py:1", ()),
        body=None,
        site="f.py:1",
    )
    outcome = prior.append_with(TermValue(2), "f.py:2")
    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, CallSiteValue)
    assert outcome.value.target_name == "list.append"
    assert outcome.value.term.name == "py.list_append"


def test_chained_list_append_callsite_rebinds_through_list_append() -> None:
    """The coordinate ``append_with`` mints must accept a further append."""
    from sugar_lift_py_tests.ir import ctor
    from sugar_lift_py_tests.outcome import Complete

    prior = CallSiteValue(
        target_name="list.append",
        arg_values=(ListValue((TermValue(1),)), TermValue(2)),
        parameters=(),
        term=ctor("py.list_append", ()),
        body=None,
        site="f.py:1",
    )
    outcome = prior.append_with(TermValue(3), "f.py:2")
    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, CallSiteValue)
    assert outcome.value.target_name == "list.append"
    assert outcome.value.term.name == "py.list_append"


def test_append_after_compact_curried_for_does_not_panic() -> None:
    """Product shape: over-cap branched for append-carries a list, then appends.

    Before: FactoryPanic owner=CallSiteValue.append_with on loop: post-state.
    After: construction continues (no append_with panic on that face).
    """
    from sugar_lift_py_tests.audit_only import collect_factory_panic
    from sugar_lift_py_tests.lift_rpc import lift_file_payload

    source = """
PUBLIC = list(range(32))

def check(x):
    return False

def test():
    module_names = []
    for module_name in PUBLIC:
        if not check(module_name):
            module_names.append(module_name)
    module_names.append(99)
    return module_names
"""
    _payload, gap = collect_factory_panic(
        "compact_for_append.py",
        lambda: lift_file_payload(source, "compact_for_append.py"),
    )
    if gap is not None:
        assert "CallSiteValue.append_with" not in gap.message, gap.message
        assert "loop:" not in gap.message or "append_with" not in gap.message, (
            gap.message
        )


def test_list_copy_appends_exact_post_state() -> None:
    """``[1].copy().append(2)`` folds exact element history, never opaque."""
    record = compose_block(
        "    xs = [1].copy()\n    xs.append(2)\n    return xs\n",
    )

    assert record.statements == (ReturnValue(ListValue((TermValue(1), TermValue(2)))),)


def test_list_value_copy_appends_exact_post_state() -> None:
    """Parametrized finite list copy (pandas find_replace residual) folds."""
    record = compose_block(
        "    xs = expected_data.copy()\n    xs.append(3)\n    return xs\n",
        binds={"expected_data": ListValue((TermValue(1), TermValue(2)))},
    )

    assert record.statements == (
        ReturnValue(ListValue((TermValue(1), TermValue(2), TermValue(3)))),
    )


def test_list_shaped_callsite_copy_rebinds_through_list_append() -> None:
    """``s.split(".").copy()`` is still list-shaped after copy."""
    record = compose_block(
        '    xs = s.split(".").copy()\n    xs.append("0")\n    return xs\n',
        binds={"s": SymbolicValue(make_var("s"))},
    )

    assert isinstance(record, BlockValue)
    returned = record.statements[0]
    assert isinstance(returned, ReturnValue)
    assert isinstance(returned.value, CallSiteValue)
    assert returned.value.target_name == "list.append"
    assert returned.value.term.name == "py.list_append"


def test_opaque_copy_append_stays_loud() -> None:
    """``opaque.copy().append`` is not blessed; copy alone is not list proof."""
    from sugar_lift_py_tests.ir import ctor

    opaque = CallSiteValue(
        target_name="opaque_factory",
        arg_values=(),
        parameters=(),
        term=ctor("call:opaque_factory", ()),
        body=None,
        site="append.py:1",
    )
    copied = CallSiteValue(
        target_name="copy",
        arg_values=(opaque,),
        parameters=(),
        term=ctor("call:copy", ()),
        body=None,
        site="append.py:1",
    )

    with pytest.raises(FactoryPanic) as raised:
        compose_block(
            "    xs.append(1)\n    return xs\n",
            binds={"xs": copied},
        )

    assert raised.value.info.owner == "CallSiteValue.append_with"
    assert raised.value.info.observed == "CallSiteValue(copy)"


def test_pandas_index_as_unit_chain_constructs_non_mutating_append() -> None:
    """``date_range(...).as_unit(u).append(other)`` is Index-like (live residual)."""
    from sugar_lift_py_tests.ir import ctor

    date_range = CallSiteValue(
        target_name="pandas.core.indexes.datetimes.date_range",
        arg_values=(),
        parameters=(),
        term=ctor("call:pandas.core.indexes.datetimes.date_range", ()),
        body=None,
        site="append.py:1",
    )
    receiver = CallSiteValue(
        target_name="as_unit",
        arg_values=(date_range, StringValue("ns")),
        parameters=(),
        term=ctor("call:as_unit", ()),
        body=None,
        site="append.py:1",
    )
    other = CallSiteValue(
        target_name="pandas.core.indexes.datetimes.date_range",
        arg_values=(),
        parameters=(),
        term=ctor("call:pandas.core.indexes.datetimes.date_range", ()),
        body=None,
        site="append.py:1",
    )

    record = compose_block(
        "    result = index.append(other)\n    return result\n",
        binds={"index": receiver, "other": other},
    )

    returned = record.statements[0]
    assert isinstance(returned, ReturnValue)
    assert isinstance(returned.value, CallSiteValue)
    assert returned.value.target_name == "append"
    assert returned.value.arg_values == (receiver, other)


@pytest.mark.parametrize(
    "target_name",
    (
        "pandas.DatetimeIndex",
        "pandas.Index",
        "pandas.IntervalIndex",
        "pandas.IntervalIndex.from_breaks",
        "pandas.MultiIndex.from_arrays",
        "pandas.PeriodIndex",
        "pandas.RangeIndex",
        "pandas.core.indexes.api.Index",
        "pandas.core.indexes.datetimes.date_range",
        "pandas.core.indexes.period.period_range",
        "pandas.core.indexes.timedeltas.timedelta_range",
    ),
)
def test_pandas_index_append_constructs_result_without_rebinding_receiver(
    target_name: str,
) -> None:
    from sugar_lift_py_tests.floor import CallSiteValue
    from sugar_lift_py_tests.ir import ctor

    receiver = CallSiteValue(
        target_name=target_name,
        arg_values=(),
        parameters=(),
        term=ctor(f"call:{target_name}", ()),
        body=None,
        site="append.py:1",
    )
    index = CallSiteValue(
        target_name="pandas.Index",
        arg_values=(),
        parameters=(),
        term=ctor("call:pandas.Index", ()),
        body=None,
        site="append.py:1",
    )

    record = compose_block(
        "    result = rng.append(idx)\n    return result[0]\n",
        binds={"rng": receiver, "idx": index},
    )

    returned = record.statements[0]
    assert isinstance(returned, ReturnValue)
    assert isinstance(returned.value, CallSiteValue)
    assert returned.value.target_name == "py.subscript"
    append_result = returned.value.arg_values[0]
    assert isinstance(append_result, CallSiteValue)
    assert append_result.target_name == "append"
    assert append_result.arg_values == (receiver, index)


def test_unclassified_callsite_append_contract_stays_loud() -> None:
    from sugar_lift_py_tests.floor import CallSiteValue
    from sugar_lift_py_tests.ir import ctor

    opaque = CallSiteValue(
        target_name="opaque_factory",
        arg_values=(),
        parameters=(),
        term=ctor("call:opaque_factory", ()),
        body=None,
        site="append.py:1",
    )

    with pytest.raises(FactoryPanic) as raised:
        compose_block(
            "    result = opaque.append(1)\n    return result[0]\n",
            binds={"opaque": opaque},
        )

    assert raised.value.info.owner == "CallSiteValue.append_with"
    assert raised.value.info.requested == "classified append contract"


def test_typing_cast_of_finite_list_appends_exact_post_state() -> None:
    from sugar_lift_py_tests.ir import ctor

    finite_cast = CallSiteValue(
        target_name="typing.cast",
        arg_values=(
            StringValue("list[tuple[str, int]]"),
            ListValue((TermValue(1),)),
        ),
        parameters=(),
        term=ctor("call:typing.cast", ()),
        body=None,
        site="append.py:1",
    )

    record = compose_block(
        "    attrs.append(2)\n    return attrs\n",
        binds={"attrs": finite_cast},
    )

    assert record.statements == (ReturnValue(ListValue((TermValue(1), TermValue(2)))),)


def test_typing_cast_annotation_does_not_bless_opaque_receiver() -> None:
    from sugar_lift_py_tests.ir import ctor

    opaque = CallSiteValue(
        target_name="opaque_factory",
        arg_values=(),
        parameters=(),
        term=ctor("call:opaque_factory", ()),
        body=None,
        site="append.py:1",
    )
    lying_cast = CallSiteValue(
        target_name="typing.cast",
        arg_values=(StringValue("list[int]"), opaque),
        parameters=(),
        term=ctor("call:typing.cast", ()),
        body=None,
        site="append.py:1",
    )

    with pytest.raises(FactoryPanic) as raised:
        compose_block(
            "    attrs.append(2)\n    return attrs\n",
            binds={"attrs": lying_cast},
        )

    assert raised.value.info.owner == "CallSiteValue.append_with"


def test_append_sugar_enrolls_finite_cast_witness() -> None:
    from sugar_lift_py_tests.sugar.append_call_sugar import AppendCallSugar

    assert any(
        pair.name == "append_finite_cast_return" for pair in AppendCallSugar.witnesses()
    )


def test_append_sugar_enrolls_finite_copy_witness() -> None:
    from sugar_lift_py_tests.sugar.append_call_sugar import AppendCallSugar

    assert any(
        pair.name == "append_finite_copy_return" for pair in AppendCallSugar.witnesses()
    )


def test_append_sugar_enrolls_diggable_unpack_and_cast_witnesses() -> None:
    from sugar_lift_py_tests.sugar.append_call_sugar import AppendCallSugar

    names = {pair.name for pair in AppendCallSugar.witnesses()}
    assert "append_diggable_unpack_return" in names
    assert "append_diggable_cast_return" in names


def test_diggable_tuple_subscript_unpack_appends_exact_post_state() -> None:
    """``handles = f()[2]`` digs a returned triple and folds list append (#5136)."""
    from sugar_lift_py_tests.claim import SugarRole
    from sugar_lift_py_tests.floor import CallSiteValue, TupleValue
    from sugar_lift_py_tests.ir import ctor
    from sugar_lift_py_tests.outcome import Complete
    from sugar_lift_py_tests.sugar_body import SugarBody

    class _StaticFloor:
        def __init__(self, value) -> None:
            self.value = value

        def desugar(self, ctx=None):
            return Complete(self.value)

        def walk_children(self):
            return ()

    returned = TupleValue((TermValue(1), TermValue(True), ListValue((TermValue(0),))))
    call = CallSiteValue(
        target_name="_maybe_memory_map",
        arg_values=(),
        parameters=(),
        term=ctor("call:_maybe_memory_map", ()),
        body=SugarBody(_StaticFloor(returned), SugarRole.TERM),
        site="append.py:1",
    )
    handles = CallSiteValue(
        target_name="py.subscript",
        arg_values=(call, TermValue(2)),
        parameters=(),
        term=ctor(
            "py.subscript",
            [call.term, TermValue(2).to_term(owner="append.py:1")],
        ),
        body=None,
        site="append.py:1",
    )

    record = compose_block(
        "    handles.append(9)\n    return handles\n",
        binds={"handles": handles},
    )

    assert record.statements == (ReturnValue(ListValue((TermValue(0), TermValue(9)))),)


def test_function_return_unpack_list_appends_exact_post_state() -> None:
    """Live residual shape: dig through ``h, m, handles = f(); handles.append``."""
    record = compose_block(
        "    def f():\n"
        "        return (1, True, [0])\n"
        "    h, m, handles = f()\n"
        "    handles.append(9)\n"
        "    return handles\n"
    )

    returned = record.statements[-1]
    assert isinstance(returned, ReturnValue)
    assert returned.value == ListValue((TermValue(0), TermValue(9)))


def test_opaque_subscript_unpack_append_stays_loud() -> None:
    from sugar_lift_py_tests.floor import CallSiteValue
    from sugar_lift_py_tests.ir import ctor

    opaque = CallSiteValue(
        target_name="opaque_factory",
        arg_values=(),
        parameters=(),
        term=ctor("call:opaque_factory", ()),
        body=None,
        site="append.py:1",
    )
    handles = CallSiteValue(
        target_name="py.subscript",
        arg_values=(opaque, TermValue(2)),
        parameters=(),
        term=ctor(
            "py.subscript",
            [opaque.term, TermValue(2).to_term(owner="append.py:1")],
        ),
        body=None,
        site="append.py:1",
    )

    with pytest.raises(FactoryPanic) as raised:
        compose_block(
            "    handles.append(9)\n    return handles\n",
            binds={"handles": handles},
        )

    assert raised.value.info.owner == "CallSiteValue.append_with"
    assert raised.value.info.observed == "CallSiteValue(py.subscript)"


def test_iter_elem_of_list_of_lists_rebinds_through_list_append() -> None:
    """Symbolic loop face over a proven list-of-lists is list-shaped (#5136)."""
    from sugar_lift_py_tests.floor import CallSiteValue
    from sugar_lift_py_tests.ir import ctor

    columns = ListValue(
        (ListValue((StringValue("a"),)), ListValue((StringValue("b"),)))
    )
    loop_face = CallSiteValue(
        target_name="iter_elem",
        arg_values=(columns,),
        parameters=(),
        term=ctor("py.iter_elem", [columns.to_term(owner="append.py:1")]),
        body=None,
        site="append.py:1",
    )

    record = compose_block(
        "    x.append('')\n    return x\n",
        binds={"x": loop_face},
    )

    returned = record.statements[0]
    assert isinstance(returned, ReturnValue)
    assert isinstance(returned.value, CallSiteValue)
    assert returned.value.target_name == "list.append"
    assert returned.value.term.name == "py.list_append"


def test_iter_elem_of_listcomp_of_lists_rebinds_through_list_append() -> None:
    """format.py residual: ``for x in [[label] for label in header]: x.append``."""
    from sugar_lift_py_tests.floor import CallSiteValue, ComprehensionValue
    from sugar_lift_py_tests.ir import ctor, make_var

    columns = ComprehensionValue(
        ctor(
            "py.listcomp",
            [
                ctor("array", [ctor("py.iter_elem", [make_var("header")])]),
                make_var("header"),
            ],
        )
    )
    loop_face = CallSiteValue(
        target_name="iter_elem",
        arg_values=(columns,),
        parameters=(),
        term=ctor("py.iter_elem", [columns.term]),
        body=None,
        site="append.py:1",
    )

    record = compose_block(
        "    x.append('')\n    return x\n",
        binds={"x": loop_face},
    )

    returned = record.statements[0]
    assert isinstance(returned, ReturnValue)
    assert isinstance(returned.value, CallSiteValue)
    assert returned.value.target_name == "list.append"


def test_iter_elem_of_opaque_iterable_append_stays_loud() -> None:
    from sugar_lift_py_tests.floor import CallSiteValue
    from sugar_lift_py_tests.ir import ctor

    opaque = CallSiteValue(
        target_name="opaque_factory",
        arg_values=(),
        parameters=(),
        term=ctor("call:opaque_factory", ()),
        body=None,
        site="append.py:1",
    )
    loop_face = CallSiteValue(
        target_name="iter_elem",
        arg_values=(opaque,),
        parameters=(),
        term=ctor("py.iter_elem", [opaque.term]),
        body=None,
        site="append.py:1",
    )

    with pytest.raises(FactoryPanic) as raised:
        compose_block(
            "    x.append('')\n    return x\n",
            binds={"x": loop_face},
        )

    assert raised.value.info.owner == "CallSiteValue.append_with"
    assert raised.value.info.observed == "CallSiteValue(iter_elem)"


def test_typing_cast_of_diggable_list_call_appends_exact_post_state() -> None:
    """range.py residual: cast around a diggable list-returning call folds."""
    from sugar_lift_py_tests.claim import SugarRole
    from sugar_lift_py_tests.floor import CallSiteValue
    from sugar_lift_py_tests.ir import ctor
    from sugar_lift_py_tests.outcome import Complete
    from sugar_lift_py_tests.sugar_body import SugarBody

    class _StaticFloor:
        def __init__(self, value) -> None:
            self.value = value

        def desugar(self, ctx=None):
            return Complete(self.value)

        def walk_children(self):
            return ()

    diggable = CallSiteValue(
        target_name="_get_data_as_items",
        arg_values=(),
        parameters=(),
        term=ctor("call:_get_data_as_items", ()),
        body=SugarBody(
            _StaticFloor(ListValue((TermValue(1), TermValue(2)))),
            SugarRole.TERM,
        ),
        site="append.py:1",
    )
    casted = CallSiteValue(
        target_name="typing.cast",
        arg_values=(StringValue("list"), diggable),
        parameters=(),
        term=ctor("call:typing.cast", ()),
        body=None,
        site="append.py:1",
    )

    record = compose_block(
        "    attrs.append(3)\n    return attrs\n",
        binds={"attrs": casted},
    )

    assert record.statements == (
        ReturnValue(ListValue((TermValue(1), TermValue(2), TermValue(3)))),
    )


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
