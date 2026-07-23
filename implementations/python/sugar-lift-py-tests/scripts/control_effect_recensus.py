#!/usr/bin/env python3
"""Measure pandas control/effect construction without hiding blocked sites."""

from __future__ import annotations

import argparse
import ast
from collections import Counter, defaultdict
import json
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Any, Callable

from sugar_lift_py_tests.audit_only import collect_construction_panic


class FileTimeout(Exception):
    pass


def _timeout(_signum, _frame):
    raise FileTimeout("per-file construction timeout")


def _coordinate(node) -> tuple[str, int, int]:
    span = node.line_col_span()
    return node.kind, span.start_line, span.start_col


def _dotted(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _import_bindings(tree: ast.Module) -> dict[str, str]:
    bindings: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                bindings.setdefault(
                    alias.asname or alias.name.split(".")[0], alias.name
                )
        elif isinstance(node, ast.ImportFrom):
            module = "." * node.level + (node.module or "")
            for alias in node.names:
                if alias.name != "*":
                    bindings.setdefault(
                        alias.asname or alias.name, f"{module}.{alias.name}"
                    )
    return bindings


def _resolved_call_name(node: ast.Call, imports: dict[str, str]) -> str | None:
    raw = _dotted(node.func)
    if raw is None:
        return None
    head, dot, tail = raw.partition(".")
    origin = imports.get(head)
    return origin + (dot + tail if dot else "") if origin else raw


_EXIT_NODES = (ast.Raise, ast.Return, ast.Break, ast.Continue, ast.Assert, ast.Try)
if hasattr(ast, "TryStar"):
    _EXIT_NODES = (*_EXIT_NODES, ast.TryStar)


def _branch_has_exit(statements: list[ast.stmt]) -> bool:
    pending: list[ast.AST] = list(statements)
    while pending:
        node = pending.pop()
        if isinstance(node, _EXIT_NODES):
            return True
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
        ):
            continue
        pending.extend(ast.iter_child_nodes(node))
    return False


def _labels(node: ast.AST, imports: dict[str, str]) -> tuple[str, ...]:
    labels: list[str] = []
    if isinstance(node, ast.Try):
        labels.append("Try")
        if node.finalbody:
            labels.append("finally")
    elif hasattr(ast, "TryStar") and isinstance(node, ast.TryStar):
        labels.append("TryStar")
        if node.finalbody:
            labels.append("finally")
    elif isinstance(node, ast.Raise):
        labels.extend(
            ("Raise", "bare-reraise" if node.exc is None else "explicit-raise")
        )
    elif isinstance(node, ast.Return):
        labels.append("Return")
    elif isinstance(node, ast.Break):
        labels.append("Break")
    elif isinstance(node, ast.Continue):
        labels.append("Continue")
    elif isinstance(node, ast.Assert):
        labels.append("Assert")
    elif isinstance(node, ast.If) and (
        _branch_has_exit(node.body) or _branch_has_exit(node.orelse)
    ):
        labels.append("guarded-exit-join")
    elif isinstance(node, ast.Call):
        target = _resolved_call_name(node, imports)
        if target in {"warnings.warn", "warnings.warn_explicit"}:
            labels.append("warning-effect-call")
    return tuple(labels)


