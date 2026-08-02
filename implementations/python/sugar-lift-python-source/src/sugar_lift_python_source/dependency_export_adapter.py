"""Residual dual-body static export scan (stdlib ast).

Owns foreign-ast surface for installed-artifact export resolution.
``dependency_artifact`` must not import ``ast``.

Retirement: rewrite export selection on SourceFile typed Nodes and delete
this adapter (same residual pattern as ``source_tables_adapter``).
"""

from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import PurePosixPath
import re
from typing import Any, Literal

from .canonical import blake3_512_of
from .resolution_session import SourceResolutionSession, session_or_new
from .source_tables import parsed_tree


def _bind() -> None:
    """Late-bind parent symbols to avoid import cycles."""
    from . import dependency_artifact as da

    g = globals()
    for name in (
        "AuthenticatedModuleSourceV1",
        "DefinitionCoordinateV1",
        "DependencyArtifactGraph",
        "PythonObjectResolutionGapV1",
        "PythonObjectResolutionV1",
        "ReexportWarrantV1",
        "ResolvedPythonObjectV1",
        "_cid",
        "_gap",
        "_string",
    ):
        g[name] = getattr(da, name)


def _export_terminal_result(result: Any) -> Any:
    """Definition/gap only — no path warrants or import-binding CID.

    Reexport hops carry path warrants and cannot share the pure-entry memo
    (that memo keeps module-structural reexport warrants).  The terminal memo
    is the shared definition identity both doors restamp onto.
    """
    if isinstance(result, ResolvedPythonObjectV1):
        return replace(
            result,
            import_binding_cid="",
            reexport_warrants=(),
            cid="",
        )
    if isinstance(result, PythonObjectResolutionGapV1):
        return replace(result, import_binding_cid="")
    return result


def _restamp_export_result(
    result: Any,
    binding_cid: str,
    *,
    warrants: tuple[ReexportWarrantV1, ...] | None = None,
) -> Any:
    """Reuse a cached resolution under a new binding / warrant path."""
    if isinstance(result, ResolvedPythonObjectV1):
        return replace(
            result,
            import_binding_cid=binding_cid,
            reexport_warrants=(
                warrants if warrants is not None else result.reexport_warrants
            ),
            cid="",
        )
    if isinstance(result, PythonObjectResolutionGapV1):
        return replace(result, import_binding_cid=binding_cid)
    return result


def resolve_export(
    graph: DependencyArtifactGraph,
    binding_cid: str,
    module_name: str,
    exported_name: str,
    warrants: tuple[ReexportWarrantV1, ...],
    seen: frozenset[tuple[str, str]],
    *,
    session: SourceResolutionSession | None = None,
) -> PythonObjectResolutionV1:
    """Resolve one static export.

    Two session memos share the key (distribution_artifact_cid, module_name,
    exported_name):

    * **pure-entry** (``export_resolutions``): how THIS module exports the name,
      including module-structural reexport warrants.  Filled only on pure entry
      (no path warrants / empty seen).
    * **terminal** (``export_terminals``): definition/gap only.  Filled on every
      successful resolve so a reexport hop with path warrants can hit after a
      pure resolve of the same symbol (or after another hop) without re-running
      prefix fallthrough.  Measured on _json: pure-entry hit for repeats, but
      reexport hops with warrants skipped the memo and re-paid ~0.8s prefix.

    ``seen`` still owns cycle detection and is checked before either memo.
    """
    _bind()
    session = session_or_new(session)
    if (module_name, exported_name) in seen:
        return _gap(
            "reexport-cycle", binding_cid, graph, module_name, exported_name
        )
    cache_key = (
        graph.distribution_artifact_cid,
        module_name,
        exported_name,
    )
    pure_entry = not warrants and not seen
    if pure_entry:
        hit = session.export_hit(cache_key)
        if hit is not None:
            return _restamp_export_result(hit, binding_cid)
        # A prior reexport hop may have filled the terminal memo for this
        # symbol without a pure-entry row (hops do not write export_resolutions).
        terminal = session.export_terminal_hit(cache_key)
        if terminal is not None:
            return _restamp_export_result(terminal, binding_cid, warrants=())
    else:
        # Reexport hop / path context: share definition identity only.
        terminal = session.export_terminal_hit(cache_key)
        if terminal is not None:
            return _restamp_export_result(
                terminal, binding_cid, warrants=warrants
            )

    result = _resolve_export_uncached(
        graph,
        binding_cid,
        module_name,
        exported_name,
        warrants,
        seen,
        session=session,
    )
    # Terminal definition/gap: always, so the next hop can hit.
    session.remember_export_terminal(cache_key, _export_terminal_result(result))
    # Pure-entry form (keeps module-structural warrants): pure door only.
    if pure_entry:
        session.remember_export(
            cache_key, _restamp_export_result(result, binding_cid="")
        )
    return result


