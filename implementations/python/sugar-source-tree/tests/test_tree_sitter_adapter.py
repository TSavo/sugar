"""tree-sitter-python adapter smoke tests (#5940, #5932).

No cross-backend CID comparison here (out of scope — see differential.py).
This adapter reproduces the FULL goldens/quirks.py corpus (including match/
case, which parso's grammar cannot express at all — see
test_parso_adapter.py), so the golden file doubles as this adapter's
broadest single regression fixture.
"""

import pytest

tree_sitter = pytest.importorskip("tree_sitter")
pytest.importorskip("tree_sitter_python")

from pathlib import Path

from sugar_source_tree import SourceFile
from sugar_source_tree.tree_sitter_python_adapter import TreeSitterPythonBackend

GOLDENS = Path(__file__).resolve().parents[1] / "goldens"


def _root(source: str, filename: str):
    return SourceFile(filename=filename, source=source, backend=TreeSitterPythonBackend()).root


def test_constructs_the_full_quirks_golden():
    source = (GOLDENS / "quirks.py").read_text(encoding="utf-8")
    root = _root(source, filename="quirks.py")
    assert len(list(root.walk())) > 20


def test_match_case_constructs():
    source = (
        "def matcher(value):\n"
        "    match value:\n"
        "        case 0 | 1:\n"
        "            return 'small'\n"
        "        case [first, *rest] if rest:\n"
        "            return first\n"
        "        case {'key': v, **others}:\n"
        "            return v\n"
        "        case Point(x=0, y=0):\n"
        "            return 'origin'\n"
        "        case _:\n"
        "            return None\n"
    )
    root = _root(source, filename="match.py")
    assert len(list(root.walk())) > 10


def test_byte_vs_codepoint_columns_are_normalized():
    """tree-sitter reports UTF-8 BYTE columns (like CPython, unlike parso/
    LibCST) — verify a non-ASCII prefix does not corrupt a later span."""
    source = 'x = "éü" + f(y)\n'
    root = _root(source, filename="unicode.py")
    call_positions = [
        n.segment() for n in root.walk() if type(n).__name__ == "Call"
    ]
    assert call_positions == ["f(y)"]
