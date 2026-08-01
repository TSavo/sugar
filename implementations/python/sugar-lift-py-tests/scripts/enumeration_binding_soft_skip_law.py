#!/usr/bin/env python3
"""R_enumeration_binding_soft_skips — soft catch of authenticated binding refuse.

Offender class (SIN CLUSTER 6 residual after #6946):

``FunctionBindingMiss`` and ``SourceCallBindingGap`` are *named* refusals from
the construction door. Catching them and soft-continuing (``continue``,
``fn = None``, ``rows = None`` without a gap row) reopens the pre-#6946 soft-None
path under a louder exception type. Serving an abstract universe contract from a
**spelling-keyed** ``by_name[t]`` table after binding refused is the same door
again: first-match-by-spelling enumeration.

Law:

1. Production may not catch ``FunctionBindingMiss`` solely to soft-skip.
   Sanctioned membrane (exact AST shape): append a gap naming the miss, then
   ``continue`` — never assign ``fn = None`` and fall through to a spelling table.
2. Production may not index abstract universe contracts by callee *spelling*
   (``by_name[t]``) on the dig path that also calls ``resolve_function_for_call``.
   Abstract fallback, when allowed, is keyed by authenticated definition identity
   (``source_cid`` of the resolved def memento).
3. ``SourceCallBindingGap`` on the applied dig is not a soft silent ``rows=None``
   without a gap when it shares a handler with soft ``continue`` into spelling
   fallback. Prefer a named gap row; identity-keyed abstract is separate.

Enforcement ladder retirement path:

- Type: Python cannot forbid ``except FunctionBindingMiss``; no codomain close.
- One door: resolve + bind_node_actuals already refuse; the dig must not invent
  a second serve path after refuse.
- Panic: a process panic on every dig miss would halt audit scans of partial
  workspaces — too high for open corpus. Loud *gap row* is the honest terminal
  until enumerate can refuse the whole request typed.
- This auditor holds the residual until dig has no soft FunctionBindingMiss
  membrane and no spelling ``by_name`` on the resolve path; then delete this shell.

Exit 1 while R > 0. No baseline.
"""

from __future__ import annotations

# Not the board. Own denominator; scripts/control_effect_recensus.py is the
# sole authoritative Python corpus scoreboard.
SCOREBOARD_AUTHORITY = False

import argparse
import ast
import sys
from pathlib import Path
from typing import NamedTuple


class SoftSkipOffender(NamedTuple):
    path: str
    line: int
    kind: str
    note: str


_FUNCTION_BINDING_MISS = frozenset({"FunctionBindingMiss"})
_SOURCE_CALL_BINDING_GAP = frozenset({"SourceCallBindingGap"})


def _handler_type_names(handler: ast.ExceptHandler) -> set[str]:
    names: set[str] = set()
    t = handler.type
    if t is None:
        return {"<bare>"}

    def walk(node: ast.AST) -> None:
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Tuple):
            for elt in node.elts:
                walk(elt)

    walk(t)
    return names


def _handler_text(handler: ast.ExceptHandler) -> str:
    return ast.unparse(handler)


def _is_gap_append_then_continue(handler: ast.ExceptHandler) -> bool:
    """Sanctioned: name the miss as a gap row, then continue — no fn=None fallthrough."""
    text = _handler_text(handler)
    if "fn = None" in text or "fn=None" in text:
        return False
    if "rows = None" in text and "gaps.append" not in text:
        return False
    # Must append a gap that names the miss class, then continue.
    if "gaps.append" not in text and "cue_gaps.append" not in text:
        return False
    if "FunctionBindingMiss" not in text and "SourceCallBindingGap" not in text:
        # reason string may use the exception instance
        if "miss." not in text and "bind_gap" not in text and "as miss" not in text:
            if "as " not in text:
                return False
    body = [s for s in handler.body if not isinstance(s, ast.Pass)]
    if not body:
        return False
    # Last statement continue, and some append of gaps earlier
    last = body[-1]
    if not isinstance(last, ast.Continue):
        return False
    return any(
        "gaps.append" in ast.unparse(stmt) or "cue_gaps.append" in ast.unparse(stmt)
        for stmt in body[:-1]
    )


def _soft_function_binding_miss(handler: ast.ExceptHandler) -> bool:
    names = _handler_type_names(handler)
    if not (names & _FUNCTION_BINDING_MISS):
        return False
    if _is_gap_append_then_continue(handler):
        return False
    text = _handler_text(handler)
    # Pure re-raise is allowed (process-terminal).
    if len(handler.body) == 1 and isinstance(handler.body[0], ast.Raise):
        return False
    soft = (
        "continue" in text
        or "fn = None" in text
        or "fn=None" in text
        or "pass" == text.strip().splitlines()[-1].strip()
        or "return None" in text
    )
    return soft


