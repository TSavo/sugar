from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, NoReturn

from sugar_lift_py_tests.factory.array_map_report import (
    _callsite_string,
    _function_source_memento,
    _source_ledger,
    _statement_source_memento,
)
from sugar_lift_py_tests.canonicalizer import encode_jcs
from sugar_lift_py_tests.claim import SugarCatalog, SugarRole
from sugar_lift_py_tests.ir import (
    Formula,
    Term,
    _Atomic,
    _Connective,
    _Quantifier,
    and_,
    ctor,
    eq,
    formula_to_value,
)
from sugar_lift_py_tests.kit_rpc import (
    BodyUniverseDto,
    FactoryWalkRowDto,
    LiftReportPayloadDto,
    SourceMementoDto,
    SourceSpanDto,
)
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar.floor_terms import floor_to_term
from sugar_lift_py_tests.proofir import (
    ConstructionSite,
    Derived,
    EqualityFact,
    Provenance,
    Stated,
    merge_equality_facts,
)

from .dig_refusal import DigRefusal
from .floor_contract_agreement import (
    FloorContractAgreementViolation,
    enforce_floor_contract_agreement_gate,
    floor_contract_agreement_diagnostic,
    floor_contract_agreement_violations_for_fact,
)
from .proofir_provenance_diagnostic import proofir_formula_provenance_diagnostic
from .factory_build_context import FactoryBuildContext
from .source_fragment import SourceFragment


def _canonical_term_sig(term) -> str:
    """Deterministic canonical signature for a Term, argument-keying the callsite
    contract base so mint coalesces cross-location assertions about the SAME
    (callee, args) into one ``::assertion`` inv. Structural, hash-stable: same
    structure -> same string -> same base -> mint conjoins -> contradiction fires."""
    from sugar_lift_py_tests.ir import (
        _ConstBool,
        _ConstInt,
        _ConstReal,
        _ConstStr,
        _Ctor,
        _Var,
    )

    if isinstance(term, _Var):
        return f"v:{term.name}"
    if isinstance(term, _ConstInt):
        return f"i:{term.value}"
    if isinstance(term, _ConstStr):
        return f"s:{term.value!r}"
    if isinstance(term, _ConstBool):
        return f"b:{term.value}"
    if isinstance(term, _ConstReal):
        return f"r:{term.value}"
    if isinstance(term, _Ctor):
        inner = ",".join(_canonical_term_sig(a) for a in term.args)
        return f"c:{term.name}({inner})"
    return f"?:{term!r}"


def euf_call_term(callee_name: str, arg_terms):
    """The EUF callsite term for ``callee(args)`` -- an uninterpreted ``call:<callee>``
    ctor over the argument terms. The SINGLE constructor of the bridge term, so every
    callsite of the same callee+args builds the byte-identical term that mint coalesces.
    """
    return ctor(f"call:{callee_name}", arg_terms)


def euf_callsite_name(callee_name: str, euf_term, *, suffix: str) -> str:
    """The ONE canonical ``#euf#`` contract name -- the single speller of the join key.

    ``suffix`` is ``"::assertion"`` (the sworn fact about a concrete call, keyed on its
    concrete arg terms) or ``"::universe"`` (the dig: ``f(args)``, the function over its
    formals, keyed on the callee). Byte-canonical by construction: cross-location facts
    coalesce ONLY by exact name match, so one speller is soundness, not style -- a single
    drifted byte sends a fact into a different universe and the contradiction is never
    computed (a green proof that lies)."""
    return f"{callee_name}#euf#{_canonical_term_sig(euf_term)}{suffix}"


# One lift, returned as five parallel lists: (contracts, source_mementos,
# source_audits, factory_walk_rows, call_edges).
LiftResult = tuple[
    list[Any],
    list[SourceMementoDto],
    list[dict[str, Any]],
    list[FactoryWalkRowDto],
    list[dict[str, Any]],
]


@dataclass(frozen=True)
class SourceReportBuild:
    payload: LiftReportPayloadDto


@dataclass(frozen=True)
class EqualityFactEmission:
    fact: EqualityFact
    source_warrants: tuple[SourceMementoDto, ...]


def _resolver_nodes(
    functions_by_name: dict[str, SourceFragment],
    classes_by_name: dict[str, SourceFragment],
) -> dict[str, Any]:
    return {
        **{name: frag.node for name, frag in functions_by_name.items()},
        **{name: frag.node for name, frag in classes_by_name.items()},
    }


def _is_free_var_definition(formula_value: dict[str, Any], bound: set[str]) -> bool:
    """An `eq(var, _)` whose var is neither a formal nor `out` -- a free-variable
    definition that would leave an exported universe post OPEN, so the verifier's
    `linked_ambient_post_instances_for_inv` skips it. The str.eq-bv-blocks relation
    carries the alphabet as a constant payload, so dropping the definition is safe."""
    if not isinstance(formula_value, dict) or formula_value.get("name") != "=":
        return False
    args = formula_value.get("args")
    if not isinstance(args, list) or len(args) != 2 or not isinstance(args[0], dict):
        return False
    return args[0].get("kind") == "var" and args[0].get("name") not in bound


def build_literal_call_report(
    *,
    source: str,
    filename: str,
    memento_file: str | None = None,
    contract_bindings: list | None = None,
) -> SourceReportBuild | None:
    root_frag = SourceFragment.from_source(source, filename)
    lines = source.splitlines(keepends=True)
    rel_file = memento_file or filename
    contracts: list[Any] = []
    source_mementos: list[SourceMementoDto] = []
    source_audits: list[dict[str, Any]] = []
    factory_walk: list[FactoryWalkRowDto] = []
    call_edges: list[dict[str, Any]] = []
    dig_refusals: list[DigRefusal] = []
    agreement_violations: list[FloorContractAgreementViolation] = []
    local_functions = {
        frag.function_name(): frag
        for frag in root_frag.walk()
        if frag.observed == "FunctionDef"
    }
    local_classes = {
        frag.class_name(): frag
        for frag in root_frag.walk()
        if frag.observed == "ClassDef"
    }
    import_aliases, from_imports = _import_bindings(root_frag)
    module_statements = _module_statements(root_frag)
    # IMPORT SUGAR: a callee reached through `import numpy as np` / `from mod import f`
    # is not local, so the dig cannot see its body. Resolve each imported callee to
    # its installed source FunctionDef so the SAME dig walks it like a local function.
    # Locals win on name collision; the assert-iteration below stays local-only.
    dig_functions = {
        **_resolve_imported_callees(
            root_frag, import_aliases, from_imports, dig_refusals=dig_refusals
        ),
        **local_functions,
    }
    for fn in local_functions.values():
        for stmt in fn.function_body():
            if stmt.observed != "Assert":
                continue
            lifted = _lift_assert(
                stmt,
                fn=fn,
                filename=filename,
                memento_file=rel_file,
                source_lines=lines,
                functions_by_name=dig_functions,
                classes_by_name=local_classes,
                import_aliases=import_aliases,
                from_imports=from_imports,
                contract_bindings=contract_bindings or [],
                module_statements=module_statements,
                dig_refusals=dig_refusals,
                agreement_violations=agreement_violations,
            )
            # _lift_assert never returns None now: it lifts the assert or PANICS
            # (FactoryGap). A silent skip here would be the cardinal crime.
            lifted_contracts, mementos, audits, rows, edges = lifted
            contracts = _merge_contract_rows([*contracts, *lifted_contracts])
            source_mementos.extend(mementos)
            source_audits.extend(audits)
            factory_walk.extend(rows)
            call_edges.extend(edges)
    if not contracts:
        return None
    materialized_contracts = _materialize_contract_rows(contracts)
    enforce_floor_contract_agreement_gate(agreement_violations)
    ir_payload: list[BodyUniverseDto | dict[str, Any]] = []
    ir_payload.extend(materialized_contracts)
    memento_payload: list[SourceMementoDto | dict[str, Any]] = []
    memento_payload.extend(source_mementos)
    walk_payload: list[FactoryWalkRowDto | dict[str, Any]] = []
    walk_payload.extend(factory_walk)
    return SourceReportBuild(
        LiftReportPayloadDto(
            ir=ir_payload,
            source_mementos=memento_payload,
            source_ledger=_source_ledger(len(source_audits)),
            source_audits=source_audits,
            factory_walk=walk_payload,
            call_edges=call_edges,
            diagnostics=[
                *[refusal.to_json() for refusal in dig_refusals],
                floor_contract_agreement_diagnostic(agreement_violations),
                proofir_formula_provenance_diagnostic(
                    materialized_contracts, factory_walk
                ),
            ],
        )
    )


