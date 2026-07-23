#!/usr/bin/env python3
"""Measure pandas comprehension/iteration construction without hiding residue."""

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


class FileTimeout(Exception):
    pass


def _timeout(_signum, _frame):
    raise FileTimeout("per-file construction timeout")


def _coordinate(node) -> tuple[str, int, int]:
    span = node.line_col_span()
    return node.kind, span.start_line, span.start_col


def _syntax_coordinate(node: ast.AST, lines: list[str]) -> tuple[str, int, int]:
    line = node.lineno
    byte_col = node.col_offset
    prefix = lines[line - 1].encode("utf-8")[:byte_col]
    return type(node).__name__, line, len(prefix.decode("utf-8"))


def _contains(node: ast.AST, kinds: tuple[type[ast.AST], ...]) -> bool:
    return any(
        isinstance(child, kinds) for child in ast.walk(node) if child is not node
    )


def _contains_or_is(node: ast.AST, kinds: tuple[type[ast.AST], ...]) -> bool:
    return any(isinstance(child, kinds) for child in ast.walk(node))


def _iteration_evidence(iterables: list[ast.expr]) -> str:
    """Classify syntax-authenticated finite iteration vs a protocol obligation.

    Only list/tuple displays carry their complete element sequence in this AST.
    A call spelled ``range`` is deliberately not authenticated here: it may be
    rebound, and the construction pass owns that lexical decision.
    """
    if all(isinstance(iterable, (ast.List, ast.Tuple)) for iterable in iterables):
        return "literal-finite-iteration-evidence"
    return "iterator-protocol-and-exhaustion-required"


def _comprehension_shape(node: ast.AST) -> tuple[str, tuple[str, ...]]:
    generators = node.generators
    roots = [generator.iter for generator in generators]
    if isinstance(node, ast.DictComp):
        roots.extend((node.key, node.value))
    else:
        roots.append(node.elt)

    flags = []
    if any(generator.is_async for generator in generators):
        flags.append("async-clause")
    if any(generator.ifs for generator in generators):
        flags.append("filter")
    if len(generators) > 1:
        flags.append("multiple-generators")
    if any(not isinstance(generator.target, ast.Name) for generator in generators):
        flags.append("non-name-target")
    if any(_contains_or_is(root, (ast.NamedExpr,)) for root in roots):
        flags.append("named-expression")
    comprehension_kinds = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
    if any(_contains_or_is(root, comprehension_kinds) for root in roots):
        flags.append("nested-comprehension")
    if not flags:
        flags.append("single-simple-coordinate")

    priority = (
        "async-clause",
        "filter",
        "multiple-generators",
        "non-name-target",
        "named-expression",
        "nested-comprehension",
        "single-simple-coordinate",
    )
    primary = next(label for label in priority if label in flags)
    flags.append(_iteration_evidence([generator.iter for generator in generators]))
    return primary, tuple(flags)


def _for_shape(node: ast.For | ast.AsyncFor) -> tuple[str, tuple[str, ...]]:
    flags = []
    if isinstance(node, ast.AsyncFor):
        flags.append("async-iteration")
    if node.orelse:
        flags.append("else")
    if not isinstance(node.target, ast.Name):
        flags.append("non-name-target")
    if _contains(node, (ast.Break, ast.Continue)):
        flags.append("loop-control")

    binding_kinds = (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.NamedExpr)
    has_binding = any(
        isinstance(descendant, binding_kinds)
        for statement in node.body
        for descendant in ast.walk(statement)
    )
    has_fact = any(
        not any(
            isinstance(descendant, binding_kinds) for descendant in ast.walk(statement)
        )
        for statement in node.body
    )
    if has_binding and has_fact:
        flags.append("mixed-accumulator-facts")
    elif has_binding:
        flags.append("fold-body")
    else:
        flags.append("fact-body")

    priority = (
        "async-iteration",
        "loop-control",
        "else",
        "non-name-target",
        "mixed-accumulator-facts",
        "fold-body",
        "fact-body",
    )
    primary = next(label for label in priority if label in flags)
    flags.append(_iteration_evidence([node.iter]))
    return primary, tuple(flags)


