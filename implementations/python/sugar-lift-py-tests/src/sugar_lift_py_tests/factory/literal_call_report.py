from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, NoReturn

from sugar_lift_py_tests.factory.array_map_report import (
    _callsite_string,
    _function_source_memento,
    _source_ledger,
    _statement_source_memento,
)
from sugar_lift_py_tests.claim import SugarCatalog, SugarRole
from sugar_lift_py_tests.ir import (
    Formula,
    Locus,
    Term,
    _Atomic,
    _ConstBool,
    _ConstInt,
    _ConstReal,
    _ConstStr,
    _Connective,
    _Ctor,
    _Quantifier,
    _Var,
    and_,
    ctor,
    eq,
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
    AuditLocus,
    AuditMemento,
    BridgeAtom,
    CallEdgeDecl,
    ClaimFormula,
    ConstructionSite,
    Derived,
    EqualityFact,
    FunctionContract,
    IntSort,
    PostCondition,
    Provenance,
    Stated,
    UniverseMint,
    UnknownSort,
    claim_formula_from_ir,
    formula_from_ir,
    merge_equality_facts,
)
from sugar_lift_py_tests.proofir.formulas import (
    formula_to_rpc as proofir_formula_to_rpc,
)
from sugar_lift_py_tests.proofir.sorts import Sort as ProofSort, sort_from_ir

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


def _is_free_var_definition(formula: Formula, bound: set[str]) -> bool:
    """An `eq(var, _)` whose var is neither a formal nor `out` -- a free-variable
    definition that would leave an exported universe post OPEN, so the verifier's
    `linked_ambient_post_instances_for_inv` skips it. The str.eq-bv-blocks relation
    carries the alphabet as a constant payload, so dropping the definition is safe."""
    if not isinstance(formula, _Atomic) or formula.name != "=":
        return False
    if len(formula.args) != 2:
        return False
    left = formula.args[0]
    return isinstance(left, _Var) and left.name not in bound


def _contract_scope_sorts(
    formulas: list[Formula],
    *,
    formal_names: tuple[str, ...],
    out_binding: str = "out",
) -> dict[str, ProofSort]:
    sorts: dict[str, ProofSort] = {
        name: UnknownSort(reason=f"no declared sort for formal {name!r}")
        for name in formal_names
    }
    sorts[out_binding] = UnknownSort(
        reason=f"no declared return sort for {out_binding!r}"
    )
    for formula in formulas:
        _infer_formula_sorts(formula, sorts)
    return sorts


def _infer_formula_sorts(formula: Formula, sorts: dict[str, ProofSort]) -> None:
    if isinstance(formula, _Atomic):
        if formula.name in {">", "≥", "<", "≤"}:
            for term in formula.args:
                _mark_numeric_term(term, sorts)
            return
        if formula.name == "=" and len(formula.args) == 2:
            left, right = formula.args
            left_sort = _known_term_sort(left)
            right_sort = _known_term_sort(right)
            if left_sort is not None:
                _mark_term_sort(right, left_sort, sorts)
            if right_sort is not None:
                _mark_term_sort(left, right_sort, sorts)
        return
    if isinstance(formula, _Connective):
        for operand in formula.operands:
            _infer_formula_sorts(operand, sorts)
        return
    if isinstance(formula, _Quantifier):
        _infer_formula_sorts(formula.body, sorts)


def _known_term_sort(term: Term) -> ProofSort | None:
    if isinstance(term, (_ConstInt, _ConstStr, _ConstBool, _ConstReal)):
        return sort_from_ir(term.sort)
    if isinstance(term, _Ctor) and term.name in {"+", "-", "*"}:
        return IntSort()
    return None


def _mark_numeric_term(term: Term, sorts: dict[str, ProofSort]) -> None:
    _mark_term_sort(term, IntSort(), sorts)


def _mark_term_sort(term: Term, sort: ProofSort, sorts: dict[str, ProofSort]) -> None:
    if isinstance(term, _Var):
        existing = sorts.get(term.name)
        if existing is None or isinstance(existing, UnknownSort):
            sorts[term.name] = sort
        return
    if isinstance(term, _Ctor):
        if term.name in {"+", "-", "*"}:
            sort = IntSort()
        for arg in term.args:
            _mark_term_sort(arg, sort, sorts)


def _typed_formula_to_rpc(
    formula: Formula, scope_sorts: dict[str, ProofSort]
) -> dict[str, Any]:
    return proofir_formula_to_rpc(formula_from_ir(formula, var_sorts=scope_sorts))


