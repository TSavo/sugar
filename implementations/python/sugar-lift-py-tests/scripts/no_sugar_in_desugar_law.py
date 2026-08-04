#!/usr/bin/env python3
"""R_no_sugar_in_desugar — sole-construction reduction floor.

AST nodes construct Sugar before reduction. A Sugar ``desugar`` method may
consume only the child Sugars it was constructed with; neither it nor any
same-module reduction helper it reaches may call ``.sugar()`` and reopen AST
construction.

The instrument scans every ``sugar/*.py`` module, starts at each class
``desugar`` method, follows calls to methods on that class and functions in the
same module, and reports every reachable ``.sugar()`` call. There is no
baseline or allowlist: every locus is red.
"""

from __future__ import annotations

# Not the board. This module measures its own named denominator; the sole
# authoritative Python corpus scoreboard is scripts/control_effect_recensus.py.
# See tests/test_one_authoritative_scoreboard.py.

from sugar_lift_py_tests.repo_root import sugar_lift_py_tests_package_root

SCOREBOARD_AUTHORITY = False

import argparse
import ast
import json
import sys
import tempfile
import traceback
from pathlib import Path
from typing import NamedTuple, Sequence


class SugarDuringDesugar(NamedTuple):
    path: str
    line: int
    column: int
    owner: str
    helper: str
    expression: str
    kind: str = "sugar-call-during-desugar"


class AuditorError(NamedTuple):
    path: str
    line: int
    column: int
    owner: str
    helper: str
    expression: str
    kind: str


Finding = SugarDuringDesugar | AuditorError


