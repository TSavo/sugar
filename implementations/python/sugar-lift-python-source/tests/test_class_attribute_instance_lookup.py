"""A constructed instance reads an authenticated class-body field."""

from __future__ import annotations

import json
from pathlib import Path

from sugar_lift_py_tests.context_manager_contract import (
    NeverSuppressesDispositionV1,
    ProtocolResourceSemanticsV1,
    ReturnTruthinessDispositionV1,
)
from sugar_lift_py_tests.context_manager_resolution import (
    SourceDerivedContextManagerRefV1,
)
from sugar_lift_py_tests.corpus_pin import pin_corpus
from sugar_lift_py_tests.floor.universe_value import UniverseValue
from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.floor.return_value import ReturnValue
from sugar_lift_py_tests.floor.term_value import TermValue
from sugar_lift_py_tests.outcome import Complete, Completed, Halted
from sugar_lift_py_tests.sugar.with_source_resource_sugar import WithSourceResourceSugar
from sugar_source_tree.nodes import FunctionDef, With
from sugar_source_tree.reporter import CollectingReporter
from sugar_lift_python_source.resolution_session import (
    SourceResolutionSession,
    clear_walk_sessions,
)


RESOURCE = (
    "class Resource:\n"
    "    default = 1\n"
    "    def __enter__(self):\n"
    "        return self.default\n"
    "    def __exit__(self, *exc):\n"
    "        pass\n"
    "\n"
    "def f():\n"
    "    with Resource() as x:\n"
    "        return x\n"
)

NAMED_OVERRIDE = (
    "class Resource:\n"
    "    default = 1\n"
    "    def __enter__(self):\n"
    "        return self.default\n"
    "    def __exit__(self, *exc):\n"
    "        pass\n"
    "\n"
    "class Named(Resource):\n"
    "    default = 2\n"
    "\n"
    "def f():\n"
    "    with Named() as x:\n"
    "        return x\n"
)

NAMED_INHERITS = (
    "class Resource:\n"
    "    default = 1\n"
    "    def __enter__(self):\n"
    "        return self.default\n"
    "    def __exit__(self, *exc):\n"
    "        pass\n"
    "\n"
    "class Named(Resource):\n"
    "    tag = 'named'\n"
    "\n"
    "def f():\n"
    "    with Named() as x:\n"
    "        return x\n"
)

INSTANCE_SHADOWS = (
    "class Resource:\n"
    "    default = 1\n"
    "    def __init__(self):\n"
    "        self.default = 3\n"
    "    def __enter__(self):\n"
    "        return self.default\n"
    "    def __exit__(self, *exc):\n"
    "        pass\n"
    "\n"
    "def f():\n"
    "    with Resource() as x:\n"
    "        return x\n"
)

