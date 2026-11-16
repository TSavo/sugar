"""The one field store on a source instance is decided at prove (#7757 H1b).

``o.f = v`` is ``type(o).__setattr__(o, 'f', v)``.  The lift no longer walks
the class to decide what that runs (``field_store_route`` is deleted).  It
states two faces of one partition (``ObjectValue.plain_store_faces``):

- under ``python:plain_store(<class>, "f")`` (``ObjectValue.
  plain_store_guard``, over the instance's class term), the plain store:
  the instance with the field stored (``ReceiverFieldStoreValue``);
- under its complement, the dispatched ``type(o).__setattr__`` call
  (``ObjectValue.field_store_call``), whose member and halts prove's one
  walk of the order decides.

Where no class term is decided (no workspace root, no class statement, an
instance that is not current), the store is the call alone: the unanswered
call where no class is named.  What the instance shares is exposed at every
store (``_may_change`` under ``field_store_method``): the lift never decides
the store runs no code.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from pathlib import Path

from frame_fresh import FRAME_FRESH, fresh

from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1
from sugar_lift_py_tests.effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import (
    ListValue,
    NoneValue,
    ObjectValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.floor.class_definition_value import ClassDefinitionValue
from sugar_lift_py_tests.floor.object_identity import contents_current
from sugar_lift_py_tests.floor.receiver_field_store_value import (
    ReceiverFieldStoreValue,
)
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.outcome import Completed, ExitSet
from sugar_lift_py_tests.receiver_dispatch import PLAIN_STORE
from sugar_lift_py_tests.sugar.builtin_container_call_sugar import _may_change
from sugar_lift_py_tests.sugar.receiver_field_store_sugar import (
    ReceiverFieldStoreSugar,
)
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_source_tree.container_mutation import (
    field_store_method,
    field_store_rule,
    holder_states,
)
from sugar_source_tree.nodes import ClassDef

AFTER = "evaluation:store/.x="

_SOURCE = (
    "class Widget:\n"
    "    pass\n"
    "\n"
    "\n"
    "def f(obj, value):\n"
    "    obj.x = value\n"
)


def _setup(tmp_path: Path):
    """``Widget``'s class value under a workspace root (its class names a
    join symbol) and the fragment of ``f``'s store."""
    from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction

    path = tmp_path / "field_store.py"
    path.write_text(_SOURCE)
    tree = open_source_file_for_construction(path, root=tmp_path)
    statement = next(
        node for node in tree.root.body if isinstance(node, ClassDef)
    )
    span = statement.binding_target.line_col_span()
    value = ClassDefinitionValue(
        class_name=statement.name,
        class_definition_cid=statement.fragment.seal().cid,
        methods=(),
        initializer=None,
        binding_target_occurrence=SourceFragmentCoordinateV1(
            statement.unit.source_cid,
            span.start_line,
            span.start_col,
            span.end_line,
            span.end_col,
        ),
        class_definition=statement,
    )
    function = next(tree.functions())
    return value, function.body[0].fragment


@dataclass(frozen=True)
class _Read(Sugar):
    value: object

    @classmethod
    def witnesses(cls):
        raise AssertionError("test helper has no witness")

    def desugar(self, ctx=None):
        del ctx
        return ExitSet.completed(self.value)


def _store(receiver, value, site, after=None):
    return ReceiverFieldStoreSugar(
        receiver=_Read(receiver),
        value=_Read(value),
        attr="x",
        site=site,
        after=after,
    )


def _mentions(formula, name: str) -> bool:
    return name in repr(formula)


# --- a class term: the plain store under prove's guard, the call else -----


def test_a_store_on_an_instance_of_a_named_class_is_two_faced_on_prove_s_guard(
    tmp_path,
):
    value, site = _setup(tmp_path)
    receiver = ObjectValue(
        value.class_name,
        (),
        identity="receiver",
        defining_class=value,
        allocation=FRAME_FRESH,
    )
    guard = receiver.plain_store_guard("x")
    assert guard is not None and _mentions(guard, PLAIN_STORE)
    # A dunder name is never a plain store: no namespace row states one.
    assert receiver.plain_store_guard("__class__") is None

    outcome = _store(receiver, TermValue(7), site, AFTER).desugar()

    completed = [arm for arm in outcome.exits if isinstance(arm, Completed)]
    stored = [
        arm for arm in completed if isinstance(arm.value, ReceiverFieldStoreValue)
    ]
    # The plain store is recorded only under the guard prove decides.
    assert len(stored) == 1, outcome
    assert stored[0].value == ReceiverFieldStoreValue(receiver, "x", TermValue(7))
    assert _mentions(stored[0].guard, PLAIN_STORE)
    # Under the complement, the dispatched call: another completed face,
    # and its halt face kept.
    assert len(completed) > 1, outcome
    assert outcome.halts(), outcome
    for halt in outcome.halts():
        assert getattr(halt.effect, "exception_name", None) != "AttributeError"


# --- no class term: the call alone ----------------------------------------


def test_a_store_with_no_class_named_is_the_unanswered_call(tmp_path):
    _value, site = _setup(tmp_path)
    receiver = ObjectValue("R", (), allocation=FRAME_FRESH)
    assert receiver.plain_store_guard("x") is None

    outcome = _store(receiver, TermValue(7), site, AFTER).desugar()

    # Two faces: nothing is assumed of what ``type(o).__setattr__`` runs.
    (halt,) = outcome.halts()
    assert len(outcome.exits) > 1
    assert isinstance(halt.effect, UndeterminedRaiseEffect)
    assert halt.effect.producer_node_owner == "UnknownCallee:R.__setattr__"
    # No instance-field store is recorded: the field is not assumed stored.
    for arm in outcome.exits:
        if isinstance(arm, Completed):
            assert not isinstance(arm.value, ReceiverFieldStoreValue), arm

    # The object after it is the same instance with its contents not
    # current: every field read of it is the undecided read.
    after = receiver.after_field_store_call(NoneValue(), site)(receiver)
    assert isinstance(after, ObjectValue)
    assert after.class_name == "R"
    assert contents_current(after) is False


def test_an_instance_that_is_not_current_names_no_guard(tmp_path):
    from sugar_lift_py_tests.floor.object_identity import arrived

    value, site = _setup(tmp_path)
    receiver = ObjectValue(
        value.class_name,
        (),
        identity="receiver",
        defining_class=value,
        allocation=FRAME_FRESH,
    )
    assert receiver.plain_store_guard("x") is not None
    assert arrived(receiver, site).plain_store_guard("x") is None


# --- what a store exposes -------------------------------------------------


def test_a_store_on_a_source_instance_may_run_code():
    receiver = ObjectValue("R", (), allocation=FRAME_FRESH)
    method = field_store_method("x")
    # The object itself, and what it shares: the lift never decides the
    # store is the plain one.
    assert _may_change(receiver, method, False, False) is True
    assert _may_change(receiver, method, False, True) is True
    operand = field_store_method("x", operand=True)
    held = fresh(ListValue, (TermValue(1),))
    assert _may_change(receiver, operand, False, True, held=held) is True
    # An immutable operand keeps its value whatever the store runs.
    assert _may_change(receiver, operand, False, True, held=TermValue(1)) is False


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