def _post_condition_from_ir(
    formula: Formula,
    *,
    scope_sorts: dict[str, ProofSort],
    formal_names: tuple[str, ...],
    out_binding: str = "out",
) -> PostCondition:
    formal_sorts = {name: scope_sorts[name] for name in formal_names}
    out_sort = scope_sorts[out_binding]
    return PostCondition(
        formula_from_ir(formula, var_sorts={**formal_sorts, out_binding: out_sort}),
        formals=formal_sorts,
        out_binding=out_binding,
        out_sort=out_sort,
    )


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
    factory_audits: list[Any] = []
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
                factory_audits=factory_audits,
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
            factory_audits=factory_audits,
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
    factory_audits: list[Any],
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
        factory_audits=factory_audits,
        dig_refusals=dig_refusals,
        agreement_violations=agreement_violations,
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

    universe: LiftResult | None = None
    universe_factory_audits: list[Any] = []
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
            factory_audits=universe_factory_audits,
        )
    call_return_sort = _call_return_sort_from_universe(universe, callee_name)
    assertion_ctx = _assertion_factory_ctx(
        stmt=stmt,
        fn=fn,
        filename=filename,
        functions_by_name=functions_by_name,
        classes_by_name=classes_by_name,
        import_aliases=import_aliases,
        from_imports=from_imports,
        contract_bindings=contract_bindings,
        module_statements=module_statements,
        factory_audits=factory_audits,
    )
    derived_literal_call = _numpy_integer_literal_call_derived_fact(
        stmt,
        comparison=comparison,
        callee_name=callee_name,
        callsite=comparison_left,
        fn=fn,
        filename=filename,
        memento_file=memento_file,
        source_lines=source_lines,
        ctx=assertion_ctx,
        call_return_sort=call_return_sort,
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
        ctx=assertion_ctx,
        call_return_sort=call_return_sort,
    )
    factory_audits.extend(universe_factory_audits)
    return _merge_many(
        [
            lift
            for lift in (universe, derived_literal_call, assertion)
            if lift is not None
        ]
    )


def _call_return_sort_from_universe(
    universe: LiftResult | None,
    callee_name: str,
) -> ProofSort | None:
    if universe is None:
        return None
    for contract in universe[0]:
        if (
            isinstance(contract, FunctionContract)
            and contract.bridge_source_symbol == f"call:{callee_name}"
        ):
            return contract.out_sort
    return None


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
    factory_audits: list[Any],
    dig_refusals: list[DigRefusal],
    agreement_violations: list[FloorContractAgreementViolation],
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
        factory_audits=factory_audits,
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
    universe = _factory_assertion_derived_context(
        stmt,
        fn=fn,
        filename=filename,
        memento_file=memento_file,
        source_lines=source_lines,
        functions_by_name=functions_by_name,
        classes_by_name=classes_by_name,
        import_aliases=import_aliases,
        from_imports=from_imports,
        dig_refusals=dig_refusals,
        agreement_violations=agreement_violations,
        factory_audits=factory_audits,
    )
    if universe is not None:
        lifted = _merge_lifts(universe, lifted)
    return lifted


def _factory_assertion_derived_context(
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
    dig_refusals: list[DigRefusal],
    agreement_violations: list[FloorContractAgreementViolation],
    factory_audits: list[Any],
) -> LiftResult | None:
    if stmt.observed != "Assert":
        return None
    test = stmt.assert_test()
    if test.observed == "BoolOp":
        contexts = [
            context
            for value in test.boolop_values()
            if (
                context := _factory_assertion_derived_context(
                    stmt.assert_with_test(value),
                    fn=fn,
                    filename=filename,
                    memento_file=memento_file,
                    source_lines=source_lines,
                    functions_by_name=functions_by_name,
                    classes_by_name=classes_by_name,
                    import_aliases=import_aliases,
                    from_imports=from_imports,
                    dig_refusals=dig_refusals,
                    agreement_violations=agreement_violations,
                    factory_audits=factory_audits,
                )
            )
            is not None
        ]
        return _merge_many(contexts) if contexts else None
    if test.observed == "Call":
        callee_name = _callee_name(test, import_aliases, from_imports)
        if callee_name is None or callee_name not in functions_by_name:
            return None
        return _construct_callsite_from_factory_term(
            stmt,
            test,
            callee_name,
            fn,
            functions_by_name,
            classes_by_name,
            filename=filename,
            memento_file=memento_file,
            source_lines=source_lines,
            dig_refusals=dig_refusals,
            agreement_violations=agreement_violations,
            factory_audits=factory_audits,
        )
    comparison = test
    if comparison.observed != "Compare":
        return None
    if comparison.compare_ops() != ["Eq"] or len(comparison.compare_comparators()) != 1:
        return None
    comparison_left = _resolve_bound_lhs(comparison.compare_left(), fn)
    callee_name = _callee_name(comparison_left, import_aliases, from_imports)
    if callee_name is None or callee_name not in functions_by_name:
        return None
    return _construct_callsite_from_factory_term(
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
        factory_audits=factory_audits,
    )


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
    factory_audits: list[Any] | None = None,
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
        audit_sink=factory_audits,
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


