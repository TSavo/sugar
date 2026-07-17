"""Install-source body dig: resolve vendor/same-module callees for CallSiteValue.body.

Membrane: fleet/CallSugar emits call:f(...) coordinates. This module resolves
f to a FunctionDef (same module, from_import, or importable module.attr), tags
install-source provenance, and builds a diggable body via build_bridge_body.

Method dig: MethodCallSugar attaches body when recv is a known class ctor /
from_import class and the method FunctionDef resolves on install source.

Bridge/dig doctrine:
- Resolve first; None means body stays None (coordinate only / dig opaque).
- Prefer real source file (Download Sources / site-packages) over invention.
- nested_external_bridge stays default False — not flipped here.
- Failures are None (opaque) or leave force_floor to panic — never silent invent.
"""

from __future__ import annotations

import importlib
import importlib.machinery
import ast
import copy
import functools
import inspect
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from sugar_lift_py_tests.factory.factory_audit_row import FactoryAuditStatus
from sugar_lift_python_source.source_oracle import installed_module_source
from sugar_lift_python_source.source_tables import parsed_tree

INSTALLED_SOURCE_INDEX_CAPACITY = 64


@dataclass(frozen=True)
class _InstalledDefinition:
    key: str
    name: str
    lineno: int
    col_offset: int
    bridge_name: str


@dataclass(frozen=True)
class _InstalledSourceIndex:
    """Immutable source plus compact definition coordinates for one module."""

    module_name: str
    source: str
    sourcefile: str
    definitions: tuple[_InstalledDefinition, ...]


def _definition_locator(
    key: str,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    bridge_name: str,
) -> _InstalledDefinition:
    return _InstalledDefinition(
        key=key,
        name=node.name,
        lineno=node.lineno,
        col_offset=node.col_offset,
        bridge_name=bridge_name,
    )


@functools.lru_cache(maxsize=INSTALLED_SOURCE_INDEX_CAPACITY)
def _installed_source_index(module_name: str) -> _InstalledSourceIndex | None:
    installed = _installed_source(module_name)
    if installed is None:
        installed = _imported_module_source(module_name)
    if installed is None:
        return None
    source, sourcefile = installed
    try:
        parsed = parsed_tree(source, sourcefile)
    except SyntaxError:
        return None

    definitions: dict[str, _InstalledDefinition] = {}
    for child in ast.walk(parsed):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            bridge_name = f"{module_name}.{child.name}"
            for key in (child.name, bridge_name):
                definitions[key] = _definition_locator(key, child, bridge_name)
        elif isinstance(child, ast.ClassDef):
            for statement in child.body:
                if not isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                bridge_name = f"{module_name}.{child.name}.{statement.name}"
                for key in (
                    f"{child.name}.{statement.name}",
                    bridge_name,
                ):
                    definitions[key] = _definition_locator(key, statement, bridge_name)
    return _InstalledSourceIndex(
        module_name=module_name,
        source=source,
        sourcefile=sourcefile,
        definitions=tuple(definitions.values()),
    )


def _installed_source(module_name: str) -> tuple[str, str] | None:
    """Compatibility view over the SourceOracle-owned installed source."""
    resolved = installed_module_source(module_name)
    if resolved is None:
        return None
    source, sourcefile, _source_cid = resolved
    return source, sourcefile


def _installed_native_extension(module_name: str) -> str | None:
    """Return one exact extension-module origin without importing the module."""
    if not module_name:
        return None
    parts = module_name.split(".")
    search_path = None
    spec = None
    try:
        for index in range(1, len(parts) + 1):
            qualified = ".".join(parts[:index])
            spec = importlib.machinery.PathFinder.find_spec(qualified, search_path)
            if spec is None:
                return None
            if index < len(parts):
                search_path = spec.submodule_search_locations
                if search_path is None:
                    return None
        origin = getattr(spec, "origin", None)
        loader = getattr(spec, "loader", None)
        if not isinstance(origin, str) or not isinstance(
            loader, importlib.machinery.ExtensionFileLoader
        ):
            return None
        if not origin.endswith(tuple(importlib.machinery.EXTENSION_SUFFIXES)):
            return None
        return origin
    except (ImportError, ModuleNotFoundError, OSError, TypeError, ValueError):
        return None


def _relative_import_package_parts(defining_module: str) -> list[str]:
    """Package components used as the base for relative imports.

    Matches importlib ``__package__``: a package ``__init__`` module uses its
    own dotted name; a leaf module uses its parent package. Without this,
    ``from ._private.utils import *`` inside ``numpy/testing/__init__.py``
    wrongly resolves to ``numpy._private.utils`` instead of
    ``numpy.testing._private.utils`` — so star-reexported callables like
    ``numpy.testing.assert_equal`` never bind (CallSugar FactoryPanic, #4585).
    """
    if not defining_module:
        return []
    installed = _installed_source(defining_module)
    if installed is not None:
        _source, sourcefile = installed
        if sourcefile.endswith(("__init__.py", "__init__.pyi")):
            return defining_module.split(".")
    parts = defining_module.split(".")
    return parts[:-1]


def _absolute_import_from_module(
    defining_module: str, imported_module: str | None, level: int
) -> str | None:
    if level == 0:
        return imported_module or None
    package = _relative_import_package_parts(defining_module)
    ascend = level - 1
    if ascend > len(package):
        return None
    base = list(package[: len(package) - ascend] if ascend else package)
    if imported_module:
        base.extend(imported_module.split("."))
    return ".".join(base) or None


