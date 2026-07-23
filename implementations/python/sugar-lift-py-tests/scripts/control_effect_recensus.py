#!/usr/bin/env python3
"""Measure pandas control/effect construction without hiding blocked sites."""

from __future__ import annotations

import argparse
import ast
from collections import Counter, defaultdict
import json
from pathlib import Path
import os
import subprocess
import sys
import time
from typing import Any, Callable

from sugar_lift_py_tests.audit_only import collect_construction_panic


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


def _production_source_file(
    path,
    *,
    root,
    reporter,
    distribution_index=None,
    artifact_graph_cache=None,
):
    from _production_source_file import production_source_file

    return production_source_file(
        path,
        root=root,
        reporter=reporter,
        distribution_index=distribution_index,
        artifact_graph_cache=artifact_graph_cache,
    )


def _measure_file(path: Path, *, root: Path, relative: str) -> dict[str, Any]:
    from sugar_source_tree.panic import SugarNotWritten
    from sugar_source_tree.reporter import CollectingReporter

    import importlib.metadata

    package_distributions = importlib.metadata.packages_distributions()
    distribution_index = {
        package: importlib.metadata.distribution(distributions[0])
        for package, distributions in package_distributions.items()
        if len(distributions) == 1
    }
    source = path.read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(source, filename=str(path))
    imports = _import_bindings(tree)
    syntax: dict[tuple[str, int, int], tuple[str, ...]] = {}
    for node in ast.walk(tree):
        labels = _labels(node, imports)
        if labels:
            syntax[(type(node).__name__, node.lineno, node.col_offset)] = labels

    functions_total = 0
    functions_clean = 0
    source_calls_total = 0
    source_call_preconstruction: Counter[str] = Counter()

    def construct_file():
        nonlocal functions_total, functions_clean, source_calls_total
        reporter = CollectingReporter()
        source_file = _production_source_file(
            path,
            root=root,
            reporter=reporter,
            distribution_index=distribution_index,
            artifact_graph_cache={},
        )
        from sugar_lift_py_tests.source_call_resolution import (
            SourceCallPreconstructionRefV1,
        )
        from sugar_source_tree.nodes import Call

        source_calls_total = sum(
            1 for node in source_file.nodes() if isinstance(node, Call)
        )
        for row in source_file.unit.construction_context.source_call_resolutions.values():
            source_call_preconstruction[
                (
                    f"source-visible-{row.dispatch_kind}"
                    if isinstance(row, SourceCallPreconstructionRefV1)
                    else row.kind
                )
            ] += 1
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
        return {
            "category": "construction-panic",
            "panic": panic_row,
            "functionsTotal": functions_total,
            "functionsClean": functions_clean,
            "sourceCallsTotal": source_calls_total,
            "sourceCallPreconstruction": dict(source_call_preconstruction),
        }
    assert reporter is not None
    registered = {_coordinate(node) for node in reporter.registered}
    present = {_coordinate(node) for node in reporter.present}
    gaps = {_coordinate(node): panic for node, panic in reporter.gaps}
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    mechanisms: dict[str, Counter[str]] = defaultdict(Counter)
    families: Counter[str] = Counter(kind for kind, _line, _col in gaps)
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
    return {
        "category": "completed",
        "functionsTotal": functions_total,
        "functionsClean": functions_clean,
        "sourceCallsTotal": source_calls_total,
        "sourceCallPreconstruction": dict(source_call_preconstruction),
        "counts": {label: dict(values) for label, values in counts.items()},
        "mechanisms": {label: dict(values) for label, values in mechanisms.items()},
        "families": dict(families),
    }


def _child_main(path: Path, *, root: Path, relative: str) -> int:
    try:
        row = _measure_file(path, root=root, relative=relative)
    except Exception as error:
        row = {
            "category": "backend-defect",
            "defect": {
                "file": relative,
                "type": type(error).__name__,
                "message": str(error),
            },
        }
    print(json.dumps({"kind": "control-effect-row", "result": row}, sort_keys=True))
    return 0


