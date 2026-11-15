"""A read of a name nothing answers on an instance is decided by Python's
absence rule, never a panic (#7757).

``ObjectValue.attribute`` on a name no recorded field, delete, helper
deferral or class member answers raises ``AttributeError`` -- a halt at the
read's fragment, the builtin by binding -- when the instance is current (the
one currency rule), every class of its MRO is a source class or ``object``,
the one class-namespace lookup decides no class binds the name, none binds
``__getattr__`` and ``__getattribute__`` is ``object``'s.  Every other
receiver -- a builtin base other than ``object``, either hook, an instance
that arrived, no class statement, a name ``object`` holds -- is the one
undecided member.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.context_manager_resolution import (
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import ObjectField, TermValue
from sugar_lift_py_tests.floor.class_definition_value import ClassDefinitionValue
from sugar_lift_py_tests.floor.object_value import ObjectValue
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Attribute, ClassDef
from sugar_source_tree.tree import SourceFile

from frame_fresh import FRAME_FRESH

_READ = "\ndef read(o):\n    return o.missing\n"


def _setup(source: str):
    """``source``'s ``Widget`` class value and the fragment of its one
    attribute read (``o.missing``)."""
    source = source + _READ
    tree = SourceFile(
        (source, "absence_rule.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
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


def _attribute_error(outcome) -> None:
    assert outcome.completed_value() is None, outcome
    assert len(outcome.exits) == 1, outcome
    (halt,) = outcome.halts()
    assert not isinstance(halt.effect, UndeterminedRaiseEffect)
    assert halt.effect.exception_name == "AttributeError"
    assert halt.effect.producer_node_owner == "ObjectValue.attribute"


def _undecided(outcome) -> None:
    (halt,) = outcome.halts()
    assert isinstance(halt.effect, UndeterminedRaiseEffect)
    assert halt.effect.producer_node_owner == "ObjectValue.attribute"
    assert outcome.owed_items()


# --- Python decides: AttributeError ---------------------------------------------


@pytest.mark.parametrize(
    "source",
    [
        "class Widget:\n    pass\n",
        "class Widget(object):\n    def m(self):\n        return 1\n",
        "class Base:\n    pass\n\nclass Widget(Base):\n    pass\n",
    ],
)
def test_a_fresh_source_instance_lacking_the_name_raises_attribute_error(
    source,
) -> None:
    value, site = _setup(source)
    receiver = _fresh(value, (ObjectField("other", TermValue(1)),))

    _attribute_error(receiver.attribute("missing", site, None))


def test_a_recorded_field_still_answers() -> None:
    value, site = _setup("class Widget:\n    pass\n")
    receiver = _fresh(value, (ObjectField("missing", TermValue(4)),))

    assert receiver.attribute("missing", site, None).completed_value() == TermValue(4)


# --- Python does not decide here: the undecided member --------------------------


@pytest.mark.parametrize(
    "source",
    [
        # A builtin base other than ``object``.
        "class Widget(dict):\n    pass\n",
        "class Base(ValueError):\n    pass\n\nclass Widget(Base):\n    pass\n",
        # ``__getattr__`` answers a name the instance and its class lack.
        "class Widget:\n    def __getattr__(self, name):\n        return 1\n",
        "class Base:\n    def __getattr__(self, name):\n        return 1\n"
        "\nclass Widget(Base):\n    pass\n",
        # A source ``__getattribute__`` answers every read.
        "class Base:\n    def __getattribute__(self, name):\n        return 1\n"
        "\nclass Widget(Base):\n    pass\n",
    ],
)
def test_a_builtin_base_or_a_hook_is_the_undecided_member(source) -> None:
    value, site = _setup(source)

    _undecided(_fresh(value).attribute("missing", site, None))


def test_an_instance_that_arrived_is_the_undecided_member() -> None:
    value, site = _setup("class Widget:\n    pass\n")
    receiver = ObjectValue(
        "Widget",
        (),
        identity="receiver",
        defining_class=value,
        allocation=None,
        arrival="arrived-receiver",
    )

    _undecided(receiver.attribute("missing", site, None))


def test_no_class_statement_is_the_undecided_member() -> None:
    _value, site = _setup("class Widget:\n    pass\n")
    receiver = ObjectValue("Widget", (), identity="receiver", allocation=FRAME_FRESH)

    _undecided(receiver.attribute("missing", site, None))


def test_a_name_object_holds_is_never_attribute_error() -> None:
    value, site = _setup("class Widget:\n    pass\n")

    # ``object`` binds ``__init__``: the read is a member, never absent.
    _undecided(_fresh(value).attribute("__init__", site, None))