def _resolve_qualified_native_callable(
    import_target: str, *, resolving: frozenset[str] = frozenset()
):
    """Follow one static re-export route to an installed extension symbol."""
    if "." not in import_target or import_target in resolving:
        return None
    resolving = resolving | {import_target}
    module_name, attr = import_target.rsplit(".", 1)
    origin = _installed_native_extension(module_name)
    if origin is not None:
        from sugar_lift_py_tests.floor import NativeCallableValue

        return NativeCallableValue(
            qualified_name=import_target,
            module_origin=origin,
        )

    installed = _installed_source(module_name)
    if installed is None:
        return None
    source, sourcefile = installed
    try:
        parsed = parsed_tree(source, sourcefile)
    except SyntaxError:
        return None
    if any(
        isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
        and statement.name == attr
        for statement in parsed.body
    ):
        return None

    reexports: list[str] = []
    for statement in parsed.body:
        if not isinstance(statement, ast.ImportFrom):
            continue
        for alias in statement.names:
            if (alias.asname or alias.name) != attr or alias.name == "*":
                continue
            target_module = _absolute_import_from_module(
                module_name, statement.module, statement.level
            )
            if target_module:
                reexports.append(f"{target_module}.{alias.name}")
    if len(reexports) != 1:
        return None
    return _resolve_qualified_native_callable(reexports[0], resolving=resolving)


def _imported_module_source(module_name: str) -> tuple[str, str] | None:
    """Compatibility source fallback for modules without a passive file spec."""
    try:
        from _pytest.outcomes import Skipped
    except ImportError:

        class Skipped(BaseException):  # type: ignore[no-redef]
            pass

    try:
        module = importlib.import_module(module_name)
        sourcefile = inspect.getsourcefile(module)
        if not sourcefile:
            return None
        return Path(sourcefile).read_text(encoding="utf-8"), sourcefile
    except Skipped as skipped:
        from sugar_lift_py_tests.factory import (
            FactoryAuditRow,
            FactoryGapInfo,
            GapKind,
            GapLocus,
            factory_panic,
        )

        info = FactoryGapInfo(
            owner="install_source_dig.module_sibling_function_nodes",
            blame=module_name,
            observed=type(skipped).__name__,
            requested="installed Python source for optional-dependency module",
            fix="install the module's Python source before install-source body dig",
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )
        factory_panic(
            info,
            FactoryAuditRow(
                role="install-source import",
                status=FactoryAuditStatus.FLOOR_GAP,
                observed=type(skipped).__name__,
                blame=module_name,
                selected=None,
                candidates=[],
                message=f"install-source import raised pytest Skipped: {skipped}; {info.message}",
            ),
        )
    except (ImportError, OSError, TypeError, UnicodeError):
        return None


def _materialize_index_definitions(index: _InstalledSourceIndex) -> dict[str, ast.AST]:
    """Reparse an index into caller-owned nodes; cached state stays immutable."""
    parsed = parsed_tree(index.source, index.sourcefile)
    nodes_by_locus = {
        (node.name, node.lineno, node.col_offset): node
        for node in ast.walk(parsed)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    materialized: dict[str, ast.AST] = {}
    for definition in index.definitions:
        node = nodes_by_locus.get(
            (definition.name, definition.lineno, definition.col_offset)
        )
        if node is None:
            continue
        node = copy.deepcopy(node)
        node.decorator_list = []
        node._sugar_source = index.source  # type: ignore[attr-defined]
        node._sugar_file = index.sourcefile  # type: ignore[attr-defined]
        node._sugar_bridge_name = definition.bridge_name  # type: ignore[attr-defined]
        materialized[definition.key] = node
    return materialized


def module_sibling_function_nodes(module_name: str) -> dict:
    """Return fresh AST nodes materialized from the bounded immutable index."""
    index = _installed_source_index(module_name)
    if index is None:
        return {}
    return _materialize_index_definitions(index)


def _literal_string_sequence(node: ast.AST) -> tuple[str, ...] | None:
    if not isinstance(node, (ast.List, ast.Tuple)):
        return None
    values: list[str] = []
    for element in node.elts:
        if not isinstance(element, ast.Constant) or not isinstance(element.value, str):
            return None
        values.append(element.value)
    return tuple(values)


def _static_module_exports(module_name: str) -> frozenset[str] | None:
    """Read one literal ``__all__`` manifest without importing its module."""
    installed = _installed_source(module_name)
    if installed is None:
        return None
    source, sourcefile = installed
    try:
        parsed = parsed_tree(source, sourcefile)
    except SyntaxError:
        return None
    manifests: list[tuple[str, ...]] = []
    for statement in parsed.body:
        value = None
        if isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "__all__"
            for target in statement.targets
        ):
            value = statement.value
        elif (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and statement.target.id == "__all__"
        ):
            value = statement.value
        if value is None:
            continue
        manifest = _literal_string_sequence(value)
        if manifest is None:
            return None
        manifests.append(manifest)
    if len(manifests) != 1:
        return None
    return frozenset(manifests[0])


def resolve_install_source_funcdef(import_target: str):
    """Resolve an exact qualified direct/re-exported FunctionDef without import."""
    return _resolve_qualified_function_fragment(import_target)


