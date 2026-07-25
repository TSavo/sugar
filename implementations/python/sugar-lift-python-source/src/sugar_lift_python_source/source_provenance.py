"""Kit-source testimony for Python lift RPC initialize responses.

The CLI enforces `kit_source.identity` on the `python` authoring surface so
mint/prove can seal split-pipeline provenance. Every Python RPC that can be
registered as that surface must include this field.

Kit identity is the sourceStamp, NOT Git HEAD (#6224): the binary embeds
`SUGAR_BUILD_STAMP` and the gate (`refuse_split_pipeline`) is
`kit.sourceStamp == binary.sourceStamp`. #6224 migrated the
`sugar_lift_py_tests` twin of this module and left this one on Git HEAD, which
refused every mint that registered the `python` surface through
`verify_rpc.run_rpc` (e.g. examples/python-bodyguard-precondition). Both
modules must keep answering the same `kind`; `tests/source_stamp_compat_twins.sh`
holds that line.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Iterable

from sugar_lift_python_source.canonical import blake3_512_of


def _git(root: Path, *args: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(root), *args], text=True, capture_output=True, check=False
    )
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _monorepo_root() -> Path | None:
    """Locate monorepo root from installed package paths (…/implementations/python/…)."""
    import sugar_lift_python_source

    here = Path(sugar_lift_python_source.__file__).resolve()
    for parent in here.parents:
        if (parent / "tools" / "sugar_source_stamp.py").is_file() and (
            parent / "implementations" / "rust" / "Cargo.toml"
        ).is_file():
            return parent
    return None


def _content_identity(roots: list[Path]) -> str:
    """Legacy content hash (tests / non-monorepo). Path-safe underscore form."""
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
    # blake3_512_of returns blake3-512:<hex>; normalize to the path-safe _ form.
    return blake3_512_of(bytes(material)).replace(":", "_", 1)


def source_provenance_for_roots(roots: Iterable[Path]) -> dict[str, object]:
    """Content identity of `roots`. Git HEAD is an attestation, never identity
    (#6224), so it only contributes the `dirty` flag."""
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
    import sugar_lift_python_source

    roots = [Path(sugar_lift_python_source.__file__).resolve().parent]
    for module in ("sugar_lift_py_tests", "sugar_source_tree"):
        try:
            imported = __import__(module)
        except ImportError:
            continue
        roots.append(Path(imported.__file__).resolve().parent)
    return roots


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

    Matches the binary's embedded SUGAR_BUILD_STAMP so the split-pipeline gate
    is kit.sourceStamp == binary.sourceStamp. Mirror of
    `sugar_lift_py_tests.source_provenance.kit_source_provenance`: both Python
    kits can be registered as the `python` surface, so both must answer the
    same identity kind or one of them refuses every mint (#6224).
    """
    stamp = source_stamp_for_sugar_cli()
    if stamp is not None:
        dirty = False
        root = _monorepo_root()
        if root is not None:
            dirty = any(
                bool(_git(root, "status", "--porcelain", "--", rel))
                for rel in (
                    "implementations/python/sugar-lift-python-source",
                    "implementations/python/sugar-lift-py-tests",
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
