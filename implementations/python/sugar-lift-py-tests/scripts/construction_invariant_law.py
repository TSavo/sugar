#!/usr/bin/env python3
"""Closed construction-invariant auditor.

This is a pre-review floor, not a semantic recognizer.  It detects structural
shapes which have repeatedly admitted fabricated authority or a second
construction path.  Every row names the replacement law; unknown source is an
auditor error, never a zero.
"""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Iterable


SELF_HASH = "SELF-HASHING-AS-AUTHORITY"
NAME_GATE = "NAME-SPELLING-OVERLOAD-GATE"
SECOND_PATH = "SECOND-CONSTRUCTION-PATH"
NON_EXHAUSTIVE = "NON-EXHAUSTIVE-VARIANT-COVERAGE"
FABRICATED = "FABRICATED-COMPLETION-FALLBACK"

REQUIRED_FIX = {
    SELF_HASH: (
        "re-resolve against the authenticated artifact/graph and require "
        "byte-identical equality; a self-hash is integrity, not authority"
    ),
    NAME_GATE: (
        "resolve through an authenticated binding/contract coordinate; remove "
        "vendor, spelling, manifest, and overload-name dispatch"
    ),
    SECOND_PATH: (
        "delete the private evaluator and consume already-constructed Sugar/"
        "call-frame/receiver-state testimony from the sole construction door"
    ),
    NON_EXHAUSTIVE: (
        "use a closed typed union or an executable running-grammar coverage "
        "audit, with every unknown variant returning a typed-loud outcome"
    ),
    FABRICATED: (
        "preserve the opaque/symbolic face as typed-loud; never synthesize a "
        "default value, None completion, benign catch-all, or dropped filter"
    ),
}


@dataclass(frozen=True, order=True)
class Finding:
    path: str
    line: int
    column: int
    violation_class: str
    observed: str

    @property
    def required_fix(self) -> str:
        return REQUIRED_FIX[self.violation_class]

    def to_value(self) -> dict[str, object]:
        return {
            "path": self.path,
            "line": self.line,
            "column": self.column,
            "class": self.violation_class,
            "observed": self.observed,
            "requiredFix": self.required_fix,
        }


_HASH_CALLS = {
    "cid_of_json",
    "canonical_json_cid",
    "blake3_512_of",
    "jcs_cid",
    "hash",
    "sha256",
}
_AUTHORITY_WORDS = (
    "authenticated",
    "resolved",
    "contractref",
    "contract_ref",
    "constructed",
    "authority",
)
_REVALIDATION_WORDS = (
    "revalidate",
    "reconstruct",
    "re_resolve",
    "resolve_import_binding",
    "authenticate",
    "from_graph",
)
_FORBIDDEN_SPELLING = re.compile(
    r"(^|[.:/_-])(pytest|pandas|numpy|pyarrow|matplotlib|contextlib)([.:/_-]|$)",
    re.IGNORECASE,
)
_FORBIDDEN_API_NAMES = {
    "row_for_spelling",
    "default_community_manifest",
    "manifest_membrane",
    "community_context_managers",
    "overload_name",
}
_FLOOR_MAKERS = {
    "FloorValue",
    "TermValue",
    "StringValue",
    "NoneValue",
    "TupleValue",
    "DictValue",
    "ObjectValue",
    "ObjectField",
    "GuardedValue",
}
_AST_STMT_NAMES = {
    "FunctionDef",
    "AsyncFunctionDef",
    "ClassDef",
    "Return",
    "Delete",
    "Assign",
    "TypeAlias",
    "AugAssign",
    "AnnAssign",
    "For",
    "AsyncFor",
    "While",
    "If",
    "With",
    "AsyncWith",
    "Match",
    "Raise",
    "Try",
    "TryStar",
    "Assert",
    "Import",
    "ImportFrom",
    "Global",
    "Nonlocal",
    "Expr",
    "Pass",
    "Break",
    "Continue",
}


def _name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _name(node.value)
        return f"{base}.{node.attr}" if base else node.attr
    return ""


