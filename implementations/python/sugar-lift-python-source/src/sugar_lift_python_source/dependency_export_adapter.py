"""Residual dual-body static export scan (stdlib ast).

Owns foreign-ast surface for installed-artifact export resolution.
``dependency_artifact`` must not import ``ast``.

Retirement: rewrite export selection on SourceFile typed Nodes and delete
this adapter (same residual pattern as ``source_tables_adapter``).
"""

from __future__ import annotations

import ast
from typing import Any, Literal

from .canonical import blake3_512_of
from .source_tables import parsed_tree


def _bind() -> None:
    """Late-bind parent symbols to avoid import cycles."""
    from . import dependency_artifact as da

    g = globals()
    for name in (
        "AuthenticatedModuleSourceV1",
        "DefinitionCoordinateV1",
        "DependencyArtifactGraph",
        "PythonObjectResolutionV1",
        "ReexportWarrantV1",
        "ResolvedPythonObjectV1",
        "_cid",
        "_gap",
        "_string",
    ):
        g[name] = getattr(da, name)


def resolve_export(
    graph: DependencyArtifactGraph,
    binding_cid: str,
    module_name: str,
    exported_name: str,
    warrants: tuple[ReexportWarrantV1, ...],
    seen: frozenset[tuple[str, str]],
) -> PythonObjectResolutionV1:
    _bind()
    key = (module_name, exported_name)
    if key in seen:
        return _gap("reexport-cycle", binding_cid, graph, module_name, exported_name)
    module = graph.modules.get(module_name)
    if module is None:
        return _gap(
            "artifact-module-absent", binding_cid, graph, module_name, exported_name
        )
    tree = parsed_tree(module.source, module.source_seat)
    binding = _export_block(tree.body, exported_name, None)
    dynamic_getattr = any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "__getattr__"
        for node in tree.body
    )
    if binding is not None and binding[0] == "definition":
        definition = _definition(module, binding[1])
        return ResolvedPythonObjectV1(
            distribution_artifact_cid=graph.distribution_artifact_cid,
            import_binding_cid=binding_cid,
            module_name=module_name,
            source_cid=module.source_cid,
            reexport_warrants=warrants,
            definition=definition,
        )
    if binding is not None and binding[0] == "import":
        node, alias = binding[1]
        target_module = _absolute_import(module_name, module.source_seat, node)
        if target_module is None:
            return _gap("opaque-source", binding_cid, graph, module_name, exported_name)
        target = graph.modules.get(target_module)
        if target is None:
            return _gap(
                "artifact-module-absent",
                binding_cid,
                graph,
                target_module,
                alias.name,
            )
        warrant = ReexportWarrantV1(
            from_module=module_name,
            from_source_cid=module.source_cid,
            to_module=target_module,
            to_source_cid=target.source_cid,
            exported_name=exported_name,
            imported_name=alias.name,
            definition=_import_coordinate(module, node, exported_name),
        )
        return resolve_export(
            graph,
            binding_cid,
            target_module,
            alias.name,
            (*warrants, warrant),
            seen | {key},
        )
    if binding is not None and binding[0] == "alias":
        return resolve_export(
            graph,
            binding_cid,
            module_name,
            binding[1].id,
            warrants,
            seen | {key},
        )
    if binding is not None and binding[0] == "unsupported":
        return _gap(
            "unsupported-statement",
            binding_cid,
            graph,
            module_name,
            exported_name,
        )
    return _gap(
        (
            "dynamic-export"
            if dynamic_getattr or (binding is not None and binding[0] == "dynamic")
            else "static-export-absent"
        ),
        binding_cid,
        graph,
        module_name,
        exported_name,
    )


def _definition(
    module: AuthenticatedModuleSourceV1, node: ast.AST
) -> DefinitionCoordinateV1:
    segment = ast.get_source_segment(module.source, node)
    if segment is None:
        raise DependencyArtifactAuthenticationError(
            "definition source segment is unavailable"
        )
    kind: Literal["function", "class"] = (
        "class" if isinstance(node, ast.ClassDef) else "function"
    )
    return DefinitionCoordinateV1(
        name=node.name,
        kind=kind,
        source_cid=module.source_cid,
        start_line=node.lineno,
        start_col=node.col_offset,
        end_line=node.end_lineno,
        end_col=node.end_col_offset,
        fragment_cid=blake3_512_of(segment.encode("utf-8")),
    )


def _import_coordinate(
    module: AuthenticatedModuleSourceV1,
    node: ast.ImportFrom,
    exported_name: str,
) -> DefinitionCoordinateV1:
    segment = ast.get_source_segment(module.source, node)
    if segment is None:
        raise DependencyArtifactAuthenticationError(
            "re-export source segment is unavailable"
        )
    return DefinitionCoordinateV1(
        name=exported_name,
        kind="import",
        source_cid=module.source_cid,
        start_line=node.lineno,
        start_col=node.col_offset,
        end_line=node.end_lineno,
        end_col=node.end_col_offset,
        fragment_cid=blake3_512_of(segment.encode("utf-8")),
    )