def _resolve_bound_lhs(lhs, fn):
    """LHS-as-term, syntactically: a Name bound to a CALL recomposes to that call, so
    ``x = y(5); assert x == 9`` lifts IDENTICALLY to ``assert y(5) == 9`` -- the binding is
    transparent and the bridge falls out wherever the call appears (the same dance, the
    binding just different clothes). Only a call RHS substitutes; a non-call binding leaves
    the Name as-is (which panics as before -- only ``call(...) == literal`` is covered).
    """
    if lhs.observed != "Name":
        return lhs
    name = lhs.name_id()
    for stmt in fn.function_body():
        if stmt.observed == "Assign" and stmt.assign_target_name() == name:
            rhs = stmt.assign_value()
            if rhs.observed == "Call":
                return rhs
    return lhs


def _non_call_equality_lhs_gap(
    lhs: SourceFragment, *, fn: SourceFragment, stmt: SourceFragment
) -> tuple[str, str, str]:
    if lhs.observed == "Name":
        name = lhs.name_id()
        for prior in _prior_assignment_sites([], fn, stmt):
            if name in _assignment_target_names(prior):
                return (
                    f"assert-eq-lhs:bound-name:{name}",
                    "BoundNameEquality",
                    (
                        f"lift bound-name equality for `{name}`: reduce a proven-pure "
                        "binding, dig its assignment/mutation history, or emit a "
                        "stateful effect"
                    ),
                )
    return (
        f"assert-eq-lhs:{lhs.observed}",
        "CallsiteEquality",
        "lift `<lhs> == literal` where the lhs is not a call",
    )


def _lift_assert(
    stmt: SourceFragment,
    *,
    fn: SourceFragment,
    filename: str,
    memento_file: str,
    source_lines: list[str],
    functions_by_name: dict[str, SourceFragment],
    classes_by_name: dict[str, SourceFragment],
    import_aliases: dict[str, str],
    from_imports: dict[str, tuple[str, str]],
    contract_bindings: list,
    module_statements: list[SourceFragment],
    dig_refusals: list[DigRefusal],
    agreement_violations: list[FloorContractAgreementViolation],
) -> LiftResult:
    """One mechanism. An assertion `callee(args) == expected` is a fact -- a debt on
    `callee` -- and it WARRANTS a dig for `callee`'s contract.

    1. THE FACT (always): the assertion mints the euf callsite obligation
       `eq(call:callee(args), expected)`.
    2. THE DIG (warranted by the fact): resolve `callee`'s contract.
       - source present (`callee in functions_by_name`) -> the dig CONTINUES into the
         body, desugars it, and mints the universe post -- the same dig that warranted
         it discharges the fact.
       - source absent -> an imported `.proof` already SUPPLIES the contract (a memoized
         dig); the dig stops on that cache hit and we mint nothing here.

    Either way the verifier's ambient-post specialization joins the post (local or
    imported) to the fact and z3 decides `and(universe, fact)`."""
    assertion_sugar = _lift_assertion_via_factory(
        stmt,
        fn=fn,
        filename=filename,
        memento_file=memento_file,
        source_lines=source_lines,
        functions_by_name=functions_by_name,
        classes_by_name=classes_by_name,
        import_aliases=import_aliases,
        from_imports=from_imports,
        contract_bindings=contract_bindings,
        module_statements=module_statements,
    )
    if assertion_sugar is not None:
        return assertion_sugar

    comparison = stmt.assert_test()
    if comparison.observed != "Compare" or len(comparison.compare_ops()) != 1:
        _panic_no_sugar(
            stmt,
            memento_file,
            observed=f"assert-test:{comparison.observed}",
            requested="EqualityAssertion",
            fix="lift this assertion shape (only `call(...) == literal` is covered)",
        )
    if (
        comparison.compare_ops()[0] != "Eq"
        or len(comparison.compare_comparators()) != 1
    ):
        _panic_no_sugar(
            stmt,
            memento_file,
            observed=f"assert-compare-op:{comparison.compare_ops()[0]}",
            requested="EqualityAssertion",
            fix="lift non-`==` comparison assertions",
        )
    comparison_left = _resolve_bound_lhs(comparison.compare_left(), fn)
    callee_name = _callee_name(comparison_left, import_aliases, from_imports)
    if callee_name is None:
        observed, requested, fix = _non_call_equality_lhs_gap(
            comparison_left, fn=fn, stmt=stmt
        )
        _panic_no_sugar(
            comparison_left,
            memento_file,
            observed=observed,
            requested=requested,
            fix=fix,
        )

    # _lift_callsite_assertion lifts or PANICS; it never returns None.
    assertion = _lift_callsite_assertion(
        stmt,
        comparison=comparison,
        callee_name=callee_name,
        callsite=comparison_left,
        fn=fn,
        filename=filename,
        memento_file=memento_file,
        source_lines=source_lines,
        ctx=_assertion_factory_ctx(
            stmt=stmt,
            fn=fn,
            filename=filename,
            functions_by_name=functions_by_name,
            classes_by_name=classes_by_name,
            import_aliases=import_aliases,
            from_imports=from_imports,
            contract_bindings=contract_bindings,
            module_statements=module_statements,
        ),
    )

    universe: LiftResult | None = None
    if callee_name in functions_by_name:
        # Build the callsite through the factory and then ask the factory term for the floor.
        # The consumer reads the CallSiteValue/force_floor/project_callsite_with spine directly.
        universe = _construct_callsite_from_factory_term(
            stmt,
            comparison_left,
            callee_name,
            fn,
            functions_by_name,
            classes_by_name,
            filename=filename,
            memento_file=memento_file,
            source_lines=source_lines,
            dig_refusals=dig_refusals,
            agreement_violations=agreement_violations,
        )
    return _merge_lifts(universe, assertion)


def _lift_assertion_via_factory(
    stmt: SourceFragment,
    *,
    fn: SourceFragment,
    filename: str,
    memento_file: str,
    source_lines: list[str],
    functions_by_name: dict[str, SourceFragment],
    classes_by_name: dict[str, SourceFragment],
    import_aliases: dict[str, str],
    from_imports: dict[str, tuple[str, str]],
    contract_bindings: list,
    module_statements: list[SourceFragment],
) -> LiftResult | None:
    from .build import build_node, default_catalog

    catalog = default_catalog()
    external_bridge_sink: list[dict[str, Any]] = []
    ctx = _assertion_factory_ctx(
        stmt=stmt,
        fn=fn,
        filename=filename,
        functions_by_name=functions_by_name,
        classes_by_name=classes_by_name,
        import_aliases=import_aliases,
        from_imports=from_imports,
        contract_bindings=contract_bindings,
        module_statements=module_statements,
        external_bridge_sink=external_bridge_sink,
    )
    if _is_simple_bound_name_equality(
        stmt, _prior_assignment_names(module_statements, fn, stmt)
    ):
        return None
    if _comparison_assertion_uses_nonfree_name(
        stmt,
        fn,
        import_aliases=import_aliases,
        from_imports=from_imports,
        extra_safe_names=_temporal_binding_names(ctx),
    ):
        catalog = SugarCatalog(
            [
                claim
                for claim in catalog.claims
                if claim.name
                not in {
                    "ChainedComparisonAssertionSugar",
                    "ComparisonAssertionSugar",
                }
            ]
        )
        ctx = replace(ctx, catalog=catalog)
    candidates = catalog.candidates_for(SugarRole.ASSERTION, stmt)
    if not candidates:
        return None
    result = build_node(
        stmt,
        filename=filename,
        role=SugarRole.ASSERTION,
        catalog=catalog,
        ctx=ctx,
    )
    formula = result.sugar.desugar(ctx)
    source_role = getattr(
        result.sugar,
        "source_role",
        f"python.{type(result.sugar).__name__}",
    )
    lifted = _emit_assertion_surface_fact(
        stmt,
        fn,
        formula,
        selected=result.audit_row.selected or type(result.sugar).__name__,
        role=source_role,
        filename=filename,
        memento_file=memento_file,
        source_lines=source_lines,
        reason=getattr(result.sugar, "degraded_reason", None),
    )
    if external_bridge_sink:
        edges = _external_bridge_edges(
            external_bridge_sink,
            source_contract=lifted[0][0].name,
            memento_file=memento_file,
            contract_bindings=contract_bindings,
        )
        lifted = (lifted[0], lifted[1], lifted[2], lifted[3], [*lifted[4], *edges])
    return lifted