def _soft_binding_gap_with_rows_none(handler: ast.ExceptHandler) -> bool:
    """SourceCallBindingGap soft-set rows=None without a gap row."""
    names = _handler_type_names(handler)
    if not (names & _SOURCE_CALL_BINDING_GAP):
        return False
    text = _handler_text(handler)
    if "rows = None" in text or "rows=None" in text:
        if "gaps.append" in text or "cue_gaps.append" in text:
            return False
        return True
    return False


def _function_contains_resolve_and_spelling_by_name(func: ast.AST) -> list[ast.AST]:
    """Find ``by_name[t]`` / ``if t in by_name`` on a path that resolves callees."""
    if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return []
    text = ast.unparse(func)
    if "resolve_function_for_call" not in text:
        return []
    offenders: list[ast.AST] = []
    for node in ast.walk(func):
        # by_name = {name: ...} construction used as spelling index
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "by_name":
                    offenders.append(node)
        # if t in by_name
        if isinstance(node, ast.Compare):
            if any(isinstance(op, ast.In) for op in node.ops):
                unparsed = ast.unparse(node)
                if "by_name" in unparsed and (
                    "t in by_name" in unparsed or "in by_name" in unparsed
                ):
                    offenders.append(node)
        # by_name[t]
        if isinstance(node, ast.Subscript):
            if isinstance(node.value, ast.Name) and node.value.id == "by_name":
                offenders.append(node)
    return offenders


def scan_sources(paths: list[Path], *, root: Path) -> list[SoftSkipOffender]:
    offenders: list[SoftSkipOffender] = []
    for path in paths:
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            rel = path.as_posix()
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            offenders.append(
                SoftSkipOffender(
                    rel, 0, "auditor-read-error", f"could not read source: {error}"
                )
            )
            continue
        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as error:
            offenders.append(
                SoftSkipOffender(
                    rel,
                    int(error.lineno or 0),
                    "auditor-parse-error",
                    f"ast.parse failed: {error.msg}",
                )
            )
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                if _soft_function_binding_miss(node):
                    offenders.append(
                        SoftSkipOffender(
                            path=rel,
                            line=node.lineno,
                            kind="function-binding-miss-soft-skip",
                            note=(
                                "except FunctionBindingMiss soft-continues "
                                "(continue / fn=None / pass) without a gap row. "
                                "Replacement: append a named gap then continue, "
                                "or re-raise. Never fall through to spelling by_name."
                            ),
                        )
                    )
                if _soft_binding_gap_with_rows_none(node):
                    offenders.append(
                        SoftSkipOffender(
                            path=rel,
                            line=node.lineno,
                            kind="source-call-binding-gap-soft-rows-none",
                            note=(
                                "except SourceCallBindingGap sets rows=None without "
                                "a gap row, reopening silent applied-dig failure. "
                                "Replacement: gaps.append naming the bind gap, then "
                                "identity-keyed abstract only — never spelling by_name."
                            ),
                        )
                    )
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for hit in _function_contains_resolve_and_spelling_by_name(node):
                    offenders.append(
                        SoftSkipOffender(
                            path=rel,
                            line=getattr(hit, "lineno", node.lineno),
                            kind="spelling-by-name-after-resolve",
                            note=(
                                "universe dig builds or reads by_name on the same "
                                "path as resolve_function_for_call. Spelling index is "
                                "the pre-#6946 second door. Replacement: key abstract "
                                "contracts by resolved def source_cid only."
                            ),
                        )
                    )
    return offenders


def production_scan_roots(kit_root: Path) -> list[Path]:
    """Production membranes only — tests/scripts are free to plant the sin."""
    src = kit_root / "src" / "sugar_lift_py_tests"
    paths: list[Path] = []
    for name in ("lift_rpc.py", "tree_enumerate.py"):
        path = src / name
        if path.is_file():
            paths.append(path)
    return paths


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--kit-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="sugar-lift-py-tests package root",
    )
    args = parser.parse_args(argv)
    kit_root = args.kit_root.resolve()
    paths = production_scan_roots(kit_root)
    if not paths:
        print("R_enumeration_binding_soft_skips auditor_errors=1 (no production roots)")
        return 1
    offenders = scan_sources(paths, root=kit_root)
    r = len(offenders)
    print(f"R_enumeration_binding_soft_skips={r}")
    for row in offenders:
        print(f"  {row.path}:{row.line} [{row.kind}] {row.note}")
    if r:
        print(
            "replacement: FunctionBindingMiss → gap row then continue; "
            "abstract universe by source_cid of resolved def; delete by_name[t]"
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
