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

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node.name == self.name:
            self.bindings.append(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        if node.name == self.name:
            self.bindings.append(node)

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


def _has_unique_unconditional_binding(
    tree: ast.Module, name: str, *, before: ast.ClassDef
) -> bool:
    """One prior direct module binding only; all ambiguity stays unproven."""
    census = _ModuleBindingCensus(name)
    census.visit(tree)
    if len(census.bindings) != 1:
        return False
    binding = census.bindings[0]
    if getattr(binding, "lineno", before.lineno) >= before.lineno:
        return False
    return any(name in set(_direct_bound_names(node)) for node in tree.body)


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

    # 1. Class definition in this module. A direct override owns the
    # disposition. Otherwise admit only one statically named base; multiple or
    # computed bases remain ambiguous and therefore unproven.
    for node in _module_level_nodes(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            exit_fn = _direct_class_exit(node)
            if exit_fn is not None:
                return DefinitionMemento(
                    module=module_name,
                    class_name=name,
                    source_cid=source_cid,
                    filename=filename,
                    exit_fn=exit_fn,
                )
            if len(node.bases) != 1 or not isinstance(node.bases[0], ast.Name):
                return None
            if not _has_unique_unconditional_binding(
                tree, node.bases[0].id, before=node
            ):
                return None
            return _lookup_name_in_module(
                module_name, node.bases[0].id, depth=depth + 1
            )

    # 2. from X import name / from X import Y as name / star-import follow
    for node in _module_level_nodes(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        for alias in node.names:
            if alias.name == "*":
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
                return _lookup_name_in_module(
                    module_name, node.value.id, depth=depth + 1
                )

    return None


def _local_import_bindings(source: str) -> dict[str, tuple[str, str]]:
    """Map local bound name → (kind, payload).

    kind ``module``: payload is absolute module name (``import numpy as np``).
    kind ``from``: payload is ``module.name`` to look up
    (``from pandas import option_context``).
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return {}
    out: dict[str, tuple[str, str]] = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.asname:
                    # import numpy as np → np denotes module numpy
                    out[alias.asname] = ("module", alias.name)
                else:
                    # import a.b.c binds only top-level name `a`
                    top = alias.name.split(".")[0]
                    out[top] = ("module", top)
        if isinstance(node, ast.ImportFrom) and node.module is not None and node.level == 0:
            for alias in node.names:
                if alias.name == "*":
                    continue
                bound = alias.asname or alias.name
                out[bound] = ("from", f"{node.module}.{alias.name}")
    return out


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


def resolve_definition_memento_from_manager_expr(
    manager_node,
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
    bindings = _local_import_bindings(source)
    parts = _dotted_of_sugar_node(manager_node.func)
    if not parts:
        return None

    head, *rest = parts
    if head not in bindings:
        return None
    kind, payload = bindings[head]
    if payload is None:
        return None

    if kind == "module":
        # head is a module binding; rest are attributes into that package.
        if not rest:
            return None  # calling a module is not a class CM
        module_name = payload
        # Walk attributes: each step is either a submodule or a name in module
        for i, attr in enumerate(rest):
            is_last = i == len(rest) - 1
            if is_last:
                return _lookup_name_in_module(module_name, attr)
            # Non-final: treat as submodule package path
            module_name = f"{module_name}.{attr}"
        return None

    if kind == "from":
        # from mod import name [as head]; rest must be empty for Class() form
        if rest:
            # from mod import pkg; pkg.Class — rare; treat payload module.attr
            # payload is mod.name; if rest, unproven unless name is submodule
            return None
        # payload "pandas.option_context" or "numpy.errstate" style
        if "." not in payload:
            return None
        mod, _, name = payload.rpartition(".")
        return _lookup_name_in_module(mod, name)

    return None


def prove_exit_disposition_from_manager_expr(
    manager_node,
) -> ExitDispositionProof | None:
    """Static resolve + return proof. None → RuntimeSelected."""
    memento = resolve_definition_memento_from_manager_expr(manager_node)
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