def _safe_unparse(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception as exc:  # noqa: BLE001 -- auditor containment
        return f"<unparse-failed:{type(exc).__name__}>"


def _rel_path(root: Path, path: Path) -> str:
    try:
        rel = path.resolve().relative_to(root.resolve())
    except ValueError:
        rel = Path(path.name)
    return f"{root.name}/{rel.as_posix()}"


def _calls_in(function: ast.FunctionDef | ast.AsyncFunctionDef):
    """Yield calls lexically owned by a reduction function.

    Local helpers are part of the enclosing reduction implementation. Walking
    their bodies conservatively keeps a nested ``reduce`` from becoming an
    unmeasured construction door.
    """

    class Calls(ast.NodeVisitor):
        def __init__(self) -> None:
            self.calls: list[ast.Call] = []

        def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
            self.calls.append(node)
            self.generic_visit(node)

        def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
            del node

    visitor = Calls()
    visitor.visit(function)
    return visitor.calls


def _scan_tree(tree: ast.Module, *, rel: str) -> list[Finding]:
    module_functions = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    findings: list[Finding] = []
    seen_loci: set[tuple[int, int]] = set()

    for class_node in (node for node in tree.body if isinstance(node, ast.ClassDef)):
        methods = {
            node.name: node
            for node in class_node.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        desugar = methods.get("desugar")
        if desugar is None:
            continue
        pending: list[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]] = [
            ("desugar", desugar)
        ]
        visited: set[tuple[str, str]] = set()
        while pending:
            helper_name, function = pending.pop()
            identity = (
                "method" if helper_name in methods else "function",
                helper_name,
            )
            if identity in visited:
                continue
            visited.add(identity)
            for call in _calls_in(function):
                if isinstance(call.func, ast.Attribute) and call.func.attr == "sugar":
                    locus = (call.lineno, call.col_offset)
                    if locus not in seen_loci:
                        seen_loci.add(locus)
                        findings.append(
                            SugarDuringDesugar(
                                path=rel,
                                line=call.lineno,
                                column=call.col_offset,
                                owner=class_node.name,
                                helper=helper_name,
                                expression=_safe_unparse(call),
                            )
                        )

                target = call.func
                if isinstance(target, ast.Name) and target.id in module_functions:
                    pending.append((target.id, module_functions[target.id]))
                elif (
                    isinstance(target, ast.Attribute)
                    and isinstance(target.value, ast.Name)
                    and target.value.id in {"self", "cls"}
                    and target.attr in methods
                ):
                    pending.append((target.attr, methods[target.attr]))
    return findings


def scan_file(path: Path, *, rel: str) -> list[Finding]:
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return [
            AuditorError(
                rel,
                0,
                0,
                "-",
                "-",
                f"{type(exc).__name__}: {exc}",
                "auditor-read-error",
            )
        ]
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [
            AuditorError(
                rel,
                int(exc.lineno or 0),
                int(exc.offset or 0),
                "-",
                "-",
                exc.msg,
                "auditor-parse-error",
            )
        ]
    return _scan_tree(tree, rel=rel)


def scan_roots(roots: Sequence[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for root in roots:
        if not root.is_dir():
            findings.append(
                AuditorError(
                    str(root), 0, 0, "-", "-", "not a directory", "auditor-root-error"
                )
            )
            continue
        for path in sorted(root.rglob("*.py")):
            if path.is_file():
                findings.extend(scan_file(path, rel=_rel_path(root, path)))
    return sorted(findings, key=lambda row: (row.path, row.line, row.column, row.owner))


def r_no_sugar_in_desugar(findings: Sequence[Finding]) -> int:
    return sum(1 for row in findings if row.kind == "sugar-call-during-desugar")


def r_auditor_errors(findings: Sequence[Finding]) -> int:
    return sum(1 for row in findings if row.kind.startswith("auditor-"))


def format_report(findings: Sequence[Finding]) -> str:
    lines = [
        f"R_no_sugar_in_desugar = {r_no_sugar_in_desugar(findings)}",
        f"auditor_errors = {r_auditor_errors(findings)}",
        "Replacement: construct child Sugars at the AST boundary and consume only those children during desugar.",
        "",
        "Loci:",
    ]
    for row in findings:
        lines.append(
            f"{row.path}:{row.line}:{row.column}:{row.kind}:"
            f"owner={row.owner}:helper={row.helper} — {row.expression}"
        )
    return "\n".join(lines)


def discrimination_self_test() -> bool:
    planted_source = """
class PlantedNestedHelperSugar:
    def desugar(self, ctx=None):
        def reduce(node):
            return node.sugar().desugar(ctx)
        return reduce(self.child)
"""
    clean_source = """
class ConstructedChildSugar:
    def desugar(self, ctx=None):
        return self.child.desugar(ctx)
"""
    with tempfile.TemporaryDirectory() as raw:
        root = Path(raw) / "sugar"
        root.mkdir()
        fixture = root / "fixture.py"
        fixture.write_text(planted_source, encoding="utf-8")
        planted = scan_roots((root,))
        fixture.write_text(clean_source, encoding="utf-8")
        clean = scan_roots((root,))
    return (
        r_no_sugar_in_desugar(planted) == 1
        and r_auditor_errors(planted) == 0
        and bool(planted)
        and clean == []
    )


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roots", nargs="*", type=Path)
    parser.add_argument("--self-test", action="store_true")
    try:
        args = parser.parse_args(argv)
        if args.self_test:
            ok = discrimination_self_test()
            print("NO-SUGAR-IN-DESUGAR SELF-TEST " + ("GREEN" if ok else "RED"))
            print(json.dumps({"instrument": "R_no_sugar_in_desugar", "self_test": ok}))
            return 0 if ok else 1
        roots = args.roots or [
            sugar_lift_py_tests_package_root()
            / "src"
            / "sugar_lift_py_tests"
            / "sugar"
        ]
        findings = scan_roots(roots)
    except Exception as exc:  # noqa: BLE001 -- process-level containment
        print(
            f"NO-SUGAR-IN-DESUGAR LAW ERROR: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        print(traceback.format_exc(), file=sys.stderr)
        print(
            json.dumps(
                {
                    "instrument": "R_no_sugar_in_desugar",
                    "ok": False,
                    "R_no_sugar_in_desugar": None,
                    "auditor_errors": 1,
                }
            )
        )
        return 2

    r = r_no_sugar_in_desugar(findings)
    errors = r_auditor_errors(findings)
    summary = {
        "instrument": "R_no_sugar_in_desugar",
        "ok": r == 0 and errors == 0,
        "R_no_sugar_in_desugar": r,
        "auditor_errors": errors,
    }
    if r or errors:
        print(
            f"NO-SUGAR-IN-DESUGAR LAW RED: {r} construction loci"
            + (f"; {errors} auditor errors" if errors else "")
        )
        print(format_report(findings))
        print(json.dumps(summary))
        return 1
    print("NO-SUGAR-IN-DESUGAR LAW GREEN: R_no_sugar_in_desugar = 0")
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
