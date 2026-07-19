"""Install-source body dig: resolve vendor/same-module callees for CallSiteValue.body.

Membrane: fleet/CallSugar emits call:f(...) coordinates. This module resolves
f to a FunctionDef (same module, from_import, or importable module.attr), tags
install-source provenance, and builds a diggable body via ControlFlowBodySugar.

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
import importlib.util
import ast
import copy
import functools
import inspect
import sys
import textwrap
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from sugar_lift_py_tests.factory.factory_audit_row import FactoryAuditStatus
from sugar_lift_python_source.source_oracle import installed_module_source
from sugar_lift_python_source.source_tables import parsed_tree

INSTALLED_SOURCE_INDEX_CAPACITY = 64

# Construction identity for install-source *values*. SourceOracle is not
# extended: it remains the interface for source text. This wraps its CID so
# construction is correctness — once a name is built from pinned source, that
# floor value *is* the system and is never rebuilt for the same identity.
# Capacity is resident ownership only (eviction recomputes; not invalidation).
INSTALL_SOURCE_VALUE_CAPACITY = 256
_MISSING = object()


class InstallSourceValueOracle:
    """The one constructor for source-backed named floor values.

    **Does not extend SourceOracle.** SourceOracle
    (``installed_module_source``) is the sole interface for source text. This
    type *wraps* that pin and is the sole constructor for the floor value of a
    cited ``module.attr``.

    Construction is correctness because no other constructor exists: dig, seed,
    and import-alias resolution must enter through :meth:`resolve`. Same
    SourceOracle CID + name is one identity; the published floor value *is* the
    system for that identity.

    Publishing rules:
      - Complete constructed values are published under the key.
      - Unresolved ``None`` and cycle breaks return without publishing.
      - FactoryPanic propagates and never publishes.
    """

    __slots__ = ("_capacity", "_table", "construct_count", "hit_count")

    def __init__(self, capacity: int = INSTALL_SOURCE_VALUE_CAPACITY) -> None:
        from collections import OrderedDict

        self._capacity = max(int(capacity), 1)
        self._table: OrderedDict[tuple[str, str], Any] = OrderedDict()
        self.construct_count = 0
        self.hit_count = 0

    def identity_key(self, import_target: str) -> tuple[str, str] | None:
        """Construction identity: SourceOracle content CID + name.

        Wraps SourceOracle — does not re-discover or re-parse modules.
        """
        if "." not in import_target:
            return None
        module_name, attr = import_target.rsplit(".", 1)
        installed = installed_module_source(module_name)
        if installed is not None:
            _source, _sourcefile, source_cid = installed
            return (str(source_cid), attr)
        # Native extension / absent module: stabilize on the qualified name only.
        return ("target", import_target)

    def resolve(
        self,
        import_target: str,
        ctx: Any,
        *,
        _resolving: frozenset[str] = frozenset(),
    ) -> Any:
        """Sole construction entry for install-source named values."""
        if "." not in import_target or import_target in _resolving:
            # Cycle break or ill-formed name: never publish.
            return None
        key = self.identity_key(import_target)
        from sugar_lift_py_tests.engine_log import reduction_span

        if key is not None:
            known = self._lookup(key)
            if known is not _MISSING:
                with reduction_span(
                    sugar=import_target,
                    role="dig.resolve_value.hit",
                    site=import_target,
                ):
                    return known

        with reduction_span(
            sugar=import_target,
            role="dig.resolve_value",
            site=import_target,
        ):
            self.construct_count += 1
            value = _construct_install_source_value(
                import_target, ctx, _resolving=_resolving
            )
        # Publish completed answers only. FactoryPanic never reaches here.
        if key is not None:
            self._publish(key, value)
        return value

    def _lookup(self, key: tuple[str, str]) -> Any:
        value = self._table.get(key, _MISSING)
        if value is _MISSING:
            return _MISSING
        self._table.move_to_end(key)
        self.hit_count += 1
        return value

    def _publish(self, key: tuple[str, str], value: Any) -> None:
        if value is None:
            return
        if key in self._table:
            self._table.move_to_end(key)
        self._table[key] = value
        while len(self._table) > self._capacity:
            self._table.popitem(last=False)

    def clear(self) -> None:
        self._table.clear()
        self.construct_count = 0
        self.hit_count = 0


# Process-lifetime sole constructor (wraps SourceOracle; never a second door).
INSTALL_SOURCE_VALUE_ORACLE = InstallSourceValueOracle()


# Dig *body sugar* is a second construction domain: CallSugar/MethodCallSugar
# desugar asked build_dig_body on every callsite. Same FunctionDef pin must not
# re-factory its body statements each time. Context (formals/module temporal)
# is re-wrapped per call; the body sugar structure is the system identity.
DIG_BODY_CAPACITY = 256


class DigBodyOracle:
    """Sole constructor for diggable body *structure* (wraps source pin).

    Does not extend SourceOracle. Identity is defining file + lineno + name
    (and bridge when present). Published value is the pre-context SugarBody
    (bridge body or SequentialDigBody); :func:`build_dig_body` re-wraps
    :class:`ContextualizedDigBody` with the call-site formal context.
    """

    __slots__ = ("_capacity", "_table", "construct_count", "hit_count")

    def __init__(self, capacity: int = DIG_BODY_CAPACITY) -> None:
        from collections import OrderedDict

        self._capacity = max(int(capacity), 1)
        self._table: OrderedDict[tuple[Any, ...], Any] = OrderedDict()
        self.construct_count = 0
        self.hit_count = 0

    def identity_key(self, fn_site: Any) -> tuple[str, int, str, str] | None:
        if fn_site is None or getattr(fn_site, "observed", None) != "FunctionDef":
            return None
        node = fn_site.node
        file = str(
            getattr(node, "_sugar_file", None) or getattr(fn_site, "blame", "") or ""
        )
        lineno = int(getattr(node, "lineno", -1) or -1)
        name = str(fn_site.function_name())
        bridge = str(getattr(node, "_sugar_bridge_name", None) or name)
        if not file or lineno < 0:
            return None
        return (file, lineno, name, bridge)

    def cache_key(self, fn_site: Any, ctx: Any) -> tuple[Any, ...] | None:
        base = self.identity_key(fn_site)
        if base is None:
            return None
        source = getattr(getattr(fn_site, "node", None), "_sugar_source", "") or ""
        from sugar_lift_py_tests.canonicalizer import blake3_512_of

        source_cid = blake3_512_of(str(source).encode()) if source else ""
        # Dig construction builds the body with this context; every factory
        # recognition input must partition the published successful structure.
        return (*base, source_cid, _factory_context_identity(ctx))

    def get(self, key: tuple[str, int, str, str]) -> Any:
        value = self._table.get(key, _MISSING)
        if value is _MISSING:
            return _MISSING
        self._table.move_to_end(key)
        self.hit_count += 1
        return value

    def put(self, key: tuple[str, int, str, str], value: Any) -> None:
        if key in self._table:
            self._table.move_to_end(key)
        self._table[key] = value
        while len(self._table) > self._capacity:
            self._table.popitem(last=False)

    def clear(self) -> None:
        self._table.clear()
        self.construct_count = 0
        self.hit_count = 0


DIG_BODY_ORACLE = DigBodyOracle()


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
    """Return one exact extension-module origin without importing the module.

    Covers ExtensionFileLoader packages (``.so``) and top-level built-in
    modules (``origin='built-in'``, e.g. stdlib ``_csv``). Built-ins are only
    admitted as top-level names so nested package dig never treats a missing
    package as native.
    """
    if not module_name:
        return None
    parts = module_name.split(".")
    search_path = None
    spec = None
    try:
        for index in range(1, len(parts) + 1):
            qualified = ".".join(parts[:index])
            lookup_name = qualified if search_path is None else parts[index - 1]
            spec = importlib.machinery.PathFinder.find_spec(lookup_name, search_path)
            if spec is None:
                # PathFinder does not own built-ins; fall through for top-level.
                if len(parts) == 1:
                    break
                return None
            if index < len(parts):
                search_path = spec.submodule_search_locations
                if search_path is None:
                    return None
        else:
            origin = getattr(spec, "origin", None)
            loader = getattr(spec, "loader", None)
            if (
                isinstance(origin, str)
                and isinstance(loader, importlib.machinery.ExtensionFileLoader)
                and origin.endswith(tuple(importlib.machinery.EXTENSION_SUFFIXES))
            ):
                return origin
    except (ImportError, KeyError, ModuleNotFoundError, OSError, TypeError, ValueError):
        pass
    # Top-level built-in (no package walk). Never for dotted package names.
    if "." in module_name:
        return None
    try:
        builtin_spec = importlib.util.find_spec(module_name)
    except (ImportError, ModuleNotFoundError, ValueError):
        return None
    if (
        builtin_spec is None
        or builtin_spec.loader is not importlib.machinery.BuiltinImporter
        or builtin_spec.origin != "built-in"
    ):
        return None
    return "built-in"


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
    """Follow one static re-export route to an installed extension symbol.

    PathFinder origin is sufficient for callable coordinate authority
    (``NativeCallableValue``) and for refusing dig body. Dig must never
    cold-import a *package* extension tree: that freezes ``dig.resolve_value``
    on vendor package init (sklearn #5338 family D residual) under the product
    bound. ExceptionClassValue remains decidable only from already-resident
    modules or from a top-level extension cold import (stdlib ``_csv``-class).
    """
    if "." not in import_target or import_target in resolving:
        return None
    resolving = resolving | {import_target}
    module_name, attr = import_target.rsplit(".", 1)
    origin = _installed_native_extension(module_name)
    if origin is not None:
        from sugar_lift_py_tests.floor import (
            ExceptionClassValue,
            NativeCallableValue,
        )

        module = sys.modules.get(module_name)
        if module is None and "." not in module_name:
            # Top-level extension only (e.g. ``_csv``). Nested package
            # extensions stay coordinate-only — never pull sklearn/numpy trees.
            try:
                module = importlib.import_module(module_name)
            except (ImportError, ModuleNotFoundError, OSError):
                module = None
        if module is not None:
            try:
                exported = getattr(module, attr)
            except AttributeError:
                return None
            if isinstance(exported, type) and issubclass(exported, BaseException):
                return ExceptionClassValue(import_target)

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
    """Compatibility source fallback for modules without a passive file spec.

    Open-domain absence (missing module, no Python file, unreadable path) is
    ``None`` by pre-check — never a soft TypeError/getsource swallow (#4203).
    """
    try:
        from _pytest.outcomes import Skipped
    except ImportError:

        class Skipped(BaseException):  # type: ignore[no-redef]
            pass

    try:
        module = importlib.import_module(module_name)
    except ImportError:
        return None
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

    # Built-ins and extension modules have no diggable Python source file.
    sourcefile = getattr(module, "__file__", None)
    if not isinstance(sourcefile, str) or not sourcefile.endswith((".py", ".pyi")):
        return None
    try:
        return Path(sourcefile).read_text(encoding="utf-8"), sourcefile
    except (OSError, UnicodeError):
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


def _module_sibling_function_node(module_name: str, *keys: str):
    """Materialize one indexed definition without deepcopying its siblings."""
    index = _installed_source_index(module_name)
    if index is None:
        return None
    wanted = next(
        (definition for definition in index.definitions if definition.key in keys),
        None,
    )
    if wanted is None:
        return None
    parsed = parsed_tree(index.source, index.sourcefile)
    node = next(
        (
            candidate
            for candidate in ast.walk(parsed)
            if isinstance(candidate, (ast.FunctionDef, ast.AsyncFunctionDef))
            and candidate.name == wanted.name
            and candidate.lineno == wanted.lineno
            and candidate.col_offset == wanted.col_offset
        ),
        None,
    )
    if node is None:
        return None
    node = copy.deepcopy(node)
    node.decorator_list = []
    node._sugar_source = index.source  # type: ignore[attr-defined]
    node._sugar_file = index.sourcefile  # type: ignore[attr-defined]
    node._sugar_bridge_name = wanted.bridge_name  # type: ignore[attr-defined]
    return node


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


def resolved_star_import_names(module_name: str) -> tuple[str, ...] | None:
    """Return the closed, lift-decidable names bound by one star import.

    Source modules qualify only when a literal ``__all__`` is present. A
    computed manifest or an implicit source-module namespace depends on
    executing arbitrary module code, so it remains a construction panic.
    Native extensions and builtins have an exact resolved module namespace;
    Python's star-import rule selects ``__all__`` or its public names.
    """
    exports = _static_module_exports(module_name)
    if exports is not None:
        return tuple(sorted(exports))

    native_origin = _installed_native_extension(module_name)
    if native_origin is None:
        try:
            spec = importlib.util.find_spec(module_name)
        except (ImportError, ModuleNotFoundError, ValueError):
            spec = None
        if spec is None or spec.loader is not importlib.machinery.BuiltinImporter:
            return None
    try:
        module = importlib.import_module(module_name)
    except (ImportError, ModuleNotFoundError):
        return None
    manifest = getattr(module, "__all__", None)
    if manifest is not None:
        if not isinstance(manifest, (list, tuple)) or not all(
            isinstance(name, str) for name in manifest
        ):
            return None
        names = tuple(manifest)
    else:
        names = tuple(name for name in vars(module) if not name.startswith("_"))
    return tuple(sorted(set(names)))


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
    if len(definitions) != 1:
        return None
    return _contextmanager_exit_contract_from_definition(definitions[0], parsed)


def contextmanager_exit_contract_for_fragment(fn_site):
    """Recognize the same closed contextmanager subset in a local fragment."""
    if fn_site is None or fn_site.observed != "FunctionDef":
        return None
    source = getattr(fn_site, "source", None)
    filename = getattr(fn_site, "filename", "<contextmanager>")
    if source is None:
        return None
    try:
        parsed = parsed_tree(source, filename)
    except SyntaxError:
        return None
    definition = getattr(fn_site, "node", None)
    if not isinstance(definition, ast.FunctionDef):
        return None
    return _contextmanager_exit_contract_from_definition(definition, parsed)


def _contextmanager_exit_contract_from_definition(definition, parsed):
    if not _is_contextmanager_definition(definition, parsed):
        return None
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


def resolve_source_exit_contract(
    import_target: str, *, _stack: frozenset[str] = frozenset()
):
    """Dig a source-backed exit suppression contract for one qualified target.

    Proven subset beyond the static coordinate table and ``@contextmanager``
    generator shapes:

    - A class whose exact ``__exit__`` body cannot return a truthy value proves
      non-suppression (implicit ``None``, bare ``return``, ``return False`` /
      ``return None`` only).
    - A function whose only value-bearing ``return`` is a call to a target that
      itself has a proven contract inherits that contract.
    - A function whose return annotation names only local classes whose
      ``__exit__`` methods prove the same disposition inherits that disposition.

    Every other shape remains ``None`` so WithSugar stays loud. Never invent
    non-suppression from missing evidence.
    """
    if not import_target or "." not in import_target or import_target in _stack:
        return None
    contract = resolve_contextmanager_exit_contract(import_target)
    if contract is not None:
        return contract
    contract = resolve_class_exit_contract(import_target)
    if contract is not None:
        return contract
    return resolve_function_return_exit_contract(
        import_target, _stack=_stack | {import_target}
    )


def resolve_local_source_exit_contract(filename: str | None, local_name: str):
    """Resolve an exact module import used by a source-digged callsite.

    Only an unconditional top-level import in the authenticated installed
    source file qualifies a bare call coordinate. Shadowed or local-only names
    return no contract and therefore remain loud.
    """
    if not filename or not local_name or "." in local_name:
        return None
    from pathlib import Path

    from sugar_lift_py_tests.lift_rpc import _installed_module_name_from_filename

    module_name = _installed_module_name_from_filename(str(Path(filename).resolve()))
    if module_name is None:
        return None
    installed = _installed_source(module_name)
    if installed is None:
        return None
    source, sourcefile = installed
    try:
        parsed = parsed_tree(source, sourcefile)
    except SyntaxError:
        return None
    target = _definite_unconditional_reexport_target(module_name, local_name, parsed)
    if target is None:
        return None
    return resolve_source_exit_contract(target)


def resolve_class_exit_contract(qualified_class: str):
    """Prove exit disposition from an installed class's exact ``__exit__`` body."""
    exit_fn = resolve_install_source_class_method(qualified_class, "__exit__")
    if exit_fn is None or not isinstance(exit_fn.node, ast.FunctionDef):
        return None
    return _exit_method_suppression_contract(exit_fn.node)


def resolve_function_return_exit_contract(
    import_target: str, *, _stack: frozenset[str] = frozenset()
):
    """Inherit a proven exit contract from a function's source returns/annotation."""
    fn = resolve_install_source_funcdef(import_target)
    if fn is None or not isinstance(fn.node, ast.FunctionDef):
        return None
    definition = fn.node
    module_name = (
        getattr(definition, "_sugar_defining_module", None)
        or import_target.rsplit(".", 1)[0]
    )
    return_contracts = []
    returns_unproved = False
    for node in _direct_method_returns(definition):
        if node.value is None:
            continue
        if not isinstance(node.value, ast.Call):
            returns_unproved = True
            break
        target = _qualified_call_func_name(node.value.func, module_name, definition)
        if target is None:
            returns_unproved = True
            break
        contract = resolve_source_exit_contract(target, _stack=_stack)
        if contract is None:
            returns_unproved = True
            break
        return_contracts.append(contract)
    if return_contracts and not returns_unproved:
        head = return_contracts[0]
        if all(contract == head for contract in return_contracts):
            return head
    # Call-return proof failed or was empty: annotation may still name the
    # constructed manager class whose digged ``__exit__`` is decidable.
    return _annotation_class_exit_contract(definition, module_name, _stack=_stack)


def _exit_method_suppression_contract(definition: ast.FunctionDef):
    """Prove non-suppression when ``__exit__`` cannot return a truthy value.

    A truthy ``return`` (including ``return True`` and every non-constant
    expression) stays unproved: suppression would require reducing the exact
    method body, not this static disposition contract. Nested function/class
    bodies are ignored — only the method's own control flow decides exit.
    """
    from sugar_lift_py_tests.floor.call_site_value import ExitSuppressionContract

    for node in _direct_method_returns(definition):
        if node.value is None:
            continue
        if isinstance(node.value, ast.Constant) and node.value.value in (False, None):
            continue
        if isinstance(node.value, ast.Name) and node.value.id in {"False", "None"}:
            continue
        return None
    return ExitSuppressionContract.never_suppresses()


def _direct_method_returns(definition: ast.FunctionDef):
    """Yield ``return`` nodes owned by ``definition``, not nested defs/classes."""

    def walk(node: ast.AST):
        if isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
        ):
            return
        if isinstance(node, ast.Return):
            yield node
            return
        for child in ast.iter_child_nodes(node):
            if isinstance(
                child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
            ):
                continue
            yield from walk(child)

    for statement in definition.body:
        yield from walk(statement)


def _annotation_class_exit_contract(
    definition: ast.FunctionDef,
    module_name: str,
    *,
    _stack: frozenset[str],
):
    if definition.returns is None:
        return None
    names = _annotation_class_names(definition.returns)
    if not names:
        return None
    contracts = []
    for name in names:
        if name in {"Any", "None", "NoneType"}:
            continue
        contract = resolve_class_exit_contract(f"{module_name}.{name}")
        if contract is None:
            return None
        contracts.append(contract)
    if not contracts:
        return None
    head = contracts[0]
    if all(contract == head for contract in contracts):
        return head
    return None


def _annotation_class_names(node: ast.expr) -> tuple[str, ...] | None:
    if isinstance(node, ast.Name):
        return (node.id,)
    if isinstance(node, ast.Attribute):
        dotted = _dotted_ast_name(node)
        return (dotted,) if dotted is not None else None
    if isinstance(node, ast.Constant) and node.value is None:
        return ("None",)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        left = _annotation_class_names(node.left)
        right = _annotation_class_names(node.right)
        if left is None or right is None:
            return None
        return (*left, *right)
    if isinstance(node, ast.Subscript):
        return _annotation_class_names(node.value)
    return None


def _qualified_call_func_name(
    func: ast.expr, module_name: str, definition: ast.FunctionDef
) -> str | None:
    """Resolve a returned call's callee to a module-qualified source target."""
    del definition
    if isinstance(func, ast.Name):
        return f"{module_name}.{func.id}"
    if isinstance(func, ast.Attribute):
        dotted = _dotted_ast_name(func)
        if dotted is None:
            return None
        # ``mod.attr`` where ``mod`` is this defining package alias stays as-is
        # when already dotted; bare ``pkg.fn`` is already qualified enough for
        # install-source resolution.
        if "." in dotted:
            return dotted
        return f"{module_name}.{dotted}"
    return None


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


def _module_import_bindings(
    statement: ast.stmt, *, defining_module: str | None = None
) -> dict[str, tuple[str, str | None]]:
    bindings: dict[str, tuple[str, str | None]] = {}
    if isinstance(statement, ast.Import):
        for alias in statement.names:
            bound = alias.asname or alias.name.split(".", 1)[0]
            module_name = alias.name if alias.asname else alias.name.split(".", 1)[0]
            bindings[bound] = (module_name, None)
    elif isinstance(statement, ast.ImportFrom):
        module_name = statement.module or ""
        if statement.level and defining_module is not None:
            module_name = (
                _absolute_import_from_module(
                    defining_module,
                    module_name or None,
                    statement.level,
                )
                or module_name
            )
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
    defining_module: str | None = None,
):
    """Construct a target node's lexical module bindings, need-first.

    The imported value belongs to its defining module, not to the consumer's
    temporal. Reverse selection finds only prerequisite declarations; forward
    construction then sends each selected declaration through the **sole**
    install-source value constructor (``resolve_install_source_value``) when a
    defining module is known — same SourceOracle pin, same construction identity.
    Same-module assigns/functions are never re-factoryed outside that door.
    """
    from sugar_lift_py_tests.engine_log import reduction_span

    with reduction_span(
        sugar="module_seed",
        role="dig.module_seed",
        site=f"{sourcefile}:{target_index}",
    ):
        return _ctx_with_required_module_bindings_impl(
            statements,
            target_index,
            needed,
            source=source,
            sourcefile=sourcefile,
            ctx=ctx,
            resolving=resolving,
            defining_module=defining_module,
        )


