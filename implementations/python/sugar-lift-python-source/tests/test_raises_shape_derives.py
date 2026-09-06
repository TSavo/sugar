"""Plan Cut 3 core: a pytest.raises-shaped manager derives end to end.

This is the payoff of Cuts 2 (re.search recognition) + 6 (frame-door __init__
field seeding) + the existing isinstance semantic. A factory that returns a
RaisesExc whose __init__ stores ``expected``/``match`` and whose __exit__
checks ``isinstance(exc, self.expected)`` and ``re.search(self.match, ...)``
constructs a SourceDerivedContextManagerRefV1 -- not enter-may-halt, not a gap.

Key soundness note: ``re`` is NOT enrolled. re.search is recognized at the
authenticated import target by the Cut 2 seam (ImportMemberValue), so it never
materializes re's own body (which drags enum). Only the manager's own
distribution is enrolled.
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


def _install(root: Path):
    pkg = root / "site" / "raiselib"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("from raiselib.impl import raises\n", encoding="utf-8")
    (pkg / "impl.py").write_text(_IMPL, encoding="utf-8")
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


def _derive(tmp_path: Path, use: str):
    _install(tmp_path)
    monkeyenv = "raiselib"
    import os

    os.environ["SUGAR_ENROLLED_POPULATIONS"] = monkeyenv
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
            distribution="tiny-corpus",
            source_workspace_root=corpus,
        )
        refs = source_file.root.unit.construction_context.source_derived_contract_refs
        return [type(v).__name__ for v in refs.values()]
    finally:
        os.environ.pop("SUGAR_ENROLLED_POPULATIONS", None)
        sys.path[:] = [p for p in sys.path if not p.endswith("/site")]


def test_raises_without_match_derives(tmp_path) -> None:
    kinds = _derive(
        tmp_path,
        "from raiselib import raises\n\ndef f():\n    with raises(ValueError):\n        pass\n",
    )
    assert kinds == ["SourceDerivedContextManagerRefV1"], kinds


def test_raises_with_match_derives_via_re_recognition(tmp_path) -> None:
    kinds = _derive(
        tmp_path,
        'from raiselib import raises\n\ndef f():\n    with raises(ValueError, match="bad"):\n        pass\n',
    )
    assert kinds == ["SourceDerivedContextManagerRefV1"], kinds