def resolve_contextmanager_exit_contract(import_target: str):
    """Prove the closed static subset of ``@contextmanager`` exits.

    This deliberately returns ``None`` for every shape whose exception
    disposition depends on runtime control flow.  Absence is consumed by
    WithSugar as its existing named gap, never as non-suppression.
    """
    if "." not in import_target:
        return None
    module_name, attr = import_target.rsplit(".", 1)
    index = _installed_source_index(module_name)
    if index is None:
        return None
    try:
        parsed = parsed_tree(index.source, index.sourcefile)
    except SyntaxError:
        return None
    definitions = [
        statement
        for statement in parsed.body
        if isinstance(statement, ast.FunctionDef) and statement.name == attr
    ]
    if len(definitions) != 1 or not _is_contextmanager_definition(
        definitions[0], parsed
    ):
        return None
    definition = definitions[0]
    tries = [
        statement for statement in definition.body if isinstance(statement, ast.Try)
    ]
    if len(tries) != 1:
        return None
    protected = tries[0]
    if definition.body[-1] is not protected or any(
        isinstance(node, ast.Return) for node in ast.walk(definition)
    ):
        return None
    yields = [node for node in ast.walk(definition) if isinstance(node, ast.Yield)]
    if len(yields) != 1 or not any(
        node is yields[0]
        for statement in protected.body
        for node in ast.walk(statement)
    ):
        return None
    if protected.orelse:
        return None

    from sugar_lift_py_tests.floor.call_site_value import ExitSuppressionContract

    if not protected.handlers:
        if _contains_exit_override(protected.finalbody):
            return None
        return ExitSuppressionContract.never_suppresses()

    if len(protected.handlers) != 1 or protected.finalbody:
        return None
    handler = protected.handlers[0]
    exception_name = _static_exception_name(handler.type)
    if (
        exception_name is None
        or not handler.body
        or any(not isinstance(statement, ast.Pass) for statement in handler.body)
    ):
        return None
    return ExitSuppressionContract.suppresses((exception_name,))


def _is_contextmanager_definition(
    definition: ast.FunctionDef, module: ast.Module
) -> bool:
    imported_names = {
        alias.asname or alias.name: f"{statement.module}.{alias.name}"
        for statement in module.body
        if isinstance(statement, ast.ImportFrom) and statement.module
        for alias in statement.names
    }
    module_aliases = {
        alias.asname or alias.name: alias.name
        for statement in module.body
        if isinstance(statement, ast.Import)
        for alias in statement.names
    }
    for decorator in definition.decorator_list:
        if isinstance(decorator, ast.Name):
            if imported_names.get(decorator.id) == "contextlib.contextmanager":
                return True
        elif (
            isinstance(decorator, ast.Attribute)
            and decorator.attr == "contextmanager"
            and isinstance(decorator.value, ast.Name)
            and module_aliases.get(decorator.value.id) == "contextlib"
        ):
            return True
    return False


def _contains_exit_override(statements: list[ast.stmt]) -> bool:
    return any(
        isinstance(node, (ast.Return, ast.Raise, ast.Yield, ast.YieldFrom))
        for statement in statements
        for node in ast.walk(statement)
    )


def _static_exception_name(node: ast.expr | None) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parts: list[str] = [node.attr]
        value = node.value
        while isinstance(value, ast.Attribute):
            parts.append(value.attr)
            value = value.value
        if isinstance(value, ast.Name):
            parts.append(value.id)
            return ".".join(reversed(parts))
    return None


def _is_overload_declaration(
    definition: ast.FunctionDef | ast.AsyncFunctionDef,
) -> bool:
    """Whether a definition is a typing overload declaration, not a body."""
    for decorator in definition.decorator_list:
        if isinstance(decorator, ast.Name) and decorator.id == "overload":
            return True
        if (
            isinstance(decorator, ast.Attribute)
            and decorator.attr == "overload"
            and isinstance(decorator.value, ast.Name)
            and decorator.value.id == "typing"
        ):
            return True
    return False


def _resolve_qualified_function_fragment(
    import_target: str, *, resolving: frozenset[str] = frozenset()
):
    if "." not in import_target or import_target in resolving:
        return None
    resolving = resolving | {import_target}
    module_name, attr = import_target.rsplit(".", 1)
    index = _installed_source_index(module_name)
    if index is None:
        return None
    source = index.source
    sourcefile = index.sourcefile
    try:
        parsed = parsed_tree(source, sourcefile)
    except SyntaxError:
        return None

    declarations = [
        statement
        for statement in parsed.body
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
        and statement.name == attr
    ]
    definitions = [
        statement
        for statement in declarations
        if not _is_overload_declaration(statement)
    ]
    if len(definitions) > 1:
        from sugar_lift_py_tests.factory import factory_panic_gap
        from sugar_lift_py_tests.factory.factory_gap_info import GapKind, GapLocus

        factory_panic_gap(
            owner="install_source_dig",
            blame=sourcefile,
            observed=import_target,
            requested="resolve a unique top-level FunctionDef from exact installed source",
            fix="remove duplicate qualified definitions or cite one exact source memento",
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )
    if len(definitions) == 1:
        from sugar_lift_py_tests.factory.source_fragment import SourceFragment

        node = copy.deepcopy(definitions[0])
        node.decorator_list = []
        node._sugar_source = source  # type: ignore[attr-defined]
        node._sugar_file = sourcefile  # type: ignore[attr-defined]
        node._sugar_bridge_name = import_target  # type: ignore[attr-defined]
        return SourceFragment.from_node(node, sourcefile, source=source)

    reexports: list[str] = []
    for statement in parsed.body:
        if not isinstance(statement, ast.ImportFrom):
            continue
        target_module = _absolute_import_from_module(
            module_name, statement.module, statement.level
        )
        if not target_module:
            continue
        for alias in statement.names:
            if alias.name == "*":
                exports = _static_module_exports(target_module)
                if exports is not None and attr in exports:
                    reexports.append(f"{target_module}.{attr}")
                continue
            if (alias.asname or alias.name) != attr:
                continue
            reexports.append(f"{target_module}.{alias.name}")
    if len(reexports) > 1:
        from sugar_lift_py_tests.factory import factory_panic_gap
        from sugar_lift_py_tests.factory.factory_gap_info import GapKind, GapLocus

        factory_panic_gap(
            owner="install_source_dig",
            blame=sourcefile,
            observed=import_target,
            requested=(
                "resolve one exact qualified re-export route or one exact "
                "manifest-witnessed star re-export route"
            ),
            fix="cite a unique source-qualified re-export instead of alternatives",
            gap_kind=GapKind.FLOOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )
    if len(reexports) == 1:
        return _resolve_qualified_function_fragment(reexports[0], resolving=resolving)
    return None


