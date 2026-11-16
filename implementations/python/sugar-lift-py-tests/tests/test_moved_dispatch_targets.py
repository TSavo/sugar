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

from frame_fresh import fresh
from sugar_lift_py_tests.floor import (
    GroundSequenceRepetitionValue,
    ListValue,
    StringValue,
    SymbolicValue,
    TermValue,
    TupleValue,
)
from sugar_lift_py_tests.ir import _Ctor, make_var
from sugar_lift_py_tests.outcome import ExitSet
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


def test_a_symbolic_receiver_has_no_store_arm_of_its_own() -> None:
    """The ``SymbolicValue.setitem``/``delitem`` arms that projected a
    ``py.setitem``/``py.delitem`` coordinate are deleted: they completed with
    no halt face.  A symbolic receiver's store is the one item mutation's
    undecided arm (``store_effect_sugar.item_mutation``); a path that reaches
    the floor's own method instead refuses by name (#7757 step 7)."""
    assert "setitem" not in SymbolicValue.__dict__
    assert "delitem" not in SymbolicValue.__dict__
    receiver = SymbolicValue(make_var("xs"))
    with pytest.raises(ConstructionPanic):
        receiver.setitem(TermValue(0), TermValue(7), "setitem-site", None)


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

    assert len(outcome.exits) == 1 and outcome.halts() == outcome.exits
    (halt,) = outcome.halts()
    expected = ctor(
        "adt.is_python_type",
        [value.to_term(owner="isinstance value"), dynamic_type.term],
    )
    assert halt.effect.witness.operation == expected
    assert halt.effect.witness.operand == dynamic_type.term
    assert halt.effect.witness.site is site


def test_dynamic_isinstance_keeps_a_value_owned_term_refusal_loud() -> None:
    source = "subject\n"
    tree = SourceFile(
        (source, "dynamic-isinstance-lie.py", blake3_512_of(source.encode()))
    )
    site = next(node for node in tree.nodes() if isinstance(node, Name)).fragment

    with pytest.raises(ConstructionPanic):
        SymbolicValue(make_var("RuntimeType")).test_python_type(FloorValue(), site)


# -- sugar.for_sugar cap -> floor/sequence_repetition.py --------------------
#
# `STATIC_UNFOLD_LIMIT` / `finite_unfold_cap_panic` were the abolished cap.
# `ArrayLiteral` had no producer left once a ground `str.split` folded to the
# list floor (#8055), so it is deleted; a list is `ListValue` (#7757).


def test_the_deleted_array_literal_floor_is_not_quietly_back() -> None:
    """Discriminating face: a second list floor nothing produces stays gone."""
    import sugar_lift_py_tests.floor as floor

    assert not _resolves("sugar_lift_py_tests.floor.array_literal")
    assert not _resolves("sugar_lift_py_tests.floor.builder_state")
    assert not hasattr(floor, "ArrayLiteral")
    assert not hasattr(floor, "BuilderState")


def test_list_repetition_folds_the_one_repetition_law() -> None:
    element = TermValue(7)

    outcome = fresh(ListValue, (element,)).multiply(
        TermValue(64), "multiply-site", None
    )

    assert outcome.completed_value() is not None
    assert isinstance(outcome.completed_value(), ListValue)
    assert outcome.completed_value().elements == (element,) * 64


@pytest.mark.parametrize(
    "sequence, count",
    [
        (fresh(ListValue, (TermValue(7),)), 1000),
        (TupleValue((TermValue(7),)), 1000),
    ],
)
def test_no_cardinality_refuses_a_concrete_repetition(sequence, count) -> None:
    """Over the eager budget the law FOLDS. The cap that panicked is abolished.

    This is the arm that used to reach `sugar.for_sugar`: above the static limit
    it raised (and latterly ImportError'd) instead of repeating.
    """
    outcome = sequence.multiply(TermValue(count), "multiply-site", None)

    assert outcome.completed_value() is not None
    assert isinstance(outcome.completed_value(), GroundSequenceRepetitionValue)
    assert outcome.completed_value().repetitions == count
    term = outcome.completed_value().to_term(owner="multiply-site")
    assert isinstance(term, _Ctor)
    assert term.name == "python:sequence_repeat"
    assert len(term.args) == 2


def test_a_symbolic_count_is_the_same_closed_coordinate() -> None:
    """A symbolic count repeats to the one closed `python:sequence_repeat`."""
    outcome = fresh(ListValue, (TermValue(7),)).multiply(
        SymbolicValue(make_var("n")), "multiply-site", None
    )

    assert outcome.completed_value() is not None
    assert isinstance(outcome.completed_value(), SymbolicValue)
    assert outcome.completed_value().term.name == "python:sequence_repeat"


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

    parts = fresh(ListValue, tuple(StringValue(str(n)) for n in range(300)))

    outcome = _fold_string_method(
        StringValue(","), _MethodCallOperation("join", (parts,))
    )

    assert outcome.completed_value() is not None
    assert isinstance(outcome.completed_value(), StringValue)
    assert outcome.completed_value().value == ",".join(str(n) for n in range(300))


