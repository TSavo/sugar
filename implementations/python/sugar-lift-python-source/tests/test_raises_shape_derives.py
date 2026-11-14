"""An installed pytest.raises-shaped manager is an imported call, cited.

``raiselib`` is installed beside the corpus, not one of step 2's files. The
corpus file imports it, and the import does not enroll it: an imported call
is a coordinate plus an edge, answered by an imported proof, and its body is
never lifted (#7796). So the manager is cited, never derived from raiselib's
source.
"""

from __future__ import annotations

import csv
import importlib.metadata
import json
import sys
from pathlib import Path

import pytest

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.corpus_pin import pin_corpus
from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
from sugar_lift_python_source.resolution_session import clear_walk_sessions
from sugar_source_tree.reporter import CollectingReporter


_IMPL = (
    "import re\n"
    "class RaisesExc:\n"
    "    def __init__(self, expected, match=None):\n"
    "        self.expected = expected\n"
    "        self.match = match\n"
    "    def __enter__(self):\n"
    "        return self\n"
    "    def __exit__(self, exc_type, exc_value, tb):\n"
    "        if exc_type is None:\n"
    "            return False\n"
    "        if not isinstance(exc_value, self.expected):\n"
    "            return False\n"
    "        if self.match is not None:\n"
    "            return re.search(self.match, str(exc_value)) is not None\n"
    "        return True\n"
    "\n"
    "def raises(expected, match=None):\n"
    "    return RaisesExc(expected, match)\n"
)


# Spelled exactly like pytest's ``RaisesExc``: fields ``expected_exceptions``,
# ``match`` and ``check``, a ``matches`` method. The spelling earns nothing; the
# manager is known by the target its call binds to through the import table.
_PYTEST_SPELLED_IMPL = (
    "import re\n"
    "class RaisesExc:\n"
    "    def __init__(self, expected_exception, *, match=None, check=None):\n"
    "        self.expected_exceptions = (expected_exception,)\n"
    "        self.match = match\n"
    "        self.check = check\n"
    "    def matches(self, exception):\n"
    "        if not isinstance(exception, self.expected_exceptions):\n"
    "            return False\n"
    "        if self.match is not None:\n"
    "            return re.search(self.match, str(exception)) is not None\n"
    "        return True\n"
    "    def __enter__(self):\n"
    "        return self\n"
    "    def __exit__(self, exc_type, exc_val, exc_tb):\n"
    "        if exc_type is None:\n"
    "            raise AssertionError('DID NOT RAISE')\n"
    "        if not self.matches(exc_val):\n"
    "            return False\n"
    "        return True\n"
    "\n"
    "def raises(expected_exception, *, match=None, check=None):\n"
    "    return RaisesExc(expected_exception, match=match, check=check)\n"
)


def _install(root: Path, impl: str = _IMPL):
    pkg = root / "site" / "raiselib"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("from raiselib.impl import raises\n", encoding="utf-8")
    (pkg / "impl.py").write_text(impl, encoding="utf-8")
    meta = root / "site" / "raiselib-1.0.dist-info"
    meta.mkdir()
    (meta / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: raiselib\nVersion: 1.0\n", encoding="utf-8"
    )
    (meta / "top_level.txt").write_text("raiselib\n", encoding="utf-8")
    with (meta / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        w = csv.writer(stream)
        for item in (
            "raiselib/__init__.py",
            "raiselib/impl.py",
            "raiselib-1.0.dist-info/METADATA",
            "raiselib-1.0.dist-info/top_level.txt",
            "raiselib-1.0.dist-info/RECORD",
        ):
            w.writerow((item, "", ""))
    sys.path.insert(0, str(root / "site"))
    return importlib.metadata.Distribution.at(meta)


def _derive(tmp_path: Path, use: str, impl: str = _IMPL):
    # ``use.py`` imports raiselib; the import is an edge, not population.
    _install(tmp_path, impl)
    try:
        corpus = tmp_path / "c"
        corpus.mkdir()
        (corpus / "use.py").write_text(use, encoding="utf-8")
        (tmp_path / "c.identity.json").write_text(
            json.dumps({"distribution": "tiny-corpus", "version": "0.0.1"}), encoding="utf-8"
        )
        pin_corpus(corpus, distribution="tiny-corpus", version="0.0.1")
        clear_walk_sessions()
        source_file = open_source_file_for_construction(
            corpus / "use.py",
            root=corpus,
            reporter=CollectingReporter(),
            source_workspace_root=corpus,
        )
        refs = source_file.root.unit.construction_context.source_derived_contract_refs
        return [type(v).__name__ for v in refs.values()]
    finally:
        sys.path[:] = [p for p in sys.path if not p.endswith("/site")]


def test_installed_raises_without_match_is_cited(tmp_path) -> None:
    kinds = _derive(
        tmp_path,
        "from raiselib import raises\n\ndef f():\n    with raises(ValueError):\n        pass\n",
    )
    assert kinds == ["OpaqueCitedContextManagerRefV1"], kinds


def test_installed_raises_with_match_is_cited(tmp_path) -> None:
    kinds = _derive(
        tmp_path,
        'from raiselib import raises\n\ndef f():\n    with raises(ValueError, match="bad"):\n        pass\n',
    )
    assert kinds == ["OpaqueCitedContextManagerRefV1"], kinds


def test_pytest_spelled_installed_raises_is_cited_by_its_binding(tmp_path) -> None:
    """A ``RaisesExc``-spelled class answers through the import table alone."""
    kinds = _derive(
        tmp_path,
        'from raiselib import raises\n\ndef f():\n    with raises(ValueError, match="bad"):\n        pass\n',
        impl=_PYTEST_SPELLED_IMPL,
    )
    assert kinds == ["OpaqueCitedContextManagerRefV1"], kinds


def test_real_pytest_raises_with_match_is_cited(tmp_path) -> None:
    """``pytest.raises(E, match=...)`` is an imported call: cited by the target
    its binding resolves to, never derived from pytest's field spellings."""
    kinds = _derive(
        tmp_path,
        'from pytest import raises\n\ndef f():\n    with raises(ValueError, match="bad"):\n        pass\n',
    )
    assert kinds == ["OpaqueCitedContextManagerRefV1"], kinds