def _module_assignment_name(statement: ast.stmt) -> str | None:
    if isinstance(statement, ast.Assign):
        names = [
            target.id for target in statement.targets if isinstance(target, ast.Name)
        ]
        return names[0] if len(names) == 1 else None
    if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
        return statement.target.id if statement.value is not None else None
    return None


def _module_declaration_name(statement: ast.stmt) -> str | None:
    assigned = _module_assignment_name(statement)
    if assigned is not None:
        return assigned
    if isinstance(
        statement,
        (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef),
    ):
        return statement.name
    return None


def _module_import_bindings(statement: ast.stmt) -> dict[str, tuple[str, str | None]]:
    bindings: dict[str, tuple[str, str | None]] = {}
    if isinstance(statement, ast.Import):
        for alias in statement.names:
            bound = alias.asname or alias.name.split(".", 1)[0]
            module_name = alias.name if alias.asname else alias.name.split(".", 1)[0]
            bindings[bound] = (module_name, None)
    elif isinstance(statement, ast.ImportFrom):
        module_name = statement.module or ""
        for alias in statement.names:
            if alias.name == "*":
                continue
            bindings[alias.asname or alias.name] = (module_name, alias.name)
    return bindings


def _loaded_names(node: ast.AST | None) -> set[str]:
    if node is None:
        return set()
    return {
        child.id
        for child in ast.walk(node)
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load)
    }


def _function_definition_dependencies(
    statement: ast.FunctionDef | ast.AsyncFunctionDef,
) -> set[str]:
    """Names constructed when this lifter builds a function definition.

    The function body is deferred. Decorators, positional defaults, and
    keyword-only defaults are reduced when ``StatementFunctionDefSugar``
    constructs the callable, so each belongs to the defining module's lexical
    temporal rather than the consumer's. Annotations remain deferred by the
    current callable representation (and by ``from __future__ import
    annotations`` sources such as pandas), so they are not eagerly seeded here.
    """
    needed: set[str] = set()
    eager_terms = (
        *statement.decorator_list,
        *statement.args.defaults,
        *(default for default in statement.args.kw_defaults if default is not None),
    )
    for term in eager_terms:
        needed.update(_loaded_names(term))
    return needed


def _ctx_with_required_module_bindings(
    statements: list[ast.stmt],
    target_index: int,
    needed: set[str],
    *,
    source: str,
    sourcefile: str,
    ctx: Any,
    resolving: frozenset[str],
):
    """Construct a target node's lexical module bindings, need-first.

    The imported value belongs to its defining module, not to the consumer's
    temporal. Reverse selection finds only prerequisite declarations; forward
    construction then sends each selected declaration through the ordinary
    factory. This is the module-value analogue of install-source function-global
    seeding and deliberately does not execute or fabricate Python constants.
    """
    from dataclasses import replace

    from sugar_lift_py_tests.claim import SugarRole
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment
    from sugar_lift_py_tests.floor import (
        BlockValue,
        ClassValue,
        ImportAliasValue,
    )
    from sugar_lift_py_tests.outcome import Incomplete, complete_value
    from sugar_lift_py_tests.temporal import TemporalContext

    # Imported values are constructed in the defining module's lexical frame.
    # Consumer locals are not module globals and must never satisfy these Names.
    needed = set(needed)

    selected: list[ast.stmt] = []
    for statement in reversed(statements[:target_index]):
        declaration = _module_declaration_name(statement)
        imports = _module_import_bindings(statement)
        owned = ({declaration} if declaration is not None else set()) | set(imports)
        wanted = owned & needed
        if not wanted:
            continue
        selected.append(statement)
        needed.difference_update(wanted)
        if declaration in wanted:
            if isinstance(statement, (ast.Assign, ast.AnnAssign)):
                needed.update(_loaded_names(statement.value))
            elif isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                needed.update(_function_definition_dependencies(statement))
    selected.reverse()

    lexical = TemporalContext.empty()
    module_ctx = replace(ctx, temporal=lexical, module_temporal=lexical)
    for statement in selected:
        imports = _module_import_bindings(statement)
        if imports:
            temporal = module_ctx.temporal
            for bound, (module_name, imported_name) in imports.items():
                import_target = (
                    f"{module_name}.{imported_name}" if imported_name else module_name
                )
                resolved = (
                    resolve_install_source_value(
                        import_target, module_ctx, _resolving=resolving
                    )
                    if imported_name
                    else None
                )
                temporal = temporal.bind_value(
                    bound,
                    ImportAliasValue(
                        imported_name or module_name,
                        bound,
                        import_target=import_target,
                        resolved_value=resolved,
                    ),
                )
            module_ctx = replace(
                module_ctx, temporal=temporal, module_temporal=temporal
            )
            continue

        if isinstance(statement, ast.ClassDef):
            temporal = module_ctx.temporal.bind_value(
                statement.name,
                ClassValue(
                    name=statement.name,
                    bases=(),
                    record=BlockValue(()),
                ),
            )
            module_ctx = replace(
                module_ctx, temporal=temporal, module_temporal=temporal
            )
            continue

        fragment = SourceFragment.from_node(statement, sourcefile, source=source)
        outcome = module_ctx.build_body(fragment, SugarRole.STATEMENT).reduce(
            module_ctx
        )
        if isinstance(outcome, Incomplete):
            # Runtime-selected prerequisites do not have a static value to
            # seed. Keep the imported coordinate unresolved for its consumer
            # instead of force-reading an effect as though it had completed.
            return None
        complete_value(outcome, owner="install-source module prerequisite")
        extended = outcome.extend_scope(module_ctx)
        module_ctx = replace(extended, module_temporal=extended.temporal)
    return module_ctx


