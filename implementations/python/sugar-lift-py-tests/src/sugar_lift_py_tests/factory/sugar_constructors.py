from __future__ import annotations

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.sugar.control_flow_body_sugar import (
    select_control_flow_body_sugar as build_control_flow_body_sugar,
)

from .source_fragment import SourceFragment


class IncompleteFunctionBody(Exception):
    def __init__(self, incomplete):
        super().__init__(incomplete.reason)
        self.incomplete = incomplete


def _ctx_with_formal_binds(site: SourceFragment, ctx):
    """Factory build ctx with formals bound as SymbolicValue(<name>).

    CallSugar selects MethodCallStrategy for bare Name receivers only when the
    name is temporally bound at *build* time (`_method_receiver_is_temporally_bound`).
    Universe dig already binds via `build_control_flow_body_sugar`; the single-return
    bridge shortcut must bind too, or `def A(s): return s.mean()` builds as
    factory_panic(call-method:mean) while the universe post correctly states
    `out == call:mean(s)`.

    Install-source digs (``_sugar_file`` / ``_sugar_source`` on the FunctionDef)
    also seed module-level ``Name = ...`` Assign constants into temporal so body
    names like ``_urlsafe_encode_translation`` reduce instead of TemporalContext
    floor-gapping before NameSugar.
    """
    from sugar_lift_py_tests.floor import SymbolicValue
    from sugar_lift_py_tests.ir import make_var
    from sugar_lift_py_tests.temporal import TemporalContext, bind_temporal

    module_temporal = getattr(ctx, "module_temporal", None)
    # Function construction starts from its defining module, never the caller's
    # live temporal and never the process-wide builtin seed. A module traversal
    # may provide an explicit lexical frame; install-source functions reconstruct
    # their source-owned prerequisites below.
    body_ctx = ctx.with_temporal(
        module_temporal if module_temporal is not None else TemporalContext()
    )
    body_ctx = _ctx_with_module_global_binds(site, body_ctx)
    for param_name in site.function_params():
        body_ctx = bind_temporal(
            body_ctx,
            param_name,
            SymbolicValue(make_var(param_name)),
            owner="sugar_constructors.formal_binds",
            blame=f"{getattr(site, 'filename', '')}:{getattr(site, 'line', 0)}",
        )
    return body_ctx


def _module_source_for_site(site: SourceFragment, ctx) -> tuple[str, str] | None:
    """Return the preserved defining source for a qualified install-source def.

    Module bindings belong only to FunctionDefs carrying the complete provenance
    installed-source discovery stamps. Reading another file by leaf name would
    permit two distinct modules to cross-bind; importing it would execute source.
    The preserved source text is therefore the sole construction input.
    """
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
        and isinstance(bridge_name, str)
        and "." in bridge_name
        and bridge_name.rsplit(".", 1)[-1] == site.function_name()
    ):
        return None
    return sugar_source, sugar_file


def _names_in_fragment(site: SourceFragment) -> list[str]:
    """Collect bare Name identifiers under ``site`` (free + bound uses).

    Bare-name callees are free names the body demands — exception constructors
    such as ``raise OpError(...)`` load ``OpError`` at the call target, not
    only in arguments. Method receivers stay via ``call_receiver()``; attribute
    tails are not free names.
    """
    if site.observed == "Name":
        return [site.name_id()]
    if site.observed == "Call":
        names: list[str] = []
        receiver = site.call_receiver()
        if receiver is not None:
            names.extend(_names_in_fragment(receiver))
        else:
            # Plain ``Name(...)`` callee: the target is a free load.
            target = site.call_target_name()
            if target is not None:
                names.append(target)
        for arg in site.call_args():
            names.extend(_names_in_fragment(arg))
        for keyword in site.call_keywords():
            names.extend(_names_in_fragment(keyword.keyword_value()))
        return names
    if site.observed == "Attribute":
        return _names_in_fragment(site.attr_receiver())
    if site.observed == "keyword":
        return _names_in_fragment(site.keyword_value())
    names = []
    for child in site.fragments():
        names.extend(_names_in_fragment(child))
    return names


