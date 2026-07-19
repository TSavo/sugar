from __future__ import annotations

import ast
import hashlib
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass, field as dataclass_field
from enum import Enum
from typing import Any, cast

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody

# Deferred body statements (#5321) are factory-built only when dig demands them.
# Residual post-#5321 hang profiles show the same statement sites re-entering
# factory.select / factory.new on every SequentialDigBody.reduce (set_module
# bodies 9–18× per residual file). Structure is content-addressed and immutable;
# live reduce still uses the call-site temporal. Capacity is resident ownership
# only (eviction recomputes; not invalidation).
DEFERRED_STATEMENT_STRUCTURE_CAPACITY = 1024
_MISSING = object()


@dataclass(frozen=True)
class _ObjectIdentity:
    """Hashable strong identity for opaque recognition inputs.

    Holding the object prevents Python from reusing its id while a cache entry
    is resident. Equality is deliberately object identity, never a potentially
    context-blind ``__eq__`` implementation.
    """

    value: Any = dataclass_field(compare=False, hash=False, repr=False)

    def __hash__(self) -> int:
        return id(self.value)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _ObjectIdentity) and self.value is other.value


def _immutable_recognition_identity(
    value: Any, seen: frozenset[int] = frozenset()
) -> Any:
    """Freeze one factory-recognition input into an immutable cache-key part."""
    if value is None or isinstance(value, (bool, int, float, str, bytes)):
        return value
    if isinstance(value, Enum):
        return (type(value).__module__, type(value).__qualname__, value.value)
    if isinstance(value, ast.AST):
        return ("ast", ast.dump(value, annotate_fields=True, include_attributes=True))
    marker = id(value)
    if marker in seen:
        return ("cycle", _ObjectIdentity(value))
    nested_seen = seen | {marker}
    if isinstance(value, Mapping):
        frozen = tuple(
            (
                _immutable_recognition_identity(key, nested_seen),
                _immutable_recognition_identity(item, nested_seen),
            )
            for key, item in value.items()
        )
        return (
            "mapping",
            tuple(sorted(frozen, key=repr)),
        )
    if isinstance(value, (tuple, list)):
        return (
            type(value).__name__,
            tuple(_immutable_recognition_identity(item, nested_seen) for item in value),
        )
    if isinstance(value, (set, frozenset)):
        frozen = tuple(
            _immutable_recognition_identity(item, nested_seen) for item in value
        )
        return (type(value).__name__, tuple(sorted(frozen, key=repr)))
    if is_dataclass(value) and not isinstance(value, type):
        return (
            type(value).__module__,
            type(value).__qualname__,
            tuple(
                (
                    item.name,
                    _immutable_recognition_identity(
                        getattr(value, item.name), nested_seen
                    ),
                )
                for item in fields(value)
            ),
        )
    if isinstance(value, type):
        return ("type", value.__module__, value.__qualname__)
    if callable(value):
        return (
            "callable",
            getattr(value, "__module__", type(value).__module__),
            getattr(value, "__qualname__", type(value).__qualname__),
            _ObjectIdentity(value),
        )
    return _ObjectIdentity(value)


# These fields are mutable construction telemetry, not candidate-recognition
# inputs. Their object identity still belongs in the cache key so a structure
# never crosses output membranes; their growing contents must not invalidate a
# successfully constructed immutable body.
_FACTORY_OUTPUT_FIELDS = frozenset(
    {
        "external_bridge_sink",
        "audit_sink",
        "factory_audit_sink",
        "proof_sink",
        "report_sink",
        "operation_log",
        "module_rewrite_log",
        "dig_sink",
        "record_operation",
    }
)


def _factory_recognition_identity(build_ctx: Any) -> tuple[Any, ...]:
    """Complete identity of every input carried by FactoryBuildContext."""
    return tuple(
        (
            item.name,
            (
                _ObjectIdentity(value)
                if item.name in _FACTORY_OUTPUT_FIELDS and value is not None
                else _immutable_recognition_identity(value)
            ),
        )
        for item in fields(build_ctx)
        for value in (getattr(build_ctx, item.name),)
    )