def _shape(node: ast.AST) -> tuple[str, tuple[str, ...]]:
    if isinstance(node, (ast.For, ast.AsyncFor)):
        return _for_shape(node)
    return _comprehension_shape(node)


def _git_commit(root: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()


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
    primary_shapes: dict[str, dict[str, Counter]] = defaultdict(
        lambda: defaultdict(Counter)
    )
    shape_axes: dict[str, dict[str, Counter]] = defaultdict(
        lambda: defaultdict(Counter)
    )
    direct_mechanisms: dict[str, Counter] = defaultdict(Counter)
    defects = []
    files_completed = 0
    started = time.time()
    target_kinds = (
        ast.ListComp,
        ast.SetComp,
        ast.DictComp,
        ast.GeneratorExp,
        ast.For,
        ast.AsyncFor,
    )

    for index, path in enumerate(files, 1):
        relative = str(path.relative_to(args.corpus))
        try:
            signal.alarm(args.timeout)
            source = path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(source, filename=str(path))
            lines = source.splitlines()
            syntax = {}
            for node in ast.walk(tree):
                if isinstance(node, target_kinds):
                    syntax[_syntax_coordinate(node, lines)] = _shape(node)

            reporter = CollectingReporter()
            source_file = SourceFile.from_path(str(path), reporter=reporter)
            for function in source_file.functions():
                try:
                    function.sugar()
                except SugarNotWritten:
                    pass

            registered = {_coordinate(node) for node in reporter.registered}
            present = {_coordinate(node) for node in reporter.present}
            gaps = {_coordinate(node): panic for node, panic in reporter.gaps}
            for key, (primary, axes) in syntax.items():
                family = key[0]
                if key in gaps:
                    status = "direct-loud"
                    direct_mechanisms[family][type(gaps[key]).__name__] += 1
                elif key in present:
                    status = "built"
                elif key in registered:
                    status = "blocked-descendant"
                else:
                    status = "unregistered"
                counts[family][status] += 1
                primary_shapes[family][primary][status] += 1
                for axis in axes:
                    shape_axes[family][axis][status] += 1

            files_completed += 1
            if index % 100 == 0:
                direct = sum(row["direct-loud"] for row in counts.values())
                print(
                    f"[{index}/{len(files)}] completed={files_completed} "
                    f"direct-family={direct}",
                    flush=True,
                )
        except BaseException as exc:
            if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                raise
            defects.append(
                {"file": relative, "type": type(exc).__name__, "message": str(exc)}
            )
            print(
                f"[{index}/{len(files)}] DEFECT {type(exc).__name__} "
                f"{relative}: {exc}",
                flush=True,
            )
        finally:
            signal.alarm(0)

    def render_nested(rows):
        return {
            family: {
                shape: dict(sorted(statuses.items()))
                for shape, statuses in sorted(shapes.items())
            }
            for family, shapes in sorted(rows.items())
        }

    result = {
        "kind": "comprehension-iteration-construction-recensus",
        "commit": _git_commit(args.repo),
        "corpus": str(args.corpus),
        "filesTotal": len(files),
        "filesCompleted": files_completed,
        "defects": defects,
        "families": {
            family: dict(sorted(statuses.items()))
            for family, statuses in sorted(counts.items())
        },
        "primaryShapes": render_nested(primary_shapes),
        "overlappingShapeAxes": render_nested(shape_axes),
        "directGapMechanisms": {
            family: dict(sorted(rows.items(), key=lambda item: (-item[1], item[0])))
            for family, rows in sorted(direct_mechanisms.items())
        },
        "elapsedSeconds": time.time() - started,
        "python": sys.version,
    }
    rendered = json.dumps(result, indent=2)
    print("=== RESULT JSON ===", flush=True)
    print(rendered, flush=True)
    if args.json is not None:
        args.json.write_text(rendered + "\n")
    return 1 if defects or files_completed != len(files) else 0


if __name__ == "__main__":
    raise SystemExit(main())
