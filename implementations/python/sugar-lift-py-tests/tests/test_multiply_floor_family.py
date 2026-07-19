from __future__ import annotations

from pathlib import Path

import pytest

from factory_reduce import reduce_value

from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.effect import (
    SequenceRepetitionRuntimeEffect,
    SubscriptStoreRuntimeEffect,
    runtime_effect_evidence,
)
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import (
    CallSiteValue,
    ComprehensionValue,
    ListValue,
    ImportAliasValue,
    OpaqueOpCallsite,
    StringValue,
    SymbolicValue,
    TermValue,
    TupleValue,
)
from sugar_lift_py_tests.floor.guarded_value import GuardedValue
from sugar_lift_py_tests.ir import atomic, ctor, make_var, num
from sugar_lift_py_tests.outcome import Complete, Incomplete
from sugar_lift_py_tests.sugar.multiply_op_sugar import MultiplyOpSugar
from sugar_lift_py_tests.sugar.witnesses import SugarWitnessPair
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver

_SITE = SourceFragment.from_source("xs * n\n", "runtime_repeat.py").statements()[0]


@pytest.mark.parametrize(
    ("source", "expected"),
    (
        ("[1, 2] * 3", (1, 2, 1, 2, 1, 2)),
        ("3 * [1, 2]", (1, 2, 1, 2, 1, 2)),
        ("[1, 2] * 0", ()),
        ("0 * [1, 2]", ()),
        ("[1, 2] * -2", ()),
        ("-2 * [1, 2]", ()),
    ),
)
def test_list_repetition_constructs_exact_python_order_through_multiply_sugar(
    source: str, expected: tuple[int, ...]
) -> None:
    value = reduce_value(source)

    assert value == ListValue(tuple(TermValue(item) for item in expected))


@pytest.mark.parametrize("source", ("[first, second] * 2", "2 * [first, second]"))
def test_list_repetition_preserves_reduced_element_identities(source: str) -> None:
    first = SymbolicValue(make_var("first_value"))
    second = SymbolicValue(make_var("second_value"))

    value = reduce_value(source, {"first": first, "second": second})

    assert type(value) is ListValue
    assert value.elements == (first, second, first, second)
    assert value.elements[0] is value.elements[2] is first
    assert value.elements[1] is value.elements[3] is second


@pytest.mark.parametrize("count", (3, 0, -2))
def test_string_multiply_matches_python(count: int) -> None:
    expected = "ab" * count

    value = reduce_value(f"'ab' * {count}")

    assert value == StringValue(expected)


@pytest.mark.parametrize("left,right", ((3, 4), (2, 1.5), (-2, 3)))
def test_number_multiply_matches_python(left: int | float, right: int | float) -> None:
    expected = left * right

    value = reduce_value(f"{left!r} * {right!r}")

    assert value == TermValue(expected)


@pytest.mark.parametrize(
    ("source", "expected"),
    (
        (
            "'ab' * count",
            ctor("*", [StringValue("ab").to_term(owner="test"), make_var("count")]),
        ),
        ("2 * count", ctor("*", [num(2), make_var("count")])),
    ),
)
def test_non_list_symbolic_multiplier_uses_native_operator_coordinate(
    source, expected
) -> None:
    value = reduce_value(source, {"count": SymbolicValue(make_var("count"))})

    assert value == SymbolicValue(expected)


def test_comprehension_repetition_by_concrete_int_preserves_native_coordinate() -> None:
    items = SymbolicValue(make_var("items"))
    element = ctor("py.iter_elem", [make_var("items")])

    value = reduce_value("[item for item in items] * 2", {"items": items})

    assert value == SymbolicValue(
        ctor(
            "*",
            [
                ctor("py.listcomp", [element, make_var("items")]),
                num(2),
            ],
        )
    )


