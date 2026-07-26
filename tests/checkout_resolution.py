"""Tests must measure THIS checkout, and must be able to prove they did.

The uid skips and the missing-corpus skips *omitted* work. This one is worse:
it **fabricates attribution**. A package that resolves to an editable install
pointing at another worktree does not fail -- it passes, reports coverage, and
every number taken from it describes a checkout nobody is looking at.

Found in ``sugar-lift-python-source`` (#6362), which lacked a ``conftest.py``
its sibling had and so imported
``/Users/tsavo/provekit-wt/fresh-main-20260701`` instead of its own tree. The
asymmetry was the tell, and it was not the only instance.

It also fabricates FAILURE attribution. ``sugar-lift-py-pytest-witness``
reported 12 failures that were nothing but the stale worktree reached through a
spawned subprocess::

    ImportError: cannot import name 'SourceUnavailable' from
    'sugar_lift_python_source.source_oracle'
    (/Users/tsavo/provekit-wt/fresh-main-20260701/.../source_oracle.py)

With the pin propagated to children, the same suite is 32 passed. So the pin
is not only ``sys.path``: a child process inherits ``PYTHONPATH``, not the
parent's ``sys.path``, and a test that shells out is measuring whatever that
child resolves.

The guard here asserts a POSITIVE -- *this module resolved under this repo
root* -- because the failure mode is not an error to detect. It is success
about the wrong thing.
"""

from __future__ import annotations

import ast
import importlib.util
import pathlib
import os
import sys


class CheckoutResolutionEscaped(AssertionError):
    """A package under test resolved outside this checkout.

    An ``AssertionError``, so it lands as a FAILURE. There is no honest
    weaker outcome: every assertion made after this point describes code that
    is not in this tree.
    """


def repo_root_from(start):
    """Walk up to the checkout root, identified by its top-level landmarks."""
    current = os.path.dirname(os.path.abspath(start))
    while True:
        if os.path.isdir(os.path.join(current, "implementations")) and os.path.isdir(
            os.path.join(current, "tests")
        ):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            raise CheckoutResolutionEscaped(
                f"no checkout root above {start}: expected an ancestor holding "
                "both implementations/ and tests/. Without a root there is "
                "nothing to prove resolution against."
            )
        current = parent


def _prepend_path(entry):
    if os.path.isdir(entry) and entry not in sys.path:
        sys.path.insert(0, entry)


def _prepend_pythonpath(entries):
    """Propagate the pin to child processes.

    A subprocess inherits PYTHONPATH, never the parent's sys.path. A test that
    shells out measures whatever the child resolves, which is how a stale
    worktree produced 12 phantom failures in sugar-lift-py-pytest-witness.
    """
    existing = os.environ.get("PYTHONPATH", "")
    parts = [p for p in existing.split(os.pathsep) if p]
    for entry in reversed(entries):
        if os.path.isdir(entry) and entry not in parts:
            parts.insert(0, entry)
    os.environ["PYTHONPATH"] = os.pathsep.join(parts)


def local_modules_under(src_dir):
    """Top-level importable names this checkout provides from ``src_dir``."""
    if not os.path.isdir(src_dir):
        return ()
    names = []
    for entry in sorted(os.listdir(src_dir)):
        full = os.path.join(src_dir, entry)
        if os.path.isdir(full) and os.path.isfile(os.path.join(full, "__init__.py")):
            names.append(entry)
        elif entry.endswith(".py") and not entry.startswith("_"):
            names.append(entry[:-3])
    return tuple(names)


