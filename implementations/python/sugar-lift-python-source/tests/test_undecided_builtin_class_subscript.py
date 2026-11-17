"""An item read on a builtin callable floor is the one undecided read (#7757).

The pandas 3.0.3 / numpy 2.5.1 lane (main 13e3413ad) refused 153 functions
by the owner ``subscript`` because ``dict`` (``BuiltinDictClassValue``) and
``tuple`` / ``set`` / ``type`` / ``len`` (``BuiltinSemanticCallable``) had no
subscript floor: ``ResType: TypeAlias = dict[int, Any]``,
``LONG_VERSION_PY: dict[str, str] = {}``, ``cast(tuple[int, int], x)``,
``np.ndarray[tuple[Any, ...], np.dtype[np.float64]]``.  A module whose
prelude refused took every function of the module with it.

``type(<builtin>)`` binds no ``__getitem__``; Python then looks up the
builtin's own ``__class_getitem__`` (absent on some builtins) and builds a
generic alias that reads attributes of every non-class argument.  Nothing
here decides either, so the read completes only under
``python:subscript_op.completes`` and raises something undetermined under
the complement, owed either way.  The truthful twin pins those two faces; the
lying twin pins that the read never completes with its halt dropped and
names no exception class.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.outcome import Completed, Halted
from sugar_source_tree.nodes import FunctionDef

from test_contextlib_suppress_source_exit_faces import _corpus, _open

_SOURCE = (
    "def dict_alias():\n"
    "    return dict[str, int]\n"
    "def tuple_alias():\n"
    "    return tuple[int, ...]\n"
    "def set_alias(t):\n"
    "    return set[t]\n"
)

_ALIASES = pytest.mark.parametrize(
    "function", ["dict_alias", "tuple_alias", "set_alias"]
)

_OWNER = "BuiltinSemanticCallable.subscript"
_COMPLETES = "python:subscript_op.completes"


def _exits(tmp_path: Path, name: str):
    source_file = _open(_corpus(tmp_path, _SOURCE))
    function = next(
        node
        for node in source_file.nodes()
        if isinstance(node, FunctionDef) and node.name == name
    )
    return function.sugar().desugar()


@_ALIASES
def test_the_alias_completes_under_its_atom_and_keeps_its_halt(
    tmp_path, function
) -> None:
    exits = _exits(tmp_path, function)
    halts = [
        face
        for face in exits.exits
        if isinstance(face, Halted)
        and isinstance(face.effect, UndeterminedRaiseEffect)
        and face.effect.producer_node_owner == _OWNER
    ]
    assert len(halts) == 1, [type(face).__name__ for face in exits.exits]
    completions = [face for face in exits.exits if isinstance(face, Completed)]
    assert len(completions) == 1
    assert _COMPLETES in str(completions[0].guard)
    assert _COMPLETES in str(halts[0].guard)


@_ALIASES
def test_the_alias_never_completes_with_its_halt_dropped(tmp_path, function) -> None:
    exits = _exits(tmp_path, function)
    # A sole unguarded completion would be the alias answered as if
    # ``__class_getitem__`` could not raise: the lie.
    assert exits.completed_value() is None
    assert not {
        getattr(face.effect, "exception_name", None)
        for face in exits.exits
        if isinstance(face, Halted)
    } & {"TypeError", "KeyError", "IndexError"}