def test_term_times_len_coordinate_preserves_integer_multiplication() -> None:
    kinds = SymbolicValue(make_var("kinds"))

    value = reduce_value("4 * len(kinds)", {"kinds": kinds})

    assert value == SymbolicValue(
        ctor(
            "*",
            [
                num(4),
                ctor(
                    "call:len",
                    [make_var("kinds")],
                    symbol_kind="method-coordinate",
                ),
            ],
        )
    )


def test_comprehension_repetition_by_non_int_stays_loud() -> None:
    value = ComprehensionValue(ctor("py.listcomp", [make_var("items")]))

    with pytest.raises(FactoryPanic, match="stand on the multiplication floor"):
        value.multiply(StringValue("2"), _SITE)


@pytest.mark.parametrize("coordinate", ("py.setcomp", "py.dictcomp"))
def test_non_list_comprehension_times_int_stays_loud(coordinate: str) -> None:
    value = ComprehensionValue(ctor(coordinate, [make_var("items")]))

    with pytest.raises(FactoryPanic, match="stand on the multiplication floor"):
        value.multiply(TermValue(2), _SITE)


def test_term_times_unwarranted_opaque_coordinate_stays_loud() -> None:
    value = OpaqueOpCallsite(
        callee="str",
        arg=SymbolicValue(make_var("runtime_value")),
        computed=None,
    )

    with pytest.raises(FactoryPanic, match="stand on the multiplication floor"):
        TermValue(4).multiply(value, _SITE)


def test_term_times_len_witness_truthful_sat_lying_unsat(
    tmp_path: Path,
) -> None:
    pair = next(
        witness
        for witness in MultiplyOpSugar.witnesses()
        if isinstance(witness, SugarWitnessPair)
        and witness.name == "term_times_len_return"
    )

    truthful = run_source_through_real_solver(
        tmp_path / "truthful", pair.truthful.source
    )
    lying = run_source_through_real_solver(tmp_path / "lying", pair.lying.source)

    assert truthful.verdict == pair.truthful.expected == "sat"
    assert lying.verdict == pair.lying.expected == "unsat"


def test_imported_list_repetition_count_remains_a_named_loud_gap() -> None:
    count = ImportAliasValue("start_caching_at", "start_caching_at")
    receiver = ListValue((StringValue("2024-01-01"),))

    with pytest.raises(
        FactoryPanic,
        match="ListValue.*stand on the multiplication floor",
    ):
        receiver.multiply(count, "test_to_datetime.py:3626:17")


@pytest.mark.parametrize("reversed_operands", (False, True))
def test_runtime_list_repetition_count_is_a_named_typed_effect(
    reversed_operands: bool,
) -> None:
    count = SymbolicValue(make_var("runtime_n"))
    items = ListValue((TermValue(7),))

    outcome = (
        count.multiply(items, _SITE)
        if reversed_operands
        else items.multiply(count, _SITE)
    )

    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, SequenceRepetitionRuntimeEffect)
    assert "ListValue depends on runtime __index__/length semantics" in outcome.reason
    assert outcome.effect.witness.operand == make_var("runtime_n")
    assert outcome.effect.witness.operation == ctor(
        "py.sequence_repeat", [make_var("runtime_n")]
    )


def test_ground_sequence_repeat_100000_is_typed_loud_not_complete() -> None:
    """#5361: a decidable over-cap repeat stays loud, never opaque Complete."""
    from sugar_lift_py_tests.effect import genuine_runtime_operand

    site = SourceFragment.from_source(
        "index = [0] * 100000\n",
        "pandas/tests/indexing/test_loc.py",
    ).statements()[0]
    items = ListValue((TermValue(0),))
    count = TermValue(100000)

    with pytest.raises(FactoryPanic) as panic:
        items.multiply(count, site)
    assert panic.value.info.owner == "finite_unfold"
    assert panic.value.info.observed == "list repetition cardinality=100000"

    # Law: the ground operand cannot mint SequenceRepetitionRuntimeEffect evidence.
    with pytest.raises(TypeError, match="genuine runtime-dependent operand"):
        genuine_runtime_operand("py.sequence_repeat", count)


