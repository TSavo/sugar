from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Mapping

_PYTHON_PACKAGE_PATHS: tuple[tuple[str, str], ...] = (
    (
        "sugar_lift_py_tests",
        "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests",
    ),
    (
        "sugar_lift_python_source",
        "implementations/python/sugar-lift-python-source/src/sugar_lift_python_source",
    ),
    (
        "sugar_source_tree",
        "implementations/python/sugar-source-tree/src/sugar_source_tree",
    ),
)


def _git(root: Path, *args: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(root), *args], text=True, capture_output=True, check=False
    )
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _monorepo_root() -> Path | None:
    """Locate monorepo root via the one resolve door (sugar-build.toml).

    Returns None when the door refuses — callers that need a soft miss keep
    that shape. Prefer ``resolve_repo_root()`` when absence must be loud.
    """
    from sugar_lift_py_tests.repo_root import RepoRootUnresolved, resolve_repo_root

    try:
        return resolve_repo_root()
    except RepoRootUnresolved:
        return None


def _content_identity(roots: list[Path]) -> str:
    """Legacy content hash (tests / non-monorepo). Path-safe underscore form."""
    from sugar_lift_py_tests.canonicalizer import blake3_512_of

    material = bytearray()
    for index, root in enumerate(roots):
        for path in sorted(
            candidate for candidate in root.rglob("*") if candidate.is_file()
        ):
            if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
                continue
            relative = path.relative_to(root).as_posix().encode()
            payload = path.read_bytes()
            material.extend(f"{index}:".encode() + relative + b"\0")
            material.extend(str(len(payload)).encode() + b"\0" + payload)
    # blake3_512_of returns blake3-512:<hex> historically; normalize to _.
    raw = blake3_512_of(bytes(material))
    return raw.replace(":", "_", 1)


def source_provenance_for_roots(roots: Iterable[Path]) -> dict[str, object]:
    resolved = [Path(root).resolve() for root in roots]
    dirty = False
    for root in resolved:
        top = _git(root, "rev-parse", "--show-toplevel")
        if top is None:
            continue
        try:
            relative = root.relative_to(Path(top)).as_posix()
        except ValueError:
            continue
        if bool(_git(Path(top), "status", "--porcelain", "--", relative)):
            dirty = True
            break
    return {
        "identity": _content_identity(resolved),
        "kind": "content",
        "dirty": dirty,
    }


def kit_package_roots() -> list[Path]:
    import sugar_lift_py_tests
    import sugar_lift_python_source
    import sugar_source_tree

    return [
        Path(sugar_lift_py_tests.__file__).resolve().parent,
        Path(sugar_lift_python_source.__file__).resolve().parent,
        Path(sugar_source_tree.__file__).resolve().parent,
    ]


def _canonical_content_cid(root: Path) -> str:
    """Content identity in the in-memory CID spelling, never path spelling."""
    return _content_identity([root]).replace("blake3-512_", "blake3-512:", 1)


def _loaded_package_origins() -> dict[str, Path]:
    import sugar_lift_py_tests
    import sugar_lift_python_source
    import sugar_source_tree

    modules = {
        "sugar_lift_py_tests": sugar_lift_py_tests,
        "sugar_lift_python_source": sugar_lift_python_source,
        "sugar_source_tree": sugar_source_tree,
    }
    origins: dict[str, Path] = {}
    for package, module in modules.items():
        raw_origin = getattr(module, "__file__", None)
        if not raw_origin:
            raise RuntimeError(
                "LoadedPythonSourceIdentityConstructionGapV1: "
                f"loaded package {package!r} has no module origin"
            )
        origins[package] = Path(raw_origin).resolve()
    return origins


def _declared_package_roots(repo_root: Path | None = None) -> dict[str, Path]:
    from sugar_lift_py_tests.repo_root import resolve_repo_root

    root = Path(repo_root).resolve() if repo_root is not None else resolve_repo_root()
    return {
        package: (root / relative).resolve()
        for package, relative in _PYTHON_PACKAGE_PATHS
    }


def _package_identity_rows(
    roots: Mapping[str, Path], *, origins: Mapping[str, Path] | None = None
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for package in sorted(roots):
        root = Path(roots[package]).resolve()
        origin = (
            Path(origins[package]).resolve()
            if origins is not None
            else (root / "__init__.py").resolve()
        )
        rows.append(
            {
                "subject": package,
                "origin": str(origin),
                "root": str(root),
                "contentCid": _canonical_content_cid(root),
            }
        )
    return rows


def loaded_python_source_identity(
    *,
    declared_package_roots: Mapping[str, Path] | None = None,
    loaded_package_origins: Mapping[str, Path] | None = None,
) -> dict[str, object]:
    """Describe the checkout declared by the run and packages actually loaded.

    Origins are testimony, not identity: an installed copy may live at a
    different path while carrying the same bytes. The consumer authenticates
    the package roster and per-package content CIDs and retains both origin
    inventories in the receipt.
    """
    declared = (
        _declared_package_roots()
        if declared_package_roots is None
        else {
            name: Path(root).resolve() for name, root in declared_package_roots.items()
        }
    )
    loaded_origins = (
        _loaded_package_origins()
        if loaded_package_origins is None
        else {
            name: Path(origin).resolve()
            for name, origin in loaded_package_origins.items()
        }
    )
    if set(declared) != set(loaded_origins):
        raise RuntimeError(
            "LoadedPythonSourceIdentityConstructionGapV1: declared and loaded "
            f"package rosters differ: declared={sorted(declared)!r} "
            f"loaded={sorted(loaded_origins)!r}"
        )
    loaded_roots = {
        package: origin.parent for package, origin in loaded_origins.items()
    }
    return {
        "schema": "loaded-source-identity/v1",
        "declared": _package_identity_rows(declared),
        "loaded": _package_identity_rows(loaded_roots, origins=loaded_origins),
    }


def source_stamp_for_sugar_cli(repo_root: Path | None = None) -> str | None:
    """Same sourceStamp sugarbin / SUGAR_BUILD_STAMP use for package sugar-cli."""
    root = repo_root or _monorepo_root()
    if root is None:
        return None
    script = root / "tools" / "sugar_source_stamp.py"
    if not script.is_file():
        return None
    cargo = os.environ.get("SUGAR_BINARY_CARGO") or os.environ.get("CARGO") or "cargo"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--repo-root",
            str(root),
            "--package",
            "sugar-cli",
            "--cargo",
            cargo,
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    stamp = result.stdout.strip()
    if not stamp.startswith("blake3-512_"):
        return None
    return stamp


def kit_source_provenance() -> dict[str, object]:
    """Kit identity is the sourceStamp (not Git HEAD).

    Matches the binary's embedded SUGAR_BUILD_STAMP so the split-pipeline
    gate is kit.sourceStamp == binary.sourceStamp.
    """
    stamp = source_stamp_for_sugar_cli()
    if stamp is not None:
        dirty = False
        root = _monorepo_root()
        if root is not None:
            dirty = any(
                bool(_git(root, "status", "--porcelain", "--", rel))
                for rel in (
                    "implementations/python/sugar-lift-py-tests",
                    "implementations/python/sugar-lift-python-source",
                    "implementations/python/sugar-source-tree",
                    "implementations/rust",
                )
            )
        return {
            "identity": stamp,
            "kind": "sourceStamp",
            "dirty": dirty,
        }
    # Offline / unpackaged: content identity of kit packages only.
    return source_provenance_for_roots(kit_package_roots())
