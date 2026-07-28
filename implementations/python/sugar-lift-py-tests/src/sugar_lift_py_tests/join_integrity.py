"""Check laws on the synthetic merge tree, never on either tip alone."""

from __future__ import annotations

import argparse
import ast
import importlib.util
import subprocess
import tarfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


class JoinIntegrityError(RuntimeError):
    """The merged tree lost a law or a live production caller."""


@dataclass(frozen=True)
class DroppedCallerFinding:
    package: str
    path: str
    line: int
    symbol: str
    lost_reference_count: int

    def render(self) -> str:
        return (
            "test=dropped-caller "
            f"package={self.package} path={self.path}:{self.line} "
            f"symbol={self.symbol} ZERO_REFERENCES_AFTER "
            f"lostReferences={self.lost_reference_count}"
        )


@dataclass(frozen=True)
class SemanticFieldLossFinding:
    package: str
    path: str
    line: int
    constructor: str
    field: str
    introducing_tip: str

    def render(self) -> str:
        return (
            "test=semantic-field-propagation "
            f"package={self.package} path={self.path}:{self.line} "
            f"constructor={self.constructor} missingField={self.field} "
            f"introducedBy={self.introducing_tip}"
        )


JoinFinding = DroppedCallerFinding | SemanticFieldLossFinding


@dataclass(frozen=True)
class JoinIntegrityReport:
    base: str
    left: str
    right: str
    merged_tree: str
    adjacent_packages: tuple[str, ...]
    findings: tuple[JoinFinding, ...]

    @property
    def measured_packages(self) -> int:
        return len(self.adjacent_packages)

    def test_counts(self) -> Mapping[str, int]:
        return {
            "dropped-caller": sum(
                isinstance(item, DroppedCallerFinding) for item in self.findings
            ),
            "semantic-field-propagation": sum(
                isinstance(item, SemanticFieldLossFinding) for item in self.findings
            ),
        }

    def render(self) -> str:
        counts = self.test_counts()
        header = (
            f"join base={self.base} left={self.left} right={self.right} "
            f"mergedTree={self.merged_tree} measuredPackages={self.measured_packages} "
            f"droppedCaller={counts['dropped-caller']} "
            f"semanticFieldLoss={counts['semantic-field-propagation']}"
        )
        return "\n".join((header, *(item.render() for item in self.findings)))

    def require_clean(self) -> None:
        if self.findings:
            raise JoinIntegrityError(self.render())


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        text=True,
        capture_output=True,
        check=check,
    )


def _changed_packages(repo: Path, base: str, tip: str) -> set[str]:
    completed = _git(repo, "diff", "--name-only", base, tip)
    packages = set()
    for path in completed.stdout.splitlines():
        parts = path.split("/")
        if len(parts) >= 4 and parts[:2] == ["implementations", "python"]:
            packages.add(parts[2])
    return packages


def _merge_tree(repo: Path, base: str, left: str, right: str) -> str:
    completed = _git(
        repo,
        "merge-tree",
        "--write-tree",
        "--merge-base",
        base,
        left,
        right,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stdout + completed.stderr).strip()
        raise JoinIntegrityError(f"test=merged-tree conflict {detail}")
    tree = completed.stdout.splitlines()[0].strip()
    if not tree:
        raise JoinIntegrityError("test=merged-tree produced no tree coordinate")
    return tree