class DeferredStatementStructureOracle:
    """Sole memo for deferred function-body statement *structure*.

    Identity is the recognized source fragment's complete enclosing source plus
    every FactoryBuildContext input that can participate in factory recognition.
    The published value is the factory-built ``SugarBody`` — the complete
    immutable structure for that construction identity.

    Publishing rules (match InstallSourceValueOracle / DigBodyOracle):
      - Successfully factory-built SugarBody is published under the key.
      - FactoryPanic propagates and never publishes.
      - Incomplete / None are reduce outcomes, never stored as success.
      - Live ``reduce`` always re-runs against the call-site context; only
        structure is memoized, never a Complete/Incomplete desugar result.
    """

    __slots__ = ("_capacity", "_table", "construct_count", "hit_count")

    def __init__(self, capacity: int = DEFERRED_STATEMENT_STRUCTURE_CAPACITY) -> None:
        self._capacity = max(int(capacity), 1)
        self._table: OrderedDict[tuple[Any, ...], SugarBody] = OrderedDict()
        self.construct_count = 0
        self.hit_count = 0

    def identity_key(self, site: Any, build_ctx: Any) -> tuple[Any, ...] | None:
        """Complete construction identity for one deferred body statement."""
        filename = str(getattr(site, "filename", "") or "")
        line_raw = getattr(site, "line", None)
        col_raw = getattr(site, "col", None)
        line = int(line_raw) if line_raw is not None else -1
        col = int(col_raw) if col_raw is not None else -1
        observed = str(getattr(site, "observed", "") or "")
        if not filename or line < 0 or not observed:
            return None
        source = getattr(site, "source", None)
        node = getattr(site, "node", None)
        if not isinstance(source, str) or node is None:
            return None
        from sugar_lift_python_source.source_tables import source_segment

        segment = source_segment(source, node)
        if not isinstance(segment, str):
            return None
        return (
            filename,
            line,
            col,
            observed,
            hashlib.sha256(source.encode("utf-8")).hexdigest(),
            segment,
            _factory_recognition_identity(build_ctx),
        )

    def resolve(self, site: Any, build_ctx: Any) -> SugarBody:
        """Return factory-built statement structure; construct once per identity."""
        key = self.identity_key(site, build_ctx)
        if key is not None:
            known = self._lookup(key)
            if known is not _MISSING:
                return known  # type: ignore[return-value]

        self.construct_count += 1
        body = build_ctx.build_body(site, SugarRole.STATEMENT)
        if key is not None:
            self._publish(key, body)
        return body

    def _lookup(self, key: tuple[Any, ...]) -> Any:
        value = self._table.get(key, _MISSING)
        if value is _MISSING:
            return _MISSING
        self._table.move_to_end(key)
        self.hit_count += 1
        return value

    def _publish(self, key: tuple[Any, ...], value: SugarBody) -> None:
        if value is None:  # pragma: no cover - defensive; build_body never returns None
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


# Process-lifetime sole structure memo for deferred body statements.
DEFERRED_STATEMENT_STRUCTURE_ORACLE = DeferredStatementStructureOracle()


@dataclass(frozen=True)
class _DeferredFactoryStatement:
    """Construct one function-body statement only when dig reaches it.

    Structure is memoized by content identity after the first successful
    factory build. Each dig still reduces against the live call-site context.
    """

    site: Any
    build_ctx: Any

    def reduce(self, ctx):
        body = DEFERRED_STATEMENT_STRUCTURE_ORACLE.resolve(self.site, self.build_ctx)
        return body.reduce(ctx)