def require_local_resolution(module_name, root):
    """Prove ``module_name`` resolves under ``root``. The positive assertion.

    Absence of an ImportError proves nothing here -- the whole defect is that
    the import SUCCEEDS, against the wrong tree. So the resolved origin is
    compared against the checkout root explicitly.
    """
    try:
        spec = importlib.util.find_spec(module_name)
    except Exception as error:  # a broken parent package, not our question
        raise CheckoutResolutionEscaped(
            f"{module_name} could not be resolved at all ({error!r}); a package "
            "whose resolution cannot be established cannot be measured"
        ) from None

    origin = getattr(spec, "origin", None) if spec else None
    if not origin:
        raise CheckoutResolutionEscaped(
            f"{module_name} does not resolve to any file, so nothing proves "
            f"which checkout its tests would measure. Expected it under {root}."
        )

    resolved = os.path.abspath(origin)
    if not resolved.startswith(os.path.abspath(root) + os.sep):
        raise CheckoutResolutionEscaped(
            f"{module_name} resolved OUTSIDE this checkout: {resolved} "
            f"(expected under {root}). The tests would pass, report coverage, "
            "and describe a tree nobody is editing -- this fabricates "
            "attribution rather than omitting work. "
            "replacement: pin this package's src through pin_checkout in its "
            "tests/conftest.py, ahead of any editable install. Do NOT rely on "
            "an installed distribution to be the checkout under test."
        )
    return resolved


def _imported_roots(path):
    """Top-level module names imported by one file, at any scope.

    Module scope is where an undeclared import aborts collection for the whole
    package, but a function-scope import of a sibling escapes to the wrong tree
    just as silently at runtime. Both are collected.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return ()
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return tuple(roots)


def _module_owners(packages_dir):
    """Map every top-level module this repo provides to the package shipping it."""
    owners = {}
    if not os.path.isdir(packages_dir):
        return owners
    for entry in sorted(os.listdir(packages_dir)):
        src = os.path.join(packages_dir, entry, "src")
        for module_name in local_modules_under(src):
            owners.setdefault(module_name, entry)
    return owners


def derive_required_siblings(package_dir, packages_dir):
    """Which sibling packages this one's code actually imports.

    DERIVED, never declared. A hand-maintained sibling list is a declaration
    that drifts from reality with nothing to notice -- which is exactly how
    ``siblings=()`` sat beside two real sibling imports while the guard stayed
    green and 30 test modules resolved a stale worktree.

    Transitive: a sibling's own sibling must be on the path too, or the import
    that reaches it escapes just the same.
    """
    owners = _module_owners(packages_dir)
    own_name = os.path.basename(package_dir)
    required = {}
    pending = [package_dir]
    seen = {own_name}

    while pending:
        current = pending.pop()
        for sub in ("tests", "src"):
            root = os.path.join(current, sub)
            if not os.path.isdir(root):
                continue
            for path in pathlib.Path(root).rglob("*.py"):
                if any(part in {"__pycache__", ".venv", "build"} for part in path.parts):
                    continue
                for imported in _imported_roots(path):
                    owner = owners.get(imported)
                    if owner is None or owner in seen:
                        continue
                    seen.add(owner)
                    required[owner] = imported
                    pending.append(os.path.join(packages_dir, owner))
    return required


def pin_checkout(conftest_file, siblings=()):
    """Pin this package's sources (and declared siblings) to THIS checkout.

    Called from a package's ``tests/conftest.py``. Inserts the local ``src``
    directories ahead of any installed distribution, propagates them to child
    processes, and then PROVES the package's own modules resolve locally.
    """
    here = os.path.dirname(os.path.abspath(conftest_file))
    package_dir = os.path.dirname(here)
    root = repo_root_from(conftest_file)
    packages_dir = os.path.dirname(package_dir)

    # Derived first, so nothing depends on a declaration staying true.
    # `siblings` remains only as an additive escape hatch for an import no
    # static scan can see; it can no longer HIDE a sibling by being empty.
    required = derive_required_siblings(package_dir, packages_dir)
    src_dirs = [os.path.join(package_dir, "src")]
    for sibling in sorted(set(required) | set(siblings)):
        src_dirs.append(os.path.join(packages_dir, sibling, "src"))

    for entry in reversed(src_dirs):
        _prepend_path(entry)
    # Helpers that live next to test modules (declared_corpus, fixtures).
    _prepend_path(here)
    _prepend_pythonpath(src_dirs)

    for module_name in local_modules_under(src_dirs[0]):
        require_local_resolution(module_name, root)
    # The positive assertion applies to siblings too. Importing one without an
    # ImportError proves nothing when the defect is a SUCCESSFUL import of the
    # wrong tree -- which is precisely what these 30 collection errors were.
    for imported in sorted(required.values()):
        require_local_resolution(imported, root)
    return root
