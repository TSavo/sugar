"""The one field store decides by the receiver's class (#7757).

``o.f = v`` is ``type(o).__setattr__(o, 'f', v)``.  The one class lookup on
the receiver's value decides what that runs
(``ObjectValue.field_store_route``), and the store, its post-state and what
the statement exposes all read that one decision:

- a class that takes ``object``'s ``__setattr__`` and binds no data
  descriptor for the name: the plain store, which changes the object only;
- a class whose lookup selects a source ``__setattr__``, or a source
  descriptor's ``__set__`` for the name: a call of that function, followed
  like any call;
- a class whose lookup does not decide: the one unanswered call, and the
  field is undecided.

``container_mutation.holder_states`` no longer assumes a field store is the
plain store of one field: a name that shares something with the object is
rebound to its value after the store, which the receiver's value decides at
reduce (``_may_change`` under ``field_store_method``).
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from pathlib import Path

from frame_fresh import FRAME_FRESH, fresh

from sugar_lift_py_tests.effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import (
    ListValue,
    NoneValue,
    ObjectField,
    ObjectMethodValue,
    ObjectValue,
    StringValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.floor.object_identity import contents_current
from sugar_lift_py_tests.floor.receiver_field_store_value import (
    ReceiverFieldStoreValue,
)
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.lift_rpc import tree_construction_context_for_workspace
from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.builtin_container_call_sugar import _may_change
from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock
from sugar_lift_py_tests.sugar.receiver_field_store_sugar import (
    ReceiverFieldStoreSugar,
)
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_python_source.source_oracle import workspace_path_source
from sugar_source_tree.container_mutation import (
    field_store_method,
    field_store_rule,
    holder_states,
)
from sugar_source_tree.tree import SourceFile

AFTER = "evaluation:store/.x="


def _site(tmp_path: Path):
    path = tmp_path / "field_store.py"
    path.write_text("def f(obj, value):\n    obj.x = value\n")
    function = next(
        SourceFile(
            workspace_path_source(str(path), root=str(tmp_path)),
            construction_context=tree_construction_context_for_workspace(tmp_path),
        ).functions()
    )
    return function.body[0].fragment


@dataclass(frozen=True)
class _Read(Sugar):
    value: object

    @classmethod
    def witnesses(cls):
        raise AssertionError("test helper has no witness")

    def desugar(self, ctx=None):
        del ctx
        return ExitSet.completed(self.value)


@dataclass(frozen=True)
class _Body(Sugar):
    """A method body the tests never apply (``_Recording.call_member``)."""

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        raise AssertionError("the recorded member call applies no body")


_CALLS: list = []


@dataclass(frozen=True)
class _Recording(ObjectValue):
    """An instance whose member calls are recorded, not applied: the call
    the store makes is what these laws read."""

    def call_member(
        self,
        name,
        member,
        arguments,
        *,
        owner,
        blame,
        ctx=None,
        keywords=(),
        required_frame=None,
    ):
        del owner, blame, ctx, keywords, required_frame
        _CALLS.append((self.class_name, name, member, tuple(arguments)))
        return ExitSet.completed(NoneValue())


def _store(receiver, value, site, after=None):
    return ReceiverFieldStoreSugar(
        receiver=_Read(receiver),
        value=_Read(value),
        attr="x",
        site=site,
        after=after,
    )


def _method(name, *parameters):
    return ObjectMethodValue(name=name, parameters=parameters, body=_Body())


# --- the plain store ------------------------------------------------------


def test_object_setattr_and_no_data_descriptor_is_the_plain_store(tmp_path):
    receiver = ObjectValue("R", (), allocation=FRAME_FRESH)
    assert receiver.field_store_route("x") == ("plain", None)
    assert receiver.field_store_runs_code("x") is False

    outcome = _store(receiver, TermValue(7), _site(tmp_path)).desugar()
    assert not outcome.halts()
    assert outcome.completed_value() == ReceiverFieldStoreValue(
        receiver, "x", TermValue(7)
    )

    # The plain store changes the object, and so whatever holds it; it
    # reaches nothing that merely shares with it, and no operand.
    method = field_store_method("x")
    assert _may_change(receiver, method, False, False) is True
    assert _may_change(receiver, method, False, True) is False
    operand = field_store_method("x", operand=True)
    held = fresh(ListValue, (TermValue(1),))
    assert _may_change(receiver, operand, False, True, held=held) is False


def test_a_class_field_that_is_no_data_descriptor_is_the_plain_store():
    receiver = ObjectValue(
        "R",
        (),
        class_fields=(ObjectField("x", TermValue(0)),),
        allocation=FRAME_FRESH,
    )
    assert receiver.field_store_route("x") == ("plain", None)


def test_a_property_with_no_selected_setter_refuses_and_runs_no_code():
    getter = ObjectMethodValue(
        name="x", parameters=("self",), body=_Body(), descriptor_kind="property"
    )
    receiver = ObjectValue("R", (), methods=(getter,), allocation=FRAME_FRESH)
    assert receiver.field_store_route("x") == ("refused", None)
    assert receiver.field_store_runs_code("x") is False


# --- a source __setattr__ / descriptor __set__: the call ------------------


def test_a_source_setattr_is_a_call_of_that_function_on_the_receiver(tmp_path):
    _CALLS.clear()
    setter = _method("__setattr__", "self", "name", "value")
    receiver = _Recording("R", (), methods=(setter,), allocation=FRAME_FRESH)
    assert receiver.field_store_route("x") == ("setattr", setter)
    assert receiver.field_store_runs_code("x") is True

    outcome = _store(receiver, TermValue(7), _site(tmp_path), AFTER).desugar()

    # The store is the call ``type(o).__setattr__(o, 'x', 7)``.
    assert _CALLS == [("R", "__setattr__", setter, (StringValue("x"), TermValue(7)))]
    assert not outcome.halts()
    record = outcome.completed_value()
    assert isinstance(record, _ReducedBlock)
    # No instance-field store is recorded: the field is not assumed stored.
    assert not any(
        isinstance(entry, ReceiverFieldStoreValue) for entry in record.entries
    )
    # The call stated nothing of the object: it is the same instance, its
    # contents no longer this frame's, bound where the post-state reads it.
    left = record.context.temporal.value_if_bound(AFTER)
    assert isinstance(left, _Recording)
    assert left.class_name == "R"
    assert contents_current(left) is False

    # Such a store reaches what a call reaches.
    method = field_store_method("x")
    assert _may_change(receiver, method, False, True) is True
    operand = field_store_method("x", operand=True)
    held = fresh(ListValue, (TermValue(1),))
    assert _may_change(receiver, operand, False, True, held=held) is True
    # An immutable operand keeps its value whatever the store runs.
    assert _may_change(receiver, operand, False, True, held=TermValue(1)) is False


def test_a_source_descriptor_set_is_a_call_of_that_function_on_the_descriptor(
    tmp_path,
):
    _CALLS.clear()
    setter = _method("__set__", "self", "instance", "value")
    descriptor = _Recording("D", (), methods=(setter,), allocation=FRAME_FRESH)
    receiver = _Recording(
        "R",
        (),
        class_fields=(ObjectField("x", descriptor),),
        allocation=FRAME_FRESH,
    )
    assert receiver.field_store_route("x") == ("descriptor", (descriptor, setter))
    assert receiver.field_store_runs_code("x") is True
    # Another name of the same class takes the plain store.
    assert receiver.field_store_route("y") == ("plain", None)

    outcome = _store(receiver, TermValue(7), _site(tmp_path), AFTER).desugar()

    # The store is the call ``type(d).__set__(d, o, 7)``.
    assert _CALLS == [("D", "__set__", setter, (receiver, TermValue(7)))]
    assert not outcome.halts()
    record = outcome.completed_value()
    assert isinstance(record, _ReducedBlock)
    assert not any(
        isinstance(entry, ReceiverFieldStoreValue) for entry in record.entries
    )


def test_a_setattr_that_is_no_plain_function_is_not_decided():
    setter = ObjectMethodValue(
        name="__setattr__",
        parameters=("name", "value"),
        body=_Body(),
        descriptor_kind="staticmethod",
    )
    receiver = ObjectValue("R", (), methods=(setter,), allocation=FRAME_FRESH)
    assert receiver.field_store_route("x") == ("undecided", None)


# --- an undecided class lookup: the unanswered call -----------------------


def test_an_undecided_lookup_is_the_unanswered_call_and_the_field_is_undecided(
    tmp_path,
):
    # A receiver with no class statement that holds ``__setattr__`` both as
    # a method and as a field: no order of its bindings is read.
    receiver = ObjectValue(
        "R",
        (),
        methods=(_method("__setattr__", "self", "name", "value"),),
        class_fields=(ObjectField("__setattr__", TermValue(1)),),
        allocation=FRAME_FRESH,
    )
    assert receiver.field_store_route("x") == ("undecided", None)
    assert receiver.field_store_runs_code("x") is True

    site = _site(tmp_path)
    outcome = _store(receiver, TermValue(7), site, AFTER).desugar()

    # Two faces: nothing is assumed of what ``type(o).__setattr__`` runs.
    (halt,) = outcome.halts()
    assert len(outcome.exits) > 1
    assert isinstance(halt.effect, UndeterminedRaiseEffect)
    assert halt.effect.producer_node_owner == "UnknownCallee:R.__setattr__"

    # The object after it is the same instance with its contents not
    # current: every field read of it is the undecided read.
    after = receiver.after_field_store_call(NoneValue(), site)(receiver)
    assert isinstance(after, ObjectValue)
    assert after.class_name == "R"
    assert contents_current(after) is False

    # It exposes what an unfollowed call exposes.
    assert _may_change(receiver, field_store_method("x"), False, True) is True


def test_a_receiver_that_is_no_source_instance_decides_by_its_own_value():
    method = field_store_method("x")
    operand = field_store_method("x", operand=True)
    # A formal with no actual, or an undecided value: its ``__setattr__``
    # may run any code.
    undecided = SymbolicValue(make_var("obj"))
    assert _may_change(undecided, method, False, True) is True
    held = fresh(ListValue, (TermValue(1),))
    assert _may_change(undecided, operand, False, True, held=held) is True
    # An operand no source types keeps its value, as at any unfollowed call.
    untyped = SymbolicValue(make_var("value"))
    assert _may_change(undecided, operand, False, True, held=untyped) is False
    # A builtin container's own floor answers the store: no code runs.
    container = fresh(ListValue, (TermValue(1),))
    assert _may_change(container, method, False, True) is False
    assert _may_change(container, operand, False, True, held=held) is False


# --- the rule's name, and the holder rule ---------------------------------


def test_the_field_store_rule_names_the_stored_attribute():
    assert field_store_rule(field_store_method("x")) == ("x", False)
    assert field_store_rule(field_store_method("value")) == ("value", False)
    assert field_store_rule(field_store_method("x", operand=True)) == ("x", True)
    # No method a source spells is read as a field store.
    assert field_store_rule("__setattr__") is None
    assert field_store_rule("append") is None
    assert field_store_rule("") is None


def test_the_holder_rule_does_not_assume_a_field_store_is_plain():
    assert "ordinary" not in inspect.signature(holder_states).parameters
