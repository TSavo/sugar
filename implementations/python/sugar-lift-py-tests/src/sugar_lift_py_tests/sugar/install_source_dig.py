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
import importlib.util
import ast
import functools
import inspect
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def module_sibling_function_nodes(module_name: str) -> dict:
    """Copy-on-read facade over the memoized bridge table (callers may pop)."""
    return dict(_module_sibling_function_nodes(module_name))


@functools.lru_cache(maxsize=None)
def _module_sibling_function_nodes(module_name: str) -> dict:
    """AST FunctionDef nodes for every def in ``module_name``, bare + qualified keys.

    Also indexes ``Class.method`` / ``module.Class.method`` for method body dig.
    """
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment

    sourcefile = None
    source = None
    try:
        # Source presence is the construction boundary. Reading a module must
        # not execute its import-time optional-dependency guards merely to dig
        # definitions whose Python source is already installed.
        spec = importlib.util.find_spec(module_name)
        origin = getattr(spec, "origin", None)
        if origin and origin.endswith((".py", ".pyi")):
            sourcefile = origin
            source = Path(origin).read_text(encoding="utf-8")
    except (
        ImportError,
        ModuleNotFoundError,
        OSError,
        TypeError,
        UnicodeError,
        ValueError,
    ):
        pass

    if source is None:
        try:
            from _pytest.outcomes import Skipped

            module = importlib.import_module(module_name)
            sourcefile = inspect.getsourcefile(module)
            if not sourcefile:
                return {}
            source = Path(sourcefile).read_text(encoding="utf-8")
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
                    status="floor-gap",
                    observed=type(skipped).__name__,
                    blame=module_name,
                    selected=None,
                    candidates=[],
                    message=f"install-source import raised pytest Skipped: {skipped}; {info.message}",
                ),
            )
        except (ImportError, OSError, TypeError, UnicodeError):
            return {}
    try:
        parsed = SourceFragment.from_source_private(source, sourcefile)
    except SyntaxError:
        return {}
    nodes: dict = {}
    for child in parsed.walk():
        if child.observed == "FunctionDef":
            name = child.function_name()
            child.node.decorator_list = []  # type: ignore[attr-defined]
            child.node._sugar_source = source  # type: ignore[attr-defined]
            child.node._sugar_file = sourcefile  # type: ignore[attr-defined]
            child.node._sugar_bridge_name = f"{module_name}.{name}"  # type: ignore[attr-defined]
            nodes[name] = child.node
            nodes[f"{module_name}.{name}"] = child.node
        elif child.observed == "ClassDef":
            cname = child.class_name()
            for stmt in child.class_body():
                if stmt.observed != "FunctionDef":
                    continue
                mname = stmt.function_name()
                stmt.node.decorator_list = []  # type: ignore[attr-defined]
                stmt.node._sugar_source = source  # type: ignore[attr-defined]
                stmt.node._sugar_file = sourcefile  # type: ignore[attr-defined]
                stmt.node._sugar_bridge_name = f"{module_name}.{cname}.{mname}"  # type: ignore[attr-defined]
                nodes[f"{cname}.{mname}"] = stmt.node
                nodes[f"{module_name}.{cname}.{mname}"] = stmt.node
    return nodes


