"""A constructed instance reads an authenticated class-body field."""

from __future__ import annotations

import json
from pathlib import Path

from sugar_lift_py_tests.corpus_pin import pin_corpus
from sugar_lift_py_tests.floor.universe_value import UniverseValue
from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
from sugar_lift_py_tests.sugar.with_source_resource_sugar import WithReducedManagerSugar
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
    # The manager is the head's reduced value: a source class instance,
    # entered through its own ``__enter__`` (#7757).
    with_node = next(n for n in source_file.nodes() if isinstance(n, With))
    assert type(with_node.sugar()) is WithReducedManagerSugar
    func = next(
        n for n in source_file.nodes() if isinstance(n, FunctionDef) and n.name == "f"
    )
    completed = func.sugar().desugar().completed_value()
    assert isinstance(completed, UniverseValue)
    enter_facts = []
    for statement in completed.record.statements:
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
