"""Non-constructing lexical authentication for imported call uses.

This pass owns only Python def-use.  It never imports a module, opens a target
module, or constructs Sugar.  Its output is the source-authenticated half of
the import-to-contract bridge protocol.
"""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .canonicalizer import blake3_512_of, encode_jcs
from .context_manager_contract import _json_value


def _hash(value: Any) -> str:
    return blake3_512_of(encode_jcs(_json_value(value)).encode("utf-8"))


def _site(source_cid: str, node: ast.AST) -> dict[str, Any]:
    if not hasattr(node, "lineno"):
        body = getattr(node, "body", ())
        if not body:
            return {"sourceCid": source_cid, "startLine": 1, "startCol": 0, "endLine": 1, "endCol": 0}
        return {
            "sourceCid": source_cid, "startLine": 1, "startCol": 0,
            "endLine": body[-1].end_lineno, "endCol": body[-1].end_col_offset,
        }
    return {
        "sourceCid": source_cid,
        "startLine": node.lineno,
        "startCol": node.col_offset,
        "endLine": node.end_lineno,
        "endCol": node.end_col_offset,
    }


@dataclass(frozen=True)
class _ImportDef:
    cid: str
    target_symbol: str
    payload_jcs: str


@dataclass(frozen=True)
class _ModuleFunctionDef:
    target_symbol: str
    definition_site: tuple[int, int, int, int]


_NON_IMPORT = "non-import"
_UNBOUND = "unbound"
Definition = _ImportDef | _ModuleFunctionDef | str
State = dict[str, frozenset[Definition]]


def _join(*states: State) -> State:
    names = set().union(*(state for state in states))
    return {
        name: frozenset().union(*(state.get(name, frozenset({_UNBOUND})) for state in states))
        for name in names
    }


def _bound_names(target: ast.AST) -> set[str]:
    if isinstance(target, ast.Name):
        return {target.id}
    if isinstance(target, (ast.Tuple, ast.List)):
        return set().union(*(_bound_names(item) for item in target.elts), set())
    if isinstance(target, ast.Starred):
        return _bound_names(target.value)
    return set()