def _git_commit(root: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()


def _collect_file_construction(
    label: str, walker: Callable[[], Any]
) -> tuple[Any | None, dict[str, Any] | None]:
    value, gap = collect_construction_panic(label, walker)
    if gap is None:
        return value, None
    return None, {
        "file": label,
        "type": "ConstructionPanic",
        "message": gap.message,
        "gap": gap.info,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("corpus", type=Path)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()

    from sugar_source_tree.panic import SugarNotWritten
    from sugar_source_tree.reporter import CollectingReporter
    from sugar_source_tree.tree import SourceFile

    files = sorted(args.corpus.rglob("*.py"))
    signal.signal(signal.SIGALRM, _timeout)
    counts: dict[str, Counter] = defaultdict(Counter)
    mechanisms: dict[str, Counter] = defaultdict(Counter)
    families = Counter()
    defects = []
    construction_panics: list[dict[str, Any]] = []
    floor_rows: list[dict[str, Any]] = []
    files_completed = 0
    functions_total = 0
    functions_clean = 0
    started = time.time()

    for index, path in enumerate(files, 1):
        relative = str(path.relative_to(args.corpus))
        try:
            signal.alarm(args.timeout)
            source = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(path))
            imports = _import_bindings(tree)
            syntax = {}
            for node in ast.walk(tree):
                labels = _labels(node, imports)
                if labels:
                    syntax[(type(node).__name__, node.lineno, node.col_offset)] = labels

            def construct_file():
                nonlocal functions_total, functions_clean
                reporter = CollectingReporter()
                source_file = SourceFile.from_path(str(path), reporter=reporter)
                for function in source_file.functions():
                    functions_total += 1
                    try:
                        function.sugar()
                        functions_clean += 1
                    except SugarNotWritten:
                        pass
                return reporter

            reporter, panic_row = _collect_file_construction(relative, construct_file)
            if panic_row is not None:
                construction_panics.append(panic_row)
                families["ConstructionPanic"] += 1
                print(
                    f"[{index}/{len(files)}] CONSTRUCTION-PANIC {relative}: "
                    f"{panic_row['message']}",
                    flush=True,
                )
                floor_rows.append(
                    {
                        "file": f"{args.corpus.name}/{relative}",
                        "category": "construction-panic",
                    }
                )
                continue
            assert reporter is not None

            registered = {_coordinate(node) for node in reporter.registered}
            present = {_coordinate(node) for node in reporter.present}
            gaps = {_coordinate(node): panic for node, panic in reporter.gaps}
            for kind, _line, _col in gaps:
                families[kind] += 1

            for (kind, line, col), labels in syntax.items():
                key = (kind, line, col)
                if key in gaps:
                    status = "direct-loud"
                    mechanism = type(gaps[key]).__name__
                elif key in present:
                    status = "built"
                    mechanism = None
                elif key in registered:
                    status = "blocked-descendant"
                    mechanism = None
                else:
                    status = "unregistered"
                    mechanism = None
                for label in labels:
                    counts[label][status] += 1
                    if mechanism is not None:
                        mechanisms[label][mechanism] += 1
            files_completed += 1
            floor_rows.append(
                {"file": f"{args.corpus.name}/{relative}", "category": "completed"}
            )
            if index % 100 == 0:
                direct = sum(row["direct-loud"] for row in counts.values())
                print(
                    f"[{index}/{len(files)}] completed={files_completed} "
                    f"direct-labelled={direct}",
                    flush=True,
                )
        except Exception as exc:
            defects.append(
                {"file": relative, "type": type(exc).__name__, "message": str(exc)}
            )
            print(
                f"[{index}/{len(files)}] DEFECT {type(exc).__name__} "
                f"{relative}: {exc}",
                flush=True,
            )
            floor_rows.append(
                {
                    "file": f"{args.corpus.name}/{relative}",
                    "category": "unmeasurable",
                    "reason": type(exc).__name__,
                }
            )
        finally:
            signal.alarm(0)

    result = {
        "kind": "control-effect-construction-recensus",
        "commit": _git_commit(args.repo),
        "corpus": str(args.corpus),
        "filesTotal": len(files),
        "filesCompleted": files_completed,
        "defects": defects,
        "constructionPanics": construction_panics,
        "R_construction_panics": len(construction_panics),
        "functionsTotal": functions_total,
        "functionsConstructClean": functions_clean,
        "constructs": {
            label: dict(sorted(statuses.items()))
            for label, statuses in sorted(counts.items())
        },
        "directGapMechanisms": {
            label: dict(sorted(rows.items(), key=lambda item: (-item[1], item[0])))
            for label, rows in sorted(mechanisms.items())
        },
        "R": sum(families.values()),
        "families": dict(
            sorted(families.items(), key=lambda item: (-item[1], item[0]))
        ),
        "elapsedSeconds": time.time() - started,
        "python": sys.version,
    }
    from pandas_floor_summary import floor_summary

    file_names = sorted(
        f"{args.corpus.name}/{path.relative_to(args.corpus)}" for path in files
    )
    result["floorSummary"] = floor_summary(
        floor="control-effect",
        files=file_names,
        rows=floor_rows,
        totals={
            "R_control_effect": result["R"],
            "constructionPanics": len(construction_panics),
            "unmeasurable": len(defects),
        },
        measured=(
            not defects
            and not construction_panics
            and files_completed == len(files)
        ),
        unmeasurable_reasons=(
            (["construction-panic"] if construction_panics else [])
            + (["defect"] if defects else [])
        ),
    )
    rendered = json.dumps(result, indent=2)
    print("=== RESULT JSON ===", flush=True)
    print(rendered, flush=True)
    if args.json is not None:
        args.json.write_text(rendered + "\n")
    return 1 if defects or construction_panics or files_completed != len(files) else 0


if __name__ == "__main__":
    raise SystemExit(main())