def _assertion_factory_ctx(
    *,
    stmt: SourceFragment,
    fn: SourceFragment,
    filename: str,
    functions_by_name: dict[str, SourceFragment],
    classes_by_name: dict[str, SourceFragment],
    import_aliases: dict[str, str],
    from_imports: dict[str, tuple[str, str]],
    contract_bindings: list,
    module_statements: list[SourceFragment],
    external_bridge_sink: list[dict[str, Any]] | None = None,
) -> FactoryBuildContext:
    from .build import default_catalog

    ctx = FactoryBuildContext(
        filename=filename,
        catalog=default_catalog(),
        name_resolver=_resolver_nodes(functions_by_name, classes_by_name),
        import_aliases=import_aliases,
        from_imports=from_imports,
        contract_bindings=contract_bindings,
        external_bridge_sink=external_bridge_sink,
    )
    ctx = _ctx_with_function_params(fn, ctx)
    return _ctx_with_prior_assignments(module_statements, fn, stmt, ctx)


def _ctx_with_function_params(
    fn: SourceFragment, ctx: FactoryBuildContext
) -> FactoryBuildContext:
    from sugar_lift_py_tests.floor import SymbolicValue
    from sugar_lift_py_tests.ir import make_var
    from sugar_lift_py_tests.temporal import bind_temporal

    for param_name in fn.function_params():
        ctx = bind_temporal(
            ctx,
            param_name,
            SymbolicValue(make_var(param_name)),
            owner="literal_call_report.function_params",
            blame=fn.blame,
        )
    return ctx


def _ctx_with_prior_assignments(
    module_statements: list[SourceFragment],
    fn: SourceFragment,
    stmt: SourceFragment,
    ctx: FactoryBuildContext,
) -> FactoryBuildContext:
    from sugar_lift_py_tests.sugar.block_sugar import BlockSugar

    priors = _needed_prior_assignment_sites(module_statements, fn, stmt)
    if not priors:
        return ctx
    block = BlockSugar(
        statements=tuple(
            ctx.build_body(prior, SugarRole.STATEMENT) for prior in priors
        ),
        blame=stmt.blame,
    )
    folded = block.fold_with_context(ctx)
    complete_value(folded.outcome, owner="literal_call_report.prior_assignment_block")
    return folded.ctx


def _needed_prior_assignment_sites(
    module_statements: list[SourceFragment],
    fn: SourceFragment,
    stmt: SourceFragment,
) -> list[SourceFragment]:
    needed_names = set(_names_including_self(stmt))
    selected: list[SourceFragment] = []
    for prior in reversed(_prior_assignment_sites(module_statements, fn, stmt)):
        names = _assignment_target_names(prior)
        if not names or needed_names.isdisjoint(names):
            continue
        selected.append(prior)
        needed_names.update(_assignment_value_names(prior))
    return list(reversed(selected))


def _assignment_value_names(site: SourceFragment) -> set[str]:
    if site.observed != "Assign":
        return set()
    return set(_names_including_self(site.assign_value()))


def _assignment_target_names(site: SourceFragment) -> set[str]:
    if site.observed != "Assign":
        return set()
    name = site.assign_target_name()
    if name is not None:
        return {name}
    targets = site.assign_targets()
    if len(targets) == 1 and targets[0].observed == "Tuple":
        return {
            item.name_id() for item in targets[0].terms() if item.observed == "Name"
        }
    return set()


def _prior_assignment_names(
    module_statements: list[SourceFragment],
    fn: SourceFragment,
    stmt: SourceFragment,
) -> set[str]:
    names: set[str] = set()
    for prior in _prior_assignment_sites(module_statements, fn, stmt):
        names.update(_assignment_target_names(prior))
    return names


def _prior_assignment_sites(
    module_statements: list[SourceFragment],
    fn: SourceFragment,
    stmt: SourceFragment,
) -> list[SourceFragment]:
    priors: list[SourceFragment] = []
    for prior in module_statements:
        if prior.line == fn.line and prior.col == fn.col:
            break
        priors.append(prior)
    for prior in fn.function_body():
        if prior.line == stmt.line and prior.col == stmt.col:
            break
        priors.append(prior)
    return priors


def _temporal_binding_names(ctx: FactoryBuildContext) -> set[str]:
    return {binding.name for binding in ctx.temporal.bindings}


def _is_simple_bound_name_equality(stmt: SourceFragment, bound_names: set[str]) -> bool:
    if stmt.observed != "Assert":
        return False
    test = stmt.assert_test()
    if test.observed != "Compare":
        return False
    if test.compare_ops() != ["Eq"] or len(test.compare_comparators()) != 1:
        return False
    left = test.compare_left()
    return left.observed == "Name" and left.name_id() in bound_names


def _comparison_assertion_uses_nonfree_name(
    stmt: SourceFragment,
    fn: SourceFragment,
    *,
    import_aliases: dict[str, str],
    from_imports: dict[str, tuple[str, str]],
    extra_safe_names: set[str] | None = None,
) -> bool:
    if stmt.observed != "Assert":
        return False
    test = stmt.assert_test()
    if test.observed != "Compare":
        return False
    operators = test.compare_ops()
    comparators = test.compare_comparators()
    if not operators or len(operators) != len(comparators):
        return False
    if operators != ["Eq"]:
        return False
    if any(
        operator not in {"Eq", "NotEq", "Lt", "LtE", "Gt", "GtE"}
        for operator in operators
    ):
        return False
    safe_names = (
        set(fn.function_params())
        | set(import_aliases)
        | set(from_imports)
        | set(extra_safe_names or set())
    )
    for operand in (test.compare_left(), *comparators):
        for name in _names_including_self(operand):
            if name not in safe_names:
                return True
    return False


def _names_including_self(site: SourceFragment) -> list[str]:
    if site.observed == "Name":
        return [site.name_id()]
    if site.observed == "Call":
        names: list[str] = []
        receiver = site.call_receiver()
        if receiver is not None:
            names.extend(_names_including_self(receiver))
        for arg in site.call_args():
            names.extend(_names_including_self(arg))
        for keyword in site.call_keywords():
            names.extend(_names_including_self(keyword.keyword_value()))
        return names
    if site.observed == "Attribute":
        return _names_including_self(site.attr_receiver())
    if site.observed == "keyword":
        return _names_including_self(site.keyword_value())

    names: list[str] = []
    for child in site.fragments():
        names.extend(_names_including_self(child))
    return names


def _lift_literal_via_factory(
    frag: SourceFragment, filename: str, *, ctx: FactoryBuildContext | None = None
) -> Term:
    """Lift a literal operand of a callsite equality THROUGH THE FACTORY: the
    catalog's literal sugars (PrimitiveLiteral, ...) build and reduce it, and an
    unhandled shape panics via the catalog's own mouth. No special-casing per type."""
    from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
    from sugar_lift_py_tests.claim import SugarRole as _Role

    from .build import default_catalog

    ctx = ctx or FactoryBuildContext(filename=filename, catalog=default_catalog())
    body = ctx.build_body(frag, _Role.TERM)
    return floor_to_term(
        complete_value(body.reduce(ctx), owner="callsite literal"),
        owner="literal_call_report",
    )


def _lift_callsite_assertion(
    stmt: SourceFragment,
    *,
    comparison: SourceFragment,
    callee_name: str,
    callsite: SourceFragment,
    fn: SourceFragment,
    filename: str,
    memento_file: str,
    source_lines: list[str],
    ctx: FactoryBuildContext | None = None,
) -> LiftResult:
    """The fact. `callee(args) == expected` lifts to the euf callsite obligation
    `eq(call:callee(args), expected)`, contract-named `callee#euf#<arg_sig>::assertion`.
    `call:<callee>` is the callsite-ctor head the verifier recognizes
    (`is_callsite_ctor_term` requires the `call:` prefix) and the head the universe
    post specializes onto. Only concrete-literal args take this path; a symbolic arg
    returns None."""
    # The expected value composes through the factory's literal sugars (string,
    # int, ...). Anything the catalog can't build panics via its own mouth, which
    # names the next sugar -- no string-only special case here.
    expected_term = _lift_literal_via_factory(
        comparison.compare_comparators()[0], filename, ctx=ctx
    )
    # Each arg composes through the factory's literal sugars (string, int, array,
    # ...) -- the same path as the expected. A literal the catalog reduces but can't
    # yet shape into a term (e.g. a nested array) is turned into a clean mouth-panic
    # naming the next sugar, not a crash.
    arg_terms = []
    for arg_frag in callsite.call_args():
        try:
            arg_terms.append(_lift_literal_via_factory(arg_frag, filename, ctx=ctx))
        except TypeError as exc:
            _panic_no_sugar(
                arg_frag,
                memento_file,
                observed=f"callsite-arg:{arg_frag.observed}-unliftable",
                requested="LiftableCallArg",
                fix=(
                    "lift this call-arg shape (e.g. nested arrays, mixed-type "
                    f"lists): {exc}"
                ),
            )
    return _emit_euf_fact(
        stmt,
        fn,
        callee_name,
        arg_terms,
        expected_term,
        filename=filename,
        memento_file=memento_file,
        source_lines=source_lines,
        warrant=Stated(locus=_proofir_construction_site(stmt, memento_file)),
    )