MISSING = (
    "class Resource:\n"
    "    default = 1\n"
    "    def __enter__(self):\n"
    "        return self.missing\n"
    "    def __exit__(self, *exc):\n"
    "        pass\n"
    "\n"
    "def f():\n"
    "    with Resource() as x:\n"
    "        return x\n"
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


def _assert_enter_returns(source_file, expected: int) -> None:
    refs = source_file.root.unit.construction_context.source_derived_contract_refs
    with_node = next(n for n in source_file.nodes() if isinstance(n, With))
    line = with_node.line_col_span().start_line
    (site,) = [k for k in refs if k.start_line == line]
    ref = refs[site]
    assert type(ref) is SourceDerivedContextManagerRefV1
    assert isinstance(ref.semantics, ProtocolResourceSemanticsV1)
    assert isinstance(
        ref.semantics.exit.disposition,
        (NeverSuppressesDispositionV1, ReturnTruthinessDispositionV1),
    )
    assert type(with_node.sugar()) is WithSourceResourceSugar
    func = next(
        n for n in source_file.nodes() if isinstance(n, FunctionDef) and n.name == "f"
    )
    completed = func.sugar().desugar()
    assert isinstance(completed, Complete)
    assert isinstance(completed.value, UniverseValue)
    enter_facts = []
    for statement in completed.value.record.statements:
        formula = getattr(statement, "formula", None)
        if getattr(formula, "name", None) != "=":
            continue
        left = formula.args[0]
        if getattr(left, "name", None) == "enter_result_value":
            enter_facts.append(formula.args[1])
    assert len(enter_facts) == 1
    assert enter_facts[0].value == expected


def test_instance_reads_its_own_class_field(tmp_path) -> None:
    root = _corpus(tmp_path, **{"e.py": RESOURCE})
    _assert_enter_returns(_open(root, "e.py", session=_session()), 1)


def test_subclass_class_field_overrides_the_base(tmp_path) -> None:
    root = _corpus(tmp_path, **{"e.py": NAMED_OVERRIDE})
    _assert_enter_returns(_open(root, "e.py", session=_session()), 2)


def test_instance_reads_an_inherited_class_field(tmp_path) -> None:
    root = _corpus(tmp_path, **{"e.py": NAMED_INHERITS})
    _assert_enter_returns(_open(root, "e.py", session=_session()), 1)


def test_instance_field_shadows_the_class_field(tmp_path) -> None:
    root = _corpus(tmp_path, **{"e.py": INSTANCE_SHADOWS})
    _assert_enter_returns(_open(root, "e.py", session=_session()), 3)


def test_missing_class_field_stays_a_gap(tmp_path) -> None:
    root = _corpus(tmp_path, **{"e.py": MISSING})
    source_file = _open(root, "e.py", session=_session())
    with_node = next(n for n in source_file.nodes() if isinstance(n, With))
    refs = source_file.root.unit.construction_context.source_derived_contract_refs
    line = with_node.line_col_span().start_line
    selected = [refs[k] for k in refs if k.start_line == line]
    assert not any(isinstance(ref, SourceDerivedContextManagerRefV1) for ref in selected)
    assert selected
    details = " ".join(getattr(ref, "detail", "") or "" for ref in selected)
    assert "ObjectValue.attribute:ObjectValue.missing" in details
    assert "AttributeError" not in details


REDIRECT_STDOUT = (
    "from contextlib import redirect_stdout\n"
    "from io import StringIO\n"
    "\n"
    "def f():\n"
    "    with redirect_stdout(StringIO()):\n"
    "        return 1\n"
)

REDIRECT_STDOUT_RAISE = (
    "from contextlib import redirect_stdout\n"
    "from io import StringIO\n"
    "\n"
    "def f():\n"
    "    with redirect_stdout(StringIO()):\n"
    "        raise RuntimeError('boom')\n"
)

REDIRECT_STDERR = (
    "from contextlib import redirect_stderr\n"
    "from io import StringIO\n"
    "\n"
    "def f():\n"
    "    with redirect_stderr(StringIO()):\n"
    "        return 1\n"
)


def _contextlib_session():
    return SourceResolutionSession(
        enrolled_distributions=frozenset({"tiny-corpus", "cpython-stdlib:contextlib"})
    )


def _assert_complete_return_one(source_file) -> None:
    refs = source_file.root.unit.construction_context.source_derived_contract_refs
    with_node = next(n for n in source_file.nodes() if isinstance(n, With))
    line = with_node.line_col_span().start_line
    (site,) = [k for k in refs if k.start_line == line]
    ref = refs[site]
    assert type(ref) is SourceDerivedContextManagerRefV1
    assert isinstance(ref.semantics, ProtocolResourceSemanticsV1)
    assert isinstance(
        ref.semantics.exit.disposition,
        (NeverSuppressesDispositionV1, ReturnTruthinessDispositionV1),
    )
    assert type(with_node.sugar()) is WithSourceResourceSugar
    func = next(
        n for n in source_file.nodes() if isinstance(n, FunctionDef) and n.name == "f"
    )
    # ``StringIO()`` is a call whose body the lift does not hold: it may
    # raise, and that halt is the ``with`` statement's own construction face.
    # ``__exit__``'s ``self._old_targets.pop()`` reads a list reached through
    # ``self``, whose contents at the exit (after ``__enter__``'s append) are
    # not testified there: the pop is two-faced, never total.
    exits = func.sugar().desugar()
    assert sorted(
        face.effect.producer_node_owner
        for face in exits.exits
        if isinstance(face, Halted)
    ) == ["BuiltinMethodCall:list.pop", "UnknownCallee:StringIO"]
    returns = [
        statement
        for face in exits.exits
        if isinstance(face, Completed)
        for statement in face.value.record.statements
        if isinstance(statement, ReturnValue)
    ]
    assert all(
        isinstance(face.value, UniverseValue)
        for face in exits.exits
        if isinstance(face, Completed)
    )
    assert len(returns) == 1
    assert isinstance(returns[0].value, TermValue)
    assert returns[0].value.value == 1


def test_redirect_stdout_constructs(tmp_path) -> None:
    root = _corpus(tmp_path, **{"e.py": REDIRECT_STDOUT})
    _assert_complete_return_one(_open(root, "e.py", session=_contextlib_session()))


def test_redirect_stdout_does_not_suppress_a_body_raise(tmp_path) -> None:
    root = _corpus(tmp_path, **{"e.py": REDIRECT_STDOUT_RAISE})
    source_file = _open(root, "e.py", session=_contextlib_session())
    refs = source_file.root.unit.construction_context.source_derived_contract_refs
    with_node = next(n for n in source_file.nodes() if isinstance(n, With))
    line = with_node.line_col_span().start_line
    (site,) = [k for k in refs if k.start_line == line]
    ref = refs[site]
    assert type(ref) is SourceDerivedContextManagerRefV1
    func = next(
        n for n in source_file.nodes() if isinstance(n, FunctionDef) and n.name == "f"
    )
    raised = func.sugar().desugar()
    halted = [
        face
        for face in raised.exits
        if isinstance(face, Halted)
        and face.effect.producer_node_owner
        not in ("UnknownCallee:StringIO", "BuiltinMethodCall:list.pop")
    ]
    assert len(halted) == 1
    assert isinstance(halted[0].effect, RaiseEffect)
    assert halted[0].effect.exception_name == "RuntimeError"


def test_redirect_stderr_constructs(tmp_path) -> None:
    root = _corpus(tmp_path, **{"e.py": REDIRECT_STDERR})
    _assert_complete_return_one(_open(root, "e.py", session=_contextlib_session()))
