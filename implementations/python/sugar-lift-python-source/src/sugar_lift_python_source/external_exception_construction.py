"""Construct external exception classes from authenticated provider source."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from sugar_lift_py_tests.ir import Term, ctor, str_const

from .dependency_artifact import (
    DependencyArtifactGraph,
    ResolvedPythonObjectV1,
    resolve_authenticated_module_export,
)
from .resolution_session import SourceResolutionSession


class ExternalExceptionConstructionGap(ValueError):
    """Provider source did not prove the requested exception class."""


@dataclass(frozen=True)
class AuthenticatedProviderExceptionTypeV1:
    """One source operand joined to one provider-defined exception class."""

    source_attribute: str
    resolved: ResolvedPythonObjectV1
    identity: Term
    ancestry: tuple[Term, ...]

    def class_value(self):
        """Construct the authenticated class/base graph used by native floors."""
        from sugar_lift_py_tests.floor import BlockValue, ClassValue

        base = None
        for name in reversed(_ancestry_labels(self.ancestry, self.resolved)):
            base = ClassValue(
                name=name,
                bases=() if base is None else (base,),
                record=BlockValue(()),
            )
        assert base is not None
        return base

    @classmethod
    def construct(
        cls,
        *,
        graph: DependencyArtifactGraph,
        binding_cid: str,
        module_name: str,
        source_attribute: str,
        session: SourceResolutionSession | None = None,
    ) -> "AuthenticatedProviderExceptionTypeV1":
        resolved = resolve_authenticated_module_export(
            graph=graph,
            binding_cid=binding_cid,
            module_name=module_name,
            exported_name=source_attribute,
            session=session,
        )
        if not isinstance(resolved, ResolvedPythonObjectV1):
            artifact = f"{module_name}.{source_attribute}"
            raise ExternalExceptionConstructionGap(
                f"provider export source absent for {artifact}: {resolved.kind}"
            )
        return cls.from_resolved(
            graph=graph,
            source_attribute=source_attribute,
            resolved=resolved,
        )

    @classmethod
    def from_resolved(
        cls,
        *,
        graph: DependencyArtifactGraph,
        source_attribute: str,
        resolved: ResolvedPythonObjectV1,
    ) -> "AuthenticatedProviderExceptionTypeV1":
        """Join an already-authenticated provider result to its source use."""
        if resolved.distribution_artifact_cid != graph.distribution_artifact_cid:
            raise ExternalExceptionConstructionGap(
                "provider definition belongs to a different artifact graph"
            )
        if resolved.definition.kind != "class":
            raise ExternalExceptionConstructionGap(
                f"provider export {resolved.module_name}.{source_attribute} resolves to "
                f"{resolved.definition.kind}, not class source"
            )
        # The source operand and resolved definition must name the same class.
        # This check is deliberately before identity minting: a valid provider
        # coordinate for a different exception is a lie, not partial testimony.
        if resolved.definition.name != source_attribute:
            raise ExternalExceptionConstructionGap(
                "provider definition mismatch: source binds "
                f"{source_attribute}, provider resolved {resolved.definition.name}"
            )
        ancestry_names = _exception_ancestry_names(graph, resolved)
        if ancestry_names is None:
            raise ExternalExceptionConstructionGap(
                "provider class source does not reach BaseException: "
                f"{resolved.module_name}.{resolved.definition.name}"
            )
        identity = _provider_identity(resolved)
        ancestry = tuple(
            (
                identity
                if index == 0
                else ctor(
                    "python:exception_type_identity",
                    [str_const("provider-base"), str_const(name)],
                )
            )
            for index, name in enumerate(ancestry_names)
        )
        return cls(source_attribute, resolved, identity, ancestry)


def _provider_identity(resolved: ResolvedPythonObjectV1) -> Term:
    """The qualified coordinate is admitted only behind provider testimony."""
    return ctor(
        "python:exception_type_identity",
        [
            str_const("import"),
            str_const(f"{resolved.module_name}.{resolved.definition.name}"),
        ],
    )


def _ancestry_labels(
    ancestry: tuple[Term, ...], resolved: ResolvedPythonObjectV1
) -> tuple[str, ...]:
    labels = [f"{resolved.module_name}.{resolved.definition.name}"]
    labels.extend(
        str(getattr(term.args[1], "value", "<invalid>")) for term in ancestry[1:]
    )
    return tuple(labels)


def _exception_ancestry_names(
    graph: DependencyArtifactGraph, resolved: ResolvedPythonObjectV1
) -> tuple[str, ...] | None:
    from sugar_source_tree.nodes import ClassDef, Name
    from sugar_source_tree.tree import SourceFile

    module = graph.modules.get(resolved.module_name)
    if module is not None and module.source_cid == resolved.source_cid:
        tree = SourceFile((module.source, module.source_seat, module.source_cid)).root
        classes = {
            node.name: tuple(base.id for base in node.bases if isinstance(base, Name))
            for node in tree.body
            if isinstance(node, ClassDef)
            and all(isinstance(base, Name) for base in node.bases)
        }
        starts = {
            node.name: node.lineno for node in tree.body if isinstance(node, ClassDef)
        }
    else:
        recorded = [
            item for item in graph.files if item.content_cid == resolved.source_cid
        ]
        if len(recorded) != 1:
            return None
        try:
            source = recorded[0].content.decode("utf-8")
        except UnicodeError:
            return None
        classes, starts = _source_visible_class_bases(source)
    leaf_name = resolved.definition.name
    if (
        leaf_name not in classes
        or starts.get(leaf_name) != resolved.definition.start_line
    ):
        return None

    result: list[str] = []
    visiting: set[str] = set()
    completed: set[str] = set()

    from sugar_lift_py_tests.temporal.builtin_name_bindings import (
        BUILTIN_EXCEPTION_BASES,
    )

    def visit(name: str) -> bool:
        if name in completed:
            return True
        if name in visiting:
            return False
        visiting.add(name)
        result.append(name)
        if name == "BaseException":
            visiting.remove(name)
            completed.add(name)
            return True
        bases = classes.get(name)
        if bases is None:
            bases = tuple(BUILTIN_EXCEPTION_BASES.get(name, ()))
        if not bases or not all(visit(base) for base in bases):
            return False
        visiting.remove(name)
        completed.add(name)
        return True

    return tuple(result) if visit(leaf_name) else None


_SOURCE_CLASS = re.compile(r"^class\s+([A-Za-z_]\w*)\s*\(([^)]*)\)\s*:\s*(?:#.*)?$")


def _source_visible_class_bases(
    source: str,
) -> tuple[dict[str, tuple[str, ...]], dict[str, int]]:
    """Read plain Python class headers from a larger provider source dialect."""
    classes: dict[str, tuple[str, ...]] = {}
    starts: dict[str, int] = {}
    for line_number, line in enumerate(source.splitlines(), start=1):
        match = _SOURCE_CLASS.fullmatch(line)
        if match is None:
            continue
        raw_bases = tuple(part.strip() for part in match.group(2).split(","))
        if not raw_bases or not all(base.isidentifier() for base in raw_bases):
            continue
        name = match.group(1)
        if name in classes:
            classes.pop(name, None)
            starts.pop(name, None)
            continue
        classes[name] = raw_bases
        starts[name] = line_number
    return classes, starts


def construct_provider_exception_attribute(
    node,
    *,
    root: Path,
    path: Path,
    graph_cache: dict[str, DependencyArtifactGraph],
    session: SourceResolutionSession,
    distribution_index=None,
) -> AuthenticatedProviderExceptionTypeV1 | None:
    """Construct ``provider.Exception`` through its reaching provider binding.

    The provider binding is either a native import statement or an assignment
    whose authenticated callee source returns ``sys.modules[formal]``.  No
    manager/callee spelling participates.  ``None`` means the operand is not
    this source shape; a recognized shape with missing provider source is a
    named construction gap.
    """
    from sugar_source_tree.nodes import Attribute, Name

    if not isinstance(node, Attribute):
        return None
    head = node.value
    if not isinstance(head, Name):
        return None
    module_name, binding_cid = _reaching_provider_module(
        head,
        root=root,
        path=path,
        graph_cache=graph_cache,
        session=session,
        distribution_index=distribution_index,
    )
    if module_name is None or binding_cid is None:
        return None
    top_level = module_name.split(".", 1)[0]
    graph = graph_cache.get(top_level)
    if graph is None:
        from .dependency_artifact import authenticate_dependency_top_level

        try:
            graph = authenticate_dependency_top_level(
                top_level, distribution_index=distribution_index
            )
        except Exception as exc:
            raise ExternalExceptionConstructionGap(
                f"provider artifact source absent: {module_name}"
            ) from exc
        graph_cache[top_level] = graph
    return AuthenticatedProviderExceptionTypeV1.construct(
        graph=graph,
        binding_cid=binding_cid,
        module_name=module_name,
        source_attribute=node.attr,
        session=session,
    )


def _reaching_provider_module(
    head,
    *,
    root: Path,
    path: Path,
    graph_cache: dict[str, DependencyArtifactGraph],
    session: SourceResolutionSession,
    distribution_index=None,
) -> tuple[str | None, str | None]:
    """Return the module and authenticated binding CID reaching ``head``."""
    from .canonical import cid_of_json
    from sugar_source_tree.nodes import Assign, Call, Constant, Import, Name, Try

    unit = head.unit
    bindings = tuple((unit.module_direct_bindings or {}).get(head.id, ()))
    # Ordinary module import: the lexical pass already owns this case.
    if len(bindings) == 1 and isinstance(bindings[0], Import):
        statement = bindings[0]
        matches = [
            alias
            for alias in statement.names
            if (alias.asname or alias.name.split(".", 1)[0]) == head.id
        ]
        if len(matches) == 1:
            module = matches[0].name
            return module, statement.fragment.seal().cid

    # Optional direct import under a try/except gate.  The imported name is a
    # value only on the success face; downstream source that reaches it is
    # already guarded by that provider gate.  Competing/rebinding handlers are
    # refused rather than joined optimistically.
    module = unit.typed_module
    candidates = []
    if module is not None:
        for statement in module.body:
            if not isinstance(statement, Try):
                continue
            imported = []
            for member in statement.body:
                if isinstance(member, Import):
                    imported.extend(
                        alias.name
                        for alias in member.names
                        if (alias.asname or alias.name.split(".", 1)[0]) == head.id
                    )
            rebound = any(
                any(
                    isinstance(part, Name) and part.id == head.id
                    for part in item.walk()
                )
                for handler in statement.handlers
                for item in handler.body
            )
            if len(imported) == 1 and not rebound:
                candidates.append((imported[0], statement.fragment.seal().cid))
    if len(candidates) == 1:
        return candidates[0]

    # Returned-module provider: resolve the assignment callee through its
    # authenticated import use, then read the native return shape from that
    # exact provider source.  No callee or vendor name is selected here.
    if len(bindings) != 1 or not isinstance(bindings[0], Assign):
        return None, None
    assignment = bindings[0]
    if len(assignment.targets) != 1 or not isinstance(assignment.value, Call):
        return None, None
    call = assignment.value
    if not call.args or not isinstance(call.args[0], Constant):
        return None, None
    actual_module = call.args[0].value
    if not isinstance(actual_module, str) or not actual_module:
        return None, None

    from sugar_lift_py_tests.import_binding import authenticated_import_use_receipts
    from .dependency_artifact import (
        ResolvedPythonObjectV1,
        authenticate_dependency_top_level,
        resolve_import_binding,
    )

    receipts, _ = authenticated_import_use_receipts(
        root, path, unit.source, unit.source_cid, module_identities={}
    )
    span = call.line_col_span()
    receipt = next(
        (
            item
            for item in receipts
            if (
                item.use["useSite"]["startLine"],
                item.use["useSite"]["startCol"],
                item.use["useSite"]["endLine"],
                item.use["useSite"]["endCol"],
            )
            == (span.start_line, span.start_col, span.end_line, span.end_col)
        ),
        None,
    )
    if receipt is None:
        return None, None
    callee_top = receipt.target_symbol.removeprefix("python:").split(".", 1)[0]
    callee_graph = graph_cache.get(callee_top)
    if callee_graph is None:
        callee_graph = authenticate_dependency_top_level(
            callee_top, distribution_index=distribution_index
        )
        graph_cache[callee_top] = callee_graph
    resolved = resolve_import_binding(receipt, graph=callee_graph, session=session)
    if not isinstance(resolved, ResolvedPythonObjectV1):
        return None, None
    provider_parameter = _returned_module_parameter(callee_graph, resolved)
    if provider_parameter != 0:
        return None, None
    binding_cid = cid_of_json(
        {
            "kind": "source-returned-module-binding",
            "assignmentCid": assignment.fragment.seal().cid,
            "calleeResolutionCid": resolved.cid,
            "module": actual_module,
        }
    )
    return actual_module, binding_cid


def _returned_module_parameter(
    graph: DependencyArtifactGraph, resolved: ResolvedPythonObjectV1
) -> int | None:
    """Parameter projected by a source function as ``sys.modules[param]``."""
    from sugar_source_tree.nodes import (
        Assign,
        AsyncFunctionDef,
        Attribute,
        FunctionDef,
        Import,
        Name,
        Return,
        Subscript,
    )
    from sugar_source_tree.tree import SourceFile

    module = graph.modules.get(resolved.module_name)
    if module is None or module.source_cid != resolved.source_cid:
        return None
    source_file = SourceFile((module.source, module.source_seat, module.source_cid))
    tree = source_file.root
    function = next(
        (
            node
            for node in tree.body
            if isinstance(node, (FunctionDef, AsyncFunctionDef))
            and node.name == resolved.definition.name
            and node.lineno == resolved.definition.start_line
        ),
        None,
    )
    if function is None:
        return None
    parameters = [arg.arg for arg in (*function.args.posonlyargs, *function.args.args)]
    sys_names = {
        alias.asname or alias.name
        for statement in tree.body
        if isinstance(statement, Import)
        for alias in statement.names
        if alias.name == "sys"
    }
    projected: dict[str, str] = {}
    returned_names: set[str] = set()
    registered = (
        source_file.constructed_module.construction_event_receipt.registered_occurrences
    )
    function_span = function.span
    nested_function_spans = tuple(
        node.span
        for node in registered
        if (
            node is not function
            and isinstance(node, (FunctionDef, AsyncFunctionDef))
            and function_span.start <= node.span.start
            and node.span.end <= function_span.end
        )
    )
    owned_occurrences = (
        node
        for node in registered
        if (
            node is not function
            and function_span.start <= node.span.start
            and node.span.end <= function_span.end
            and not any(
                nested.start <= node.span.start and node.span.end <= nested.end
                for nested in nested_function_spans
            )
        )
    )
    for statement in owned_occurrences:
        if isinstance(statement, Assign) and len(statement.targets) == 1:
            target = statement.targets[0]
            value = statement.value
            if isinstance(target, Name) and isinstance(value, Subscript):
                owner = value.value
                if (
                    isinstance(owner, Attribute)
                    and owner.attr == "modules"
                    and isinstance(owner.value, Name)
                    and owner.value.id in sys_names
                    and isinstance(value.slice_, Name)
                    and value.slice_.id in parameters
                ):
                    projected[target.id] = value.slice_.id
        if isinstance(statement, Return) and isinstance(statement.value, Name):
            returned_names.add(statement.value.id)
    returned = {projected[name] for name in returned_names if name in projected}
    if len(returned) != 1:
        return None
    return parameters.index(next(iter(returned)))