def resolve_install_source_value(
    import_target: str, ctx, *, _resolving: frozenset[str] = frozenset()
):
    """Construct a cited module-level imported name from its Python source.

    A source-backed import is statically knowable. Find the defining statement,
    construct the module globals its RHS needs, and send all values through the
    ordinary factory. Any missing Sugar or floor arm propagates its FactoryPanic;
    this function never converts a dig gap into a runtime effect.
    """
    if "." not in import_target or import_target in _resolving:
        return None
    resolving = _resolving | {import_target}
    native = _resolve_qualified_native_callable(import_target, resolving=_resolving)
    if native is not None:
        return native
    module_name, attr = import_target.rsplit(".", 1)
    installed = _installed_source(module_name)
    if installed is None:
        return None
    source, sourcefile = installed
    try:
        parsed = parsed_tree(source, sourcefile)
    except SyntaxError:
        return None

    from sugar_lift_py_tests.claim import SugarRole
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment
    from sugar_lift_py_tests.outcome import Incomplete, complete_value

    if _installed_class_is_exception(
        module_name,
        attr,
        parsed,
        resolving=frozenset(),
    ):
        from sugar_lift_py_tests.floor import ExceptionClassValue

        return ExceptionClassValue(import_target)

    function = _resolve_qualified_function_fragment(import_target, resolving=_resolving)
    if function is not None:
        defining_source = function.node._sugar_source  # type: ignore[attr-defined]
        defining_file = function.node._sugar_file  # type: ignore[attr-defined]
        defining_tree = copy.deepcopy(parsed_tree(defining_source, defining_file))
        target_index = next(
            index
            for index, statement in enumerate(defining_tree.body)
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
            and statement.lineno == function.node.lineno
            and statement.name == function.function_name()
        )
        definition = defining_tree.body[target_index]
        definition._sugar_source = defining_source  # type: ignore[attr-defined]
        definition._sugar_file = defining_file  # type: ignore[attr-defined]
        definition._sugar_bridge_name = function.node._sugar_bridge_name  # type: ignore[attr-defined]
        function = SourceFragment.from_node(
            definition, defining_file, source=defining_source
        )
        module_ctx = _ctx_with_required_module_bindings(
            defining_tree.body,
            target_index,
            _function_definition_dependencies(definition),
            source=defining_source,
            sourcefile=defining_file,
            ctx=ctx,
            resolving=resolving,
        )
        if module_ctx is None:
            return None
        body = module_ctx.build_body(function, SugarRole.STATEMENT)
        outcome = body.reduce(module_ctx)
        if isinstance(outcome, Incomplete):
            return None
        return complete_value(outcome, owner="install-source imported function")

    for target_index, statement in enumerate(parsed.body):
        value_node = None
        if isinstance(statement, (ast.Assign, ast.AnnAssign)):
            targets = (
                statement.targets
                if isinstance(statement, ast.Assign)
                else [statement.target]
            )
            if any(
                isinstance(target, ast.Name) and target.id == attr for target in targets
            ):
                value_node = statement.value
        if value_node is not None:
            module_ctx = _ctx_with_required_module_bindings(
                parsed.body,
                target_index,
                _loaded_names(value_node),
                source=source,
                sourcefile=sourcefile,
                ctx=ctx,
                resolving=resolving,
            )
            if module_ctx is None:
                return None
            body = module_ctx.build_body(
                SourceFragment.from_node(value_node, sourcefile, source=source),
                SugarRole.TERM,
            )
            outcome = body.reduce(module_ctx)
            if isinstance(outcome, Incomplete):
                return None
            return complete_value(outcome, owner="install-source imported value")
    return None


def _installed_class_is_exception(
    module_name: str,
    class_name: str,
    parsed: ast.Module,
    *,
    resolving: frozenset[str],
) -> bool:
    """Prove one exact source class has transitive exception ancestry."""
    qualified = f"{module_name}.{class_name}"
    if qualified in resolving:
        return False
    resolving = resolving | {qualified}
    declarations = [
        statement
        for statement in parsed.body
        if isinstance(statement, ast.ClassDef) and statement.name == class_name
    ]
    if len(declarations) != 1:
        return False
    imports = _static_import_targets(module_name, parsed)
    classes = {
        statement.name: statement
        for statement in parsed.body
        if isinstance(statement, ast.ClassDef)
    }
    return any(
        _base_is_exception(
            base,
            module_name=module_name,
            parsed=parsed,
            classes=classes,
            imports=imports,
            resolving=resolving,
        )
        for base in declarations[0].bases
    )


def _base_is_exception(
    base: ast.expr,
    *,
    module_name: str,
    parsed: ast.Module,
    classes: dict[str, ast.ClassDef],
    imports: dict[str, str],
    resolving: frozenset[str],
) -> bool:
    from sugar_lift_py_tests.temporal.builtin_name_bindings import (
        BUILTIN_EXCEPTION_NAMES,
    )

    if isinstance(base, ast.Name):
        if base.id in BUILTIN_EXCEPTION_NAMES:
            return True
        if base.id in classes:
            return _installed_class_is_exception(
                module_name, base.id, parsed, resolving=resolving
            )
        target = imports.get(base.id)
    else:
        target = _dotted_ast_name(base)
        if target is not None:
            head, separator, rest = target.partition(".")
            imported = imports.get(head)
            if imported is not None:
                target = f"{imported}.{rest}" if separator else imported
    if target is None or "." not in target or target in resolving:
        return False
    target_module, target_name = target.rsplit(".", 1)
    installed = _installed_source(target_module)
    if installed is None:
        return False
    source, sourcefile = installed
    try:
        target_tree = parsed_tree(source, sourcefile)
    except SyntaxError:
        return False
    return _installed_class_is_exception(
        target_module, target_name, target_tree, resolving=resolving
    )


