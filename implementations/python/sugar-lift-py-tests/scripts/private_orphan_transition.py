#!/usr/bin/env python3
"""Find private definitions whose final package reference vanished.

This is deliberately a two-tree audit, not a dead-code census. Existing
zero-reference definitions are outside its population.
"""

from __future__ import annotations

import ast
import argparse
from collections import defaultdict
from pathlib import Path
import subprocess
import tarfile
from typing import Mapping, NamedTuple


class Definition(NamedTuple):
    package: str
    path: str
    line: int
    column: int
    name: str


class ReferenceSite(NamedTuple):
    path: str
    line: int
    column: int
    kind: str


class OrphanTransition(NamedTuple):
    definition: Definition
    lost_references: tuple[ReferenceSite, ...]


class PackageIndex(NamedTuple):
    definitions: Mapping[tuple[str, str], Definition]
    references: Mapping[str, tuple[ReferenceSite, ...]]


def _private_definition(name: str) -> bool:
    return name.startswith("_") and not (name.startswith("__") and name.endswith("__"))


def _string_members(node: ast.AST) -> tuple[ast.Constant, ...]:
    if not isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return ()
    return tuple(
        item
        for item in node.elts
        if isinstance(item, ast.Constant) and isinstance(item.value, str)
    )


def _index_package(package: str, sources: Mapping[str, str]) -> PackageIndex:
    definitions: dict[tuple[str, str], Definition] = {}
    references: defaultdict[str, list[ReferenceSite]] = defaultdict(list)

    for path, source in sorted(sources.items()):
        _index_source(package, path, source, definitions, references)

    return PackageIndex(
        definitions=definitions,
        references={name: tuple(sites) for name, sites in references.items()},
    )


def _index_source(
    package: str,
    path: str,
    source: str,
    definitions: dict[tuple[str, str], Definition],
    references: defaultdict[str, list[ReferenceSite]],
) -> None:
    tree = ast.parse(source, filename=path)
    for statement in tree.body:
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if "/src/" in f"/{path}" and _private_definition(statement.name):
                definitions[(path, statement.name)] = Definition(
                    package,
                    path,
                    statement.lineno,
                    statement.col_offset,
                    statement.name,
                )
                for decorator in statement.decorator_list:
                    references[statement.name].append(
                        ReferenceSite(
                            path,
                            decorator.lineno,
                            decorator.col_offset,
                            "decorator-registration",
                        )
                    )
        if isinstance(statement, (ast.Assign, ast.AnnAssign)):
            targets = (
                statement.targets
                if isinstance(statement, ast.Assign)
                else [statement.target]
            )
            if any(
                isinstance(target, ast.Name) and target.id == "__all__"
                for target in targets
            ):
                for member in _string_members(statement.value):
                    references[member.value].append(
                        ReferenceSite(path, member.lineno, member.col_offset, "__all__")
                    )

    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            references[node.id].append(
                ReferenceSite(path, node.lineno, node.col_offset, "name")
            )
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load):
            references[node.attr].append(
                ReferenceSite(path, node.lineno, node.col_offset, "attribute")
            )
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                references[alias.name].append(
                    ReferenceSite(path, node.lineno, node.col_offset, "import-reexport")
                )
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in {"getattr", "setattr", "hasattr", "delattr"}
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and isinstance(node.args[1].value, str)
        ):
            member = node.args[1]
            references[member.value].append(
                ReferenceSite(
                    path,
                    member.lineno,
                    member.col_offset,
                    "dynamic-attribute",
                )
            )


def compare_package_sources(
    package: str,
    before_sources: Mapping[str, str],
    after_sources: Mapping[str, str],
) -> tuple[OrphanTransition, ...]:
    before = _index_package(package, before_sources)
    after = _index_package(package, after_sources)
    findings: list[OrphanTransition] = []

    for key, definition in sorted(after.definitions.items()):
        if key not in before.definitions:
            continue
        before_references = before.references.get(definition.name, ())
        after_references = after.references.get(definition.name, ())
        if before_references and not after_references:
            findings.append(
                OrphanTransition(
                    definition=definition,
                    lost_references=before_references,
                )
            )
    return tuple(findings)


