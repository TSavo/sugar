"""A Python exception raised by an operation in a With body reaches __exit__.

CPython hands every exception raised in the body to ``__exit__(type, value,
tb)``, and a true result suppresses it (Python reference 8.5). An operation that
raises a decided exception (``1/0``, ``{}[k]``) is a ``RaiseEffect`` carrying
its class, so each With path feeds it to exit exactly like ``raise``.

A ``RuntimeEffect`` is a different thing: the lift's boundary at an operation
whose dispatch exists only at runtime, which may complete or raise. It is not
an exception occurrence, so no With path hands it to exit as one; it stays the
With's residue instead of becoming an invented raise or an invented suppression.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.effect import RaiseEffect, RuntimeEffect
from sugar_lift_py_tests.outcome import Completed, Halted
from sugar_lift_py_tests.sugar.with_source_resource_sugar import WithSourceResourceSugar
from sugar_source_tree.nodes import FunctionDef, With

from test_contextlib_suppress_source_exit_faces import _corpus, _open, _suppress

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
    assert type(with_node.sugar()) is WithSourceResourceSugar
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


@pytest.mark.parametrize("body", ["1/0", "{}['k']", "[][3]", "1 % 0"])
def test_true_exit_suppresses_a_runtime_raise(tmp_path, body):
    exits = _with(tmp_path, "Swallows", body)
    assert _halts(exits) == []
    assert any(isinstance(face, Completed) for face in exits.exits)


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


def test_suppress_consumes_a_runtime_raise_of_its_class(tmp_path):
    exits = _suppress(tmp_path, "ZeroDivisionError", "1/0")
    assert _halts(exits) == []
    assert any(isinstance(face, Completed) for face in exits.exits)


def test_suppress_consumes_a_runtime_raise_by_its_base(tmp_path):
    exits = _suppress(tmp_path, "LookupError", "{}['k']")
    assert _halts(exits) == []


def test_suppress_reraises_an_unrelated_runtime_raise(tmp_path):
    exits = _suppress(tmp_path, "ZeroDivisionError", "{}['k']")
    assert _raised(exits) == ["KeyError"]


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


def test_a_reraised_runtime_raise_skips_the_tail(tmp_path):
    exits = _function(tmp_path, "NeverSuppresses()", "1/0")
    assert _returns(exits) == []
    assert _raised(exits) == ["ZeroDivisionError"]


def test_a_cited_manager_keeps_a_runtime_boundary_as_residue(tmp_path):
    """An unpack of an opaque operand is undecided, not a raise: no split."""
    exits = _function(tmp_path, "decimal.localcontext()", "a, b = x", params="x")
    residues = [
        face for face in _halts(exits) if isinstance(face.effect, RuntimeEffect)
    ]
    assert residues
    assert not [face for face in residues if isinstance(face.effect, RaiseEffect)]
    # The boundary is neither suppressed into the tail nor re-raised as a class.
    assert _returns(exits) == []
    assert _raised(exits) == []