def _call_name(node: ast.AST) -> str:
    return _name(node.func) if isinstance(node, ast.Call) else ""


def _depends_on(node: ast.AST, names: set[str]) -> bool:
    return any(isinstance(child, ast.Name) and child.id in names for child in ast.walk(node))


def _finding(path: str, node: ast.AST, kind: str, observed: str) -> Finding:
    return Finding(path, getattr(node, "lineno", 1), getattr(node, "col_offset", 0), kind, observed)


def _function_parameters(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    args = node.args
    return {
        item.arg
        for item in (
            *args.posonlyargs,
            *args.args,
            *args.kwonlyargs,
            *(() if args.vararg is None else (args.vararg,)),
            *(() if args.kwarg is None else (args.kwarg,)),
        )
    }


def _has_revalidation(function: ast.AST) -> bool:
    for node in ast.walk(function):
        if isinstance(node, ast.Call):
            call = _call_name(node).lower().split(".")[-1]
            if call in _REVALIDATION_WORDS or call.startswith(("revalidate_", "reconstruct_", "resolve_")):
                return True
        if isinstance(node, ast.Compare) and any(
            isinstance(op, (ast.Eq, ast.NotEq)) for op in node.ops
        ):
            return True
    return False


def _self_hash_findings(tree: ast.Module, path: str) -> list[Finding]:
    findings: list[Finding] = []
    for function in (
        node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ):
        parameters = _function_parameters(function)
        hashes: dict[str, ast.Call] = {}
        for node in ast.walk(function):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            if not isinstance(value, ast.Call):
                continue
            call_tail = _call_name(value).split(".")[-1]
            if call_tail not in _HASH_CALLS or not _depends_on(value, parameters):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
            for target in targets:
                if isinstance(target, ast.Name):
                    hashes[target.id] = value
        if not hashes or _has_revalidation(function):
            continue
        for node in ast.walk(function):
            if not isinstance(node, ast.Return) or not isinstance(node.value, ast.Call):
                continue
            sink = node.value
            sink_name = _call_name(sink).lower().replace(".", "")
            uses_hash = _depends_on(sink, set(hashes))
            uses_input = _depends_on(sink, parameters)
            has_cid_slot = any("cid" in keyword.arg.lower() for keyword in sink.keywords if keyword.arg)
            authority_sink = any(word in sink_name for word in _AUTHORITY_WORDS)
            if uses_hash and uses_input and (has_cid_slot or authority_sink):
                findings.append(
                    _finding(
                        path,
                        node,
                        SELF_HASH,
                        "caller-controlled preimage is self-hashed into an authority-bearing return",
                    )
                )
                break
    return findings


def _is_gate_context(node: ast.Constant, parents: dict[ast.AST, ast.AST]) -> bool:
    parent = parents.get(node)
    if isinstance(parent, (ast.Compare, ast.Subscript, ast.Dict)):
        return True
    if isinstance(parent, ast.Call):
        return _call_name(parent).endswith((".get", ".lookup", ".resolve", ".dispatch"))
    if isinstance(parent, (ast.Tuple, ast.List, ast.Set)):
        grand = parents.get(parent)
        return isinstance(grand, (ast.Compare, ast.Dict, ast.Call))
    return False


def _name_gate_findings(tree: ast.Module, path: str) -> list[Finding]:
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    findings: list[Finding] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in _FORBIDDEN_API_NAMES:
            findings.append(_finding(path, node, NAME_GATE, f"spelling authority API `{node.attr}`"))
        elif isinstance(node, ast.Name) and node.id in _FORBIDDEN_API_NAMES:
            findings.append(_finding(path, node, NAME_GATE, f"spelling authority name `{node.id}`"))
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and (_FORBIDDEN_SPELLING.search(node.value) or "overload" in node.value.lower())
            and _is_gate_context(node, parents)
        ):
            findings.append(_finding(path, node, NAME_GATE, f"semantic gate literal {node.value!r}"))
    return findings


