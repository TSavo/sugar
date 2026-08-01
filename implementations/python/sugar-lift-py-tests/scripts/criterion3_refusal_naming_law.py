#!/usr/bin/env python3
"""Criterion 3 — refusals must name the artifact they cannot see.

CLASS NAME
    CRITERION-3 REFUSAL NAMING

DEFINITION (the half we state but never measured)
    Source-visible behaviour CONSTRUCTS; source-undecidable behaviour is
    specifically refused, NAMING the artifact it cannot see.

    Two axes:

    1. R_refusals_naming_nothing
       A refusal (``SugarNotWritten``, ``construction_panic_gap``,
       ``BackendDefect``, kin) whose ``observed`` uses undecidable-class
       language without naming a concrete invisible artifact (receiver type,
       missing field, coordinate, semantics variant, …). Those are unfinished
       construction wearing a typed label.

    2. R_refusals_over_decidable_source  — OPEN (not measured)
       A refusal where perfect machinery over source-visible code could still
       have decided. Final only when perfect source machinery could not.
       Static AST cannot soundly recover "source was visible at this site"
       without false greens. Retirement path (names the object that retires
       this open axis): a construction-required
       ``RefusalDecidability`` enum on every named refusal:

         - ``MissingMachinery(source_visible: tuple[Artifact, ...])``
         - ``PerfectSourceStillUndecidable(exhausted: tuple[Artifact, ...])``

       Only the second is a valid final refusal. When that type is required at
       the one door, delete any auditor that tried to guess from prose.

ENFORCEMENT LADDER
    Rung: **auditor** (static recognition over product refusal mints).

    Why not higher yet:
    - Type system: free ``observed: str`` on SourceTreePanic / ConstructionGap
      admits any prose; cannot require an Artifact noun in a string.
    - Construction door: no sealed ``NamedRefusal(artifact, decidability)``
      yet — optional keyword strings remain open Python.
    - Panic at contact: a green path never re-reads the refusal prose.

    Retirement (axis 1): typed ``observed: Artifact`` (or required non-empty
    artifact field alongside undecidability) makes nameless undecidable
    prose unconstructible; delete this auditor.

    Retirement (axis 2): see RefusalDecidability above — open until then.

Not the board. Sole Python corpus scoreboard remains
scripts/control_effect_recensus.py.
"""

from __future__ import annotations

# Not the board.
SCOREBOARD_AUTHORITY = False

import argparse
import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

NAMING_NOTHING = "REFUSAL-NAMING-NOTHING"
# Axis 2 is reported as open, never faked as a live count.
OPEN_AXIS = "REFUSAL-OVER-DECIDABLE-SOURCE-OPEN"

REQUIRED_FIX = {
    NAMING_NOTHING: (
        "name the invisible artifact in observed (f-string the receiver/"
        "key/semantics type, missing field, or coordinate); undecidable-"
        "class prose alone is unfinished construction wearing a label"
    ),
}

# Calls that mint accounted named refusals / construction gaps.
_REFUSAL_FUNCS = frozenset(
    {
        "SugarNotWritten",
        "VocabularyMissing",
        "UnattributableRefusal",
        "BackendDefect",
        "WithConstructionGap",
        "ContextManagerResolutionConstructionGap",
        "OpaqueSourceCallResolutionGap",
        "RuntimeSelectedContextManager",
        "SubstituteNotWritten",
        "ConstructedValueTestimonyNotWritten",
        "UnsupportedContextManagerSemantics",
        "UnsupportedWithBindingTarget",
        "AsyncContextManagerUnsupported",
        "construction_panic_gap",
        "vocabulary_missing",
        "backend_defect",
        "ConstructionGap",
    }
)

_REFUSAL_NAME_MARKERS = (
    "NotWritten",
    "Gap",
    "Refusal",
    "Missing",
    "Defect",
    "Unsupported",
)

# Undecidable-class language in observed prose.
_UNDECIDABLE = re.compile(
    r"undecid|not source-decid|cannot decide|opaque|"
    r"unknown (?:runtime|type|value|semantics|variant)|"
    r"runtime-selected|undischarged",
    re.IGNORECASE,
)

