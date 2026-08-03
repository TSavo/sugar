"""An arm that cannot import its dispatch target is unwritten, not working.

`perform_operation` was deleted with the operations layer (`b0aadef50`). #6316
later created a *new* `operations` package holding one unrelated module. The
name never came back, and five call sites still reach for it — three in
`floor/call_site_value.py`, one in `floor/symbolic_value.py`, one in
`floor/block_value.py`. All five import it lazily, inside the function body, so
nothing fails until the arm is actually reached.

**Why this is a scoreboard defect and not a floor bug.** Reaching one of those
arms raises `ImportError` / `ModuleNotFoundError`. That is not a
`ConstructionPanic`, not a typed refusal, and not in any family the census
buckets. The row comes back short and nothing says so — an unwritten arm
wearing a working arm's clothes. It is the same class as an instrument that
cannot see what it reports, except this one *corrupts* counts instead of
producing a visible zero, which is strictly harder to notice.

A lazy import is a promise that the name exists. This test collects every such
promise in the kit's source and checks it, so the promise cannot be broken
silently again. It reads the SOURCE rather than executing the arms: these paths
are reached from vendor source shapes, not from unit tests, so "the suite
passes" says nothing about them.
"""

from __future__ import annotations

import ast
import importlib
import importlib.util
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"


def _function_local_imports(tree: ast.AST) -> list[tuple[str, str, int]]:
    """Every ``from X import Y`` that lives inside a function body.

    Module-level imports fail loudly at import time and cannot hide. A
    function-local import is the one that waits until the arm is reached.
    """
    promises: list[tuple[str, str, int]] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.ImportFrom) and inner.module and inner.level == 0:
                for alias in inner.names:
                    promises.append((inner.module, alias.name, inner.lineno))
    return promises


def _resolves(module: str, name: str) -> bool:
    """Does ``from <module> import <name>`` actually have something to bind?

    Checked without importing: a submodule on disk, or a name bound at the
    module's top level. Importing the whole kit here would drag in the engine
    and turn a source audit into an integration test.
    """
    try:
        spec = importlib.util.find_spec(module)
    except (ImportError, AttributeError):
        return False
    if spec is None:
        return False
    # Only ask about a submodule when the parent is actually a package.
    # ``find_spec("some.module.Name")`` RAISES rather than returning None when
    # ``some.module`` is a plain module -- which is most of them.
    if spec.submodule_search_locations is not None:
        try:
            if importlib.util.find_spec(f"{module}.{name}") is not None:
                return True
        except (ImportError, AttributeError):
            pass
    origin = spec.origin
    if not origin or not origin.endswith(".py"):
        return False
    tree = ast.parse(Path(origin).read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name == name:
                return True
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return True
        elif isinstance(node, ast.AnnAssign):
            if isinstance(node.target, ast.Name) and node.target.id == name:
                return True
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                if (alias.asname or alias.name.split(".")[0]) == name:
                    return True
    return False


def _broken_promises() -> list[str]:
    broken: list[str] = []
    for path in sorted(SRC.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for module, name, line in _function_local_imports(tree):
            if not module.startswith("sugar_"):
                continue  # third-party availability is the closure's business
            if not _resolves(module, name):
                broken.append(
                    f"{path.relative_to(SRC)}:{line} from {module} import {name}"
                )
    return broken


def test_every_lazy_dispatch_target_resolves() -> None:
    broken = _broken_promises()
    assert not broken, (
        "these arms import a dispatch target that does not exist. Reaching one "
        "raises ImportError, which is not a panic, not a typed refusal, and not "
        "in any family the census buckets -- the row comes back short and "
        "nothing says so:\n  " + "\n  ".join(broken)
    )


def test_the_audit_actually_recognizes(tmp_path) -> None:
    """Discriminating face: a real name resolves, an invented one does not."""
    # A name that genuinely exists in the kit.
    assert _resolves("sugar_lift_py_tests.corpus_pin", "pin_corpus")
    # A submodule, reached the other way.
    assert _resolves("sugar_lift_py_tests", "corpus_pin")
    # The shapes that must NOT pass.
    assert not _resolves("sugar_lift_py_tests.corpus_pin", "perform_operation")
    assert not _resolves("sugar_lift_py_tests.operations.perform_operation", "x")
    assert not _resolves("sugar_lift_py_tests.no_such_module_at_all", "anything")

    # And the walker must actually see a function-local import, not just
    # module-level ones -- that distinction is the whole point.
    tree = ast.parse(
        "import os\n" "def f():\n" "    from sugar_x.y import z\n" "    return z\n"
    )
    assert _function_local_imports(tree) == [("sugar_x.y", "z", 3)]