def _emit_euf_fact(
    stmt: SourceFragment,
    fn: SourceFragment,
    callee_name: str,
    arg_terms,
    value_term,
    *,
    filename: str,
    memento_file: str,
    source_lines: list[str],
    warrant: Stated | Derived,
) -> LiftResult:
    """Emit one `<callee>#euf#<args>::assertion` fact: `eq(call:callee(args), value)`.

    The SINGLE emitter for both the sworn facts in play: the VENDOR's stated value (the
    assertion RHS) and the value WE construct by slamming the callee's body to the floor.
    Both land under the same #euf# key, so they conjoin -- agreement discharges, disagreement
    is UNSAT. One emitter means the key is spelled once: a vendor lie and a Python truth meet
    on the same name or they never meet at all."""
    from sugar_lift_py_tests.proofir import (
        CallTerm,
        canonical_euf_callsite_name,
        term_from_ir,
    )

    rhs_term = term_from_ir(value_term)
    call_term = CallTerm(
        callee_name,
        tuple(term_from_ir(arg_term) for arg_term in arg_terms),
        sort=rhs_term.sort,
    )
    contract_name = canonical_euf_callsite_name(call_term, suffix="::assertion")
    memento = _statement_source_memento(
        stmt,
        fn,
        memento_file,
        source_lines,
        contract_name=contract_name,
        role="python.literal-call-sugar",
    )
    member = EqualityFact(
        call_term=call_term,
        rhs_term=rhs_term,
        provenance=Provenance(
            node_class=EqualityFact.node_class,
            construction_site=_proofir_construction_site(stmt, memento_file),
            warrant=warrant,
        ),
    )
    _require_proofir_emission_node(
        member,
        construction_site=(
            f"_emit_euf_fact:{memento.role or 'unknown-sugar'}:{contract_name}"
        ),
        replacement="EqualityFact",
    )
    inv = _body_universe_from_declaration(member.to_declaration()).inv
    walk = _walk_row(
        "CallSugar",
        "Call",
        stmt,
        filename,
        memento,
        "predicate",
        requested_role="AssertionSurface",
        emitted_formula=inv,
    )
    audit = _source_audit(
        fn,
        stmt,
        memento_file,
        contract_name,
        memento,
        role="python.literal-call-sugar",
        ast_kind="Assert",
    )
    return ([EqualityFactEmission(member, (memento,))], [memento], [audit], [walk], [])


def _require_proofir_emission_node(
    value: object,
    *,
    construction_site: str,
    replacement: str,
):
    """ProofIR Slice 3 return-type seam: raw formula rows must become nodes."""
    from sugar_lift_py_tests.factory import FactoryAuditRow, FactoryGap, FactoryGapInfo
    from sugar_lift_py_tests.proofir import ProofIRNode

    if isinstance(value, ProofIRNode):
        return value

    if isinstance(value, dict):
        observed = "raw dict emission"
    elif isinstance(value, str):
        observed = "raw str emission"
    else:
        observed = f"raw {type(value).__name__} emission"
    info = FactoryGapInfo(
        owner="python.proofir.return-type-frontier",
        blame=construction_site,
        observed=observed,
        requested=f"ProofIRNode ({replacement})",
        fix=(
            f"construct {replacement} at the emission site; raw dict/str "
            "emission is retired by #3234"
        ),
        gap_kind="ProofIR",
        gap_locus="Emission",
    )
    raise FactoryGap(
        info,
        FactoryAuditRow(
            role="ProofIRNode",
            status="proofir-return-type-gap",
            observed=observed,
            blame=construction_site,
            selected=None,
            candidates=[replacement],
            message=info.message,
        ),
    )


def _emit_assertion_surface_fact(
    stmt: SourceFragment,
    fn: SourceFragment,
    formula: Formula,
    *,
    selected: str,
    role: str,
    filename: str,
    memento_file: str,
    source_lines: list[str],
    reason: str | None = None,
) -> LiftResult:
    contract_name = (
        f"{Path(memento_file).stem}::{fn.function_name()}::"
        f"assert:{stmt.line}:{stmt.col}::assertion"
    )
    memento = _statement_source_memento(
        stmt,
        fn,
        memento_file,
        source_lines,
        contract_name=contract_name,
        role=role,
    )
    inv = _formula_to_rpc(formula)
    contract = BodyUniverseDto(
        name=contract_name,
        out_binding="out",
        inv=inv,
        source_warrants=[memento],
    )
    walk = _walk_row(
        selected,
        "Assert",
        stmt,
        filename,
        memento,
        "predicate",
        requested_role="AssertionSurface",
        emitted_formula=inv,
        reason=reason,
    )
    audit = _source_audit(
        fn,
        stmt,
        memento_file,
        contract_name,
        memento,
        role=role,
        ast_kind="Assert",
    )
    return ([contract], [memento], [audit], [walk], [])


def _empty_lift() -> LiftResult:
    return ([], [], [], [], [])


def _merge_many(lifts: list[LiftResult]) -> LiftResult:
    if not lifts:
        return _empty_lift()
    merged = lifts[0]
    for extra in lifts[1:]:
        merged = _merge_lifts(merged, extra)
    return merged


def _merge_contract_rows(rows: list[Any]) -> list[Any]:
    merged: list[Any] = []
    for row in rows:
        fact = _equality_fact_for_row(row)
        if fact is None:
            merged.append(row)
            continue
        for index, existing in enumerate(merged):
            existing_fact = _equality_fact_for_row(existing)
            if existing_fact is None:
                continue
            if existing_fact.euf_key != fact.euf_key:
                continue
            if existing_fact.semantic_cid() != fact.semantic_cid():
                continue
            merged_fact = merge_equality_facts(existing_fact, fact)
            merged[index] = _merge_equality_fact_rows(existing, row, merged_fact)
            break
        else:
            merged.append(row)
    return merged


def _materialize_contract_rows(rows: list[Any]) -> list[BodyUniverseDto]:
    materialized: list[BodyUniverseDto] = []
    for row in _merge_contract_rows(rows):
        if isinstance(row, EqualityFactEmission):
            declaration = row.fact.to_declaration()
            contract = _body_universe_from_declaration(declaration)
            materialized.append(
                replace(contract, source_warrants=list(row.source_warrants))
            )
            continue
        if isinstance(row, BodyUniverseDto):
            materialized.append(row)
            continue
        node = _require_proofir_emission_node(
            row,
            construction_site=f"{type(row).__name__}.to_declaration",
            replacement="ProofIRNode",
        )
        materialized.append(_body_universe_from_declaration(node.to_declaration()))
    return materialized


def _body_universe_from_declaration(declaration: dict[str, Any]) -> BodyUniverseDto:
    return BodyUniverseDto(
        name=declaration["name"],
        out_binding=declaration.get("outBinding", "out"),
        pre=declaration.get("pre"),
        post=declaration.get("post"),
        inv=declaration.get("inv"),
        source_warrants=list(declaration.get("sourceWarrants", [])),
        proofir_provenance=declaration.get("proofirProvenance"),
        warranted_by=declaration.get("warrantedBy"),
        formals=list(declaration.get("formals", [])),
        kind=declaration.get("kind", "contract"),
        bridge_source_symbol=declaration.get("bridgeSourceSymbol"),
    )


def _proofir_construction_site(
    stmt: SourceFragment, memento_file: str
) -> ConstructionSite:
    return ConstructionSite(path=memento_file, line=stmt.line, column=stmt.col)