def _module_level_declarations_before(
    root: SourceFragment, fn: SourceFragment
) -> list[SourceFragment]:
    """Supported top-level declarations at the function's module coordinate."""
    declarations: list[SourceFragment] = []
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
            # Installed modules finish executing before an imported function can
            # be called. A function may therefore lawfully load a top-level class
            # declared later in source order. Keep only ClassDefs here; selection
            # below still filters them by the body's actually loaded names.
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
        elif statement.observed in ("Import", "ImportFrom"):
            declarations.append(statement)
        elif statement.observed == "Try":
            # Optional imports and try/except/else name joins (e.g. requests/help).
            declarations.append(statement)
        elif statement.observed == "ClassDef":
            # An installed module has executed its earlier class declarations
            # before an imported function can run. Eligibility remains exact in
            # _module_declaration_bound_names: dynamic bases, metaclasses, and
            # class-replacing decorators bind nothing and therefore stay loud.
            declarations.append(statement)
    # Never attach declarations when the preserved tree does not contain this
    # exact function coordinate: that is stale or mismatched provenance.
    return []


def _class_decorators_preserve_identity(statement: SourceFragment) -> bool:
    """Recognize source contracts whose decorator result is exactly the class.

    pandas ``set_module`` and ``inherit_names`` mutate class metadata/methods
    and return the same class object. That identity is sufficient for a later
    function to name the executed module class; arbitrary decorators may
    replace the class and therefore remain unbound.
    """
    identity_exports = {
        ("pandas.core.indexes.extension", "inherit_names"),
        ("pandas.util._decorators", "set_module"),
        ("pandas.api.extensions", "register_dataframe_accessor"),
        ("pandas.api.extensions", "register_index_accessor"),
        ("pandas.api.extensions", "register_series_accessor"),
    }
    try:
        root = SourceFragment.from_source(statement.source, statement.filename or "")
    except (SyntaxError, TypeError):
        return False
    authenticated_names: set[str] = set()
    authenticated_modules: dict[str, str] = {}
    declarations = [
        declaration
        for fragment in root.fragments()
        for declaration in fragment.statements()
    ]
    for declaration in declarations:
        if declaration.observed == "ImportFrom":
            module = declaration.importfrom_module()
            for imported, alias in declaration.importfrom_names():
                if (module, imported) in identity_exports:
                    authenticated_names.add(alias or imported)
        elif declaration.observed == "Import":
            for imported, alias in declaration.import_names():
                authenticated_modules[alias or imported.split(".", 1)[0]] = imported
    for decorator in statement.class_decorators():
        if decorator.observed == "Name":
            receiver = decorator
        elif decorator.observed == "Call":
            receiver = decorator.call_func()
        else:
            return False
        if receiver is None:
            return False
        dotted = receiver.dotted_expr_name()
        if dotted in authenticated_names:
            continue
        if dotted is None:
            return False
        head, separator, tail = dotted.partition(".")
        module = authenticated_modules.get(head)
        if not separator or module is None:
            return False
        qualified = f"{module}.{tail}"
        export_module, _, export_name = qualified.rpartition(".")
        if (export_module, export_name) not in identity_exports:
            return False
    return True


def _module_declaration_bound_names(statement: SourceFragment) -> set[str]:
    """Names a static module declaration adds to its lexical frame."""
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
        return _try_module_bound_names(statement)
    if statement.observed == "ClassDef":
        base_names = statement.class_base_names()
        if (
            not _class_decorators_preserve_identity(statement)
            or statement.class_keywords()
            or any(base_name is None for base_name in base_names)
        ):
            return set()
        return {statement.class_name()}
    return set()


def _try_module_bound_names(statement: SourceFragment) -> set[str]:
    """Names a module-level Try may join into the continuing lexical frame."""
    names: set[str] = set()
    suites: list[SourceFragment] = [statement.try_body()]
    for handler in statement.try_handlers():
        suites.append(handler.except_handler_body())
    orelse = statement.try_orelse()
    if orelse is not None:
        suites.append(orelse)
    for suite in suites:
        for child in suite.statements():
            names.update(_module_declaration_bound_names(child))
    return names