@dataclass(frozen=True)
class StatementFunctionDefSugar(Sugar, role=SugarRole.STATEMENT):
    """An executable ``def`` binds a named callable without reducing its body."""

    name: str
    signature: tuple[tuple[str, str], ...]
    decorators: tuple[SugarBody, ...]
    positional_defaults: tuple[SugarBody, ...]
    keyword_only_defaults: tuple[SugarBody | None, ...]
    body: SugarBody | tuple[_DeferredFactoryStatement, ...]
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "FunctionDef"

    @classmethod
    def new(cls, site, ctx) -> "StatementFunctionDefSugar":
        return cls(
            name=getattr(site.node, "_sugar_bridge_name", site.function_name()),
            signature=site.function_binding_signature(),
            decorators=tuple(
                ctx.build_body(decorator, SugarRole.TERM)
                for decorator in site.function_decorators()
            ),
            positional_defaults=tuple(
                ctx.build_body(default, SugarRole.TERM)
                for default in site.function_defaults()
            ),
            keyword_only_defaults=tuple(
                None if default is None else ctx.build_body(default, SugarRole.TERM)
                for default in site.function_keyword_only_defaults()
            ),
            # Python constructs decorators/defaults when executing ``def``;
            # the body itself is not executed. Preserve the recognized source
            # fragments for SequentialDigBody instead of recursively
            # factory-building every descendant merely to bind the callable.
            body=(
                tuple(
                    _DeferredFactoryStatement(statement, ctx)
                    for statement in site.function_body()
                )
                if ctx.defer_function_body_construction
                else ctx.build_body(site.function_body_block(), SugarRole.STATEMENT)
            ),
            site=site,
        )

    @staticmethod
    def _module_source_for_site(site, ctx) -> tuple[str, str] | None:
        del ctx
        if site.observed != "FunctionDef":
            return None
        sugar_file = getattr(site.node, "_sugar_file", None)
        sugar_source = getattr(site.node, "_sugar_source", None)
        bridge_name = getattr(site.node, "_sugar_bridge_name", None)
        if not (
            isinstance(sugar_file, str)
            and sugar_file
            and isinstance(sugar_source, str)
            and sugar_source
        ):
            return None
        if bridge_name is not None and not (
            isinstance(bridge_name, str)
            and "." in bridge_name
            and bridge_name.rsplit(".", 1)[-1] == site.function_name()
        ):
            return None
        return sugar_source, sugar_file

    @classmethod
    def _names_in_fragment(cls, site) -> list[str]:
        if site.observed == "Name":
            return [site.name_id()]
        if site.observed == "Call":
            names: list[str] = []
            receiver = site.call_receiver()
            if receiver is not None:
                names.extend(cls._names_in_fragment(receiver))
            else:
                target = site.call_target_name()
                if target is not None:
                    names.append(target)
            for arg in site.call_args():
                names.extend(cls._names_in_fragment(arg))
            for keyword in site.call_keywords():
                names.extend(cls._names_in_fragment(keyword.keyword_value()))
            return names
        if site.observed == "Attribute":
            return cls._names_in_fragment(site.attr_receiver())
        if site.observed == "keyword":
            return cls._names_in_fragment(site.keyword_value())
        names = []
        for child in site.fragments():
            names.extend(cls._names_in_fragment(child))
        return names

    @staticmethod
    def _module_level_declarations_before(root, fn) -> list:
        declarations: list = []
        fn_name = fn.function_name()
        top_level = [
            statement
            for fragment in root.fragments()
            for statement in fragment.statements()
        ]
        for index, statement in enumerate(top_level):
            candidates = (
                [statement]
                if statement.observed == "FunctionDef"
                else [
                    nested
                    for nested in statement.walk()
                    if nested.observed == "FunctionDef"
                ]
            )
            if any(
                candidate.function_name() == fn_name
                and (
                    (fn.line and candidate.line == fn.line)
                    or (not fn.line and candidate.col == fn.col)
                )
                for candidate in candidates
            ):
                declarations.extend(
                    later
                    for later in top_level[index + 1 :]
                    if later.observed == "ClassDef"
                )
                return declarations
            if (
                statement.observed == "Assign"
                and statement.assign_target_name() is not None
            ):
                declarations.append(statement)
            elif statement.observed == "AnnAssign":
                try:
                    statement.annassign_target_id()
                except TypeError:
                    continue
                if statement.annassign_value() is not None:
                    declarations.append(statement)
            elif statement.observed in ("Import", "ImportFrom", "Try", "ClassDef"):
                declarations.append(statement)
        return []

    @classmethod
    def _module_declaration_bound_names(cls, statement) -> set[str]:
        if statement.observed == "Assign":
            name = statement.assign_target_name()
            return set() if name is None else {name}
        if statement.observed == "AnnAssign":
            try:
                return {statement.annassign_target_id()}
            except TypeError:
                return set()
        if statement.observed == "Import":
            return {
                alias or imported.split(".", 1)[0]
                for imported, alias in statement.import_names()
            }
        if statement.observed == "ImportFrom":
            return {
                alias or imported
                for imported, alias in statement.importfrom_names()
                if imported != "*"
            }
        if statement.observed == "Try":
            return cls._try_module_bound_names(statement)
        if statement.observed == "ClassDef":
            from sugar_lift_py_tests.sugar.class_def_sugar import ClassDefSugar

            base_names = statement.class_base_names()
            if (
                not ClassDefSugar.decorators_preserve_identity(statement)
                or statement.class_keywords()
                or any(base_name is None for base_name in base_names)
            ):
                return set()
            return {statement.class_name()}
        return set()

    @classmethod
    def _try_module_bound_names(cls, statement) -> set[str]:
        names: set[str] = set()
        suites = [statement.try_body()]
        suites.extend(
            handler.except_handler_body() for handler in statement.try_handlers()
        )
        orelse = statement.try_orelse()
        if orelse is not None:
            suites.append(orelse)
        for suite in suites:
            for child in suite.statements():
                names.update(cls._module_declaration_bound_names(child))
        return names

    @classmethod
    def module_context_for(cls, site, ctx):
        """Replay demanded module declarations through their registered Sugars."""
        from sugar_lift_py_tests.factory.source_fragment import SourceFragment
        from sugar_lift_py_tests.outcome import Incomplete, complete_value

        needed: set[str] = set()
        for body_stmt in site.function_body():
            needed.update(cls._names_in_fragment(body_stmt))
        needed -= set(site.function_params())
        if not needed:
            return ctx

        # The file gateway has already constructed the execution-order prefix
        # into module_temporal. Capture exact demanded values from that frame
        # instead of reparsing and replaying their declarations once per
        # FunctionDef. Missing/forward names still take the constructor below.
        folded_ctx = ctx
        module_temporal = ctx.module_temporal
        if module_temporal is not None:
            captured = {
                name: value
                for name in needed
                if (value := module_temporal.value_if_bound(name)) is not None
            }
            temporal = folded_ctx.temporal
            for name, value in captured.items():
                temporal = temporal.bind_value(name, value)
            folded_ctx = folded_ctx.with_temporal(temporal)
            needed.difference_update(captured)
            if not needed:
                return folded_ctx

        loaded = cls._module_source_for_site(site, ctx)
        if loaded is None:
            return folded_ctx
        source, filename = loaded
        try:
            root = SourceFragment.from_source(source, filename)
        except SyntaxError:
            return folded_ctx
        declarations = cls._module_level_declarations_before(root, site)
        if not declarations:
            return folded_ctx

        selected: list = []
        needed_work = set(needed)
        for prior in reversed(declarations):
            owned = cls._module_declaration_bound_names(prior)
            wanted = owned & needed_work
            if not wanted:
                continue
            selected.append(prior)
            needed_work.difference_update(wanted)
            if prior.observed == "Assign":
                needed_work.update(cls._names_in_fragment(prior.assign_value()))
            elif prior.observed == "AnnAssign":
                value = prior.annassign_value()
                if value is not None:
                    needed_work.update(cls._names_in_fragment(value))
            elif prior.observed == "Try":
                needed_work.update(cls._names_in_fragment(prior))
        selected.reverse()

        for prior in selected:
            if prior.observed == "ImportFrom" and (
                prior.importfrom_level() or not prior.importfrom_module()
            ):
                continue
            body = folded_ctx.build_body(prior, SugarRole.STATEMENT)
            if prior.observed == "Import":
                from sugar_lift_py_tests.sugar.import_sugar import ImportSugar

                if not isinstance(body.sugar, ImportSugar):
                    raise TypeError(
                        f"Import statement selected {type(body.sugar).__name__}"
                    )
                outcome = body.sugar.desugar_module_context(folded_ctx)
            elif prior.observed == "ClassDef":
                from sugar_lift_py_tests.sugar.class_def_sugar import ClassDefSugar

                if not isinstance(body.sugar, ClassDefSugar):
                    raise TypeError(f"ClassDef selected {type(body.sugar).__name__}")
                outcome = body.sugar.desugar_module_context(folded_ctx)
            else:
                outcome = body.reduce(folded_ctx)
            if isinstance(outcome, Incomplete):
                from sugar_lift_py_tests.factory.factory_gap import factory_panic_gap

                factory_panic_gap(
                    owner="StatementFunctionDefSugar.module_context_for",
                    blame=prior,
                    observed=prior.observed,
                    requested="module-binding",
                    fix=(
                        "construct this dependency in its owning Sugar or narrow "
                        "owns() so the factory None arm panics"
                    ),
                    selected=type(body.sugar).__name__,
                )
            complete_value(
                outcome, owner="StatementFunctionDefSugar.module_context_for"
            )
            folded_ctx = outcome.extend_scope(folded_ctx)
        return folded_ctx

    @classmethod
    def witnesses(cls):
        prefix = (
            "def A(z):\n"
            "    def inner(x):\n"
            "        return x\n"
            "    return inner(z)\n\n"
        )
        expansion_prefix = (
            "def A():\n"
            "    def inner(**options):\n"
            '        return options["value"]\n'
            '    return inner(**{"value": 5})\n\n'
        )
        default_expansion_prefix = (
            "def A():\n"
            "    def inner(required, optional=4, **options):\n"
            '        return optional + options["value"]\n'
            '    return inner(1, **{"value": 5})\n\n'
        )
        self_binding_prefix = (
            "def A():\n"
            "    def inner():\n"
            "        callback = inner\n"
            "        return 5\n"
            "    return inner()\n\n"
        )
        unexpected_keyword_prefix = (
            "def A(z):\n"
            "    def inner(value):\n"
            "        return value\n"
            "    if z < 0:\n"
            "        inner(z, extra=1)\n"
            "    return z\n\n"
        )
        diggable_expansion_prefix = (
            "def A():\n"
            "    def options():\n"
            '        return {"value": 5}\n'
            "    def inner(**kwargs):\n"
            '        return kwargs["value"]\n'
            "    return inner(**options())\n\n"
        )
        multi_expansion_prefix = (
            "def A():\n"
            "    def inner(**kwargs):\n"
            '        return kwargs["left"] + kwargs["right"]\n'
            '    return inner(**{"left": 2}, **{"right": 3})\n\n'
        )
        decorated_callable_prefix = (
            "def A(z):\n"
            "    def decorate(func):\n"
            "        def wrapper(value):\n"
            "            return func(value, 4)\n"
            "        return wrapper\n"
            "    @decorate\n"
            "    def add(value, increment):\n"
            "        return value + increment\n"
            "    return add(z)\n\n"
        )
        return (
            _call_pair(
                name="statement_function_def_return",
                owner_sugar="StatementFunctionDefSugar",
                truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
                lying=prefix + "def test_a():\n    assert A(5) == 6\n",
            ),
            _call_pair(
                name="statement_function_def_keyword_expansion_return",
                owner_sugar="StatementFunctionDefSugar",
                truthful=expansion_prefix + "def test_a():\n    assert A() == 5\n",
                lying=expansion_prefix + "def test_a():\n    assert A() == 6\n",
            ),
            _call_pair(
                name="statement_function_def_default_keyword_expansion_return",
                owner_sugar="StatementFunctionDefSugar",
                truthful=(
                    default_expansion_prefix + "def test_a():\n    assert A() == 9\n"
                ),
                lying=(
                    default_expansion_prefix + "def test_a():\n    assert A() == 10\n"
                ),
            ),
            _call_pair(
                name="statement_function_def_self_binding_return",
                owner_sugar="StatementFunctionDefSugar",
                truthful=self_binding_prefix + "def test_a():\n    assert A() == 5\n",
                lying=self_binding_prefix + "def test_a():\n    assert A() == 6\n",
            ),
            _call_pair(
                name="statement_function_def_unexpected_keyword_type_error",
                owner_sugar="StatementFunctionDefSugar",
                truthful=(
                    unexpected_keyword_prefix + "def test_a():\n    assert A(5) == 5\n"
                ),
                lying=(
                    unexpected_keyword_prefix + "def test_a():\n    assert A(5) == 6\n"
                ),
            ),
            _call_pair(
                name="statement_function_def_decorated_callable_substitution",
                owner_sugar="StatementFunctionDefSugar",
                truthful=(
                    decorated_callable_prefix
                    + "def test_a():\n"
                    + "    assert A(3) == 7\n"
                ),
                lying=(
                    decorated_callable_prefix
                    + "def test_a():\n"
                    + "    assert A(3) == 8\n"
                ),
            ),
            _call_pair(
                name="statement_function_def_diggable_keyword_expansion_return",
                owner_sugar="StatementFunctionDefSugar",
                truthful=(
                    diggable_expansion_prefix + "def test_a():\n    assert A() == 5\n"
                ),
                lying=(
                    diggable_expansion_prefix + "def test_a():\n    assert A() == 6\n"
                ),
            ),
            _call_pair(
                name="statement_function_def_multi_keyword_expansion_return",
                owner_sugar="StatementFunctionDefSugar",
                truthful=(
                    multi_expansion_prefix + "def test_a():\n    assert A() == 5\n"
                ),
                lying=(multi_expansion_prefix + "def test_a():\n    assert A() == 6\n"),
            ),
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self._reduce_decorators(self.decorators, (), ctx)

    def _reduce_decorators(self, remaining, accumulated, ctx) -> Outcome:
        if remaining:
            head, *rest = remaining
            return head.reduce(ctx).and_then(
                lambda value: self._reduce_decorators(
                    tuple(rest), (*accumulated, value), ctx
                )
            )
        return self._reduce_defaults(self.positional_defaults, (), accumulated, ctx)

    def _reduce_defaults(self, remaining, accumulated, decorators, ctx) -> Outcome:
        if remaining:
            head, *rest = remaining
            return head.reduce(ctx).and_then(
                lambda value: self._reduce_defaults(
                    tuple(rest), (*accumulated, value), decorators, ctx
                )
            )
        return self._reduce_keyword_only_defaults(
            self.keyword_only_defaults, (), accumulated, decorators, ctx
        )

    def _reduce_keyword_only_defaults(
        self, remaining, accumulated, positional_defaults, decorators, ctx
    ) -> Outcome:
        if remaining:
            head, *rest = remaining
            if head is None:
                return self._reduce_keyword_only_defaults(
                    tuple(rest),
                    (*accumulated, None),
                    positional_defaults,
                    decorators,
                    ctx,
                )
            return head.reduce(ctx).and_then(
                lambda value: self._reduce_keyword_only_defaults(
                    tuple(rest),
                    (*accumulated, value),
                    positional_defaults,
                    decorators,
                    ctx,
                )
            )
        return self._construct_callable(
            positional_defaults, accumulated, decorators, ctx
        )

    def _construct_callable(
        self, positional_defaults, keyword_only_defaults, decorators, ctx
    ) -> Outcome:
        from sugar_lift_py_tests.floor import FunctionCallable
        from sugar_lift_py_tests.sugar.block_sugar import BlockSugar
        from sugar_lift_py_tests.sugar.install_source_dig import (
            SequentialDigBody,
            _contextualized_dig_body,
            contextmanager_exit_contract_for_fragment,
            resolve_contextmanager_exit_contract,
        )

        site = cast(Any, self.site)
        contextmanager_contract = contextmanager_exit_contract_for_fragment(site)
        callable_body = self.body
        body_ctx = type(self).module_context_for(site, ctx)
        if isinstance(self.body, tuple):
            callable_body = _contextualized_dig_body(
                SugarBody(
                    sugar=SequentialDigBody(
                        self.body,
                        fn_site=site,
                        contextmanager_yield=contextmanager_contract is not None,
                    ),
                    role=SugarRole.TERM,
                ),
                body_ctx,
            )
        elif isinstance(self.body.sugar, BlockSugar):
            callable_body = _contextualized_dig_body(
                SugarBody(
                    sugar=SequentialDigBody(
                        self.body.sugar.statements,
                        fn_site=site,
                        contextmanager_yield=contextmanager_contract is not None,
                    ),
                    role=SugarRole.TERM,
                ),
                body_ctx,
            )
        return Complete(
            FunctionCallable(
                name=self.name,
                parameters=tuple(name for name, _kind in self.signature),
                parameter_kinds=tuple(kind for _name, kind in self.signature),
                positional_defaults=positional_defaults,
                keyword_only_defaults=keyword_only_defaults,
                decorators=decorators,
                exit_suppression=(
                    resolve_contextmanager_exit_contract(bridge_name)
                    if (bridge_name := getattr(site.node, "_sugar_bridge_name", None))
                    else contextmanager_contract
                ),
                body=callable_body,
            )
        )

    def walk_children(self):
        children = (
            *self.decorators,
            *self.positional_defaults,
            *(default for default in self.keyword_only_defaults if default is not None),
        )
        if isinstance(self.body, SugarBody):
            return (*children, self.body)
        return children
