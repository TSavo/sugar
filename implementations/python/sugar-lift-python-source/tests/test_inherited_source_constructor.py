"""A source subclass uses its authenticated local base's constructor and protocol."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sugar_lift_py_tests.corpus_pin import pin_corpus
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.floor.return_value import ReturnValue
from sugar_lift_py_tests.floor.term_value import TermValue
from sugar_lift_py_tests.floor.universe_value import UniverseValue
from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
from sugar_lift_py_tests.outcome import Halted
from sugar_lift_py_tests.sugar.with_source_resource_sugar import WithReducedManagerSugar
from sugar_source_tree.nodes import FunctionDef, With
from sugar_source_tree.reporter import CollectingReporter
from sugar_lift_python_source.resolution_session import (
    SourceResolutionSession,
    clear_walk_sessions,
)


NAMED = (
    "class Resource:\n"
    "    def __init__(self, target):\n"
    "        self.target = target\n"
    "    def __enter__(self):\n"
    "        return self.target\n"
    "    def __exit__(self, *exc):\n"
    "        pass\n"
    "\n"
    "class Named(Resource):\n"
    "    tag = 'named'\n"
    "\n"
    "def f():\n"
    "    with Named(1):\n"
    "        return 1\n"
)

NAMED_RAISE = (
    "class Resource:\n"
    "    def __init__(self, target):\n"
    "        self.target = target\n"
    "    def __enter__(self):\n"
    "        return self.target\n"
    "    def __exit__(self, *exc):\n"
    "        pass\n"
    "\n"
    "class Named(Resource):\n"
    "    tag = 'named'\n"
    "\n"
    "def f():\n"
    "    with Named(1):\n"
    "        raise RuntimeError('boom')\n"
)

# Lying twin: a subclass that writes its own __init__ does not inherit the
# base's formals, so Named() with a leftover actual stays a binding gap.
OWN_INIT = (
    "class Resource:\n"
    "    def __init__(self, target):\n"
    "        self.target = target\n"
    "    def __enter__(self):\n"
    "        return self.target\n"
    "    def __exit__(self, *exc):\n"
    "        pass\n"
    "\n"
    "class Named(Resource):\n"
    "    def __init__(self):\n"
    "        self.target = 0\n"
    "\n"
    "def f():\n"
    "    with Named(1):\n"
    "        return 1\n"
)


def _corpus(tmp_path: Path, **files: str) -> Path:
    root = tmp_path / "c"
    root.mkdir()
    for name, source in files.items():
        (root / name).write_text(source, encoding="utf-8")
    (tmp_path / "c.identity.json").write_text(
        json.dumps({"distribution": "tiny-corpus", "version": "0.0.1"}), encoding="utf-8"
    )
    pin_corpus(root, distribution="tiny-corpus", version="0.0.1")
    return root


def _open(root: Path, name: str, *, session):
    clear_walk_sessions()
    return open_source_file_for_construction(
        root / name,
        root=root,
        reporter=CollectingReporter(),
        source_workspace_root=root,
        resolution_session=session,
    )


def _session():
    return SourceResolutionSession(enrolled_distributions=frozenset({"tiny-corpus"}))


def test_inherited_source_constructor_constructs(tmp_path) -> None:
    root = _corpus(tmp_path, **{"e.py": NAMED})
    source_file = _open(root, "e.py", session=_session())
    # The manager is the head's reduced value: the subclass instance, entered
    # through the base's own methods (#7757).
    sugar = next(n.sugar() for n in source_file.nodes() if isinstance(n, With))
    assert type(sugar) is WithReducedManagerSugar
    func = next(
        n for n in source_file.nodes() if isinstance(n, FunctionDef) and n.name == "f"
    )
    completed = func.sugar().desugar().completed_value()
    assert isinstance(completed, UniverseValue)
    returns = [
        statement
        for statement in completed.record.statements
        if isinstance(statement, ReturnValue)
    ]
    assert len(returns) == 1
    assert isinstance(returns[0].value, TermValue)
    assert returns[0].value.value == 1


def test_inherited_source_constructor_does_not_suppress_a_body_raise(tmp_path) -> None:
    root = _corpus(tmp_path, **{"e.py": NAMED_RAISE})
    source_file = _open(root, "e.py", session=_session())
    func = next(
        n for n in source_file.nodes() if isinstance(n, FunctionDef) and n.name == "f"
    )
    raised = func.sugar().desugar()
    halted = [face for face in raised.exits if isinstance(face, Halted)]
    assert len(halted) == 1
    assert isinstance(halted[0].effect, RaiseEffect)
    assert halted[0].effect.exception_name == "RuntimeError"


def test_own_initializer_does_not_inherit_the_base_formals(tmp_path) -> None:
    """``Named`` defines its own ``__init__()``, so ``Named(1)`` has an actual
    no formal consumes.  The open reads no body; the head's own construction
    says so by name (#7757)."""
    from sugar_lift_py_tests.source_call_frame import SourceCallBindingGap

    root = _corpus(tmp_path, **{"e.py": OWN_INIT})
    source_file = _open(root, "e.py", session=_session())
    func = next(
        n for n in source_file.nodes() if isinstance(n, FunctionDef) and n.name == "f"
    )
    with pytest.raises(SourceCallBindingGap, match="unconsumed call actual"):
        func.sugar().desugar()