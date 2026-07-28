"""Check laws on the synthetic merge tree, never on either tip alone."""

from __future__ import annotations

import argparse
import ast
import importlib.util
import itertools
import json
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


@dataclass(frozen=True)
class TextualConflictFinding:
    path: str
    hunk_header: str
    marker_count: int

    def render(self) -> str:
        return (
            "test=textual-conflict "
            f"path={self.path} hunk={self.hunk_header!r} "
            f"markerCount={self.marker_count}"
        )


@dataclass(frozen=True)
class NamedLawLossFinding:
    path: str
    law: str

    def render(self) -> str:
        return f"test=named-law-survival path={self.path} missingLaw={self.law}"


@dataclass(frozen=True)
class StackedBaseFinding:
    pull_request: int
    base_ref: str
    parent_pull_request: int

    def render(self) -> str:
        return (
            "test=stacked-base-retarget "
            f"pr={self.pull_request} baseRef={self.base_ref} "
            f"openParentPr={self.parent_pull_request}"
        )


JoinFinding = (
    DroppedCallerFinding
    | SemanticFieldLossFinding
    | TextualConflictFinding
    | NamedLawLossFinding
    | StackedBaseFinding
)


@dataclass(frozen=True)
class JoinIntegrityReport:
    base: str
    left: str
    right: str
    merged_tree: str | None
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
            "textual-conflict": sum(
                isinstance(item, TextualConflictFinding) for item in self.findings
            ),
            "named-law-survival": sum(
                isinstance(item, NamedLawLossFinding) for item in self.findings
            ),
            "stacked-base-retarget": sum(
                isinstance(item, StackedBaseFinding) for item in self.findings
            ),
        }

    def render(self) -> str:
        counts = self.test_counts()
        header = (
            f"join base={self.base} left={self.left} right={self.right} "
            f"mergedTreeStatus={'constructed' if self.merged_tree else 'conflicted'} "
            f"measuredPackages={self.measured_packages} "
            f"droppedCaller={counts['dropped-caller']} "
            f"semanticFieldLoss={counts['semantic-field-propagation']} "
            f"textualConflict={counts['textual-conflict']} "
            f"namedLawLoss={counts['named-law-survival']} "
            f"stackedBase={counts['stacked-base-retarget']}"
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


def _parse_conflicts(output: str) -> tuple[TextualConflictFinding, ...]:
    findings = []
    sections = output.split("changed in both\n")[1:]
    for section in sections:
        lines = section.splitlines()
        path = "<unknown>"
        for line in lines[:4]:
            fields = line.split()
            if line.startswith("  base ") and len(fields) >= 4:
                path = fields[-1]
                break
        hunk_starts = [
            index for index, line in enumerate(lines) if line.startswith("@@")
        ]
        for offset, start in enumerate(hunk_starts):
            end = (
                hunk_starts[offset + 1] if offset + 1 < len(hunk_starts) else len(lines)
            )
            hunk = lines[start:end]
            marker_count = sum(
                marker in line
                for line in hunk
                for marker in ("<<<<<<<", "=======", ">>>>>>>")
            )
            if marker_count:
                findings.append(TextualConflictFinding(path, hunk[0], marker_count))
    return tuple(findings)


def _merge_tree(
    repo: Path, base: str, left: str, right: str
) -> tuple[str | None, tuple[TextualConflictFinding, ...]]:
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
        legacy = _git(repo, "merge-tree", base, left, right)
        conflicts = _parse_conflicts(legacy.stdout)
        if not conflicts:
            detail = (completed.stdout + completed.stderr).strip()
            raise JoinIntegrityError(f"test=merged-tree unparsed-conflict {detail}")
        return None, conflicts
    tree = completed.stdout.splitlines()[0].strip()
    if not tree:
        raise JoinIntegrityError("test=merged-tree produced no tree coordinate")
    return tree, ()


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
                        keyword.arg
                        for keyword in node.keywords
                        if keyword.arg is not None
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


_ATTRIBUTION_TEST = (
    "implementations/python/sugar-lift-py-tests/tests/"
    "test_no_call_body_attribution.py"
)
_ATTRIBUTION_SOURCE = (
    "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/"
    "no_call_body_attribution.py"
)
_REQUIRED_ATTRIBUTION_LAWS = (
    "test_escaped_construction_panic_remains_a_separate_loud_axis",
    "test_silent_completion_stays_a_separate_loud_discrepancy",
    "test_population_selection_never_reads_manager_target_symbol",
)


def _named_law_losses(
    package: str, sources: Mapping[str, str]
) -> tuple[NamedLawLossFinding, ...]:
    if package != "sugar-lift-py-tests":
        return ()
    findings = []
    test_source = sources.get(_ATTRIBUTION_TEST)
    if test_source is None:
        findings.append(NamedLawLossFinding(_ATTRIBUTION_TEST, "test-file-present"))
    else:
        names = {
            node.name
            for node in ast.parse(test_source, filename=_ATTRIBUTION_TEST).body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        findings.extend(
            NamedLawLossFinding(_ATTRIBUTION_TEST, law)
            for law in _REQUIRED_ATTRIBUTION_LAWS
            if law not in names
        )
    source = sources.get(_ATTRIBUTION_SOURCE)
    denominator_sum = None
    if source is not None:
        for node in ast.parse(source, filename=_ATTRIBUTION_SOURCE).body:
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and (
                (
                    isinstance(node, ast.Assign)
                    and any(
                        isinstance(t, ast.Name) and t.id == "FAMILY_DENOMINATORS"
                        for t in node.targets
                    )
                )
                or (
                    isinstance(node, ast.AnnAssign)
                    and isinstance(node.target, ast.Name)
                    and node.target.id == "FAMILY_DENOMINATORS"
                )
            ):
                value = node.value
                if isinstance(value, ast.Dict) and all(
                    isinstance(item, ast.Constant) and isinstance(item.value, int)
                    for item in value.values
                ):
                    denominator_sum = sum(item.value for item in value.values)
                break
    if denominator_sum != 1008:
        findings.append(
            NamedLawLossFinding(_ATTRIBUTION_SOURCE, "FAMILY_DENOMINATORS.sum==1008")
        )
    return tuple(findings)


def check_git_join(
    repo: Path, *, base: str, left: str, right: str
) -> JoinIntegrityReport:
    """Measure adjacent Python packages on the actual synthesized merge tree."""
    repo = repo.resolve()
    adjacent = tuple(
        sorted(
            _changed_packages(repo, base, left) & _changed_packages(repo, base, right)
        )
    )
    if not adjacent:
        conflicts = _parse_conflicts(_git(repo, "merge-tree", base, left, right).stdout)
        return JoinIntegrityReport(
            base,
            left,
            right,
            "textual-merge-clean" if not conflicts else None,
            (),
            conflicts,
        )
    merged_tree, conflicts = _merge_tree(repo, base, left, right)
    if conflicts:
        return JoinIntegrityReport(base, left, right, None, adjacent, conflicts)
    assert merged_tree is not None
    findings: list[JoinFinding] = []
    detector_path = (
        Path(__file__).resolve().parents[2] / "scripts/private_orphan_transition.py"
    )
    spec = importlib.util.spec_from_file_location(
        "sugar_private_orphan_transition", detector_path
    )
    if spec is None or spec.loader is None:
        raise JoinIntegrityError(
            f"dropped-caller detector unavailable: {detector_path}"
        )
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
        findings.extend(_named_law_losses(package, merged_sources))
    return JoinIntegrityReport(
        base=base,
        left=left,
        right=right,
        merged_tree=merged_tree,
        adjacent_packages=adjacent,
        findings=tuple(findings),
    )


@dataclass(frozen=True)
class OpenPullRequest:
    number: int
    head_ref: str
    base_ref: str
    files: frozenset[str]


def _open_pull_requests(repo: Path) -> tuple[OpenPullRequest, ...]:
    limit = 10_000
    completed = subprocess.run(
        [
            "gh",
            "pr",
            "list",
            "--state",
            "open",
            "--limit",
            str(limit),
            "--json",
            "number,headRefName,baseRefName,files",
        ],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )
    rows = json.loads(completed.stdout)
    if len(rows) == limit:
        raise JoinIntegrityError(
            f"coverage=incomplete reason=open-pr-limit limit={limit}"
        )
    return tuple(
        OpenPullRequest(
            row["number"],
            row["headRefName"],
            row["baseRefName"],
            frozenset(item["path"] for item in row["files"]),
        )
        for row in rows
    )


def _adjacent_pairs(
    pulls: tuple[OpenPullRequest, ...],
) -> tuple[tuple[OpenPullRequest, OpenPullRequest], ...]:
    return tuple(
        (left, right)
        for left, right in itertools.combinations(pulls, 2)
        if left.files & right.files
    )


def check_open_pr_joins(repo: Path) -> tuple[JoinIntegrityReport, ...]:
    pulls = _open_pull_requests(repo)
    parents = {pull.head_ref: pull for pull in pulls}
    stacked = tuple(
        StackedBaseFinding(pull.number, pull.base_ref, parents[pull.base_ref].number)
        for pull in pulls
        if pull.base_ref in parents
    )
    if stacked:
        raise JoinIntegrityError("\n".join(item.render() for item in stacked))
    pairs = _adjacent_pairs(pulls)
    print(
        f"openPrs={len(pulls)} commonFilePairs={len(pairs)} droppedPairs=0 coverage=complete",
        flush=True,
    )
    reports = []
    for left, right in pairs:
        left_ref = f"refs/join-audit/open-{left.number}"
        right_ref = f"refs/join-audit/open-{right.number}"
        _git(
            repo,
            "fetch",
            "--force",
            "origin",
            f"refs/pull/{left.number}/head:{left_ref}",
        )
        _git(
            repo,
            "fetch",
            "--force",
            "origin",
            f"refs/pull/{right.number}/head:{right_ref}",
        )
        base = _git(repo, "merge-base", left_ref, right_ref).stdout.strip()
        reports.append(check_git_join(repo, base=base, left=left_ref, right=right_ref))
    return tuple(reports)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="check laws on the synthesized merge of two adjacent tips"
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--base")
    parser.add_argument("--left")
    parser.add_argument("--right")
    parser.add_argument("--open-prs", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.open_prs:
            reports = check_open_pr_joins(args.repo)
            for report in reports:
                print(report.render(), flush=True)
                report.require_clean()
        else:
            if not all((args.base, args.left, args.right)):
                parser.error(
                    "--base, --left, and --right are required without --open-prs"
                )
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
