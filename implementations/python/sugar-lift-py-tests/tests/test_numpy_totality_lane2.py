from __future__ import annotations

import pytest

from factory_reduce import reduce_value

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext
from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.factory.factory_gap import factory_panic_gap
from sugar_lift_py_tests.factory import factory_panic
from sugar_lift_py_tests.factory import GapKind, GapLocus
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report
from sugar_lift_py_tests.floor import StringValue, SymbolicValue, TermValue
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.operations import MethodCallOperation, perform_operation
from sugar_lift_py_tests.outcome import Complete, Incomplete, complete_value
from sugar_lift_py_tests.temporal import TemporalContext


def test_symbolic_method_call_is_opaque_op_coordinate():
    """#3809 / #3943: symbolic receiver methods are OpaqueOpCallsite, not FactoryGap."""
    from sugar_lift_py_tests.floor.opaque_op_callsite import OpaqueOpCallsite

    outcome = perform_operation(
        owner="CallSugar",
        blame="numpy/_core/tests/test_scalar_ctors.py:148:15",
        receiver=SymbolicValue(make_var("arr")),
        operation=MethodCallOperation(
            name="astype",
            arguments=(StringValue("int64"),),
            owner="CallSugar",
            blame="numpy/_core/tests/test_scalar_ctors.py:148:15",
        ),
        ctx=ReduceContext(temporal=TemporalContext.empty()),
    )

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, OpaqueOpCallsite)
    assert outcome.value.callee == "astype"
    assert outcome.value.arg == SymbolicValue(make_var("arr"))
    assert outcome.value.extra_args == (StringValue("int64"),)
    # Coordinate only — no concrete value invented for a symbolic receiver.
    assert outcome.value.computed is None


def test_symbolic_method_coordinate_is_not_a_concrete_fiat_value():
    """OpaqueOpCallsite completes, but computed stays None (not a green number by fiat)."""
    from sugar_lift_py_tests.floor.opaque_op_callsite import OpaqueOpCallsite

    outcome = perform_operation(
        owner="CallSugar",
        blame="numpy/_core/tests/test_scalar_ctors.py:148:15",
        receiver=SymbolicValue(make_var("arr")),
        operation=MethodCallOperation(
            name="astype",
            arguments=(StringValue("int64"),),
            owner="CallSugar",
            blame="numpy/_core/tests/test_scalar_ctors.py:148:15",
        ),
        ctx=ReduceContext(temporal=TemporalContext.empty()),
    )

    value = complete_value(outcome, owner="numpy lane2 symbolic method")
    assert isinstance(value, OpaqueOpCallsite)
    assert value.computed is None
    assert not isinstance(value, TermValue)


def test_concrete_method_call_still_uses_existing_green_floor():
    outcome = perform_operation(
        owner="CallSugar",
        blame="t.py:1:0",
        receiver=TermValue(7),
        operation=MethodCallOperation(
            name="__int__",
            arguments=(),
            owner="CallSugar",
            blame="t.py:1:0",
        ),
        ctx=ReduceContext(temporal=TemporalContext.empty()),
    )

    assert outcome == Complete(TermValue(7))


def test_temporal_unbound_name_is_registered_floor_effect():
    import ast

    build_ctx = FactoryBuildContext(filename="numpy.py", catalog=default_catalog())
    body = build_ctx.build_body(ast.parse("np", mode="eval").body, SugarRole.TERM)
    name = body.reduce(ReduceContext(temporal=TemporalContext.empty()))

    assert isinstance(name, Incomplete)
    assert isinstance(name.effect)
    assert name.effect.owner == "TemporalContext"
    assert name.effect.observed == "np"
    assert name.effect.requested == "value"
    assert name.effect.gap_kind is GapKind.FLOOR
    assert name.effect.gap_locus is GapLocus.CONSTRUCTION


def test_temporal_bound_name_still_reduces_to_value():
    value = reduce_value("np", {"np": SymbolicValue(make_var("np"))})

    assert value == SymbolicValue(make_var("np"))


