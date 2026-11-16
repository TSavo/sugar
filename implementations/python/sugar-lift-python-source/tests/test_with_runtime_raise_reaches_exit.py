"""A Python exception raised by an operation in a With body reaches __exit__.

CPython hands every exception raised in the body to ``__exit__(type, value,
tb)``, and a true result suppresses it (Python reference 8.5). An operation that
raises a decided exception (``1/0``, ``{}[k]``) is a ``RaiseEffect`` carrying
its class, so each With path feeds it to exit exactly like ``raise``.

An operation over an operand nothing typed (``a, b = x``) may complete or
raise something no one names: the one undetermined raise
(``UndeterminedRaiseEffect``).  It is never given a class.

The manager's ``__exit__`` is its call, never its body read at lift (#7757
step 6, #8744): a same-file class's exit is its dispatched edge, an imported
manager's the undecided manager's.  Whether it suppresses is decided where the
exit is, so the body's raise is kept beside the face where it was suppressed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.outcome import Completed, Halted
from sugar_lift_py_tests.sugar.with_source_resource_sugar import WithReducedManagerSugar
from sugar_source_tree.nodes import FunctionDef, With

from test_contextlib_suppress_source_exit_faces import _corpus, _open

_MANAGERS = (
    "class Swallows:\n"
    "    def __enter__(self):\n"
    "        return self\n"
    "    def __exit__(self, t, v, tb):\n"
    "        return True\n"
    "class NeverSuppresses:\n"
    "    def __enter__(self):\n"
    "        return self\n"
    "    def __exit__(self, t, v, tb):\n"
    "        return None\n"
)


def _with(tmp_path: Path, manager: str, body: str):
    source = _MANAGERS + f"def f():\n    with {manager}():\n        {body}\n    return 1\n"
    source_file = _open(_corpus(tmp_path, source))
    with_node = next(n for n in source_file.nodes() if isinstance(n, With))
    assert type(with_node.sugar()) is WithReducedManagerSugar
    func = next(
        n for n in source_file.nodes() if isinstance(n, FunctionDef) and n.name == "f"
    )
    return func.sugar().desugar()


def _raised(exits):
    return sorted(
        face.effect.exception_name
        for face in exits.exits
        if isinstance(face, Halted) and isinstance(face.effect, RaiseEffect)
    )


def _halts(exits):
    return [face for face in exits.exits if isinstance(face, Halted)]


@pytest.mark.parametrize(
    ("body", "name"),
    [
        ("1/0", "ZeroDivisionError"),
        ("{}['k']", "KeyError"),
        ("[][3]", "IndexError"),
        ("1 % 0", "ZeroDivisionError"),
    ],
)
def test_false_exit_reraises_the_runtime_raise(tmp_path, body, name):
    exits = _with(tmp_path, "NeverSuppresses", body)
    assert _raised(exits) == [name]


def _returns(exits):
    """Values a completed function face returns (statements after the With)."""
    from sugar_lift_py_tests.floor import ReturnValue

    return [
        statement.value
        for face in exits.exits
        if isinstance(face, Completed)
        for statement in face.value.record.statements
        if isinstance(statement, ReturnValue)
    ]


def _function(tmp_path: Path, manager: str, body: str, params: str = ""):
    source = (
        "import contextlib, decimal\n"
        + _MANAGERS
        + f"def f({params}):\n    with {manager}:\n        {body}\n    return 7\n"
    )
    source_file = _open(_corpus(tmp_path, source))
    func = next(
        n for n in source_file.nodes() if isinstance(n, FunctionDef) and n.name == "f"
    )
    return func.sugar().desugar()


@pytest.mark.parametrize(
    "manager",
    [
        "Swallows()",
        "contextlib.suppress(ZeroDivisionError)",
        "decimal.localcontext()",
    ],
)
@pytest.mark.parametrize("body", ["1/0", "raise ZeroDivisionError()"])
def test_a_suppressed_raise_continues_after_the_with(tmp_path, manager, body):
    """After suppression "execution continues with the statement following the
    with statement" (Python reference 8.5), whatever produced the exception."""
    from sugar_lift_py_tests.floor import TermValue

    assert TermValue(7) in _returns(_function(tmp_path, manager, body))


def test_an_undecided_manager_keeps_an_opaque_unpack_undetermined(tmp_path):
    """An unpack of an operand nothing typed may raise something no one
    names: its halt leaves the undecided manager's ``with`` as the one
    undetermined raise, never dropped and never given a class."""
    exits = _function(tmp_path, "decimal.localcontext()", "a, b = x", params="x")
    unpacks = [
        face
        for face in _halts(exits)
        if isinstance(face.effect, UndeterminedRaiseEffect)
        and str(face.effect.producer_node_owner).endswith(".unpack")
    ]
    assert unpacks
    assert _raised(exits) == []