def module_name_for_path(root: Path, path: Path) -> str:
    parts = list(path.relative_to(root).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _import_from_module(current: str, node: ast.ImportFrom) -> str | None:
    if node.level == 0:
        return node.module
    package = current.split(".")
    # A non-__init__ module's package excludes its final component.
    if package:
        package.pop()
    ascend = node.level - 1
    if ascend > len(package):
        return None
    base = package[: len(package) - ascend]
    if node.module:
        base.extend(node.module.split("."))
    return ".".join(base) or None


class _Pass:
    def __init__(
        self,
        *,
        source_cid: str,
        module_name: str,
        module_identities: dict[str, dict[str, Any]],
        module_state: State | None = None,
        analyze_nested: bool = True,
    ):
        self.source_cid = source_cid
        self.module_name = module_name
        self.module_identities = module_identities
        self.rows: list[dict[str, Any]] = []
        self.outcomes: dict[tuple[int, int, int, int], str] = {}
        self.module_state = module_state or {}
        self.analyze_nested = analyze_nested
        self.class_outer_states: dict[int, State] = {}

    def _state_only_statement(
        self, node: ast.stmt, state: State, scope: ast.AST
    ) -> State:
        """Transfer one statement without enrolling any use-site testimony."""
        transfer = _Pass(
            source_cid=self.source_cid,
            module_name=self.module_name,
            module_identities=self.module_identities,
            module_state=self.module_state,
            analyze_nested=False,
        )
        return transfer.statement(node, state, scope)

    def _loop_entry(
        self,
        node: ast.For | ast.AsyncFor | ast.While,
        state: State,
        scope: ast.AST,
    ) -> State:
        """Least fixed point for definitions that can arrive on a back-edge."""
        entry = dict(state)
        while True:
            body_in = dict(entry)
            if hasattr(node, "target"):
                for name in _bound_names(node.target):
                    body_in[name] = frozenset({_NON_IMPORT})
            body_out = body_in
            for statement in node.body:
                body_out = self._state_only_statement(statement, body_out, scope)
            widened = _join(state, body_out)
            if widened == entry:
                return entry
            entry = widened

    def expression(self, node: ast.AST | None, state: State, scope: ast.AST) -> None:
        if node is None:
            return
        if isinstance(node, ast.Call):
            self.expression(node.func, state, scope)
            for arg in node.args:
                self.expression(arg, state, scope)
            for keyword in node.keywords:
                self.expression(keyword.value, state, scope)
            if (
                isinstance(node.func, ast.Name)
                and not node.keywords
                and not any(isinstance(arg, ast.Starred) for arg in node.args)
            ):
                self._call(node, state, scope)
            return
        if isinstance(node, ast.Lambda):
            inner = dict(state)
            for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
                inner[arg.arg] = frozenset({_NON_IMPORT})
            if node.args.vararg:
                inner[node.args.vararg.arg] = frozenset({_NON_IMPORT})
            if node.args.kwarg:
                inner[node.args.kwarg.arg] = frozenset({_NON_IMPORT})
            self.expression(node.body, inner, node)
            return
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            inner = dict(state)
            for generator in node.generators:
                self.expression(generator.iter, inner, scope)
                for name in _bound_names(generator.target):
                    inner[name] = frozenset({_NON_IMPORT})
                for condition in generator.ifs:
                    self.expression(condition, inner, scope)
            if isinstance(node, ast.DictComp):
                self.expression(node.key, inner, scope)
                self.expression(node.value, inner, scope)
            else:
                self.expression(node.elt, inner, scope)
            return
        for child in ast.iter_child_nodes(node):
            self.expression(child, state, scope)

    def _call(self, node: ast.Call, state: State, scope: ast.AST) -> None:
        reaching = state.get(node.func.id, frozenset({_UNBOUND}))
        imports = {value for value in reaching if isinstance(value, _ImportDef)}
        nonimports = reaching - imports
        key = (node.lineno, node.col_offset, node.end_lineno, node.end_col_offset)
        if len(imports) == 1 and not nonimports:
            binding = next(iter(imports))
            self.outcomes[key] = "authenticated-import-use"
            use_site = _site(self.source_cid, node)
            use = {
                "kind": "authenticated-import-use",
                "schemaVersion": "1",
                "useSite": use_site,
                "importBindingCid": binding.cid,
            }
            self.rows.append({
                "schemaVersion": "1",
                "kind": "call-contract-demand",
                "authenticatedImportUse": {**use, "cid": _hash(use)},
                "importBinding": json.loads(binding.payload_jcs),
                "targetSymbol": binding.target_symbol,
                "importBindingCid": binding.cid,
                "importSignature": {
                    "formals": [],
                    "sorts": [
                        {"kind": "primitive", "name": "Value"}
                        for _ in node.args
                    ],
                },
                "useSite": use_site,
            })
        elif imports:
            self.outcomes[key] = "ambiguous-lexical-binding"
        elif reaching == frozenset({_NON_IMPORT}):
            self.outcomes[key] = "shadowed-non-import"
        else:
            self.outcomes[key] = "no-lexical-binding"

    def statements(self, statements: Iterable[ast.stmt], state: State, scope: ast.AST) -> State:
        state = dict(state)
        for statement in statements:
            state = self.statement(statement, state, scope)
        return state

    def statement(self, node: ast.stmt, state: State, scope: ast.AST) -> State:
        state = dict(state)
        if isinstance(node, ast.ImportFrom):
            module = _import_from_module(self.module_name, node)
            if module is None:
                return state
            for alias in node.names:
                if alias.name == "*":
                    continue
                local = alias.asname or alias.name
                payload = {
                    "kind": "python-import-binding",
                    "schemaVersion": "1",
                    "sourceCid": self.source_cid,
                    "scope": _site(self.source_cid, scope),
                    "definitionSite": _site(self.source_cid, node),
                    "localSlot": local,
                    "target": {
                        "moduleIdentity": self.module_identities.get(module, {
                            "kind": "unavailable-python-module", "name": module,
                        }),
                        "exportedPath": [alias.name],
                    },
                }
                state[local] = frozenset({
                    _ImportDef(
                        _hash(payload), f"python:{module}.{alias.name}",
                        encode_jcs(_json_value(payload)),
                    )
                })
            return state
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".")[0]
                payload = {
                    "kind": "python-import-binding", "schemaVersion": "1",
                    "sourceCid": self.source_cid, "scope": _site(self.source_cid, scope),
                    "definitionSite": _site(self.source_cid, node), "localSlot": local,
                    "target": {"moduleIdentity": self.module_identities.get(alias.name, {
                        "kind": "unavailable-python-module", "name": alias.name,
                    }), "exportedPath": []},
                }
                state[local] = frozenset({
                    _ImportDef(
                        _hash(payload), f"python:{alias.name}",
                        encode_jcs(_json_value(payload)),
                    )
                })
            return state
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for deco in node.decorator_list:
                self.expression(deco, state, scope)
            for default in (*node.args.defaults, *(d for d in node.args.kw_defaults if d)):
                self.expression(default, state, scope)
            if isinstance(scope, ast.Module):
                state[node.name] = frozenset({
                    _ModuleFunctionDef(
                        f"python:{self.module_name}.{node.name}",
                        (node.lineno, node.col_offset, node.end_lineno, node.end_col_offset),
                    )
                })
            else:
                state[node.name] = frozenset({_NON_IMPORT})
            if not self.analyze_nested:
                return state
            inner = dict(
                self.class_outer_states.get(id(scope), state)
                if isinstance(scope, ast.ClassDef)
                else state
            )
            local_names = _function_locals(node)
            for name in local_names:
                inner[name] = frozenset({_UNBOUND})
            for arg in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs):
                inner[arg.arg] = frozenset({_NON_IMPORT})
            if node.args.vararg:
                inner[node.args.vararg.arg] = frozenset({_NON_IMPORT})
            if node.args.kwarg:
                inner[node.args.kwarg.arg] = frozenset({_NON_IMPORT})
            globals_, _nonlocals = _function_declarations(node)
            for name in globals_:
                inner[name] = self.module_state.get(name, frozenset({_UNBOUND}))
            self.statements(node.body, inner, node)
            return state
        if isinstance(node, ast.ClassDef):
            for expr in (*node.decorator_list, *node.bases):
                self.expression(expr, state, scope)
            state[node.name] = frozenset({_NON_IMPORT})
            if not self.analyze_nested:
                return state
            self.class_outer_states[id(node)] = dict(state)
            self.statements(node.body, dict(state), node)
            return state
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.NamedExpr)):
            value = getattr(node, "value", None)
            self.expression(value, state, scope)
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                for name in _bound_names(target):
                    state[name] = frozenset({_NON_IMPORT})
            return state
        if isinstance(node, ast.If):
            self.expression(node.test, state, scope)
            return _join(
                self.statements(node.body, state, scope),
                self.statements(node.orelse, state, scope),
            )
        if isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
            self.expression(getattr(node, "iter", None), state, scope)
            body_in = self._loop_entry(node, state, scope)
            self.expression(getattr(node, "test", None), body_in, scope)
            if hasattr(node, "target"):
                for name in _bound_names(node.target):
                    body_in[name] = frozenset({_NON_IMPORT})
            body = self.statements(node.body, body_in, scope)
            return _join(
                state,
                body,
                self.statements(node.orelse, _join(state, body), scope),
            )
        if isinstance(node, ast.Try):
            exceptional_prefixes = [dict(state)]
            prefix = dict(state)
            for statement in node.body:
                prefix = self._state_only_statement(statement, prefix, scope)
                exceptional_prefixes.append(prefix)
            handler_entry = _join(*exceptional_prefixes)
            paths = [self.statements(node.body, state, scope)]
            for handler in node.handlers:
                handler_state = dict(handler_entry)
                if handler.name:
                    handler_state[handler.name] = frozenset({_NON_IMPORT})
                paths.append(self.statements(handler.body, handler_state, scope))
            joined = _join(*paths)
            joined = self.statements(node.orelse, joined, scope)
            return self.statements(node.finalbody, joined, scope)
        if isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                self.expression(item.context_expr, state, scope)
                if item.optional_vars:
                    for name in _bound_names(item.optional_vars):
                        state[name] = frozenset({_NON_IMPORT})
            return self.statements(node.body, state, scope)
        if isinstance(node, ast.Delete):
            for target in node.targets:
                for name in _bound_names(target):
                    state[name] = frozenset({_UNBOUND})
            return state
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.expr):
                self.expression(child, state, scope)
        return state