def test_missing_floor_on_unrelated_receiver_still_panics_for_unclassified_shape():
    with pytest.raises(FactoryGap):
        perform_operation(
            owner="CallSugar",
            blame="numpy.py:1:0",
            receiver=TermValue(1),
            operation=MethodCallOperation(
                name="astype",
                arguments=(StringValue("int64"),),
                owner="CallSugar",
                blame="numpy.py:1:0",
            ),
            ctx=ReduceContext(temporal=TemporalContext.empty()),
        )


def test_effectful_callsite_expected_emits_effect_not_euf_fact():
    report = build_literal_call_report(
        source=("def t(arr):\n" "    assert f(1) == arr.astype('int64')\n"),
        filename="numpy.py",
        memento_file="numpy.py",
    )

    assert report is not None
    assert report.payload.ir == []
    assert len(report.payload.effects) == 1
    effect = report.payload.effects[0]
    assert effect.name == "numpy::t::effect:2:19"
    assert isinstance(effect.effect)
    assert effect.effect.observed == "SymbolicValue.astype"
    assert effect.effect.requested == "symbolic receiver method floor"
    assert [row.status for row in report.payload.factory_walk] == ["factory-gap"]


def test_effectful_projected_equality_emits_effect_not_formula():
    report = build_literal_call_report(
        source=("def t(arr):\n" "    assert int(arr)[0] == 1\n"),
        filename="numpy.py",
        memento_file="numpy.py",
    )

    assert report is not None
    assert report.payload.ir == []
    assert len(report.payload.effects) == 1
    effect = report.payload.effects[0]
    assert isinstance(effect.effect)
    assert effect.effect.observed == "SymbolicValue.__int__"
    assert effect.effect.requested == "symbolic receiver method floor"
    assert [row.status for row in report.payload.factory_walk] == ["factory-gap"]


def test_external_bridge_keyword_effect_is_not_forced_to_call_term():
    report = build_literal_call_report(
        source=(
            "import numpy as np\n"
            "def t(arr):\n"
            "    assert np.array(arr, dtype=str)[0] == 1\n"
        ),
        filename="numpy.py",
        memento_file="numpy.py",
    )

    assert report is not None
    assert report.payload.ir == []
    assert len(report.payload.effects) == 1
    effect = report.payload.effects[0]
    assert isinstance(effect.effect)
    assert effect.effect.owner == "TemporalContext"
    assert effect.effect.observed == "str"
    assert [row.status for row in report.payload.factory_walk] == ["factory-gap"]


def test_local_bridge_body_effect_is_not_forced_to_universe():
    report = build_literal_call_report(
        source=(
            "def f(x):\n"
            "    if x == 1:\n"
            "        return result\n"
            "    return x\n"
            "def t():\n"
            "    assert g(f(1)) == 1\n"
        ),
        filename="numpy.py",
        memento_file="numpy.py",
    )

    assert report is not None
    assert report.payload.ir == []
    assert len(report.payload.effects) == 1
    effect = report.payload.effects[0]
    assert isinstance(effect.effect)
    assert effect.effect.owner == "TemporalContext"
    assert effect.effect.observed == "result"
    assert [row.status for row in report.payload.factory_walk] == ["factory-gap"]


def test_array_literal_element_effect_is_not_forced_to_value():
    report = build_literal_call_report(
        source=("def t():\n" "    assert f([nan]) == 1\n"),
        filename="numpy.py",
        memento_file="numpy.py",
    )

    assert report is not None
    assert report.payload.ir == []
    assert len(report.payload.effects) == 1
    effect = report.payload.effects[0]
    assert isinstance(effect.effect)
    assert effect.effect.owner == "TemporalContext"
    assert effect.effect.observed == "nan"
    assert [row.status for row in report.payload.factory_walk] == ["factory-gap"]