def _static_import_targets(module_name: str, parsed: ast.Module) -> dict[str, str]:
    targets: dict[str, str] = {}
    for statement in parsed.body:
        if isinstance(statement, ast.ImportFrom):
            imported_module = _absolute_import_from_module(
                module_name, statement.module, statement.level
            )
            if imported_module is None:
                continue
            for alias in statement.names:
                if alias.name != "*":
                    targets[alias.asname or alias.name] = (
                        f"{imported_module}.{alias.name}"
                    )
        elif isinstance(statement, ast.Import):
            for alias in statement.names:
                targets[alias.asname or alias.name.split(".")[0]] = alias.name
    return targets


def _dotted_ast_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        receiver = _dotted_ast_name(node.value)
        if receiver is not None:
            return f"{receiver}.{node.attr}"
    return None


def resolve_install_source_class_method(qualified_class: str, method_name: str):
    """Resolve ``module.Class.method`` to a FunctionDef SourceFragment, or None."""
    if not qualified_class or not method_name or "." not in qualified_class:
        return None
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment

    module_name, class_name = qualified_class.rsplit(".", 1)
    siblings = module_sibling_function_nodes(module_name)
    node = siblings.get(f"{module_name}.{class_name}.{method_name}") or siblings.get(
        f"{class_name}.{method_name}"
    )
    if node is not None:
        return SourceFragment.from_node(
            node, getattr(node, "_sugar_file", f"<{module_name}>")
        )

    try:
        module = importlib.import_module(module_name)
        cls = getattr(module, class_name)
        if not inspect.isclass(cls):
            return None
        obj = cls.__dict__.get(method_name)
        if obj is None:
            obj = getattr(cls, method_name, None)
        if obj is None or not callable(obj):
            return None
        source = textwrap.dedent(inspect.getsource(obj))
        sourcefile = inspect.getsourcefile(obj) or f"<{module_name}>"
    except (ImportError, AttributeError, OSError, TypeError):
        return None
    try:
        parsed = SourceFragment.from_source_private(source, sourcefile)
    except SyntaxError:
        return None
    for child in parsed.walk():
        if child.observed == "FunctionDef" and child.function_name() == method_name:
            child.node.decorator_list = []  # type: ignore[attr-defined]
            child.node._sugar_source = source  # type: ignore[attr-defined]
            child.node._sugar_file = sourcefile  # type: ignore[attr-defined]
            child.node._sugar_bridge_name = f"{qualified_class}.{method_name}"  # type: ignore[attr-defined]
            return child
    return None


def resolve_call_funcdef(target_name: str, ctx: Any):
    """Resolve a plain-name call target to a FunctionDef SourceFragment, or None."""
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment

    if not target_name or ctx is None:
        return None

    resolver = getattr(ctx, "name_resolver", None) or {}
    node = resolver.get(target_name)
    if node is not None:
        filename = getattr(ctx, "filename", "<module>")
        site = SourceFragment.from_node(node, filename)
        if site.observed == "FunctionDef":
            sugar_file = getattr(node, "_sugar_file", None) or filename
            sugar_source = getattr(node, "_sugar_source", None)
            if sugar_source is None and sugar_file and Path(sugar_file).is_file():
                try:
                    sugar_source = Path(sugar_file).read_text(encoding="utf-8")
                except OSError:
                    sugar_source = None
            if sugar_source is not None:
                node._sugar_source = sugar_source  # type: ignore[attr-defined]
                node._sugar_file = sugar_file  # type: ignore[attr-defined]
            return site

    from_imports = getattr(ctx, "from_imports", None) or {}
    if target_name in from_imports:
        mod, attr = from_imports[target_name]
        qualified = f"{mod}.{attr}" if mod else attr
        if mod:
            siblings = module_sibling_function_nodes(mod)
            n = siblings.get(qualified) or siblings.get(attr)
            if n is not None:
                return SourceFragment.from_node(
                    n, getattr(n, "_sugar_file", f"<{mod}>")
                )
        return resolve_install_source_funcdef(qualified)

    return None


def _receiver_class_name(receiver_floor: Any) -> str | None:
    """Best-effort class name from a reduced method receiver floor.

    CallSiteValue ctor receivers expose ``target_name``; ObjectValue exposes
    ``class_name``. Both enable nested method dig (self.method) under budget
    without vendor-only name==sign special cases.
    """
    if receiver_floor is None:
        return None
    target = getattr(receiver_floor, "target_name", None)
    if isinstance(target, str) and target:
        return target
    class_name = getattr(receiver_floor, "class_name", None)
    if isinstance(class_name, str) and class_name:
        return class_name
    bound = getattr(receiver_floor, "bound_name", None) or getattr(
        receiver_floor, "name", None
    )
    if isinstance(bound, str) and bound:
        return bound
    return None


def resolve_method_funcdef(method_name: str, receiver_floor: Any, ctx: Any):
    """Resolve recv.method to a FunctionDef SourceFragment, or None."""
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment

    if not method_name or ctx is None:
        return None

    class_name = _receiver_class_name(receiver_floor)
    resolver = getattr(ctx, "name_resolver", None) or {}

    if class_name:
        key = f"{class_name}.{method_name}"
        node = resolver.get(key)
        if node is not None:
            filename = getattr(ctx, "filename", "<module>")
            site = SourceFragment.from_node(node, filename)
            if site.observed == "FunctionDef":
                sugar_file = getattr(node, "_sugar_file", None) or filename
                sugar_source = getattr(node, "_sugar_source", None)
                if sugar_source is None and sugar_file and Path(sugar_file).is_file():
                    try:
                        sugar_source = Path(sugar_file).read_text(encoding="utf-8")
                    except OSError:
                        sugar_source = None
                if sugar_source is not None:
                    node._sugar_source = sugar_source  # type: ignore[attr-defined]
                    node._sugar_file = sugar_file  # type: ignore[attr-defined]
                return site

        from_imports = getattr(ctx, "from_imports", None) or {}
        if class_name in from_imports:
            mod, attr = from_imports[class_name]
            qualified = f"{mod}.{attr}" if mod else attr
            return resolve_install_source_class_method(qualified, method_name)

    return None