def _ctx_with_required_module_bindings_impl(
    statements: list[ast.stmt],
    target_index: int,
    needed: set[str],
    *,
    source: str,
    sourcefile: str,
    ctx: Any,
    resolving: frozenset[str],
    defining_module: str | None = None,
):
    from dataclasses import replace

    from sugar_lift_py_tests.claim import SugarRole
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment
    from sugar_lift_py_tests.floor import (
        BlockValue,
        ImportAliasValue,
    )
    from sugar_lift_py_tests.floor.local_exception_class_value import (
        module_class_value,
    )
    from sugar_lift_py_tests.outcome import Incomplete, complete_value

    from sugar_lift_py_tests.temporal import TemporalContext

    # Imported values are constructed in the defining module's lexical frame.
    # Consumer locals are not module globals and must never satisfy these Names.
    needed = set(needed)

    selected: list[ast.stmt] = []
    for statement in reversed(statements[:target_index]):
        declaration = _module_declaration_name(statement)
        imports = _module_import_bindings(statement, defining_module=defining_module)
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
                # Body is deferred on the callable. Only eager construct faces
                # (decorators/defaults) expand the seed; body free names are
                # seeded when that function is itself constructed or dug —
                # never re-pulled into every sibling seed.
                needed.update(_function_definition_dependencies(statement))
    selected.reverse()

    lexical = TemporalContext.empty()
    module_ctx = replace(ctx, temporal=lexical, module_temporal=lexical)
    for statement in selected:
        imports = _module_import_bindings(statement, defining_module=defining_module)
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
                        install_source_checked=imported_name is not None,
                    ),
                )
            module_ctx = replace(
                module_ctx, temporal=temporal, module_temporal=temporal
            )
            continue

        if isinstance(statement, ast.ClassDef):
            temporal = module_ctx.temporal.bind_value(
                statement.name,
                module_class_value(
                    name=statement.name,
                    base_names=tuple(
                        base.id
                        for base in statement.bases
                        if isinstance(base, ast.Name)
                    ),
                    temporal=module_ctx.temporal,
                    record=BlockValue(()),
                ),
            )
            module_ctx = replace(
                module_ctx, temporal=temporal, module_temporal=temporal
            )
            continue

        declaration = _module_declaration_name(statement)
        # Sole constructor for same-module named values: wrap SourceOracle
        # identity (defining_module.attr), do not re-factory outside the door.
        if (
            defining_module
            and declaration
            and isinstance(
                statement,
                (ast.Assign, ast.AnnAssign, ast.FunctionDef, ast.AsyncFunctionDef),
            )
        ):
            qualified = f"{defining_module}.{declaration}"
            constructed = resolve_install_source_value(
                qualified, module_ctx, _resolving=resolving
            )
            if constructed is None:
                # Same opacity as Incomplete local construct: seed cannot force.
                return None
            temporal = module_ctx.temporal.bind_value(declaration, constructed)
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
    """Public door: the sole constructor for install-source named floor values.

    A source-backed import is statically knowable. Find the defining statement,
    construct the module globals its RHS needs, and send all values through the
    ordinary factory. Any missing Sugar or floor arm propagates its FactoryPanic;
    this function never converts a dig gap into a runtime effect.

    Construction is correctness: SourceOracle is the only source constructor;
    :class:`InstallSourceValueOracle` is the only floor constructor for cited
    install-source names. Callers must not factory-build ``module.attr`` outside
    this door.
    """
    return INSTALL_SOURCE_VALUE_ORACLE.resolve(
        import_target, ctx, _resolving=_resolving
    )