def _package_index_at_revision(
    repo: Path, revision: str, distribution: str
) -> PackageIndex:
    pathspec = f"implementations/python/{distribution}"
    process = subprocess.Popen(
        ["git", "archive", "--format=tar", revision, pathspec],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    definitions: dict[tuple[str, str], Definition] = {}
    references: defaultdict[str, list[ReferenceSite]] = defaultdict(list)
    assert process.stdout is not None
    with tarfile.open(fileobj=process.stdout, mode="r|") as archive:
        for member in archive:
            if not member.isfile() or not member.name.endswith(".py"):
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            try:
                source = extracted.read().decode("utf-8")
            except UnicodeDecodeError:
                continue
            _index_source(distribution, member.name, source, definitions, references)
    stderr = process.communicate()[1]
    if process.returncode != 0:
        raise RuntimeError(
            f"git archive failed for {revision}: "
            f"{stderr.decode(errors='replace').strip()}"
        )
    return PackageIndex(
        definitions=definitions,
        references={name: tuple(sites) for name, sites in references.items()},
    )


def _changed_python_paths(
    repo: Path, before_revision: str, after_revision: str
) -> dict[str, tuple[str, ...]]:
    completed = subprocess.run(
        [
            "git",
            "diff",
            "--name-only",
            before_revision,
            after_revision,
            "--",
            "implementations/python",
        ],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"git diff failed for {before_revision}..{after_revision}: "
            f"{completed.stderr.strip()}"
        )
    changed: defaultdict[str, list[str]] = defaultdict(list)
    for line in completed.stdout.splitlines():
        parts = Path(line).parts
        if (
            len(parts) >= 4
            and parts[:2] == ("implementations", "python")
            and line.endswith(".py")
        ):
            changed[parts[2]].append(line)
    surviving: dict[str, tuple[str, ...]] = {}
    for distribution, paths in sorted(changed.items()):
        package_path = f"implementations/python/{distribution}"
        if all(
            subprocess.run(
                ["git", "cat-file", "-e", f"{revision}:{package_path}"],
                cwd=repo,
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            ).returncode
            == 0
            for revision in (before_revision, after_revision)
        ):
            surviving[distribution] = tuple(sorted(paths))
    return surviving


def _source_at_revision(repo: Path, revision: str, path: str) -> str | None:
    completed = subprocess.run(
        ["git", "show", f"{revision}:{path}"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return None
    return completed.stdout


def compare_git_revisions(
    repo: Path, before_revision: str, after_revision: str
) -> tuple[int, tuple[OrphanTransition, ...]]:
    changed = _changed_python_paths(repo, before_revision, after_revision)
    findings: list[OrphanTransition] = []
    for package, changed_paths in changed.items():
        before_changed_sources = {
            path: source
            for path in changed_paths
            if (source := _source_at_revision(repo, before_revision, path)) is not None
        }
        before_changed = _index_package(package, before_changed_sources)
        after = _package_index_at_revision(repo, after_revision, package)
        for key, definition in sorted(after.definitions.items()):
            lost_references = before_changed.references.get(definition.name, ())
            if not lost_references or after.references.get(definition.name, ()):
                continue
            before_definition_source = _source_at_revision(
                repo, before_revision, definition.path
            )
            if before_definition_source is None:
                continue
            before_definition = _index_package(
                package, {definition.path: before_definition_source}
            )
            if key in before_definition.definitions:
                findings.append(OrphanTransition(definition, lost_references))
    return len(changed), tuple(findings)


def _render(packages: int, findings: tuple[OrphanTransition, ...]) -> str:
    lines: list[str] = []
    for finding in findings:
        definition = finding.definition
        lines.append(
            f"{definition.path}:{definition.line}:{definition.column}: "
            f"private orphan transition: {definition.name} "
            f"(package {definition.package})"
        )
        for site in finding.lost_references:
            lines.append(
                f"  lost reference {site.path}:{site.line}:{site.column} "
                f"[{site.kind}]"
            )
    lines.append(f"package_transitions={packages} orphan_transitions={len(findings)}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--before", required=True)
    parser.add_argument("--after", required=True)
    args = parser.parse_args(argv)
    packages, findings = compare_git_revisions(
        args.repo.resolve(), args.before, args.after
    )
    print(_render(packages, findings))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
