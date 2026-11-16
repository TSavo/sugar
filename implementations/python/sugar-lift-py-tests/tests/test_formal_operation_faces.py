"""An operation on a formal is evaluated where it stands (#7757 NEW-1).

The native-operation carrier (``NativeOperationExitCarrierV1``) that once
deferred an operation on a parameter until a caller's actual discharged it
is deleted: production never supplied an actual, so every carrier ended as
the undecided two faces it now is at once.  Each operation on a formal
completes only under its own ``.completes`` atom, halts with an
``UndeterminedRaiseEffect`` under the complement from the record of the
statement it stands in, and owes the ``undecided`` member on both faces.
A decided receiver is its floor's own operation.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from frame_fresh import fresh
from sugar_lift_py_tests.context_manager_resolution import (
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.effect.authenticated_raise_locus import AuthenticatedRaiseLocus
from sugar_lift_py_tests.floor import (
    FloorValue,
    ListValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.floor.floor_value import (
    BINARY_FLOOR_OPERATIONS,
    _BINARY_OPERATOR_COORDINATE,
)
from sugar_lift_py_tests.formal_parameter import FormalParameterCoordinateV1
from sugar_lift_py_tests.ir import PrimitiveSort, ctor, make_var, str_const
from sugar_lift_py_tests.outcome import (
    Completed,
    ExitSet,
    Halted,
)
from sugar_lift_py_tests.outcome.exit_set import complement_guard
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import FunctionDef
from sugar_source_tree.tree import SourceFile


def _site():
    source = "def operation(left, right):\n    return left + right\n"
    tree = SourceFile(
        (source, "native_operation.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    return next(tree.functions()).fragment


def _coordinate(name: str, ordinal: int) -> FormalParameterCoordinateV1:
    source_cid = "blake3-512:" + "a" * 128
    owner = SourceFragmentCoordinateV1(source_cid, 1, 0, 2, 23)
    return FormalParameterCoordinateV1.mint(
        owner_source_identity_cid=source_cid,
        owner_definition_locus=owner,
        declaration_locus=SourceFragmentCoordinateV1(
            source_cid, 1, 14 + ordinal * 6, 1, 18 + ordinal * 6
        ),
        ordinal=ordinal,
        parameter_kind="positional-or-keyword",
        declared_name=name,
        sort=PrimitiveSort("Value"),
    )


def _undecided_binary_arms(outcome, operator: str):
    """The undecided binary law's two faces (``undecided_binary_faces``):
    the result completes only under its own ``python:binary_op.completes``
    atom, an ``UndeterminedRaiseEffect`` halts under the complement, and
    both owe the undecided member."""
    assert isinstance(outcome, ExitSet), outcome
    (completed,) = (exit_ for exit_ in outcome.exits if isinstance(exit_, Completed))
    (halted,) = (exit_ for exit_ in outcome.exits if isinstance(exit_, Halted))
    assert completed.guard.name == "python:binary_op.completes"
    assert halted.guard == complement_guard(completed.guard)
    assert isinstance(halted.effect, UndeterminedRaiseEffect)
    assert halted.effect.producer_node_owner == f"UndecidedBinary:{operator}"
    assert halted.effect.exception_name is None
    assert completed.owed and completed.owed == halted.owed
    return completed, halted


@pytest.mark.parametrize("method", tuple(_BINARY_OPERATOR_COORDINATE))
def test_formal_binary_dispatch_is_the_undecided_two_faces(method):
    """A binary operator with a parameter operand mints no carrier: the
    operator is a protocol with a fallback (``__op__``, then the reflected
    ``__rop__``) that no one dispatched method states, so it is the one
    undecided binary law, whether or not the parameter's class is an input
    (#7757, audit row NEW-1)."""
    left_coordinate = _coordinate("left", 0)
    right_coordinate = _coordinate("right", 1)
    left = SymbolicValue(make_var("left"), left_coordinate)
    right = SymbolicValue(make_var("right"), right_coordinate)
    operator = _BINARY_OPERATOR_COORDINATE[method]

    outcome = BINARY_FLOOR_OPERATIONS[method](left, right, _site(), None)

    completed, _halted = _undecided_binary_arms(outcome, operator)
    result = completed.value.term
    assert result.name == "python:binary_result"
    assert result.args[0] == str_const(operator)
    assert result.args[1:3] == (make_var("left"), make_var("right"))


def test_swapped_formal_binary_operands_retain_distinct_ordered_results():
    left_coordinate = _coordinate("left", 0)
    right_coordinate = _coordinate("right", 1)
    left = SymbolicValue(make_var("left"), left_coordinate)
    right = SymbolicValue(make_var("right"), right_coordinate)

    forward, _ = _undecided_binary_arms(left.subtract(right, _site(), None), "-")
    reverse, _ = _undecided_binary_arms(right.subtract(left, _site(), None), "-")

    assert forward.value.term.args[1:3] == (make_var("left"), make_var("right"))
    assert reverse.value.term.args[1:3] == (make_var("right"), make_var("left"))
    assert forward.value != reverse.value
    assert forward.guard != reverse.guard


@pytest.mark.parametrize("formal_side", ("left", "right"))
def test_either_formal_operand_takes_the_undecided_two_faces(formal_side):
    coordinate = _coordinate(formal_side, 0)
    left = SymbolicValue(
        make_var("left"), coordinate if formal_side == "left" else None
    )
    right = SymbolicValue(
        make_var("right"), coordinate if formal_side == "right" else None
    )

    outcome = left.add(right, _site(), None)

    _undecided_binary_arms(outcome, "+")


def test_coordinate_free_binary_dispatch_retains_existing_symbolic_faces():
    outcome = SymbolicValue(make_var("left")).add(
        SymbolicValue(make_var("right")), _site(), None
    )

    assert isinstance(outcome, ExitSet)
    assert (
        len(tuple(exit_ for exit_ in outcome.exits if isinstance(exit_, Completed)))
        == 1
    )
    assert (
        len(tuple(exit_ for exit_ in outcome.exits if isinstance(exit_, Halted))) == 1
    )

class _Expected:
    def __init__(self, name: str):
        self.identity = ctor(
            "python:exception_type_identity",
            [str_const("builtins"), str_const(name)],
        )

    def exception_type_identity(self):
        return self.identity


def _setitem_site():
    source = "def store(receiver, index, value):\n    receiver[index] = value\n"
    tree = SourceFile(
        (source, "setitem_operation.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    return next(tree.functions()).fragment


def _setattr_site():
    source = "def store(receiver, value):\n    receiver.name = value\n"
    tree = SourceFile(
        (source, "setattr_operation.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    return next(tree.functions()).fragment


def _item_store(receiver, index, value):
    """``receiver[index] = value`` through the one item mutation (#7757 step
    7): an item store mints no carrier, and a decided receiver is its
    floor's own store."""
    from sugar_lift_py_tests.sugar.store_effect_sugar import item_mutation

    return item_mutation(
        "__setitem__", receiver, (index, value), _setitem_site(), None, unit=None
    )


@dataclass(frozen=True)
class _AttrStoreReceiver(FloorValue):
    """Minimal decided Floor receiver that owns ``setattr``: the one
    attribute mutation reaches its own store."""

    fields: tuple[tuple[str, FloorValue], ...] = ()

    def setattr(self, name, value, site, ctx):
        del site, ctx
        remaining = tuple(field for field in self.fields if field[0] != name)
        return ExitSet.completed(_AttrStoreReceiver((*remaining, (name, value))))

    def to_term(self, *, owner: str):
        del owner
        return ctor(
            "test:attr_store_receiver",
            [
                ctor(
                    "test:attr_store_field",
                    [str_const(name), field.to_term(owner="attr-store")],
                )
                for name, field in self.fields
            ],
        )


def test_item_store_on_a_decided_list_stores_the_value_at_the_index():
    """``receiver[index] = value`` on a decided list is the list's own store:
    the value lands at the index, never the index at the value."""
    exits = _item_store(
        fresh(ListValue, (TermValue(0), TermValue(1))), TermValue(0), TermValue(9)
    )

    assert len(exits.exits) == 1
    completed = exits.exits[0]
    assert isinstance(completed, Completed)
    assert completed.value == fresh(ListValue, (TermValue(9), TermValue(1)))


def test_item_store_halts_with_named_exception_identity():
    """Store halt identity comes from the operation floor, never the boundary."""
    exits = _item_store(fresh(ListValue, (TermValue(0),)), TermValue(4), TermValue(9))

    assert len(exits.exits) == 1
    halted = exits.exits[0]
    assert isinstance(halted, Halted)
    assert halted.effect.exception_type_coordinate == _Expected("IndexError").identity
    assert isinstance(halted.effect.occurrence, AuthenticatedRaiseLocus)
    assert (
        isinstance(halted.effect.occurrence_id, str)
        and ":" in halted.effect.occurrence_id
    ), (
        "authenticated raise locus must be a file:line:col occurrence id, "
        f"not presence-only; got {halted.effect.occurrence_id!r}"
    )


def test_attribute_store_on_a_decided_receiver_is_its_own_setattr():
    """``receiver.name = value`` on a decided receiver is its own store
    through the one attribute mutation (``store_effect_sugar.
    attribute_mutation``, #7757): the name is the static identifier, the
    value lands under it.  An attribute store mints no carrier."""
    from sugar_lift_py_tests.sugar.store_effect_sugar import attribute_mutation

    exits = attribute_mutation(
        "__setattr__",
        _AttrStoreReceiver(),
        "name",
        (TermValue(7),),
        _setattr_site(),
        None,
        unit=None,
    )

    assert len(exits.exits) == 1
    completed = exits.exits[0]
    assert isinstance(completed, Completed)
    assert completed.value == _AttrStoreReceiver((("name", TermValue(7)),))


def test_attribute_store_on_a_formal_is_no_carrier():
    """``receiver.name = value`` on a formal waits on no caller's actual: it
    is the undecided store, its halt kept (#7757)."""
    from sugar_lift_py_tests.sugar.store_effect_sugar import attribute_mutation

    receiver = _coordinate("receiver", 0)
    exits = attribute_mutation(
        "__setattr__",
        SymbolicValue(make_var("receiver"), receiver),
        "name",
        (TermValue(7),),
        _setattr_site(),
        None,
        unit=None,
    )

    assert isinstance(exits, ExitSet)
    assert [halt.effect.producer_node_owner for halt in exits.halts()] == [
        "UndecidedSetattr"
    ]
    assert exits.completed_value() is None


def test_source_evaluation_order_rhs_receiver_index_is_independent_of_the_store():
    """Python eval order (RHS, receiver, index) is not the setitem call order.

    Source producers evaluate value first, then the target's receiver, then
    the index.  The store still calls ``setitem(index, value)`` on the
    receiver (``store_effect_sugar.item_mutation``, #7757).
    """
    order: list[str] = []

    @dataclass(frozen=True)
    class _Probe(Sugar):
        label: str
        payload: FloorValue

        def desugar(self, ctx=None):
            del ctx
            order.append(self.label)
            return ExitSet.completed(self.payload)

        @classmethod
        def witnesses(cls):
            return ()

    # The store producer's source chain (window 10876): value → receiver → index.
    value = _Probe("value", TermValue(9))
    receiver = _Probe("receiver", fresh(ListValue, (TermValue(0),)))
    index = _Probe("index", TermValue(0))
    source_outcome = value.desugar().and_then(
        lambda stored: receiver.desugar().and_then(
            lambda recv: index.desugar().and_then(
                lambda idx: recv.setitem(idx, stored, _setitem_site(), None)
            )
        )
    )
    assert order == ["value", "receiver", "index"]
    assert source_outcome.completed_value() == fresh(ListValue, (TermValue(9),))


def test_lying_swapped_index_and_value_must_fail_to_match_correct_store():
    """Swapped index/value still calls cleanly — so order must be enforced by twins.

    Both orders invoke ``setitem`` without TypeError.  The store with the
    value and the index swapped must not claim the truthful store face.
    """

    def receiver():
        return fresh(ListValue, (TermValue(0), TermValue(1), TermValue(2)))

    truthful_exits = _item_store(receiver(), TermValue(1), TermValue(99))
    # LYING store: index and value swapped.
    lying_exits = _item_store(receiver(), TermValue(99), TermValue(1))

    assert isinstance(truthful_exits.exits[0], Completed)
    assert truthful_exits.exits[0].value == fresh(
        ListValue, (TermValue(0), TermValue(99), TermValue(2))
    )
    # The lying order stores at index 99 (the value) — IndexError — or at the
    # wrong cell.  Either way it must not equal the truthful post-state.
    lying_face = lying_exits.exits[0]
    if isinstance(lying_face, Completed):
        assert lying_face.value != truthful_exits.exits[0].value
    else:
        assert isinstance(lying_face, Halted)

def test_symbolic_formal_subscript_is_the_undecided_read_not_a_carrier():
    """A parameter's read mints no ``subscript`` carrier (#7757, audit 2 row
    NEW-1): nothing decides ``type(p)`` or its ``__getitem__``, so
    ``SymbolicValue.subscript`` is the one undecided read -- a completed
    face under its own atom and an ``UndeterminedRaiseEffect`` halt, the
    halt kept."""
    receiver_coordinate = _coordinate("receiver", 0)
    formal = SymbolicValue(make_var("receiver"), receiver_coordinate)

    outcome = formal.subscript(TermValue(0), _site())

    assert isinstance(outcome, ExitSet), type(outcome)
    assert sum(isinstance(exit_, Completed) for exit_ in outcome.exits) == 1
    (halted,) = [exit_ for exit_ in outcome.exits if isinstance(exit_, Halted)]
    assert isinstance(halted.effect, UndeterminedRaiseEffect), halted.effect


_MULTI_PRIOR_STORE_BINARY = (
    "def multi(left, right):\n"
    "    a = [0]\n"
    "    a[0] = 9\n"
    "    r = left + right\n"
    "    return r\n"
)


def test_a_formal_operation_halt_leaves_with_the_earlier_store_in_its_state():
    """The halt of ``left + right`` on two formals leaves from the record the
    body reached before the statement (``a[0] = 9`` in it), as the carrier's
    enrolled pre-effect state once stated it: the statement halts at its
    head, and the block reducer gives it the block's prefix.  Both faces owe
    the undecided member at the operation's site."""
    from sugar_lift_py_tests.unanswered_calls import owed_calls, unanswered_call

    source = _MULTI_PRIOR_STORE_BINARY
    tree = SourceFile(
        (source, "formal_operation_state.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    function = next(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == "multi"
    )
    outcome = function.sugar().desugar(None)

    assert isinstance(outcome, ExitSet), type(outcome)
    (halt,) = [
        face
        for face in outcome.halts()
        if face.effect.producer_node_owner == "UndecidedBinary:+"
    ]
    assert isinstance(halt.effect, UndeterminedRaiseEffect), halt.effect
    assert halt.effect.exception_name is None
    assert halt.state is not None, "the operation's halt dropped its state"
    lists = [entry for entry in halt.state.entries if isinstance(entry, ListValue)]
    assert lists == [fresh(ListValue, (TermValue(9),))], halt.state.entries
    assert unanswered_call(None, halt.effect.site) in owed_calls(outcome)


def test_the_native_operation_carrier_is_gone():
    """No operation waits on a caller's actual: the carrier, its demand and
    resolution, its reducer enrollment, its projector table and its operator
    set are deleted (#7757 NEW-1)."""
    from sugar_lift_py_tests import caller_parameter_contract, outcome, tree_enumerate

    for name in (
        "NativeOperationExitCarrierV1",
        "NativeOperationDemandV1",
        "NativeOperationResolutionV1",
        "ReducerPreEffectStateV1",
        "authenticated_exceptional_resolution_count",
        "native_operator_demand",
        "_NATIVE_OPERATION_PROJECTORS",
        "production_native_operation_operators",
        "_typed_minted_native_operator_constants",
    ):
        assert not hasattr(caller_parameter_contract, name), name
        assert not hasattr(outcome, name), name
    assert not hasattr(tree_enumerate, "as_its_own_proof_states")