def _function_locals(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    class Collector(ast.NodeVisitor):
        def __init__(self):
            self.globals: set[str] = set()
            self.nonlocals: set[str] = set()
            self.names: set[str] = set()

        def visit_Global(self, child):
            self.globals.update(child.names)

        def visit_Nonlocal(self, child):
            self.nonlocals.update(child.names)

        def visit_Import(self, child):
            self.names.update(alias.asname or alias.name.split(".")[0] for alias in child.names)

        visit_ImportFrom = visit_Import

        def visit_Name(self, child):
            if isinstance(child.ctx, (ast.Store, ast.Del)):
                self.names.add(child.id)

        def visit_FunctionDef(self, child):
            if child is not node:
                self.names.add(child.name)
                return
            for statement in child.body:
                self.visit(statement)

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_ClassDef(self, child):
            self.names.add(child.name)

        def visit_Lambda(self, child):
            return

        def visit_ExceptHandler(self, child):
            if child.name:
                self.names.add(child.name)
            self.generic_visit(child)

    collector = Collector()
    collector.visit(node)
    return collector.names - collector.globals - collector.nonlocals


def _function_declarations(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[set[str], set[str]]:
    class Collector(ast.NodeVisitor):
        def __init__(self):
            self.globals: set[str] = set()
            self.nonlocals: set[str] = set()

        def visit_Global(self, child):
            self.globals.update(child.names)

        def visit_Nonlocal(self, child):
            self.nonlocals.update(child.names)

        def visit_FunctionDef(self, child):
            if child is node:
                for statement in child.body:
                    self.visit(statement)

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_ClassDef(self, child):
            return

        def visit_Lambda(self, child):
            return

    collector = Collector()
    collector.visit(node)
    return collector.globals, collector.nonlocals


def _final_module_state(
    *,
    module: ast.Module,
    source_cid: str,
    module_name: str,
    module_identities: dict[str, dict[str, Any]],
) -> State:
    prepass = _Pass(
        source_cid=source_cid,
        module_name=module_name,
        module_identities=module_identities,
        analyze_nested=False,
    )
    return prepass.statements(module.body, {}, module)


def authenticated_import_uses(
    root: Path, path: Path, source: str, source_cid: str,
    module_identities: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[tuple[int, int, int, int], str]]:
    module = ast.parse(source, filename=str(path))
    module_name = module_name_for_path(root, path)
    identities = module_identities or {}
    module_state = _final_module_state(
        module=module,
        source_cid=source_cid,
        module_name=module_name,
        module_identities=identities,
    )
    runner = _Pass(
        source_cid=source_cid,
        module_name=module_name,
        module_identities=identities,
        module_state=module_state,
    )
    runner.statements(module.body, {}, module)
    return runner.rows, runner.outcomes


def authenticated_module_exports(
    root: Path, path: Path, source: str, source_cid: str
) -> list[dict[str, Any]]:
    """Source-authenticated module-slot declarations for the frozen catalog."""
    module_name = module_name_for_path(root, path)
    module = ast.parse(source, filename=str(path))
    final_state = _final_module_state(
        module=module,
        source_cid=source_cid,
        module_name=module_name,
        module_identities={},
    )
    rows: list[dict[str, Any]] = []
    for local, reaching in sorted(final_state.items()):
        if len(reaching) != 1:
            continue
        definition = next(iter(reaching))
        if isinstance(definition, _ModuleFunctionDef):
            exported = target = definition.target_symbol
            start_line, start_col, end_line, end_col = definition.definition_site
            rows.append({
                "kind": "call-contract-export", "schemaVersion": "1",
                "sourceCid": source_cid,
                "definitionSite": {
                    "sourceCid": source_cid,
                    "startLine": start_line,
                    "startCol": start_col,
                    "endLine": end_line,
                    "endCol": end_col,
                },
                "exportedSymbol": exported, "targetSymbol": target,
            })
        elif isinstance(definition, _ImportDef):
            payload = json.loads(definition.payload_jcs)
            rows.append({
                "kind": "call-contract-export",
                "schemaVersion": "1",
                "sourceCid": source_cid,
                "definitionSite": payload["definitionSite"],
                "exportedSymbol": f"python:{module_name}.{local}",
                "targetSymbol": definition.target_symbol,
            })
    return rows