def test_len_result_is_a_warranted_runtime_list_repetition_count() -> None:
    count = OpaqueOpCallsite(
        callee="len",
        arg=SymbolicValue(make_var("runtime_items")),
        computed=None,
    )

    outcome = ListValue((TermValue(7),)).multiply(count, _SITE)

    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, SequenceRepetitionRuntimeEffect)
    assert "integer-warranted len(...) result" in outcome.reason
    assert outcome.effect.witness.operand == ctor(
        "call:len", [make_var("runtime_items")], symbol_kind="method-coordinate"
    )


def test_opaque_non_index_result_remains_a_loud_list_repetition_gap() -> None:
    count = OpaqueOpCallsite(
        callee="str",
        arg=SymbolicValue(make_var("runtime_value")),
        computed=None,
    )

    with pytest.raises(FactoryPanic, match="stand on the multiplication floor"):
        ListValue((TermValue(7),)).multiply(count, _SITE)


@pytest.mark.parametrize(
    "count",
    (
        CallSiteValue(
            target_name="ndim",
            arg_values=(SymbolicValue(make_var("array")),),
            parameters=(),
            term=ctor("call:ndim", [make_var("array")]),
            body=None,
            site=_SITE,
        ),
        CallSiteValue(
            target_name="nlanes",
            arg_values=(SymbolicValue(make_var("simd")),),
            parameters=(),
            term=ctor("call:nlanes", [make_var("simd")]),
            body=None,
            site=_SITE,
        ),
        CallSiteValue(
            target_name="_AXIS_LEN",
            arg_values=(SymbolicValue(make_var("box")),),
            parameters=(),
            term=ctor("call:_AXIS_LEN", [make_var("box")]),
            body=None,
            site=_SITE,
        ),
        CallSiteValue(
            target_name="max",
            arg_values=(TermValue(0), SymbolicValue(make_var("runtime_n"))),
            parameters=(),
            term=ctor("call:max", [num(0), make_var("runtime_n")]),
            body=None,
            site=_SITE,
        ),
    ),
)
def test_integer_warranted_callsite_is_a_runtime_list_repetition_count(
    count: CallSiteValue,
) -> None:
    outcome = ListValue((TermValue(7),)).multiply(count, _SITE)

    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, SequenceRepetitionRuntimeEffect)
    assert "integer-warranted callsite" in outcome.reason
    assert outcome.effect.witness.operand == count.term


def test_shape_element_is_a_warranted_runtime_list_repetition_count() -> None:
    """#5111 residual: Index(["foo"] * mgr.shape[ax]) — shape[i] is an int dim."""
    site = SourceFragment.from_source(
        'Index(["foo"] * mgr.shape[ax])\n',
        "pandas/tests/internals/test_internals.py",
    ).statements()[0]
    shape = CallSiteValue(
        target_name="shape",
        arg_values=(SymbolicValue(make_var("mgr")),),
        parameters=(),
        term=ctor("call:shape", [make_var("mgr")]),
        body=None,
        site=site,
    )
    count = CallSiteValue(
        target_name="py.subscript",
        arg_values=(shape, SymbolicValue(make_var("ax"))),
        parameters=(),
        term=ctor("call:py.subscript", [shape.term, make_var("ax")]),
        body=None,
        site=site,
    )

    outcome = ListValue((StringValue("foo"),)).multiply(count, site)

    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, SequenceRepetitionRuntimeEffect)
    assert "integer-warranted shape element" in outcome.reason
    assert outcome.effect.witness.operand == count.term
    with pytest.raises(FactoryPanic, match="genuine runtime-dependent operand"):
        runtime_effect_evidence("py.sequence_repeat", TermValue(2), site)


