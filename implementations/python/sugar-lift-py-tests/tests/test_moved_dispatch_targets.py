"""The mechanism behind each repaired dispatch promise, per target.

`test_dispatch_targets_resolve.py` proves the promises RESOLVE. Resolving is
not working: a name can resolve and still be the wrong door. These twins pin
what each repointed arm now does, so a future rewrite that re-breaks the arm
fails on behaviour rather than on spelling.

Each target gets both faces: the arm produces its stated result, AND the shape
that must not pass still does not. Where a target was found dead or lost, the
discriminating face pins its ABSENCE, so nobody quietly re-plumbs it.
"""

from __future__ import annotations

import importlib.util

import pytest

from sugar_lift_py_tests.floor import (
    ArrayLiteral,
    CallSiteValue,
    ListValue,
    StringValue,
    SymbolicValue,
    TermValue,
    TupleValue,
)
from sugar_lift_py_tests.floor.function_callable import FunctionCallable
from sugar_lift_py_tests.sugar.function_body_universe import FunctionBodyUniverse
from sugar_lift_py_tests.ir import _Ctor, make_var
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.outcome import Incomplete
from sugar_lift_py_tests.floor.floor_value import FloorValue
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.ir import ctor
from sugar_source_tree.nodes import Name
from sugar_source_tree.tree import SourceFile
from sugar_lift_python_source.canonical import blake3_512_of


def _resolves(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, AttributeError):
        return False


# -- sugar.floor_terms.floor_to_term -> FloorValue.to_term ------------------
#
# The deleted shim's whole body was `return value.to_term(owner=owner)`, so the
# method IS the door. Eleven arms reached for the shim.


def test_floor_to_term_arms_project_through_the_value_s_own_to_term() -> None:
    index, value = TermValue(0), TermValue(7)
    receiver = SymbolicValue(make_var("xs"))

    outcome = receiver.setitem(index, value, "setitem-site")

    assert isinstance(outcome, Complete)
    term = outcome.value.term
    assert isinstance(term, _Ctor)
    assert term.name == "py.setitem"
    # Exact cardinality: receiver, index, value -- one projected term each, and
    # the index/value legs are precisely what the value projects for itself.
    assert len(term.args) == 3
    assert term.args[1] == index.to_term(owner="SymbolicValue.setitem index")
    assert term.args[2] == value.to_term(owner="SymbolicValue.setitem value")


def test_the_deleted_floor_terms_shim_is_not_quietly_back() -> None:
    """Discriminating face: the module must stay gone, not be re-added."""
    assert not _resolves("sugar_lift_py_tests.sugar.floor_terms")


def test_dynamic_isinstance_projects_the_value_through_its_owned_term_door() -> None:
    source = "subject\n"
    tree = SourceFile((source, "dynamic-isinstance.py", blake3_512_of(source.encode())))
    site = next(node for node in tree.nodes() if isinstance(node, Name)).fragment
    value = SymbolicValue(make_var("subject"))
    dynamic_type = SymbolicValue(make_var("RuntimeType"))

    outcome = dynamic_type.test_python_type(value, site)

    assert isinstance(outcome, Incomplete)
    expected = ctor(
        "adt.is_python_type",
        [value.to_term(owner="isinstance value"), dynamic_type.term],
    )
    assert outcome.effect.witness.operation == expected
    assert outcome.effect.witness.operand == dynamic_type.term
    assert outcome.effect.witness.site is site


def test_dynamic_isinstance_keeps_a_value_owned_term_refusal_loud() -> None:
    source = "subject\n"
    tree = SourceFile((source, "dynamic-isinstance-lie.py", blake3_512_of(source.encode())))
    site = next(node for node in tree.nodes() if isinstance(node, Name)).fragment

    with pytest.raises(ConstructionPanic):
        SymbolicValue(make_var("RuntimeType")).test_python_type(
            FloorValue(), site
        )


# -- sugar.for_sugar cap -> floor/sequence_repetition.py --------------------
#
# `STATIC_UNFOLD_LIMIT` / `finite_unfold_cap_panic` were the abolished cap.
# ArrayLiteral was the straggler that never joined the one repetition law.


def test_array_repetition_folds_the_same_law_list_and_tuple_fold() -> None:
    element = TermValue(7)

    outcome = ArrayLiteral((element,)).multiply(TermValue(64), "multiply-site")

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, ArrayLiteral)
    assert outcome.value.items == (element,) * 64


@pytest.mark.parametrize(
    "sequence, count",
    [
        (ArrayLiteral((TermValue(7),)), 1000),
        (ListValue((TermValue(7),)), 1000),
        (TupleValue((TermValue(7),)), 1000),
    ],
)
def test_no_cardinality_refuses_a_concrete_repetition(sequence, count) -> None:
    """Over the eager budget the law FOLDS. The cap that panicked is abolished.

    This is the arm that used to reach `sugar.for_sugar`: above the static limit
    it raised (and latterly ImportError'd) instead of repeating.
    """
    outcome = sequence.multiply(TermValue(count), "multiply-site")

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, SymbolicValue)
    term = outcome.value.term
    assert isinstance(term, _Ctor)
    assert term.name == "python:sequence_repeat"
    assert len(term.args) == 2


