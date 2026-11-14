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
from .dependency_artifact import (
    AuthenticatedModuleSourceV1,
    DefinitionCoordinateV1,
    DependencyArtifactGraph,
    PythonObjectResolutionGapV1,
    PythonObjectResolutionV1,
    ReexportWarrantV1,
    ResolvedPythonObjectV1,
    _gap,
)
from .resolution_session import SourceResolutionSession, session_or_new
from .source_tables import parsed_tree


def _export_terminal_result(result: Any, prefix: int) -> Any:
    """Definition plus this key's OWN hops — no caller path, no binding CID.

    ``prefix`` is how many warrants the caller already held on entry.  Those
    are the caller's path and are dropped.  Everything after them is the
    suffix this key resolved through: the hops from the keyed module down to
    the definition.  The suffix is part of the answer, not part of the path —
    the keyed module reaches that definition only through those hops, and a
    memo that discards them answers a different question than the uncached
    resolve.  Restamping then either fails ``ResolvedPythonObjectV1``'s
    reaching check ("re-export warrants do not reach the resolved definition")
    or publishes a definition with no provenance at all.
    """
    if isinstance(result, ResolvedPythonObjectV1):
        return replace(
            result,
            import_binding_cid="",
            reexport_warrants=result.reexport_warrants[prefix:],
            cid="",
        )
    if isinstance(result, PythonObjectResolutionGapV1):
        return replace(result, import_binding_cid="")
    return result