def _parse_child(stdout: str) -> dict[str, Any] | None:
    for line in reversed(stdout.splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("kind") == "control-effect-row":
            result = value.get("result")
            return result if isinstance(result, dict) else None
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("corpus", type=Path, nargs="?")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--commit")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--checkpoint-jsonl", type=Path)
    parser.add_argument("--child-file", type=Path)
    parser.add_argument("--child-root", type=Path)
    parser.add_argument("--child-rel")
    args = parser.parse_args()
    if args.child_file or args.child_root or args.child_rel:
        if args.child_file is None or args.child_root is None or args.child_rel is None:
            parser.error("child mode requires --child-file, --child-root, and --child-rel")
        return _child_main(
            args.child_file, root=args.child_root, relative=args.child_rel
        )
    if args.corpus is None:
        parser.error("corpus is required in parent mode")
    if args.timeout > 30:
        parser.error("--timeout may not exceed 30 seconds")
    files = sorted(args.corpus.rglob("*.py"))
    if not files:
        parser.error("corpus contains no Python files")
    counts: dict[str, Counter] = defaultdict(Counter)
    mechanisms: dict[str, Counter] = defaultdict(Counter)
    families = Counter()
    defects: list[dict[str, Any]] = []
    construction_panics: list[dict[str, Any]] = []
    floor_rows: list[dict[str, Any]] = []
    files_completed = 0
    functions_total = 0
    functions_clean = 0
    source_calls_total = 0
    source_call_preconstruction = Counter()
    started = time.time()
    script = Path(__file__).resolve()
    by_file = {
        f"{args.corpus.name}/{path.relative_to(args.corpus).as_posix()}": path
        for path in files
    }

    def run_file(file: str) -> dict[str, Any]:
        path = by_file[file]
        relative = path.relative_to(args.corpus).as_posix()
        env = dict(os.environ)
        env["PYTHONFAULTHANDLER"] = "1"
        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--child-file",
                    str(path),
                    "--child-root",
                    str(args.corpus),
                    "--child-rel",
                    relative,
                ],
                text=True,
                capture_output=True,
                timeout=args.timeout,
                env=env,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {"category": "timeout", "timeoutSeconds": args.timeout}
        if completed.returncode < 0:
            return {
                "category": "native-crash",
                "returncode": completed.returncode,
                "signal": -completed.returncode,
            }
        testimony = _parse_child(completed.stdout)
        if completed.returncode != 0 or testimony is None:
            return {
                "category": "backend-defect",
                "defect": {
                    "file": relative,
                    "type": "ChildProtocolError",
                    "message": completed.stderr[-2000:] or "child emitted no testimony",
                },
            }
        return testimony

    if args.checkpoint_jsonl is not None:
        from pandas_census_checkpoint import Checkpoint, run_pending

        checkpoint = Checkpoint(
            floor="control-effect",
            files=tuple(by_file),
            path=args.checkpoint_jsonl,
        )
        journal_rows = run_pending(
            checkpoint, run_file, workers=max(1, args.workers)
        )
        measured_rows = [(row["file"], row["result"]) for row in journal_rows]
    else:
        measured_rows = [(file, run_file(file)) for file in sorted(by_file)]

    for index, (file, raw) in enumerate(measured_rows, start=1):
        row = dict(raw)
        category = str(row.get("category"))
        floor_rows.append({"file": file, "category": category})
        functions_total += int(row.get("functionsTotal") or 0)
        functions_clean += int(row.get("functionsClean") or 0)
        source_calls_total += int(row.get("sourceCallsTotal") or 0)
        source_call_preconstruction.update(row.get("sourceCallPreconstruction") or {})
        for label, values in (row.get("counts") or {}).items():
            counts[str(label)].update(values)
        for label, values in (row.get("mechanisms") or {}).items():
            mechanisms[str(label)].update(values)
        families.update(row.get("families") or {})
        if category == "completed":
            files_completed += 1
        elif category == "construction-panic":
            panic = row.get("panic")
            if isinstance(panic, dict):
                construction_panics.append(panic)
            families["ConstructionPanic"] += 1
        else:
            defect = row.get("defect")
            defects.append(
                dict(defect)
                if isinstance(defect, dict)
                else {"file": file, "type": category, "message": category}
            )
        if index % 25 == 0:
            print(f"measured {index}/{len(files)} files", flush=True)

    result = {
        "kind": "control-effect-construction-recensus",
        "commit": args.commit or _git_commit(args.repo),
        "corpus": str(args.corpus),
        "filesTotal": len(files),
        "filesCompleted": files_completed,
        "defects": defects,
        "constructionPanics": construction_panics,
        "R_construction_panics": len(construction_panics),
        "functionsTotal": functions_total,
        "functionsConstructClean": functions_clean,
        "sourceCallsTotal": source_calls_total,
        "sourceCallPreconstruction": {
            **dict(sorted(source_call_preconstruction.items())),
            "unclassifiedLocalOrDynamic": source_calls_total
            - sum(source_call_preconstruction.values()),
        },
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

    file_names = sorted(by_file)
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
            not defects and not construction_panics and files_completed == len(files)
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