def test_tuple_ndim_is_a_warranted_runtime_repetition_count() -> None:
    """#5111 residual: (1,) * d.ndim constructs typed runtime testimony, not panic."""
    site = SourceFragment.from_source(
        "(1,) * d.ndim\n",
        "numpy/lib/tests/test_nanfunctions.py",
    ).statements()[0]
    count = CallSiteValue(
        target_name="ndim",
        arg_values=(SymbolicValue(make_var("d")),),
        parameters=(),
        term=ctor("call:ndim", [make_var("d")]),
        body=None,
        site=site,
    )

    outcome = TupleValue((TermValue(1),)).multiply(count, site)

    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, SequenceRepetitionRuntimeEffect)
    assert "integer-warranted callsite ndim" in outcome.reason
    assert outcome.effect.witness.operand == count.term
    with pytest.raises(FactoryPanic, match="genuine runtime-dependent operand"):
        runtime_effect_evidence("py.sequence_repeat", TermValue(4), site)


def test_finite_ground_list_repetition_constructs_not_runtime_effect() -> None:
    """#5111 law: ground literal count constructs; never mints RuntimeEffect."""
    from sugar_lift_py_tests.effect import genuine_runtime_operand
    from sugar_lift_py_tests.sugar.for_sugar import STATIC_UNFOLD_LIMIT

    items = ListValue((TermValue(0),))
    small = items.multiply(TermValue(3), _SITE)
    at_limit = items.multiply(TermValue(STATIC_UNFOLD_LIMIT), _SITE)

    assert isinstance(small, Complete)
    assert isinstance(small.value, ListValue)
    assert small.value.elements == (TermValue(0),) * 3

    assert isinstance(at_limit, Complete)
    assert isinstance(at_limit.value, ListValue)
    assert len(at_limit.value.elements) == STATIC_UNFOLD_LIMIT

    with pytest.raises(FactoryPanic) as mid_panic:
        items.multiply(TermValue(STATIC_UNFOLD_LIMIT + 1), _SITE)
    assert mid_panic.value.info.owner == "finite_unfold"

    with pytest.raises(FactoryPanic) as large_panic:
        items.multiply(TermValue(100000), _SITE)
    assert large_panic.value.info.owner == "finite_unfold"
    with pytest.raises(TypeError, match="genuine runtime-dependent operand"):
        genuine_runtime_operand("py.sequence_repeat", TermValue(100000))


def test_runtime_max_result_is_a_warranted_tuple_repetition_count() -> None:
    site = SourceFragment.from_source(
        "(1,) * max(0, len(shape_b) - len(shape_a))\n",
        "numpy/lib/tests/test_shape_base.py",
    ).statements()[0]
    runtime_delta = SymbolicValue(
        ctor(
            "-",
            [
                ctor("call:len", [make_var("shape_b")]),
                ctor("call:len", [make_var("shape_a")]),
            ],
        )
    )
    count = CallSiteValue(
        target_name="max",
        arg_values=(TermValue(0), runtime_delta),
        parameters=(),
        term=ctor("call:max", [num(0), runtime_delta.term]),
        body=None,
        site=site,
    )

    outcome = TupleValue((TermValue(1),)).multiply(count, site)

    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, SequenceRepetitionRuntimeEffect)
    assert "integer-warranted callsite max" in outcome.reason
    assert outcome.effect.witness.operand == count.term
    assert outcome.effect.witness.locus == "numpy/lib/tests/test_shape_base.py:1:0"


@pytest.mark.parametrize(
    "runtime_peer",
    (
        StringValue("zero"),
        SymbolicValue(make_var("unwarranted_runtime_value")),
    ),
)
def test_unwarranted_max_result_stays_loud_on_tuple_repetition_floor(
    runtime_peer,
) -> None:
    count = CallSiteValue(
        target_name="max",
        arg_values=(TermValue(0), runtime_peer),
        parameters=(),
        term=ctor("call:max", [num(0), runtime_peer.to_term(owner="test")]),
        body=None,
        site=_SITE,
    )

    with pytest.raises(FactoryPanic, match="stand on the multiplication floor"):
        TupleValue((TermValue(1),)).multiply(count, _SITE)