# Concrete artifact signals inside a constant observed string.
_CAMEL_TYPE = re.compile(r"\b[A-Z][a-z0-9]+(?:[A-Z][a-zA-Z0-9]+)+\b")
_PATHISH = re.compile(r"[A-Za-z0-9_./-]+\.py\b|[A-Za-z_]+\.[A-Za-z_]+|:\d+")
_IDENTITY_FIELD = re.compile(
    r"\b(?:exception_type_coordinate|exception_type_mro|occurrence_id|"
    r"occurrence|type_coordinate|coordinate_cid|authenticated_identity|"
    r"producer_node_owner|demand_cid|member_cid|semantics)\b"
)


@dataclass(frozen=True, order=True)
class Finding:
    path: str
    line: int
    column: int
    violation_class: str
    call_name: str
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
            "call": self.call_name,
            "observed": self.observed,
            "requiredFix": self.required_fix,
        }


def _call_name(func: ast.AST) -> str | None:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _is_refusal_call_name(name: str | None) -> bool:
    if name is None:
        return False
    if name in _REFUSAL_FUNCS:
        return True
    return any(marker in name for marker in _REFUSAL_NAME_MARKERS)


def _observed_text_constant_parts(expr: ast.AST) -> str:
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        return expr.value
    if isinstance(expr, ast.JoinedStr):
        parts: list[str] = []
        for value in expr.values:
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                parts.append(value.value)
        return "".join(parts)
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add):
        return _observed_text_constant_parts(expr.left) + _observed_text_constant_parts(
            expr.right
        )
    return ""


def _is_undecidable_class(expr: ast.AST) -> bool:
    text = _observed_text_constant_parts(expr)
    if text and _UNDECIDABLE.search(text):
        return True
    # Pure non-constant observed with no constant undecidable marker: not this axis.
    return False


def _names_artifact(expr: ast.AST) -> bool:
    """True when observed names a concrete invisible artifact, not only a class."""
    if isinstance(expr, ast.JoinedStr):
        # f-string always interpolates something — that something is the artifact.
        return any(isinstance(v, ast.FormattedValue) for v in expr.values)
    if isinstance(expr, ast.Call):
        return True
    if isinstance(expr, ast.BinOp) and isinstance(expr.op, ast.Add):
        return _names_artifact(expr.left) or _names_artifact(expr.right)
    if isinstance(expr, (ast.Attribute, ast.Name)):
        return True
    if isinstance(expr, ast.Constant) and isinstance(expr.value, str):
        s = expr.value
        if _CAMEL_TYPE.search(s):
            return True
        if _PATHISH.search(s):
            return True
        if _IDENTITY_FIELD.search(s):
            return True
        if "[" in s and "]" in s:
            return True
        return False
    return False


def _kw_observed(call: ast.Call) -> ast.AST | None:
    for kw in call.keywords:
        if kw.arg == "observed":
            return kw.value
    return None


class _Visitor(ast.NodeVisitor):
    def __init__(self, path: str) -> None:
        self.path = path
        self.findings: list[Finding] = []
        self._seen: set[tuple[int, int, str]] = set()

    def _consider(self, call: ast.Call) -> None:
        name = _call_name(call.func)
        if not _is_refusal_call_name(name):
            return
        observed = _kw_observed(call)
        if observed is None:
            return
        if not _is_undecidable_class(observed):
            return
        if _names_artifact(observed):
            return
        key = (getattr(call, "lineno", 0) or 0, getattr(call, "col_offset", 0) or 0, name or "")
        if key in self._seen:
            return
        self._seen.add(key)
        text = _observed_text_constant_parts(observed) or ast.dump(observed)
        self.findings.append(
            Finding(
                path=self.path,
                line=key[0],
                column=key[1],
                violation_class=NAMING_NOTHING,
                call_name=name or "?",
                observed=text,
            )
        )

    def visit_Raise(self, node: ast.Raise) -> None:
        if isinstance(node.exc, ast.Call):
            self._consider(node.exc)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        # Direct mint helpers (construction_panic_gap, backend_defect, …)
        # that do not always appear under raise.
        name = _call_name(node.func)
        if name in {
            "construction_panic_gap",
            "vocabulary_missing",
            "backend_defect",
            "ConstructionGap",
        }:
            self._consider(node)
        self.generic_visit(node)