def test_an_opaque_join_iterable_still_only_coordinates() -> None:
    """Discriminating face: removing the cap did not make the fold greedy.

    Expected shape changed (#8898): ``sep.join`` over an iterable the cited
    fold does not decide iterates it through the one iterator path and
    checks each member to be a ``str`` (``string_value._joined``), so an
    opaque formal's ``iter``, ``next`` and member check are halt faces at the
    call's source site (``test_str_join_states_its_iteration``), which this
    operation's prose blame cannot address.  The iterable here is the one
    whose iteration cannot raise and whose member is known to be a ``str``
    but is not ground -- an earlier join's coordinate in a tuple -- so the
    fold still answers only the ``STR_JOIN`` coordinate, never a computed
    string."""
    from sugar_lift_py_tests.floor.opaque_op_callsite import OpaqueOpCallsite
    from sugar_lift_py_tests.floor.string_value import _fold_string_method
    from sugar_source_tree.nodes import LanguageCallee

    inner = OpaqueOpCallsite(
        callee="join",
        arg=StringValue(","),
        computed=None,
        extra_args=(SymbolicValue(make_var("xs")),),
        language_callee=LanguageCallee.STR_JOIN,
    )
    outcome = _fold_string_method(
        StringValue(","),
        _MethodCallOperation("join", (TupleValue((inner,)),)),
    )

    assert outcome.completed_value() is not None
    assert isinstance(outcome.completed_value(), OpaqueOpCallsite)
    assert outcome.completed_value().computed is None


def test_the_deleted_cap_module_is_not_quietly_back() -> None:
    """Discriminating face: restoring the cap would restore the abolished lie."""
    assert not _resolves("sugar_lift_py_tests.sugar.for_sugar")


def test_the_deleted_block_sugar_is_not_quietly_back() -> None:
    assert not _resolves("sugar_lift_py_tests.sugar.block_sugar")


# -- operations.perform_operation -> operation.submit(value, ctx) -----------
#
# The rebuilt operations layer has no centre: the operation submits itself to
# the value, which is the same `getattr(receiver, method_name)(op, ctx)` the
# deleted dispatcher performed.


class _RecordingOperation:
    """One operation, submitting itself exactly as the rebuilt layer does."""

    method_name = "subscript_with"

    def __init__(self) -> None:
        self.submitted_to: list[object] = []

    def submit(self, value, ctx):
        self.submitted_to.append(value)
        return ExitSet.completed(value)


def test_a_block_redispatches_its_single_exit_by_submitting_the_operation():
    from sugar_lift_py_tests.floor.block_value import BlockValue

    exit_value = TermValue(7)
    operation = _RecordingOperation()

    outcome = BlockValue((exit_value,)).subscript_with(operation, None)

    assert outcome.completed_value() is not None
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


# -- operation methods typed against deleted operation modules: DEAD, deleted --
#
# Each `*_with` method below took an operation class whose module was deleted
# with the operations layer, and nothing submitted that operation any more.
# The floor surface declares only operations that exist.


def test_the_deleted_operation_methods_are_not_quietly_back() -> None:
    from sugar_lift_py_tests.floor import FLOOR_OPERATION_METHOD_NAMES, ObjectValue

    deleted = (
        "add_with",
        "attribute_with",
        "binary_operator_with",
        "call_method_with",
        "contains_with",
        "map_with",
        "project_callsite_with",
        "str_with",
        "unary_operator_with",
    )
    for name in deleted:
        assert name not in FLOOR_OPERATION_METHOD_NAMES, name
        assert not hasattr(FloorValue, name), name
        assert not hasattr(ObjectValue, name), name
        assert not hasattr(SymbolicValue, name), name


# -- sugar.install_source_dig.ContextualizedDigBody: DEAD, deleted ----------


def test_the_dig_body_type_exists_nowhere_so_no_arm_may_claim_it() -> None:
    """Discriminating face: the type is gone, and so is the callable that
    reached for it (``FunctionCallable``, deleted with its own binder: every
    call binds through ``object_value.bind_call``)."""
    assert not _resolves("sugar_lift_py_tests.sugar.install_source_dig")
    assert not _resolves("sugar_lift_py_tests.floor.function_callable")


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


# -- lift_rpc.lift_file_payload: LOST -- the axis is retired ----------------
#
# `live_per_file_isolation_conservation` measured the production lift one file
# at a time through a path deleted in 9d3b5c304. There is no successor, so
# `R_live_construction_panic_files` had no denominator (#6395). The instrument,
# its script and its gate are deleted (#7757); nothing is pinned here.
