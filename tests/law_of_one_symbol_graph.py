"""Source-ordered, scope-correct symbol graph for the LAW_OF_ONE auditor."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, order=True)
class Symbol:
    module: str
    lexical: tuple[str, ...]
    name: str
    path: Path
    line: int

    @property
    def qualified(self) -> str:
        return ".".join((self.module, *self.lexical, self.name))


@dataclass(frozen=True)
class CallEdge:
    caller: Symbol
    path: Path
    line: int
    targets: tuple[Symbol, ...]
    dynamic: bool
    expression: str


@dataclass(frozen=True)
class BindingEdge:
    owner: Symbol
    path: Path
    line: int
    name: str
    targets: tuple[Symbol, ...]
    kind: str


class SymbolGraph:
    """Conservative Python name resolution at each source program point.

    A set-valued environment is propagated through control-flow joins.  Empty
    sets mean a local binding exists but its value is not statically known;
    they deliberately stop lexical lookup rather than falling through.
    """

    def __init__(self, modules: dict[str, tuple[Path, ast.Module]]) -> None:
        self.modules = modules
        self.definitions: dict[str, Symbol] = {}
        self.calls: list[CallEdge] = []
        self.bindings: list[BindingEdge] = []
        self.discovery_errors: list[str] = []
        self._node_symbols: dict[ast.AST, Symbol] = {}
        self._class_symbols: set[Symbol] = set()
        self._module_symbols: dict[str, Symbol] = {}
        self._exports: dict[str, dict[str, set[Symbol]]] = {}
        self._index_definitions()
        self._resolve_imports_to_fixed_point()
        self._walk_programs()

    def _index_definitions(self) -> None:
        def visit(module: str, path: Path, body: list[ast.stmt], lexical: tuple[str, ...]) -> None:
            for node in body:
                if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                    symbol = Symbol(module, lexical, node.name, path, node.lineno)
                    self.definitions[symbol.qualified] = symbol
                    self._node_symbols[node] = symbol
                    if isinstance(node, ast.ClassDef):
                        self._class_symbols.add(symbol)
                    visit(module, path, node.body, (*lexical, node.name))
                else:
                    for _field, value in ast.iter_fields(node):
                        if isinstance(value, list) and value and all(
                            isinstance(item, ast.stmt) for item in value
                        ):
                            visit(module, path, value, lexical)
                        elif isinstance(value, ast.ExceptHandler):
                            visit(module, path, value.body, lexical)
                        elif isinstance(value, list):
                            for item in value:
                                if isinstance(item, ast.ExceptHandler):
                                    visit(module, path, item.body, lexical)

        for module, (path, tree) in self.modules.items():
            root = Symbol(module, (), "<module>", path, 1)
            self._module_symbols[module] = root
            self.definitions[root.qualified] = root
            visit(module, path, tree.body, ())

    def _absolute_import(self, current: str, node: ast.ImportFrom) -> str:
        if node.level == 0:
            return node.module or ""
        package = current.split(".")[:-1]
        package = package[: max(0, len(package) - (node.level - 1))]
        suffix = (node.module or "").split(".") if node.module else []
        return ".".join((*package, *suffix))

    def _resolve_imports_to_fixed_point(self) -> None:
        exports: dict[str, dict[str, set[Symbol]]] = {name: {} for name in self.modules}
        for qualified, symbol in self.definitions.items():
            if symbol.name != "<module>" and not symbol.lexical:
                exports[symbol.module].setdefault(symbol.name, set()).add(symbol)

        changed = True
        while changed:
            changed = False
            for module, (_, tree) in self.modules.items():
                proposed = {name: set(values) for name, values in exports[module].items()}
                for node in tree.body:
                    if isinstance(node, ast.Import):
                        for item in node.names:
                            imported = self._module_symbols.get(item.name)
                            if imported is not None:
                                proposed[item.asname or item.name.split(".")[0]] = {imported}
                    elif isinstance(node, ast.ImportFrom):
                        source = self._absolute_import(module, node)
                        for item in node.names:
                            if item.name == "*":
                                for name, values in exports.get(source, {}).items():
                                    if not name.startswith("_"):
                                        proposed.setdefault(name, set()).update(values)
                            else:
                                values = exports.get(source, {}).get(item.name, set())
                                if values:
                                    proposed[item.asname or item.name] = set(values)
                    elif isinstance(node, (ast.Assign, ast.AnnAssign)) and node.value is not None:
                        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                        values = self._resolve_expr(node.value, proposed)
                        for target in targets:
                            if isinstance(target, ast.Name) and values:
                                proposed[target.id] = set(values)
                if proposed != exports[module]:
                    exports[module] = proposed
                    changed = True
        self._exports = exports

    @staticmethod
    def _join(environments: list[dict[str, set[Symbol]]]) -> dict[str, set[Symbol]]:
        names = set().union(*(env.keys() for env in environments))
        joined: dict[str, set[Symbol]] = {}
        for name in names:
            present = [env[name] for env in environments if name in env]
            # Absence on one path means the pre-branch lexical binding remains
            # possible; callers pass that pre-state as an explicit arm.
            joined[name] = set().union(*present)
        return joined

    def _resolve_expr(self, expr: ast.AST, env: dict[str, set[Symbol]]) -> set[Symbol]:
        if isinstance(expr, ast.Name):
            return set(env.get(expr.id, ()))
        if isinstance(expr, ast.Attribute):
            found: set[Symbol] = set()
            for base in self._resolve_expr(expr.value, env):
                if base.name == "<module>":
                    found.update(self._exports.get(base.module, {}).get(expr.attr, ()))
                target = self.definitions.get(f"{base.qualified}.{expr.attr}")
                if target is not None:
                    found.add(target)
            return found
        return set()

    def _record_call(self, node: ast.Call, owner: Symbol, env: dict[str, set[Symbol]]) -> None:
        targets = tuple(sorted(self._resolve_expr(node.func, env)))
        expression = ast.unparse(node.func)
        dynamic = not targets
        self.calls.append(CallEdge(owner, owner.path, node.lineno, targets, dynamic, expression))
        if dynamic:
            self.discovery_errors.append(
                f"{owner.path}:{node.lineno}: unresolved call edge {expression!r} in {owner.qualified}"
            )

    def _walk_expr(self, node: ast.AST, owner: Symbol, env: dict[str, set[Symbol]]) -> None:
        # ast.walk is safe for expression children because bindings cannot
        # change between them; statement order is handled only by _walk_body.
        for child in ast.walk(node):
            if isinstance(child, ast.Call):
                self._record_call(child, owner, env)

    def _bind(self, owner: Symbol, node: ast.AST, name: str, values: set[Symbol], kind: str, env: dict[str, set[Symbol]]) -> None:
        env[name] = set(values)
        self.bindings.append(BindingEdge(owner, owner.path, getattr(node, "lineno", 1), name, tuple(sorted(values)), kind))

    @staticmethod
    def _declared_locals(body: list[ast.stmt]) -> set[str]:
        """Names Python makes local for the whole lexical function scope."""
        locals_: set[str] = set()
        global_names: set[str] = set()
        nonlocal_names: set[str] = set()

        def visit(statement: ast.stmt) -> None:
            if isinstance(statement, ast.Global):
                global_names.update(statement.names)
                return
            if isinstance(statement, ast.Nonlocal):
                nonlocal_names.update(statement.names)
                return
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                locals_.add(statement.name)
                return
            if isinstance(statement, ast.Import):
                locals_.update(item.asname or item.name.split(".")[0] for item in statement.names)
            elif isinstance(statement, ast.ImportFrom):
                locals_.update(item.asname or item.name for item in statement.names if item.name != "*")
            elif isinstance(statement, ast.ExceptHandler) and statement.name:
                locals_.add(statement.name)
            for child in ast.iter_child_nodes(statement):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
                    continue
                if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                    locals_.add(child.id)
                elif isinstance(child, ast.stmt):
                    visit(child)

        for statement in body:
            visit(statement)
        return locals_ - global_names - nonlocal_names

    def _walk_body(self, body: list[ast.stmt], owner: Symbol, incoming: dict[str, set[Symbol]]) -> dict[str, set[Symbol]]:
        env = {name: set(values) for name, values in incoming.items()}
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                symbol = self._node_symbols[node]
                self._bind(owner, node, node.name, {symbol}, "definition", env)
                inherited = self._exports[owner.module] if owner in self._class_symbols else env
                child_env = {name: set(values) for name, values in inherited.items()}
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for name in self._declared_locals(node.body):
                        child_env[name] = set()
                    args = (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
                    if node.args.vararg:
                        args = (*args, node.args.vararg)
                    if node.args.kwarg:
                        args = (*args, node.args.kwarg)
                    for arg in args:
                        self._bind(symbol, arg, arg.arg, set(), "parameter", child_env)
                self._walk_body(node.body, symbol, child_env)
                continue
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.Import):
                    for item in node.names:
                        target = self._module_symbols.get(item.name)
                        self._bind(owner, node, item.asname or item.name.split(".")[0], {target} if target else set(), "import", env)
                else:
                    source = self._absolute_import(owner.module, node)
                    for item in node.names:
                        if item.name == "*":
                            for name, values in self._exports.get(source, {}).items():
                                if not name.startswith("_"):
                                    self._bind(owner, node, name, values, "reexport" if owner.name == "<module>" else "import", env)
                        else:
                            values = self._exports.get(source, {}).get(item.name, set())
                            self._bind(owner, node, item.asname or item.name, values, "reexport" if owner.name == "<module>" else "import", env)
                continue
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
                value = node.value
                if value is None:
                    targets = [node.target]
                    for target in targets:
                        for name_node in ast.walk(target):
                            if isinstance(name_node, ast.Name) and isinstance(name_node.ctx, ast.Store):
                                self._bind(owner, node, name_node.id, set(), "annotation", env)
                    continue
                self._walk_expr(value, owner, env)
                values = self._resolve_expr(value, env)
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    for name_node in ast.walk(target):
                        if isinstance(name_node, ast.Name) and isinstance(name_node.ctx, ast.Store):
                            self._bind(owner, node, name_node.id, values, "alias" if values else "assignment", env)
                continue
            if isinstance(node, ast.Delete):
                for target in node.targets:
                    for name_node in ast.walk(target):
                        if isinstance(name_node, ast.Name):
                            self._bind(owner, node, name_node.id, set(), "delete", env)
                continue
            if isinstance(node, ast.If):
                self._walk_expr(node.test, owner, env)
                left = self._walk_body(node.body, owner, env)
                right = self._walk_body(node.orelse, owner, env)
                env = self._join([left, right])
                continue
            if isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
                if isinstance(node, (ast.For, ast.AsyncFor)):
                    self._walk_expr(node.iter, owner, env)
                    loop_env = {name: set(values) for name, values in env.items()}
                    for name_node in ast.walk(node.target):
                        if isinstance(name_node, ast.Name) and isinstance(name_node.ctx, ast.Store):
                            self._bind(owner, node, name_node.id, set(), "loop-target", loop_env)
                else:
                    self._walk_expr(node.test, owner, env)
                    loop_env = env
                body_env = self._walk_body(node.body, owner, loop_env)
                else_env = self._walk_body(node.orelse, owner, self._join([env, body_env]))
                env = self._join([env, body_env, else_env])
                continue
            if isinstance(node, (ast.With, ast.AsyncWith)):
                with_env = {name: set(values) for name, values in env.items()}
                for item in node.items:
                    self._walk_expr(item.context_expr, owner, env)
                    if item.optional_vars:
                        for name_node in ast.walk(item.optional_vars):
                            if isinstance(name_node, ast.Name) and isinstance(name_node.ctx, ast.Store):
                                self._bind(owner, node, name_node.id, set(), "with-target", with_env)
                env = self._walk_body(node.body, owner, with_env)
                continue
            if isinstance(node, (ast.Try, ast.TryStar)):
                arms = [self._walk_body(node.body, owner, env)]
                for handler in node.handlers:
                    handler_env = {name: set(values) for name, values in env.items()}
                    if handler.name:
                        self._bind(owner, handler, handler.name, set(), "except-target", handler_env)
                    arm = self._walk_body(handler.body, owner, handler_env)
                    if handler.name:
                        arm[handler.name] = set()
                    arms.append(arm)
                joined = self._join(arms)
                joined = self._walk_body(node.orelse, owner, joined)
                env = self._walk_body(node.finalbody, owner, joined)
                continue
            self._walk_expr(node, owner, env)
        return env

    def _walk_programs(self) -> None:
        for module, (_, tree) in self.modules.items():
            root = self._module_symbols[module]
            self._walk_body(tree.body, root, {})
