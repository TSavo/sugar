#!/usr/bin/env python3.12
"""Build one task image from its derived managed-precondition closure."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import contract


def build_command(
    task: str,
    *,
    repo_root: Path,
    tag: str,
    push: bool,
) -> list[str]:
    projection = contract.resolve_task_image_build(
        task,
        repo_root,
        repo_root / "sugar-build.toml",
    )
    return [
        "docker",
        "buildx",
        "build",
        "--platform",
        "linux/amd64",
        "--target",
        projection["target"],
        "--build-arg",
        "MANAGED_APT_PACKAGES=" + " ".join(projection["aptPackages"]),
        "--build-arg",
        "MANAGED_RUST_TOOLCHAIN=" + projection["rustToolchain"],
        "--build-arg",
        "MANAGED_RUST_COMPONENTS=" + " ".join(projection["rustComponents"]),
        "--tag",
        tag,
        "--push" if push else "--load",
        "--file",
        str(repo_root / "tools/sugar-build/Dockerfile"),
        str(repo_root),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("task")
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    publication = parser.add_mutually_exclusive_group(required=True)
    publication.add_argument("--push", action="store_true")
    publication.add_argument("--load", action="store_true")
    args = parser.parse_args(argv)
    repo_root = args.repo_root.resolve()
    try:
        command = build_command(
            args.task,
            repo_root=repo_root,
            tag=args.tag,
            push=args.push,
        )
    except contract.ContractError as exc:
        print(f"sugar-build: {exc}", file=sys.stderr)
        return 2
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
