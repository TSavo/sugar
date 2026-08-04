#!/usr/bin/env python3
"""Authenticated AST census of construction-panic catches in our implementation.

This instrument never scans the authenticated pandas corpus.  It carries the
complete implementation file/site manifests, keeps ConstructionPanic and
SugarNotWritten candidate populations separate, and refuses measurement when
the declared source population cannot be read or parsed.
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Iterable, Mapping, Sequence

from sugar_lift_py_tests.canonicalizer import blake3_512_of
from sugar_lift_python_source.canonical import cid_of_json


SCHEMA = "implementation-catch-census/v1"
_SCRIPT_PATH = Path(__file__).resolve()
_SCRIPT_DIR = _SCRIPT_PATH.parent
_CLASSIFIER_PATH = _SCRIPT_DIR / "construction_panic_catch_law.py"


def _load_construction_panic_classifier():
    spec = importlib.util.spec_from_file_location(
        "implementation_catch_census_construction_panic_authority",
        _CLASSIFIER_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(
            f"cannot load ConstructionPanic classifier at {_CLASSIFIER_PATH}"
        )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_CP_AUTHORITY = _load_construction_panic_classifier()


_CP_TYPES = frozenset({"ConstructionPanic", "BaseException", "<bare>"})
_SNW_TYPES = frozenset(
    {"SugarNotWritten", "SourceTreePanic", "Exception", "BaseException", "<bare>"}
)
_CP_DIRECT_CALLS = frozenset(
    {"ConstructionPanic", "construction_panic", "construction_panic_gap", "dig_boundary_panic"}
)
_SNW_DIRECT_CALLS = frozenset({"SugarNotWritten", "SourceTreePanic"})
_TYPED_TESTIMONY_SUFFIXES = (
    "Gap",
    "GapV1",
    "Failure",
    "Refusal",
    "Row",
)
_KNOWN_NONCONSTRUCTION_CALLS = frozenset(
    {
        "abs",
        "all",
        "any",
        "bool",
        "bytes",
        "dict",
        "enumerate",
        "float",
        "frozenset",
        "getattr",
        "hasattr",
        "hex",
        "int",
        "isinstance",
        "issubclass",
        "iter",
        "len",
        "list",
        "max",
        "min",
        "next",
        "object",
        "open",
        "print",
        "range",
        "repr",
        "reversed",
        "set",
        "setattr",
        "sorted",
        "str",
        "sum",
        "super",
        "tuple",
        "type",
        "zip",
    }
)


def _source_cid(data: bytes) -> str:
    return blake3_512_of(data)


def _canonical_ast_cid(node: ast.AST) -> str:
    return blake3_512_of(
        ast.dump(node, include_attributes=False).encode("utf-8")
    )


def _handler_names(handler: ast.ExceptHandler) -> set[str]:
    return set(_CP_AUTHORITY._handler_names(handler))


def _module_name(relative: Path) -> str:
    parts = list(relative.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _enclosing_qualname(
    node: ast.AST, parents: Mapping[ast.AST, ast.AST]
) -> str:
    names: list[str] = []
    parent = parents.get(node)
    while parent is not None:
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(parent.name)
        parent = parents.get(parent)
    return ".".join(reversed(names)) or "<module>"


def _function_qualname(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    parents: Mapping[ast.AST, ast.AST],
) -> str:
    names = [node.name]
    parent = parents.get(node)
    while parent is not None:
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.append(parent.name)
        parent = parents.get(parent)
    return ".".join(reversed(names))


class _BodySignals(ast.NodeVisitor):
    """Calls and raises in one lexical body, excluding nested definitions."""

    def __init__(self) -> None:
        self.calls: list[ast.Call] = []
        self.raises: list[ast.Raise] = []

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802 - ast API
        self.calls.append(node)
        self.generic_visit(node)

    def visit_Raise(self, node: ast.Raise) -> None:  # noqa: N802 - ast API
        self.raises.append(node)
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        return

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        return

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        return

    def visit_Lambda(self, node: ast.Lambda) -> None:  # noqa: N802
        return


def _signals(statements: Iterable[ast.stmt]) -> _BodySignals:
    visitor = _BodySignals()
    for statement in statements:
        visitor.visit(statement)
    return visitor


def _call_leaf(call: ast.Call) -> str | None:
    function = call.func
    if isinstance(function, ast.Name):
        return function.id
    if isinstance(function, ast.Attribute):
        return function.attr
    return None


def _raised_leaf(node: ast.Raise) -> str | None:
    exc = node.exc
    if isinstance(exc, ast.Call):
        return _call_leaf(exc)
    if isinstance(exc, ast.Name):
        return exc.id
    if isinstance(exc, ast.Attribute):
        return exc.attr
    return None


def _import_aliases(tree: ast.Module) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                aliases[alias.asname or alias.name.split(".")[0]] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                if alias.name == "*":
                    continue
                aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    return aliases


def _attribute_parts(node: ast.AST) -> list[str] | None:
    parts: list[str] = []
    cursor = node
    while isinstance(cursor, ast.Attribute):
        parts.append(cursor.attr)
        cursor = cursor.value
    if not isinstance(cursor, ast.Name):
        return None
    parts.append(cursor.id)
    return list(reversed(parts))


def _resolved_call_target(
    call: ast.Call,
    *,
    module: str,
    function_qualname: str,
    aliases: Mapping[str, str],
    functions: Mapping[str, dict[str, Any]],
    module_simple: Mapping[tuple[str, str], tuple[str, ...]],
) -> tuple[str | None, bool]:
    """Return (authenticated local target, dynamic/unknown)."""
    function = call.func
    if isinstance(function, ast.Name):
        name = function.id
        if name in _CP_DIRECT_CALLS or name in _SNW_DIRECT_CALLS:
            return None, False
        candidates = module_simple.get((module, name), ())
        if len(candidates) == 1:
            return candidates[0], False
        imported = aliases.get(name)
        if imported in functions:
            return imported, False
        if name in _KNOWN_NONCONSTRUCTION_CALLS:
            return None, False
        return None, True
    if isinstance(function, ast.Attribute):
        parts = _attribute_parts(function)
        if not parts:
            return None, True
        if parts[0] in {"self", "cls"}:
            class_path = function_qualname.rsplit(".", 1)[0] if "." in function_qualname else ""
            target = f"{module}.{class_path}.{parts[-1]}" if class_path else ""
            if target in functions:
                return target, False
            return None, True
        imported = aliases.get(parts[0])
        if imported:
            target = ".".join([imported, *parts[1:]])
            if target in functions:
                return target, False
        return None, True
    return None, True


def _direct_hierarchies(signals: _BodySignals) -> set[str]:
    direct: set[str] = set()
    for raised in signals.raises:
        leaf = _raised_leaf(raised)
        if leaf in _CP_DIRECT_CALLS:
            direct.add("constructionPanic")
        if leaf in _SNW_DIRECT_CALLS:
            direct.add("sugarNotWritten")
        # A bare raise preserves an exception already caught by its enclosing
        # handler; it does not originate either construction hierarchy.  Treating
        # it as a provider made an inner I/O cleanup re-raise authenticate an
        # unrelated outer best-effort cache catch as construction-reachable.
    for call in signals.calls:
        leaf = _call_leaf(call)
        if leaf in _CP_DIRECT_CALLS:
            direct.add("constructionPanic")
        if leaf in _SNW_DIRECT_CALLS:
            direct.add("sugarNotWritten")
    return direct


def _expression_leaf(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Call):
        return _call_leaf(node)
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _is_typed_testimony_expression(node: ast.AST | None) -> bool:
    leaf = _expression_leaf(node)
    if leaf is None:
        return False
    return _is_typed_testimony_leaf(leaf)


def _is_typed_testimony_leaf(leaf: str) -> bool:
    if leaf in {
        "terminal_from_enumerate",
        "_attest_terminal_row",
        "_construction_panic_row",
        "_instrument_failure_row",
    }:
        return True
    return leaf.endswith(_TYPED_TESTIMONY_SUFFIXES)


def _contains_string(node: ast.AST, value: str) -> bool:
    return any(
        isinstance(item, ast.Constant) and item.value == value
        for item in ast.walk(node)
    )


def _explicit_reraise(handler: ast.ExceptHandler) -> bool:
    if not handler.body:
        return False
    final = handler.body[-1]
    if not isinstance(final, ast.Raise) or final.exc is not None:
        return False
    return not any(
        isinstance(item, (ast.Return, ast.Continue, ast.Break))
        for statement in handler.body[:-1]
        for item in ast.walk(statement)
    )


def _typed_guarded_return_names(handler: ast.ExceptHandler) -> dict[str, str]:
    guarded: dict[str, str] = {}
    for branch in ast.walk(handler):
        if not isinstance(branch, ast.If):
            continue
        test = branch.test
        if (
            not isinstance(test, ast.Call)
            or _call_leaf(test) != "isinstance"
            or len(test.args) != 2
            or not isinstance(test.args[0], ast.Name)
        ):
            continue
        type_leaf = _expression_leaf(test.args[1])
        if type_leaf is None or not _is_typed_testimony_leaf(type_leaf):
            continue
        name = test.args[0].id
        if any(
            isinstance(item, ast.Return)
            and isinstance(item.value, ast.Name)
            and item.value.id == name
            for statement in branch.body
            for item in ast.walk(statement)
        ):
            guarded[name] = type_leaf
    return guarded


def _typed_conversion_kind(handler: ast.ExceptHandler) -> tuple[str | None, list[str]]:
    """Authenticate named testimony produced by one handler.

    This is the primary lawfulness classifier.  The legacy CP scanner's exact
    sanctioned-site result remains carried as independent testimony, but does
    not mint lawfulness here: a handler must visibly re-raise, emit typed-loud
    transport, return/raise named typed testimony, install an attested gap
    obligation, or complete an authenticated alternate construction.
    """
    if _explicit_reraise(handler):
        return "explicit-reraise", ["handler is a pure re-raise"]

    raises = [item for item in ast.walk(handler) if isinstance(item, ast.Raise)]
    typed_raises = [
        item for item in raises if _is_typed_testimony_expression(item.exc)
    ]
    if typed_raises:
        leaves = sorted(
            {
                leaf
                for item in typed_raises
                if (leaf := _expression_leaf(item.exc)) is not None
            }
        )
        return "typed-refusal-raise", [f"raises named typed testimony: {', '.join(leaves)}"]

    calls = [item for item in ast.walk(handler) if isinstance(item, ast.Call)]
    call_leaves = {_call_leaf(item) for item in calls}
    if "_send" in call_leaves and _contains_string(handler, "typed-loud"):
        return "typed-loud-refusal", ["emits transport testimony kind=typed-loud"]
    if (
        "_send" in call_leaves
        and _contains_string(handler, "diagnostic")
        and _contains_string(handler, "exception_type")
        and any(_expression_leaf(item.exc) == "SystemExit" for item in raises)
    ):
        return "typed-rpc-refusal", [
            "emits exception_type plus diagnostic transport and exits loud"
        ]

    if (
        "_install_opaque_call_obligation" in call_leaves
        and "obligation" in call_leaves
    ):
        return "attested-gap-obligation", ["installs a named opaque-call obligation"]

    guarded_names = _typed_guarded_return_names(handler)
    returns = [item for item in ast.walk(handler) if isinstance(item, ast.Return)]
    typed_returns = [
        item
        for item in returns
        if _is_typed_testimony_expression(item.value)
        or (isinstance(item.value, ast.Name) and item.value.id in guarded_names)
    ]
    untyped_returns = [item for item in returns if item not in typed_returns]
    if typed_returns and not untyped_returns:
        leaves = sorted(
            {
                guarded_names.get(leaf, leaf)
                for item in typed_returns
                if (leaf := _expression_leaf(item.value)) is not None
            }
        )
        control_transfers = [
            item
            for item in ast.walk(handler)
            if isinstance(item, (ast.Continue, ast.Break))
        ]
        if not control_transfers:
            recovery_calls = sorted(
                leaf
                for leaf in call_leaves
                if leaf is not None
                and not _is_typed_testimony_leaf(leaf)
                and (
                    "construct" in leaf.lower()
                    or "project" in leaf.lower()
                    or leaf == "reduce_source_outcome"
                )
            )
            if recovery_calls:
                return "typed-gap-or-construction-recovery", [
                    f"returns typed testimony: {', '.join(leaves)}",
                    f"otherwise continues authenticated construction: {', '.join(recovery_calls)}",
                ]
            return "typed-gap-return", [f"returns named typed testimony: {', '.join(leaves)}"]

    return None, []


def _build_function_index(parsed: Sequence[dict[str, Any]]) -> dict[str, Any]:
    functions: dict[str, dict[str, Any]] = {}
    module_simple_lists: dict[tuple[str, str], list[str]] = {}
    for file_info in parsed:
        tree = file_info["tree"]
        parents = file_info["parents"]
        module = file_info["module"]
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            qualname = _function_qualname(node, parents)
            identity = f"{module}.{qualname}" if module else qualname
            info = {
                "identity": identity,
                "module": module,
                "qualname": qualname,
                "node": node,
                "aliases": file_info["aliases"],
                "direct": _direct_hierarchies(_signals(node.body)),
                "callees": set(),
                "dynamic": False,
            }
            functions[identity] = info
            module_simple_lists.setdefault((module, node.name), []).append(identity)
    module_simple = {key: tuple(value) for key, value in module_simple_lists.items()}
    for info in functions.values():
        sig = _signals(info["node"].body)
        for call in sig.calls:
            target, dynamic = _resolved_call_target(
                call,
                module=info["module"],
                function_qualname=info["qualname"],
                aliases=info["aliases"],
                functions=functions,
                module_simple=module_simple,
            )
            if target:
                info["callees"].add(target)
            if dynamic:
                info["dynamic"] = True
    providers = {identity: set(info["direct"]) for identity, info in functions.items()}
    changed = True
    while changed:
        changed = False
        for identity, info in functions.items():
            before = set(providers[identity])
            for callee in info["callees"]:
                providers[identity].update(providers.get(callee, set()))
            if providers[identity] != before:
                changed = True
    return {
        "functions": functions,
        "moduleSimple": module_simple,
        "providers": providers,
    }


def _handler_reachability(
    handler: ast.ExceptHandler,
    *,
    hierarchy: str,
    file_info: Mapping[str, Any],
    function_index: Mapping[str, Any],
) -> tuple[str, list[str]]:
    parent = file_info["parents"].get(handler)
    if not isinstance(parent, (ast.Try, ast.TryStar)):
        return "unresolved", ["handler parent is not Try/TryStar"]
    sig = _signals(parent.body)
    if hierarchy in _direct_hierarchies(sig):
        return "direct", ["guarded body directly raises/calls the panic hierarchy"]
    function_qualname = _enclosing_qualname(handler, file_info["parents"])
    paths: list[str] = []
    dynamic_calls: list[str] = []
    for call in sig.calls:
        target, unknown = _resolved_call_target(
            call,
            module=file_info["module"],
            function_qualname=function_qualname,
            aliases=file_info["aliases"],
            functions=function_index["functions"],
            module_simple=function_index["moduleSimple"],
        )
        if target and hierarchy in function_index["providers"].get(target, set()):
            paths.append(target)
        if unknown:
            try:
                spelling = ast.unparse(call.func)
            except (AttributeError, ValueError):
                spelling = ast.dump(call.func, include_attributes=False)
            dynamic_calls.append(
                f"{spelling}@{call.lineno}:{call.col_offset}"
            )
    if paths:
        return "transitive", sorted(paths)
    if dynamic_calls:
        return "unresolved", [
            "guarded body contains dynamically unresolved calls",
            *sorted(set(dynamic_calls)),
        ]
    return "outside-construction", []


def _snw_prior_reraise(
    handler: ast.ExceptHandler, parents: Mapping[ast.AST, ast.AST]
) -> bool:
    parent = parents.get(handler)
    if not isinstance(parent, (ast.Try, ast.TryStar)):
        return False
    index = parent.handlers.index(handler)
    for prior in parent.handlers[:index]:
        if _handler_names(prior) & _SNW_TYPES and _CP_AUTHORITY._pure_reraise(prior):
            return True
    return False


def _proximity(file: str, reachability: str) -> dict[str, Any]:
    if reachability == "direct" and any(
        token in file for token in ("lift_rpc.py", "manager_construction.py", "nodes.py")
    ):
        return {"rank": 0, "kind": "direct-lifter-or-mint"}
    if reachability == "direct":
        return {"rank": 1, "kind": "direct-construction"}
    if reachability == "transitive":
        return {"rank": 2, "kind": "transitive-construction"}
    if "/scripts/" in file or file.startswith("sugar-lift-py-tests/scripts"):
        return {"rank": 3, "kind": "measurement-script"}
    if reachability == "unresolved":
        return {"rank": 4, "kind": "unresolved"}
    return {"rank": 5, "kind": "outside-construction"}


def _stage_map() -> dict[str, Any]:
    return {
        "implementationCatchCensus": {
            "module": _SCRIPT_PATH.as_posix(),
            "qualname": "measure_declared_roots",
            "sourceCid": _source_cid(_SCRIPT_PATH.read_bytes()),
        },
        "constructionPanicClassifier": {
            "module": _CLASSIFIER_PATH.as_posix(),
            "qualname": "construction_panic_catch_law semantic predicates",
            "sourceCid": _source_cid(_CLASSIFIER_PATH.read_bytes()),
        },
    }


def _unmeasured(
    *,
    measured_commit: str,
    declared_roots: Sequence[tuple[str, Path]],
    failures: list[dict[str, Any]],
    stage_map: dict[str, Any] | None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "unmeasured",
        "measured": False,
        "measuredCommit": measured_commit,
        "declaredRoots": [
            {"prefix": prefix, "path": str(Path(root).resolve())}
            for prefix, root in declared_roots
        ],
        "instrumentFailures": failures,
    }
    if stage_map is not None:
        body["stageMap"] = stage_map
    return body


def _parse_population(
    declared_roots: Sequence[tuple[str, Path]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    parsed: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    seen_paths: set[Path] = set()
    for prefix, raw_root in declared_roots:
        root = Path(raw_root)
        if not root.is_dir():
            failures.append(
                {"kind": "missing-root", "root": str(root), "prefix": prefix}
            )
            continue
        try:
            paths = sorted(root.rglob("*.py"))
        except OSError as error:
            failures.append(
                {"kind": "enumerate-error", "root": str(root), "error": str(error)}
            )
            continue
        for path in paths:
            try:
                resolved = path.resolve()
            except OSError as error:
                failures.append(
                    {"kind": "resolve-error", "file": str(path), "error": str(error)}
                )
                continue
            if resolved in seen_paths or "__pycache__" in resolved.parts:
                continue
            seen_paths.add(resolved)
            relative = resolved.relative_to(root.resolve())
            file = f"{prefix}/{relative.as_posix()}"
            try:
                data = resolved.read_bytes()
            except OSError as error:
                failures.append(
                    {"kind": "read-error", "file": file, "error": str(error)}
                )
                continue
            try:
                source = data.decode("utf-8")
            except UnicodeError as error:
                failures.append(
                    {"kind": "decode-error", "file": file, "error": str(error)}
                )
                continue
            try:
                tree = ast.parse(source, filename=file)
            except SyntaxError as error:
                failures.append(
                    {
                        "kind": "parse-error",
                        "file": file,
                        "line": int(error.lineno or 0),
                        "error": error.msg,
                    }
                )
                continue
            parents = {
                child: parent
                for parent in ast.walk(tree)
                for child in ast.iter_child_nodes(parent)
            }
            parsed.append(
                {
                    "prefix": prefix,
                    "root": root.resolve(),
                    "path": resolved,
                    "relative": relative,
                    "file": file,
                    "sourceCid": _source_cid(data),
                    "tree": tree,
                    "parents": parents,
                    "module": _module_name(relative),
                    "aliases": _import_aliases(tree),
                }
            )
    return parsed, failures


def _site_row(file_info: Mapping[str, Any], handler: ast.ExceptHandler) -> dict[str, Any]:
    names = sorted(_handler_names(handler))
    row = {
        "file": file_info["file"],
        "sourceCid": file_info["sourceCid"],
        "module": file_info["module"],
        "qualname": _enclosing_qualname(handler, file_info["parents"]),
        "coordinate": {
            "startLine": handler.lineno,
            "startCol": handler.col_offset,
            "endLine": int(handler.end_lineno or handler.lineno),
            "endCol": int(handler.end_col_offset or handler.col_offset),
        },
        "caughtTypes": names,
        "handlerAstCid": _canonical_ast_cid(handler),
    }
    row["siteId"] = cid_of_json(row)
    return row


def _candidate_row(
    site: Mapping[str, Any],
    *,
    handler: ast.ExceptHandler,
    hierarchy: str,
    file_info: Mapping[str, Any],
    function_index: Mapping[str, Any],
) -> dict[str, Any]:
    reachability, evidence = _handler_reachability(
        handler,
        hierarchy=hierarchy,
        file_info=file_info,
        function_index=function_index,
    )
    pure_reraise = _explicit_reraise(handler)
    legacy_classifier_reraise = bool(_CP_AUTHORITY._pure_reraise(handler))
    authority_rel = file_info["relative"].as_posix()
    sanctioned = bool(
        _CP_AUTHORITY._is_sanctioned_handler(
            authority_rel, handler, file_info["parents"]
        )
    )
    typed_conversion, conversion_evidence = _typed_conversion_kind(handler)
    classification: str | None = None
    if typed_conversion is not None and reachability != "outside-construction":
        # Handler semantics, not a site allowlist, are the primary authority.
        # This can be decided even when the guarded call graph is unresolved:
        # if the hierarchy ever arrives, the handler still emits or re-raises
        # named typed testimony.
        classification = "lawful"
    elif reachability in {"direct", "transitive"}:
        classification = "suppression"
    row = dict(site)
    row.update(
        {
            "hierarchy": hierarchy,
            "reachability": reachability,
            "reachabilityEvidence": evidence,
            "classification": classification,
            "pureReraise": pure_reraise,
            "legacyClassifierPureReraise": legacy_classifier_reraise,
            "typedConversionKind": typed_conversion,
            "typedConversionEvidence": conversion_evidence,
            "sanctionedMembrane": sanctioned,
            "classifierAuthority": _CLASSIFIER_PATH.as_posix(),
            "proximity": _proximity(str(site["file"]), reachability),
        }
    )
    return row


def _manifest(members: list[dict[str, Any]], field: str) -> dict[str, Any]:
    return {
        "count": len(members),
        "cid": cid_of_json({field: members}),
        "manifest": members,
    }


def measure_declared_roots(
    *,
    declared_roots: Sequence[tuple[str, Path]],
    measured_commit: str,
) -> dict[str, Any]:
    roots = tuple((str(prefix), Path(root)) for prefix, root in declared_roots)
    try:
        stage_map = _stage_map()
    except (OSError, UnicodeError, ValueError) as error:
        return _unmeasured(
            measured_commit=measured_commit,
            declared_roots=roots,
            failures=[{"kind": "stage-witness-error", "error": str(error)}],
            stage_map=None,
        )
    parsed, failures = _parse_population(roots)
    if failures:
        return _unmeasured(
            measured_commit=measured_commit,
            declared_roots=roots,
            failures=failures,
            stage_map=stage_map,
        )
    function_index = _build_function_index(parsed)
    file_members = [
        {
            "file": info["file"],
            "sourceCid": info["sourceCid"],
            "module": info["module"],
        }
        for info in parsed
    ]
    site_members: list[dict[str, Any]] = []
    cp_rows: list[dict[str, Any]] = []
    snw_rows: list[dict[str, Any]] = []
    for file_info in parsed:
        for handler in sorted(
            (
                node
                for node in ast.walk(file_info["tree"])
                if isinstance(node, ast.ExceptHandler)
            ),
            key=lambda node: (node.lineno, node.col_offset),
        ):
            site = _site_row(file_info, handler)
            names = set(site["caughtTypes"])
            site["constructionPanicCandidate"] = bool(names & _CP_TYPES)
            site["sugarNotWrittenCandidate"] = bool(names & _SNW_TYPES)
            site_members.append(site)
            if site["constructionPanicCandidate"] and not (
                _CP_AUTHORITY._prior_pure_reraise_intercepts_construction_panic(
                    handler, file_info["parents"]
                )
            ):
                cp_rows.append(
                    _candidate_row(
                        site,
                        handler=handler,
                        hierarchy="constructionPanic",
                        file_info=file_info,
                        function_index=function_index,
                    )
                )
            if site["sugarNotWrittenCandidate"] and not _snw_prior_reraise(
                handler, file_info["parents"]
            ):
                snw_rows.append(
                    _candidate_row(
                        site,
                        handler=handler,
                        hierarchy="sugarNotWritten",
                        file_info=file_info,
                        function_index=function_index,
                    )
                )
    file_members.sort(key=lambda row: row["file"])
    site_members.sort(
        key=lambda row: (
            row["file"],
            row["coordinate"]["startLine"],
            row["coordinate"]["startCol"],
        )
    )
    for rows in (cp_rows, snw_rows):
        rows.sort(
            key=lambda row: (
                row["file"],
                row["coordinate"]["startLine"],
                row["coordinate"]["startCol"],
            )
        )
    suppression_sites = {
        row["siteId"]
        for row in (*cp_rows, *snw_rows)
        if row["classification"] == "suppression"
    }
    reachability_unresolved_sites = {
        row["siteId"]
        for row in (*cp_rows, *snw_rows)
        if row["reachability"] == "unresolved"
    }
    unresolved_sites = {
        row["siteId"]
        for row in (*cp_rows, *snw_rows)
        if row["reachability"] == "unresolved"
        and row["classification"] is None
    }
    body: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "measured",
        "measured": True,
        "measuredCommit": measured_commit,
        "declaredRoots": [
            {"prefix": prefix, "path": str(root.resolve())} for prefix, root in roots
        ],
        "stageMap": stage_map,
        "files": _manifest(file_members, "files"),
        "sites": _manifest(site_members, "sites"),
        "candidates": {
            "constructionPanic": _manifest(cp_rows, "candidates"),
            "sugarNotWritten": _manifest(snw_rows, "candidates"),
        },
        "diffs": {"missing": [], "extra": [], "duplicate": []},
        "instrumentFailures": [],
        "result": {
            "suppressionCount": len(suppression_sites),
            "unresolvedCount": len(unresolved_sites),
            "reachabilityUnresolvedCount": len(reachability_unresolved_sites),
            "constructionPanicCandidateCount": len(cp_rows),
            "sugarNotWrittenCandidateCount": len(snw_rows),
        },
    }
    validation = validate_measured_receipt(body)
    if validation:
        return _unmeasured(
            measured_commit=measured_commit,
            declared_roots=roots,
            failures=validation,
            stage_map=stage_map,
        )
    body["bodyCid"] = cid_of_json({key: value for key, value in body.items() if key != "bodyCid"})
    return body


def validate_measured_receipt(receipt: Mapping[str, Any]) -> list[dict[str, Any]]:
    failures: list[dict[str, Any]] = []
    if receipt.get("status") != "measured" or receipt.get("measured") is not True:
        return [{"kind": "receipt-not-measured", "reason": "receipt is not measured"}]
    for key, field in (("files", "files"), ("sites", "sites")):
        value = receipt.get(key)
        if not isinstance(value, Mapping) or not isinstance(value.get("manifest"), list):
            failures.append({"kind": "missing-manifest", "reason": f"missing {key} manifest"})
            continue
        manifest = value["manifest"]
        if value.get("count") != len(manifest):
            failures.append({"kind": "count-mismatch", "reason": f"{key} manifest count mismatch"})
        if value.get("cid") != cid_of_json({field: manifest}):
            failures.append({"kind": "cid-mismatch", "reason": f"{key[:-1] if key.endswith('s') else key} manifest CID mismatch"})
    candidates = receipt.get("candidates")
    if not isinstance(candidates, Mapping):
        failures.append({"kind": "missing-candidates", "reason": "candidate manifests absent"})
    else:
        for hierarchy in ("constructionPanic", "sugarNotWritten"):
            value = candidates.get(hierarchy)
            if not isinstance(value, Mapping) or not isinstance(value.get("manifest"), list):
                failures.append({"kind": "missing-manifest", "reason": f"missing {hierarchy} candidate manifest"})
                continue
            manifest = value["manifest"]
            if value.get("count") != len(manifest):
                failures.append({"kind": "count-mismatch", "reason": f"{hierarchy} candidate count mismatch"})
            if value.get("cid") != cid_of_json({"candidates": manifest}):
                failures.append({"kind": "cid-mismatch", "reason": f"{hierarchy} candidate manifest CID mismatch"})
    site_manifest = (
        receipt.get("sites", {}).get("manifest", [])
        if isinstance(receipt.get("sites"), Mapping)
        else []
    )
    site_ids = [row.get("siteId") for row in site_manifest if isinstance(row, Mapping)]
    if len(site_ids) != len(set(site_ids)):
        failures.append({"kind": "duplicate-site", "reason": "site manifest has duplicate identities"})
    return failures


def _default_roots() -> tuple[tuple[str, Path], ...]:
    python_root = _SCRIPT_DIR.parent.parent
    return (
        ("sugar-lift-python-source/src", python_root / "sugar-lift-python-source" / "src"),
        ("sugar-source-tree/src", python_root / "sugar-source-tree" / "src"),
        ("sugar-lift-py-tests/src", python_root / "sugar-lift-py-tests" / "src"),
        ("sugar-lift-py-tests/scripts", python_root / "sugar-lift-py-tests" / "scripts"),
    )


def _git_commit() -> str:
    repo = _SCRIPT_PATH
    while repo.parent != repo and not (repo / ".git").exists():
        repo = repo.parent
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=repo, text=True
    ).strip()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--measured-commit", default=None)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    receipt = measure_declared_roots(
        declared_roots=_default_roots(),
        measured_commit=args.measured_commit or _git_commit(),
    )
    rendered = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    sys.stdout.write(rendered)
    if receipt.get("status") != "measured":
        return 1
    result = receipt["result"]
    return 1 if result["suppressionCount"] or result["unresolvedCount"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
