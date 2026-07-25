"""STAGED: pin the six-line Try/ExitSet law. Do not treat green as merge-ready.

Merge waits on the post-Merkle census gate. This test only freezes the
foundational routing path so staged Try work cannot silently invent a second
control door.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.sugar.try_sugar import TrySugar
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile


def test_try_sugar_source_documents_exitset_law() -> None:
    """The production TrySugar module must name the foundational path."""
    path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "sugar_lift_py_tests"
        / "sugar"
        / "try_sugar.py"
    )
    text = path.read_text(encoding="utf-8")
    assert "body -> guarded ExitSet" in text or "guarded ExitSet" in text
    assert "handler routing" in text or "_route_handlers_over_exits" in text
    assert "finally" in text


def test_basic_try_except_constructs_try_sugar(tmp_path: Path) -> None:
    path = tmp_path / "t.py"
    path.write_text(
        "def f(z):\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except ValueError:\n"
        "        pass\n"
        "    return z\n",
        encoding="utf-8",
    )
    fn = next(SourceFile(path_source(str(path))).functions())
    sugar = fn.sugar()
    assert any(isinstance(node, TrySugar) for node in _walk(sugar))


def _walk(root, seen=None):
    if seen is None:
        seen = set()
    if id(root) in seen:
        return
    seen.add(id(root))
    yield root
    for name in dir(root):
        if name.startswith("_"):
            continue
        try:
            child = getattr(root, name)
        except Exception:
            continue
        if isinstance(child, (list, tuple)):
            for item in child:
                if hasattr(item, "desugar"):
                    yield from _walk(item, seen)
        elif hasattr(child, "desugar"):
            yield from _walk(child, seen)
