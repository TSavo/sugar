#!/usr/bin/env python3
"""R_context_incomplete_construction_caches — permanent cache-soundness floor.

A cache that publishes a factory-built value or structure must separate every
factory recognition context consumed while constructing it. A source-only key
can otherwise return a successful but wrong floor value or SugarBody across
contexts.

R is the number of production construction-cache owners whose lookup key omits
the factory context used by build_body/build_child/build_node, including when
construction is delegated to a module helper or driven around an external
oracle. R > 0 is red; there is no baseline or allowlist.
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


def _self_attribute(node: ast.AST) -> str | None:
    if (
        isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
    ):
        return node.attr
    return None


def _owned_table_attributes(
    methods: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
) -> frozenset[str]:
    attributes: set[str] = set()
    for method in methods.values():
        for node in ast.walk(method):
            target = None
            value = None
            if isinstance(node, ast.Assign):
                if len(node.targets) == 1:
                    target = node.targets[0]
                value = node.value
            elif isinstance(node, ast.AnnAssign):
                target = node.target
                value = node.value
            attribute = _self_attribute(target) if target is not None else None
            if attribute is None or value is None:
                continue
            if isinstance(value, (ast.Dict, ast.DictComp)):
                attributes.add(attribute)
            elif isinstance(value, ast.Call) and _call_name(value) in {
                "dict",
                "defaultdict",
                "OrderedDict",
                "WeakKeyDictionary",
                "WeakValueDictionary",
            }:
                attributes.add(attribute)
    return frozenset(attributes)


def _table_accesses(
    method: ast.FunctionDef | ast.AsyncFunctionDef,
    table_attributes: frozenset[str],
) -> tuple[bool, bool]:
    reads = False
    writes = False
    for node in ast.walk(method):
        if isinstance(node, ast.Subscript):
            attribute = _self_attribute(node.value)
            if attribute not in table_attributes:
                continue
            if isinstance(node.ctx, ast.Load):
                reads = True
            else:
                writes = True
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            attribute = _self_attribute(node.func.value)
            if attribute not in table_attributes:
                continue
            if node.func.attr in {"get", "__getitem__", "pop", "move_to_end"}:
                reads = True
            if node.func.attr in {
                "__setitem__",
                "setdefault",
                "update",
                "pop",
                "popitem",
                "clear",
            }:
                writes = True
    return reads, writes


def _local_function_map(
    tree: ast.AST,
) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    return {
        node.name: node
        for node in getattr(tree, "body", ())
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _function_constructs(
    method: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    local_functions: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
    owner_methods: dict[str, ast.FunctionDef | ast.AsyncFunctionDef],
    seen: frozenset[int] = frozenset(),
) -> bool:
    identity = id(method)
    if identity in seen:
        return False
    seen = seen | {identity}
    calls = [node for node in ast.walk(method) if isinstance(node, ast.Call)]
    if any(_call_name(call) in _FACTORY_BUILD_CALLS for call in calls):
        return True
    for call in calls:
        target = None
        if isinstance(call.func, ast.Name):
            target = local_functions.get(call.func.id)
        elif (
            isinstance(call.func, ast.Attribute)
            and isinstance(call.func.value, ast.Name)
            and call.func.value.id in {"self", "cls"}
        ):
            target = owner_methods.get(call.func.attr)
        if target is not None and _function_constructs(
            target,
            local_functions=local_functions,
            owner_methods=owner_methods,
            seen=seen,
        ):
            return True
    return False


def _assigned_call_names(
    method: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    receivers: frozenset[str],
) -> dict[str, ast.Call]:
    assigned: dict[str, ast.Call] = {}
    for node in ast.walk(method):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        target = node.targets[0] if isinstance(node, ast.Assign) and len(node.targets) == 1 else (
            node.target if isinstance(node, ast.AnnAssign) else None
        )
        value = node.value
        if (
            isinstance(target, ast.Name)
            and isinstance(value, ast.Call)
            and isinstance(value.func, ast.Attribute)
            and isinstance(value.func.value, ast.Name)
            and value.func.value.id in receivers
        ):
            assigned[target.id] = value
    return assigned


def _cache_key_names(
    method: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    receivers: frozenset[str],
    table_attributes: frozenset[str],
    lookup_methods: frozenset[str],
    publish_methods: frozenset[str],
) -> frozenset[str]:
    names: set[str] = set()
    for node in ast.walk(method):
        key = None
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in receivers
            and node.func.attr in lookup_methods | publish_methods
            and node.args
        ):
            key = node.args[0]
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and _self_attribute(node.func.value) in table_attributes
            and node.args
        ):
            key = node.args[0]
        elif (
            isinstance(node, ast.Subscript)
            and _self_attribute(node.value) in table_attributes
        ):
            key = node.slice
        if isinstance(key, ast.Name):
            names.add(key.id)
    return frozenset(names)


def _local_receiver_aliases(
    method: ast.FunctionDef | ast.AsyncFunctionDef, globals_for_owner: frozenset[str]
) -> frozenset[str]:
    aliases = set(globals_for_owner)
    for node in ast.walk(method):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if (
            isinstance(target, ast.Name)
            and isinstance(node.value, ast.Name)
            and node.value.id in globals_for_owner
        ):
            aliases.add(target.id)
    return frozenset(aliases)


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
    local_functions = _local_function_map(tree)
    owners = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
    global_instances: dict[str, str] = {}
    for node in getattr(tree, "body", ()):
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if (
            isinstance(target, ast.Name)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
        ):
            global_instances[target.id] = node.value.func.id
    for owner in owners:
        methods = _method_map(owner)
        table_attributes = _owned_table_attributes(methods)
        if not table_attributes:
            continue
        access = {
            name: _table_accesses(method, table_attributes)
            for name, method in methods.items()
        }
        lookup_methods = frozenset(name for name, (read, _) in access.items() if read)
        publish_methods = frozenset(name for name, (_, write) in access.items() if write)
        if not lookup_methods or not publish_methods:
            continue
        globals_for_owner = frozenset(
            name for name, class_name in global_instances.items() if class_name == owner.name
        )
        regions: list[
            tuple[
                ast.FunctionDef | ast.AsyncFunctionDef,
                frozenset[str],
            ]
        ] = [(method, frozenset({"self", "cls"})) for method in methods.values()]
        regions.extend(
            (method, _local_receiver_aliases(method, globals_for_owner))
            for method in local_functions.values()
            if globals_for_owner
        )
        for method, receivers in regions:
            if not receivers or not _function_constructs(
                method,
                local_functions=local_functions,
                owner_methods=methods,
            ):
                continue
            calls = [node for node in ast.walk(method) if isinstance(node, ast.Call)]
            invokes_lookup = any(
                isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id in receivers
                and call.func.attr in lookup_methods
                for call in calls
            )
            invokes_publish = any(
                isinstance(call.func, ast.Attribute)
                and isinstance(call.func.value, ast.Name)
                and call.func.value.id in receivers
                and call.func.attr in publish_methods
                for call in calls
            )
            direct_read, direct_write = (
                _table_accesses(method, table_attributes)
                if "self" in receivers
                else (False, False)
            )
            if not (invokes_lookup or direct_read) or not (
                invokes_publish or direct_write
            ):
                continue
            context_parameters = _context_parameters(method)
            key_names = _cache_key_names(
                method,
                receivers=receivers,
                table_attributes=table_attributes,
                lookup_methods=lookup_methods,
                publish_methods=publish_methods,
            )
            assigned_calls = _assigned_call_names(method, receivers=receivers)
            identity_calls = [
                call for name, call in assigned_calls.items() if name in key_names
            ]
            identity_method = None
            if identity_calls:
                identity_method = methods.get(_call_name(identity_calls[0]))
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
                        "factory-built value/structure cache key omits the "
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