def test_a_symbolic_count_is_the_same_closed_coordinate() -> None:
    """The array's private `SequenceRepetitionRuntimeEffect` arm is gone too."""
    outcome = ArrayLiteral((TermValue(7),)).multiply(
        SymbolicValue(make_var("n")), "multiply-site"
    )

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, SymbolicValue)
    assert outcome.value.term.name == "python:sequence_repeat"


class _MethodCallOperation:
    method_name = "call_method_with"

    def __init__(self, name, arguments) -> None:
        self.name = name
        self.arguments = arguments
        self.owner = "test"
        self.blame = "join-site"


def test_static_join_folds_at_any_cardinality() -> None:
    """`",".join([...])` over more parts than the abolished cap allowed."""
    from sugar_lift_py_tests.floor.string_value import _fold_string_method

    parts = ArrayLiteral(tuple(StringValue(str(n)) for n in range(300)))

    outcome = _fold_string_method(
        StringValue(","), _MethodCallOperation("join", (parts,))
    )

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, StringValue)
    assert outcome.value.value == ",".join(str(n) for n in range(300))


def test_an_opaque_join_iterable_still_only_coordinates() -> None:
    """Discriminating face: removing the cap did not make the fold greedy."""
    from sugar_lift_py_tests.floor.opaque_op_callsite import OpaqueOpCallsite
    from sugar_lift_py_tests.floor.string_value import _fold_string_method

    outcome = _fold_string_method(
        StringValue(","),
        _MethodCallOperation("join", (SymbolicValue(make_var("xs")),)),
    )

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, OpaqueOpCallsite)
    assert outcome.value.computed is None


def test_the_deleted_cap_module_is_not_quietly_back() -> None:
    """Discriminating face: restoring the cap would restore the abolished lie."""
    assert not _resolves("sugar_lift_py_tests.sugar.for_sugar")


# -- sugar.block_sugar.BlockSugar -> function_universe_sugar.reduce_body ----


class _EmptyBodyUniverse(FunctionBodyUniverse):
    parameter = "x"
    statements: tuple = ()

    def constraint_formulas(self):  # pragma: no cover - not reached by reduction
        return []


def test_a_body_universe_reduces_through_the_one_reduce_body_law() -> None:
    from sugar_lift_py_tests.floor.call_site_value import _reduce_callsite_body
    from sugar_lift_py_tests.sugar.function_universe_sugar import reduce_body
    from sugar_lift_py_tests.sugar.source_visible_function_body_sugar import (
        SourceVisibleFunctionBodySugar,
    )

    reduced = _reduce_callsite_body(_EmptyBodyUniverse(), None, blame="body-site")

    # The FunctionBodyUniverse arm reduces to exactly what `reduce_body` gives,
    # and to exactly what the SourceVisibleFunctionBodySugar arm two lines above
    # it gives -- one law for both, which is why `reduce_body` is the successor
    # of the deleted `BlockSugar.desugar` and not a lookalike.
    assert reduced == reduce_body((), None)
    assert reduced == SourceVisibleFunctionBodySugar((), object()).desugar(None)


def test_the_deleted_block_sugar_is_not_quietly_back() -> None:
    assert not _resolves("sugar_lift_py_tests.sugar.block_sugar")


# -- operations.perform_operation -> operation.submit(value, ctx) -----------
#
# The rebuilt operations layer has no centre: the operation submits itself to
# the value, which is the same `getattr(receiver, method_name)(op, ctx)` the
# deleted dispatcher performed.


class _RecordingOperation:
    """One operation, submitting itself exactly as the rebuilt layer does."""

    method_name = "unary_operator_with"

    def __init__(self) -> None:
        self.submitted_to: list[object] = []

    def submit(self, value, ctx):
        self.submitted_to.append(value)
        return Complete(value)


def test_a_block_redispatches_its_single_exit_by_submitting_the_operation():
    from sugar_lift_py_tests.floor.block_value import BlockValue

    exit_value = TermValue(7)
    operation = _RecordingOperation()

    outcome = BlockValue((exit_value,)).unary_operator_with(operation, None)

    assert isinstance(outcome, Complete)
    # Exact cardinality: submitted once, to the single exit -- not to the block.
    assert operation.submitted_to == [exit_value]


def test_the_deleted_dispatcher_and_its_operations_are_not_quietly_back() -> None:
    """Discriminating face: the whole deleted layer, by name.

    `#6316` rebuilt `operations` as a package holding ONE module. These names
    were never part of it; re-adding any of them would be re-centralising a
    dispatch the layer deliberately gave back to the operations themselves.
    """
    for module in (
        "sugar_lift_py_tests.operations.perform_operation",
        "sugar_lift_py_tests.operations.binary_operator_operation",
        "sugar_lift_py_tests.operations.floor_operation",
    ):
        assert not _resolves(module), module
    # The one module that IS there, and the submission protocol it defines.
    from sugar_lift_py_tests.operations import SequenceProjectionOperation

    assert hasattr(SequenceProjectionOperation, "submit")


