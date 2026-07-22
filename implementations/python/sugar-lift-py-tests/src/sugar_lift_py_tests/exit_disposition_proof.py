"""Source-visible ``__exit__`` → authenticated ``ExitDispositionProof``.

Wording (exact): every reachable **completed** return of ``__exit__`` must be
proven exactly ``None`` or ``False``, including implicit ``None`` fallthrough.
It is not enough that no ``return True`` was observed.

Unknown, symbolic, delegated, or dynamically dispatched returns remain
unproven → caller keeps ``RuntimeSelected``. Exit **halts** (raise inside
``__exit__``) do not decide suppression; the proof covers suppression only.

This cut covers class ``__exit__`` methods only. Generator
``@contextmanager`` (e.g. ``util.switchdir``) is a separate proof.
"""

from __future__ import annotations

import ast
import importlib
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


class ExitDispositionUnproven(Exception):
    """Internal reason; callers map this to RuntimeSelected."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _is_exact_none_or_false(node: ast.AST | None) -> bool:
    """True only for bare return / literal ``None`` / literal ``False``."""
    if node is None:
        return True  # bare ``return`` → None
    if isinstance(node, ast.Constant):
        return node.value is None or node.value is False
    return False


def _iter_direct_stmts(stmt: ast.stmt) -> Iterator[ast.stmt]:
    """Yield stmt and nested stmts, skipping nested function/class bodies.

    ``Try`` handlers are not ``ast.stmt`` children under generic walk — visit
    them explicitly so ``except: return True`` is not invisible.
    """
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
    """True if ``fn`` body yields (skipping nested defs/classes/lambdas)."""

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

    # Implicit None fallthrough at end of __exit__ is a completed exit and is
    # proven (Python: missing return → None). No extra observation required.
    return ExitDispositionProof(
        kind="never_suppresses",
        module=module,
        class_name=class_name,
        method_name="__exit__",
        source_cid=source_cid,
        filename=filename,
        definition_lineno=fn.lineno,
    )


def _defining_class_and_exit(cls: type) -> tuple[type, object] | None:
    for c in cls.__mro__:
        if c is object:
            continue
        if "__exit__" in getattr(c, "__dict__", {}):
            return c, c.__dict__["__exit__"]
    return None


def _find_class_exit_ast(
    tree: ast.Module, class_name: str
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for item in node.body:
                if (
                    isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and item.name == "__exit__"
                ):
                    return item
    return None


def prove_never_suppresses_for_class(cls: type) -> ExitDispositionProof | None:
    """SourceOracle-backed proof for a concrete class's defining ``__exit__``.

    Uses the defining method's on-disk module (not a re-export module such as
    ``numpy.__init__`` that only aliases the class).
    """
    import inspect

    found = _defining_class_and_exit(cls)
    if found is None:
        return None
    defining_cls, method = found

    # Prefer the module that *defines* the function object (not the re-export).
    method_mod = getattr(method, "__module__", None) or getattr(
        defining_cls, "__module__", None
    )
    if not method_mod:
        return None

    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_lift_python_source.source_oracle import installed_module_source
    from sugar_lift_python_source.source_tables import parsed_tree

    resolved = installed_module_source(method_mod)
    # If re-export module lacks the class body, resolve via source file of method.
    source: str | None = None
    filename: str | None = None
    source_cid: str | None = None
    if resolved is not None:
        source, filename, source_cid = resolved
        tree = None
        try:
            tree = parsed_tree(source, filename)
        except SyntaxError:
            tree = None
        fn = (
            _find_class_exit_ast(tree, defining_cls.__name__)
            if isinstance(tree, ast.Module)
            else None
        )
        if fn is not None:
            try:
                return prove_exit_function_ast(
                    fn,
                    module=method_mod,
                    class_name=defining_cls.__name__,
                    source_cid=source_cid,
                    filename=filename,
                )
            except ExitDispositionUnproven:
                return None

    # Fallback: defining source file from inspect (still CID-pinned).
    try:
        path = inspect.getsourcefile(method) or inspect.getfile(defining_cls)
    except TypeError:
        return None
    if not path or not path.endswith((".py", ".pyi")):
        return None
    try:
        from pathlib import Path

        source = Path(path).read_text(encoding="utf-8")
    except OSError:
        return None
    source_cid = blake3_512_of(source.encode("utf-8"))
    filename = path
    try:
        tree = parsed_tree(source, filename)
    except SyntaxError:
        return None
    if not isinstance(tree, ast.Module):
        return None
    fn = _find_class_exit_ast(tree, defining_cls.__name__)
    if fn is None:
        return None
    try:
        return prove_exit_function_ast(
            fn,
            module=method_mod,
            class_name=defining_cls.__name__,
            source_cid=source_cid,
            filename=filename,
        )
    except ExitDispositionUnproven:
        return None


_IMPORT_ALIASES = {
    "np": "numpy",
    "pd": "pandas",
}


def _resolve_callable_from_dotted(dotted: str) -> object | None:
    if not dotted:
        return None
    parts = dotted.split(".")
    if len(parts) == 1:
        return None  # bare name needs local scope — unproven
    candidates = [dotted]
    if parts[0] in _IMPORT_ALIASES:
        candidates.append(".".join([_IMPORT_ALIASES[parts[0]], *parts[1:]]))
    for candidate in candidates:
        cparts = candidate.split(".")
        for split in range(len(cparts) - 1, 0, -1):
            mod_name = ".".join(cparts[:split])
            rest = cparts[split:]
            try:
                mod = importlib.import_module(mod_name)
            except Exception:
                continue
            obj: object = mod
            try:
                for attr in rest:
                    obj = getattr(obj, attr)
                return obj
            except Exception:
                continue
    return None


def _dotted_of_sugar_node(node) -> str | None:
    from sugar_source_tree.nodes import Attribute, Name

    if isinstance(node, Name):
        return node.id
    if isinstance(node, Attribute):
        base = _dotted_of_sugar_node(node.value)
        if base is None:
            return None
        return f"{base}.{node.attr}"
    return None


def _resolve_from_unit_imports(unit, name: str) -> object | None:
    """Resolve a bare name via the source file's top-level imports only."""
    source = getattr(unit, "source", None)
    if not source or not name:
        return None
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                bound = alias.asname or alias.name
                if bound == name:
                    if alias.name == "*":
                        return None
                    return _resolve_callable_from_dotted(f"{node.module}.{alias.name}")
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound = alias.asname or alias.name
                if bound == name:
                    try:
                        return importlib.import_module(alias.name)
                    except Exception:
                        return None
    return None


def prove_exit_disposition_from_manager_expr(
    manager_node,
) -> ExitDispositionProof | None:
    """Prove NeverSuppresses from a sugar-tree manager expression, or None.

    Handles ``Class(...)`` calls where ``Class`` resolves to a type with a
    source-visible defining ``__exit__``. Bare names resolve only through
    authenticated top-level imports in the same file (not ambient globals).
    Functions/generators and ambiguous dispatch → None (RuntimeSelected).
    """
    from sugar_source_tree.nodes import Call, Name

    if not isinstance(manager_node, Call):
        return None
    func = manager_node.func
    obj = None
    if isinstance(func, Name):
        obj = _resolve_from_unit_imports(manager_node.unit, func.id)
    else:
        dotted = _dotted_of_sugar_node(func)
        if dotted is not None:
            obj = _resolve_callable_from_dotted(dotted)
    if obj is None or not isinstance(obj, type):
        return None
    return prove_never_suppresses_for_class(obj)