def scan_python_source(source: str, path: str) -> list[Finding]:
    tree = ast.parse(source, filename=path)
    visitor = _Visitor(path)
    visitor.visit(tree)
    return sorted(set(visitor.findings))


def _default_roots(repo: Path) -> tuple[Path, ...]:
    return (
        repo / "implementations/python/sugar-lift-py-tests/src",
        repo / "implementations/python/sugar-source-tree/src",
        repo / "implementations/python/sugar-lift-python-source/src",
    )


def _source_files(roots: Iterable[Path]) -> list[Path]:
    files: set[Path] = set()
    for root in roots:
        if root.is_file() and root.suffix == ".py":
            files.add(root)
        elif root.is_dir():
            for path in root.rglob("*.py"):
                if "__pycache__" in path.parts:
                    continue
                files.add(path)
    return sorted(files)


def scan_roots(
    roots: Iterable[Path] | None = None, *, repo: Path | None = None
) -> tuple[list[Finding], list[str]]:
    base = (repo or Path.cwd()).resolve()
    scan_paths = tuple(roots) if roots is not None else _default_roots(base)
    findings: list[Finding] = []
    errors: list[str] = []
    self_path = Path(__file__).resolve()
    for path in _source_files(scan_paths):
        if path.resolve() == self_path:
            continue
        label = (
            str(path.resolve().relative_to(base))
            if path.resolve().is_relative_to(base)
            else str(path)
        )
        try:
            source = path.read_text(encoding="utf-8")
            findings.extend(scan_python_source(source, label))
        except (OSError, UnicodeError, SyntaxError) as exc:
            errors.append(f"{label}: {type(exc).__name__}: {exc}")
    return sorted(set(findings)), sorted(errors)


def format_report(findings: Iterable[Finding], errors: Iterable[str] = ()) -> str:
    rows = list(findings)
    error_rows = list(errors)
    lines = [
        "CRITERION-3 REFUSAL NAMING AUDIT",
        "rung=auditor",
        "retire_when="
        "typed observed:Artifact + RefusalDecidability one-door make both axes "
        "unrepresentable; then delete this auditor",
        "axis2=OPEN: R_refusals_over_decidable_source not measured "
        "(static scan cannot soundly recover source-visibility; see module doc)",
        "",
    ]
    for finding in rows:
        lines.append(
            f"{finding.path}:{finding.line}:{finding.column}: {finding.violation_class}: "
            f"{finding.call_name}: {finding.observed!r}; required fix: {finding.required_fix}"
        )
    lines.extend(f"AUDITOR-ERROR: {error}" for error in error_rows)
    lines.append(f"R_refusals_naming_nothing = {len(rows)}")
    lines.append("R_refusals_over_decidable_source = OPEN")
    lines.append(f"R_auditor_errors = {len(error_rows)}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roots", nargs="*", type=Path)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    repo = args.repo.resolve()
    roots = tuple(path.resolve() for path in args.roots) or None
    findings, errors = scan_roots(roots, repo=repo)
    print(format_report(findings, errors))
    if args.json is not None:
        args.json.write_text(
            json.dumps(
                {
                    "kind": "criterion3-refusal-naming-audit",
                    "class": "CRITERION-3 REFUSAL NAMING",
                    "rung": "auditor",
                    "R_refusals_naming_nothing": len(findings),
                    "R_refusals_over_decidable_source": "OPEN",
                    "auditorErrors": errors,
                    "findings": [finding.to_value() for finding in findings],
                    "openAxis": {
                        "name": "R_refusals_over_decidable_source",
                        "why_open": (
                            "static AST cannot soundly decide that perfect "
                            "machinery over source-visible code could have "
                            "constructed instead of refused"
                        ),
                        "retirement": (
                            "RefusalDecidability::{MissingMachinery, "
                            "PerfectSourceStillUndecidable} required at the "
                            "named-refusal door"
                        ),
                    },
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