def test_prior_assignment_block_effect_is_reported_at_assignment_locus():
    from sugar_lift_py_tests.sugar.block_sugar import BlockFold, BlockSugar

    forced_effect = Incomplete(
        FactoryGapEffect(
            owner="CallSugar",
            blame="numpy.py:2:10",
            observed="SymbolicValue.mode",
            requested="symbolic receiver method floor",
            fix=(
                "add cited warrant for SymbolicValue.mode or keep the opaque "
                "runtime method as a typed effect"
            ),
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )
    )

    def forced_incomplete(self, ctx):
        return BlockFold(forced_effect, ctx)

    original_fold = BlockSugar.fold_with_context
    try:
        BlockSugar.fold_with_context = forced_incomplete
        report = build_literal_call_report(
            source=(
                "def t(arr):\n" "    res = arr.mode()\n" "    assert f(res) == 1\n"
            ),
            filename="numpy.py",
            memento_file="numpy.py",
        )
    finally:
        BlockSugar.fold_with_context = original_fold

    assert report is not None
    assert report.payload.ir == []
    assert len(report.payload.effects) == 1
    effect = report.payload.effects[0]
    assert effect.name == "numpy::t::effect:2:4"
    assert isinstance(effect.effect)
    assert effect.effect.owner == "CallSugar"
    assert effect.effect.observed == "SymbolicValue.mode"
    assert effect.effect.requested == "symbolic receiver method floor"
    assert [row.status for row in report.payload.factory_walk] == ["factory-gap"]
    assert report.payload.factory_walk[0].line == 2
    assert report.payload.factory_walk[0].ast_kind == "Assign"


def test_external_call_class_field_is_constructor_field_not_missing_attribute():
    report = build_literal_call_report(
        source=(
            "import numpy as np\n"
            "class NonHashableWithDtype:\n"
            "    __hash__ = None\n"
            "    dtype = np.dtype('float32')\n"
            "def t():\n"
            "    x = NonHashableWithDtype()\n"
            "    assert f(x.dtype) == 1\n"
        ),
        filename="numpy.py",
        memento_file="numpy.py",
    )

    assert report is not None
    assert len(report.payload.ir) == 1
    euf = report.payload.ir[0]
    assert euf.name.startswith("f#euf#c:call:f(")
    assert "py.object.identity" not in euf.name


def test_callsite_symbolic_expected_becomes_typed_proofir_effect():
    report = build_literal_call_report(
        source=("def t(expected):\n" "    assert f(1) == expected\n"),
        filename="numpy.py",
        memento_file="numpy.py",
    )

    assert report is not None
    assert report.payload.ir == []
    assert len(report.payload.effects) == 1
    effect = report.payload.effects[0]
    assert isinstance(effect.effect)
    assert effect.effect.owner == "literal_call_report.equality_fact"
    assert effect.effect.observed == "open term variable(s): expected"
    assert effect.effect.requested == "closed EqualityFact terms"
    assert effect.effect.gap_kind is GapKind.PROOFIR
    assert effect.effect.gap_locus is GapLocus.CONSTRUCTION_LAW


def test_inherited_opaque_constructor_argument_becomes_typed_effect():
    report = build_literal_call_report(
        source=(
            "import numpy as np\n"
            "class my_int16(np.int16):\n"
            "    pass\n"
            "def t():\n"
            "    s = repr(my_int16(3))\n"
            "    assert s == 'my_int16(3)'\n"
        ),
        filename="numpy.py",
        memento_file="numpy.py",
    )

    assert report is not None
    assert report.payload.ir == []
    assert len(report.payload.effects) == 1
    effect = report.payload.effects[0]
    assert isinstance(effect.effect)
    assert effect.effect.owner == "python.factory"
    assert effect.effect.observed == "my_int16(...)"
    assert effect.effect.requested == "inherited opaque constructor effect"
    assert effect.effect.gap_kind is GapKind.CONSTRUCTOR


def test_plain_zero_init_constructor_with_arguments_becomes_typed_effect():
    source = "class Plain:\n" "    pass\n" "def t():\n" "    assert f(Plain(3)) == 1\n"

    report = build_literal_call_report(
        source=source,
        filename="plain.py",
        memento_file="plain.py",
    )

    assert report is not None
    assert report.payload.ir == []
    assert len(report.payload.effects) == 1
    effect = report.payload.effects[0]
    assert isinstance(effect.effect)
    assert effect.effect.observed == "Plain(...)"
    assert effect.effect.requested == "zero-arg constructor"
    assert effect.effect.gap_kind is GapKind.CONSTRUCTOR
    assert [row.status for row in report.payload.factory_walk] == ["factory-gap"]