def _equality_fact_for_row(row: object) -> EqualityFact | None:
    if isinstance(row, EqualityFactEmission):
        return row.fact
    if isinstance(row, EqualityFact):
        return row
    return None


def _merge_equality_fact_rows(
    left: object, right: object, merged_fact: EqualityFact
) -> EqualityFact | EqualityFactEmission:
    warrants = _union_source_warrants(
        [*_source_warrants_for_row(left), *_source_warrants_for_row(right)]
    )
    if warrants:
        return EqualityFactEmission(merged_fact, tuple(warrants))
    return merged_fact


def _source_warrants_for_row(row: object) -> tuple[SourceMementoDto, ...]:
    if isinstance(row, EqualityFactEmission):
        return row.source_warrants
    return ()


def _union_source_warrants(
    warrants: list[SourceMementoDto],
) -> list[SourceMementoDto]:
    merged: list[SourceMementoDto] = []
    seen: set[str] = set()
    for warrant in warrants:
        key = json.dumps(warrant.to_rpc(), sort_keys=True, separators=(",", ":"))
        if key in seen:
            continue
        seen.add(key)
        merged.append(warrant)
    return merged


@dataclass(frozen=True)
class _BridgeProjectionRefused:
    pass


_BRIDGE_PROJECTION_REFUSED = _BridgeProjectionRefused()


def _construct_callsite_from_factory_term(
    stmt: SourceFragment,
    callsite: SourceFragment,
    callee_name: str,
    caller_fn: SourceFragment,
    functions_by_name: dict[str, SourceFragment],
    classes_by_name: dict[str, SourceFragment],
    *,
    filename: str,
    memento_file: str,
    source_lines: list[str],
    dig_refusals: list[DigRefusal],
    agreement_violations: list[FloorContractAgreementViolation],
) -> LiftResult:
    """Construct floor facts by reading the factory's CallSiteValue term.

    This is the Slice-4 consumer path: the callsite is built by the catalog, bridges append
    their owed digs to ``dig_sink``, and concrete floors are projected through
    ``project_callsite_with``. No callee body is reduced here by hand.
    """
    from .build import default_catalog
    from .sugar_constructors import build_bridge_body
    from sugar_lift_py_tests.context.reduce_context import ReduceContext
    from sugar_lift_py_tests.factory.factory_gap import FactoryGap
    from sugar_lift_py_tests.floor import CallSiteValue, FloorValue
    from sugar_lift_py_tests.floor.call_site_value import force_floor
    from sugar_lift_py_tests.operations import (
        CallsiteProjectionOperation,
        perform_operation,
    )
    from sugar_lift_py_tests.outcome import Complete

    build_ctx = FactoryBuildContext(
        filename=filename,
        catalog=default_catalog(),
        name_resolver=_resolver_nodes(functions_by_name, classes_by_name),
    )
    sink: list[tuple[str, FloorValue]] = []
    reduce_ctx = ReduceContext.root(
        owner="literal_call_report.callsite_floor", dig_sink=sink
    )
    callable_contracts: dict[str, BodyUniverseDto] = {}
    facts: list[LiftResult] = []
    universes_seen: set[str] = set()
    callsites_seen: set[str] = set()
    facts_seen: set[tuple[str, str]] = set()

    def mint_universe(cn: str) -> None:
        if cn in universes_seen:
            return
        universes_seen.add(cn)
        callee = functions_by_name.get(cn)
        if callee is None:
            return
        uni = _function_universe(
            callee,
            cn,
            functions_by_name=functions_by_name,
            classes_by_name=classes_by_name,
            filename=filename,
            memento_file=memento_file,
            source_lines=source_lines,
            dig_refusals=dig_refusals,
        )
        if uni is None:
            return
        facts.append(uni)
        for contract in uni[0]:
            if (
                contract.kind == "function-contract"
                and contract.bridge_source_symbol is not None
            ):
                callable_contracts[contract.bridge_source_symbol] = contract

    def emit_projected_fact(
        call_value: CallSiteValue,
        arg_terms: list[Term],
        value_term: Term,
        *,
        check_agreement: bool,
    ) -> bool:
        call_term = euf_call_term(call_value.target_name, arg_terms)
        if value_term == call_term:
            return False
        contract_name = euf_callsite_name(
            call_value.target_name,
            call_term,
            suffix="::assertion",
        )
        fact_key = (contract_name, repr(value_term))
        if fact_key in facts_seen:
            return False
        facts_seen.add(fact_key)
        if check_agreement:
            callable_contract = callable_contracts.get(f"call:{call_value.target_name}")
            if callable_contract is not None:
                agreement_violations.extend(
                    floor_contract_agreement_violations_for_fact(
                        callee=call_value.target_name,
                        callable_contract=callable_contract,
                        arg_terms=arg_terms,
                        floor_term=value_term,
                        callsite_contract=contract_name,
                    )
                )
        facts.append(
            _emit_euf_fact(
                stmt,
                caller_fn,
                call_value.target_name,
                arg_terms,
                value_term,
                filename=filename,
                memento_file=memento_file,
                source_lines=source_lines,
                warrant=Derived(
                    floor_chain=(
                        "literal_call_report.callsite_floor",
                        call_value.target_name,
                    )
                ),
            )
        )
        return True

    def floor_fact(call_value: CallSiteValue) -> None:
        arg_terms = [
            floor_to_term(arg, owner="literal_call_report.callsite_floor_arg")
            for arg in call_value.arg_values
        ]
        contract_name = euf_callsite_name(
            call_value.target_name,
            euf_call_term(call_value.target_name, arg_terms),
            suffix="::assertion",
        )
        if contract_name in callsites_seen:
            return
        callsites_seen.add(contract_name)
        immediate = _immediate_callsite_term(
            call_value,
            reduce_ctx,
            owner="literal_call_report.callsite_bridge",
            blame=callsite.blame,
            dig_refusals=dig_refusals,
        )
        immediate_emitted = False
        if immediate is not None:
            if isinstance(immediate, _BridgeProjectionRefused):
                return
            immediate_emitted = emit_projected_fact(
                call_value, arg_terms, immediate, check_agreement=True
            )
        try:
            floor = force_floor(
                call_value,
                reduce_ctx,
                owner="literal_call_report.callsite_floor",
                project_callsite=False,
            )
            projection = _formula_or_none(
                perform_operation(
                    owner="literal_call_report.callsite_floor",
                    blame=call_value.target_name,
                    receiver=floor,
                    operation=CallsiteProjectionOperation(
                        callee_name=call_value.target_name,
                        arg_terms=tuple(arg_terms),
                        owner="literal_call_report.callsite_floor",
                        blame=call_value.target_name,
                    ),
                    ctx=reduce_ctx,
                )
            )
        except (TypeError, ValueError, FactoryGap) as exc:
            _record_dig_refusal(
                dig_refusals,
                callee=call_value.target_name,
                blame=callsite.blame,
                caught=exc,
                reason="callsite floor projection refused this callee",
            )
            return
        if projection is None:
            _record_dig_refusal(
                dig_refusals,
                callee=call_value.target_name,
                blame=callsite.blame,
                caught=ValueError("callsite floor stayed symbolic"),
                reason="callsite floor projection refused this callee",
            )
            return
        value_term = _projected_value_term(projection)
        if value_term is None:
            _record_dig_refusal(
                dig_refusals,
                callee=call_value.target_name,
                blame=callsite.blame,
                caught=TypeError(
                    f"project_callsite_with returned {type(projection).__name__}"
                ),
                reason="callsite floor projection refused this callee",
            )
            return
        emit_projected_fact(
            call_value,
            arg_terms,
            value_term,
            check_agreement=not immediate_emitted,
        )

    def sink_call_value(cn: str, arg_value: FloorValue) -> CallSiteValue | None:
        callee = functions_by_name.get(cn)
        if callee is None or len(callee.function_params()) != 1:
            return None
        try:
            body = build_bridge_body(
                callee, replace(build_ctx, building=build_ctx.building | {cn})
            )
            arg_term = floor_to_term(
                arg_value, owner="literal_call_report.callsite_floor_sink_arg"
            )
        except (TypeError, ValueError, FactoryGap) as exc:
            _record_dig_refusal(
                dig_refusals,
                callee=cn,
                blame=callee.blame,
                caught=exc,
                reason="transitive bridge floor projection refused this callee",
            )
            return None
        return CallSiteValue(
            target_name=cn,
            arg_values=(arg_value,),
            parameters=tuple(callee.function_params()),
            term=euf_call_term(cn, [arg_term]),
            body=body,
        )

    mint_universe(callee_name)
    try:
        call_body = build_ctx.build_body(callsite, SugarRole.TERM)
        outcome = call_body.reduce(reduce_ctx)
        if not isinstance(outcome, Complete):
            raise TypeError(f"callsite reduced to {type(outcome).__name__}")
        top_value = complete_value(outcome, owner="literal_call_report.callsite_floor")
        if not isinstance(top_value, CallSiteValue):
            raise TypeError(f"callsite reduced to {type(top_value).__name__}")
    except (TypeError, ValueError, FactoryGap) as exc:
        _record_dig_refusal(
            dig_refusals,
            callee=callee_name,
            blame=callsite.blame,
            caught=exc,
            reason="callsite floor projection refused this callee",
        )
        return _merge_many(facts)

    floor_fact(top_value)
    index = 0
    while index < len(sink):
        cn, arg_value = sink[index]
        index += 1
        mint_universe(cn)
        bridged = sink_call_value(cn, arg_value)
        if bridged is not None:
            floor_fact(bridged)
    return _merge_many(facts)


