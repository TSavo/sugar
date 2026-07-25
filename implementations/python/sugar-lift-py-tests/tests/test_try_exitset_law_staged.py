"""STAGED: pin the six-line Try/ExitSet law. Do not treat green as merge-ready.

Merge waits on the post-V2 / post-Merkle census gate (PR #6242).

Full behavioral twins live in sugar-source-tree::

    tests/test_try_exitset_law.py

This module freezes the foundational routing path in production source so
staged Try work cannot silently invent a second control door.
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
    # First-match only is the router contract (source order, break after match).
    assert "first matching handler" in text or "first matching" in text


def test_route_handlers_first_match_is_runtime_behavior(tmp_path: Path) -> None:
    """A broad first arm wins at runtime; later matching arms do not run."""
    path = tmp_path / "t.py"
    path.write_text(
        "class RootFault(Exception):\n"
        "    pass\n"
        "class LeafFault(RootFault):\n"
        "    pass\n"
        "def f(z):\n"
        "    try:\n"
        "        raise LeafFault\n"
        "    except RootFault:\n"
        "        return 1\n"
        "    except LeafFault:\n"
        "        return 2\n"
        "    return z\n",
        encoding="utf-8",
    )
    fn = next(SourceFile(path_source(str(path))).functions())
    value = fn.sugar().desugar().value
    assert value.post().args[1].value == 1


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


def test_multi_handler_constructs_handlers_in_source_order(tmp_path: Path) -> None:
    """Handler specs on TrySugar follow source order (Exception then ValueError)."""
    path = tmp_path / "t.py"
    path.write_text(
        "def f(z):\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except Exception:\n"
        "        return 1\n"
        "    except ValueError:\n"
        "        return 2\n"
        "    return z\n",
        encoding="utf-8",
    )
    fn = next(SourceFile(path_source(str(path))).functions())
    try_nodes = [n for n in _walk(fn.sugar()) if isinstance(n, TrySugar)]
    assert try_nodes, "expected a TrySugar node"
    handlers = try_nodes[0].handlers
    assert len(handlers) >= 2
    # The constructed handler sequence is source order, not merely cardinality.
    assert [matcher.value.name for matcher, _body, _slot in handlers[:2]] == [
        "Exception",
        "ValueError",
    ]


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