def _construct_install_source_value(
    import_target: str, ctx, *, _resolving: frozenset[str] = frozenset()
):
    """Internal construct body — only :meth:`InstallSourceValueOracle.resolve` calls this.

    L4 spans (``dig.construct.*``) bisect first-time construct mass by shape and
    by function sub-step (deepcopy / seed / factory), not by guessing.
    """
    from sugar_lift_py_tests.engine_log import reduction_span

    resolving = _resolving | {import_target}
    native = _resolve_qualified_native_callable(import_target, resolving=_resolving)
    if native is not None:
        with reduction_span(
            sugar=import_target, role="dig.construct.native", site=import_target
        ):
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

    reexport = _definite_unconditional_reexport_target(module_name, attr, parsed)
    if reexport is None:
        reexport = _definite_star_reexport_target(module_name, attr, parsed)
    if reexport is None:
        reexport = _definite_setup_reexport_target(module_name, attr, parsed)
    if reexport is not None and reexport not in resolving:
        resolved = resolve_install_source_value(
            reexport,
            ctx,
            _resolving=resolving,
        )
        if resolved is not None:
            from sugar_lift_py_tests.floor import ImportAliasValue

            if (
                isinstance(resolved, ImportAliasValue)
                and resolved.resolved_value is None
            ):
                coordinate = _concrete_import_constant_coordinate(reexport)
                if coordinate is not None:
                    return coordinate
            return resolved
        from sugar_lift_py_tests.floor import ImportAliasValue

        coordinate = _concrete_import_constant_coordinate(reexport)
        if coordinate is not None:
            return coordinate
        return ImportAliasValue(
            attr,
            attr,
            import_target=reexport,
            install_source_checked=True,
        )

    if _installed_class_is_exception(
        module_name,
        attr,
        parsed,
        resolving=frozenset(),
    ):
        from sugar_lift_py_tests.floor import ExceptionClassValue

        with reduction_span(
            sugar=import_target, role="dig.construct.exception", site=import_target
        ):
            return ExceptionClassValue(import_target)

    function = _resolve_qualified_function_fragment(import_target, resolving=_resolving)
    if function is not None:
        with reduction_span(
            sugar=import_target, role="dig.construct.function", site=import_target
        ):
            defining_source = function.node._sugar_source  # type: ignore[attr-defined]
            defining_file = function.node._sugar_file  # type: ignore[attr-defined]
            # SourceOracle / parsed_tree owns the immutable module tree. Never
            # deepcopy the whole module per function (L4: ~majority of first-time
            # dig construct wall). Copy only the FunctionDef we will tag.
            defining_tree = parsed_tree(defining_source, defining_file)
            target_index = next(
                index
                for index, statement in enumerate(defining_tree.body)
                if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
                and statement.lineno == function.node.lineno
                and statement.name == function.function_name()
            )
            with reduction_span(
                sugar=import_target,
                role="dig.construct.function.deepcopy",
                site=import_target,
            ):
                definition = copy.deepcopy(defining_tree.body[target_index])
            definition._sugar_source = defining_source  # type: ignore[attr-defined]
            definition._sugar_file = defining_file  # type: ignore[attr-defined]
            definition._sugar_bridge_name = (
                function.node._sugar_bridge_name
            )  # type: ignore[attr-defined]
            function = SourceFragment.from_node(
                definition, defining_file, source=defining_source
            )
            with reduction_span(
                sugar=import_target,
                role="dig.construct.function.seed",
                site=import_target,
            ):
                module_ctx = _ctx_with_required_module_bindings(
                    defining_tree.body,
                    target_index,
                    # Eager construct faces (decorators/defaults). Body free
                    # names are seeded when dig opens the body.
                    _function_definition_dependencies(definition),
                    source=defining_source,
                    sourcefile=defining_file,
                    ctx=ctx,
                    resolving=resolving,
                    defining_module=module_name,
                )
            if module_ctx is None:
                return None
            # Resolving an imported function constructs its definition-time
            # faces now (decorators/defaults), but Python does not execute its
            # body until a call. Carry body fragments into SequentialDigBody
            # and let the ordinary factory construct each statement on demand.
            module_ctx = replace(
                module_ctx,
                defer_function_body_construction=True,
            )
            with reduction_span(
                sugar=import_target,
                role="dig.construct.function.factory",
                site=import_target,
            ):
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
            with reduction_span(
                sugar=import_target, role="dig.construct.assign", site=import_target
            ):
                module_ctx = _ctx_with_required_module_bindings(
                    parsed.body,
                    target_index,
                    _loaded_names(value_node),
                    source=source,
                    sourcefile=sourcefile,
                    ctx=ctx,
                    resolving=resolving,
                    defining_module=module_name,
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

    # A module value selected by ``try`` / ``except`` is still source-owned.
    # Let TrySugar reduce every path and admit the binding only when its
    # continuing-path join constructs one exact value. Import availability is
    # represented by the existing cited ``py.except`` guard; a ground import
    # coordinate never mints RuntimeEffect authority.
    for target_index, statement in enumerate(parsed.body):
        if not isinstance(statement, ast.Try) or not any(
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Store)
            and node.id == attr
            for node in ast.walk(statement)
        ):
            continue
        with reduction_span(
            sugar=import_target,
            role="dig.construct.try",
            site=import_target,
        ):
            module_ctx = _ctx_with_required_module_bindings(
                parsed.body,
                target_index,
                _loaded_names(statement),
                source=source,
                sourcefile=sourcefile,
                ctx=ctx,
                resolving=resolving,
                defining_module=module_name,
            )
            if module_ctx is None:
                return None
            body = module_ctx.build_body(
                SourceFragment.from_node(statement, sourcefile, source=source),
                SugarRole.STATEMENT,
            )
            outcome = body.reduce(module_ctx)
            if isinstance(outcome, Incomplete):
                return None
            extended = outcome.extend_scope(module_ctx)
            resolved = extended.temporal.value_if_bound(attr)
            if resolved is not None:
                return resolved

    return None