def test_numpy_sum_of_runtime_predicate_is_a_warranted_list_repetition_count() -> None:
    site = SourceFragment.from_source(
        "[None] * np.sum(index_with_missing.isna())\n",
        "pandas/tests/indexes/test_common.py",
    ).statements()[0]
    runtime_predicate = CallSiteValue(
        target_name="isna",
        arg_values=(SymbolicValue(make_var("index")),),
        parameters=(),
        term=ctor("call:isna", [make_var("index")]),
        body=None,
        site=site,
    )
    count = CallSiteValue(
        target_name="numpy.sum",
        arg_values=(runtime_predicate,),
        parameters=(),
        term=ctor("call:numpy.sum", [runtime_predicate.term]),
        body=None,
        site=site,
    )

    outcome = ListValue((TermValue(None),)).multiply(count, site)

    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, SequenceRepetitionRuntimeEffect)
    assert "integer-warranted numpy.sum boolean count" in outcome.reason
    assert outcome.effect.witness.operand == count.term
    assert outcome.effect.witness.locus == "pandas/tests/indexes/test_common.py:1:0"

    with pytest.raises(FactoryPanic, match="genuine runtime-dependent operand"):
        runtime_effect_evidence("py.sequence_repeat", TermValue(0), site)


@pytest.mark.parametrize("target_name", ("sum", "vendor.sum"))
def test_unqualified_sum_result_stays_loud_on_list_repetition_floor(
    target_name: str,
) -> None:
    count = CallSiteValue(
        target_name=target_name,
        arg_values=(SymbolicValue(make_var("values")),),
        parameters=(),
        term=ctor(f"call:{target_name}", [make_var("values")]),
        body=None,
        site=_SITE,
    )

    with pytest.raises(FactoryPanic, match="stand on the multiplication floor"):
        ListValue((TermValue(None),)).multiply(count, _SITE)


@pytest.mark.parametrize(
    "count",
    (
        CallSiteValue(
            target_name="nlevels",
            arg_values=(SymbolicValue(make_var("index")),),
            parameters=(),
            term=ctor("call:nlevels", [make_var("index")]),
            body=None,
            site=_SITE,
        ),
        CallSiteValue(
            target_name="min",
            arg_values=(
                CallSiteValue(
                    target_name="abs",
                    arg_values=(SymbolicValue(make_var("periods")),),
                    parameters=(),
                    term=ctor("call:abs", [make_var("periods")]),
                    body=None,
                    site=_SITE,
                ),
                OpaqueOpCallsite(
                    callee="len",
                    arg=SymbolicValue(make_var("items")),
                    computed=None,
                ),
            ),
            parameters=(),
            term=ctor(
                "call:min",
                [
                    ctor("call:abs", [make_var("periods")]),
                    ctor("call:len", [make_var("items")]),
                ],
            ),
            body=None,
            site=_SITE,
        ),
    ),
)
def test_integer_warranted_residual_callsite_is_runtime_sequence_count(
    count: CallSiteValue,
) -> None:
    outcome = ListValue((TermValue(7),)).multiply(count, _SITE)

    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, SequenceRepetitionRuntimeEffect)
    assert outcome.effect.witness.operand == count.term


def _pyarrow_list_max_as_py_count() -> CallSiteValue:
    pyarrow = ImportAliasValue(name="pyarrow", bound_name="pa")
    compute = CallSiteValue(
        target_name="compute",
        arg_values=(pyarrow,),
        parameters=(),
        term=ctor("call:compute", [pyarrow.to_term(owner="test")]),
        body=None,
        site=_SITE,
    )
    lengths = CallSiteValue(
        target_name="list_value_length",
        arg_values=(compute, SymbolicValue(make_var("arrow_array"))),
        parameters=(),
        term=ctor(
            "call:list_value_length",
            [compute.term, make_var("arrow_array")],
        ),
        body=None,
        site=_SITE,
        runtime_dispatch_receiver=compute,
    )
    maximum = CallSiteValue(
        target_name="max",
        arg_values=(compute, lengths),
        parameters=(),
        term=ctor("call:max", [compute.term, lengths.term]),
        body=None,
        site=_SITE,
        runtime_dispatch_receiver=compute,
    )
    return CallSiteValue(
        target_name="as_py",
        arg_values=(maximum,),
        parameters=(),
        term=ctor("call:as_py", [maximum.term]),
        body=None,
        site=_SITE,
        runtime_dispatch_receiver=maximum,
    )