def _package_sources(repo: Path, revision: str, package: str) -> dict[str, str]:
    root = f"implementations/python/{package}"
    sources = {}
    process = subprocess.Popen(
        ["git", "archive", "--format=tar", revision, root],
        cwd=repo,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert process.stdout is not None
    with tarfile.open(fileobj=process.stdout, mode="r|") as archive:
        for member in archive:
            if not member.isfile() or not member.name.endswith(".py"):
                continue
            extracted = archive.extractfile(member)
            if extracted is None:
                continue
            try:
                sources[member.name] = extracted.read().decode("utf-8")
            except UnicodeDecodeError:
                continue
    stderr = process.communicate()[1]
    if process.returncode != 0:
        raise JoinIntegrityError(
            f"test=merged-tree archive failed revision={revision} "
            f"detail={stderr.decode(errors='replace').strip()}"
        )
    return sources


def _dataclass_fields(sources: Mapping[str, str]) -> dict[str, frozenset[str]]:
    fields: dict[str, set[str]] = {}
    for path, source in sources.items():
        tree = ast.parse(source, filename=path)
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            decorators = {
                decorator.id
                for decorator in node.decorator_list
                if isinstance(decorator, ast.Name)
            }
            if "dataclass" not in decorators:
                continue
            fields[node.name] = {
                statement.target.id
                for statement in node.body
                if isinstance(statement, ast.AnnAssign)
                and isinstance(statement.target, ast.Name)
            }
    return {name: frozenset(names) for name, names in fields.items()}


@dataclass(frozen=True)
class _CallSite:
    path: str
    line: int
    constructor: str
    keywords: frozenset[str]
    shape: str


def _calls(sources: Mapping[str, str]) -> tuple[_CallSite, ...]:
    calls = []
    for path, source in sources.items():
        tree = ast.parse(source, filename=path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            calls.append(
                _CallSite(
                    path=path,
                    line=node.lineno,
                    constructor=node.func.id,
                    keywords=frozenset(
                        keyword.arg for keyword in node.keywords if keyword.arg is not None
                    ),
                    shape=ast.dump(node, include_attributes=False),
                )
            )
    return tuple(calls)


def _semantic_losses(
    package: str,
    base: Mapping[str, str],
    left: Mapping[str, str],
    right: Mapping[str, str],
    merged: Mapping[str, str],
) -> tuple[SemanticFieldLossFinding, ...]:
    base_fields = _dataclass_fields(base)
    left_fields = _dataclass_fields(left)
    right_fields = _dataclass_fields(right)
    base_calls = Counter(call.shape for call in _calls(base))
    merged_calls = _calls(merged)
    findings = []
    for introducing_tip, introduced_fields, other_calls in (
        ("left", left_fields, _calls(right)),
        ("right", right_fields, _calls(left)),
    ):
        for constructor, fields in introduced_fields.items():
            added = fields - base_fields.get(constructor, frozenset())
            for field in added:
                candidates = Counter(call.shape for call in other_calls)
                candidates.subtract(base_calls)
                new_shapes = {shape for shape, count in candidates.items() if count > 0}
                for call in merged_calls:
                    if (
                        call.constructor == constructor
                        and call.shape in new_shapes
                        and field not in call.keywords
                    ):
                        findings.append(
                            SemanticFieldLossFinding(
                                package,
                                call.path,
                                call.line,
                                constructor,
                                field,
                                introducing_tip,
                            )
                        )
    return tuple(findings)


def check_git_join(
    repo: Path, *, base: str, left: str, right: str
) -> JoinIntegrityReport:
    """Measure adjacent Python packages on the actual synthesized merge tree."""
    repo = repo.resolve()
    adjacent = tuple(
        sorted(
            _changed_packages(repo, base, left)
            & _changed_packages(repo, base, right)
        )
    )
    merged_tree = _merge_tree(repo, base, left, right)
    findings: list[JoinFinding] = []
    detector_path = (
        Path(__file__).resolve().parents[2]
        / "scripts/private_orphan_transition.py"
    )
    spec = importlib.util.spec_from_file_location(
        "sugar_private_orphan_transition", detector_path
    )
    if spec is None or spec.loader is None:
        raise JoinIntegrityError(f"dropped-caller detector unavailable: {detector_path}")
    detector = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(detector)

    for package in adjacent:
        base_sources = _package_sources(repo, base, package)
        left_sources = _package_sources(repo, left, package)
        right_sources = _package_sources(repo, right, package)
        merged_sources = _package_sources(repo, merged_tree, package)
        for orphan in detector.compare_package_sources(
            package, base_sources, merged_sources
        ):
            findings.append(
                DroppedCallerFinding(
                    package=package,
                    path=orphan.definition.path,
                    line=orphan.definition.line,
                    symbol=orphan.definition.name,
                    lost_reference_count=len(orphan.lost_references),
                )
            )
        findings.extend(
            _semantic_losses(
                package,
                base_sources,
                left_sources,
                right_sources,
                merged_sources,
            )
        )
    return JoinIntegrityReport(
        base=base,
        left=left,
        right=right,
        merged_tree=merged_tree,
        adjacent_packages=adjacent,
        findings=tuple(findings),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="check laws on the synthesized merge of two adjacent tips"
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--base", required=True)
    parser.add_argument("--left", required=True)
    parser.add_argument("--right", required=True)
    args = parser.parse_args(argv)
    try:
        report = check_git_join(
            args.repo, base=args.base, left=args.left, right=args.right
        )
        print(report.render(), flush=True)
        report.require_clean()
    except JoinIntegrityError as error:
        print(str(error), flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