def _concrete_import_constant_coordinate(import_target: str):
    """Authenticate a definite reexported constant without reading its value."""
    import inspect
    from types import ModuleType

    from sugar_lift_py_tests.floor.import_alias_value import (
        _resolve_qualified_import_object,
    )

    value = _resolve_qualified_import_object(import_target)
    if value is None or isinstance(value, ModuleType) or inspect.isclass(value):
        return None
    if callable(value):
        return None

    from sugar_lift_py_tests.floor import SymbolicValue
    from sugar_lift_py_tests.ir import ctor, str_const

    return SymbolicValue(
        ctor(
            "python:import_alias",
            [str_const(import_target.rsplit(".", 1)[-1]), str_const(import_target)],
        )
    )


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


def _definite_unconditional_reexport_target(
    module_name: str, attr: str, parsed: ast.Module
) -> str | None:
    """Return the sole unshadowed top-level ``from`` binding for ``attr``.

    A plain module-level import is executed unconditionally and its source
    coordinate is therefore decidable.  Multiple bindings or any later
    declaration of the same name are not a unique construction and stay
    unresolved.  Conditional imports are deliberately excluded because they
    are not direct children of the module.
    """

    targets: list[tuple[int, str]] = []
    for index, statement in enumerate(parsed.body):
        if not isinstance(statement, ast.ImportFrom):
            continue
        target_module = _absolute_import_from_module(
            module_name, statement.module, statement.level
        )
        if target_module is None:
            continue
        for alias in statement.names:
            if alias.name != "*" and (alias.asname or alias.name) == attr:
                targets.append((index, f"{target_module}.{alias.name}"))
    if len(targets) != 1:
        return None
    import_index, target = targets[0]
    if any(
        (
            _module_declaration_name(statement) == attr
            or attr in _module_import_bindings(statement)
        )
        for statement in parsed.body[import_index + 1 :]
    ):
        return None
    return target


