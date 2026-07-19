#!/usr/bin/env python3
"""R_context_incomplete_construction_caches — permanent cache-soundness floor.

A cache that publishes factory-built structure must separate every factory
recognition context consumed while constructing that structure.  A source-only
key can otherwise return a successful but wrong SugarBody across contexts.

R is the number of production construction-cache owners whose lookup key omits
the factory context used by build_body/build_child/build_node.  R > 0 is red;
there is no baseline or allowlist.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import NamedTuple


_FACTORY_BUILD_CALLS = frozenset({"build_body", "build_child", "build_node"})
_CACHE_LOOKUP_CALLS = frozenset({"_lookup", "cache_get"})
_CACHE_PUBLISH_CALLS = frozenset({"_publish", "cache_put"})


class ContextIncompleteConstructionCache(NamedTuple):
    file: str
    line: int
    owner: str
    reason: str


def _call_name(node: ast.Call) -> str:
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    if isinstance(node.func, ast.Name):
        return node.func.id
    return ""


def _method_map(owner: ast.ClassDef) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    return {
        node.name: node
        for node in owner.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _context_parameters(
    method: ast.FunctionDef | ast.AsyncFunctionDef,
) -> frozenset[str]:
    return frozenset(
        arg.arg
        for arg in (*method.args.posonlyargs, *method.args.args, *method.args.kwonlyargs)
        if arg.arg not in {"self", "cls", "site", "fragment", "node", "role"}
        and ("ctx" in arg.arg or "context" in arg.arg)
    )


def _identity_call_carries_context(
    call: ast.Call, context_parameters: frozenset[str]
) -> bool:
    supplied = (*call.args, *(keyword.value for keyword in call.keywords))
    return any(
        isinstance(value, ast.Name) and value.id in context_parameters
        for value in supplied
    )


def _identity_method_consumes_context(
    method: ast.FunctionDef | ast.AsyncFunctionDef | None,
) -> bool:
    if method is None:
        return False
    context_parameters = _context_parameters(method)
    if not context_parameters:
        return False
    return any(
        isinstance(node, ast.Name)
        and isinstance(node.ctx, ast.Load)
        and node.id in context_parameters
        for node in ast.walk(method)
    )


def context_incomplete_construction_caches(
    tree: ast.AST, *, file: str
) -> list[ContextIncompleteConstructionCache]:
    offenders: list[ContextIncompleteConstructionCache] = []
    for owner in (node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)):
        methods = _method_map(owner)
        for method in methods.values():
            calls = [node for node in ast.walk(method) if isinstance(node, ast.Call)]
            if not any(_call_name(call) in _FACTORY_BUILD_CALLS for call in calls):
                continue
            if not any(_call_name(call) in _CACHE_LOOKUP_CALLS for call in calls):
                continue
            if not any(_call_name(call) in _CACHE_PUBLISH_CALLS for call in calls):
                continue

            context_parameters = _context_parameters(method)
            identity_calls = [
                call for call in calls if _call_name(call) == "identity_key"
            ]
            identity_method = methods.get("identity_key")
            carries_context = bool(context_parameters) and any(
                _identity_call_carries_context(call, context_parameters)
                for call in identity_calls
            )
            consumes_context = _identity_method_consumes_context(identity_method)
            if carries_context and consumes_context:
                continue
            offenders.append(
                ContextIncompleteConstructionCache(
                    file=file,
                    line=owner.lineno,
                    owner=owner.name,
                    reason=(
                        "factory-built structure cache key omits the "
                        "factory-recognition context consumed by construction"
                    ),
                )
            )
            break
    return offenders


def scan_paths(paths: Iterable[Path], *, root: Path) -> list[ContextIncompleteConstructionCache]:
    offenders: list[ContextIncompleteConstructionCache] = []
    for path in sorted(set(paths)):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        offenders.extend(
            context_incomplete_construction_caches(
                tree, file=path.relative_to(root).as_posix()
            )
        )
    return offenders


def _python_paths(roots: Sequence[Path]) -> list[Path]:
    return [
        path
        for root in roots
        for path in (root.rglob("*.py") if root.is_dir() else (root,))
        if path.is_file() and "__pycache__" not in path.parts
    ]


def main(argv: Sequence[str] | None = None) -> int:
    repo_root = Path(__file__).resolve().parents[4]
    default_root = (
        repo_root
        / "implementations"
        / "python"
        / "sugar-lift-py-tests"
        / "src"
        / "sugar_lift_py_tests"
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, action="append", default=[])
    parser.add_argument("--repo-root", type=Path, default=repo_root)
    args = parser.parse_args(argv)
    roots = args.root or [default_root]

    try:
        paths = _python_paths(roots)
        if not paths:
            raise ValueError(f"no Python production files found under {roots}")
        offenders = scan_paths(paths, root=args.repo_root)
    except (OSError, UnicodeError, SyntaxError, TypeError, ValueError) as exc:
        print(
            "CONSTRUCTION-CACHE-CONTEXT LAW ERROR: "
            f"{type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        print(
            json.dumps(
                {
                    "instrument": "R_context_incomplete_construction_caches",
                    "ok": False,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "R_context_incomplete_construction_caches": None,
                }
            )
        )
        return 2

    for offender in offenders:
        print(
            f"{offender.file}:{offender.line}: {offender.owner}: "
            f"{offender.reason}"
        )
    r = len(offenders)
    print(
        json.dumps(
            {
                "instrument": "R_context_incomplete_construction_caches",
                "ok": r == 0,
                "R_context_incomplete_construction_caches": r,
                "files_scanned": len(paths),
            }
        )
    )
    if r:
        print(
            "CONSTRUCTION-CACHE-CONTEXT LAW RED: "
            f"R_context_incomplete_construction_caches = {r}"
        )
        return 1
    print(
        "CONSTRUCTION-CACHE-CONTEXT LAW GREEN: "
        "R_context_incomplete_construction_caches = 0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