def _resolve_export_uncached(
    graph: DependencyArtifactGraph,
    binding_cid: str,
    module_name: str,
    exported_name: str,
    warrants: tuple[ReexportWarrantV1, ...],
    seen: frozenset[tuple[str, str]],
    *,
    session: SourceResolutionSession,
) -> PythonObjectResolutionV1:
    key = (module_name, exported_name)
    if key in seen:
        return _gap("reexport-cycle", binding_cid, graph, module_name, exported_name)
    module = graph.modules.get(module_name)
    if module is None:
        included = _cython_included_class(graph, module_name, exported_name)
        if included is not None:
            source, definition = included
            return ResolvedPythonObjectV1(
                distribution_artifact_cid=graph.distribution_artifact_cid,
                import_binding_cid=binding_cid,
                module_name=module_name,
                source_cid=source.source_cid,
                reexport_warrants=warrants,
                definition=definition,
            )
        return _gap(
            "artifact-module-absent", binding_cid, graph, module_name, exported_name
        )
    tree = parsed_tree(module.source, module.source_seat)
    binding, locus = _export_block_with_locus(tree.body, exported_name, None)
    dynamic_getattr = any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "__getattr__"
        for node in tree.body
    )
    # Normal-completion authority for the prefix (statements strictly before
    # the unique export-binding locus): producer-owned Completed faces only.
    if locus is not None and not _prefix_has_completed_fallthrough(
        module, locus, graph=graph, session=session
    ):
        return _gap("dynamic-export", binding_cid, graph, module_name, exported_name)
    return _resolve_export_binding(
        graph,
        binding_cid,
        module,
        module_name,
        exported_name,
        binding,
        tree.body,
        warrants,
        seen,
        key,
        dynamic_getattr=dynamic_getattr,
        session=session,
    )