def method_body_is_attachable(fn_site) -> bool:
    """Whether attaching dig body is safe under current floors.

    Allows a straight-line prefix of Assign/Pass/Expr then a single Return.
    Return expr may be Name/const/attr/BinOp/Call once CallSiteValue binary
    dispatch totalizes ``+`` (and friends). Multi-branch / raise / with stay out.
    """
    if fn_site is None or fn_site.observed != "FunctionDef":
        return False
    frags = fn_site.function_body()
    if not frags:
        return False
    *prefix, last = frags
    for stmt in prefix:
        if stmt.observed not in (
            "Assign",
            "AnnAssign",
            "AugAssign",
            "Expr",
            "Pass",
            "Try",
            "If",
        ):
            return False
    # Terminal Return with attachable expr, or Try/If that carries return (e.g. base64_decode).
    if last.observed == "Return" and last.return_value() is not None:
        return _return_expr_attachable(last.return_value())
    if last.observed in ("Try", "If"):
        return True
    return False


def _return_expr_attachable(rv) -> bool:
    obs = rv.observed
    if obs in ("Name", "Constant", "PrimitiveLiteral", "JoinedStr"):
        return True
    if obs == "Attribute":
        recv = rv.attr_receiver()
        return recv is not None and recv.observed == "Name"
    if obs == "BinOp":
        # Recurse both sides so value + self.sep + call is fine.
        try:
            left = rv.binop_left()
            right = rv.binop_right()
        except Exception:
            return True
        return _return_expr_attachable(left) and _return_expr_attachable(right)
    if obs == "Call":
        return True
    return False


@dataclass(frozen=True)
class SequentialDigBody:
    """Reduce straight-line statements; surface one diggable return floor.

    Used when method bodies are ``x = f(x); return x + ...``. Dig wants the
    return floor, not a BlockValue record. Scope threads via BoundVar.

    An unguarded ``ReturnValue`` is terminal: dig returns that floor and does
    not walk later statements. Walking past an early return previously kept
    the *last* return (e.g. fall-through ``return 0`` after a taken
    ``if ...: return 7``), which fabricated a false Derived EUF residue and
    dual-refuted truthful control-flow witnesses (#4387). Guarded /
    multi-exit faces stay Incomplete so dig is opaque rather than lying.
    """

    statements: tuple  # SugarBody STATEMENT
    # The dug FunctionDef's SourceFragment: the terminal-effect witness is
    # constructed from a real fragment, never from a blame string.
    fn_site: Any = None

    def desugar(self, ctx: Any = None):
        from sugar_lift_py_tests.floor.guarded_return import GuardedReturn
        from sugar_lift_py_tests.floor.return_value import ReturnValue
        from sugar_lift_py_tests.outcome import Complete, Incomplete

        cur = ctx
        saw_guarded_exit = False
        for stmt in self.statements:
            if saw_guarded_exit:
                # A prior face already posted a GuardedReturn. Later statements
                # ride under branch polarity (e.g. fall-through after
                # ``if z in xs: return 1`` / ``return 0``). Dig must not pin the
                # fall-through as an unguarded literal Derived residue.
                return self._control_flow_incomplete()
            outcome = stmt.reduce(cur)
            from sugar_lift_py_tests.outcome import Incomplete as _Inc

            if isinstance(outcome, _Inc):
                return outcome
            cur = outcome.extend_scope(cur)
            for item in outcome.contribution():
                # Exact unguarded return only — GuardedReturn is multi-exit.
                if type(item) is ReturnValue:
                    # Dig wants the returned floor, not the ReturnValue wrapper.
                    return Complete(item.value)
                if isinstance(item, GuardedReturn):
                    saw_guarded_exit = True
            follow = getattr(outcome, "follow", None)
            if callable(follow):
                step = follow()
                if not step.continues:
                    # Nested block already halted (e.g. BlockValue with return).
                    # Do not reduce later statements; no unguarded dig pin.
                    break
                if step.transform is not None:
                    # Continuation is polarity-guarded; dig cannot pin one arm.
                    return self._control_flow_incomplete()
        # No unguarded ReturnValue: either multi-exit (GuardedReturn) or no
        # return at all. Dig stays opaque so Derived residue cannot invent a
        # single fall-through literal across control flow.
        return self._control_flow_incomplete()

    def _control_flow_incomplete(self):
        from sugar_lift_py_tests.effect import (
            ConditionalExpressionRuntimeEffect,
            RuntimeEffectWitness,
        )
        from sugar_lift_py_tests.ir import ctor, str_const
        from sugar_lift_py_tests.outcome import Incomplete

        terminal = self.statements[-1] if self.statements else None
        audit_row = getattr(terminal, "audit_row", None)
        blame = getattr(audit_row, "blame", "<install-source-dig>")
        observed = getattr(audit_row, "observed", "SequentialDigBody")
        # The witness is constructed from the real fragment: the terminal
        # statement's own site when its sugar carries one, else the dug
        # FunctionDef fragment threaded in at construction. The audit-row
        # blame string stays in the reason prose only.
        site = getattr(getattr(terminal, "sugar", None), "site", None) or self.fn_site
        if site is None:
            from sugar_lift_py_tests.factory.factory_gap import factory_panic_gap

            factory_panic_gap(
                owner="SequentialDigBody",
                blame=str(blame),
                observed=str(observed),
                requested="SourceFragment for terminal dig runtime effect",
                fix=(
                    "thread the dug FunctionDef fragment into SequentialDigBody "
                    "(build_dig_body does this); do not mint a RuntimeEffect "
                    "without a real site"
                ),
            )
        terminal_selection = ctor(
            "py.sequential_terminal",
            [str_const(str(blame)), str_const(str(observed))],
        )
        return Incomplete(
            ConditionalExpressionRuntimeEffect(
                f"{blame}: {observed} leaves the sequential dig return value "
                "dependent on runtime control flow",
                witness=RuntimeEffectWitness(
                    operation=ctor("py.conditional_select", [terminal_selection]),
                    operand=terminal_selection,
                    site=site,
                ),
            )
        )