def _ctx_with_module_global_binds(site: SourceFragment, ctx):
    """Construct only needed globals from a qualified def's preserved module AST.

    Supported simple assignments and import aliases are selected backwards from
    the function's module coordinate, then constructed forwards. Unsupported
    declarations are not fabricated: their names remain absent so ordinary
    TemporalContext lookup stays loud when the body demands them.
    """
    from sugar_lift_py_tests.floor import BlockValue, ImportAliasValue
    from sugar_lift_py_tests.floor.local_exception_class_value import (
        module_class_value,
    )
    from sugar_lift_py_tests.outcome import Incomplete, complete_value

    loaded = _module_source_for_site(site, ctx)
    if loaded is None:
        return ctx
    source, filename = loaded
    try:
        root = SourceFragment.from_source(source, filename)
    except SyntaxError:
        return ctx

    declarations = _module_level_declarations_before(root, site)
    if not declarations:
        return ctx

    needed: set[str] = set()
    for body_stmt in site.function_body():
        needed.update(_names_in_fragment(body_stmt))
    needed -= set(site.function_params())
    if not needed:
        return ctx

    selected: list[SourceFragment] = []
    needed_work = set(needed)
    for prior in reversed(declarations):
        owned = _module_declaration_bound_names(prior)
        wanted = owned & needed_work
        if not wanted:
            continue
        selected.append(prior)
        needed_work.difference_update(wanted)
        if prior.observed == "Assign":
            needed_work.update(_names_in_fragment(prior.assign_value()))
        elif prior.observed == "AnnAssign":
            value = prior.annassign_value()
            if value is not None:
                needed_work.update(_names_in_fragment(value))
        elif prior.observed == "Try":
            # The statement catalog selected this Try because one of its
            # continuing paths binds a name demanded by the function. Complete
            # that selection from the Try's own source-fragment testimony:
            # earlier declarations it loads must be replayed before TrySugar.
            # The reverse one-pass walk deliberately cannot select a dependency
            # declared after the Try, preserving module execution order.
            needed_work.update(_names_in_fragment(prior))
    selected.reverse()

    folded_ctx = ctx
    for prior in selected:
        if prior.observed == "Import":
            temporal = folded_ctx.temporal
            for imported, alias in prior.import_names():
                bound = alias or imported.split(".", 1)[0]
                target = imported if alias else imported.split(".", 1)[0]
                temporal = temporal.bind_value(
                    bound,
                    ImportAliasValue(
                        imported,
                        bound,
                        import_target=target,
                    ),
                )
            folded_ctx = folded_ctx.with_temporal(temporal)
            continue
        if prior.observed == "ImportFrom":
            module = prior.importfrom_module()
            if prior.importfrom_level() or not module:
                continue
            temporal = folded_ctx.temporal
            for imported, alias in prior.importfrom_names():
                if imported == "*":
                    continue
                bound = alias or imported
                target = f"{module}.{imported}"
                from sugar_lift_py_tests.sugar.install_source_dig import (
                    resolve_install_source_value,
                )

                resolved = resolve_install_source_value(target, folded_ctx)
                temporal = temporal.bind_value(
                    bound,
                    ImportAliasValue(
                        target,
                        bound,
                        import_target=target,
                        resolved_value=resolved,
                        install_source_checked=True,
                    ),
                )
            folded_ctx = folded_ctx.with_temporal(temporal)
            continue
        if prior.observed == "ClassDef":
            name = prior.class_name()
            base_names = tuple(
                base_name
                for base_name in prior.class_base_names()
                if base_name is not None
            )
            value = module_class_value(
                name=name,
                base_names=base_names,
                temporal=folded_ctx.temporal,
                record=BlockValue(()),
            )
            folded_ctx = folded_ctx.with_temporal(
                folded_ctx.temporal.bind_value(name, value)
            )
            continue
        # #4203: no soft TypeError/Exception continue past construction. A missing
        # shape is Incomplete (leave name unbound) or FactoryPanic (loud). Soft
        # continues laundered construction bugs into absent globals.
        outcome = folded_ctx.build_body(prior, SugarRole.STATEMENT).reduce(folded_ctx)
        if isinstance(outcome, Incomplete):
            continue
        complete_value(outcome, owner="sugar_constructors.module_global_binds")
        folded_ctx = outcome.extend_scope(folded_ctx)
    return folded_ctx


def build_bridge_body(site: SourceFragment, ctx):
    body_frags = site.function_body()
    if len(body_frags) == 1:
        body_frag = body_frags[0]
        if body_frag.observed == "Return" and body_frag.return_value() is not None:
            # Same formal binds as build_control_flow_body_sugar — required so
            # method-on-formal returns mint MethodCallStrategy (call:mean(s)),
            # not call-method:mean FactoryGap on the force_floor / bridge path.
            return _ctx_with_formal_binds(site, ctx).build_body(
                body_frag.return_value(), SugarRole.TERM
            )
    return build_control_flow_body_sugar(site, ctx)