@functools.lru_cache(maxsize=None)
def resolve_install_source_funcdef(import_target: str):
    """Resolve ``module.attr`` to an installed FunctionDef SourceFragment, or None."""
    if "." not in import_target:
        return None
    module_name, attr = import_target.rsplit(".", 1)
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment

    try:
        module = importlib.import_module(module_name)
        obj = getattr(module, attr)
        if not callable(obj) or inspect.isclass(obj):
            return None
        source = textwrap.dedent(inspect.getsource(obj))
    except (ImportError, AttributeError, OSError, TypeError):
        return None
    try:
        sourcefile = inspect.getsourcefile(obj) or f"<{module_name}>"
    except TypeError:
        sourcefile = f"<{module_name}>"
    try:
        parsed = SourceFragment.from_source_private(source, sourcefile)
    except SyntaxError:
        return None
    for child in parsed.walk():
        if child.observed == "FunctionDef" and child.function_name() == attr:
            child.node.decorator_list = []  # type: ignore[attr-defined]
            child.node._sugar_source = source  # type: ignore[attr-defined]
            child.node._sugar_file = sourcefile  # type: ignore[attr-defined]
            child.node._sugar_bridge_name = import_target  # type: ignore[attr-defined]
            return child
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
    """Names Python evaluates while constructing a function definition.

    A function body is deferred, but decorators are evaluated in the defining
    module when the ``def`` statement executes.  Keep that temporal boundary
    explicit: body globals belong to later call/dig construction and must not
    make an unrelated decorator seed eagerly construct them.
    """
    needed: set[str] = set()
    for decorator in statement.decorator_list:
        needed.update(_loaded_names(decorator))
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
    from sugar_lift_py_tests.floor import ImportAliasValue
    from sugar_lift_py_tests.outcome import complete_value
    from sugar_lift_py_tests.temporal import TemporalContext

    # Imported values are constructed in the defining module's lexical frame.
    # Consumer locals are not module globals and must never satisfy these Names.
    needed = set(needed)

    selected: list[ast.stmt] = []
    for statement in reversed(statements[:target_index]):
        assigned = _module_assignment_name(statement)
        imports = _module_import_bindings(statement)
        owned = ({assigned} if assigned is not None else set()) | set(imports)
        wanted = owned & needed
        if not wanted:
            continue
        selected.append(statement)
        needed.difference_update(wanted)
        if assigned in wanted:
            value = (
                statement.value
                if isinstance(statement, (ast.Assign, ast.AnnAssign))
                else None
            )
            needed.update(_loaded_names(value))
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

        fragment = SourceFragment.from_node(statement, sourcefile, source=source)
        outcome = module_ctx.build_body(fragment, SugarRole.STATEMENT).reduce(
            module_ctx
        )
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
    module_name, attr = import_target.rsplit(".", 1)
    try:
        spec = importlib.util.find_spec(module_name)
        sourcefile = getattr(spec, "origin", None)
        if not sourcefile or not sourcefile.endswith((".py", ".pyi")):
            return None
        source = Path(sourcefile).read_text(encoding="utf-8")
        parsed = ast.parse(source, filename=sourcefile)
    except (
        ImportError,
        ModuleNotFoundError,
        OSError,
        SyntaxError,
        TypeError,
        ValueError,
    ):
        return None

    from sugar_lift_py_tests.claim import SugarRole
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment
    from sugar_lift_py_tests.outcome import complete_value

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
        elif (
            isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
            and statement.name == attr
        ):
            module_ctx = _ctx_with_required_module_bindings(
                parsed.body,
                target_index,
                _function_definition_dependencies(statement),
                source=source,
                sourcefile=sourcefile,
                ctx=ctx,
                resolving=resolving,
            )
            body = module_ctx.build_body(
                SourceFragment.from_node(statement, sourcefile, source=source),
                SugarRole.STATEMENT,
            )
            return complete_value(
                body.reduce(module_ctx), owner="install-source imported function"
            )
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
            body = module_ctx.build_body(
                SourceFragment.from_node(value_node, sourcefile, source=source),
                SugarRole.TERM,
            )
            return complete_value(
                body.reduce(module_ctx), owner="install-source imported value"
            )
    return None


@functools.lru_cache(maxsize=None)
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
    """Reduce straight-line statements; surface the last return value for dig.

    Used when method bodies are ``x = f(x); return x + ...``. Dig wants the
    return floor, not a BlockValue record. Scope threads via BoundVar.
    """

    statements: tuple  # SugarBody STATEMENT

    def desugar(self, ctx: Any = None):
        from sugar_lift_py_tests.floor.return_value import ReturnValue
        from sugar_lift_py_tests.outcome import Complete, Incomplete

        cur = ctx
        last_return = None
        for stmt in self.statements:
            outcome = stmt.reduce(cur)
            from sugar_lift_py_tests.outcome import Incomplete as _Inc

            if isinstance(outcome, _Inc):
                return outcome
            cur = outcome.extend_scope(cur)
            for item in outcome.contribution():
                if isinstance(item, ReturnValue):
                    last_return = item
        if last_return is not None:
            # Dig wants the returned floor, not the ReturnValue wrapper.
            return Complete(last_return.value)
        from sugar_lift_py_tests.effect import (
            ConditionalExpressionRuntimeEffect,
            RuntimeEffectWitness,
        )
        from sugar_lift_py_tests.ir import ctor, str_const

        terminal = self.statements[-1] if self.statements else None
        audit_row = getattr(terminal, "audit_row", None)
        blame = getattr(audit_row, "blame", "<install-source-dig>")
        observed = getattr(audit_row, "observed", "SequentialDigBody")
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
                    locus=str(blame),
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
            sugar=SequentialDigBody(statements=statements),
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