def _projected_value_term(formula: Formula) -> Term | None:
    if not isinstance(formula, _Atomic) or formula.name != "=":
        return None
    if len(formula.args) != 2:
        return None
    return formula.args[1]


def _formula_or_none(value: object) -> Formula | None:
    if value is None:
        return None
    if isinstance(value, (_Atomic, _Connective, _Quantifier)):
        return value
    raise TypeError(f"project_callsite_with returned {type(value).__name__}")


def _immediate_callsite_term(
    call_value,
    ctx,
    *,
    owner: str,
    blame: str,
    dig_refusals: list[DigRefusal],
) -> Term | _BridgeProjectionRefused | None:
    from sugar_lift_py_tests.factory.factory_gap import FactoryGap
    from sugar_lift_py_tests.floor.call_site_value import (
        _ctx_with_curried_args,
        _reduce_callsite_body,
    )
    from sugar_lift_py_tests.operations import (
        CallsiteProjectionOperation,
        perform_operation,
    )
    from sugar_lift_py_tests.outcome import Incomplete, complete_value

    try:
        arg_terms = [
            floor_to_term(arg, owner="literal_call_report.callsite_bridge_arg")
            for arg in call_value.arg_values
        ]
        reduce_ctx = _ctx_with_curried_args(
            ctx, call_value.parameters, call_value.arg_values
        )
        outcome = _reduce_callsite_body(
            call_value.body, reduce_ctx, blame=call_value.target_name
        )
        if isinstance(outcome, Incomplete):
            return None
        value = complete_value(outcome, owner=owner)
        projection = _formula_or_none(
            perform_operation(
                owner=owner,
                blame=call_value.target_name,
                receiver=value,
                operation=CallsiteProjectionOperation(
                    callee_name=call_value.target_name,
                    arg_terms=tuple(arg_terms),
                    owner=owner,
                    blame=call_value.target_name,
                ),
                ctx=reduce_ctx,
            )
        )
    except (TypeError, ValueError, FactoryGap) as exc:
        _record_dig_refusal(
            dig_refusals,
            callee=call_value.target_name,
            blame=blame,
            caught=exc,
            reason="callsite floor projection refused this callee",
        )
        return _BRIDGE_PROJECTION_REFUSED
    if projection is None:
        return None
    return _projected_value_term(projection)


def _function_universe(
    callee: SourceFragment,
    callee_name: str,
    *,
    functions_by_name: dict[str, SourceFragment],
    classes_by_name: dict[str, SourceFragment],
    filename: str,
    memento_file: str,
    source_lines: list[str],
    dig_refusals: list[DigRefusal],
) -> LiftResult | None:
    """The `::callable` universe for ONE resolved function, walked from its DEFINITION.

    The construction swears the concrete VALUE at the callsite; this walks the body over its
    formals into `out == <body>` and warrants each source LINE -- so the visual walk paints the
    function body green where its constraints originate, not just the assertion. It calls the
    control-flow walker DIRECTLY (which now lifts `return x + 1` to `out == +(x, 1)` via the
    symbolic-op emission), bypassing build_bridge_body's string-only single-return shortcut.
    Returns None if the body cannot be walked -- the construction still stands; only the
    source-line warrant is absent."""
    from sugar_lift_py_tests.factory.factory_gap import FactoryGap

    from .build import default_catalog
    from .sugar_constructors import build_control_flow_body_sugar

    build_ctx = FactoryBuildContext(
        filename=filename,
        catalog=default_catalog(),
        name_resolver=_resolver_nodes(functions_by_name, classes_by_name),
    )
    try:
        universe_sugar = build_control_flow_body_sugar(callee, build_ctx)
        body_steps = universe_sugar.factory_steps(callee.node)
        body_formulas = universe_sugar.constraint_formulas()
        body_step_formulas = universe_sugar.constraint_formula_steps()
    except (TypeError, ValueError, FactoryGap) as exc:
        _record_dig_refusal(
            dig_refusals,
            callee=callee.function_name(),
            blame=callee.blame,
            caught=exc,
            reason="function universe body walker refused this body",
        )
        return None  # a body shape the walker cannot lift yet -> no warrant, construction stands

    # IMPORT SUGAR: an imported callee's body lives in its OWN module source -- swap provenance
    # (before the contract name, which keys on the stem) so the universe's mementos resolve
    # against the right lines instead of indexing past the importer's file (as _dig_universe does).
    _imported_source = getattr(callee.node, "_sugar_source", None)
    if _imported_source is not None:
        source_lines = _imported_source.splitlines(keepends=True)
        memento_file = getattr(callee.node, "_sugar_file", memento_file)
    body_formula_values = [_formula_to_rpc(formula) for formula in body_formulas]
    body_step_formula_values = [
        _formula_to_rpc(formula) if formula is not None else None
        for formula in body_step_formulas
    ]
    _universe_bound = set(callee.function_params()) | {"out"}
    _universe_formulas = [
        f
        for f, fv in zip(body_formulas, body_formula_values)
        if not _is_free_var_definition(fv, _universe_bound)
    ]
    if not _universe_formulas:
        return None
    function_post = (
        _formula_to_rpc(_universe_formulas[0])
        if len(_universe_formulas) == 1
        else _formula_to_rpc(and_(_universe_formulas))
    )
    function_contract_name = (
        f"{Path(memento_file).stem}::{callee.function_name()}::callable"
    )
    function_memento = _function_source_memento(
        callee,
        memento_file,
        source_lines,
        role="python.literal-call-sugar",
        contract_name=function_contract_name,
    )
    body_mementos = [
        _statement_source_memento(
            SourceFragment.from_node(step_stmt, memento_file),
            callee,
            memento_file,
            source_lines,
            contract_name=function_contract_name,
            role="python.literal-call-sugar",
        )
        for _, _, step_stmt, _ in body_steps
    ]
    return_stmt_frag = SourceFragment.from_node(body_steps[-1][2], memento_file)
    function_contract = BodyUniverseDto(
        name=function_contract_name,
        out_binding="out",
        post=function_post,
        source_warrants=[function_memento],
        formals=callee.function_params(),
        kind="function-contract",
        bridge_source_symbol=f"call:{callee_name}",
    )
    audit = _source_audit(
        callee,
        return_stmt_frag,
        memento_file,
        function_contract_name,
        body_mementos[-1],
        role="python.literal-call-sugar",
        ast_kind="Return",
    )
    walk_rows = [
        _walk_row(
            selected,
            ast_kind,
            SourceFragment.from_node(step_stmt, memento_file),
            filename,
            step_memento,
            output,
            requested_role="FunctionBodyConstraint",
            emitted_formula=(
                body_step_formula_values[index]
                if index < len(body_step_formula_values)
                else None
            ),
        )
        for index, ((selected, ast_kind, step_stmt, output), step_memento) in enumerate(
            zip(body_steps, body_mementos)
        )
    ]
    return (
        [function_contract],
        [function_memento, *body_mementos],
        [audit],
        walk_rows,
        [],
    )