def _absolute_import(
    current_module: str, source_seat: str, node: ast.ImportFrom
) -> str | None:
    if node.level == 0:
        return node.module
    package = current_module.split(".")
    if not source_seat.endswith("/__init__.py"):
        package.pop()
    ascend = node.level - 1
    if ascend > len(package):
        return None
    base = package[: len(package) - ascend]
    if node.module:
        base.extend(node.module.split("."))
    return ".".join(base) or None


def _target_binds(target: ast.AST, name: str) -> bool:
    if isinstance(target, ast.Name):
        return target.id == name
    if isinstance(target, (ast.Tuple, ast.List)):
        return any(_target_binds(item, name) for item in target.elts)
    if isinstance(target, ast.Starred):
        return _target_binds(target.value, name)
    return False


_TYPE_ALIAS = getattr(ast, "TypeAlias", None)
_TRY_TYPES = tuple(
    kind for kind in (ast.Try, getattr(ast, "TryStar", None)) if kind is not None
)

_EXPORT_SIMPLE_STATEMENTS = frozenset(
    kind
    for kind in (
        ast.Assign,
        ast.AnnAssign,
        ast.AugAssign,
        ast.Delete,
        ast.Import,
        ast.ImportFrom,
        ast.FunctionDef,
        ast.AsyncFunctionDef,
        ast.ClassDef,
        ast.Expr,
        ast.Return,
        ast.Raise,
        ast.Assert,
        ast.Pass,
        ast.Break,
        ast.Continue,
        ast.Global,
        ast.Nonlocal,
        _TYPE_ALIAS,
    )
    if kind is not None
)
_EXPORT_COMPOUND_STATEMENTS = frozenset(
    kind
    for kind in (
        ast.If,
        ast.For,
        ast.AsyncFor,
        ast.While,
        ast.With,
        ast.AsyncWith,
        ast.Try,
        getattr(ast, "TryStar", None),
        ast.Match,
    )
    if kind is not None
)


def export_statement_coverage() -> tuple[list[str], list[str]]:
    """Audit that every running-interpreter statement has one transfer arm."""
    grammar = frozenset(ast.stmt.__subclasses__())
    declared = _EXPORT_SIMPLE_STATEMENTS | _EXPORT_COMPOUND_STATEMENTS
    return (
        sorted(kind.__name__ for kind in grammar - declared),
        sorted(kind.__name__ for kind in declared - grammar),
    )


def _export_block(statements, name, initial):
    state = initial
    for index, statement in enumerate(statements):
        if _statement_contains_module_init_raise(statement) and _suite_binds_export(
            statements[index + 1 :], name
        ):
            # A later binding is control-dependent on whether this exceptional
            # prefix completes.  In particular, a With/AsyncWith exit may
            # suppress the exception while skipping the remainder of its
            # suite.  Selecting that later textual binding would authenticate
            # an unreachable definition.
            return ("dynamic", statement)
        state = _export_statement(statement, name, state)
    return state


def _suite_binds_export(statements, name: str) -> bool:
    marker = object()
    return _export_block(statements, name, marker) is not marker


def _statement_contains_module_init_raise(statement: ast.AST) -> bool:
    stack: list[ast.AST] = [statement]
    while stack:
        node = stack.pop()
        if isinstance(node, ast.Raise):
            return True
        if node is not statement and isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
        ):
            continue
        stack.extend(ast.iter_child_nodes(node))
    return False


