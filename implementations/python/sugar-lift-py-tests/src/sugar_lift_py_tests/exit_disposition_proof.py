"""Source-visible ``__exit__`` → authenticated ``ExitDispositionProof``.

Pipeline (required)::

    source import binding (local AST)
    → static re-export follow (module source via SourceOracle only)
    → definition memento (module, class, cid, file, line)
    → prove every completed return is exact None/False (+ implicit fallthrough)

Wording: every reachable **completed** return must be proven exactly ``None``
or ``False``, including implicit ``None`` fallthrough — not merely “no
``return True`` observed.”

**Forbidden** in the manager→definition path: ``importlib.import_module``,
``getattr`` on live objects, MRO walks, ``inspect.getsource*``, and
vendor-specific alias tables (``np``/``pd``). Those recreate recognition
authority through Python execution.

This cut covers class ``__exit__`` methods only. Generator
``@contextmanager`` (e.g. ``util.switchdir``) is a separate proof.
"""

from __future__ import annotations

import ast
import symtable
from dataclasses import dataclass
from typing import Iterator, Literal

from sugar_lift_py_tests.context_manager_contract import NeverSuppresses


@dataclass(frozen=True)
class ExitDispositionProof:
    """Authenticated never-suppresses proof for one defining ``__exit__``."""

    kind: Literal["never_suppresses"]
    module: str
    class_name: str
    method_name: str
    source_cid: str
    filename: str
    definition_lineno: int

    def disposition(self) -> NeverSuppresses:
        return NeverSuppresses()


@dataclass(frozen=True)
class DefinitionMemento:
    """Authenticated definition coordinate before return analysis."""

    module: str
    class_name: str
    source_cid: str
    filename: str
    exit_fn: ast.FunctionDef | ast.AsyncFunctionDef
    determining_classes: tuple[tuple[str, str], ...]