def _definite_star_reexport_target(
    module_name: str, attr: str, parsed: ast.Module
) -> str | None:
    """Return one top-level star source that explicitly exports ``attr``.

    Star imports are only construction-closed when the cited source module
    names the member in a literal ``__all__``.  Merely finding a declaration is
    insufficient because a module may deliberately hide it.  Multiple matching
    stars are ambiguous and stay unresolved.
    """

    targets: list[tuple[int, str]] = []
    for index, statement in enumerate(parsed.body):
        if not isinstance(statement, ast.ImportFrom) or not any(
            alias.name == "*" for alias in statement.names
        ):
            continue
        target_module = _absolute_import_from_module(
            module_name, statement.module, statement.level
        )
        if target_module is None:
            continue
        installed = _installed_source(target_module)
        if installed is None:
            continue
        source, sourcefile = installed
        try:
            target_tree = parsed_tree(source, sourcefile)
        except SyntaxError:
            continue
        exported: set[str] = set()
        for candidate in target_tree.body:
            if (
                isinstance(candidate, (ast.Assign, ast.AnnAssign))
                and any(
                    isinstance(target, ast.Name) and target.id == "__all__"
                    for target in (
                        candidate.targets
                        if isinstance(candidate, ast.Assign)
                        else [candidate.target]
                    )
                )
                and isinstance(candidate.value, (ast.List, ast.Tuple))
                and all(
                    isinstance(element, ast.Constant) and isinstance(element.value, str)
                    for element in candidate.value.elts
                )
            ):
                exported.update(element.value for element in candidate.value.elts)
        if attr in exported:
            targets.append((index, f"{target_module}.{attr}"))
    if len(targets) != 1:
        return None
    import_index, target = targets[0]
    if any(
        (
            _module_declaration_name(statement) == attr
            or attr in _module_import_bindings(statement)
        )
        for statement in parsed.body[import_index + 1 :]
    ):
        return None
    return target


def _definite_setup_reexport_target(
    module_name: str, attr: str, parsed: ast.Module
) -> str | None:
    """Resolve an import in a setup sentinel's provably selected false branch.

    Installed packages commonly guard their public re-exports with the exact
    fresh-module pattern ``try: __SETUP__; except NameError: __SETUP__ = False``
    followed by ``if __SETUP__: ... else: from ... import name``.  On a fresh
    import that private sentinel is unbound, so the false branch is selected.
    Other conditionals, non-NameError handlers, truthy defaults, nested imports,
    and ambiguous bindings remain unresolved and loud.
    """

    false_sentinels: set[str] = set()
    for statement_index, statement in enumerate(parsed.body):
        if (
            not isinstance(statement, ast.Try)
            or len(statement.body) != 1
            or statement.orelse
            or statement.finalbody
            or not isinstance(statement.body[0], ast.Expr)
            or not isinstance(statement.body[0].value, ast.Name)
        ):
            continue
        sentinel = statement.body[0].value.id
        if not (sentinel.startswith("__") and sentinel.endswith("__")):
            continue
        if any(
            _module_declaration_name(previous) == sentinel
            or sentinel in _module_import_bindings(previous)
            for previous in parsed.body[:statement_index]
        ):
            continue
        for handler in statement.handlers:
            if (
                isinstance(handler.type, ast.Name)
                and handler.type.id == "NameError"
                and len(handler.body) == 1
                and isinstance(handler.body[0], ast.Assign)
                and len(handler.body[0].targets) == 1
                and isinstance(handler.body[0].targets[0], ast.Name)
                and handler.body[0].targets[0].id == sentinel
                and isinstance(handler.body[0].value, ast.Constant)
                and handler.body[0].value.value is False
            ):
                false_sentinels.add(sentinel)

    targets: list[str] = []
    for statement in parsed.body:
        if (
            not isinstance(statement, ast.If)
            or not isinstance(statement.test, ast.Name)
            or statement.test.id not in false_sentinels
        ):
            continue
        for selected in statement.orelse:
            if not isinstance(selected, ast.ImportFrom):
                continue
            target_module = _absolute_import_from_module(
                module_name, selected.module, selected.level
            )
            if target_module is None:
                continue
            for alias in selected.names:
                if (alias.asname or alias.name) == attr and alias.name != "*":
                    targets.append(f"{target_module}.{alias.name}")
    return targets[0] if len(targets) == 1 else None


def _dotted_ast_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        receiver = _dotted_ast_name(node.value)
        if receiver is not None:
            return f"{receiver}.{node.attr}"
    return None


def _class_base_ast_name(node: ast.expr) -> str | None:
    """Static class-base coordinate, ignoring a type-parameter subscription."""
    if isinstance(node, ast.Subscript):
        node = node.value
    return _dotted_ast_name(node)


def _facade_class_source(module_name: str, class_name: str) -> tuple[str, str] | None:
    """Resolve the defining source behind a public re-exporting module."""
    try:
        module = importlib.import_module(module_name)
    except ImportError:
        return None
    cls = getattr(module, class_name, None)
    try:
        sourcefile = inspect.getsourcefile(cls) if inspect.isclass(cls) else None
    except (TypeError, OSError):
        return None
    if not isinstance(sourcefile, str):
        return None
    try:
        return Path(sourcefile).read_text(encoding="utf-8"), sourcefile
    except (OSError, UnicodeError):
        return None


@functools.lru_cache(maxsize=INSTALL_SOURCE_VALUE_CAPACITY)
def resolve_install_source_class_bases(
    qualified_class: str,
) -> tuple[str, ...] | None:
    """Resolve one installed class's direct source bases.

    ``None`` is deliberately loud at the constructor consumer: it means source
    did not prove every base coordinate. This door never guesses from an
    instance and never turns an unbuilt source shape into runtime dependence.
    """
    return _resolve_install_source_class_bases(qualified_class, frozenset())


def _resolve_install_source_class_bases(
    qualified_class: str, resolving: frozenset[str]
) -> tuple[str, ...] | None:
    if (
        not qualified_class
        or "." not in qualified_class
        or qualified_class in resolving
    ):
        return None
    resolving = resolving | {qualified_class}
    module_name, class_name = qualified_class.rsplit(".", 1)
    installed = _installed_source(module_name)
    if installed is None:
        # ``collections.abc`` is a public facade whose source file is
        # ``_collections_abc.py``. Resolve that source file from the class
        # coordinate; do not consult its runtime MRO.
        installed = _facade_class_source(module_name, class_name)
        if installed is None:
            return None
    source, sourcefile = installed
    try:
        parsed = parsed_tree(source, sourcefile)
    except SyntaxError:
        return None
    class_node = next(
        (
            statement
            for statement in parsed.body
            if isinstance(statement, ast.ClassDef) and statement.name == class_name
        ),
        None,
    )
    if class_node is None:
        reexport = (
            _definite_unconditional_reexport_target(module_name, class_name, parsed)
            or _definite_star_reexport_target(module_name, class_name, parsed)
            or _definite_setup_reexport_target(module_name, class_name, parsed)
        )
        if reexport is not None:
            return _resolve_install_source_class_bases(reexport, resolving)
        # Resolve public source facades without consulting runtime ``__mro__``.
        # Python 3.11's ``collections.abc`` is literally a star re-export of
        # ``_collections_abc``; later releases point inspection at the defining
        # file directly. Both spellings denote the same source-proven classes.
        for statement in parsed.body:
            if not isinstance(statement, ast.ImportFrom) or not any(
                alias.name == "*" for alias in statement.names
            ):
                continue
            target_module = _absolute_import_from_module(
                module_name, statement.module, statement.level
            )
            if target_module is None:
                continue
            bases = _resolve_install_source_class_bases(
                f"{target_module}.{class_name}", resolving
            )
            if bases is None:
                continue
            target_prefix = f"{target_module}."
            return tuple(
                (
                    f"{module_name}.{base.removeprefix(target_prefix)}"
                    if base.startswith(target_prefix)
                    else base
                )
                for base in bases
            )
        # Some Python releases ship ``collections.abc`` as a thin
        # ``from _collections_abc import *`` facade. The module source exists,
        # but the requested class is defined in the re-exported class's source.
        defining = _facade_class_source(module_name, class_name)
        if defining is None or defining == installed:
            return None
        source, sourcefile = defining
        try:
            parsed = parsed_tree(source, sourcefile)
        except SyntaxError:
            return None
        class_node = next(
            (
                statement
                for statement in parsed.body
                if isinstance(statement, ast.ClassDef) and statement.name == class_name
            ),
            None,
        )
        if class_node is None:
            return None
    if not class_node.bases:
        return () if qualified_class == "builtins.object" else ("builtins.object",)

    imports = _static_import_targets(module_name, parsed)
    local_classes = {
        statement.name
        for statement in parsed.body
        if isinstance(statement, ast.ClassDef)
    }
    resolved: list[str] = []
    for base in class_node.bases:
        coordinate = _class_base_ast_name(base)
        if coordinate is None:
            return None
        head, separator, rest = coordinate.partition(".")
        imported = imports.get(head)
        if imported is not None:
            resolved.append(f"{imported}.{rest}" if separator else imported)
        elif not separator and coordinate in local_classes:
            resolved.append(f"{module_name}.{coordinate}")
        elif not separator and coordinate == "object":
            resolved.append("builtins.object")
        else:
            return None
    return tuple(resolved)