def _terminal_suffix(terminal: Any) -> tuple:
    """The hops a stored terminal resolved through, below its keyed module."""
    if isinstance(terminal, ResolvedPythonObjectV1):
        return terminal.reexport_warrants
    return ()


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
    * **terminal** (``export_terminals``): definition/gap plus the hops THIS
      key resolved through, with the entering caller's path warrants stripped.
      Filled on every successful resolve so a reexport hop with path warrants
      can hit after a pure resolve of the same symbol (or after another hop)
      without re-running prefix fallthrough.  Measured on _json: pure-entry hit
      for repeats, but reexport hops with warrants skipped the memo and re-paid
      ~0.8s prefix.

    A reader composes its own path with the stored suffix.  The suffix cannot
    be dropped: the resolved definition may sit several modules below the key,
    and a chain that stops at the key does not reach it.

    ``seen`` still owns cycle detection and is checked before either memo.
    """
    session = session_or_new(session)
    if (module_name, exported_name) in seen:
        return _gap("reexport-cycle", binding_cid, graph, module_name, exported_name)
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
            # Pure entry holds no path, so the stored suffix IS the whole
            # chain from this module to the definition. Keep it.
            return _restamp_export_result(terminal, binding_cid)
    else:
        # Reexport hop: this caller's path, then the hops the memo resolved
        # through. Dropping the suffix would strand the chain at this module.
        terminal = session.export_terminal_hit(cache_key)
        if terminal is not None:
            return _restamp_export_result(
                terminal,
                binding_cid,
                warrants=(*warrants, *_terminal_suffix(terminal)),
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
    # Terminal definition/gap plus this key's own hops: always, so the next
    # hop can hit and still compose a chain that reaches the definition.
    session.remember_export_terminal(
        cache_key, _export_terminal_result(result, len(warrants))
    )
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
    # The module prefix is never executed to admit an export: that opened the
    # dependency module a second way (the prefix door), with its own context.
    # A bind that every successful import reaches is the export.  A prefix
    # that may skip it leaves the export undecided, named ``dynamic-export``;
    # it is never admitted on an answer nobody computed.  A bind inside an If
    # takes that If as the statement to reach.
    if locus is not None and not _prefix_reaches_locus_or_aborts(
        tree.body, _top_level_containing(tree.body, locus)
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
    if binding is not None and binding[0] in {"star", "stars"}:
        stars = (binding[1],) if binding[0] == "star" else binding[1]
        publishers = []
        for star_import in stars:
            target_module = _absolute_import(module_name, module.source_seat, star_import)
            if target_module is None:
                continue
            target = graph.modules.get(target_module)
            if target is None:
                if exported_name in _builtin_module_star_names(target_module):
                    publishers.append(star_import)
                continue
            target_tree = parsed_tree(target.source, target.source_seat)
            published = _target_star_published_names(
                target_tree.body,
                graph=graph,
                module_name=target_module,
                module=target,
                seen=seen,
            )
            if exported_name in published:
                publishers.append(star_import)
        if len(publishers) > 1:
            return _gap(
                "ambiguous-static-export",
                binding_cid,
                graph,
                module_name,
                exported_name,
            )
        if len(publishers) == 1:
            return _resolve_star_export(
                graph,
                binding_cid,
                module,
                module_name,
                exported_name,
                publishers[0],
                warrants,
                seen,
                key,
                session=session,
            )
        # A star that publishes nothing is still a star residual, not a
        # missing static bind: the existing membrane names that dynamic-export.
        return _gap(
            "dynamic-export",
            binding_cid,
            graph,
            module_name,
            exported_name,
        )
    if binding is not None and binding[0] == "dynamic":
        bound = class_bound_classmethod(body, binding[1], exported_name)
        if bound is not None:
            return ResolvedPythonObjectV1(
                distribution_artifact_cid=graph.distribution_artifact_cid,
                import_binding_cid=binding_cid,
                module_name=module_name,
                source_cid=module.source_cid,
                reexport_warrants=warrants,
                definition=_definition(module, bound[1]),
            )
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


def resolve_class_body_member(graph, binding_cid: str, resolved, member_name: str):
    """Look up one method on an already-resolved class export.

    ``from module import Class`` then ``Class.method`` names a FunctionDef in
    that class body. It is not a nested module under ``module.Class``.
    Inherited methods and class-body assignments stay outside-binding: only a
    unique FunctionDef or AsyncFunctionDef on the class itself.
    """
    if isinstance(resolved, PythonObjectResolutionGapV1):
        return resolved
    if not isinstance(resolved, ResolvedPythonObjectV1):
        return _gap(
            "target-outside-binding",
            binding_cid,
            graph,
            getattr(resolved, "module_name", ""),
            member_name,
        )
    if resolved.definition.kind != "class":
        return _gap(
            "target-outside-binding",
            binding_cid,
            graph,
            resolved.module_name,
            member_name,
        )
    module = graph.modules.get(resolved.module_name)
    if module is None or module.source_cid != resolved.source_cid:
        return _gap(
            "target-outside-binding",
            binding_cid,
            graph,
            resolved.module_name,
            member_name,
        )
    tree = parsed_tree(module.source, module.source_seat)
    class_def = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef)
            and node.name == resolved.definition.name
            and node.lineno == resolved.definition.start_line
            and node.col_offset == resolved.definition.start_col
        ),
        None,
    )
    if class_def is None:
        return _gap(
            "target-outside-binding",
            binding_cid,
            graph,
            resolved.module_name,
            member_name,
        )
    found = [
        item
        for item in class_def.body
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
        and item.name == member_name
    ]
    if len(found) != 1:
        return _gap(
            "target-outside-binding",
            binding_cid,
            graph,
            resolved.module_name,
            member_name,
        )
    return ResolvedPythonObjectV1(
        distribution_artifact_cid=resolved.distribution_artifact_cid,
        import_binding_cid=binding_cid,
        module_name=resolved.module_name,
        source_cid=resolved.source_cid,
        reexport_warrants=resolved.reexport_warrants,
        definition=_definition(module, found[0]),
    )


def class_bound_classmethod(
    body: list[ast.stmt], statement: ast.AST, exported_name: str
) -> tuple[ast.ClassDef, ast.FunctionDef] | None:
    """``name = Class.method`` at module level, ``method`` a ``@classmethod``.

    Lib/tarfile.py ends ``open = TarFile.open``.  Attribute lookup on the
    class runs ``classmethod.__get__(None, TarFile)`` (Objects/funcobject.c
    ``cm_descr_get``), which binds the class: the export is that bound
    method, ``cls`` is ``Class`` and the caller supplies the remaining
    formals.  Only the exact shape is admitted: one plain ``Assign`` to the
    exported name, ``Class`` a module-level ``class`` statement that is the
    only module-level binding of that name, and ``method`` the only member
    of that name in the class body, decorated by the bare ``classmethod``
    builtin, which the module never rebinds.  Anything else stays
    ``dynamic-export``.
    """
    if not (
        isinstance(statement, ast.Assign)
        and len(statement.targets) == 1
        and isinstance(statement.targets[0], ast.Name)
        and statement.targets[0].id == exported_name
        and isinstance(statement.value, ast.Attribute)
        and isinstance(statement.value.value, ast.Name)
    ):
        return None
    class_name = statement.value.value.id
    method_name = statement.value.attr
    if not any(item is statement for item in body):
        return None
    binders = [item for item in body if _module_statement_binds(item, class_name)]
    if len(binders) != 1 or not isinstance(binders[0], ast.ClassDef):
        return None
    class_def = binders[0]
    if body.index(class_def) > body.index(statement):
        return None
    if any(_module_statement_binds(item, "classmethod") for item in body):
        return None
    members = [
        item for item in class_def.body if _module_statement_binds(item, method_name)
    ]
    if len(members) != 1 or not isinstance(members[0], ast.FunctionDef):
        return None
    method = members[0]
    if not (
        len(method.decorator_list) == 1
        and isinstance(method.decorator_list[0], ast.Name)
        and method.decorator_list[0].id == "classmethod"
        and (method.args.posonlyargs or method.args.args)
    ):
        return None
    return class_def, method


def _module_statement_binds(statement: ast.stmt, name: str) -> bool:
    """Whether one statement (at any depth) may bind ``name`` in its scope."""
    if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return statement.name == name
    for node in ast.walk(statement):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            if getattr(node, "name", None) == name:
                return True
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            if node.id == name:
                return True
        if isinstance(node, ast.alias):
            if (node.asname or node.name.split(".")[0]) == name or node.name == "*":
                return True
        if isinstance(node, (ast.Global, ast.Nonlocal)) and name in node.names:
            return True
        if isinstance(node, ast.ExceptHandler) and node.name == name:
            return True
        if isinstance(node, ast.MatchAs) and node.name == name:
            return True
    return False


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
    published = _target_star_published_names(
        target_tree.body,
        graph=graph,
        module_name=target_module,
        module=target,
        seen=seen,
    )
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


def _target_star_published_names(
    body: list[ast.stmt],
    *,
    graph=None,
    module_name: str | None = None,
    module=None,
    seen: frozenset[tuple[str, str]] | frozenset[str] = frozenset(),
) -> frozenset[str]:
    """Names a module publishes under ``from module import *``.

    Prefer an evaluable ``__all__`` algebra (a literal list, ``+=`` /
    ``extend`` of another module's ``__all__``, or a same-module helper
    that only performs that union).  Without ``__all__``, public names
    (no leading ``_``) that have a source-visible top-level bind.  Computed
    or competing ``__all__`` that the algebra cannot close yields empty
    publication (star stays dynamic).
    """
    algebraic = _algebraic_all_publication(
        body,
        graph=graph,
        module_name=module_name,
        module=module,
        seen=_module_seen(seen),
    )
    if algebraic is not None:
        return algebraic
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


def _module_seen(seen) -> frozenset[str]:
    """Module names already on an ``__all__`` algebra walk."""
    names: set[str] = set()
    for item in seen:
        if isinstance(item, str):
            names.add(item)
        elif isinstance(item, tuple) and item and isinstance(item[0], str):
            names.add(item[0])
    return frozenset(names)


def _is_ident(node: ast.AST, name: str) -> bool:
    return isinstance(node, ast.Name) and node.id == name


def _is_attribute(node: ast.AST, value_name: str, attr: str) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and _is_ident(node.value, value_name)
        and node.attr == attr
    )


def _constant_truth(node: ast.AST) -> bool | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, bool):
        return node.value
    return None


def _nameerror_except_constant(handler: ast.ExceptHandler, name: str) -> bool | None:
    """Constant assigned to ``name`` by a bare ``except NameError`` handler."""
    typ = handler.type
    if typ is None:
        return None
    if _is_ident(typ, "NameError"):
        pass
    elif isinstance(typ, ast.Tuple) and len(typ.elts) == 1 and _is_ident(
        typ.elts[0], "NameError"
    ):
        pass
    else:
        return None
    body = handler.body
    if len(body) != 1 or not isinstance(body[0], ast.Assign):
        return None
    assign = body[0]
    if not (
        len(assign.targets) == 1
        and isinstance(assign.targets[0], ast.Name)
        and assign.targets[0].id == name
    ):
        return None
    return _constant_truth(assign.value)


def _is_bare_name_load(statement: ast.stmt, name: str) -> bool:
    return (
        isinstance(statement, ast.Expr)
        and isinstance(statement.value, ast.Name)
        and statement.value.id == name
    )


def _try_nameerror_default(statement: ast.stmt, name: str) -> bool | None:
    """``try: NAME\nexcept NameError: NAME = <bool>`` default, or None."""
    if not isinstance(statement, ast.Try):
        return None
    if statement.orelse or statement.finalbody or len(statement.handlers) != 1:
        return None
    if not statement.body or not all(
        _is_bare_name_load(item, name) or isinstance(item, ast.Pass)
        for item in statement.body
    ):
        return None
    if not any(_is_bare_name_load(item, name) for item in statement.body):
        return None
    return _nameerror_except_constant(statement.handlers[0], name)


def _decided_prefix_name(name: str, prefix: list[ast.stmt]) -> bool | None:
    """Truth of ``name`` after a module prefix, when uniquely decided."""
    bound: bool | None = None
    known = False
    for statement in prefix:
        default = _try_nameerror_default(statement, name)
        if default is not None:
            if not known:
                bound = default
                known = True
            continue
        if isinstance(statement, ast.Assign):
            if not any(_target_binds(target, name) for target in statement.targets):
                continue
            if not (
                len(statement.targets) == 1
                and isinstance(statement.targets[0], ast.Name)
                and statement.targets[0].id == name
            ):
                return None
            truth = _constant_truth(statement.value)
            if truth is None:
                return None
            bound = truth
            known = True
            continue
        if isinstance(statement, ast.AnnAssign) and _target_binds(statement.target, name):
            if statement.value is None:
                continue
            if not isinstance(statement.target, ast.Name):
                return None
            truth = _constant_truth(statement.value)
            if truth is None:
                return None
            bound = truth
            known = True
            continue
        if isinstance(statement, ast.Delete) and any(
            _target_binds(target, name) for target in statement.targets
        ):
            known = False
            bound = None
            continue
        if isinstance(statement, ast.AugAssign) and _target_binds(statement.target, name):
            return None
        # Any other mention of the name in open control flow is not a decision.
        if isinstance(statement, (ast.Try, ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Match)):
            for node in ast.walk(statement):
                if isinstance(node, ast.Name) and node.id == name:
                    return None
    return bound if known else None


def _decided_if_test(test: ast.AST, prefix: list[ast.stmt]) -> bool | None:
    """Decide a module-level ``if`` test from a unique prefix binding."""
    truth = _constant_truth(test)
    if truth is not None:
        return truth
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        inner = _decided_if_test(test.operand, prefix)
        return None if inner is None else (not inner)
    if isinstance(test, ast.Name):
        return _decided_prefix_name(test.id, prefix)
    return _decided_builtin_module_membership(test, prefix)


def _is_stdlib_extension_module(module_name: str) -> bool:
    """True for a C extension shipped in the interpreter's own ``lib-dynload``.

    Such a module (``_decimal``, ``_json``, ...) is part of the pinned
    interpreter build exactly like a built-in module: it has no Python source in
    any artifact, and its spec origin is an extension file
    (``importlib.machinery.EXTENSION_SUFFIXES``) directly under the stdlib's
    ``lib-dynload``. A third-party extension lives in its own artifact and is
    not admitted here. The spec is found without executing the module.
    """
    import importlib.machinery
    import importlib.util
    import os
    import sys
    import sysconfig

    if module_name.count(".") or not module_name:
        return False
    try:
        spec = importlib.util.find_spec(module_name)
    except (ImportError, ValueError):
        return False
    origin = getattr(spec, "origin", None)
    if not isinstance(origin, str) or not isinstance(
        getattr(spec, "loader", None), importlib.machinery.ExtensionFileLoader
    ):
        return False
    # The base interpreter's stdlib, not a virtual environment's prefix.
    platstdlib = sysconfig.get_paths(
        vars={"base": sys.base_prefix, "platbase": sys.base_exec_prefix}
    )["platstdlib"]
    dynload = os.path.join(platstdlib, "lib-dynload")
    return os.path.dirname(os.path.realpath(origin)) == os.path.realpath(
        dynload
    ) and origin.endswith(tuple(importlib.machinery.EXTENSION_SUFFIXES))


def _builtin_module_star_names(module_name: str) -> frozenset[str]:
    """Names ``from <module> import *`` publishes for a built-in C module.

    A module in ``sys.builtin_module_names`` is compiled into the interpreter
    and has no source in any artifact, so the running, pin-authenticated
    interpreter's module object is the only authority. Star publication is the
    import-system rule: ``__all__`` when defined, otherwise every name not
    starting with an underscore
    (https://docs.python.org/3/reference/simple_stmts.html#the-import-statement).
    A C extension in the interpreter's own ``lib-dynload`` has the same
    standing (``_is_stdlib_extension_module``). Any other absent module
    publishes nothing here and stays a residual.
    """
    import importlib
    import sys

    if module_name not in sys.builtin_module_names and not _is_stdlib_extension_module(
        module_name
    ):
        return frozenset()
    try:
        module = importlib.import_module(module_name)
    except ImportError:
        return frozenset()
    published = getattr(module, "__all__", None)
    if published is None:
        return frozenset(name for name in vars(module) if not name.startswith("_"))
    if not all(isinstance(name, str) for name in published):
        return frozenset()
    return frozenset(published)


def _decided_builtin_module_membership(
    test: ast.AST, prefix: list[ast.stmt]
) -> bool | None:
    """Decide ``'<lit>' in <names>`` where ``<names>`` is ``sys.builtin_module_names``.

    ``sys.builtin_module_names`` is a constant of the interpreter build
    (https://docs.python.org/3/library/sys.html#sys.builtin_module_names). The
    running, pin-authenticated interpreter is the same authority the C-export
    floor already uses, so membership is read from it, never from a spelling.
    ``<names>`` is either that attribute directly or a module name whose only
    prefix binding is ``<names> = sys.builtin_module_names``; ``sys`` must be
    bound only by a top-level ``import sys``.
    """
    if not (
        isinstance(test, ast.Compare)
        and len(test.ops) == 1
        and isinstance(test.ops[0], (ast.In, ast.NotIn))
        and isinstance(test.left, ast.Constant)
        and isinstance(test.left.value, str)
    ):
        return None
    names = test.comparators[0]
    if isinstance(names, ast.Name):
        names = _unique_prefix_assigned_value(names.id, prefix)
    if not (
        isinstance(names, ast.Attribute)
        and names.attr == "builtin_module_names"
        and isinstance(names.value, ast.Name)
        and _bound_only_by_import(names.value.id, "sys", prefix)
    ):
        return None
    import sys

    member = test.left.value in sys.builtin_module_names
    return member if isinstance(test.ops[0], ast.In) else not member


def _prefix_mentions_binding(statement: ast.stmt, name: str) -> bool:
    for node in ast.walk(statement):
        if isinstance(node, ast.Name) and node.id == name and not isinstance(
            node.ctx, ast.Load
        ):
            return True
        if isinstance(node, (ast.Import, ast.ImportFrom)) and any(
            (alias.asname or alias.name.split(".")[0]) == name for alias in node.names
        ):
            return True
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        ) and node.name == name:
            return True
        if isinstance(node, ast.Global) and name in node.names:
            return True
    return False


def _unique_prefix_assigned_value(name: str, prefix: list[ast.stmt]):
    """The value of the one top-level ``name = <value>`` binding in a prefix."""
    found = None
    for statement in prefix:
        if not _prefix_mentions_binding(statement, name):
            continue
        if (
            found is None
            and isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and statement.targets[0].id == name
            and not _prefix_mentions_binding(statement.value, name)
        ):
            found = statement.value
            continue
        return None
    return found


def _bound_only_by_import(name: str, module: str, prefix: list[ast.stmt]) -> bool:
    """``name`` is bound in the prefix only by top-level ``import <module>``."""
    found = False
    for statement in prefix:
        if not _prefix_mentions_binding(statement, name):
            continue
        if (
            not found
            and isinstance(statement, ast.Import)
            and len(statement.names) == 1
            and statement.names[0].name == module
            and statement.names[0].asname is None
            and name == module
        ):
            found = True
            continue
        return False
    return found


def _all_extend_param(fn: ast.FunctionDef) -> str | None:
    """Parameter whose ``.__all__`` this helper unions into module ``__all__``."""
    if (
        fn.decorator_list
        or fn.args.vararg
        or fn.args.kwarg
        or fn.args.kwonlyargs
        or fn.args.defaults
        or len(fn.args.args) != 1
    ):
        return None
    param = fn.args.args[0].arg
    body = [
        statement
        for statement in fn.body
        if not (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        )
    ]
    if len(body) == 1 and (
        _is_all_aug_add_attr(body[0], param) or _is_all_extend_call(body[0], param)
    ):
        return param
    if _is_extend_all_loop_body(body, param):
        return param
    return None


def _is_all_aug_add_attr(statement: ast.stmt, param: str) -> bool:
    return (
        isinstance(statement, ast.AugAssign)
        and isinstance(statement.op, ast.Add)
        and _is_ident(statement.target, "__all__")
        and _is_attribute(statement.value, param, "__all__")
    )


def _is_all_extend_call(statement: ast.stmt, param: str) -> bool:
    if not isinstance(statement, ast.Expr) or not isinstance(statement.value, ast.Call):
        return False
    call = statement.value
    return (
        _is_attribute(call.func, "__all__", "extend")
        and len(call.args) == 1
        and not call.keywords
        and _is_attribute(call.args[0], param, "__all__")
    )


def _is_extend_all_loop_body(body: list[ast.stmt], param: str) -> bool:
    if len(body) != 3:
        return False
    existing_bind, mall_bind, loop = body
    if not (
        isinstance(existing_bind, ast.Assign)
        and len(existing_bind.targets) == 1
        and isinstance(existing_bind.targets[0], ast.Name)
        and isinstance(existing_bind.value, ast.Call)
        and _is_ident(existing_bind.value.func, "set")
        and len(existing_bind.value.args) == 1
        and not existing_bind.value.keywords
        and _is_ident(existing_bind.value.args[0], "__all__")
    ):
        return False
    existing = existing_bind.targets[0].id
    if not (
        isinstance(mall_bind, ast.Assign)
        and len(mall_bind.targets) == 1
        and isinstance(mall_bind.targets[0], ast.Name)
        and _is_attribute(mall_bind.value, param, "__all__")
    ):
        return False
    mall = mall_bind.targets[0].id
    if not (
        isinstance(loop, ast.For)
        and not loop.orelse
        and isinstance(loop.target, ast.Name)
        and _is_ident(loop.iter, mall)
        and len(loop.body) == 1
    ):
        return False
    item = loop.target.id
    guard = loop.body[0]
    if not (
        isinstance(guard, ast.If)
        and not guard.orelse
        and len(guard.body) == 1
        and isinstance(guard.test, ast.Compare)
        and _is_ident(guard.test.left, item)
        and len(guard.test.ops) == 1
        and isinstance(guard.test.ops[0], ast.NotIn)
        and len(guard.test.comparators) == 1
        and _is_ident(guard.test.comparators[0], existing)
    ):
        return False
    append = guard.body[0]
    return (
        isinstance(append, ast.Expr)
        and isinstance(append.value, ast.Call)
        and _is_attribute(append.value.func, "__all__", "append")
        and len(append.value.args) == 1
        and not append.value.keywords
        and _is_ident(append.value.args[0], item)
    )


def _imported_module_aliases(
    statement: ast.stmt, importer_name: str | None, importer_seat: str | None, graph
) -> dict[str, str]:
    """Local name to absolute module, when that module is in the graph."""
    aliases: dict[str, str] = {}
    if graph is None or not importer_name or not importer_seat:
        return aliases
    if isinstance(statement, ast.Import):
        for alias in statement.names:
            bound = alias.asname or alias.name.split(".")[0]
            module = alias.name if alias.asname is None else alias.name
            # ``import pkg.sub as name`` binds the submodule; ``import pkg.sub``
            # binds only ``pkg``.
            target = alias.name if alias.asname is not None else alias.name.split(".")[0]
            if target in graph.modules:
                aliases[bound] = target
        return aliases
    if not isinstance(statement, ast.ImportFrom):
        return aliases
    base = _absolute_import(importer_name, importer_seat, statement)
    if base is None:
        return aliases
    for alias in statement.names:
        if alias.name == "*":
            continue
        bound = alias.asname or alias.name
        # ``from . import numeric`` binds the submodule when it exists.
        submodule = f"{base}.{alias.name}"
        if submodule in graph.modules:
            aliases[bound] = submodule
        elif base in graph.modules and alias.name in graph.modules:
            aliases[bound] = alias.name
    return aliases


def _module_published_names(
    graph,
    module_name: str,
    seen: frozenset[str],
) -> frozenset[str] | None:
    if module_name in seen:
        return None
    target = graph.modules.get(module_name)
    if target is None:
        return None
    tree = parsed_tree(target.source, target.source_seat)
    return _target_star_published_names(
        tree.body,
        graph=graph,
        module_name=module_name,
        module=target,
        seen=seen | {module_name},
    )


def _algebraic_all_publication(
    body: list[ast.stmt],
    *,
    graph=None,
    module_name: str | None = None,
    module=None,
    seen: frozenset[str] = frozenset(),
) -> frozenset[str] | None:
    """Walk a closed ``__all__`` algebra, or None when a step is unreadable."""
    published: set[str] | None = None
    saw_all = False
    modules: dict[str, str] = {}
    helpers: dict[str, str] = {}
    opaque_all_helpers: set[str] = set()
    seat = getattr(module, "source_seat", None)
    for statement in body:
        if isinstance(statement, ast.FunctionDef):
            param = _all_extend_param(statement)
            if param is not None:
                helpers[statement.name] = param
            elif any(
                isinstance(node, ast.Name) and node.id == "__all__"
                for node in ast.walk(statement)
            ):
                opaque_all_helpers.add(statement.name)
            continue
        modules.update(_imported_module_aliases(statement, module_name, seat, graph))
        addition = _all_algebra_step(statement, modules, helpers, opaque_all_helpers, graph, seen)
        if addition is False:
            return None
        if addition is None:
            continue
        saw_all = True
        if addition[0] == "set":
            published = set(addition[1])
        else:
            if published is None:
                return None
            published.update(addition[1])
    return frozenset(published) if saw_all and published is not None else None


def _all_algebra_step(
    statement: ast.stmt,
    modules: dict[str, str],
    helpers: dict[str, str],
    opaque_all_helpers: set[str],
    graph,
    seen: frozenset[str],
):
    """('set', names), ('add', names), None if unrelated, False if opaque."""
    if isinstance(statement, ast.Assign):
        if not any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in statement.targets
        ):
            return None
        if not (
            len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and statement.targets[0].id == "__all__"
        ):
            return False
        names = _literal_string_sequence(statement.value)
        if names is None:
            return False
        return ("set", names)
    if isinstance(statement, ast.AnnAssign):
        if not (
            isinstance(statement.target, ast.Name) and statement.target.id == "__all__"
        ):
            return None
        if statement.value is None:
            return False
        names = _literal_string_sequence(statement.value)
        if names is None:
            return False
        return ("set", names)
    if isinstance(statement, ast.AugAssign):
        if not (
            _is_ident(statement.target, "__all__")
            and isinstance(statement.op, ast.Add)
        ):
            return None
        names = _literal_string_sequence(statement.value)
        if names is not None:
            return ("add", names)
        target = _all_attr_module(statement.value, modules)
        if target is None or graph is None:
            return False
        published = _module_published_names(graph, target, seen)
        if published is None:
            return False
        return ("add", published)
    if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call):
        call = statement.value
        if _is_attribute(call.func, "__all__", "extend") and len(call.args) == 1 and not call.keywords:
            names = _literal_string_sequence(call.args[0])
            if names is not None:
                return ("add", names)
            target = _all_attr_module(call.args[0], modules)
            if target is None or graph is None:
                return False
            published = _module_published_names(graph, target, seen)
            if published is None:
                return False
            return ("add", published)
        if isinstance(call.func, ast.Name) and call.func.id in helpers and len(call.args) == 1 and not call.keywords:
            if not isinstance(call.args[0], ast.Name):
                return False
            target = modules.get(call.args[0].id)
            if target is None or graph is None:
                return False
            published = _module_published_names(graph, target, seen)
            if published is None:
                return False
            return ("add", published)
        if isinstance(call.func, ast.Name) and call.func.id in opaque_all_helpers:
            return False
        # A call that is not an __all__ step is unrelated.
        return None
    # Opaque mutation of __all__ elsewhere (e.g. inside an undecided If).
    if isinstance(statement, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With, ast.AsyncWith, ast.Match)):
        for node in ast.walk(statement):
            if isinstance(node, ast.Name) and node.id == "__all__":
                return False
    return None


def _all_attr_module(node: ast.AST, modules: dict[str, str]) -> str | None:
    if isinstance(node, ast.Attribute) and node.attr == "__all__" and isinstance(node.value, ast.Name):
        return modules.get(node.value.id)
    return None



def _is_finite_sequence_value(expr: ast.AST) -> bool:
    if isinstance(expr, (ast.List, ast.Tuple, ast.Set)):
        return True
    if isinstance(expr, ast.Constant) and isinstance(
        expr.value, (str, bytes, tuple, list, set, frozenset)
    ):
        return True
    return (
        isinstance(expr, ast.Call)
        and isinstance(expr.func, ast.Name)
        and expr.func.id in {"list", "tuple", "set"}
        and not expr.args
        and not expr.keywords
    )


def _is_finite_iterable(expr: ast.AST, finite_names: set[str]) -> bool:
    if _is_finite_sequence_value(expr):
        return True
    if isinstance(expr, ast.Name) and expr.id in finite_names:
        return True
    if (
        isinstance(expr, ast.Call)
        and isinstance(expr.func, ast.Name)
        and expr.func.id == "range"
        and not expr.keywords
        and all(
            isinstance(arg, ast.Constant) and isinstance(arg.value, int)
            for arg in expr.args
        )
    ):
        return True
    return False


def _note_finite_bindings(statement: ast.AST, finite: set[str]) -> None:
    added: set[str] = set()
    discarded: set[str] = set()
    stack: list[ast.AST] = [statement]
    while stack:
        node = stack.pop()
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
        ):
            continue
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            if _is_finite_sequence_value(node.value):
                added.add(node.targets[0].id)
            else:
                discarded.add(node.targets[0].id)
        if isinstance(node, ast.Delete):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    discarded.add(target.id)
        stack.extend(ast.iter_child_nodes(node))
    finite -= discarded
    finite |= added - discarded


def _suite_cannot_fall_through(statements: list[ast.stmt]) -> bool:
    """True when no path falls through the end of this suite."""
    for statement in statements:
        if isinstance(statement, (ast.Raise, ast.Return)):
            return True
        if isinstance(statement, ast.If) and _suite_cannot_fall_through(
            statement.body
        ) and _suite_cannot_fall_through(statement.orelse):
            return True
    return False


def _stmt_reaches_successor_or_aborts(
    statement: ast.stmt, finite: set[str], *, in_loop: bool = False
) -> bool:
    """True when a successful import still reaches later module bindings.

    An unconditional ``raise`` or ``assert False`` has no success path.
    A ``while True`` is not treated as reached: that would invent a bound.
    A finite ``for`` whose body and else also have a success path is reached.
    """
    if isinstance(statement, (ast.Break, ast.Continue)):
        return in_loop
    if isinstance(statement, (ast.Raise, ast.Return)):
        return False
    if isinstance(statement, ast.Assert):
        # A proven-false assert aborts with no later bind. Other asserts may
        # pass, so they stay on a success path.
        return not (
            isinstance(statement.test, ast.Constant) and not statement.test.value
        )
    if isinstance(statement, ast.While):
        if isinstance(statement.test, ast.Constant) and statement.test.value is False:
            return all(
                _stmt_reaches_successor_or_aborts(item, finite, in_loop=in_loop)
                for item in statement.orelse
            )
        return False
    if isinstance(statement, ast.For):
        if not _is_finite_iterable(statement.iter, finite):
            return False
        if not all(
            _stmt_reaches_successor_or_aborts(item, finite, in_loop=True)
            for item in statement.body
        ):
            return False
        return all(
            _stmt_reaches_successor_or_aborts(item, finite, in_loop=in_loop)
            for item in statement.orelse
        )
    if isinstance(statement, ast.If):
        body_ok = all(
            _stmt_reaches_successor_or_aborts(item, finite, in_loop=in_loop)
            for item in statement.body
        )
        else_ok = all(
            _stmt_reaches_successor_or_aborts(item, finite, in_loop=in_loop)
            for item in statement.orelse
        )
        truth = _constant_truth(statement.test)
        if truth is True:
            return body_ok
        if truth is False:
            return else_ok
        # An aborting arm is not a success path. A successful import took
        # an arm that still reaches later bindings.
        return body_ok or else_ok
    if isinstance(statement, _TRY_TYPES):
        # A successful import takes the try body, else, and finally. Handlers
        # that cannot fall through (they always raise) are only reached when
        # the import aborts, so they do not have to be licensed here.
        success = [
            *statement.body,
            *statement.orelse,
            *statement.finalbody,
        ]
        if not all(
            _stmt_reaches_successor_or_aborts(item, finite, in_loop=in_loop)
            for item in success
        ):
            return False
        return all(
            _stmt_reaches_successor_or_aborts(item, finite, in_loop=in_loop)
            for handler in statement.handlers
            if not _suite_cannot_fall_through(handler.body)
            for item in handler.body
        )
    if isinstance(statement, (ast.With, ast.AsyncWith)):
        # A successful import passes a with in one of two ways: the body
        # completes and ``__exit__`` returns, or the body raises and the
        # manager suppresses it.  Both continue at the statement after the
        # with; a raise out of ``__enter__``/``__exit__`` aborts the import.
        # Only a body that leaves another way (break/continue) can skip it.
        return all(
            _stmt_reaches_successor_or_aborts(item, finite, in_loop=in_loop)
            for item in statement.body
        )
    if type(statement) in _EXPORT_SIMPLE_STATEMENTS:
        return True
    return False


def _prefix_reaches_locus_or_aborts(body: list[ast.stmt], locus: ast.AST) -> bool:
    """A later static bind is reached on any successful import of this module."""
    finite: set[str] = set()
    for statement in body:
        if statement is locus:
            return True
        if not _stmt_reaches_successor_or_aborts(statement, finite):
            return False
        _note_finite_bindings(statement, finite)
    return False


def _statements_before(body: list[ast.stmt], locus: ast.stmt) -> list[ast.stmt]:
    prefix: list[ast.stmt] = []
    for statement in body:
        if statement is locus:
            break
        prefix.append(statement)
    return prefix


def _top_level_containing(body: list[ast.stmt], locus: ast.AST) -> ast.AST:
    """The module-body statement that must be reached to take ``locus``."""
    for statement in body:
        if statement is locus:
            return statement
        for node in ast.walk(statement):
            if node is locus:
                return statement
    return locus


def _export_block_with_locus(statements, name, initial, prefix=None):
    """Export transfer with the statement that last bound ``name``.

    Locus is the *innermost* statement that established the bind (e.g. the
    FunctionDef inside a With body), not the compound wrapper — so prefix
    fall-through includes the compound suite that must complete to reach it.
    """
    state = initial
    locus = None
    seen = list(prefix or [])
    for statement in statements:
        prior = state
        new_state, new_locus = _export_statement_with_locus(
            statement, name, state, prefix=seen
        )
        if new_state is not prior:
            state = new_state
            locus = new_locus if new_locus is not None else statement
        seen.append(statement)
    return state, locus


def _export_statement_with_locus(statement: ast.stmt, name: str, state, prefix=None):
    """Transfer one statement; return (state, innermost bind locus or None)."""
    if isinstance(statement, (ast.With, ast.AsyncWith)):
        for item in statement.items:
            if item.optional_vars is not None and _target_binds(
                item.optional_vars, name
            ):
                state = ("dynamic", statement)
        body_state, body_locus = _export_block_with_locus(
            statement.body, name, state, prefix=prefix
        )
        return body_state, body_locus
    if isinstance(statement, ast.If):
        decided = _decided_if_test(statement.test, prefix or [])
        if decided is True:
            return _export_block_with_locus(
                statement.body, name, state, prefix=prefix
            )
        if decided is False:
            return _export_block_with_locus(
                statement.orelse, name, state, prefix=prefix
            )
        body_state, body_locus = _export_block_with_locus(
            statement.body, name, state, prefix=prefix
        )
        else_state, else_locus = _export_block_with_locus(
            statement.orelse, name, state, prefix=prefix
        )
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
            statement.body, name, iterated, prefix=prefix
        )
        else_state, else_locus = _export_block_with_locus(
            statement.orelse, name, body_state, prefix=prefix
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


def _export_block(statements, name, initial, prefix=None):
    state, _locus = _export_block_with_locus(
        statements, name, initial, prefix=prefix
    )
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
                # the name.  Each target's ``__all__`` is applied at
                # resolve-time; two stars stay a set until then, and become
                # ambiguous only when they actually publish the same name.
                if isinstance(state, tuple) and state[0] in {
                    "definition",
                    "import",
                    "alias",
                    "ambiguous",
                }:
                    continue
                if isinstance(state, tuple) and state[0] == "star":
                    state = ("stars", (state[1], statement))
                elif isinstance(state, tuple) and state[0] == "stars":
                    state = ("stars", (*state[1], statement))
                else:
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


def _interpreter_c_import_completes(statement: ast.AST) -> bool:
    """``from <C module> import ...`` that the pinned interpreter decides completes.

    The module must be compiled into the interpreter or shipped as a C extension
    in its own ``lib-dynload`` (no artifact owns its source), it must import in
    the running interpreter, and every explicitly named import must exist on the
    module object. A star always completes once the module imports. Any other
    import may raise and keeps its handler edges.
    """
    import importlib
    import sys

    if not isinstance(statement, ast.ImportFrom) or statement.level:
        return False
    module_name = statement.module
    if not module_name or (
        module_name not in sys.builtin_module_names
        and not _is_stdlib_extension_module(module_name)
    ):
        return False
    try:
        module = importlib.import_module(module_name)
    except ImportError:
        return False
    return all(
        alias.name == "*" or hasattr(module, alias.name) for alias in statement.names
    )


def _cannot_raise_during_module_init(statement: ast.AST) -> bool:
    if isinstance(statement, ast.Pass):
        return True
    if _interpreter_c_import_completes(statement):
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
