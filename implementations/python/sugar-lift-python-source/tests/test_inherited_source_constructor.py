"""A source subclass uses its authenticated local base's constructor and protocol."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sugar_lift_py_tests.context_manager_resolution import (
    SourceDerivedContextManagerRefV1,
)
from sugar_lift_py_tests.corpus_pin import pin_corpus
from sugar_lift_py_tests.context_manager_contract import (
    NeverSuppressesDispositionV1,
    ProtocolResourceSemanticsV1,
    ReturnTruthinessDispositionV1,
)
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.floor.return_value import ReturnValue
from sugar_lift_py_tests.floor.term_value import TermValue
from sugar_lift_py_tests.floor.universe_value import UniverseValue
from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
from sugar_lift_py_tests.outcome import Complete, Halted
from sugar_lift_py_tests.sugar.with_source_resource_sugar import WithSourceResourceSugar
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


def _with_resolution(root: Path, name: str, *, session):
    source_file = _open(root, name, session=session)
    with_node = next(n for n in source_file.nodes() if isinstance(n, With))
    refs = source_file.root.unit.construction_context.source_derived_contract_refs
    line = with_node.line_col_span().start_line
    (site,) = [k for k in refs if k.start_line == line]
    return refs[site], source_file


def _session():
    return SourceResolutionSession(enrolled_distributions=frozenset({"tiny-corpus"}))


def test_inherited_source_constructor_constructs(tmp_path) -> None:
    root = _corpus(tmp_path, **{"e.py": NAMED})
    session = _session()
    ref, source_file = _with_resolution(root, "e.py", session=session)
    assert type(ref) is SourceDerivedContextManagerRefV1
    assert isinstance(ref.semantics, ProtocolResourceSemanticsV1)
    assert isinstance(
        ref.semantics.exit.disposition,
        (NeverSuppressesDispositionV1, ReturnTruthinessDispositionV1),
    )
    sugar = next(n.sugar() for n in source_file.nodes() if isinstance(n, With))
    assert type(sugar) is WithSourceResourceSugar
    func = next(
        n for n in source_file.nodes() if isinstance(n, FunctionDef) and n.name == "f"
    )
    completed = func.sugar().desugar()
    assert isinstance(completed, Complete)
    assert isinstance(completed.value, UniverseValue)
    returns = [
        statement
        for statement in completed.value.record.statements
        if isinstance(statement, ReturnValue)
    ]
    assert len(returns) == 1
    assert isinstance(returns[0].value, TermValue)
    assert returns[0].value.value == 1


def test_inherited_source_constructor_does_not_suppress_a_body_raise(tmp_path) -> None:
    root = _corpus(tmp_path, **{"e.py": NAMED_RAISE})
    session = _session()
    ref, source_file = _with_resolution(root, "e.py", session=session)
    assert type(ref) is SourceDerivedContextManagerRefV1
    assert isinstance(ref.semantics, ProtocolResourceSemanticsV1)
    assert isinstance(
        ref.semantics.exit.disposition,
        (NeverSuppressesDispositionV1, ReturnTruthinessDispositionV1),
    )
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
    no formal consumes. Populate says so by name, and the open raises it: the
    failure used to be caught inside the opener, and the file opened with the
    ``with`` left underived (#7795)."""
    from sugar_lift_py_tests.source_call_frame import SourceCallBindingGap

    root = _corpus(tmp_path, **{"e.py": OWN_INIT})
    # Every open populates (#7796): there is no unpopulated open to read the
    # constructor frame from first, so the open itself is the observation.
    with pytest.raises(SourceCallBindingGap, match="unconsumed call actual"):
        _open(root, "e.py", session=_session())