def _dig_universe(
    call_frag: SourceFragment,
    *,
    functions_by_name: dict[str, SourceFragment],
    classes_by_name: dict[str, SourceFragment],
    filename: str,
    memento_file: str,
    source_lines: list[str],
    dig_refusals: list[DigRefusal],
) -> LiftResult | None:
    """The dig, when the source is present. Desugar `callee`'s body into the universe
    post (a forall over the function's formals) and mint it as a `function-contract`.
    `kind=function-contract` + `post` + `formals` makes the mint auto-mint a
    `call:<callee> -> this contract` bridge, which is exactly what `collect_ambient_posts`
    keys on -- so the post becomes an ambient universal the verifier specializes onto
    any matching `call:<callee>` callsite, local or imported."""
    from .build import default_catalog

    factory_ctx = FactoryBuildContext(
        filename=filename,
        catalog=default_catalog(),
        name_resolver=_resolver_nodes(functions_by_name, classes_by_name),
    )
    # Route through the CATALOG -- no side door. A resolved call builds a CallSugar whose
    # strategy is a BridgeStrategy carrying the callee's universe (the body walked over its
    # formals). The bridge IS the dig's source; never a side-door constructor.
    from sugar_lift_py_tests.sugar.call_sugar import BridgeStrategy

    try:
        call_body = factory_ctx.build_body(call_frag, SugarRole.TERM)
    except TypeError as exc:
        _panic_no_sugar(
            call_frag,
            memento_file,
            observed=f"dig-body:{call_frag.observed}",
            requested="FunctionBodyConstraint",
            fix=f"lift this function body for the dig ({exc})",
        )
    call_sugar = getattr(call_body.sugar, "strategy", None)
    if not isinstance(call_sugar, BridgeStrategy):
        _panic_no_sugar(
            call_frag,
            memento_file,
            observed=f"dig-body:{call_frag.observed}",
            requested="FunctionBodyConstraint",
            fix="lift this function body for the dig",
        )
    target_fn = functions_by_name[call_sugar.target_name]
    # IMPORT SUGAR: an imported callee's body belongs to its OWN module source, not
    # the file being lifted -- swap the provenance source so the dig's mementos
    # resolve against the right lines instead of indexing past the importer's file.
    _imported_source = getattr(target_fn.node, "_sugar_source", None)
    if _imported_source is not None:
        source_lines = _imported_source.splitlines(keepends=True)
        memento_file = getattr(target_fn.node, "_sugar_file", memento_file)
    # The dig walks the resolved body into the universe post. It handles control-flow and
    # encoder bodies; a numeric simple body (`return <expr>`) is not covered yet. "Not
    # covered" must speak through the MOUTH -- a named FactoryGap with blame -- never a raw
    # ValueError escaping from BridgeStrategy. The floor is honest or it is a crash.
    try:
        body_steps = call_sugar.factory_steps(target_fn.node)
        body_formulas = call_sugar.constraint_formulas()
        body_step_formulas = call_sugar.constraint_formula_steps()
    except ValueError as exc:
        _panic_no_sugar(
            target_fn,
            memento_file,
            observed=f"dig-body:simple-{target_fn.function_name()}",
            requested="NumericBodyConstraint",
            fix=f"add the numeric simple-body dig (out == <return expr over the formal>): {exc}",
        )
    body_formula_values = [_formula_to_rpc(formula) for formula in body_formulas]
    body_step_formula_values = [
        _formula_to_rpc(formula) if formula is not None else None
        for formula in body_step_formulas
    ]
    # The exported universe keeps `out` as its out-binding: the verifier substitutes
    # `out_binding -> callsite` and `formals -> call args`, turning
    # `str.eq-bv-blocks(out, value, ...)` into `str.eq-bv-blocks(call:enc(xyz), xyz, ...)`.
    # It must be CLOSED after those substitutions or the verifier skips it as "open", so
    # drop free-var DEFINITIONS (`eq(alphabet, "..")` whose var is neither a formal nor
    # `out`); the str.eq-bv-blocks payload already carries the alphabet constant.
    _universe_bound = set(target_fn.function_params()) | {"out"}
    _universe_formulas = [
        f
        for f, fv in zip(body_formulas, body_formula_values)
        if not _is_free_var_definition(fv, _universe_bound)
    ]
    function_post = (
        _formula_to_rpc(_universe_formulas[0])
        if len(_universe_formulas) == 1
        else _formula_to_rpc(and_(_universe_formulas))
    )
    function_contract_name = (
        f"{Path(memento_file).stem}::{target_fn.function_name()}::callable"
    )
    function_memento = _function_source_memento(
        target_fn,
        memento_file,
        source_lines,
        role="python.literal-call-sugar",
        contract_name=function_contract_name,
    )
    body_mementos = [
        _statement_source_memento(
            SourceFragment.from_node(step_stmt, memento_file),
            target_fn,
            memento_file,
            source_lines,
            contract_name=function_contract_name,
            role="python.literal-call-sugar",
        )
        for _, _, step_stmt, _ in body_steps
    ]
    return_memento = body_mementos[-1]
    return_stmt_raw = body_steps[-1][2]
    return_stmt_frag = SourceFragment.from_node(return_stmt_raw, memento_file)
    function_contract = BodyUniverseDto(
        name=function_contract_name,
        out_binding="out",
        post=function_post,
        source_warrants=[function_memento],
        formals=target_fn.function_params(),
        kind="function-contract",
        # Must equal the callsite ctor head the fact emits (`call:<callee>`), which the
        # verifier matches via `post.source_symbol == callsite.name`.
        bridge_source_symbol=f"call:{call_sugar.target_name}",
    )
    audit = _source_audit(
        target_fn,
        return_stmt_frag,
        memento_file,
        function_contract_name,
        return_memento,
        role="python.literal-call-sugar",
        ast_kind="Return",
    )
    walk_rows = [
        _walk_row(
            selected,
            ast_kind,
            SourceFragment.from_node(step_stmt, memento_file),
            filename,
            step_memento,
            output,
            requested_role="FunctionBodyConstraint",
            emitted_formula=(
                body_step_formula_values[index]
                if index < len(body_step_formula_values)
                else None
            ),
        )
        for index, (
            (selected, ast_kind, step_stmt, output),
            step_memento,
        ) in enumerate(zip(body_steps, body_mementos))
    ]
    return (
        [function_contract],
        [function_memento, *body_mementos],
        [audit],
        walk_rows,
        [],
    )


def _merge_lifts(universe: LiftResult | None, assertion: LiftResult) -> LiftResult:
    """Universe first (the function-contract), then the assertion -- the order the
    consumers expect when both are present."""
    if universe is None:
        return assertion
    return (
        _merge_contract_rows([*universe[0], *assertion[0]]),
        [*universe[1], *assertion[1]],
        [*universe[2], *assertion[2]],
        [*universe[3], *assertion[3]],
        [*universe[4], *assertion[4]],
    )


def _record_dig_refusal(
    dig_refusals: list[DigRefusal],
    *,
    callee: str,
    blame: str,
    caught: BaseException,
    reason: str,
) -> None:
    dig_refusals.append(
        DigRefusal(
            callee=callee,
            blame=blame,
            caught=type(caught).__name__,
            reason=f"{reason}: {caught}",
        )
    )


def _panic_no_sugar(
    frag: SourceFragment, memento_file: str, *, observed: str, requested: str, fix: str
) -> NoReturn:
    """The mouth. The lifter saw an assertion it could not lift and REFUSES to drop it
    silently -- it PANICS, naming the AST shape and the sugar that is missing. A silent
    `return None` here would be the cardinal crime (un-done work disguised as done), so
    the design forbids it: every give-up on a claim is a FactoryGap, never a None."""
    from .factory_audit_row import FactoryAuditRow
    from .factory_gap import FactoryGap
    from .factory_gap_info import FactoryGapInfo

    blame = f"{memento_file}:{frag.line}:{frag.col}"
    info = FactoryGapInfo(
        owner="python.factory.literal-call",
        blame=blame,
        observed=observed,
        requested=requested,
        fix=fix,
    )
    raise FactoryGap(
        info,
        FactoryAuditRow(
            role=requested,
            status="sugar-gap",
            observed=observed,
            blame=blame,
            selected=None,
            candidates=[],
            message=info.message,
        ),
    )