def test_pyarrow_list_length_max_as_py_is_warranted_runtime_sequence_count() -> None:
    count = _pyarrow_list_max_as_py_count()

    outcome = ListValue((TermValue(None),)).multiply(count, _SITE)

    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, SequenceRepetitionRuntimeEffect)
    assert "pyarrow list-length maximum" in outcome.reason
    assert outcome.effect.witness.operand == count.term
    assert outcome.effect.witness.operation == ctor("py.sequence_repeat", [count.term])
    with pytest.raises(FactoryPanic, match="genuine runtime-dependent operand"):
        runtime_effect_evidence("py.sequence_repeat", TermValue(4), _SITE)


def test_unproven_as_py_result_stays_loud_on_list_repetition_floor() -> None:
    count = _pyarrow_list_max_as_py_count()
    lookalike = CallSiteValue(
        target_name="as_py",
        arg_values=(
            CallSiteValue(
                target_name="sum",
                arg_values=count.arg_values[0].arg_values,
                parameters=(),
                term=ctor("call:sum", [make_var("runtime_values")]),
                body=None,
                site=_SITE,
            ),
        ),
        parameters=(),
        term=ctor("call:as_py", [make_var("runtime_scalar")]),
        body=None,
        site=_SITE,
    )

    with pytest.raises(FactoryPanic, match="stand on the multiplication floor"):
        ListValue((TermValue(None),)).multiply(lookalike, _SITE)


def test_pandas_box_expected_array_result_uses_native_multiply_coordinate() -> None:
    boxed = CallSiteValue(
        target_name="pandas._testing.box_expected",
        arg_values=(
            CallSiteValue(
                target_name="numpy.array",
                arg_values=(ListValue((TermValue(3), TermValue(4))),),
                parameters=(),
                term=ctor("call:numpy.array", [ctor("array", [num(3), num(4)])]),
                body=None,
                site=_SITE,
            ),
            SymbolicValue(make_var("box_with_array")),
        ),
        parameters=(),
        term=ctor(
            "call:pandas._testing.box_expected", [make_var("array"), make_var("box")]
        ),
        body=None,
        site=_SITE,
    )

    outcome = ListValue((TermValue(1), TermValue(2))).multiply(boxed, _SITE)

    assert isinstance(outcome, Complete)
    assert outcome.value == SymbolicValue(
        ctor(
            "*",
            [
                ctor("array", [num(1), num(2)]),
                boxed.term,
            ],
        )
    )


def test_numeric_multiply_distributes_over_guarded_receiver() -> None:
    guarded = GuardedValue(
        atomic("is_range_index", []),
        SymbolicValue(make_var("range_index")),
        SymbolicValue(make_var("index")),
    )

    outcome = TermValue(3.2).multiply(guarded, _SITE)

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, GuardedValue)


def test_numpy_maxdims_is_a_static_tuple_repetition_count() -> None:
    module = ImportAliasValue(
        name="numpy._core._multiarray_umath",
        bound_name="ncu",
    )
    count = CallSiteValue(
        target_name="MAXDIMS",
        arg_values=(module,),
        parameters=(),
        term=ctor("call:MAXDIMS", [module.to_term(owner="test")]),
        body=None,
        site=_SITE,
    )

    outcome = TupleValue((TermValue(1),)).multiply(count, _SITE)

    assert isinstance(outcome, Complete)
    assert outcome.value == TupleValue((TermValue(1),) * 64)