def _ast_test_names(function: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(function):
        if not isinstance(node, ast.Call) or _call_name(node) != "isinstance" or len(node.args) < 2:
            continue
        for candidate in ast.walk(node.args[1]):
            if isinstance(candidate, ast.Attribute) and _name(candidate.value) == "ast":
                names.add(candidate.attr)
    return names


def _second_path_findings(tree: ast.Module, path: str) -> list[Finding]:
    if path.endswith(("sugar_source_tree/nodes.py", "sugar_lift_python_source/lifter.py")):
        return []
    findings: list[Finding] = []
    for function in (
        node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ):
        ast_tests = _ast_test_names(function)
        makers = {
            _call_name(node).split(".")[-1]
            for node in ast.walk(function)
            if isinstance(node, ast.Call)
        } & _FLOOR_MAKERS
        if ast_tests and makers:
            findings.append(
                _finding(
                    path,
                    function,
                    SECOND_PATH,
                    f"private AST evaluator branches on {sorted(ast_tests)} and manufactures {sorted(makers)}",
                )
            )
    return findings


def _has_stmt_coverage_audit(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if (
            node.func.attr == "__subclasses__"
            and isinstance(node.func.value, ast.Attribute)
            and _name(node.func.value) == "ast.stmt"
        ):
            return True
    return False


def _terminal_loud(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    if not function.body:
        return False
    last = function.body[-1]
    if isinstance(last, ast.Raise):
        return True
    if isinstance(last, ast.Return) and isinstance(last.value, ast.Call):
        name = _call_name(last.value).lower()
        return any(word in name for word in ("gap", "unsupported", "incomplete", "error"))
    return False


def _declares_statement_transfer(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Separate grammar transfers from helpers that incidentally inspect AST nodes."""

    for argument in (*function.args.posonlyargs, *function.args.args, *function.args.kwonlyargs):
        annotation = argument.annotation
        if annotation is None:
            continue
        rendered = ast.unparse(annotation)
        if "ast.stmt" in rendered or rendered in {"stmt", "Statement"}:
            return True
    return False


def _non_exhaustive_findings(tree: ast.Module, path: str) -> list[Finding]:
    coverage = _has_stmt_coverage_audit(tree)
    findings: list[Finding] = []
    for function in (
        node for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ):
        if not _declares_statement_transfer(function):
            continue
        stmt_tests = _ast_test_names(function) & _AST_STMT_NAMES
        if len(stmt_tests) >= 2 and (not coverage or not _terminal_loud(function)):
            findings.append(
                _finding(
                    path,
                    function,
                    NON_EXHAUSTIVE,
                    f"statement transfer handles {sorted(stmt_tests)} without both grammar audit and loud unknown arm",
                )
            )
    return findings


def _fabricated_findings(tree: ast.Module, path: str) -> list[Finding]:
    findings: list[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node).split(".")[-1]
        if name in {"Complete", "Completed"} and any(
            isinstance(argument, ast.Constant) and argument.value is None
            for argument in (*node.args, *(keyword.value for keyword in node.keywords))
        ):
            findings.append(
                _finding(path, node, FABRICATED, "completion manufactures None as a fallback value")
            )
        if name in {"unwrap_or_default", "get_or_default"}:
            findings.append(_finding(path, node, FABRICATED, f"benign default fallback `{name}`"))
    return findings


def scan_python_source(source: str, path: str) -> list[Finding]:
    tree = ast.parse(source, filename=path)
    findings = [
        *_self_hash_findings(tree, path),
        *_name_gate_findings(tree, path),
        *_second_path_findings(tree, path),
        *_non_exhaustive_findings(tree, path),
        *_fabricated_findings(tree, path),
    ]
    return sorted(set(findings))


_RUST_CATCH_ALL = re.compile(r"\b_\s*=>")
_RUST_BENIGN_ARM = re.compile(
    r"\b_\s*=>[^,;\n]*(?:Default::default|Outcome::Complete|Complete\s*\(\s*None|"
    r"Completed\s*\(\s*None|Ok\s*\(\s*None)"
)


def scan_rust_source(source: str, path: str) -> list[Finding]:
    findings: list[Finding] = []
    lines = source.splitlines()
    for index, line in enumerate(lines, 1):
        match = _RUST_CATCH_ALL.search(line)
        # Rust utility matches legitimately use `_ => None/false` for typed
        # projections.  The invariant concerns a semantic outcome/default,
        # so require the catch-all itself to manufacture that outcome.
        if match and _RUST_BENIGN_ARM.search(line):
            findings.append(Finding(path, index, match.start(), NON_EXHAUSTIVE, "Rust catch-all variant arm silently accepts an unknown variant"))
            findings.append(Finding(path, index, match.start(), FABRICATED, "Rust catch-all manufactures a benign completion/default"))
    return sorted(set(findings))


def _default_roots(repo: Path) -> tuple[Path, ...]:
    return (
        repo / "implementations/python/sugar-source-tree/src",
        repo / "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar",
        repo / "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/context_manager_contract.py",
        repo / "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/context_manager_resolution.py",
        repo / "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/call_contract_resolution.py",
        repo / "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/import_binding.py",
        repo / "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/lift_rpc.py",
        repo / "implementations/python/sugar-lift-python-source/src",
        repo / "implementations/rust/sugar-linker/src",
        repo / "implementations/rust/sugar-compiler/src",
        repo / "implementations/rust/sugar-proof-envelope/src",
        repo / "implementations/rust/sugar-ir-types/src",
    )


def _source_files(roots: Iterable[Path]) -> list[Path]:
    files: set[Path] = set()
    for root in roots:
        if root.is_file() and root.suffix in {".py", ".rs"}:
            files.add(root)
        elif root.is_dir():
            files.update(path for path in root.rglob("*") if path.suffix in {".py", ".rs"})
    return sorted(files)


def scan_roots(roots: Iterable[Path], *, repo: Path | None = None) -> tuple[list[Finding], list[str]]:
    base = (repo or Path.cwd()).resolve()
    findings: list[Finding] = []
    errors: list[str] = []
    for path in _source_files(roots):
        label = str(path.resolve().relative_to(base)) if path.resolve().is_relative_to(base) else str(path)
        try:
            source = path.read_text(encoding="utf-8")
            findings.extend(scan_python_source(source, label) if path.suffix == ".py" else scan_rust_source(source, label))
        except (OSError, UnicodeError, SyntaxError) as exc:
            errors.append(f"{label}: {type(exc).__name__}: {exc}")
    return sorted(set(findings)), sorted(errors)


def format_report(findings: Iterable[Finding], errors: Iterable[str] = ()) -> str:
    rows = list(findings)
    error_rows = list(errors)
    lines = []
    for finding in rows:
        lines.append(
            f"{finding.path}:{finding.line}:{finding.column}: {finding.violation_class}: "
            f"{finding.observed}; required fix: {finding.required_fix}"
        )
    lines.extend(f"AUDITOR-ERROR: {error}" for error in error_rows)
    by_class = {kind: sum(row.violation_class == kind for row in rows) for kind in REQUIRED_FIX}
    lines.append(f"R_construction_invariant_violations = {len(rows)}")
    for kind, count in by_class.items():
        lines.append(f"R_{kind.lower().replace('-', '_')} = {count}")
    lines.append(f"R_auditor_errors = {len(error_rows)}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("roots", nargs="*", type=Path)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    repo = args.repo.resolve()
    roots = tuple(path.resolve() for path in args.roots) or _default_roots(repo)
    findings, errors = scan_roots(roots, repo=repo)
    print(format_report(findings, errors))
    if args.json is not None:
        args.json.write_text(
            json.dumps(
                {
                    "kind": "construction-invariant-audit",
                    "R": len(findings),
                    "auditorErrors": errors,
                    "findings": [finding.to_value() for finding in findings],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    return 1 if findings or errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
