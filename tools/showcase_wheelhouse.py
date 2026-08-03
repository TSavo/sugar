#!/usr/bin/env python3
"""Derive and verify the showcase offline build-isolation wheelhouse."""

from __future__ import annotations

import argparse
from email.parser import BytesParser
from email.policy import default
import re
import sys
import tomllib
import zipfile
from dataclasses import dataclass
from pathlib import Path

try:
    from packaging.requirements import Requirement
    from packaging.tags import sys_tags
    from packaging.utils import canonicalize_name, parse_wheel_filename
except ModuleNotFoundError:  # pip necessarily exists at this provisioning door
    from pip._vendor.packaging.requirements import Requirement
    from pip._vendor.packaging.tags import sys_tags
    from pip._vendor.packaging.utils import canonicalize_name, parse_wheel_filename


class WheelhouseRefusal(RuntimeError):
    """The showcase environment cannot be constructed honestly."""


def _editable_projects(repo_root: Path, manifest: Path) -> tuple[Path, ...]:
    projects: list[Path] = []
    for line_number, raw_line in enumerate(
        manifest.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if not line.startswith("-e "):
            raise WheelhouseRefusal(
                f"{manifest}:{line_number}: expected an editable '-e PATH' entry, "
                f"observed {line!r}"
            )
        editable = line[3:].strip()
        match = re.fullmatch(r"(?P<path>.+?)(?:\[[^]]+\])?", editable)
        if match is None:
            raise WheelhouseRefusal(
                f"{manifest}:{line_number}: cannot resolve editable entry {line!r}"
            )
        project = (repo_root / match.group("path")).resolve()
        try:
            project.relative_to(repo_root)
        except ValueError as exc:
            raise WheelhouseRefusal(
                f"{manifest}:{line_number}: editable project escapes repo root: {project}"
            ) from exc
        projects.append(project)
    if not projects:
        raise WheelhouseRefusal(f"{manifest}: no editable projects enrolled")
    return tuple(projects)


def derive_build_requirements(
    repo_root: Path, editable_requirements: Path
) -> tuple[str, ...]:
    repo_root = repo_root.resolve()
    requirements: set[str] = set()
    for project in _editable_projects(repo_root, editable_requirements.resolve()):
        pyproject = project / "pyproject.toml"
        if not pyproject.is_file():
            raise WheelhouseRefusal(f"missing build declaration {pyproject}")
        with pyproject.open("rb") as stream:
            document = tomllib.load(stream)
        declared = document.get("build-system", {}).get("requires")
        if not isinstance(declared, list) or not declared:
            raise WheelhouseRefusal(
                f"{pyproject}: [build-system].requires must be a non-empty list"
            )
        for requirement in declared:
            if not isinstance(requirement, str) or not requirement.strip():
                raise WheelhouseRefusal(
                    f"{pyproject}: invalid [build-system].requires entry "
                    f"{requirement!r}"
                )
            requirements.add(requirement.strip())
    return tuple(sorted(requirements, key=str.casefold))


def write_build_requirements(
    repo_root: Path, editable_requirements: Path, output: Path
) -> tuple[str, ...]:
    requirements = derive_build_requirements(repo_root, editable_requirements)
    output.write_text("".join(f"{item}\n" for item in requirements), encoding="utf-8")
    return requirements


@dataclass(frozen=True)
class _Wheel:
    name: str
    version: object
    requires: tuple[str, ...]


def _wheel_index(wheelhouse: Path) -> dict[str, list[_Wheel]]:
    compatible_tags = set(sys_tags())
    index: dict[str, list[_Wheel]] = {}
    for path in sorted(wheelhouse.glob("*.whl")):
        try:
            filename_name, filename_version, _, tags = parse_wheel_filename(path.name)
        except ValueError as exc:
            raise WheelhouseRefusal(
                f"malformed wheel filename {path.name}: {exc}"
            ) from exc
        if tags.isdisjoint(compatible_tags):
            continue
        with zipfile.ZipFile(path) as archive:
            metadata_paths = [
                name
                for name in archive.namelist()
                if name.endswith(".dist-info/METADATA") and name.count("/") == 1
            ]
            if len(metadata_paths) != 1:
                raise WheelhouseRefusal(
                    f"{path.name}: expected one .dist-info/METADATA, "
                    f"observed {len(metadata_paths)}"
                )
            metadata = BytesParser(policy=default).parsebytes(
                archive.read(metadata_paths[0])
            )
        metadata_name = metadata.get("Name")
        metadata_version = metadata.get("Version")
        if canonicalize_name(metadata_name or "") != canonicalize_name(filename_name):
            raise WheelhouseRefusal(
                f"{path.name}: filename distribution {filename_name!s} disagrees "
                f"with METADATA Name {metadata_name!r}"
            )
        if metadata_version != str(filename_version):
            raise WheelhouseRefusal(
                f"{path.name}: filename version {filename_version!s} disagrees "
                f"with METADATA Version {metadata_version!r}"
            )
        name = canonicalize_name(metadata_name)
        index.setdefault(name, []).append(
            _Wheel(
                name=name,
                version=filename_version,
                requires=tuple(metadata.get_all("Requires-Dist", [])),
            )
        )
    return index


def _marker_applies(requirement: Requirement, extras: set[str]) -> bool:
    if requirement.marker is None:
        return True
    return any(
        requirement.marker.evaluate({"extra": extra}) for extra in extras or {""}
    )


def verify_wheelhouse(
    repo_root: Path, editable_requirements: Path, wheelhouse: Path
) -> None:
    declared = derive_build_requirements(repo_root, editable_requirements)
    if not wheelhouse.is_dir():
        raise WheelhouseRefusal(
            f"missing wheelhouse {wheelhouse}; build requirements are required "
            "for offline editable install"
        )
    index = _wheel_index(wheelhouse)
    pending = [(Requirement(text), {""}) for text in declared]
    constraints: dict[str, list[Requirement]] = {}
    requested_extras: dict[str, set[str]] = {}
    expanded: set[tuple[str, object, tuple[str, ...]]] = set()
    while pending:
        requirement, parent_extras = pending.pop(0)
        if not _marker_applies(requirement, parent_extras):
            continue
        name = canonicalize_name(requirement.name)
        constraints.setdefault(name, []).append(requirement)
        requested_extras.setdefault(name, set()).update(requirement.extras)
        candidates = [
            wheel
            for wheel in index.get(name, [])
            if all(
                not item.specifier
                or item.specifier.contains(wheel.version, prereleases=True)
                for item in constraints[name]
            )
        ]
        if not candidates:
            raise WheelhouseRefusal(
                f"missing distribution '{name}' (requirement {str(requirement)!r}); "
                "it is required for offline editable install build isolation"
            )
        selected = max(candidates, key=lambda wheel: wheel.version)
        expansion = (
            name,
            selected.version,
            tuple(sorted(requested_extras[name])),
        )
        if expansion in expanded:
            continue
        expanded.add(expansion)
        pending.extend(
            (Requirement(text), requested_extras[name]) for text in selected.requires
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("derive", "verify"):
        child = subparsers.add_parser(command)
        child.add_argument("--repo-root", type=Path, default=Path("."))
        child.add_argument("--editable-requirements", type=Path, required=True)
        if command == "derive":
            child.add_argument("--output", type=Path, required=True)
        else:
            child.add_argument("--wheelhouse", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "derive":
            requirements = write_build_requirements(
                args.repo_root, args.editable_requirements, args.output
            )
            print(
                "showcase-wheelhouse-build-requirements "
                f"count={len(requirements)} output={args.output}"
            )
        else:
            verify_wheelhouse(
                args.repo_root, args.editable_requirements, args.wheelhouse
            )
            print("showcase-wheelhouse-verified purpose=offline-editable-install")
    except (OSError, tomllib.TOMLDecodeError, WheelhouseRefusal) as exc:
        print(f"showcase-wheelhouse-refused: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