def test_unrelated_maxdims_coordinate_stays_a_loud_tuple_gap() -> None:
    module = ImportAliasValue(name="vendor.runtime", bound_name="vendor")
    count = CallSiteValue(
        target_name="MAXDIMS",
        arg_values=(module,),
        parameters=(),
        term=ctor("call:MAXDIMS", [module.to_term(owner="test")]),
        body=None,
        site=_SITE,
    )

    with pytest.raises(FactoryPanic, match="stand on the multiplication floor"):
        TupleValue((TermValue(1),)).multiply(count, _SITE)


def test_numpy_maxdims_tuple_repetition_witness_truthful_sat_lying_unsat(
    tmp_path: Path,
) -> None:
    pair = next(
        witness
        for witness in MultiplyOpSugar.witnesses()
        if isinstance(witness, SugarWitnessPair)
        and witness.name == "numpy_maxdims_tuple_repetition_return"
    )

    truthful = run_source_through_real_solver(
        tmp_path / "numpy-maxdims-truthful", pair.truthful.source
    )
    lying = run_source_through_real_solver(
        tmp_path / "numpy-maxdims-lying", pair.lying.source
    )

    assert truthful.verdict == pair.truthful.expected == "sat"
    assert lying.verdict == pair.lying.expected == "unsat"


def test_unwarranted_callsite_remains_a_loud_list_repetition_gap() -> None:
    count = CallSiteValue(
        target_name="make_count",
        arg_values=(SymbolicValue(make_var("value")),),
        parameters=(),
        term=ctor("call:make_count", [make_var("value")]),
        body=None,
        site=_SITE,
    )

    with pytest.raises(FactoryPanic, match="stand on the multiplication floor"):
        ListValue((TermValue(7),)).multiply(count, _SITE)


@pytest.mark.parametrize(
    ("left", "right"),
    (
        (ListValue((TermValue(1),)), ListValue((TermValue(2),))),
        (StringValue("a"), StringValue("b")),
    ),
)
def test_ground_invalid_multiplication_stays_loud(left, right) -> None:
    with pytest.raises(FactoryPanic, match="stand on the multiplication floor"):
        left.multiply(right, "t.py:1:0")


@pytest.mark.parametrize(
    "source",
    (
        "[1] * [2]",
        "[1] * 2.0",
        "2.0 * [1]",
        "[1] * True",
        "True * [1]",
    ),
)
def test_non_index_list_repetition_operands_remain_named_loud_gaps(source: str) -> None:
    with pytest.raises(FactoryPanic, match="stand on the multiplication floor"):
        reduce_value(source)


def test_ranked_receivers_declare_multiply_arms() -> None:
    assert "multiply" in ListValue.__dict__
    assert "multiply" in TermValue.__dict__
    assert "multiply" in StringValue.__dict__
    assert "multiply" in SymbolicValue.__dict__


def test_unprojectable_multiplier_remains_a_loud_floor_gap() -> None:
    class Unprojectable(ListValue):
        pass

    with pytest.raises(FactoryPanic, match="stand on the multiplication floor"):
        ListValue((TermValue(1),)).multiply(Unprojectable(()), "t.py:1:0")


def test_guarded_descendant_preserves_the_typed_store_effect() -> None:
    effect = Incomplete(
        SubscriptStoreRuntimeEffect(
            "symbolic store",
            **runtime_effect_evidence(
                "py.setitem",
                make_var("runtime_index"),
                SourceFragment.from_source("x[i] = 1\n", "t.py").statements()[0],
            ),
        )
    )
    guard = atomic("guard", [])

    guarded = effect.guarded(guard)

    assert isinstance(guarded, Incomplete)
    assert isinstance(guarded.effect, SubscriptStoreRuntimeEffect)
    assert "symbolic store" in guarded.reason
    assert "under branch condition" in guarded.reason
    assert "guard" in guarded.reason
