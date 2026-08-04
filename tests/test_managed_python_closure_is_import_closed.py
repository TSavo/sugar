# SPDX-License-Identifier: MIT OR Apache-2.0
"""The managed `python-test` closure must be IMPORT-CLOSED.

`bin/bpytest` runs pytest inside the `python-test` image, whose first-party
`PYTHONPATH` is declared once in `tools/sugar-build/Dockerfile`. Every package on
that path is imported by pytest at COLLECTION time, so a first-party module that
is imported but not reachable on the path does not fail one test — it aborts
collection and a whole file silently disappears from the sweep.

That is how `sugar_source_tree` went missing: eight modules under
`sugar-lift-py-tests/src` import it at module scope, the Dockerfile path listed
`sugar-lift-py-tests` and `sugar-lift-python-source` but not `sugar-source-tree`,
and `bin/bpytest -q --collect-only .../test_exit_set.py` exited 2 with
`ModuleNotFoundError: No module named 'sugar_source_tree'`.

The same audit found `libsugar-py/src`, an entry naming a directory that does not
exist — `libsugar-py` is flat-layout — so `libsugar_py` was never importable in
the managed closure either. A path entry that resolves to nothing is silent.

This test closes the CLASS, not the instance: it re-derives the first-party
import closure from the sources themselves and refuses a path that is not closed
under it, or that contains an entry importing nothing at all.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from repo_root_test_support import resolve_repo_root

ROOT = resolve_repo_root()
DOCKERFILE = ROOT / "tools" / "sugar-build" / "Dockerfile"
WORKSPACE = "/workspace/sugar/"


def _import_roots() -> list[Path]:
    """Repo-relative import roots named by the image's PYTHONPATH, in order."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    matches = re.findall(r"^ENV PYTHONPATH=(.*)$", text, re.MULTILINE)
    assert len(matches) == 1, (
        f"expected exactly one `ENV PYTHONPATH` line in {DOCKERFILE}, found "
        f"{len(matches)}; a later line silently wins and this test would measure "
        "the wrong closure"
    )
    roots = []
    for entry in matches[0].split(":"):
        if not entry:
            continue
        assert entry.startswith(WORKSPACE), (
            f"PYTHONPATH entry {entry!r} is not under {WORKSPACE}; the managed "
            "closure executes Sugar's python from the mounted checkout only"
        )
        roots.append(ROOT / entry[len(WORKSPACE) :])
    assert roots, "the python-test image declares no first-party PYTHONPATH"
    return roots


def _packages_in(root: Path) -> set[str]:
    if not root.is_dir():
        return set()
    return {
        child.name
        for child in root.iterdir()
        if child.is_dir() and (child / "__init__.py").is_file()
    }


def _imports_under(root: Path, known: set[str]) -> dict[str, Path]:
    """Top-level first-party module names imported under `root`, to a witness."""
    found: dict[str, Path] = {}
    for path in sorted(root.rglob("*.py")):
        if ".egg-info" in path.parts or "vendor" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError):  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module] if node.level == 0 and node.module else []
            else:
                continue
            for name in names:
                head = name.split(".", 1)[0]
                if head in known:
                    found.setdefault(head, path)
    return found


def test_every_pythonpath_entry_actually_provides_a_package() -> None:
    """An entry that resolves to nothing is a silent lie about the closure."""
    empty = [
        str(root.relative_to(ROOT))
        for root in _import_roots()
        if not _packages_in(root)
    ]
    assert not empty, (
        "these python-test PYTHONPATH entries import nothing — the directory is "
        "missing or holds no package. Point them at the real import root "
        "(flat-layout packages have no `src/`):\n  " + "\n  ".join(empty)
    )


def test_managed_python_closure_is_closed_under_first_party_imports() -> None:
    roots = _import_roots()

    # A module is first-party if some import root in the repo provides it.
    provider: dict[str, Path] = {}
    for candidate in sorted((ROOT / "implementations" / "python").iterdir()):
        for root in (candidate / "src", candidate):
            for name in _packages_in(root):
                provider.setdefault(name, root)
    known = set(provider)

    on_path = {name for root in roots for name in _packages_in(root)}

    missing: list[str] = []
    for root in roots:
        for module, witness in _imports_under(root, known).items():
            if module in on_path:
                continue
            missing.append(
                f"{root.relative_to(ROOT)} imports `{module}` at "
                f"{witness.relative_to(ROOT)}, but no PYTHONPATH entry provides "
                f"it (it lives in {provider[module].relative_to(ROOT)})"
            )

    assert not missing, (
        "the managed python-test closure is not import-closed; pytest aborts "
        "COLLECTION on these, so whole files vanish from the sweep instead of "
        "failing loudly. Add the missing import roots to "
        "tools/sugar-build/Dockerfile and re-pin the image digest in "
        "sugar-build.toml:\n  " + "\n  ".join(missing)
    )


def test_sugar_source_tree_is_on_the_path() -> None:
    """Named regression pin for the instance that exposed the class."""
    on_path = {name for root in _import_roots() for name in _packages_in(root)}
    assert "sugar_source_tree" in on_path, (
        "sugar_source_tree dropped off the python-test PYTHONPATH; "
        "`bin/bpytest --collect-only` will exit 2 with "
        "ModuleNotFoundError: No module named 'sugar_source_tree'"
    )


def test_pythonpath_has_no_duplicate_entries() -> None:
    roots = [str(root) for root in _import_roots()]
    assert len(roots) == len(set(roots)), f"duplicate PYTHONPATH entries: {roots}"


def test_the_closure_test_discriminates() -> None:
    """Both arms: the audit must FIRE on a path that drops a needed root.

    A green closure test proves nothing unless removing a required entry turns
    it red. This runs the negative arm in-process.
    """
    roots = _import_roots()
    kept = [r for r in roots if "sugar_source_tree" not in _packages_in(r)]
    assert len(kept) == len(roots) - 1, "sugar-source-tree not on the path to drop"

    provider: dict[str, Path] = {}
    for candidate in sorted((ROOT / "implementations" / "python").iterdir()):
        for root in (candidate / "src", candidate):
            for name in _packages_in(root):
                provider.setdefault(name, root)

    on_path = {name for root in kept for name in _packages_in(root)}
    hits = [
        module
        for root in kept
        for module in _imports_under(root, set(provider))
        if module not in on_path
    ]
    assert "sugar_source_tree" in hits, (
        "dropping sugar-source-tree from the path did NOT make the audit fire; "
        "the audit is not measuring what it claims to measure"
    )
