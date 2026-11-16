"""A read of a name nothing answers on an instance is the dispatched read,
decided at prove, never an ``AttributeError`` the lift decides (#7757 L3).

``ObjectValue.attribute`` on a name no recorded field and no class member
answers -- a field a delete removed included -- states the one dispatched
read (``ObjectValue._dispatched_call(read=True)``,
``call:dispatch:.<name>(<instance>, py.class("0", python:instance(<class>,
<field>...)))``), both faces kept.  Whether it raises ``AttributeError`` --
the order ends in ``object``, no class of it binds the name, the instance's
``__dict__`` may not hold it, no ``__getattr__`` or ``__getattribute__``
answers -- is decided once, by prove's one walk of the order
(``consistency::dispatch_walk``).  The lift's own walk of it
(``ObjectValue._absence_raises``) is deleted, and so is the ground
``AttributeError`` a read of a deleted field took without asking whether a
``__getattr__`` answers it.

Where the read names no class -- no workspace root, an instance that
arrived, no class statement -- it is the one undecided read.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from sugar_lift_py_tests.context_manager_resolution import (
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import CallSiteValue, ObjectField, TermValue
from sugar_lift_py_tests.floor.class_definition_value import ClassDefinitionValue
from sugar_lift_py_tests.floor.named_expression_value import peel_walrus_binds
from sugar_lift_py_tests.floor.object_value import ObjectValue
from sugar_lift_py_tests.outcome import Completed
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Attribute, ClassDef
from sugar_source_tree.tree import SourceFile

from frame_fresh import FRAME_FRESH

_READ = "\ndef read(o):\n    return o.missing\n"


def _setup(source: str, tmp_path=None):
    """``source``'s ``Widget`` class value and the fragment of its one
    attribute read (``o.missing``); under a workspace root (``tmp_path``)
    the class names its join symbol, so a read on its instance names its
    class."""
    source = source + _READ
    if tmp_path is None:
        tree = SourceFile(
            (source, "absence_rule.py", blake3_512_of(source.encode())),
            construction_context=TreeConstructionContextV1.for_test_without_workspace(),
        )
    else:
        from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction

        path = tmp_path / "absence_rule.py"
        path.write_text(source)
        tree = open_source_file_for_construction(path, root=tmp_path)
    classes = {
        node.name: node for node in tree.root.body if isinstance(node, ClassDef)
    }
    statement = classes["Widget"]
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
    (site,) = (node.fragment for node in tree.nodes() if isinstance(node, Attribute))
    return value, site


def _fresh(class_value, fields=()) -> ObjectValue:
    return ObjectValue(
        class_value.class_name,
        tuple(fields),
        identity="receiver",
        defining_class=class_value,
        allocation=FRAME_FRESH,
    )


def _no_lift_attribute_error(outcome) -> None:
    """No arm of ``outcome`` is an ``AttributeError`` the lift named."""
    assert not [
        halt
        for halt in outcome.halts()
        if getattr(halt.effect, "exception_name", None) == "AttributeError"
    ], outcome


def _dispatched_read(outcome, name: str = "missing") -> CallSiteValue:
    """The dispatched read of ``name``: it completes with the read's
    coordinate (``dispatch:.<name>``) and keeps its halting face; nothing
    here decides that it raises."""
    _no_lift_attribute_error(outcome)
    (done,) = [arm for arm in outcome.exits if isinstance(arm, Completed)]
    assert outcome.halts(), outcome
    _binds, call = peel_walrus_binds(done.value)
    assert isinstance(call, CallSiteValue), type(call)
    assert call.target_name == f"dispatch:.{name}", call.target_name
    return call


def _undecided(outcome) -> None:
    _no_lift_attribute_error(outcome)
    (halt,) = outcome.halts()
    assert isinstance(halt.effect, UndeterminedRaiseEffect)
    assert halt.effect.producer_node_owner == "ObjectValue.attribute"
    assert outcome.owed_items()


# --- a class this read names: the dispatched read, decided at prove -------------


@pytest.mark.parametrize(
    "source",
    [
        # Python raises ``AttributeError`` for these: prove's walk decides it.
        "class Widget:\n    pass\n",
        "class Widget(object):\n    def m(self):\n        return 1\n",
        "class Base:\n    pass\n\nclass Widget(Base):\n    pass\n",
        # A hook answers instead: prove's walk leaves it owed.
        "class Widget:\n    def __getattr__(self, name):\n        return 1\n",
        "class Base:\n    def __getattribute__(self, name):\n        return 1\n"
        "\nclass Widget(Base):\n    pass\n",
    ],
)
def test_a_fresh_instance_lacking_the_name_is_the_dispatched_read(
    source, tmp_path
) -> None:
    value, site = _setup(source, tmp_path)
    receiver = _fresh(value, (ObjectField("other", TermValue(1)),))

    _dispatched_read(receiver.attribute("missing", site, None))


def test_a_deleted_field_is_the_dispatched_read_naming_no_such_field(
    tmp_path,
) -> None:
    # ``del o.missing`` leaves the ``__dict__`` without it; a ``__getattr__``
    # may still answer the read.  The read states the instance's fields
    # without it, and prove's walk decides.
    value, site = _setup(
        "class Widget:\n    def __getattr__(self, name):\n        return 1\n",
        tmp_path,
    )
    receiver = _fresh(value, (ObjectField("missing", TermValue(4)),))
    after = receiver.delattr("missing", site, None).completed_value()
    assert "missing" in after.deleted_instance_fields

    from sugar_lift_py_tests.receiver_dispatch import class_value, instance_term

    _dispatched_read(after.attribute("missing", site, None))
    symbol = value.class_definition.bridge_source_symbol()
    assert symbol is not None
    assert class_value(after) == instance_term(symbol)


@pytest.mark.parametrize(
    "source",
    [
        # ``object``'s ``__delattr__``: whether the delete raises is not the
        # lift's to decide (a class field's ``__delete__`` may answer it).
        "class Widget:\n    pass\n",
        # A source ``__delattr__`` answers it, and may swallow it.
        "class Widget:\n    def __delattr__(self, name):\n        pass\n",
    ],
)
def test_deleting_a_name_no_field_holds_names_no_attribute_error(
    source, tmp_path
) -> None:
    value, site = _setup(source, tmp_path)
    receiver = _fresh(value, (ObjectField("other", TermValue(1)),))

    outcome = receiver.delattr("missing", site, None)

    _no_lift_attribute_error(outcome)
    assert outcome.halts(), outcome
    assert [arm for arm in outcome.exits if isinstance(arm, Completed)], outcome


def test_a_source_delattr_answers_the_delete_of_a_held_field(tmp_path) -> None:
    # ``del o.other`` is ``Widget.__delattr__(o, "other")``: the field is
    # never removed here, and the object after the call is not read as it
    # was.
    value, site = _setup(
        "class Widget:\n    def __delattr__(self, name):\n        pass\n",
        tmp_path,
    )
    receiver = _fresh(value, (ObjectField("other", TermValue(1)),))

    outcome = receiver.delattr("other", site, None)

    _no_lift_attribute_error(outcome)
    assert outcome.halts(), outcome
    for arm in outcome.exits:
        if isinstance(arm, Completed):
            _binds, after = peel_walrus_binds(arm.value)
            assert "other" not in getattr(after, "deleted_instance_fields", ())


def test_a_recorded_field_still_answers(tmp_path) -> None:
    value, site = _setup("class Widget:\n    pass\n", tmp_path)
    receiver = _fresh(value, (ObjectField("missing", TermValue(4)),))

    assert receiver.attribute("missing", site, None).completed_value() == TermValue(4)


# --- no class named: the undecided read ------------------------------------------


def test_no_workspace_root_is_the_undecided_read() -> None:
    value, site = _setup("class Widget:\n    pass\n")

    _undecided(_fresh(value).attribute("missing", site, None))


def test_an_instance_that_arrived_is_the_undecided_read(tmp_path) -> None:
    value, site = _setup("class Widget:\n    pass\n", tmp_path)
    receiver = ObjectValue(
        "Widget",
        (),
        identity="receiver",
        defining_class=value,
        allocation=None,
        arrival="arrived-receiver",
    )

    _undecided(receiver.attribute("missing", site, None))


def test_no_class_statement_is_the_undecided_read(tmp_path) -> None:
    _value, site = _setup("class Widget:\n    pass\n", tmp_path)
    receiver = ObjectValue("Widget", (), identity="receiver", allocation=FRAME_FRESH)

    _undecided(receiver.attribute("missing", site, None))


def test_a_deleted_field_with_no_class_statement_is_the_undecided_read(
    tmp_path,
) -> None:
    _value, site = _setup("class Widget:\n    pass\n", tmp_path)
    receiver = ObjectValue(
        "Widget",
        (ObjectField("missing", TermValue(4)),),
        identity="receiver",
        allocation=FRAME_FRESH,
    )
    after = replace(receiver, fields=(), deleted_instance_fields=("missing",))

    _undecided(after.attribute("missing", site, None))
