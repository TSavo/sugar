from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Iterable

from sugar_lift_py_tests.canonicalizer import blake3_512_of


def _git(root: Path, *args: str) -> str | None:
    result = subprocess.run(
        ["git", "-C", str(root), *args], text=True, capture_output=True, check=False
    )
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def _content_identity(roots: list[Path]) -> str:
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
    return blake3_512_of(bytes(material))


def source_provenance_for_roots(roots: Iterable[Path]) -> dict[str, object]:
    resolved = [Path(root).resolve() for root in roots]
    git_rows: list[tuple[Path, str, str]] = []
    for root in resolved:
        top = _git(root, "rev-parse", "--show-toplevel")
        head = _git(root, "rev-parse", "HEAD")
        if top is None or head is None:
            return {
                "identity": _content_identity(resolved),
                "kind": "content",
                "dirty": False,
            }
        git_rows.append((Path(top), head, root.relative_to(Path(top)).as_posix()))
    heads = {head for _, head, _ in git_rows}
    if len(heads) != 1:
        return {
            "identity": _content_identity(resolved),
            "kind": "content",
            "dirty": False,
        }
    dirty = any(
        bool(_git(top, "status", "--porcelain", "--", relative))
        for top, _, relative in git_rows
    )
    return {"identity": next(iter(heads)), "kind": "git", "dirty": dirty}


def kit_source_provenance() -> dict[str, object]:
    import sugar_lift_py_tests
    import sugar_lift_python_source

    roots = [
        Path(sugar_lift_py_tests.__file__).resolve().parent,
        Path(sugar_lift_python_source.__file__).resolve().parent,
    ]
    return source_provenance_for_roots(roots)