class ExitDispositionUnproven(Exception):
    """Internal reason; callers map this to RuntimeSelected."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


# ---------------------------------------------------------------------------
# Return-value exactness (subject-independent theorem)
# ---------------------------------------------------------------------------


def _is_exact_none_or_false(node: ast.AST | None) -> bool:
    if node is None:
        return True
    if isinstance(node, ast.Constant):
        return node.value is None or node.value is False
    return False


def _iter_direct_stmts(stmt: ast.stmt) -> Iterator[ast.stmt]:
    yield stmt
    if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return
    if isinstance(stmt, ast.Try):
        for s in stmt.body:
            yield from _iter_direct_stmts(s)
        for handler in stmt.handlers:
            for s in handler.body:
                yield from _iter_direct_stmts(s)
        for s in stmt.orelse:
            yield from _iter_direct_stmts(s)
        for s in stmt.finalbody:
            yield from _iter_direct_stmts(s)
        return
    if isinstance(stmt, ast.Match):
        for case in stmt.cases:
            for s in case.body:
                yield from _iter_direct_stmts(s)
        return
    for child in ast.iter_child_nodes(stmt):
        if isinstance(child, ast.stmt):
            yield from _iter_direct_stmts(child)


def _iter_returns(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterator[ast.Return]:
    for stmt in fn.body:
        for s in _iter_direct_stmts(stmt):
            if isinstance(s, ast.Return):
                yield s


def _body_contains_yield(fn: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    class _V(ast.NodeVisitor):
        def __init__(self) -> None:
            self.found = False

        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            return

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
            return

        def visit_ClassDef(self, node: ast.ClassDef) -> None:
            return

        def visit_Lambda(self, node: ast.Lambda) -> None:
            return

        def visit_Yield(self, node: ast.Yield) -> None:
            self.found = True

        def visit_YieldFrom(self, node: ast.YieldFrom) -> None:
            self.found = True

    v = _V()
    for stmt in fn.body:
        v.visit(stmt)
    return v.found


def prove_exit_function_ast(
    fn: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    module: str,
    class_name: str,
    source_cid: str,
    filename: str,
) -> ExitDispositionProof:
    """Prove every completed return of ``fn`` is exact None/False (+ fallthrough)."""
    if fn.name != "__exit__":
        raise ExitDispositionUnproven(f"expected __exit__, got {fn.name!r}")
    if _body_contains_yield(fn):
        raise ExitDispositionUnproven("yield in __exit__ is unproven")
    for ret in _iter_returns(fn):
        if not _is_exact_none_or_false(ret.value):
            kind = type(ret.value).__name__ if ret.value is not None else "bare"
            if isinstance(ret.value, ast.Constant):
                kind = f"Constant({ret.value.value!r})"
            raise ExitDispositionUnproven(
                f"completed return is not exact None/False (got {kind})"
            )
    return ExitDispositionProof(
        kind="never_suppresses",
        module=module,
        class_name=class_name,
        method_name="__exit__",
        source_cid=source_cid,
        filename=filename,
        definition_lineno=fn.lineno,
    )


def prove_from_definition_memento(memento: DefinitionMemento) -> ExitDispositionProof:
    """Apply the return theorem to an already-authenticated definition."""
    return prove_exit_function_ast(
        memento.exit_fn,
        module=memento.module,
        class_name=memento.class_name,
        source_cid=memento.source_cid,
        filename=memento.filename,
    )


# ---------------------------------------------------------------------------
# SourceOracle: module text only (no package execution)
# ---------------------------------------------------------------------------


def _oracle_module(module_name: str) -> tuple[str, str, str] | None:
    """``(source, filename, content_cid)`` via SourceOracle — read, do not import."""
    from sugar_lift_python_source.source_oracle import installed_module_source

    return installed_module_source(module_name)


def _parse_module(module_name: str) -> tuple[ast.Module, str, str, str] | None:
    resolved = _oracle_module(module_name)
    if resolved is None:
        return None
    source, filename, source_cid = resolved
    from sugar_lift_python_source.source_tables import parsed_tree

    try:
        tree = parsed_tree(source, filename)
    except SyntaxError:
        return None
    if not isinstance(tree, ast.Module):
        return None
    return tree, source, filename, source_cid


def _resolve_relative(
    current_module: str, filename: str, level: int, module: str | None
) -> str | None:
    """Absolute module name for a relative import (static)."""
    if level == 0:
        return module
    parts = current_module.split(".")
    is_pkg = filename.endswith("__init__.py")
    pkg_parts = parts if is_pkg else parts[:-1]
    if level - 1 > len(pkg_parts):
        return None
    base = pkg_parts[: len(pkg_parts) - (level - 1)] if level >= 1 else pkg_parts
    if module:
        return ".".join([*base, *module.split(".")]) if base else module
    return ".".join(base) if base else None


def _direct_class_exit(
    cls: ast.ClassDef,
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    return next(
        (
            item
            for item in cls.body
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            and item.name == "__exit__"
        ),
        None,
    )


# ---------------------------------------------------------------------------
# Static name resolution in a module (re-exports, class defs)
# ---------------------------------------------------------------------------


def _module_level_nodes(tree: ast.Module) -> Iterator[ast.AST]:
    """Yield module-level statements, descending only into If/Try/With at top.

    Package ``__init__`` re-exports often live under ``if not SETUP:`` guards.
    Nested function/class bodies are not visited.
    """
    stack: list[ast.AST] = list(tree.body)
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, ast.If):
            stack.extend(node.orelse)
            stack.extend(node.body)
        elif isinstance(node, ast.Try):
            stack.extend(node.finalbody)
            stack.extend(node.orelse)
            for h in node.handlers:
                stack.extend(h.body)
            stack.extend(node.body)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            stack.extend(node.body)


def _direct_bound_names(node: ast.AST) -> Iterator[str]:
    if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
        yield node.name
    elif isinstance(node, ast.Import):
        for alias in node.names:
            yield alias.asname or alias.name.split(".")[0]
    elif isinstance(node, ast.ImportFrom):
        for alias in node.names:
            if alias.name != "*":
                yield alias.asname or alias.name
    elif isinstance(node, ast.Assign):
        for target in node.targets:
            if isinstance(target, ast.Name):
                yield target.id
    elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        yield node.target.id


class _ModuleBindingCensus(ast.NodeVisitor):
    """Count one spelling's module-scope bindings without entering scopes."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.bindings: list[ast.AST] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if node.name == self.name:
            self.bindings.append(node)
        for expr in (*node.decorator_list, *node.bases):
            self.visit(expr)
        for keyword in node.keywords:
            self.visit(keyword.value)
        for type_param in getattr(node, "type_params", ()):
            self.visit(type_param)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node.name == self.name:
            self.bindings.append(node)
        self._visit_function_header(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        if node.name == self.name:
            self.bindings.append(node)
        self._visit_function_header(node)

    def _visit_function_header(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> None:
        args = node.args
        for expr in (
            *node.decorator_list,
            *args.defaults,
            *(default for default in args.kw_defaults if default is not None),
        ):
            self.visit(expr)
        for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs):
            if arg.annotation is not None:
                self.visit(arg.annotation)
        for arg in (args.vararg, args.kwarg):
            if arg is not None and arg.annotation is not None:
                self.visit(arg.annotation)
        if node.returns is not None:
            self.visit(node.returns)
        for type_param in getattr(node, "type_params", ()):
            self.visit(type_param)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        del node

    def visit_Import(self, node: ast.Import) -> None:
        self.bindings.extend(
            node
            for alias in node.names
            if (alias.asname or alias.name.split(".")[0]) == self.name
        )

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if any(alias.name == "*" for alias in node.names):
            self.bindings.append(node)
        self.bindings.extend(
            node
            for alias in node.names
            if alias.name != "*" and (alias.asname or alias.name) == self.name
        )

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == self.name:
                self.bindings.append(node)
            else:
                self.visit(target)
        self.visit(node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name) and node.target.id == self.name:
            self.bindings.append(node)
        else:
            self.visit(node.target)
        self.visit(node.annotation)
        if node.value is not None:
            self.visit(node.value)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        if isinstance(node.target, ast.Name) and node.target.id == self.name:
            self.bindings.append(node)
        else:
            self.visit(node.target)
        self.visit(node.value)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)) and node.id == self.name:
            self.bindings.append(node)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name == self.name:
            self.bindings.append(node)
        self.generic_visit(node)

    def visit_MatchAs(self, node: ast.MatchAs) -> None:
        if node.name == self.name:
            self.bindings.append(node)
        self.generic_visit(node)

    def visit_MatchStar(self, node: ast.MatchStar) -> None:
        if node.name == self.name:
            self.bindings.append(node)