_COMPUTABLE_NUMPY_INTEGER_UFUNCS = frozenset(
    {
        "numpy.add",
        "numpy.floor_divide",
        "numpy.mod",
        "numpy.multiply",
        "numpy.power",
        "numpy.subtract",
    }
)
_NUMPY_INT64_MIN = -(2**63)
_NUMPY_INT64_MAX = 2**63 - 1


def _numpy_integer_literal_call_derived_fact(
    stmt: SourceFragment,
    *,
    comparison: SourceFragment,
    callee_name: str,
    callsite: SourceFragment,
    fn: SourceFragment,
    filename: str,
    memento_file: str,
    source_lines: list[str],
    ctx: FactoryBuildContext,
    call_return_sort: ProofSort | None,
) -> LiftResult | None:
    """Emit the kit-computed sibling for a tiny, deliberate numpy integer subset.

    This is not numpy execution. Both operands must reduce through the factory into
    the kit's own ``TermValue(int)`` floor values; only then do we apply the matching
    integer arithmetic axiom and emit the result as Derived testimony under the same
    EUF key as the stated assertion.
    """
    if callee_name not in _COMPUTABLE_NUMPY_INTEGER_UFUNCS:
        return None
    if len(callsite.call_args()) != 2 or callsite.call_keywords():
        return None

    values: list[int] = []
    arg_terms: list[Term] = []
    for arg_frag in callsite.call_args():
        value = _integer_floor_for_numpy_literal_arg(
            arg_frag,
            ctx=ctx,
        )
        if value is None:
            return None
        values.append(value)
        arg_terms.append(_lift_literal_via_factory(arg_frag, filename, ctx=ctx))

    left, right = values
    result = _numpy_integer_ufunc_result(callee_name, left, right)
    if result is None:
        return None

    from sugar_lift_py_tests.ir import num

    return _emit_euf_fact(
        stmt,
        fn,
        callee_name,
        arg_terms,
        num(result),
        filename=filename,
        memento_file=memento_file,
        source_lines=source_lines,
        warrant=Derived(
            floor_chain=("literal_call_report.numpy_integer_ufunc", callee_name)
        ),
        call_return_sort=call_return_sort,
    )


def _numpy_integer_ufunc_result(
    callee_name: str,
    left: int,
    right: int,
) -> int | None:
    if not (_fits_numpy_int64(left) and _fits_numpy_int64(right)):
        return None
    if callee_name == "numpy.add":
        result = left + right
    elif callee_name == "numpy.multiply":
        result = left * right
    elif callee_name == "numpy.subtract":
        result = left - right
    elif callee_name == "numpy.mod":
        if right == 0:
            return None
        result = left % right
    elif callee_name == "numpy.floor_divide":
        if right == 0:
            return None
        result = left // right
    elif callee_name == "numpy.power":
        result = _numpy_integer_power_result(left, right)
        if result is None:
            return None
    else:
        return None
    if not _fits_numpy_int64(result):
        return None
    return result


def _numpy_integer_power_result(left: int, right: int) -> int | None:
    if right < 0:
        return None
    if left not in {-1, 0, 1} and right > 63:
        return None
    return left**right


def _fits_numpy_int64(value: int) -> bool:
    return _NUMPY_INT64_MIN <= value <= _NUMPY_INT64_MAX


