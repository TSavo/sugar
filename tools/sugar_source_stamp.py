#!/usr/bin/env python3
"""Authenticated Rust build sourceStamp for a Cargo package.

Emits the same labeled byte stream sugarbin hashes into sourceStamp:

  - cargo package local dependency FS (under implementations/rust)

Python, repository docs, .git, build output, and other non-Rust-package state
are deliberately excluded: this stamp keys the compiled Rust artifact, not the
whole runtime composition. Path coordinates use underscore form:
blake3-512_<hex>.

Usage:
  tools/sugar_source_stamp.py --repo-root ROOT --package sugar-cli
  tools/sugar_source_stamp.py --stream   # raw stream to stdout (for b3sum)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

SKIP_DIRS = {
    ".git",
    ".hg",
    ".jj",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".sugar",
    "node_modules",
    "target",
    "__pycache__",
}
SKIP_FILES = {".DS_Store"}


def resolve_source_stamp_tools(cargo: str) -> tuple[str, str] | None:
    """Resolve the complete toolset before constructing any stamp bytes."""

    commands = (("b3sum", "b3sum"), ("cargo", cargo))
    resolved: dict[str, str] = {}
    missing: list[str] = []
    for name, command in commands:
        path = shutil.which(command)
        if path is None:
            missing.append(name)
        else:
            resolved[name] = os.path.abspath(path)

    if missing:
        if len(missing) == 1:
            named = f"missing required tool: {missing[0]}"
            required = f"{missing[0]} is required for source stamping"
        else:
            named = f"missing required tools: {', '.join(missing)}"
            required = f"{' and '.join(missing)} are required for source stamping"
        print(f"::error::source stamping refused: {named}; {required}", file=sys.stderr)
        return None

    return resolved["b3sum"], resolved["cargo"]


def emit(label: bytes, value: bytes) -> None:
    out = sys.stdout.buffer
    out.write(str(len(label)).encode("ascii"))
    out.write(b":")
    out.write(label)
    out.write(str(len(value)).encode("ascii"))
    out.write(b":")
    out.write(value)


def emit_path(base: Path, path: Path, *, path_label: bytes = b"path") -> None:
    rel = path.relative_to(base).as_posix()
    st = os.lstat(path)
    if stat.S_ISLNK(st.st_mode):
        kind = b"symlink"
        content = os.readlink(path).encode("utf-8", "surrogateescape")
    elif stat.S_ISREG(st.st_mode):
        kind = b"file"
        content = path.read_bytes()
    else:
        return
    executable = b"1" if (st.st_mode & 0o111) else b"0"
    emit(path_label, rel.encode("utf-8", "surrogateescape"))
    emit(b"kind", kind)
    emit(b"exec", executable)
    emit(b"bytes", content)


def walk_emit(base: Path, package_root: Path, *, path_label: bytes = b"path") -> set[Path]:
    seen: set[Path] = set()
    for dirpath, dirnames, filenames in os.walk(package_root, topdown=True, followlinks=False):
        dirnames[:] = sorted(name for name in dirnames if name not in SKIP_DIRS)
        for filename in sorted(name for name in filenames if name not in SKIP_FILES):
            path = Path(dirpath) / filename
            if path in seen:
                continue
            emit_path(base, path, path_label=path_label)
            seen.add(path)
    return seen


def write_stream(
    *,
    repo_root: Path,
    rust_workspace: Path,
    package: str,
    cargo: str,
) -> None:
    root = rust_workspace.resolve()
    if not root.is_dir():
        raise SystemExit(f"rust workspace not found: {root}")

    metadata = json.loads(
        subprocess.check_output(
            [
                cargo,
                "metadata",
                "--locked",
                "--format-version",
                "1",
                "--manifest-path",
                str(root / "Cargo.toml"),
            ],
            text=True,
        )
    )
    packages = {package_row["id"]: package_row for package_row in metadata["packages"]}
    selected = [
        package_row["id"]
        for package_row in metadata["packages"]
        if package_row["name"] == package and package_row["id"] in metadata["workspace_members"]
    ]
    if len(selected) != 1:
        raise SystemExit(
            f"expected one workspace package named {package!r}, found {len(selected)}"
        )
    nodes = {node["id"]: node for node in metadata["resolve"]["nodes"]}
    closure: set[str] = set()
    pending = selected[:]
    while pending:
        package_id = pending.pop()
        if package_id in closure:
            continue
        closure.add(package_id)
        pending.extend(dep["pkg"] for dep in nodes[package_id]["deps"])

    local_roots = sorted(
        {
            Path(packages[package_id]["manifest_path"]).parent
            for package_id in closure
            if Path(packages[package_id]["manifest_path"]).is_relative_to(root)
        },
        key=lambda path: path.as_posix(),
    )

    def stable_id(package_id: str) -> str:
        package_row = packages[package_id]
        manifest = Path(package_row["manifest_path"])
        if manifest.is_relative_to(root):
            return (
                f"workspace:{manifest.relative_to(root).as_posix()}:"
                f"{package_row['name']}@{package_row['version']}"
            )
        return package_id

    graph = []
    for package_id in sorted(closure):
        package_row = packages[package_id]
        node = nodes[package_id]
        graph.append(
            {
                "id": stable_id(package_id),
                "name": package_row["name"],
                "version": package_row["version"],
                "source": package_row.get("source"),
                "checksum": package_row.get("checksum"),
                "features": sorted(node.get("features", [])),
                "dependencies": sorted(
                    stable_id(dep["pkg"]) for dep in node.get("deps", [])
                ),
            }
        )
    emit(
        b"cargo-closure",
        json.dumps(graph, sort_keys=True, separators=(",", ":")).encode(),
    )

    seen: set[Path] = set()
    for common in (
        root / "Cargo.toml",
        root / ".cargo" / "config",
        root / ".cargo" / "config.toml",
    ):
        if common.exists():
            emit_path(root, common)
            seen.add(common)

    for package_root in local_roots:
        seen |= walk_emit(root, package_root)

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument(
        "--rust-workspace",
        type=Path,
        default=None,
        help="defaults to <repo-root>/implementations/rust",
    )
    parser.add_argument("--package", default="sugar-cli")
    parser.add_argument("--cargo", default=os.environ.get("CARGO", "cargo"))
    parser.add_argument(
        "--stream",
        action="store_true",
        help="write the raw stamp preimage stream to stdout",
    )
    args = parser.parse_args(argv)
    rust_workspace = args.rust_workspace or (
        args.repo_root / "implementations" / "rust"
    )
    tools = resolve_source_stamp_tools(args.cargo)
    if tools is None:
        return 2
    b3sum, cargo = tools

    if args.stream:
        write_stream(
            repo_root=args.repo_root,
            rust_workspace=rust_workspace,
            package=args.package,
            cargo=cargo,
        )
        return 0

    # Hash stream via b3sum when available (same as sugarbin).
    proc = subprocess.Popen(
        [sys.executable, __file__, "--stream",
         "--repo-root", str(args.repo_root),
         "--rust-workspace", str(rust_workspace),
         "--package", args.package,
         "--cargo", cargo],
        stdout=subprocess.PIPE,
    )
    assert proc.stdout is not None
    b3 = subprocess.run(
        [b3sum, "-l", "64", "--no-names"],
        stdin=proc.stdout,
        capture_output=True,
        check=False,
    )
    preimage_status = proc.wait()
    if preimage_status != 0:
        print(
            "::error::source stamping refused: cargo could not construct the "
            f"source-stamp preimage (exit {preimage_status}); cargo is required "
            "for source stamping",
            file=sys.stderr,
        )
        return 2
    if b3.returncode == 0 and b3.stdout:
        digest = b3.stdout.decode().strip()
        if len(digest) == 128 and all(c in "0123456789abcdef" for c in digest):
            print(f"blake3-512_{digest}")
            return 0
    stderr = b3.stderr.decode("utf-8", "replace").strip()
    detail = f"; stderr={stderr}" if stderr else ""
    print(
        "::error::source stamping refused: b3sum did not produce a valid "
        f"blake3-512 digest (exit {b3.returncode}){detail}; b3sum is required "
        "for source stamping",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
