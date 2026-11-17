"""A member or item read nothing here decides is the one undecided read (#7757).

The pandas 3.0.3 / numpy 2.5.1 lane (main 13e3413ad) refused whole functions
by the owner ``attribute`` / ``subscript`` for these receivers:

- a builtin class (``str.isalnum``, ``ValueError.args``): ``ClassValue``;
- a builtin callable floor (``set.union``, ``dict.__init__``):
  ``BuiltinSemanticCallable`` and ``BuiltinDictClassValue``;
- a function a ``def`` built (``g.__name__``, ``f.__doc__``):
  ``LambdaCallable``;
- what an undecided manager's ``__enter__`` returned (``with open(p) as fh:
  fh.read()``, ``fh[0]``): the opaque value, now ``SymbolicValue`` itself
  rather than a second floor that answered only its truth.

Each read is ``type(x).__getattribute__`` (or ``__getitem__``) over a
namespace nothing here reads, so it completes only under its own
``completes`` atom and raises something undetermined under the complement,
owed either way.  The truthful twin pins those two faces; the lying twin pins
that no read completes with its halt dropped and none names an exception
class it was never shown to raise.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.outcome import Completed, Halted
from sugar_source_tree.nodes import FunctionDef

from test_contextlib_suppress_source_exit_faces import _corpus, _open

_SOURCE = (
    "def builtin_class_member():\n"
    "    return str.upper\n"
    "def builtin_callable_member():\n"
    "    return set.union\n"
    "def dict_member():\n"
    "    return dict.__init__\n"
    "def function_member():\n"
    "    def g():\n"
    "        return 1\n"
    "    return g.__name__\n"
    "def entered_member(m):\n"
    "    with m as fh:\n"
    "        return fh.read\n"
    "def entered_item(m):\n"
    "    with m as fh:\n"
    "        return fh[0]\n"
)

# (function, the read's producer, its completes atom, what the atom names)
_READS = pytest.mark.parametrize(
    "function, owner, completes, named",
    [
        (
            "builtin_class_member",
            "ClassValue.attribute",
            "python:attribute_op.completes",
            "upper",
        ),
        (
            "builtin_callable_member",
            "BuiltinSemanticCallable.attribute",
            "python:attribute_op.completes",
            "union",
        ),
        (
            "dict_member",
            "BuiltinSemanticCallable.attribute",
            "python:attribute_op.completes",
            "__init__",
        ),
        (
            "function_member",
            "LambdaCallable.attribute",
            "python:attribute_op.completes",
            "__name__",
        ),
        (
            "entered_member",
            "SymbolicValue.attribute",
            "python:attribute_op.completes",
            "python:undecided_manager.slot_result",
        ),
        (
            "entered_item",
            "SymbolicValue.subscript",
            "python:subscript_op.completes",
            "python:undecided_manager.slot_result",
        ),
    ],
    ids=[
        "str.upper",
        "set.union",
        "dict.__init__",
        "g.__name__",
        "fh.read",
        "fh[0]",
    ],
)


def _exits(tmp_path: Path, name: str):
    source_file = _open(_corpus(tmp_path, _SOURCE))
    function = next(
        node
        for node in source_file.nodes()
        if isinstance(node, FunctionDef) and node.name == name
    )
    return function.sugar().desugar()


def _read_halts(exits, owner: str):
    return [
        face
        for face in exits.exits
        if isinstance(face, Halted)
        and isinstance(face.effect, UndeterminedRaiseEffect)
        and face.effect.producer_node_owner == owner
    ]


@_READS
def test_the_read_completes_under_its_atom_and_keeps_its_halt(
    tmp_path, function, owner, completes, named
) -> None:
    exits = _exits(tmp_path, function)
    halts = _read_halts(exits, owner)
    assert halts, [type(face).__name__ for face in exits.exits]
    assert all(completes in str(face.guard) for face in halts)
    completions = [face for face in exits.exits if isinstance(face, Completed)]
    assert completions
    assert all(completes in str(face.guard) for face in completions)
    assert all(named in str(face.guard) for face in completions)


@_READS
def test_no_read_completes_with_its_halt_dropped(
    tmp_path, function, owner, completes, named
) -> None:
    del owner, completes, named
    exits = _exits(tmp_path, function)
    # A sole unguarded completion would be the read answered as if it could
    # not raise: the lie.
    assert exits.completed_value() is None
    named_classes = {
        getattr(face.effect, "exception_name", None)
        for face in exits.exits
        if isinstance(face, Halted)
    }
    assert not named_classes & {"AttributeError", "KeyError", "IndexError"}