def _unique_unconditional_binding(tree: ast.Module, name: str) -> ast.AST | None:
    """Return one direct module binding; all ambiguity remains unproven."""
    census = _ModuleBindingCensus(name)
    census.visit(tree)
    if len(census.bindings) != 1:
        return None
    binding = census.bindings[0]
    if not any(name in set(_direct_bound_names(node)) for node in tree.body):
        return None
    return binding


def _class_creation_is_stable(node: ast.ClassDef) -> bool:
    """Whether source pins the class object created for this definition."""
    if node.decorator_list or node.keywords:
        return False
    if any(isinstance(base, ast.Subscript) for base in node.bases):
        return False
    transforming_hooks = {"__init_subclass__", "__class_getitem__"}
    return not any(
        isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
        and item.name in transforming_hooks
        for item in node.body
    )


def _dotted_ast(node: ast.AST) -> tuple[str, ...] | None:
    if isinstance(node, ast.Name):
        return (node.id,)
    if isinstance(node, ast.Attribute):
        base = _dotted_ast(node.value)
        if base is not None:
            return (*base, node.attr)
    return None


def _module_uses_class_unsafely(
    tree: ast.Module, class_coordinate: tuple[str, ...]
) -> bool:
    """Refuse every detectable use except aliasing, basing, and managed use.

    The coordinate is either a local class spelling (``Manager``) or the
    authenticated subject head path (``manager.Manager``). Simple module-scope
    aliases are closed to a fixed point before uses are classified.
    """
    aliases: set[str] = set()
    alias_nodes: set[int] = set()

    def is_coordinate(node: ast.AST) -> bool:
        dotted = _dotted_ast(node)
        return dotted == class_coordinate or (
            isinstance(node, ast.Name) and node.id in aliases
        )

    assignments = [
        node
        for node in _module_level_nodes(tree)
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
    ]
    coordinate_binding_nodes = {
        id(assignment.targets[0])
        for assignment in assignments
        if len(class_coordinate) == 1
        and assignment.targets[0].id == class_coordinate[0]
    }
    changed = True
    while changed:
        changed = False
        for assignment in assignments:
            target = assignment.targets[0]
            if target.id in aliases or not is_coordinate(assignment.value):
                continue
            aliases.add(target.id)
            alias_nodes.update((id(target), id(assignment.value)))
            changed = True

    parents: dict[int, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[id(child)] = parent

    for node in ast.walk(tree):
        if not is_coordinate(node):
            continue
        if id(node) in alias_nodes or id(node) in coordinate_binding_nodes:
            continue
        parent = parents.get(id(node))
        if isinstance(parent, ast.ClassDef) and any(node is b for b in parent.bases):
            continue
        if isinstance(parent, ast.Call) and parent.func is node:
            call_parent = parents.get(id(parent))
            if (
                isinstance(call_parent, ast.withitem)
                and call_parent.context_expr is parent
            ):
                continue
        return True
    return False


def _lookup_name_in_module(
    module_name: str, name: str, *, depth: int = 0
) -> DefinitionMemento | None:
    """Find class ``name`` or follow static import re-exports (depth-capped)."""
    if depth > 12 or not name or not module_name:
        return None
    parsed = _parse_module(module_name)
    if parsed is None:
        return None
    tree, _source, filename, source_cid = parsed
    if _module_uses_class_unsafely(tree, (name,)):
        return None

    # 1. Class definition in this module. A direct override owns the
    # disposition. Otherwise admit only one statically named base; multiple or
    # computed bases remain ambiguous and therefore unproven.
    for node in _module_level_nodes(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            if _unique_unconditional_binding(tree, name) is not node:
                return None
            if not _class_creation_is_stable(node):
                return None
            exit_fn = _direct_class_exit(node)
            if exit_fn is not None:
                return DefinitionMemento(
                    module=module_name,
                    class_name=name,
                    source_cid=source_cid,
                    filename=filename,
                    exit_fn=exit_fn,
                    determining_classes=((module_name, name),),
                )
            if len(node.bases) != 1 or not isinstance(node.bases[0], ast.Name):
                return None
            binding = _unique_unconditional_binding(tree, node.bases[0].id)
            if (
                binding is None
                or getattr(binding, "lineno", node.lineno) >= node.lineno
            ):
                return None
            inherited = _lookup_name_in_module(
                module_name, node.bases[0].id, depth=depth + 1
            )
            if inherited is None:
                return None
            return DefinitionMemento(
                module=inherited.module,
                class_name=inherited.class_name,
                source_cid=inherited.source_cid,
                filename=inherited.filename,
                exit_fn=inherited.exit_fn,
                determining_classes=(
                    (module_name, name),
                    *inherited.determining_classes,
                ),
            )

    binding = _unique_unconditional_binding(tree, name)
    if binding is None:
        return None

    # 2. from X import name / from X import Y as name / star-import follow
    for node in _module_level_nodes(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        for alias in node.names:
            if alias.name == "*":
                if binding is not node:
                    return None
                target = _resolve_relative(
                    module_name, filename, node.level, node.module
                )
                if target is None:
                    continue
                hit = _lookup_name_in_module(target, name, depth=depth + 1)
                if hit is not None:
                    return hit
                continue
            bound = alias.asname or alias.name
            if bound != name:
                continue
            if binding is not node:
                return None
            target = _resolve_relative(
                module_name, filename, node.level, node.module
            )
            if target is None:
                return None
            return _lookup_name_in_module(target, alias.name, depth=depth + 1)

    # 3. Simple alias: name = OtherName (same module)
    for node in _module_level_nodes(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            t = node.targets[0]
            if isinstance(t, ast.Name) and t.id == name and isinstance(node.value, ast.Name):
                if binding is not node:
                    return None
                return _lookup_name_in_module(
                    module_name, node.value.id, depth=depth + 1
                )

    return None


def _authenticated_export_names(module_name: str) -> tuple[str, ...]:
    """Uniquely bound names a statically loaded module exposes."""
    parsed = _parse_module(module_name)
    if parsed is None:
        return ()
    tree, _source, _filename, _source_cid = parsed
    candidates = {
        name
        for node in _module_level_nodes(tree)
        for name in _direct_bound_names(node)
    }
    return tuple(
        sorted(
            name
            for name in candidates
            if _unique_unconditional_binding(tree, name) is not None
        )
    )


def _local_import_bindings(
    source: str,
) -> tuple[ast.Module | None, dict[str, tuple[str, str, ast.AST]]]:
    """Map local bound name → (kind, payload).

    kind ``module``: payload is absolute module name (``import numpy as np``).
    kind ``from``: payload is ``module.name`` to look up
    (``from pandas import option_context``).
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None, {}
    out: dict[str, tuple[str, str, ast.AST]] = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    # import numpy as np → np denotes module numpy
                    out[alias.asname] = ("module", alias.name, node)
                else:
                    # import a.b.c binds only top-level name `a`
                    top = alias.name.split(".")[0]
                    out[top] = ("module", top, node)
        if isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            for alias in node.names:
                if alias.name == "*":
                    continue
                bound = alias.asname or alias.name
                out[bound] = ("from", f"{node.module}.{alias.name}", node)
    return tree, out


def _dotted_of_sugar_node(node) -> list[str] | None:
    """Attribute/Name chain as component list, or None if not pure."""
    from sugar_source_tree.nodes import Attribute, Name

    if isinstance(node, Name):
        return [node.id]
    if isinstance(node, Attribute):
        base = _dotted_of_sugar_node(node.value)
        if base is None:
            return None
        return [*base, node.attr]
    return None


def _lexically_bound_at_coordinate(
    source: str, filename: str, line: int
) -> frozenset[str]:
    """Names local to any function enclosing ``line``.

    AST supplies the lexical nesting coordinate; ``symtable`` supplies
    Python's whole-scope binding decision, so conditional/late assignments
    and captured outer locals are refused without executing the module.
    """
    try:
        tree = ast.parse(source)
        root = symtable.symtable(source, filename, "exec")
    except (SyntaxError, ValueError):
        return frozenset()

    enclosing_scopes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and getattr(node, "end_lineno", None) is not None
        and node.lineno < line <= node.end_lineno
    ]
    if enclosing_scopes:
        immediate_scope = min(
            enclosing_scopes,
            key=lambda node: (node.end_lineno - node.lineno, -node.lineno),
        )
        if isinstance(immediate_scope, ast.ClassDef):
            # Class bodies execute through LOAD_NAME against a live namespace,
            # which may be supplied by metaclass __prepare__. Source imports
            # cannot authenticate that lookup. Methods are inner functions and
            # therefore do not take this refusal arm.
            return frozenset({"*"})

    tables = []
    pending = list(root.get_children())
    while pending:
        table = pending.pop()
        tables.append(table)
        pending.extend(table.get_children())

    bound: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        end_line = getattr(node, "end_lineno", None)
        if end_line is None or not (node.lineno < line <= end_line):
            continue
        matches = [
            table
            for table in tables
            if table.get_name() == node.name and table.get_lineno() == node.lineno
        ]
        if len(matches) != 1:
            # Ambiguous scope testimony can only reduce admission.
            return frozenset({"*"})
        bound.update(
            symbol.get_name()
            for symbol in matches[0].get_symbols()
            if symbol.is_local() and not symbol.get_name().startswith(".")
        )
    return frozenset(bound)


def resolve_definition_memento_from_manager_expr(
    manager_node,
    *,
    lexically_bound_names: frozenset[str] = frozenset(),
) -> DefinitionMemento | None:
    """Static import binding → SourceOracle modules → class ``__exit__`` memento.

    No package execution. No vendor alias table.
    """
    from sugar_source_tree.nodes import Call, Name

    if not isinstance(manager_node, Call):
        return None
    unit = manager_node.unit
    source = getattr(unit, "source", None)
    if not source:
        return None
    source_tree, bindings = _local_import_bindings(source)
    if source_tree is None:
        return None
    parts = _dotted_of_sugar_node(manager_node.func)
    if not parts:
        return None

    head, *rest = parts
    try:
        manager_line = manager_node.line_col_span().start_line
    except Exception:
        return None
    coordinate_bound = _lexically_bound_at_coordinate(
        source, getattr(unit, "filename", "<unknown>"), manager_line
    )
    if "*" in coordinate_bound or head in (lexically_bound_names | coordinate_bound):
        return None
    if head not in bindings:
        return None
    kind, payload, binding_node = bindings[head]
    if payload is None:
        return None
    if _unique_unconditional_binding(source_tree, head) is not binding_node:
        return None

    if kind == "module":
        # head is a module binding; rest are attributes into that package.
        if len(rest) != 1:
            return None
        memento = _lookup_name_in_module(payload, rest[0])

    elif kind == "from":
        # from mod import name [as head]; rest must be empty for Class() form
        if rest:
            # from mod import pkg; pkg.Class — rare; treat payload module.attr
            # payload is mod.name; if rest, unproven unless name is submodule
            return None
        # payload "pandas.option_context" or "numpy.errstate" style
        if "." not in payload:
            return None
        mod, _, name = payload.rpartition(".")
        memento = _lookup_name_in_module(mod, name)

    else:
        return None

    if memento is None:
        return None

    subject_coordinates = {tuple(parts)}
    determining = set(memento.determining_classes)

    def resolves_to(
        class_module: str, class_name: str, target: tuple[str, str]
    ) -> bool:
        resolved = _lookup_name_in_module(class_module, class_name)
        return (
            resolved is not None
            and resolved.determining_classes
            and resolved.determining_classes[0] == target
        )

    for local_name, (binding_kind, binding_payload, _node) in bindings.items():
        if binding_kind == "from" and "." in binding_payload:
            bound_module, _, bound_name = binding_payload.rpartition(".")
            for target in determining:
                if (bound_module, bound_name) == target or resolves_to(
                    bound_module, bound_name, target
                ):
                    subject_coordinates.add((local_name,))
        elif binding_kind == "module":
            for exported_name in _authenticated_export_names(binding_payload):
                resolved = _lookup_name_in_module(binding_payload, exported_name)
                if (
                    resolved is not None
                    and resolved.determining_classes
                    and resolved.determining_classes[0] in determining
                ):
                    subject_coordinates.add((local_name, exported_name))

    if any(
        _module_uses_class_unsafely(source_tree, coordinate)
        for coordinate in subject_coordinates
    ):
        return None
    return memento


def prove_exit_disposition_from_manager_expr(
    manager_node,
    *,
    lexically_bound_names: frozenset[str] = frozenset(),
) -> ExitDispositionProof | None:
    """Static resolve + return proof. None → RuntimeSelected."""
    memento = resolve_definition_memento_from_manager_expr(
        manager_node, lexically_bound_names=lexically_bound_names
    )
    if memento is None:
        return None
    try:
        return prove_from_definition_memento(memento)
    except ExitDispositionUnproven:
        return None


# ---------------------------------------------------------------------------
# Executable floor: no reflection authority in this module's resolve path
# ---------------------------------------------------------------------------

_FORBIDDEN_RESOLVE_TOKENS = (
    "importlib",
    "inspect.getsource",
    "inspect.getfile",
    "inspect.getmodule",
    "inspect.getattr_static",
    "__mro__",
    "_IMPORT_ALIASES",
    "prove_never_suppresses_for_class",
    "import_module",
)


def assert_no_runtime_resolve_authority() -> None:
    """Floor: manager→definition path must not use runtime reflection tokens."""
    import inspect as _inspect

    # Only the resolve/lookup source is constrained (not this assert helper).
    src = _inspect.getsource(resolve_definition_memento_from_manager_expr)
    src += _inspect.getsource(_lookup_name_in_module)
    src += _inspect.getsource(_local_import_bindings)
    src += _inspect.getsource(prove_exit_disposition_from_manager_expr)
    src += _inspect.getsource(_oracle_module)
    src += _inspect.getsource(_parse_module)
    for token in _FORBIDDEN_RESOLVE_TOKENS:
        if token in src:
            raise AssertionError(
                f"exit disposition resolve path must not contain {token!r}"
            )