def resolve_install_source_class_method(qualified_class: str, method_name: str):
    """Resolve ``module.Class.method`` to a FunctionDef SourceFragment, or None."""
    if not qualified_class or not method_name or "." not in qualified_class:
        return None
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment

    module_name, class_name = qualified_class.rsplit(".", 1)
    node = _module_sibling_function_node(
        module_name,
        f"{module_name}.{class_name}.{method_name}",
        f"{class_name}.{method_name}",
    )
    if node is not None:
        node._sugar_defining_module = module_name  # type: ignore[attr-defined]
        return SourceFragment.from_node(
            node, getattr(node, "_sugar_file", f"<{module_name}>")
        )

    try:
        module = importlib.import_module(module_name)
    except ImportError:
        return None
    cls = getattr(module, class_name, None)
    if cls is None or not inspect.isclass(cls):
        return None
    obj = cls.__dict__.get(method_name)
    if obj is None:
        obj = getattr(cls, method_name, None)
    if obj is None or not callable(obj):
        return None
    # Open domain: builtins / descriptors / extension methods have no source.
    # Pre-check so TypeError from getsource is not soft-swallowed (#4203).
    if inspect.isbuiltin(obj) or inspect.ismethoddescriptor(obj):
        return None
    target = inspect.unwrap(obj) if callable(obj) else obj
    code = getattr(target, "__code__", None)
    if code is None:
        code = getattr(getattr(target, "__func__", None), "__code__", None)
    if code is None:
        return None
    defining_module = getattr(obj, "__module__", None) or module_name
    try:
        source = textwrap.dedent(inspect.getsource(obj))
        sourcefile = inspect.getsourcefile(obj) or f"<{module_name}>"
    except (OSError, TypeError):
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
            child.node._sugar_defining_module = defining_module  # type: ignore[attr-defined]
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
            n = _module_sibling_function_node(mod, qualified, attr)
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
    if obs in ("Name", "Constant", "JoinedStr"):
        return True
    if obs == "Attribute":
        recv = rv.attr_receiver()
        return recv is not None and recv.observed == "Name"
    if obs == "BinOp":
        # Recurse both sides so value + self.sep + call is fine.
        # #4203: BinOp arms are total once observed==BinOp; soft Exception
        # continue was a fail-open attachability lie.
        left = rv.binop_left()
        right = rv.binop_right()
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
    # Issued only when source recognition proves the closed @contextmanager
    # generator subset. Generic generators cannot project a yielded operand as
    # an ordinary call result.
    contextmanager_yield: bool = False

    def desugar(self, ctx: Any = None):
        from sugar_lift_py_tests.floor.exceptional_exit_value import (
            ExceptionalExitValue,
        )
        from sugar_lift_py_tests.floor.block_value import BlockValue
        from sugar_lift_py_tests.floor.guarded_raise import GuardedRaise
        from sugar_lift_py_tests.floor.guarded_return import GuardedReturn
        from sugar_lift_py_tests.floor.guarded_faces import GuardedFaces
        from sugar_lift_py_tests.floor.guarded_value import GuardedValue
        from sugar_lift_py_tests.floor.import_alias_value import ImportAliasValue
        from sugar_lift_py_tests.floor.inv_value import InvValue
        from sugar_lift_py_tests.floor.return_value import ReturnValue
        from sugar_lift_py_tests.floor.raise_value import RaiseValue
        from sugar_lift_py_tests.floor.scope_rebind import (
            GuardedScopeRebind,
            ScopeRebind,
        )
        from sugar_lift_py_tests.ir import and_, not_
        from sugar_lift_py_tests.outcome import Complete
        from sugar_lift_py_tests.recognition.guarded_exit import (
            GuardedExitRecognition,
        )
        from sugar_lift_py_tests.sugar_body import GuardedRawSugarBody

        cur = ctx
        guarded_exits = []
        for stmt in self.statements:
            outcome = stmt.reduce(cur)
            from sugar_lift_py_tests.outcome import Incomplete as _Inc

            if isinstance(outcome, _Inc):
                return outcome
            cur = outcome.extend_scope(cur)
            contribution = tuple(outcome.contribution())
            if self.contextmanager_yield:
                yielded = self._contextmanager_yield_value(contribution)
                if yielded is not None:
                    return Complete(yielded)
            guarded = tuple(
                item
                for item in contribution
                if isinstance(item, (GuardedReturn, GuardedRaise))
            )
            non_returns = tuple(
                item
                for item in contribution
                if not isinstance(
                    item, (GuardedReturn, GuardedRaise, ReturnValue, RaiseValue)
                )
            )
            faces = getattr(outcome, "value", None)
            guarded_faces = isinstance(faces, GuardedFaces)
            support_types = (ImportAliasValue, InvValue)
            # A joined branch composite has already constructed its exact
            # post-branch values in ``joined_bindings``. Imports and assertions
            # are reduced support testimony, not another competing result.
            joined_faces = (
                guarded_faces
                and non_returns
                and all(
                    type(item)
                    in (
                        GuardedScopeRebind,
                        ScopeRebind,
                        *support_types,
                    )
                    for item in non_returns
                )
                and any(type(item) is ScopeRebind for item in non_returns)
            )
            support_only_faces = (
                guarded_faces
                and non_returns
                and all(type(item) in support_types for item in non_returns)
            )
            # GuardedFaces is the reduced semantic authority for which branch
            # exits. State guarded by that exact terminal face is local
            # implementation testimony, not a competing function result.
            # State on a continuing face remains loud.
            terminal_face_guards = (
                (
                    *((faces.guard,) if faces.then_exits else ()),
                    *((not_(faces.guard),) if faces.else_exits else ()),
                )
                if guarded_faces
                else ()
            )
            terminal_face_state = (
                guarded_faces
                and non_returns
                and any(type(item) is GuardedScopeRebind for item in non_returns)
                and all(
                    type(item) in support_types
                    or (
                        type(item) is GuardedScopeRebind
                        and (
                            any(
                                terminal_guard in item.guards
                                for terminal_guard in terminal_face_guards
                            )
                            or GuardedExitRecognition.terminal_local_state(
                                item.guards,
                                guarded,
                            )
                        )
                    )
                    for item in non_returns
                )
            )
            terminal_raw_tail = (
                guarded_faces
                and non_returns
                and all(
                    isinstance(item, GuardedRawSugarBody)
                    and GuardedExitRecognition.terminal_local_state(
                        item.guards,
                        guarded,
                    )
                    for item in non_returns
                )
            )
            # BlockSugar has already reduced and threaded a continuing block's
            # exact scope testimony. Its guarded exits are result-bearing; its
            # rebind/support entries are not competing return values. A halted
            # block or any opaque residue remains loud.
            continuing_block_state = (
                isinstance(faces, BlockValue)
                and faces.can_fall_through
                and guarded
                and non_returns
                and all(
                    type(item)
                    in (
                        GuardedScopeRebind,
                        ScopeRebind,
                        *support_types,
                    )
                    for item in non_returns
                )
            )
            # TrySugar has already authenticated and guarded typed effects from
            # a runtime-dependent return arm. Route that existing red outcome;
            # replacing it with a SequentialDigBody construction panic loses
            # the more precise owner and aborts report painting too early.
            routed_guarded_effect = (
                guarded and len(non_returns) == 1 and isinstance(non_returns[0], _Inc)
            )
            if routed_guarded_effect:
                return non_returns[0]
            # Statements after a guarded exit execute only on its fall-through
            # path. Exact rebind-only BlockValues can therefore thread that
            # continuation scope before the final fallback is selected. A
            # rebind mixed into the *same* guarded-exit outcome remains loud.
            continuation_rebinds = (
                bool(guarded_exits)
                and not guarded
                and isinstance(getattr(outcome, "value", None), BlockValue)
                and non_returns
                and all(
                    type(item) in (GuardedScopeRebind, ScopeRebind)
                    for item in non_returns
                )
            )
            if (
                (guarded_exits or guarded)
                and non_returns
                and not (
                    joined_faces
                    or support_only_faces
                    or terminal_face_state
                    or terminal_raw_tail
                    or continuing_block_state
                    or continuation_rebinds
                )
            ):
                return self._control_flow_gap()
            for item in contribution:
                # Exact unguarded terminal only; guarded exits remain multi-exit.
                if type(item) in (ReturnValue, RaiseValue):
                    value = (
                        item.value
                        if type(item) is ReturnValue
                        else ExceptionalExitValue(item.effect)
                    )
                    for prior in reversed(guarded_exits):
                        guard = (
                            prior.guards[0]
                            if len(prior.guards) == 1
                            else and_(list(prior.guards))
                        )
                        selected = (
                            prior.value
                            if isinstance(prior, GuardedReturn)
                            else ExceptionalExitValue(prior.effect)
                        )
                        value = GuardedValue(guard, selected, value)
                    return Complete(value)
            guarded_exits.extend(guarded)
            follow = getattr(outcome, "follow", None)
            if callable(follow):
                step = follow()
                if not step.continues:
                    # Nested block already halted (e.g. BlockValue with return).
                    # Do not reduce later statements; no unguarded dig pin.
                    break
                if step.transform is not None and not guarded:
                    return self._control_flow_gap()
        # No unguarded ReturnValue: either multi-exit (GuardedReturn) or no
        # return at all. An exhaustive guarded partition still denotes one
        # exact return selection; incomplete or overlapping partitions stay
        # opaque so Derived residue cannot invent a fall-through literal.
        selected = self._exhaustive_guarded_selection(tuple(guarded_exits))
        if selected is not None:
            return Complete(selected)
        return self._control_flow_gap()

    @staticmethod
    def _contextmanager_yield_value(contribution):
        from sugar_lift_py_tests.effect import GeneratorYieldRuntimeEffect
        from sugar_lift_py_tests.floor import SymbolicValue
        from sugar_lift_py_tests.ir import _Ctor
        from sugar_lift_py_tests.outcome import Incomplete

        if len(contribution) != 1 or not isinstance(contribution[0], Incomplete):
            return None
        effect = contribution[0].effect
        if not isinstance(effect, GeneratorYieldRuntimeEffect):
            return None
        operation = effect.witness.operation
        if (
            type(operation) is not _Ctor
            or operation.name != "py.generator_yield"
            or len(operation.args) != 1
        ):
            return None
        return SymbolicValue(operation.args[0])

    @staticmethod
    def _exhaustive_guarded_selection(exits):
        from sugar_lift_py_tests.floor.exceptional_exit_value import (
            ExceptionalExitValue,
        )
        from sugar_lift_py_tests.floor.guarded_raise import GuardedRaise
        from sugar_lift_py_tests.floor.guarded_return import GuardedReturn
        from sugar_lift_py_tests.floor.guarded_value import GuardedValue
        from sugar_lift_py_tests.ir import not_

        rows = tuple(
            (
                tuple(exit_value.guards),
                (
                    exit_value.value
                    if isinstance(exit_value, GuardedReturn)
                    else ExceptionalExitValue(exit_value.effect)
                ),
            )
            for exit_value in exits
            if isinstance(exit_value, (GuardedReturn, GuardedRaise))
        )
        if len(rows) != len(exits) or not rows:
            return None

        def select(partition):
            terminal = tuple(value for guards, value in partition if not guards)
            if terminal:
                return terminal[0] if len(partition) == len(terminal) == 1 else None

            guard = partition[0][0][0]
            opposite = not_(guard)
            when_true = []
            when_false = []
            for guards, value in partition:
                if guard in guards:
                    remaining = list(guards)
                    remaining.remove(guard)
                    when_true.append((tuple(remaining), value))
                elif opposite in guards:
                    remaining = list(guards)
                    remaining.remove(opposite)
                    when_false.append((tuple(remaining), value))
                else:
                    return None
            if not when_true or not when_false:
                return None
            true_value = select(tuple(when_true))
            false_value = select(tuple(when_false))
            if true_value is None or false_value is None:
                return None
            return GuardedValue(guard, true_value, false_value)

        return select(rows)

    def _control_flow_gap(self):
        terminal = self.statements[-1] if self.statements else None
        audit_row = getattr(terminal, "audit_row", None)
        blame = getattr(audit_row, "blame", "<install-source-dig>")
        observed = getattr(audit_row, "observed", "SequentialDigBody")
        from sugar_lift_py_tests.factory.factory_gap import factory_panic_gap

        factory_panic_gap(
            owner="SequentialDigBody",
            blame=str(blame),
            observed=str(observed),
            requested="reduced guarded returns with an unguarded fallback",
            fix=(
                "construct the exact reduced return selection; unimplemented "
                "control-flow machinery must panic, never mint RuntimeEffect"
            ),
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
    callable_binding: Any = None
    callable_name_is_parameter: bool = False

    def _reduce_context(self, ctx: Any = None):
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
        callable_binding = self.callable_binding
        if callable_binding is not None and not self.callable_name_is_parameter:
            reduce_ctx = reduce_ctx.with_temporal(
                reduce_ctx.temporal.bind_value(
                    callable_binding.name,
                    callable_binding,
                    blame=f"<function:{callable_binding.name}>",
                )
            )
        return reduce_ctx

    def desugar(self, ctx: Any = None):
        reduce_ctx = self._reduce_context(ctx)
        return self.body.reduce(reduce_ctx)

    def scope_after(self, ctx: Any):
        """Thread a straight-line callback body and retain its exact rebinds."""
        from sugar_lift_py_tests.factory.factory_gap import factory_panic_gap
        from sugar_lift_py_tests.outcome import Incomplete

        sequential = getattr(self.body, "sugar", None)
        if not isinstance(sequential, SequentialDigBody):
            factory_panic_gap(
                owner="FunctionCallable",
                blame="<callback>",
                observed=type(sequential).__name__,
                requested="straight-line callback body",
                fix="construct SequentialDigBody callback scope or panic loudly",
            )
        cur = self._reduce_context(ctx)
        for statement in sequential.statements:
            outcome = statement.reduce(cur)
            if isinstance(outcome, Incomplete) or not outcome.follow().continues:
                factory_panic_gap(
                    owner="FunctionCallable",
                    blame=str(getattr(statement, "audit_row", "<callback>")),
                    observed=type(outcome).__name__,
                    requested="decidable callback scope update",
                    fix="construct the callback statement or panic loudly",
                )
            cur = outcome.extend_scope(cur)
        return cur

    def initializer_scope_after(self, ctx: Any):
        """Thread an initializer and retain exact assertion exit faces."""
        from sugar_lift_py_tests.factory.factory_gap import factory_panic_gap
        from sugar_lift_py_tests.floor import (
            ExceptionalExitValue,
            InvValue,
            RaiseValue,
        )
        from sugar_lift_py_tests.outcome import Incomplete

        sequential = getattr(self.body, "sugar", None)
        if not isinstance(sequential, SequentialDigBody):
            factory_panic_gap(
                owner="ConstructorCallSugar",
                blame="<initializer>",
                observed=type(sequential).__name__,
                requested="straight-line source initializer",
                fix="construct SequentialDigBody initializer scope or panic loudly",
            )
        cur = self._reduce_context(ctx)
        assertions = []
        for statement in sequential.statements:
            outcome = statement.reduce(cur)
            if isinstance(outcome, Incomplete):
                factory_panic_gap(
                    owner="ConstructorCallSugar",
                    blame=str(getattr(statement, "audit_row", "<initializer>")),
                    observed=type(outcome.effect).__name__,
                    requested="decidable source initializer statement",
                    fix="construct the initializer statement or panic loudly",
                )
            # SuperInitApply / SelfMethodApply project a reduced exceptional
            # exit as ExceptionalExitValue. That is already terminal control-
            # flow testimony — accept it before contribution routing, or the
            # default FloorValue continue face would silently skip the raise.
            if type(getattr(outcome, "value", None)) is ExceptionalExitValue:
                return cur, tuple(assertions), outcome.value
            contribution = tuple(outcome.contribution())
            raises = tuple(item for item in contribution if type(item) is RaiseValue)
            if raises:
                if len(contribution) != len(raises) or len(raises) != 1:
                    factory_panic_gap(
                        owner="ConstructorCallSugar",
                        blame=str(getattr(statement, "audit_row", "<initializer>")),
                        observed="mixed initializer exceptional exit",
                        requested="one exact initializer exit",
                        fix="construct the mixed initializer faces or panic loudly",
                    )
                return cur, tuple(assertions), ExceptionalExitValue(raises[0].effect)
            assertions.extend(item for item in contribution if type(item) is InvValue)
            if not outcome.follow().continues:
                factory_panic_gap(
                    owner="ConstructorCallSugar",
                    blame=str(getattr(statement, "audit_row", "<initializer>")),
                    observed=type(outcome.value).__name__,
                    requested="decidable initializer continuation",
                    fix="construct the initializer exit or panic loudly",
                )
            cur = outcome.extend_scope(cur)
        return cur, tuple(assertions), None


def _contextualized_dig_body(body, base_context):
    from sugar_lift_py_tests.claim import SugarRole
    from sugar_lift_py_tests.sugar_body import SugarBody

    return SugarBody(
        sugar=ContextualizedDigBody(body=body, base_context=base_context),
        role=SugarRole.TERM,
    )


def _ctx_with_method_module_bindings(fn_site, ctx: Any):
    """Construct globals loaded by an installed class method from its module.

    ``inspect.getsource`` gives ``resolve_install_source_class_method`` a
    dedented method fragment, which is enough to build the body but contains no
    preceding imports. Recover only the defining module declarations that the
    method actually loads and send them through the ordinary module
    prerequisite constructor. Runtime-selected prerequisites remain
    unresolved; a demanded missing name therefore still raises its normal
    ``TemporalContext`` panic.
    """
    module_name = getattr(fn_site.node, "_sugar_defining_module", None)
    if not isinstance(module_name, str) or not module_name:
        return ctx
    installed = _installed_source(module_name)
    if installed is None:
        return ctx
    source, sourcefile = installed
    try:
        parsed = parsed_tree(source, sourcefile)
    except SyntaxError:
        return ctx

    bridge = str(getattr(fn_site.node, "_sugar_bridge_name", "") or "")
    parts = bridge.split(".")
    if len(parts) < 3:
        return ctx
    class_name = parts[-2]
    target_index = next(
        (
            index
            for index, statement in enumerate(parsed.body)
            if isinstance(statement, ast.ClassDef) and statement.name == class_name
        ),
        None,
    )
    if target_index is None:
        method_name = fn_site.function_name()
        containing_classes = [
            index
            for index, statement in enumerate(parsed.body)
            if isinstance(statement, ast.ClassDef)
            and any(
                isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
                and member.name == method_name
                for member in statement.body
            )
        ]
        if len(containing_classes) == 1:
            # Re-exported or inherited methods may be requested through a
            # public class coordinate while their globals belong to the class
            # that actually defined the callable.
            target_index = containing_classes[0]
    if target_index is None:
        return ctx
    needed = _function_definition_dependencies(fn_site.node)
    for statement in fn_site.node.body:
        needed.update(_loaded_names(statement))
    seeded = _ctx_with_required_module_bindings(
        parsed.body,
        target_index,
        needed,
        source=source,
        sourcefile=sourcefile,
        ctx=ctx,
        resolving=frozenset({bridge}),
        defining_module=module_name,
    )
    return seeded if seeded is not None else ctx


def build_dig_body(
    fn_site,
    ctx: Any,
    *,
    require_attachable: bool = False,
    oracle_variant: str | None = None,
):
    """Build diggable body for ``fn_site`` FunctionDef, or None on failure.

    Sole constructor for dig body *structure* is :data:`DIG_BODY_ORACLE`. Call
    sites re-wrap the published body with their formal/module context; they do
    not re-factory the body statements.
    """
    if fn_site is None or fn_site.observed != "FunctionDef":
        return None
    if require_attachable and not method_body_is_attachable(fn_site):
        return None
    name = fn_site.function_name()
    site = getattr(fn_site, "blame", None) or name
    from sugar_lift_py_tests.engine_log import reduction_span

    with reduction_span(
        sugar=str(name),
        role="dig.build_body",
        site=str(site),
    ):
        return _build_dig_body_impl(fn_site, ctx, oracle_variant=oracle_variant)


def _build_dig_body_impl(
    fn_site,
    ctx: Any,
    *,
    oracle_variant: str | None = None,
):
    from dataclasses import replace

    from sugar_lift_py_tests.claim import SugarRole
    from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
    from sugar_lift_py_tests.sugar.control_flow_body_sugar import (
        ControlFlowBodySugar,
    )
    from sugar_lift_py_tests.sugar_body import SugarBody

    building = getattr(ctx, "building", frozenset()) or frozenset()
    name = fn_site.function_name()
    bridge = getattr(fn_site.node, "_sugar_bridge_name", None) or name
    if name in building or bridge in building:
        # Cycle: never publish a half-body.
        return None

    from sugar_lift_py_tests.engine_log import reduction_span

    try:
        body_ctx = replace(ctx, building=building | {name, bridge})
        body_ctx = _ctx_with_method_module_bindings(fn_site, body_ctx)
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

        formal_ctx = ControlFlowBodySugar.build_context(fn_site, body_ctx)
        oracle = DIG_BODY_ORACLE
        key = oracle.cache_key(fn_site, body_ctx)
        if key is not None and oracle_variant is not None:
            key = (key, oracle_variant)
        core = oracle.get(key) if key is not None else _MISSING
        if core is _MISSING:
            with reduction_span(
                sugar=str(name),
                role="dig.build_body.construct",
                site=str(getattr(fn_site, "blame", None) or name),
            ):
                oracle.construct_count += 1
                frags = fn_site.function_body()
                # Single return expr → existing bridge body (TERM sugar).
                if (
                    len(frags) == 1
                    and frags[0].observed == "Return"
                    and frags[0].return_value() is not None
                ):
                    core = ControlFlowBodySugar.build_bridge_body(fn_site, body_ctx)
                else:
                    # Straight-line Assign* + Return → sequential dig body.
                    statements = tuple(
                        formal_ctx.build_body(stmt, SugarRole.STATEMENT)
                        for stmt in frags
                    )
                    core = SugarBody(
                        sugar=SequentialDigBody(
                            statements=statements,
                            fn_site=fn_site,
                            contextmanager_yield=(
                                contextmanager_exit_contract_for_fragment(fn_site)
                                is not None
                            ),
                        ),
                        role=SugarRole.TERM,
                    )
            if key is not None:
                oracle.put(key, core)
        else:
            with reduction_span(
                sugar=str(name),
                role="dig.build_body.hit",
                site=str(getattr(fn_site, "blame", None) or name),
            ):
                pass
        return _contextualized_dig_body(core, formal_ctx)
    except FactoryPanic:
        # A selected unsupported body is a floor breach, never coordinate-only.
        raise


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
    default_ctx = _ctx_with_method_module_bindings(fn_site, ctx)

    def collect(remaining: tuple, accumulated: tuple):
        if not remaining:
            return Complete((formals, (*arg_values, *accumulated)))
        head, *rest = remaining
        return (
            default_ctx.build_body(head, SugarRole.TERM)
            .reduce(default_ctx)
            .and_then(lambda value: collect(tuple(rest), (*accumulated, value)))
        )

    return collect(selected, ())


_resolve_install_source_funcdef = resolve_install_source_funcdef