# -- BinaryOperatorOperation("+") -> SymbolicValue.add ----------------------


class _AddOperation:
    method_name = "add_with"

    def __init__(self, operand) -> None:
        self.operand = operand
        self.owner = "test"
        self.blame = "add-site"


def test_symbolic_add_of_a_numeric_operand_is_the_joinable_plus_term() -> None:
    receiver = SymbolicValue(make_var("z"))

    outcome = receiver.add_with(_AddOperation(TermValue(1)), None)

    assert isinstance(outcome, Complete)
    term = outcome.value.term
    assert isinstance(term, _Ctor)
    assert term.name == "+"
    assert len(term.args) == 2
    # Identical to `z + 1` through the ordinary addition floor -- the whole
    # point of routing `z.add(1)` through the operator, per the arm's docstring.
    assert outcome == receiver.add(TermValue(1), "add-site")


def test_symbolic_add_of_an_opaque_operand_still_mints_the_call_coordinate():
    """Discriminating face: not everything becomes `+`; the vendor arm survives."""
    from sugar_lift_py_tests.floor.opaque_op_callsite import OpaqueOpCallsite

    receiver = SymbolicValue(make_var("z"))
    operand = ArrayLiteral((TermValue(1),))

    outcome = receiver.add_with(_AddOperation(operand), None)

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, OpaqueOpCallsite)
    assert outcome.value.callee == "add"
    assert outcome.value.computed is None


# -- sugar.install_source_dig.ContextualizedDigBody: DEAD, deleted ----------


def test_binding_a_call_no_longer_reaches_a_deleted_dig_body() -> None:
    """The hot path this task was really about.

    Every successful `FunctionCallable.callsite` ran an unconditional
    `from sugar_lift_py_tests.sugar.install_source_dig import
    ContextualizedDigBody`, so it raised ModuleNotFoundError: not a panic, not a
    typed refusal, not a family the census buckets -- the row came back short.
    """
    callable_ = FunctionCallable(
        name="f",
        parameters=("x",),
        parameter_kinds=("positional",),
        body=object(),
    )

    outcome = callable_.callsite((TermValue(1),), (), "call-site")

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, CallSiteValue)
    assert outcome.value.target_name == "f"


def test_the_dig_body_type_exists_nowhere_so_no_arm_may_claim_it() -> None:
    """Discriminating face: the type is gone AND its protocol is gone.

    `call_scope_updates` was deleted rather than repointed because nothing in
    the kit can answer `scope_after` / `callable_binding`. If a live type ever
    grows them, rebuild the arm deliberately -- do not resurrect the guard.
    """
    assert not _resolves("sugar_lift_py_tests.sugar.install_source_dig")
    assert not hasattr(FunctionCallable, "call_scope_updates")


# -- sugar.builtin_dunder_call_sugar: DEAD owner, claim deleted -------------


def test_the_dunder_frontier_can_run_and_names_only_live_owners() -> None:
    """A deleted owner owns nothing, and the frontier must be able to say so.

    The claim loop raised ImportError, so the report could not run AT ALL.

    This pins that the frontier runs and that every owner it names is a live
    one. It deliberately does NOT pin which slots come back unowned: that count
    is the residual the frontier exists to drive down, and writing a real owner
    for any of those dunders must turn this test greener, never red.
    """
    from sugar_lift_py_tests.idd.collect_dunder_frontier import _owned_dunder_slots

    owners = _owned_dunder_slots()

    assert owners, "the frontier must produce an owner map, not fail to run"
    # Live owner tables still register their slots -- the claim narrowed, the
    # report did not blank.
    assert owners["__iter__"] == "SequenceProjectionOperation"
    # No slot may be attributed to the deleted sugar. That is the actual law:
    # ownership is claimed by something that exists.
    assert not _resolves("sugar_lift_py_tests.sugar.builtin_dunder_call_sugar")
    assert "BuiltinDunderCallSugar" not in set(owners.values())


# -- lift_rpc.lift_file_payload: LOST -- deliberately NOT pinned here -------
#
# `live_per_file_isolation_conservation` measures the production lift one file
# at a time through a path deleted in 9d3b5c304. There is no successor, so
# `R_live_construction_panic_files` has no denominator (#6395).
#
# It now refuses by name (`MeasurementCapabilityLost`) instead of raising the
# ImportError the census cannot bucket, and that refusal is NOT re-raised into
# a residual row. There is deliberately no twin here asserting it raises.
#
# A passing test around a broken instrument would make its brokenness a green,
# protected fact and hide the work. The loud signal is the real gate going red:
# `test_lift_coverage_harness.py::
# test_heavy_vendor_live_per_file_isolation_conservation_delta_is_zero` now
# fails with a named refusal that says what is missing and why. That red belongs
# to #6395 and stays visible until the axis is rebuilt or retired.
