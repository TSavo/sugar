"""``v.__class__ = C`` and ``del v.__class__`` on a builtin value halt with
``TypeError``; every other name with ``AttributeError``.

CPython finds ``object.__class__``, a data descriptor, on the type before it
tries any instance store; its setter (``object_set_class``) refuses an
immutable (builtin) type ("__class__ assignment only supported for mutable
types or ModuleType subclasses") and any delete ("can't delete __class__
attribute"), both ``TypeError``.  A builtin value has no ``__dict__``, so any
other name is ``AttributeError``.  Before, every builtin floor answered both
with ``AttributeError``: a wrong halt type (#8849's surfaced item).  One
reader decides it for every such floor
(``ground_exit.builtin_attribute_store_exit``).
"""

from __future__ import annotations

from frame_fresh import fresh

import pytest

from sugar_lift_py_tests.floor import (
    BytesValue,
    ListValue,
    NoneValue,
    StringValue,
    TermValue,
    TupleValue,
)
from sugar_lift_py_tests.outcome.exit_set import Halted
from sugar_lift_python_source.source_oracle import workspace_path_source
from sugar_source_tree.tree import SourceFile


def _sites(tmp_path):
    path = tmp_path / "builtin_class_store.py"
    path.write_text(
        "def f(value, replacement):\n"
        "    value.__class__ = replacement\n"
        "    del value.__class__\n"
    )
    body = next(
        SourceFile(workspace_path_source(str(path), root=str(tmp_path))).functions()
    ).body
    return body[0].fragment, body[1].fragment


def _raised(outcome):
    """The effect of the operation's one exit: a halt, never a completion."""
    (exit_,) = outcome.exits
    assert isinstance(exit_, Halted)
    return exit_.effect


_RECEIVERS = {
    "list": (lambda: fresh(ListValue, (TermValue(1),)), "ListValue"),
    "tuple": (lambda: TupleValue((TermValue(1),)), "TupleValue"),
    "str": (lambda: StringValue("abc"), "StringValue"),
    "bytes": (lambda: BytesValue(b"abc"), "BytesValue"),
    "none": (NoneValue, "NoneValue"),
    "int": (lambda: TermValue(1), "TermValue"),
}


@pytest.mark.parametrize("operation", ["setattr", "delattr"])
@pytest.mark.parametrize("receiver", sorted(_RECEIVERS))
def test_class_store_and_delete_on_a_builtin_value_is_the_certain_type_error(
    tmp_path, receiver, operation
):
    store_site, delete_site = _sites(tmp_path)
    make, floor = _RECEIVERS[receiver]
    value = make()
    if operation == "setattr":
        site = store_site
        outcome = value.setattr("__class__", TermValue(7), site, None)
    else:
        site = delete_site
        outcome = value.delattr("__class__", site, None)
    effect = _raised(outcome)
    assert effect.exception_name == "TypeError"
    assert effect.producer_node_owner == f"{floor}.{operation}"
    assert effect.occurrence_id == f"{site.filename}:{site.line}:{site.col}"


@pytest.mark.parametrize("operation", ["setattr", "delattr"])
@pytest.mark.parametrize("receiver", sorted(_RECEIVERS))
def test_any_other_name_on_a_builtin_value_stays_attribute_error(
    tmp_path, receiver, operation
):
    store_site, delete_site = _sites(tmp_path)
    make, floor = _RECEIVERS[receiver]
    value = make()
    if operation == "setattr":
        outcome = value.setattr("attr", TermValue(7), store_site, None)
    else:
        outcome = value.delattr("attr", delete_site, None)
    effect = _raised(outcome)
    assert effect.exception_name == "AttributeError"
    assert effect.producer_node_owner == f"{floor}.{operation}"