def _resolve_export_binding(
    graph,
    binding_cid: str,
    module,
    module_name: str,
    exported_name: str,
    binding,
    body: list[ast.stmt],
    warrants: tuple,
    seen: frozenset[tuple[str, str]],
    key: tuple[str, str],
    *,
    dynamic_getattr: bool,
    session,
) -> PythonObjectResolutionV1:
    """Follow one export-binding state (definition / import / alias / star)."""
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
            included = _cython_included_class(graph, target_module, alias.name)
            if included is not None:
                source, definition = included
                warrant = ReexportWarrantV1(
                    from_module=module_name,
                    from_source_cid=module.source_cid,
                    to_module=target_module,
                    to_source_cid=source.source_cid,
                    exported_name=exported_name,
                    imported_name=alias.name,
                    definition=_import_coordinate(module, node, exported_name),
                )
                return ResolvedPythonObjectV1(
                    distribution_artifact_cid=graph.distribution_artifact_cid,
                    import_binding_cid=binding_cid,
                    module_name=target_module,
                    source_cid=source.source_cid,
                    reexport_warrants=(*warrants, warrant),
                    definition=definition,
                )
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
            session=session,
        )
    if binding is not None and binding[0] == "alias":
        # Follow the binding of the RHS name that *reaches* the assignment —
        # never the RHS name's final module binding after later reassignment.
        assign_node, name_node = binding[1]
        if not any(statement is assign_node for statement in body):
            # The reaching suite is not authenticated by this module-body
            # traversal. Refuse instead of reconstructing an enclosing suite.
            return _gap(
                "dynamic-export", binding_cid, graph, module_name, exported_name
            )
        alias_name = name_node.id
        hop_key = (module_name, alias_name)
        if hop_key in seen:
            return _gap(
                "reexport-cycle", binding_cid, graph, module_name, exported_name
            )
        reaching, _ = _export_block_with_locus(
            _statements_before(body, assign_node), alias_name, None
        )
        warrant = ReexportWarrantV1(
            from_module=module_name,
            from_source_cid=module.source_cid,
            to_module=module_name,
            to_source_cid=module.source_cid,
            exported_name=exported_name,
            imported_name=alias_name,
            definition=_alias_coordinate(module, assign_node, exported_name),
        )
        return _resolve_export_binding(
            graph,
            binding_cid,
            module,
            module_name,
            exported_name,
            reaching,
            body,
            (*warrants, warrant),
            seen | {key, hop_key},
            key,
            dynamic_getattr=dynamic_getattr,
            session=session,
        )
    if binding is not None and binding[0] == "unsupported":
        return _gap(
            "unsupported-statement",
            binding_cid,
            graph,
            module_name,
            exported_name,
        )
    if binding is not None and binding[0] == "ambiguous":
        return _gap(
            "ambiguous-static-export",
            binding_cid,
            graph,
            module_name,
            exported_name,
        )
    # Star import: TARGET module's ``__all__`` / public-name rule controls
    # which names star publishes (Python import semantics), not the importer's.
    if binding is not None and binding[0] == "star":
        return _resolve_star_export(
            graph,
            binding_cid,
            module,
            module_name,
            exported_name,
            binding[1],
            warrants,
            seen,
            key,
            session=session,
        )
    if binding is not None and binding[0] == "dynamic":
        call_method = _callable_instance_call_method(body, binding[1], exported_name)
        if call_method is not None:
            definition = _definition(module, call_method)
            return ResolvedPythonObjectV1(
                distribution_artifact_cid=graph.distribution_artifact_cid,
                import_binding_cid=binding_cid,
                module_name=module_name,
                source_cid=module.source_cid,
                reexport_warrants=warrants,
                definition=definition,
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


_CYTHON_INCLUDE = re.compile(r'^include\s+["\']([^"\']+\.pxi)["\']\s*$')
_PYTHON_CLASS = re.compile(r"^class\s+([A-Za-z_]\w*)\s*\(([^)]*)\)\s*:\s*(?:#.*)?$")


def _cython_included_class(graph, module_name: str, exported_name: str):
    """Resolve a Python class from a recorded Cython include edge.

    Native-extension wheels may expose a module from ``module.pyx`` while the
    Python exception classes it exports live in a recorded ``include``d
    ``.pxi`` file.  The include statement and class bytes are both required;
    a sibling file or matching class spelling alone is never testimony.
    """
    module_seat = PurePosixPath(*module_name.split(".")).with_suffix(".pyx")
    files = {item.source_seat: item for item in graph.files}
    module_file = files.get(module_seat.as_posix())
    if module_file is None:
        return None
    try:
        module_source = module_file.content.decode("utf-8")
    except UnicodeError:
        return None
    includes = []
    for line in module_source.splitlines():
        match = _CYTHON_INCLUDE.fullmatch(line)
        if match is None:
            continue
        relative = PurePosixPath(match.group(1))
        if relative.is_absolute() or ".." in relative.parts:
            return None
        includes.append(module_seat.parent / relative)

    matches = []
    for include_seat in includes:
        included_file = files.get(include_seat.as_posix())
        if included_file is None:
            return None
        try:
            source = included_file.content.decode("utf-8")
        except UnicodeError:
            return None
        definition = _python_class_definition(
            source, included_file.content_cid, exported_name
        )
        if definition is not None:
            matches.append((included_file, source, definition))
    if len(matches) != 1:
        return None
    included_file, source, definition = matches[0]
    return (
        AuthenticatedModuleSourceV1(
            module_name=module_name,
            source_seat=included_file.source_seat,
            source_cid=included_file.content_cid,
            source=source,
        ),
        definition,
    )


def _python_class_definition(
    source: str, source_cid: str, exported_name: str
) -> DefinitionCoordinateV1 | None:
    lines = source.splitlines()
    found = []
    for index, line in enumerate(lines):
        match = _PYTHON_CLASS.fullmatch(line)
        if match is None or match.group(1) != exported_name:
            continue
        end = index + 1
        while end < len(lines):
            candidate = lines[end]
            if (
                candidate
                and not candidate[0].isspace()
                and not candidate.startswith("#")
            ):
                break
            end += 1
        while end > index + 1 and not lines[end - 1].strip():
            end -= 1
        if end == index + 1:
            return None
        segment = "\n".join(lines[index:end])
        try:
            parsed = ast.parse(segment)
        except SyntaxError:
            return None
        if len(parsed.body) != 1 or not isinstance(parsed.body[0], ast.ClassDef):
            return None
        node = parsed.body[0]
        found.append(
            DefinitionCoordinateV1(
                name=node.name,
                kind="class",
                source_cid=source_cid,
                start_line=index + 1,
                start_col=node.col_offset,
                end_line=index + node.end_lineno,
                end_col=node.end_col_offset,
                fragment_cid=blake3_512_of(segment.encode("utf-8")),
            )
        )
    return found[0] if len(found) == 1 else None


def _callable_instance_call_method(
    body: list[ast.stmt], statement: ast.AST, exported_name: str
) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """Return Class.__call__ when statement is ``name = Class()`` for a local Class.

    Only zero-arg constructor calls are accepted: the export is the instance's
    call protocol, not a partially applied factory with undecided construction
    actuals. Multi-arg or keyword construction stays dynamic-export.
    """
    value: ast.expr | None = None
    if isinstance(statement, ast.Assign):
        if not (
            len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and statement.targets[0].id == exported_name
        ):
            return None
        value = statement.value
    elif isinstance(statement, ast.AnnAssign):
        if not (
            isinstance(statement.target, ast.Name)
            and statement.target.id == exported_name
            and statement.value is not None
        ):
            return None
        value = statement.value
    else:
        return None
    if not (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and not value.args
        and not value.keywords
    ):
        return None
    class_name = value.func.id
    class_def = None
    for node in body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            class_def = node
            break
    if class_def is None:
        return None
    for item in class_def.body:
        if (
            isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            and item.name == "__call__"
        ):
            return item
    return None


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


def _alias_coordinate(
    module: AuthenticatedModuleSourceV1,
    node: ast.AST,
    exported_name: str,
) -> DefinitionCoordinateV1:
    segment = ast.get_source_segment(module.source, node)
    if segment is None:
        raise DependencyArtifactAuthenticationError(
            "alias re-export source segment is unavailable"
        )
    return DefinitionCoordinateV1(
        name=exported_name,
        kind="alias",
        source_cid=module.source_cid,
        start_line=node.lineno,
        start_col=node.col_offset,
        end_line=node.end_lineno,
        end_col=node.end_col_offset,
        fragment_cid=blake3_512_of(segment.encode("utf-8")),
    )


def _resolve_star_export(
    graph,
    binding_cid: str,
    module,
    module_name: str,
    exported_name: str,
    star_import: ast.ImportFrom,
    warrants: tuple,
    seen: frozenset[tuple[str, str]],
    key: tuple[str, str],
    *,
    session,
):
    """Star publication is the *target* module's ``__all__`` / public-name rule."""
    target_module = _absolute_import(module_name, module.source_seat, star_import)
    if target_module is None:
        return _gap("opaque-source", binding_cid, graph, module_name, exported_name)
    target = graph.modules.get(target_module)
    if target is None:
        return _gap(
            "artifact-module-absent",
            binding_cid,
            graph,
            target_module,
            exported_name,
        )
    target_tree = parsed_tree(target.source, target.source_seat)
    published = _target_star_published_names(target_tree.body)
    if exported_name not in published:
        return _gap("dynamic-export", binding_cid, graph, module_name, exported_name)
    warrant = ReexportWarrantV1(
        from_module=module_name,
        from_source_cid=module.source_cid,
        to_module=target_module,
        to_source_cid=target.source_cid,
        exported_name=exported_name,
        imported_name=exported_name,
        definition=_import_coordinate(module, star_import, exported_name),
    )
    return resolve_export(
        graph,
        binding_cid,
        target_module,
        exported_name,
        (*warrants, warrant),
        seen | {key},
        session=session,
    )


def _target_star_published_names(body: list[ast.stmt]) -> frozenset[str]:
    """Names a module publishes under ``from module import *``.

    Prefer a single immutable literal ``__all__``.  Without it, public names
    (no leading ``_``) that have a source-visible top-level bind.  Computed /
    competing ``__all__`` yields empty publication (star stays dynamic).
    """
    literal = _literal_all_publication(body)
    if literal is not None:
        return literal
    if _has_nonliteral_all(body):
        return frozenset()
    public: set[str] = set()
    for statement in body:
        for name in _top_level_bound_names(statement):
            if not name.startswith("_"):
                public.add(name)
    return frozenset(public)


def _has_nonliteral_all(body: list[ast.stmt]) -> bool:
    stack: list[ast.AST] = list(body)
    while stack:
        statement = stack.pop()
        if isinstance(statement, ast.Assign):
            if any(
                isinstance(target, ast.Name) and target.id == "__all__"
                for target in statement.targets
            ):
                return True
        elif isinstance(statement, ast.AnnAssign):
            if (
                isinstance(statement.target, ast.Name)
                and statement.target.id == "__all__"
            ):
                return True
        elif isinstance(statement, ast.AugAssign):
            if (
                isinstance(statement.target, ast.Name)
                and statement.target.id == "__all__"
            ):
                return True
        # Function/class bodies are separate namespaces, never module
        # publication testimony. Other compound suites execute in module scope.
        if isinstance(
            statement,
            (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda),
        ):
            continue
        stack.extend(ast.iter_child_nodes(statement))
    return False


def _top_level_bound_names(statement: ast.stmt) -> frozenset[str]:
    if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return frozenset({statement.name})
    if isinstance(statement, ast.ImportFrom):
        return frozenset(
            (alias.asname or alias.name)
            for alias in statement.names
            if alias.name != "*"
        )
    if isinstance(statement, ast.Import):
        return frozenset(
            (alias.asname or alias.name.split(".")[0]) for alias in statement.names
        )
    if isinstance(statement, ast.Assign):
        names: set[str] = set()
        for target in statement.targets:
            if isinstance(target, ast.Name):
                names.add(target.id)
        return frozenset(names)
    if isinstance(statement, ast.AnnAssign):
        if isinstance(statement.target, ast.Name):
            return frozenset({statement.target.id})
    return frozenset()


def _literal_all_publication(body: list[ast.stmt]) -> frozenset[str] | None:
    """Single immutable literal ``__all__`` of string constants, or None."""
    published: frozenset[str] | None = None
    saw_all = False
    for statement in body:
        binds_all = False
        value: ast.AST | None = None
        if isinstance(statement, ast.Assign):
            if any(
                isinstance(target, ast.Name) and target.id == "__all__"
                for target in statement.targets
            ):
                if not (
                    len(statement.targets) == 1
                    and isinstance(statement.targets[0], ast.Name)
                    and statement.targets[0].id == "__all__"
                ):
                    return None
                binds_all = True
                value = statement.value
        elif isinstance(statement, ast.AnnAssign):
            if (
                isinstance(statement.target, ast.Name)
                and statement.target.id == "__all__"
            ):
                if statement.value is None:
                    return None
                binds_all = True
                value = statement.value
        elif isinstance(statement, ast.AugAssign):
            if (
                isinstance(statement.target, ast.Name)
                and statement.target.id == "__all__"
            ):
                return None
        if not binds_all:
            continue
        saw_all = True
        names = _literal_string_sequence(value)
        if names is None:
            return None
        if published is not None:
            return None
        published = names
    return published if saw_all else None


def _literal_string_sequence(node: ast.AST | None) -> frozenset[str] | None:
    if node is None:
        return None
    if not isinstance(node, (ast.List, ast.Tuple)):
        return None
    names: set[str] = set()
    for element in node.elts:
        if not isinstance(element, ast.Constant) or not isinstance(element.value, str):
            return None
        if not element.value:
            return None
        names.add(element.value)
    return frozenset(names)


def _statements_before(body: list[ast.stmt], locus: ast.stmt) -> list[ast.stmt]:
    prefix: list[ast.stmt] = []
    for statement in body:
        if statement is locus:
            break
        prefix.append(statement)
    return prefix


def _export_block_with_locus(statements, name, initial):
    """Export transfer with the statement that last bound ``name``.

    Locus is the *innermost* statement that established the bind (e.g. the
    FunctionDef inside a With body), not the compound wrapper — so prefix
    fall-through includes the compound suite that must complete to reach it.
    """
    state = initial
    locus = None
    for statement in statements:
        prior = state
        new_state, new_locus = _export_statement_with_locus(statement, name, state)
        if new_state is not prior:
            state = new_state
            locus = new_locus if new_locus is not None else statement
    return state, locus


def _export_statement_with_locus(statement: ast.stmt, name: str, state):
    """Transfer one statement; return (state, innermost bind locus or None)."""
    if isinstance(statement, (ast.With, ast.AsyncWith)):
        for item in statement.items:
            if item.optional_vars is not None and _target_binds(
                item.optional_vars, name
            ):
                state = ("dynamic", statement)
        body_state, body_locus = _export_block_with_locus(statement.body, name, state)
        return body_state, body_locus
    if isinstance(statement, ast.If):
        body_state, body_locus = _export_block_with_locus(statement.body, name, state)
        else_state, else_locus = _export_block_with_locus(statement.orelse, name, state)
        joined = _join_export_states((body_state, else_state), statement)
        if joined is body_state and body_state is not state:
            return joined, body_locus
        if joined is else_state and else_state is not state:
            return joined, else_locus
        if joined is not state:
            return joined, statement
        return joined, None
    if isinstance(statement, (ast.For, ast.AsyncFor, ast.While)):
        iterated = state
        if isinstance(statement, (ast.For, ast.AsyncFor)) and _target_binds(
            statement.target, name
        ):
            iterated = ("dynamic", statement)
        body_state, body_locus = _export_block_with_locus(
            statement.body, name, iterated
        )
        else_state, else_locus = _export_block_with_locus(
            statement.orelse, name, body_state
        )
        joined = _join_export_states((state, else_state), statement)
        if joined is not state:
            locus = else_locus or body_locus or statement
            return joined, locus
        return joined, None
    if isinstance(statement, _TRY_TYPES):
        # Preserve existing try transfer; locus is the try when state changes.
        new_state = _export_statement(statement, name, state)
        return new_state, (statement if new_state is not state else None)
    if isinstance(statement, ast.Match):
        new_state = _export_statement(statement, name, state)
        return new_state, (statement if new_state is not state else None)
    new_state = _export_statement(statement, name, state)
    return new_state, (statement if new_state is not state else None)


def _prefix_has_completed_fallthrough(
    module, locus: ast.stmt, *, graph=None, session=None
) -> bool:
    """Delegate prefix meaning to the construction producer.

    The dependency adapter owns export recognition only. It must not import
    the downstream lift-kit test package or suppress a missing producer as a
    normal dynamic export.
    """
    from .manager_construction import prefix_has_completed_fallthrough

    if graph is None and session is None:
        return prefix_has_completed_fallthrough(module, locus)
    return prefix_has_completed_fallthrough(module, locus, graph=graph, session=session)


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
    state, _locus = _export_block_with_locus(statements, name, initial)
    return state


def _suite_binds_export(statements, name: str) -> bool:
    marker = object()
    return _export_block(statements, name, marker) is not marker


def _statement_contains_module_init_raise(statement: ast.AST) -> bool:
    if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        # The definition statement executes decorators/bases, not its body.
        # A Raise nested in that deferred body is not a module-init edge and
        # cannot make a later module binding control-dependent.
        return False
    stack: list[ast.AST] = [statement]
    while stack:
        node = stack.pop()
        if isinstance(node, ast.Raise):
            return True
        if isinstance(
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
        # Decorators are part of the definition site, not export opacity.
        # ``@contextmanager def f`` still statically binds ``f`` at this
        # statement; construction authenticates decorator application and
        # may stay loud if a decorator is opaque. Treating any decorator
        # list as ``dynamic-export`` erased real families (e.g. re-exported
        # ``@contextmanager`` resources) without a general capability gap.
        return ("definition", statement)
    if isinstance(statement, ast.ImportFrom):
        for alias in statement.names:
            if alias.name == "*":
                # Star residual only when no explicit static bind already owns
                # the name.  Literal ``__all__`` publication is resolve-time.
                if isinstance(state, tuple) and state[0] == "star":
                    state = ("ambiguous", statement)
                elif not (
                    isinstance(state, tuple)
                    and state[0] in {"definition", "import", "alias", "ambiguous"}
                ):
                    state = ("star", statement)
                continue
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
            return ("alias", (statement, statement.value))
        return ("dynamic", statement)
    if isinstance(statement, ast.AnnAssign):
        if statement.value is None or not _target_binds(statement.target, name):
            return state
        if isinstance(statement.target, ast.Name) and isinstance(
            statement.value, ast.Name
        ):
            return ("alias", (statement, statement.value))
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
    # Competing source-visible static bindings: ambiguous, not first-candidate.
    static_kinds = frozenset({"definition", "import", "alias"})
    concrete = tuple(state for state in states if state is not None)
    if (
        concrete
        and len(concrete) == len(states)
        and all(
            isinstance(state, tuple) and state[0] in static_kinds for state in concrete
        )
    ):
        return ("ambiguous", locus)
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