def _export_statement(statement: ast.stmt, name: str, state):
    if type(statement) not in (_EXPORT_SIMPLE_STATEMENTS | _EXPORT_COMPOUND_STATEMENTS):
        return _unsupported_export_statement(statement)
    if _statement_walrus_binds(statement, name):
        state = ("dynamic", statement)
    if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        if statement.name != name:
            return state
        return (
            ("definition", statement)
            if not statement.decorator_list
            else ("dynamic", statement)
        )
    if isinstance(statement, ast.ImportFrom):
        for alias in statement.names:
            if (alias.asname or alias.name) == name:
                state = ("import", (statement, alias))
        return state
    if isinstance(statement, ast.Import):
        return (
            ("dynamic", statement)
            if any(
                (alias.asname or alias.name.split(".")[0]) == name
                for alias in statement.names
            )
            else state
        )
    if isinstance(statement, ast.Assign):
        if not any(_target_binds(target, name) for target in statement.targets):
            return state
        if (
            len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and isinstance(statement.value, ast.Name)
        ):
            return ("alias", statement.value)
        return ("dynamic", statement)
    if isinstance(statement, ast.AnnAssign):
        if statement.value is None or not _target_binds(statement.target, name):
            return state
        if isinstance(statement.target, ast.Name) and isinstance(
            statement.value, ast.Name
        ):
            return ("alias", statement.value)
        return ("dynamic", statement)
    if isinstance(statement, ast.AugAssign):
        return (
            ("dynamic", statement) if _target_binds(statement.target, name) else state
        )
    if isinstance(statement, ast.Delete):
        return (
            None
            if any(_target_binds(target, name) for target in statement.targets)
            else state
        )
    if _TYPE_ALIAS is not None and isinstance(statement, _TYPE_ALIAS):
        return (
            ("dynamic", statement)
            if isinstance(statement.name, ast.Name) and statement.name.id == name
            else state
        )
    if isinstance(statement, (ast.With, ast.AsyncWith)):
        for item in statement.items:
            if item.optional_vars is not None and _target_binds(
                item.optional_vars, name
            ):
                state = ("dynamic", statement)
        return _export_block(statement.body, name, state)
    if isinstance(statement, ast.Match):
        outputs = [
            _export_block(
                case.body,
                name,
                ("dynamic", statement) if _pattern_binds(case.pattern, name) else state,
            )
            for case in statement.cases
        ]
        exhaustive = (
            bool(statement.cases)
            and isinstance(statement.cases[-1].pattern, ast.MatchAs)
            and statement.cases[-1].pattern.pattern is None
            and statement.cases[-1].guard is None
        )
        if not exhaustive:
            outputs.append(state)
        return _join_export_states(outputs, statement)
    if isinstance(statement, _TRY_TYPES):
        completed = _export_block(statement.body, name, state)
        completed = _export_block(statement.orelse, name, completed)
        # A suite containing only definition/pass statements cannot raise while
        # binding the export; its handlers are unreachable on successful module
        # construction. Other try bodies retain every handler edge.
        outputs = [completed]
        if not all(_cannot_raise_during_module_init(item) for item in statement.body):
            for handler in statement.handlers:
                handler_state = (
                    ("dynamic", statement) if handler.name == name else state
                )
                outputs.append(_export_block(handler.body, name, handler_state))
        joined = _join_export_states(outputs, statement)
        return _export_block(statement.finalbody, name, joined)
    if isinstance(statement, ast.If):
        return _join_export_states(
            (
                _export_block(statement.body, name, state),
                _export_block(statement.orelse, name, state),
            ),
            statement,
        )
    if isinstance(statement, (ast.For, ast.AsyncFor, ast.While)):
        iterated = state
        if isinstance(statement, (ast.For, ast.AsyncFor)) and _target_binds(
            statement.target, name
        ):
            iterated = ("dynamic", statement)
        iterated = _export_block(statement.body, name, iterated)
        iterated = _export_block(statement.orelse, name, iterated)
        return _join_export_states((state, iterated), statement)
    if type(statement) in _EXPORT_SIMPLE_STATEMENTS:
        return state
    return _unsupported_export_statement(statement)


def _unsupported_export_statement(statement: ast.AST):
    return ("unsupported", type(statement).__name__)


def _join_export_states(states, locus):
    states = tuple(states)
    if states and all(state == states[0] for state in states[1:]):
        return states[0]
    return ("dynamic", locus)


def _pattern_binds(pattern: ast.pattern, name: str) -> bool:
    if isinstance(pattern, (ast.MatchAs, ast.MatchStar)) and pattern.name == name:
        return True
    if isinstance(pattern, ast.MatchMapping) and pattern.rest == name:
        return True
    return any(
        _pattern_binds(child, name)
        for child in ast.iter_child_nodes(pattern)
        if isinstance(child, ast.pattern)
    )


def _statement_walrus_binds(statement: ast.AST, name: str) -> bool:
    """Find module-scope named expressions without entering nested scopes/suites."""
    stack = list(ast.iter_child_nodes(statement))
    while stack:
        node = stack.pop()
        if isinstance(node, ast.stmt):
            continue
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
        ):
            continue
        if isinstance(node, ast.NamedExpr) and _target_binds(node.target, name):
            return True
        stack.extend(ast.iter_child_nodes(node))
    return False


def _cannot_raise_during_module_init(statement: ast.AST) -> bool:
    if isinstance(statement, ast.Pass):
        return True
    if not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return False
    arguments = statement.args
    parameters = (
        *arguments.posonlyargs,
        *arguments.args,
        *arguments.kwonlyargs,
        *(() if arguments.vararg is None else (arguments.vararg,)),
        *(() if arguments.kwarg is None else (arguments.kwarg,)),
    )
    return not (
        statement.decorator_list
        or arguments.defaults
        or any(default is not None for default in arguments.kw_defaults)
        or statement.returns is not None
        or any(parameter.annotation is not None for parameter in parameters)
        or getattr(statement, "type_params", ())
    )