def _integer_floor_for_numpy_literal_arg(
    frag: SourceFragment,
    *,
    ctx: FactoryBuildContext,
) -> int | None:
    from sugar_lift_py_tests.floor import TermValue

    body = ctx.build_body(frag, SugarRole.TERM)
    value = complete_value(
        body.reduce(ctx), owner="literal_call_report.numpy_integer_ufunc_arg"
    )
    if not isinstance(value, TermValue):
        return None
    if type(value.value) is not int:
        return None
    if not _fits_numpy_int64(value.value):
        return None
    return value.value


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
    call_return_sort: ProofSort | None = None,
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
        call_return_sort=call_return_sort,
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
    call_return_sort: ProofSort | None = None,
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
    call_sort = call_return_sort or UnknownSort(
        reason=f"no function-contract return sort available for call:{callee_name}"
    )
    call_term = CallTerm(
        callee_name,
        tuple(term_from_ir(arg_term) for arg_term in arg_terms),
        sort=call_sort,
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
    from sugar_lift_py_tests.factory import (
    FactoryAuditRow,
    FactoryGap,
    FactoryGapInfo,
    GapKind,
    GapLocus,
)
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
        gap_kind=GapKind.PROOFIR,
        gap_locus=GapLocus.EMISSION,
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
    inv = _claim_formula_for_report(
        formula,
        stmt,
        memento_file,
        role=role,
        node_class=UniverseMint.node_class,
    )
    contract = UniverseMint(
        name=contract_name,
        slot="inv",
        formula=inv,
        provenance=inv.provenance,
        out_binding="out",
        source_warrants=(memento,),
    ).to_body_universe()
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
            contract = row.fact.to_body_universe()
            materialized.append(
                replace(contract, source_warrants=list(row.source_warrants))
            )
            continue
        if isinstance(row, BodyUniverseDto):
            materialized.append(row)
            continue
        if isinstance(row, FunctionContract):
            materialized.append(row.to_body_universe())
            continue
        node = _require_proofir_emission_node(
            row,
            construction_site=f"{type(row).__name__}.to_declaration",
            replacement="ProofIRNode",
        )
        materialized.append(_body_universe_from_declaration(node.to_declaration()))
    return materialized


def _body_universe_from_declaration(declaration: dict[str, Any]) -> BodyUniverseDto:
    provenance = _provenance_from_declaration(declaration)
    base = BodyUniverseDto(
        name=declaration["name"],
        out_binding=declaration.get("outBinding", "out"),
        source_warrants=list(declaration.get("sourceWarrants", [])),
        proofir_provenance=declaration.get("proofirProvenance"),
        warranted_by=declaration.get("warrantedBy"),
        formals=list(declaration.get("formals", [])),
        kind=declaration.get("kind", "contract"),
        bridge_source_symbol=declaration.get("bridgeSourceSymbol"),
    )
    return replace(
        base,
        pre=ClaimFormula.from_rpc(
            declaration.get("pre"),
            provenance=provenance,
            role="BodyUniverseDto.pre",
        ),
        post=ClaimFormula.from_rpc(
            declaration.get("post"),
            provenance=provenance,
            role="BodyUniverseDto.post",
        ),
        inv=ClaimFormula.from_rpc(
            declaration.get("inv"),
            provenance=provenance,
            role="BodyUniverseDto.inv",
        ),
    )


def _provenance_from_declaration(declaration: dict[str, Any]) -> Provenance:
    proofir_provenance = declaration.get("proofirProvenance")
    node_class = (
        proofir_provenance.get("nodeClass")
        if isinstance(proofir_provenance, dict)
        else None
    )
    return Provenance(
        node_class=node_class or "BodyUniverseDto",
        construction_site=ConstructionSite(
            path=f"declaration:{declaration.get('name', '<unknown>')}",
            line=0,
            column=0,
        ),
        warrant=Derived(floor_chain=("body-universe-declaration",)),
    )


def _proofir_construction_site(
    stmt: SourceFragment, memento_file: str
) -> ConstructionSite:
    return ConstructionSite(path=memento_file, line=stmt.line, column=stmt.col)


def _claim_formula_for_report(
    formula: Formula,
    stmt: SourceFragment,
    memento_file: str,
    *,
    role: str,
    node_class: str,
    scope_sorts: dict[str, ProofSort] | None = None,
) -> ClaimFormula:
    wrapped = formula_from_ir(formula, var_sorts={})
    sorts = dict(scope_sorts or {})
    for name in wrapped.free_vars:
        sorts.setdefault(
            name,
            UnknownSort(reason=f"no declared sort for formula variable {name!r}"),
        )
    _infer_formula_sorts(formula, sorts)
    return claim_formula_from_ir(
        formula,
        var_sorts=sorts,
        allowed_vars=tuple(wrapped.free_vars),
        provenance=Provenance(
            node_class=node_class,
            construction_site=_proofir_construction_site(stmt, memento_file),
            warrant=Derived(floor_chain=(role,)),
        ),
        role=role,
    )


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
    factory_audits: list[Any],
) -> LiftResult:
    """Construct floor facts by reading the factory's CallSiteValue term.

    This is the Slice-4 consumer path: the callsite is built by the catalog, bridges append
    their owed digs to ``dig_sink``, and concrete floors are projected through
    ``project_callsite_with``. No callee body is reduced here by hand.
    """
    from .build import default_catalog
    from sugar_lift_py_tests.context.reduce_context import ReduceContext
    from sugar_lift_py_tests.factory.factory_gap import FactoryGap
    from sugar_lift_py_tests.floor import CallSiteValue
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
        audit_sink=factory_audits,
    )
    sink: list[CallSiteValue] = []
    reduce_ctx = ReduceContext.root(
        owner="literal_call_report.callsite_floor", dig_sink=sink
    )
    callable_contracts: dict[str, FunctionContract] = {}
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
            factory_audits=factory_audits,
        )
        if uni is None:
            return
        facts.append(uni)
        for contract in uni[0]:
            if (
                isinstance(contract, FunctionContract)
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
        callable_contract = callable_contracts.get(f"call:{call_value.target_name}")
        if check_agreement:
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
        call_return_sort = (
            callable_contract.out_sort if callable_contract is not None else None
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
                call_return_sort=call_return_sort,
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

        def emit_immediate_fallback() -> bool | _BridgeProjectionRefused:
            immediate = _immediate_callsite_term(
                call_value,
                reduce_ctx,
                owner="literal_call_report.callsite_bridge",
                blame=callsite.blame,
                dig_refusals=dig_refusals,
            )
            if immediate is None:
                return False
            if isinstance(immediate, _BridgeProjectionRefused):
                return immediate
            return emit_projected_fact(
                call_value, arg_terms, immediate, check_agreement=True
            )

        nested_sink_start = len(sink)
        immediate = emit_immediate_fallback()
        if isinstance(immediate, _BridgeProjectionRefused):
            return
        immediate_emitted = immediate
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
            check_agreement=(not immediate_emitted and len(sink) == nested_sink_start),
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
        bridged = sink[index]
        index += 1
        mint_universe(bridged.target_name)
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
    factory_audits: list[Any],
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
        audit_sink=factory_audits,
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
    formal_names = tuple(callee.function_params())
    scope_sorts = _contract_scope_sorts(body_formulas, formal_names=formal_names)
    body_formula_values = [
        _typed_formula_to_rpc(formula, scope_sorts) for formula in body_formulas
    ]
    body_step_formula_values = [
        _typed_formula_to_rpc(formula, scope_sorts) if formula is not None else None
        for formula in body_step_formulas
    ]
    _universe_bound = set(formal_names) | {"out"}
    _universe_formulas = [
        f for f in body_formulas if not _is_free_var_definition(f, _universe_bound)
    ]
    _universe_formulas = _with_python_bytes_content_universe(_universe_formulas)
    if not _universe_formulas:
        return None
    function_post = _post_condition_from_ir(
        (
            _universe_formulas[0]
            if len(_universe_formulas) == 1
            else and_(_universe_formulas)
        ),
        scope_sorts=scope_sorts,
        formal_names=formal_names,
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
    function_contract = FunctionContract(
        symbol=function_contract_name,
        formals=tuple(
            FunctionContract.formal(name, scope_sorts[name]) for name in formal_names
        ),
        post=function_post,
        warrants=(
            Provenance(
                node_class=FunctionContract.node_class,
                construction_site=_proofir_construction_site(
                    return_stmt_frag,
                    memento_file,
                ),
                warrant=Stated(
                    locus=_proofir_construction_site(return_stmt_frag, memento_file)
                ),
            ),
        ),
        out_binding="out",
        out_sort=function_post.out_sort,
        source_warrants=[function_memento],
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
    formal_names = tuple(target_fn.function_params())
    scope_sorts = _contract_scope_sorts(body_formulas, formal_names=formal_names)
    body_formula_values = [
        _typed_formula_to_rpc(formula, scope_sorts) for formula in body_formulas
    ]
    body_step_formula_values = [
        _typed_formula_to_rpc(formula, scope_sorts) if formula is not None else None
        for formula in body_step_formulas
    ]
    # The exported universe keeps `out` as its out-binding: the verifier substitutes
    # `out_binding -> callsite` and `formals -> call args`, turning
    # `str.eq-bv-blocks(out, value, ...)` into `str.eq-bv-blocks(call:enc(xyz), xyz, ...)`.
    # It must be CLOSED after those substitutions or the verifier skips it as "open", so
    # drop free-var DEFINITIONS (`eq(alphabet, "..")` whose var is neither a formal nor
    # `out`); the str.eq-bv-blocks payload already carries the alphabet constant.
    _universe_bound = set(formal_names) | {"out"}
    _universe_formulas = [
        f for f in body_formulas if not _is_free_var_definition(f, _universe_bound)
    ]
    _universe_formulas = _with_python_bytes_content_universe(_universe_formulas)
    function_post = _post_condition_from_ir(
        (
            _universe_formulas[0]
            if len(_universe_formulas) == 1
            else and_(_universe_formulas)
        ),
        scope_sorts=scope_sorts,
        formal_names=formal_names,
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
    function_contract = FunctionContract(
        symbol=function_contract_name,
        formals=tuple(
            FunctionContract.formal(name, scope_sorts[name]) for name in formal_names
        ),
        post=function_post,
        warrants=(
            Provenance(
                node_class=FunctionContract.node_class,
                construction_site=_proofir_construction_site(
                    return_stmt_frag,
                    memento_file,
                ),
                warrant=Stated(
                    locus=_proofir_construction_site(return_stmt_frag, memento_file)
                ),
            ),
        ),
        out_binding="out",
        out_sort=function_post.out_sort,
        source_warrants=[function_memento],
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


def _with_python_bytes_content_universe(formulas: list[Formula]) -> list[Formula]:
    """Make byte-literal return bodies participate in string-theory consistency.

    The SMT compiler unwraps ``python:bytes(<String const>)`` only when the
    call-result subject is string-tainted. A simple body post
    ``out == python:bytes("...")`` otherwise remains in the opaque term regime,
    so a lying assertion can equal the same call result to different bytes
    without contradiction. The extra predicate is content testimony for this
    byte-literal body; it does not claim anything about opaque byte expressions.
    """

    out = _Var("out")
    for formula in formulas:
        if not isinstance(formula, _Atomic) or formula.name != "=":
            continue
        if len(formula.args) != 2:
            continue
        left, right = formula.args
        if left == out and _is_python_bytes_literal_term(right):
            return [*formulas, _Atomic("str.is_ascii", (out,))]
        if right == out and _is_python_bytes_literal_term(left):
            return [*formulas, _Atomic("str.is_ascii", (out,))]
    return formulas


def _is_python_bytes_literal_term(term: Term) -> bool:
    return (
        isinstance(term, _Ctor)
        and term.name == "python:bytes"
        and len(term.args) == 1
        and isinstance(term.args[0], _ConstStr)
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
        bridge = BridgeAtom(
            source_contract=source_contract,
            target_symbol=target_symbol,
            target_contract=binding.get("name") if binding is not None else None,
            target_contract_cid=_binding_cid(binding) if binding is not None else None,
            call_site_locus=Locus(memento_file, item["line"], item["column"]),
        )
        edge = CallEdgeDecl(
            bridge=bridge,
            provenance=Provenance(
                node_class=CallEdgeDecl.node_class,
                construction_site=ConstructionSite(
                    path=memento_file,
                    line=item["line"],
                    column=item["column"],
                ),
                warrant=Derived(floor_chain=("literal-call-bridge",)),
            ),
        ).to_declaration()
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
    return AuditMemento(
        role=role,
        contract=contract_name,
        file=memento_file,
        source_function_name=fn.function_name(),
        loci=(
            AuditLocus(
                file=memento_file,
                line=stmt.line,
                col=stmt.col,
                status="warranted",
                ast_kind=ast_kind,
                role=role,
                contract=contract_name,
                source_memento=memento,
            ),
        ),
        provenance=Provenance(
            node_class=AuditMemento.node_class,
            construction_site=_proofir_construction_site(stmt, memento_file),
            warrant=Stated(locus=_proofir_construction_site(stmt, memento_file)),
        ),
    ).to_declaration()


def _walk_row(
    selected: str,
    ast_kind: str,
    stmt: SourceFragment,
    filename: str,
    memento: SourceMementoDto,
    output: str,
    *,
    requested_role: str = "term",
    emitted_formula: Mapping[str, Any] | None = None,
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
