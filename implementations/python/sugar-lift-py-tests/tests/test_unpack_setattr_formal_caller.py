"""JOIN CHECK: unpack assignment with a field store on a formal.

Concrete program:

    def f(obj, p, q):
        x, obj.field = p, q
        return x

The unpack admits a Name leaf (``x``) then an attribute store leaf.  The store
is the one attribute mutation (``store_effect_sugar.attribute_mutation``,
#7757 NEW-1): on the formal ``obj`` it is the undecided store -- completing
under its own atom (or where prove decides the store plain), raising
something undetermined under the complement, both faces owed -- never a
carrier waiting on a caller's actuals (the ``setattr_named`` carrier and its
projector are deleted).  What a caller supplies is stored through the same
door: Completed field stores or the named AttributeError.

Operand order (``type(obj).__setattr__(obj, "field", q)``):

  source evaluation (store half): value → receiver   (q, obj)
  the store:                      receiver, name, value
                                  (obj, "field", q)

  The name is static: never an operand the source evaluates.

Acceptance (each with a discrimination twin):

  1. Helper alone is the undecided store over ``obj``, its halt kept.
  2. Writable source-defined receiver completes the field store; ``x``
     binds ``p``.
  3. Getter-only property → named AttributeError; never fabricated
     statement completion.
  4. RHS/receiver evaluation order differs from the store's operand order.
  5. First-store halt blocks later targets.
  6. Swapped receiver/value and read-authorizes-write twins fail.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.caller_parameter_contract import (
    NativeOperationExitCarrierV1,
    _NATIVE_OPERATION_PROJECTORS,
)
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import (
    ObjectField,
    ObjectValue,
    TermValue,
)
from sugar_lift_py_tests.floor.class_definition_value import ClassDefinitionValue
from sugar_lift_py_tests.floor.return_value import ReturnValue
from sugar_lift_py_tests.floor.universe_value import UniverseValue
from sugar_lift_py_tests.ir import str_const
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted, true_guard
from sugar_lift_py_tests.sugar import store_effect_sugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import ClassDef, FunctionDef
from sugar_source_tree.tree import SourceFile

from frame_fresh import FRAME_FRESH

PROGRAM = "def f(obj, p, q):\n    x, obj.field = p, q\n    return x\n"


def _tree(source: str, name: str = "unpack_setattr_caller.py") -> SourceFile:
    return SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


def _helper():
    tree = _tree(PROGRAM, "helper_alone.py")
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    return function, function.sugar().desugar(None)


def _identity(name: str):
    from sugar_lift_py_tests.ir import ctor

    return ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const(name)],
    )


def _undecided_store(outcome) -> Halted:
    """The undecided attribute store in ``f``'s own proof: no carrier, one
    ``UndeterminedRaiseEffect`` halt owned by ``UndecidedSetattr`` kept with
    the state the store began from, the undecided member owed on every face,
    never a completion."""
    from sugar_lift_py_tests.unanswered_calls import owed_calls, unanswered_call

    assert isinstance(outcome, ExitSet), type(outcome)
    assert not isinstance(outcome, NativeOperationExitCarrierV1)
    halts = [
        face
        for face in outcome.halts()
        if face.effect.producer_node_owner == "UndecidedSetattr"
    ]
    assert len(halts) == 1, outcome
    (halt,) = halts
    assert type(halt.effect) is UndeterminedRaiseEffect
    assert halt.state is not None
    owed = unanswered_call(None, halt.effect.site)
    assert owed in owed_calls(outcome)
    assert owed in halt.owed
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    assert completed, outcome
    assert all(owed in face.owed for face in completed)
    assert outcome.completed_value() is None
    return halt


def _store_operations(outcome):
    """Every ``python:setattr(<receiver>, <name>, <occurrence>)`` the
    completed faces' guards name: the undecided store's completes atom."""

    def walk(node, depth=0):
        if getattr(node, "name", None) == "python:setattr":
            yield node
        if depth > 64:
            return
        for child in (
            *(getattr(node, "args", ()) or ()),
            *(getattr(node, "operands", ()) or ()),
        ):
            yield from walk(child, depth + 1)

    operations = [
        atom
        for face in outcome.exits
        if isinstance(face, Completed)
        for atom in walk(face.guard)
    ]
    assert operations, outcome
    return operations


def _stored(function, receiver, value):
    """``receiver.field = value`` through the one attribute mutation at the
    store's site, the receiver a value the lift decides (what a caller
    supplies)."""
    return store_effect_sugar.attribute_mutation(
        "__setattr__",
        receiver,
        "field",
        (value,),
        function.body[0].fragment,
        None,
        unit=None,
    )


def _source_class_receiver(class_body: str):
    """A source-defined class receiver (ClassDef door) beside ``f``, whose
    own proof is the undecided store."""
    source = f"class Widget:\n{class_body}\n" + PROGRAM
    tree = _tree(source, "source_class_unpack_setattr.py")
    class_def = next(node for node in tree.nodes() if isinstance(node, ClassDef))
    helper = next(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == "f"
    )
    class_outcome = class_def.sugar().desugar(None)
    class_value = class_outcome.completed_value()
    assert isinstance(class_value, ClassDefinitionValue)
    receiver = class_value.fresh_receiver(
        class_value.class_definition_cid, allocation=FRAME_FRESH
    )
    assert isinstance(receiver, ObjectValue)
    _undecided_store(helper.sugar().desugar(None))
    return helper, receiver


# ---------------------------------------------------------------------------
# 1. Helper alone is the undecided store
# ---------------------------------------------------------------------------


def test_helper_alone_is_the_undecided_store_over_obj() -> None:
    _, outcome = _helper()
    _undecided_store(outcome)
    for operation in _store_operations(outcome):
        receiver, name, _key = operation.args
        assert getattr(receiver, "name", None) == "obj", receiver
        assert name == str_const("field")
    # The carrier, its mint and its projector are deleted.
    assert "setattr_named" not in _NATIVE_OPERATION_PROJECTORS
    assert not hasattr(store_effect_sugar, "mint_setattr_named_carrier")


def test_helper_alone_is_not_a_completed_face_discrimination() -> None:
    _, outcome = _helper()
    with pytest.raises(AssertionError):
        assert outcome.completed_value() is not None
    with pytest.raises(AssertionError):
        assert not outcome.halts()


def test_helper_alone_completed_face_returns_p() -> None:
    """Where the store completes, ``x`` binds ``p``: the return is ``p``."""
    _, outcome = _helper()
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    assert completed, outcome
    for face in completed:
        assert isinstance(face.value, UniverseValue), face.value
        returns = [
            s for s in face.value.record.statements if isinstance(s, ReturnValue)
        ]
        assert len(returns) == 1
        assert returns[0].value.term.name == "p"


# ---------------------------------------------------------------------------
# 2. Writable source-defined receiver completes the field store
# ---------------------------------------------------------------------------


def test_writable_source_defined_receiver_completes_field_store() -> None:
    helper, receiver = _source_class_receiver("    pass\n")
    assert receiver.methods == ()
    exits = _stored(helper, receiver, TermValue(7))
    assert len(exits.exits) == 1
    face = exits.exits[0]
    assert isinstance(face, Completed)
    assert isinstance(face.value, ObjectValue)
    assert face.value.fields[-1].name == "field"
    assert face.value.fields[-1].value == TermValue(7)


def test_writable_source_defined_receiver_completes_discrimination() -> None:
    helper, receiver = _source_class_receiver("    pass\n")
    exits = _stored(helper, receiver, TermValue(7))
    with pytest.raises(AssertionError):
        assert isinstance(exits.exits[0], Halted), "writable field must complete"


# ---------------------------------------------------------------------------
# 3. Getter-only property → AttributeError
# ---------------------------------------------------------------------------


def test_property_without_setter_named_attribute_error() -> None:
    """Expected verdict changed (#7757 NEW-1): the carrier's pre-effect state
    identity (``halted.state is pending.pre_effect_state.state``) has
    nothing to compare against now -- the carrier is deleted.  The state
    ``f``'s own store halt keeps is the block's record
    (``_undecided_store``)."""
    helper, receiver = _source_class_receiver(
        "    @property\n" "    def field(self):\n" "        return 1\n"
    )
    assert any(
        m.name == "field" and m.descriptor_kind == "property" for m in receiver.methods
    )
    # Floor store path (not read) refuses.
    site = helper.body[0].fragment
    from sugar_lift_py_tests.effect import RaiseEffect

    direct = receiver.setattr("field", TermValue(7), site, None)
    assert direct.halts() == direct.exits
    (direct_halt,) = direct.halts()
    assert isinstance(direct_halt.effect, RaiseEffect)
    assert direct_halt.effect.exception_name == "AttributeError"
    assert direct_halt.effect.producer_node_owner == "ObjectValue.setattr"

    exits = _stored(helper, receiver, TermValue(7))
    assert len(exits.exits) == 1
    halted = exits.exits[0]
    assert isinstance(halted, Halted)
    assert not isinstance(halted, Completed)
    assert halted.effect.exception_type_coordinate == _identity("AttributeError")
    assert halted.effect.occurrence_id == f"{site.filename}:{site.line}:{site.col}"
    assert not isinstance(getattr(halted, "value", None), UniverseValue)


def test_property_without_setter_discrimination_not_completed() -> None:
    """Bite: getter must not authorize a Completed store."""
    helper, receiver = _source_class_receiver(
        "    @property\n" "    def field(self):\n" "        return 1\n"
    )
    exits = _stored(helper, receiver, TermValue(99))
    with pytest.raises(AssertionError):
        assert isinstance(exits.exits[0], Completed), "read path licensed a store"


def test_read_authorizes_write_twin_fails() -> None:
    """Lying twin: borrowing readable property evidence to complete a store."""
    helper, receiver = _source_class_receiver(
        "    @property\n" "    def field(self):\n" "        return 1\n"
    )
    # Property is readable via the enrollment of the getter.
    assert any(m.descriptor_kind == "property" for m in receiver.methods)
    exits = _stored(helper, receiver, TermValue(1))
    assert isinstance(exits.exits[0], Halted)
    with pytest.raises(AssertionError):
        assert isinstance(exits.exits[0], Completed), "read authorized write"


# ---------------------------------------------------------------------------
# 4. Evaluation order ≠ the store's operand order
# ---------------------------------------------------------------------------


def test_eval_order_differs_from_store_operand_order() -> None:
    """Store half: source eval is value→receiver; the store names receiver,
    then the static name (``type(obj).__setattr__(obj, "field", q)``)."""
    _, outcome = _helper()
    (operation, *_rest) = _store_operations(outcome)
    receiver, name, _key = operation.args
    assert (receiver.name, name) == ("obj", str_const("field"))
    # Source evaluation reads ``q`` first; the store's first operand is
    # ``obj``, never the value evaluated first.
    with pytest.raises(AssertionError):
        assert receiver.name == "q"


def test_swapped_receiver_value_twin_fails() -> None:
    """A store with receiver and value swapped is distinguishable: the
    truthful store completes with the field stored, the swapped one is
    ``9.field = <object>``, the named AttributeError."""
    function, outcome = _helper()
    writable = ObjectValue(
        "R", (ObjectField("field", TermValue(0)),), allocation=FRAME_FRESH
    )
    truthful = _stored(function, writable, TermValue(9))
    assert isinstance(truthful.exits[0], Completed)
    assert truthful.exits[0].value.fields[-1].value == TermValue(9)

    lying = _stored(function, TermValue(9), writable)
    assert isinstance(lying.exits[0], Halted)
    assert lying.exits[0].effect.exception_type_coordinate == _identity(
        "AttributeError"
    )

    # The helper's own store names ``obj``, never the value ``q``.
    receivers = {
        getattr(operation.args[0], "name", None)
        for operation in _store_operations(outcome)
    }
    with pytest.raises(AssertionError):
        assert "q" in receivers, "receiver and value collapsed"


# ---------------------------------------------------------------------------
# 5. First-store halt blocks later targets
# ---------------------------------------------------------------------------


def test_first_store_halt_blocks_later_targets() -> None:
    """``o.x, o.y = p, q`` with ``o`` bound nowhere: the first target's read of
    ``o`` is Python's ``NameError``, and no later target runs.

    The module binds no ``o``, so ``o`` is not an object of undecided type: the
    first store's receiver read raises.  The body has that one unconditional
    halt and nothing else -- no second halt from ``o.y``, no completed arm."""
    from sugar_lift_py_tests.effect import NameErrorEffect

    source = "def f(p, q):\n    o.x, o.y = p, q\n    return p\n"
    tree = _tree(source, "dual_attr.py")
    fn = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    outcome = fn.sugar().desugar(None)
    halted = [e for e in outcome.exits if isinstance(e, Halted)]
    completed = [e for e in outcome.exits if isinstance(e, Completed)]
    assert len(halted) == 1
    assert completed == []
    assert isinstance(halted[0].effect, NameErrorEffect)
    assert halted[0].effect.name == "o"
    assert halted[0] == Halted(true_guard(), halted[0].effect, halted[0].state)
    # The halt was reached before any store: its guard states no store
    # (``python:setattr``) completed or halted.
    assert all("python:setattr" not in repr(h.guard) for h in halted), halted
    # No completed-only reading of the body.
    assert not (len(halted) == 0 and len(completed) == 1)


def test_first_store_halt_blocks_later_targets_discrimination() -> None:
    """Bite: dual free stores must not present a sole Completed arm."""
    source = "def f(p, q):\n    o.x, o.y = p, q\n    return p\n"
    tree = _tree(source, "dual_attr_d.py")
    fn = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    outcome = fn.sugar().desugar(None)
    with pytest.raises(AssertionError):
        assert len(outcome.exits) == 1 and isinstance(
            outcome.exits[0], Completed
        ), "later target ran after first-store halt"