@dataclass(frozen=True)
class ContextualizedDigBody:
    """A dig body carrying the callee's lexical module temporal.

    Legacy arithmetic floors force CallSiteValue with ``ctx=None``. The call's
    curried actuals therefore arrive in a fresh context. Overlay those actuals
    onto the captured callee context so module bindings survive while parameters
    still replace their symbolic build-time placeholders.
    """

    body: object
    base_context: Any

    def desugar(self, ctx: Any = None):
        reduce_ctx = self.base_context
        if ctx is not None:
            temporal = self.base_context.temporal
            for binding in ctx.temporal.bindings:
                temporal = temporal.bind_value(
                    binding.name,
                    binding.value,
                    blame=binding.blame,
                )
            reduce_ctx = ctx.with_temporal(temporal)
        return self.body.reduce(reduce_ctx)


def _contextualized_dig_body(body, base_context):
    from sugar_lift_py_tests.claim import SugarRole
    from sugar_lift_py_tests.sugar_body import SugarBody

    return SugarBody(
        sugar=ContextualizedDigBody(body=body, base_context=base_context),
        role=SugarRole.TERM,
    )


def build_dig_body(fn_site, ctx: Any, *, require_attachable: bool = False):
    """Build diggable body for ``fn_site`` FunctionDef, or None on failure."""
    if fn_site is None or fn_site.observed != "FunctionDef":
        return None
    if require_attachable and not method_body_is_attachable(fn_site):
        return None
    from sugar_lift_py_tests.claim import SugarRole
    from sugar_lift_py_tests.factory.sugar_constructors import (
        _ctx_with_formal_binds,
        build_bridge_body,
    )
    from sugar_lift_py_tests.sugar_body import SugarBody

    building = getattr(ctx, "building", frozenset()) or frozenset()
    name = fn_site.function_name()
    bridge = getattr(fn_site.node, "_sugar_bridge_name", None) or name
    if name in building or bridge in building:
        return None
    try:
        from dataclasses import replace

        body_ctx = replace(ctx, building=building | {name, bridge})
        mod = getattr(fn_site.node, "_sugar_bridge_name", "") or ""
        if "." in str(mod):
            parts = str(mod).split(".")
            if len(parts) >= 3 and parts[-2][:1].isupper():
                module_name = ".".join(parts[:-2])
            elif len(parts) >= 2:
                module_name = parts[0]
            else:
                module_name = str(mod)
            siblings = module_sibling_function_nodes(module_name)
            if siblings:
                merged = dict(getattr(body_ctx, "name_resolver", None) or {})
                merged.update(siblings)
                body_ctx = replace(body_ctx, name_resolver=merged)

        formal_ctx = _ctx_with_formal_binds(fn_site, body_ctx)
        frags = fn_site.function_body()
        # Single return expr → existing bridge body (TERM sugar).
        if (
            len(frags) == 1
            and frags[0].observed == "Return"
            and frags[0].return_value() is not None
        ):
            return _contextualized_dig_body(
                build_bridge_body(fn_site, body_ctx), formal_ctx
            )

        # Straight-line Assign* + Return → sequential dig body under formals.
        statements = tuple(
            formal_ctx.build_body(stmt, SugarRole.STATEMENT) for stmt in frags
        )
        sequential = SugarBody(
            sugar=SequentialDigBody(statements=statements, fn_site=fn_site),
            role=SugarRole.TERM,
        )
        return _contextualized_dig_body(sequential, formal_ctx)
    except Exception:
        return None


def dig_parameters_for_body(fn_site, arg_count: int, keyword_names: tuple[str, ...]):
    """Formal names for CallSiteValue.parameters when body dig can run."""
    if fn_site is None:
        return keyword_names
    formals = tuple(fn_site.function_params())
    if keyword_names:
        if len(keyword_names) == arg_count:
            return keyword_names
        if len(formals) == arg_count:
            return formals
        return keyword_names
    if len(formals) == arg_count:
        return formals
    return ()


def bind_positional_defaults(fn_site, arg_values: tuple, ctx: Any):
    """Fill omitted trailing positional arguments from a resolved def's defaults.

    Only the FunctionDefSugar-owned ordinary positional shape reaches this
    helper. Invalid arities remain unmatched so CallSiteValue raises its normal
    loud arity gap when the body is forced.
    """
    from sugar_lift_py_tests.claim import SugarRole
    from sugar_lift_py_tests.outcome import Complete

    if fn_site is None or not fn_site.function_has_simple_positional_params():
        return Complete(((), arg_values))
    formals = tuple(fn_site.function_params())
    min_args, max_args = fn_site.function_positional_arity()
    if not min_args <= len(arg_values) <= max_args:
        return Complete(((), arg_values))
    missing = max_args - len(arg_values)
    if missing == 0:
        return Complete((formals, arg_values))
    defaults = tuple(fn_site.function_defaults())
    selected = defaults[len(defaults) - missing :]

    def collect(remaining: tuple, accumulated: tuple):
        if not remaining:
            return Complete((formals, (*arg_values, *accumulated)))
        head, *rest = remaining
        return (
            ctx.build_body(head, SugarRole.TERM)
            .reduce(ctx)
            .and_then(lambda value: collect(tuple(rest), (*accumulated, value)))
        )

    return collect(selected, ())


_resolve_install_source_funcdef = resolve_install_source_funcdef