def _external_bridge_edges(
    sink: list[dict[str, Any]],
    *,
    source_contract: str,
    memento_file: str,
    contract_bindings: list,
) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []
    seen: set[tuple[str, int, int]] = set()
    for item in sink:
        target_symbol = item["targetSymbol"]
        key = (target_symbol, item["line"], item["column"])
        if key in seen:
            continue
        seen.add(key)
        binding = _binding_for_bridge_symbol(contract_bindings, target_symbol)
        edge: dict[str, Any] = {
            "kind": "call-edge",
            "schemaVersion": "1",
            "sourceContract": source_contract,
            "targetSymbol": target_symbol,
            "targetContract": binding.get("name") if binding is not None else None,
            "targetContractCid": _binding_cid(binding) if binding is not None else None,
            "callSiteLocus": {
                "file": memento_file,
                "line": item["line"],
                "column": item["column"],
            },
        }
        proof_cid = _binding_proof_cid(binding)
        if proof_cid is not None:
            edge["targetProofCid"] = proof_cid
        edges.append(edge)
    return edges


def _module_statements(root_frag: SourceFragment) -> list[SourceFragment]:
    statements: list[SourceFragment] = []
    for fragment in root_frag.fragments():
        statements.extend(fragment.statements())
    return statements


def _binding_for_bridge_symbol(
    contract_bindings: list,
    target_symbol: str,
) -> dict[str, Any] | None:
    target_name = target_symbol.removeprefix("call:")
    for binding in contract_bindings:
        if not isinstance(binding, dict):
            continue
        if binding.get("bridgeSourceSymbol") == target_symbol:
            return binding
        name = binding.get("name")
        if name in {target_symbol, target_name}:
            return binding
    return None


def _binding_cid(binding: dict[str, Any] | None) -> str | None:
    if binding is None:
        return None
    cid = (
        binding.get("contract_cid")
        or binding.get("contractCid")
        or binding.get("targetContractCid")
    )
    return cid if isinstance(cid, str) and cid else None


def _binding_proof_cid(binding: dict[str, Any] | None) -> str | None:
    if binding is None:
        return None
    cid = binding.get("target_proof_cid") or binding.get("targetProofCid")
    return cid if isinstance(cid, str) and cid else None


def _import_bindings(
    tree_frag: SourceFragment,
) -> tuple[dict[str, str], dict[str, tuple[str, str]]]:
    """Scan a module's imports.

    Returns ``(aliases, from_imports)`` where ``aliases`` maps a bound name to its
    module (``import numpy as np`` -> ``{"np": "numpy"}``) and ``from_imports`` maps
    a bound name to ``(module, attr)`` (``from numpy import rot90`` -> ``{"rot90":
    ("numpy", "rot90")}``)."""
    aliases: dict[str, str] = {}
    from_imports: dict[str, tuple[str, str]] = {}
    for frag in tree_frag.walk():
        if frag.observed == "Import":
            for name, asname in frag.import_names():
                aliases[asname or name] = name
        elif frag.observed == "ImportFrom" and frag.importfrom_level() == 0:
            module = frag.importfrom_module()
            if module is None:
                continue
            for name, asname in frag.importfrom_names():
                from_imports[asname or name] = (module, name)
    return aliases, from_imports


def _source_funcdef(
    module_name: str, attr: str, *, dig_refusals: list[DigRefusal]
) -> SourceFragment | None:
    """Resolve ``module_name.attr`` to its installed-source FunctionDef SourceFragment.

    The callee must be importable in the lifter's environment and have readable
    Python source. Decorators are dropped (the dig walks the body, not the
    dispatch wrapper). Anything unresolvable returns None -- the dig then has no
    universe for that callee, which is the honest outcome."""
    import importlib
    import inspect
    import textwrap

    callee = f"{module_name}.{attr}"
    try:
        module = importlib.import_module(module_name)
        obj = getattr(module, attr)
        source = textwrap.dedent(inspect.getsource(obj))
    except (ImportError, AttributeError, OSError, TypeError) as exc:
        _record_dig_refusal(
            dig_refusals,
            callee=callee,
            blame=callee,
            caught=exc,
            reason="imported callee source was not readable",
        )
        return None
    # getsourcefile is best-effort: it raises TypeError on dispatch-wrapped callees
    # (e.g. numpy's @array_function_dispatch) where getsource still works -- a failure
    # here must NOT abort the resolution, only drop the filename label.
    try:
        sourcefile = inspect.getsourcefile(obj) or f"<{module_name}>"
    except TypeError as exc:
        _record_dig_refusal(
            dig_refusals,
            callee=callee,
            blame=callee,
            caught=exc,
            reason="imported callee source filename was not readable",
        )
        sourcefile = f"<{module_name}>"
    try:
        parsed_frag = SourceFragment.from_source(source, sourcefile)
    except SyntaxError:
        return None
    for child in parsed_frag.walk():
        if child.observed == "FunctionDef" and child.function_name() == attr:
            child.node.decorator_list = []  # type: ignore[attr-defined]
            # Carry the callee's OWN source so the dig's provenance mementos resolve
            # against its module file, not the file that imported it.
            child.node._sugar_source = source  # type: ignore[attr-defined]
            child.node._sugar_file = sourcefile  # type: ignore[attr-defined]
            return child
    return None


def _resolve_imported_callees(
    tree_frag: SourceFragment,
    aliases: dict[str, str],
    from_imports: dict[str, tuple[str, str]],
    *,
    dig_refusals: list[DigRefusal],
) -> dict[str, SourceFragment]:
    """For every callsite referencing an imported callee (``np.rot90(...)`` or a
    ``from``-imported ``rot90(...)``), resolve its installed source to a
    SourceFragment keyed by the callee name -- so the dig can walk it. The import
    is the bridge from "the source is on disk" to "the dig can reach it"."""
    resolved: dict[str, SourceFragment] = {}
    for frag in tree_frag.walk():
        if frag.observed != "Call":
            continue
        target = frag.call_import_target_name(aliases, from_imports)
        if target is None or target in resolved:
            continue
        module_name, attr = _split_module_attr(target)
        funcdef = _source_funcdef(module_name, attr, dig_refusals=dig_refusals)
        if funcdef is not None:
            funcdef.node._sugar_bridge_name = target  # type: ignore[attr-defined]
            resolved[target] = funcdef
    return resolved


def _split_module_attr(target: str) -> tuple[str, str]:
    if "." not in target:
        return "", target
    module, attr = target.rsplit(".", 1)
    return module, attr


def _callee_name(
    frag: SourceFragment,
    import_aliases: dict[str, str],
    from_imports: dict[str, tuple[str, str]],
) -> str | None:
    if frag.observed != "Call":
        return None
    return (
        frag.call_import_target_name(import_aliases, from_imports)
        or frag.call_target_name()
    )


def _formula_to_rpc(formula: Formula) -> dict[str, Any]:
    return json.loads(encode_jcs(formula_to_value(formula)))


def _source_audit(
    fn: SourceFragment,
    stmt: SourceFragment,
    memento_file: str,
    contract_name: str,
    memento: SourceMementoDto,
    *,
    role: str,
    ast_kind: str,
) -> dict[str, Any]:
    totals = {
        "source_loci": 1,
        "source_warranted": 1,
        "source_inactive": 0,
        "source_support": 0,
        "source_refused": 0,
        "source_unresolved": 0,
        "unclassified_source": 0,
    }
    return {
        "role": role,
        "contract": contract_name,
        "file": memento_file,
        "sourceFunctionName": fn.function_name(),
        "totals": totals,
        "loci": [
            {
                "file": memento_file,
                "line": stmt.line,
                "col": stmt.col,
                "status": "warranted",
                "ast_kind": ast_kind,
                "role": role,
                "contract": contract_name,
                "sourceMemento": memento,
            }
        ],
    }


def _walk_row(
    selected: str,
    ast_kind: str,
    stmt: SourceFragment,
    filename: str,
    memento: SourceMementoDto,
    output: str,
    *,
    requested_role: str = "term",
    emitted_formula: dict[str, Any] | None = None,
    reason: str | None = None,
) -> FactoryWalkRowDto:
    return FactoryWalkRowDto(
        file=filename,
        line=stmt.line,
        requested_role=requested_role,
        ast_kind=ast_kind,
        selected=selected,
        # warrant vs support is the line's tie to the .proof: a line that emitted a
        # constraint is warranted; one accounted for but emitting nothing (a docstring,
        # a let inlined into the universe) is support.
        status="warranted" if emitted_formula is not None else "support",
        output=output,
        source_memento=memento,
        span=SourceSpanDto(
            start_line=stmt.line,
            start_col=stmt.col,
            end_line=stmt.end_line,
            end_col=stmt.end_col,
        ),
        emitted_formula=emitted_formula,
        reason=reason,
    )
