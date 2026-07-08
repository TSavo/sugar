from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, NoReturn, TypeVar, cast

from sugar_lift_py_tests.factory.array_map_report import (
    _callsite_string,
    _function_source_memento,
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
    atomic,
    ctor,
    eq,
    make_var,
    str_const,
    term_to_value,
)
from sugar_lift_py_tests.canonicalizer import encode_jcs
from sugar_lift_py_tests.kit_rpc import (
    BodyUniverseDto,
    CallEdgeDto,
    DiagnosticDto,
    EffectDto,
    FactoryAuditDto,
    FactoryWalkCompleteRowDto,
    FactoryWalkRedRowDto,
    FactoryWalkRowDto,
    ImplicationDto,
    LiftReportPayloadDto,
    SourceAuditDto,
    SourceMementoDto,
    SourceSpanDto,
)
from sugar_lift_py_tests.kit_rpc.rpc_value import to_rpc_value
from sugar_lift_py_tests.effect import FactoryGapEffect, RuntimeEffect
from sugar_lift_py_tests.effect import effect_status
from sugar_lift_py_tests.floor import (
    DictLiteralValue,
    ImportAliasValue,
    LambdaCallable,
    PredicateValue,
)
from sugar_lift_py_tests.outcome import Incomplete, complete_value
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
from sugar_lift_py_tests.proofir.sorts import (
    Sort as ProofSort,
    StringSort,
    sort_from_ir,
)

from .dig_boundary import DigBoundary
from .floor_contract_agreement import (
    FloorContractAgreementViolation,
    enforce_floor_contract_agreement_gate,
    floor_contract_agreement_diagnostic,
    floor_contract_agreement_violations_for_fact,
)
from .factory_gap import FactoryGap
from .package_source_accounting import (
    package_source_audits_for_source,
    source_ledger_for_source_audits,
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


def _term_to_rpc(term: Term) -> dict[str, Any]:
    return json.loads(encode_jcs(term_to_value(term)))


def euf_callsite_name(callee_name: str, euf_term, *, suffix: str) -> str:
    """The ONE canonical ``#euf#`` contract name -- the single speller of the join key.

    ``suffix`` is ``"::assertion"`` (the sworn fact about a concrete call, keyed on its
    concrete arg terms) or ``"::universe"`` (the dig: ``f(args)``, the function over its
    formals, keyed on the callee). Byte-canonical by construction: cross-location facts
    coalesce ONLY by exact name match, so one speller is soundness, not style -- a single
    drifted byte sends a fact into a different universe and the contradiction is never
    computed (a green proof that lies)."""
    return f"{callee_name}#euf#{_canonical_term_sig(euf_term)}{suffix}"


# One lift, returned as six parallel lists: (contracts, source_mementos,
# source_audits, factory_walk_rows, call_edges, effects).
LiftResult = tuple[
    list[Any],
    list[SourceMementoDto],
    list[SourceAuditDto],
    list[FactoryWalkRowDto],
    list[CallEdgeDto],
    list[EffectDto],
]
_T = TypeVar("_T")


@dataclass(frozen=True)
class SourceReportBuild:
    payload: LiftReportPayloadDto


@dataclass(frozen=True)
class _PriorAssignmentEffect:
    site: SourceFragment
    incomplete: Incomplete


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
    source_audits: list[SourceAuditDto] = []
    factory_audits: list[FactoryAuditDto] = []
    factory_walk: list[FactoryWalkRowDto] = []
    call_edges: list[CallEdgeDto] = []
    implications: list[ImplicationDto] = []
    effects: list[EffectDto] = []
    dig_refusals: list[DigBoundary] = []
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
            lifted_contracts, mementos, audits, rows, edges, effect_rows = lifted
            contracts = _merge_contract_rows([*contracts, *lifted_contracts])
            source_mementos.extend(mementos)
            source_audits.extend(audits)
            factory_walk.extend(rows)
            call_edges.extend(edges)
            implications.extend(
                _precondition_implications_from_call_edges(
                    edges, contract_bindings or []
                )
            )
            effects.extend(effect_rows)
    if not contracts and not effects:
        return None
    materialized_contracts = _dedupe_rpc_rows(
        _materialize_contract_rows(contracts),
        _body_universe_key,
    )
    source_mementos = _dedupe_rpc_rows(source_mementos, _source_memento_key)
    source_audits.extend(
        package_source_audits_for_source(source=source, filename=filename)
    )
    source_audits = _dedupe_rpc_rows(source_audits, _small_rpc_row_key)
    factory_walk = _dedupe_factory_walk_rows(factory_walk)
    call_edges = _dedupe_rpc_rows(call_edges, _small_rpc_row_key)
    effects = _dedupe_rpc_rows(effects, _small_rpc_row_key)
    enforce_floor_contract_agreement_gate(agreement_violations)
    return SourceReportBuild(
        LiftReportPayloadDto(
            ir=materialized_contracts,
            source_mementos=source_mementos,
            source_ledger=source_ledger_for_source_audits(source_audits),
            source_audits=source_audits,
            factory_audits=factory_audits,
            factory_walk=factory_walk,
            effects=effects,
            call_edges=call_edges,
            implications=implications,
            # Each diagnostic producer stamps its own ad hoc dict shape (see
            # DiagnosticDto docstring); cast documents the open membrane
            # rather than pretending pyright verified per-producer fields.
            diagnostics=[
                cast(DiagnosticDto, refusal.to_json()) for refusal in dig_refusals
            ]
            + [
                cast(
                    DiagnosticDto,
                    floor_contract_agreement_diagnostic(agreement_violations),
                ),
                cast(
                    DiagnosticDto,
                    proofir_formula_provenance_diagnostic(
                        materialized_contracts, factory_walk
                    ),
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
            if name in _prior_binding_target_names(prior):
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


def _non_call_equality_runtime_reason(
    *, observed: str, requested: str, fix: str, blame: str
) -> str:
    if requested == "BoundNameEquality":
        return (
            "bound-name equality runtime boundary: "
            f"{observed} has binding or mutation history that is runtime state; "
            "keep as typed red until a proven-pure binding dig owns the assignment "
            f"history. replacement={requested}; fix={fix}; blame={blame}"
        )
    return (
        "literal-call equality runtime boundary: "
        f"{observed} is not a callsite, so no callee obligation can be minted; "
        "Python evaluates the expression at runtime. Keep as typed red until a "
        f"narrower equality sugar owns this shape. replacement={requested}; "
        f"fix={fix}; blame={blame}"
    )


def _assertion_runtime_reason(
    *, observed: str, requested: str, fix: str, blame: str
) -> str:
    return (
        "assertion runtime boundary: "
        f"{observed} cannot be reduced to a static assertion formula by the "
        "current factory catalog; Python evaluates this assertion at runtime. "
        f"replacement={requested}; fix={fix}; blame={blame}"
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
    dig_refusals: list[DigBoundary],
    agreement_violations: list[FloorContractAgreementViolation],
    factory_audits: list[FactoryAuditDto],
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
        observed = f"assert-test:{comparison.observed}"
        requested = "EqualityAssertion"
        fix = "lift this assertion shape or keep it as a typed runtime effect"
        return _effect_lift(
            stmt,
            fn,
            Incomplete(
                RuntimeEffect(
                    _assertion_runtime_reason(
                        observed=observed,
                        requested=requested,
                        fix=fix,
                        blame=f"{memento_file}:{stmt.line}:{stmt.col}",
                    )
                )
            ),
            stmt=stmt,
            selected="AssertionRuntimeEffect",
            requested_role=requested,
            filename=filename,
            memento_file=memento_file,
            source_lines=source_lines,
        )
    if (
        comparison.compare_ops()[0] != "Eq"
        or len(comparison.compare_comparators()) != 1
    ):
        observed = f"assert-compare-op:{comparison.compare_ops()[0]}"
        requested = "EqualityAssertion"
        fix = "lift non-`==` comparison assertions or keep them typed red"
        return _effect_lift(
            stmt,
            fn,
            Incomplete(
                RuntimeEffect(
                    _assertion_runtime_reason(
                        observed=observed,
                        requested=requested,
                        fix=fix,
                        blame=f"{memento_file}:{stmt.line}:{stmt.col}",
                    )
                )
            ),
            stmt=stmt,
            selected="AssertionRuntimeEffect",
            requested_role=requested,
            filename=filename,
            memento_file=memento_file,
            source_lines=source_lines,
        )
    comparison_left = _resolve_bound_lhs(comparison.compare_left(), fn)
    callee_name = _callee_name(comparison_left, import_aliases, from_imports)
    if callee_name is None:
        observed, requested, fix = _non_call_equality_lhs_gap(
            comparison_left, fn=fn, stmt=stmt
        )
        return _effect_lift(
            comparison_left,
            fn,
            Incomplete(
                RuntimeEffect(
                    _non_call_equality_runtime_reason(
                        observed=observed,
                        requested=requested,
                        fix=fix,
                        blame=(
                            f"{memento_file}:"
                            f"{comparison_left.line}:{comparison_left.col}"
                        ),
                    )
                )
            ),
            stmt=stmt,
            selected=(
                "BoundNameEqualityRuntimeEffect"
                if requested == "BoundNameEquality"
                else "CallsiteEqualityRuntimeEffect"
            ),
            requested_role=requested,
            filename=filename,
            memento_file=memento_file,
            source_lines=source_lines,
        )

    universe: LiftResult | None = None
    universe_factory_audits: list[FactoryAuditDto] = []
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
    if isinstance(assertion_ctx, _PriorAssignmentEffect):
        return _prior_assignment_effect_lift(
            assertion_ctx,
            fn=fn,
            filename=filename,
            memento_file=memento_file,
            source_lines=source_lines,
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
        contract_bindings=contract_bindings,
        emit_call_edge=_should_emit_stated_call_edge(
            functions_by_name,
            callee_name,
            universe=universe,
            derived_literal_call=derived_literal_call,
        ),
    )
    factory_audits.extend(universe_factory_audits)
    return _merge_many(
        [
            lift
            for lift in (universe, derived_literal_call, assertion)
            if lift is not None
        ]
    )


def _should_emit_stated_call_edge(
    functions_by_name: dict[str, SourceFragment],
    callee_name: str,
    *,
    universe: LiftResult | None,
    derived_literal_call: LiftResult | None,
) -> bool:
    if derived_literal_call is not None:
        return False
    if universe is None:
        return True
    callee = functions_by_name.get(callee_name)
    return (
        callee is not None and getattr(callee.node, "_sugar_source", None) is not None
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
    factory_audits: list[FactoryAuditDto],
    dig_refusals: list[DigBoundary],
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
    if isinstance(ctx, _PriorAssignmentEffect):
        return _prior_assignment_effect_lift(
            ctx,
            fn=fn,
            filename=filename,
            memento_file=memento_file,
            source_lines=source_lines,
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
    if isinstance(formula, Incomplete):
        return _effect_lift(
            stmt,
            fn,
            formula,
            stmt=stmt,
            selected=result.audit_row.selected or type(result.sugar).__name__,
            requested_role="AssertionSurface",
            filename=filename,
            memento_file=memento_file,
            source_lines=source_lines,
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
        lifted = (
            lifted[0],
            lifted[1],
            lifted[2],
            lifted[3],
            [*lifted[4], *edges],
            lifted[5],
        )
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
    dig_refusals: list[DigBoundary],
    agreement_violations: list[FloorContractAgreementViolation],
    factory_audits: list[FactoryAuditDto],
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
    factory_audits: list[FactoryAuditDto] | None = None,
) -> FactoryBuildContext | _PriorAssignmentEffect:
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
) -> FactoryBuildContext | _PriorAssignmentEffect:
    from sugar_lift_py_tests.sugar.block_sugar import BlockSugar

    priors = _needed_prior_assignment_sites(module_statements, fn, stmt)
    if not priors:
        return ctx
    folded_ctx = ctx
    for prior in priors:
        if prior.observed in {"Import", "ImportFrom"}:
            imported = _ctx_with_prior_import_bindings(prior, folded_ctx)
            if isinstance(imported, _PriorAssignmentEffect):
                return imported
            folded_ctx = imported
            continue
        block = BlockSugar(
            statements=(folded_ctx.build_body(prior, SugarRole.STATEMENT),),
            blame=prior.blame,
        )
        folded = block.fold_with_context(folded_ctx)
        if isinstance(folded.outcome, Incomplete):
            return _PriorAssignmentEffect(site=prior, incomplete=folded.outcome)
        complete_value(
            folded.outcome,
            owner="literal_call_report.prior_assignment_block",
        )
        folded_ctx = folded.ctx
    return folded_ctx


def _ctx_with_prior_import_bindings(
    prior: SourceFragment,
    ctx: FactoryBuildContext,
) -> FactoryBuildContext | _PriorAssignmentEffect:
    from sugar_lift_py_tests.temporal import bind_temporal

    folded_ctx = ctx
    for alias in prior.fragments():
        if alias.observed != "alias":
            continue
        body = folded_ctx.build_body(alias, SugarRole.TERM)
        outcome = body.reduce(folded_ctx)
        if isinstance(outcome, Incomplete):
            return _PriorAssignmentEffect(site=alias, incomplete=outcome)
        value = complete_value(
            outcome,
            owner="literal_call_report.prior_import_alias",
        )
        if not isinstance(value, ImportAliasValue):
            raise TypeError(
                "AliasSugar built non-import alias binding "
                f"{type(value).__name__} at {alias.blame}"
            )
        folded_ctx = bind_temporal(
            folded_ctx,
            value.bound_name,
            value,
            owner="AliasSugar",
            blame=alias.blame,
        )
    return folded_ctx


def _needed_prior_assignment_sites(
    module_statements: list[SourceFragment],
    fn: SourceFragment,
    stmt: SourceFragment,
) -> list[SourceFragment]:
    needed_names = set(_names_including_self(stmt))
    selected: list[SourceFragment] = []
    for prior in reversed(_prior_assignment_sites(module_statements, fn, stmt)):
        names = _prior_binding_target_names(prior)
        if not names or needed_names.isdisjoint(names):
            continue
        selected.append(prior)
        needed_names.update(_prior_binding_value_names(prior))
    return list(reversed(selected))


def _prior_binding_value_names(site: SourceFragment) -> set[str]:
    if site.observed != "Assign":
        return set()
    return set(_names_including_self(site.assign_value()))


def _prior_binding_target_names(site: SourceFragment) -> set[str]:
    if site.observed == "Assign":
        name = site.assign_target_name()
        if name is not None:
            return {name}
        receiver_name = site.assign_target_attribute_receiver_name()
        if receiver_name is not None:
            return {receiver_name}
        targets = site.assign_targets()
        if len(targets) == 1 and targets[0].observed == "Tuple":
            return {
                item.name_id() for item in targets[0].terms() if item.observed == "Name"
            }
        return set()
    if site.observed == "Import":
        return {asname or name for name, asname in site.import_names()}
    if site.observed == "ImportFrom" and site.importfrom_level() == 0:
        return {asname or name for name, asname in site.importfrom_names()}
    return set()


def _prior_assignment_names(
    module_statements: list[SourceFragment],
    fn: SourceFragment,
    stmt: SourceFragment,
) -> set[str]:
    names: set[str] = set()
    for prior in _prior_assignment_sites(module_statements, fn, stmt):
        names.update(_prior_binding_target_names(prior))
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
    value = _literal_floor_via_factory(frag, filename, ctx=ctx)
    if isinstance(value, Incomplete):
        raise TypeError(
            "callsite literal reduced to a typed effect: " f"{value.reason}"
        )
    return floor_to_term(value, owner="literal_call_report")


def _literal_floor_via_factory(
    frag: SourceFragment, filename: str, *, ctx: FactoryBuildContext | None = None
):
    from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
    from sugar_lift_py_tests.claim import SugarRole as _Role

    from .build import default_catalog

    ctx = ctx or FactoryBuildContext(filename=filename, catalog=default_catalog())
    body = ctx.build_body(frag, _Role.TERM)
    outcome = body.reduce(ctx)
    if isinstance(outcome, Incomplete):
        return outcome
    return complete_value(outcome, owner="callsite literal")


def _effect_lift(
    frag: SourceFragment,
    fn: SourceFragment,
    incomplete: Incomplete,
    *,
    stmt: SourceFragment,
    selected: str,
    requested_role: str,
    filename: str,
    memento_file: str,
    source_lines: list[str],
) -> LiftResult:
    effect_name = (
        f"{Path(memento_file).stem}::{fn.function_name()}::"
        f"effect:{frag.line}:{frag.col}"
    )
    memento = _statement_source_memento(
        stmt,
        fn,
        memento_file,
        source_lines,
        contract_name=effect_name,
        role="python.literal-call-sugar",
    )
    walk = FactoryWalkRedRowDto(
        file=filename,
        line=frag.line,
        requested_role=requested_role,
        ast_kind=frag.observed,
        selected=selected,
        status=effect_status(incomplete.effect),
        output={"effect": type(incomplete.effect).__name__},
        source_memento=memento,
        span=SourceSpanDto(
            start_line=frag.line,
            start_col=frag.col,
            end_line=frag.end_line,
            end_col=frag.end_col,
        ),
        reason=incomplete.reason,
    )
    return (
        [],
        [memento],
        [],
        [walk],
        [],
        [EffectDto(name=effect_name, effect=incomplete.effect, source_memento=memento)],
    )


def _prior_assignment_effect_lift(
    prior: _PriorAssignmentEffect,
    *,
    fn: SourceFragment,
    filename: str,
    memento_file: str,
    source_lines: list[str],
) -> LiftResult:
    return _effect_lift(
        prior.site,
        fn,
        prior.incomplete,
        stmt=prior.site,
        selected="PriorAssignmentTypedEffect",
        requested_role="PriorAssignmentBlock",
        filename=filename,
        memento_file=memento_file,
        source_lines=source_lines,
    )


def _proofir_effect_lift(
    frag: SourceFragment,
    fn: SourceFragment,
    *,
    stmt: SourceFragment,
    observed: str,
    requested: str,
    fix: str,
    filename: str,
    memento_file: str,
    source_lines: list[str],
) -> LiftResult:
    from .factory_gap_info import GapKind, GapLocus

    return _effect_lift(
        frag,
        fn,
        Incomplete(
            FactoryGapEffect(
                owner="literal_call_report.equality_fact",
                blame=(f"{memento_file}:{stmt.line}:{stmt.col}"),
                observed=observed,
                requested=requested,
                fix=fix,
                gap_kind=GapKind.PROOFIR,
                gap_locus=GapLocus.CONSTRUCTION_LAW,
            )
        ),
        stmt=stmt,
        selected="TypedEffect",
        requested_role="ProofIRConstructionLaw",
        filename=filename,
        memento_file=memento_file,
        source_lines=source_lines,
    )


def _free_vars_in_ir_term(term: Term) -> frozenset[str]:
    if isinstance(term, _Var):
        return frozenset({term.name})
    if isinstance(term, _Ctor):
        return frozenset().union(*(_free_vars_in_ir_term(arg) for arg in term.args))
    return frozenset()


def _free_vars_in_ir_formula(formula: Formula) -> frozenset[str]:
    if isinstance(formula, _Atomic):
        return frozenset().union(*(_free_vars_in_ir_term(arg) for arg in formula.args))
    if isinstance(formula, _Connective):
        return frozenset().union(
            *(_free_vars_in_ir_formula(operand) for operand in formula.operands)
        )
    if isinstance(formula, _Quantifier):
        return _free_vars_in_ir_formula(formula.body) - {formula.name}
    return frozenset()


def _open_universe_vars(formulas: list[Formula], bound: set[str]) -> frozenset[str]:
    return (
        frozenset().union(*(_free_vars_in_ir_formula(formula) for formula in formulas))
        - bound
    )


def _is_open_byte_support_universe(formulas: list[Formula], bound: set[str]) -> bool:
    open_vars = _open_universe_vars(formulas, bound)
    return bool(open_vars) and all(name.startswith("byte_") for name in open_vars)


def _record_open_universe_refusal(
    dig_refusals: list[DigBoundary],
    *,
    callee: SourceFragment,
    formulas: list[Formula],
    bound: set[str],
) -> bool:
    open_vars = _open_universe_vars(formulas, bound)
    if not open_vars:
        return False
    _record_dig_refusal(
        dig_refusals,
        callee=callee.function_name(),
        blame=callee.blame,
        caught=ValueError(
            f"open non-formal variable(s): {', '.join(sorted(open_vars))}"
        ),
        reason=(
            "function universe body walker refused open non-formal variables; "
            "declare globals as formals or leave the callsite axiomatic"
        ),
    )
    return True


def _open_equality_fact_vars(arg_terms: list[Term], value_term: Term) -> frozenset[str]:
    return frozenset().union(
        _free_vars_in_ir_term(value_term),
        *(_free_vars_in_ir_term(arg_term) for arg_term in arg_terms),
    )


_COMPUTABLE_NUMPY_INTEGER_UFUNCS = frozenset(
    {
        "numpy.add",
        "numpy.floor_divide",
        "numpy.maximum",
        "numpy.minimum",
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
    if callee_name in _COMPUTABLE_NUMPY_FLOAT_UFUNCS:
        return _numpy_float_literal_call_derived_fact(
            stmt,
            callee_name=callee_name,
            callsite=callsite,
            fn=fn,
            filename=filename,
            memento_file=memento_file,
            source_lines=source_lines,
            ctx=ctx,
            call_return_sort=call_return_sort,
        )
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


_COMPUTABLE_NUMPY_FLOAT_UFUNCS = frozenset({"numpy.divide"})


def _numpy_float_literal_call_derived_fact(
    stmt: SourceFragment,
    *,
    callee_name: str,
    callsite: SourceFragment,
    fn: SourceFragment,
    filename: str,
    memento_file: str,
    source_lines: list[str],
    ctx: FactoryBuildContext,
    call_return_sort: ProofSort | None,
) -> LiftResult | None:
    """Emit the kit-computed sibling for ``numpy.divide`` over literal numeric
    operands.

    Boundary: division is IEEE-754 true division, not numpy execution -- both
    operands must reduce through the factory into the kit's own
    ``TermValue(int | float)`` floor values, and the quotient is Python's own
    ``/`` on the resulting floats (identical bit pattern to numpy's float64
    ``true_divide`` for finite operands). Division by zero is a permanent
    stop-line here: numpy's IEEE inf/nan/RuntimeWarning behavior is not
    reproduced, so a zero divisor returns ``None`` and the callsite falls back
    to the ordinary opaque assertion rather than fabricating a floored value.
    """
    if len(callsite.call_args()) != 2 or callsite.call_keywords():
        return None

    values: list[int | float] = []
    arg_terms: list[Term] = []
    for arg_frag in callsite.call_args():
        value = _numeric_floor_for_numpy_literal_arg(arg_frag, ctx=ctx)
        if value is None:
            return None
        values.append(value)
        arg_terms.append(_lift_literal_via_factory(arg_frag, filename, ctx=ctx))

    left, right = values
    if right == 0:
        # Stop-line: division by zero is not computed here. Fabricating
        # numpy's inf/nan/RuntimeWarning semantics without a floor for them
        # would be a lie dressed as a Derived fact.
        return None
    result = left / right

    from sugar_lift_py_tests.floor import TermValue

    return _emit_euf_fact(
        stmt,
        fn,
        callee_name,
        arg_terms,
        TermValue(result).to_term(owner="literal_call_report.numpy_float_ufunc"),
        filename=filename,
        memento_file=memento_file,
        source_lines=source_lines,
        warrant=Derived(
            floor_chain=("literal_call_report.numpy_float_ufunc", callee_name)
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
    elif callee_name == "numpy.maximum":
        result = max(left, right)
    elif callee_name == "numpy.minimum":
        result = min(left, right)
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
    outcome = body.reduce(ctx)
    if isinstance(outcome, Incomplete):
        return None
    value = complete_value(outcome, owner="literal_call_report.numpy_integer_ufunc_arg")
    if not isinstance(value, TermValue):
        return None
    if type(value.value) is not int:
        return None
    if not _fits_numpy_int64(value.value):
        return None
    return value.value


def _numeric_floor_for_numpy_literal_arg(
    frag: SourceFragment,
    *,
    ctx: FactoryBuildContext,
) -> int | float | None:
    """Like ``_integer_floor_for_numpy_literal_arg`` but admits float floors
    too, for the float-semantics ufuncs (``numpy.divide``). Ints stay ints
    (Python promotes on ``/`` regardless); non-numeric floors return None."""
    from sugar_lift_py_tests.floor import TermValue

    body = ctx.build_body(frag, SugarRole.TERM)
    outcome = body.reduce(ctx)
    if isinstance(outcome, Incomplete):
        return None
    value = complete_value(outcome, owner="literal_call_report.numpy_float_ufunc_arg")
    if not isinstance(value, TermValue):
        return None
    if type(value.value) not in (int, float):
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
    contract_bindings: list | None = None,
    emit_call_edge: bool = True,
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
    expected_frag = comparison.compare_comparators()[0]
    expected_value = _literal_floor_via_factory(expected_frag, filename, ctx=ctx)
    if isinstance(expected_value, Incomplete):
        return _effect_lift(
            expected_frag,
            fn,
            expected_value,
            stmt=stmt,
            selected="TypedEffect",
            requested_role="CallsiteExpected",
            filename=filename,
            memento_file=memento_file,
            source_lines=source_lines,
        )
    if isinstance(expected_value, PredicateValue):
        return _effect_lift(
            expected_frag,
            fn,
            Incomplete(
                RuntimeEffect(
                    "callsite expected runtime boundary: "
                    f"{type(expected_value).__name__} cannot be projected to a "
                    "ProofIR term for callsite equality; Python evaluates this "
                    "expected expression at runtime. Keep as typed red until a "
                    "boolean-expression term floor owns predicate-valued RHS "
                    f"assertions. replacement=CallsiteExpected; "
                    "fix=add a ProofIR term projection for PredicateValue "
                    "or keep predicate RHS assertions as a typed effect; "
                    f"blame={memento_file}:{expected_frag.line}:{expected_frag.col}"
                )
            ),
            stmt=stmt,
            selected="CallsiteExpectedRuntimeEffect",
            requested_role="CallsiteExpected",
            filename=filename,
            memento_file=memento_file,
            source_lines=source_lines,
        )
    expected_term = floor_to_term(expected_value, owner="literal_call_report")
    # Each arg composes through the factory's literal sugars (string, int, array,
    # ...) -- the same path as the expected. A literal the catalog reduces but can't
    # yet shape into a term is kept as typed red so one opaque arg cannot kill the
    # report.
    arg_terms = []
    edge_target_symbol: str | None = None
    receiver = callsite.call_receiver()
    if receiver is not None and callee_name == callsite.call_target_name():
        try:
            receiver_value = _literal_floor_via_factory(receiver, filename, ctx=ctx)
            if isinstance(receiver_value, Incomplete):
                return _effect_lift(
                    receiver,
                    fn,
                    receiver_value,
                    stmt=stmt,
                    selected="TypedEffect",
                    requested_role="CallsiteReceiver",
                    filename=filename,
                    memento_file=memento_file,
                    source_lines=source_lines,
                )
            arg_terms.append(
                floor_to_term(receiver_value, owner="literal_call_report.receiver")
            )
            edge_target_symbol = f"method:{callee_name}"
        except (OverflowError, RuntimeError, TypeError, ValueError) as exc:
            return _effect_lift(
                receiver,
                fn,
                Incomplete(
                    RuntimeEffect(
                        "callsite receiver runtime boundary: "
                        "crime=method receiver could not be projected to a "
                        "ProofIR term; "
                        "owner=literal_call_report; "
                        f"shape=receiver:{receiver.observed}-unliftable; "
                        "replacement=route receiver identity through the alias "
                        "floor or keep this method callsite as typed red; "
                        f"{exc}; "
                        f"blame={memento_file}:{receiver.line}:{receiver.col}"
                    )
                ),
                stmt=stmt,
                selected="CallsiteReceiverRuntimeEffect",
                requested_role="CallsiteReceiver",
                filename=filename,
                memento_file=memento_file,
                source_lines=source_lines,
            )
    for arg_frag in callsite.call_args():
        try:
            arg_value = _literal_floor_via_factory(arg_frag, filename, ctx=ctx)
            if isinstance(arg_value, Incomplete):
                return _effect_lift(
                    arg_frag,
                    fn,
                    arg_value,
                    stmt=stmt,
                    selected="TypedEffect",
                    requested_role="CallsiteArg",
                    filename=filename,
                    memento_file=memento_file,
                    source_lines=source_lines,
                )
            arg_terms.append(floor_to_term(arg_value, owner="literal_call_report"))
        except TypeError as exc:
            return _effect_lift(
                arg_frag,
                fn,
                Incomplete(
                    RuntimeEffect(
                        "callsite argument runtime boundary: "
                        "crime=callsite argument could not be projected to a "
                        "ProofIR term; "
                        "owner=literal_call_report; "
                        f"shape=callsite-arg:{arg_frag.observed}-unliftable; "
                        "replacement=add a cited floor projection for this "
                        "call-arg shape or keep the assertion as typed red; "
                        f"{exc}; "
                        f"blame={memento_file}:{arg_frag.line}:{arg_frag.col}"
                    )
                ),
                stmt=stmt,
                selected="CallsiteArgRuntimeEffect",
                requested_role="CallsiteArg",
                filename=filename,
                memento_file=memento_file,
                source_lines=source_lines,
            )
    for keyword in callsite.call_keywords():
        name = keyword.keyword_arg_name()
        keyword_frag = keyword.keyword_value()
        if name is None:
            return _effect_lift(
                keyword_frag,
                fn,
                Incomplete(
                    RuntimeEffect(
                        "callsite keyword runtime boundary: **kwargs expansion "
                        "cannot be statically bound to imported contract formals; "
                        "Python resolves the keyword set at runtime. Keep as "
                        "typed red until double-star callsite binding sugar owns "
                        f"the shape. replacement=CallsiteKeywordActuals; "
                        f"blame={memento_file}:{keyword.line}:{keyword.col}"
                    )
                ),
                stmt=stmt,
                selected="CallsiteKeywordRuntimeEffect",
                requested_role="CallsiteKeywordActuals",
                filename=filename,
                memento_file=memento_file,
                source_lines=source_lines,
            )
        keyword_value = None
        try:
            keyword_value = _literal_floor_via_factory(keyword_frag, filename, ctx=ctx)
            if isinstance(keyword_value, Incomplete):
                return _effect_lift(
                    keyword_frag,
                    fn,
                    keyword_value,
                    stmt=stmt,
                    selected="TypedEffect",
                    requested_role="CallsiteKeywordActual",
                    filename=filename,
                    memento_file=memento_file,
                    source_lines=source_lines,
                )
            if isinstance(keyword_value, LambdaCallable):
                return _effect_lift(
                    keyword_frag,
                    fn,
                    Incomplete(
                        RuntimeEffect(
                            "callsite keyword runtime boundary: "
                            "crime=callsite keyword could not be projected to a "
                            "ProofIR term; "
                            "owner=literal_call_report; "
                            f"shape=kw:{name}:LambdaCallable-unliftable; "
                            "replacement=add a cited callable identity floor for "
                            "keyword values or keep the assertion as typed red; "
                            f"blame={memento_file}:{keyword_frag.line}:{keyword_frag.col}"
                        )
                    ),
                    stmt=stmt,
                    selected="CallsiteKeywordRuntimeEffect",
                    requested_role="CallsiteKeywordActual",
                    filename=filename,
                    memento_file=memento_file,
                    source_lines=source_lines,
                )
            arg_terms.append(
                ctor(
                    f"kw:{name}",
                    [
                        floor_to_term(
                            keyword_value, owner=f"literal_call_report kw:{name}"
                        )
                    ],
                )
            )
        except TypeError as exc:
            keyword_shape = (
                type(keyword_value).__name__
                if keyword_value is not None
                else keyword_frag.observed
            )
            return _effect_lift(
                keyword_frag,
                fn,
                Incomplete(
                    RuntimeEffect(
                        "callsite keyword runtime boundary: "
                        "crime=callsite keyword could not be projected to a "
                        "ProofIR term; "
                        "owner=literal_call_report; "
                        f"shape=kw:{name}:{keyword_shape}-unliftable; "
                        "replacement=add a cited floor projection for this "
                        "keyword value or keep the assertion as typed red; "
                        f"{exc}; "
                        f"blame={memento_file}:{keyword_frag.line}:{keyword_frag.col}"
                    )
                ),
                stmt=stmt,
                selected="CallsiteKeywordRuntimeEffect",
                requested_role="CallsiteKeywordActual",
                filename=filename,
                memento_file=memento_file,
                source_lines=source_lines,
            )
    if isinstance(expected_value, DictLiteralValue):
        return _emit_dict_literal_callsite_facts(
            stmt,
            fn,
            callee_name,
            arg_terms,
            expected_value,
            filename=filename,
            memento_file=memento_file,
            source_lines=source_lines,
            warrant=Stated(locus=_proofir_construction_site(stmt, memento_file)),
            callsite=callsite,
            emit_call_edge=emit_call_edge,
            call_return_sort=call_return_sort,
            contract_bindings=contract_bindings or [],
            include_whole_call_fact=True,
            edge_target_symbol=edge_target_symbol,
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
        callsite=callsite,
        emit_call_edge=emit_call_edge,
        call_return_sort=call_return_sort,
        contract_bindings=contract_bindings or [],
        edge_target_symbol=edge_target_symbol,
    )


def _emit_dict_literal_callsite_facts(
    stmt: SourceFragment,
    fn: SourceFragment,
    callee_name: str,
    arg_terms: list[Term],
    value: DictLiteralValue,
    *,
    filename: str,
    memento_file: str,
    source_lines: list[str],
    warrant: Stated | Derived,
    callsite: SourceFragment | None = None,
    emit_call_edge: bool = False,
    call_return_sort: ProofSort | None = None,
    contract_bindings: list | None = None,
    include_whole_call_fact: bool,
    edge_target_symbol: str | None = None,
) -> LiftResult:
    from sugar_lift_py_tests.floor import TermValue

    lifts: list[LiftResult] = []
    if include_whole_call_fact:
        lifts.append(
            _emit_euf_fact(
                stmt,
                fn,
                callee_name,
                arg_terms,
                value.to_term(owner="literal_call_report.dict_literal"),
                filename=filename,
                memento_file=memento_file,
                source_lines=source_lines,
                warrant=warrant,
                callsite=callsite,
                emit_call_edge=emit_call_edge,
                call_return_sort=call_return_sort,
                contract_bindings=contract_bindings or [],
                edge_target_symbol=edge_target_symbol,
            )
        )
    entries = _canonical_dict_entries(value)
    lifts.append(
        _emit_euf_fact(
            stmt,
            fn,
            f"{callee_name}.__dict_len__",
            arg_terms,
            floor_to_term(
                TermValue(len(entries)),
                owner="literal_call_report.dict_literal_len",
            ),
            filename=filename,
            memento_file=memento_file,
            source_lines=source_lines,
            warrant=warrant,
            call_return_sort=IntSort(),
        )
    )
    for key_term, value_term in entries:
        lifts.append(
            _emit_euf_fact(
                stmt,
                fn,
                f"{callee_name}.__dict_getitem__",
                [*arg_terms, key_term],
                value_term,
                filename=filename,
                memento_file=memento_file,
                source_lines=source_lines,
                warrant=warrant,
                call_return_sort=_dict_read_sort(value_term, callee_name=callee_name),
            )
        )
    return _merge_many(lifts)


def _canonical_dict_entries(value: DictLiteralValue) -> tuple[tuple[Term, Term], ...]:
    by_key: dict[str, tuple[Term, Term]] = {}
    for key_term, value_term in value.entries:
        by_key[_canonical_term_sig(key_term)] = (key_term, value_term)
    return tuple(pair for _sig, pair in sorted(by_key.items()))


def _dict_read_sort(term: Term, *, callee_name: str) -> ProofSort:
    return _known_term_sort(term) or UnknownSort(
        reason=f"no declared dict read return sort available for call:{callee_name}"
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
    callsite: SourceFragment | None = None,
    emit_call_edge: bool = False,
    call_return_sort: ProofSort | None = None,
    contract_bindings: list | None = None,
    edge_target_symbol: str | None = None,
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

    call_sort = call_return_sort or UnknownSort(
        reason=f"no function-contract return sort available for call:{callee_name}"
    )
    open_vars = _open_equality_fact_vars(list(arg_terms), value_term)
    if open_vars:
        return _proofir_effect_lift(
            stmt,
            fn,
            stmt=stmt,
            observed=f"open term variable(s): {', '.join(sorted(open_vars))}",
            requested="closed EqualityFact terms",
            fix=(
                "route symbolic/open callsite facts through a scoped ProofIR "
                "member or emit a typed effect; do not construct EqualityFact "
                "from open terms"
            ),
            filename=filename,
            memento_file=memento_file,
            source_lines=source_lines,
        )
    rhs_term = term_from_ir(value_term, sort=call_sort)
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
        reason=(
            "derived from callsite floor" if isinstance(warrant, Derived) else None
        ),
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
    edges: list[CallEdgeDto] = []
    if emit_call_edge:
        if callsite is None:
            raise TypeError("emit_call_edge requires callsite")
        target_symbol = edge_target_symbol or f"call:{callee_name}"
        binding = _binding_for_bridge_symbol(
            contract_bindings or [], target_symbol, arg_terms=list(arg_terms)
        )
        formal_actuals = _formal_actuals_for_binding(binding, list(arg_terms))
        edges.append(
            CallEdgeDecl(
                bridge=BridgeAtom(
                    source_contract=contract_name,
                    target_symbol=target_symbol,
                    target_contract=(
                        binding.get("name") if binding is not None else None
                    ),
                    target_contract_cid=(
                        _binding_cid(binding) if binding is not None else None
                    ),
                    target_proof_cid=(
                        _binding_proof_cid(binding) if binding is not None else None
                    ),
                    call_site_locus=Locus(memento_file, callsite.line, callsite.col),
                    formal_actuals=formal_actuals,
                ),
                provenance=Provenance(
                    node_class=CallEdgeDecl.node_class,
                    construction_site=_proofir_construction_site(stmt, memento_file),
                    warrant=Derived(floor_chain=("literal-callsite-assertion",)),
                ),
            ).to_declaration()
        )
    return (
        [EqualityFactEmission(member, (memento,))],
        [memento],
        [audit],
        [walk],
        edges,
        [],
    )


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
            status="proofir-gap",
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
    return ([contract], [memento], [audit], [walk], [], [])


def _empty_lift() -> LiftResult:
    return ([], [], [], [], [], [])


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


def _dedupe_rpc_rows(rows: list[_T], key_fn: Callable[[_T], object]) -> list[_T]:
    out: list[_T] = []
    seen: set[object] = set()
    for row in rows:
        key = key_fn(row)
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def _dedupe_factory_walk_rows(
    rows: list[FactoryWalkRowDto],
) -> list[FactoryWalkRowDto]:
    out: list[FactoryWalkRowDto] = []
    by_merge_key: dict[object, int] = {}
    seen_exact: set[object] = set()
    for row in rows:
        exact_key = _factory_walk_key(row)
        if exact_key in seen_exact:
            continue
        merge_key = _factory_walk_merge_key(row)
        if merge_key is not None and merge_key in by_merge_key:
            index = by_merge_key[merge_key]
            out[index] = _merge_factory_walk_row(out[index], row)
            seen_exact.add(exact_key)
            continue
        seen_exact.add(exact_key)
        if merge_key is not None:
            by_merge_key[merge_key] = len(out)
        out.append(row)
    return out


def _factory_walk_merge_key(row: FactoryWalkRowDto) -> object | None:
    if row.emitted_formula is None:
        return None
    return (
        row.file,
        row.line,
        row.requested_role,
        row.ast_kind,
        row.selected,
        row.status,
        row.occurrences,
        _stable_json(row.output),
        _source_memento_key(row.source_memento),
        _stable_json(row.span),
        _stable_json(row.emitted_formula),
    )


def _merge_factory_walk_row(
    left: FactoryWalkRowDto, right: FactoryWalkRowDto
) -> FactoryWalkRowDto:
    if _factory_walk_merge_key(left) != _factory_walk_merge_key(right):
        raise ValueError("factory walk rows have different semantic keys")
    reasons = [reason for reason in (left.reason, right.reason) if reason]
    reason = "; ".join(dict.fromkeys(reasons)) or None
    return replace(left, reason=reason)


def _body_universe_key(row: BodyUniverseDto) -> object:
    rpc = row.to_rpc()
    return (
        rpc.get("kind"),
        rpc.get("name"),
        rpc.get("outBinding"),
        tuple(rpc.get("formals") or ()),
        rpc.get("bridgeSourceSymbol"),
        _stable_json(rpc.get("pre")),
        _stable_json(rpc.get("post")),
        _stable_json(rpc.get("inv")),
        _stable_json(rpc.get("sourceWarrants")),
        _stable_json(rpc.get("warrantedBy")),
    )


def _source_memento_key(row: SourceMementoDto | dict[str, Any]) -> object:
    rpc = to_rpc_value(row)
    return (
        rpc.get("file"),
        _stable_json(rpc.get("span")),
        rpc.get("source_cid") or rpc.get("sourceCid"),
        rpc.get("template_cid") or rpc.get("templateCid"),
        rpc.get("source_function_name") or rpc.get("sourceFunctionName"),
        rpc.get("role"),
        rpc.get("claimName"),
        rpc.get("contractName"),
        tuple(rpc.get("param_names") or rpc.get("paramNames") or ()),
    )


def _factory_walk_key(row: FactoryWalkRowDto) -> object:
    return (
        row.file,
        row.line,
        row.requested_role,
        row.ast_kind,
        row.selected,
        row.status,
        row.reason,
        row.occurrences,
        _stable_json(row.output),
        _source_memento_key(row.source_memento),
        _stable_json(row.span),
        _stable_json(row.emitted_formula),
    )


def _small_rpc_row_key(row: object) -> object:
    return _stable_json(to_rpc_value(row))


def _stable_json(value: Any) -> str:
    return json.dumps(to_rpc_value(value), sort_keys=True, separators=(",", ":"))


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
    dig_refusals: list[DigBoundary],
    agreement_violations: list[FloorContractAgreementViolation],
    factory_audits: list[FactoryAuditDto],
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
            callable_contract = callable_contracts.get(f"call:{call_value.target_name}")
            call_return_sort = (
                callable_contract.out_sort if callable_contract is not None else None
            )
            if isinstance(floor, DictLiteralValue):
                facts.append(
                    _emit_dict_literal_callsite_facts(
                        stmt,
                        caller_fn,
                        call_value.target_name,
                        arg_terms,
                        floor,
                        filename=filename,
                        memento_file=memento_file,
                        source_lines=source_lines,
                        warrant=Derived(
                            floor_chain=(
                                "literal_call_report.callsite_dict_floor",
                                call_value.target_name,
                            )
                        ),
                        call_return_sort=call_return_sort,
                        include_whole_call_fact=not immediate_emitted,
                    )
                )
                return
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
                    ctx=cast(Any, reduce_ctx),
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
    dig_refusals: list[DigBoundary],
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
    dig_refusals: list[DigBoundary],
    factory_audits: list[FactoryAuditDto],
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
    from .sugar_constructors import (
        IncompleteFunctionBody,
        build_control_flow_body_sugar,
    )

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
    except (TypeError, ValueError, FactoryGap, IncompleteFunctionBody) as exc:
        fallback = _urlsafe_translate_function_universe(
            callee,
            callee_name,
            filename=filename,
            memento_file=memento_file,
            source_lines=source_lines,
        )
        if fallback is not None:
            return fallback
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
    _universe_formulas = _with_python_number_sort_universe(_universe_formulas)
    _universe_formulas = _with_python_bytes_content_universe(_universe_formulas)
    if _is_open_byte_support_universe(_universe_formulas, _universe_bound):
        _record_dig_refusal(
            dig_refusals,
            callee=callee.function_name(),
            blame=callee.blame,
            caught=ValueError(
                "naked ord-byte body has no enclosing str.eq-bv-blocks universe"
            ),
            reason=(
                "function universe body walker refused open ord-byte support; "
                "concrete callsite projection may still derive the byte value"
            ),
        )
        return None
    if _record_open_universe_refusal(
        dig_refusals,
        callee=callee,
        formulas=_universe_formulas,
        bound=_universe_bound,
    ):
        return None
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
        [],
    )


def _urlsafe_translate_function_universe(
    callee: SourceFragment,
    callee_name: str,
    *,
    filename: str,
    memento_file: str,
    source_lines: list[str],
) -> LiftResult | None:
    """Closed CPython URL-safe base64 alphabet universe.

    CPython defines ``urlsafe_b64encode`` as ``b64encode(s).translate(table)``
    where ``table`` maps ``+`` to ``-`` and ``/`` to ``_``. The body walker cannot
    reduce that method call yet, but the closed translate table is already a
    verifier vocabulary row: the output contains none of the source-side chars.
    """

    if not _is_cpython_urlsafe_b64encode_translate(callee, callee_name):
        return None

    imported_source = getattr(callee.node, "_sugar_source", None)
    if imported_source is not None:
        source_lines = imported_source.splitlines(keepends=True)
        memento_file = getattr(callee.node, "_sugar_file", memento_file)

    return_stmt = next(
        (stmt for stmt in callee.function_body() if stmt.observed == "Return"),
        None,
    )
    if return_stmt is None:
        return None

    formal_names = tuple(callee.function_params())
    scope_sorts: dict[str, ProofSort] = {
        name: UnknownSort(reason=f"no declared sort for formal {name!r}")
        for name in formal_names
    }
    scope_sorts["out"] = StringSort()
    formula = atomic("str.chars-not-in-set", [make_var("out"), str_const("+/")])
    function_post = _post_condition_from_ir(
        formula,
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
        role="python.urlsafe-translate-universe",
        contract_name=function_contract_name,
    )
    return_memento = _statement_source_memento(
        return_stmt,
        callee,
        memento_file,
        source_lines,
        contract_name=function_contract_name,
        role="python.urlsafe-translate-universe",
    )
    provenance = Provenance(
        node_class=FunctionContract.node_class,
        construction_site=_proofir_construction_site(return_stmt, memento_file),
        warrant=Stated(locus=_proofir_construction_site(return_stmt, memento_file)),
    )
    function_contract = FunctionContract(
        symbol=function_contract_name,
        formals=tuple(
            FunctionContract.formal(name, scope_sorts[name]) for name in formal_names
        ),
        post=function_post,
        warrants=(provenance,),
        out_binding="out",
        out_sort=StringSort(),
        source_warrants=[function_memento],
        bridge_source_symbol=f"call:{callee_name}",
    )
    audit = _source_audit(
        callee,
        return_stmt,
        memento_file,
        function_contract_name,
        return_memento,
        role="python.urlsafe-translate-universe",
        ast_kind="Return",
    )
    walk = _walk_row(
        "UrlsafeTranslateUniverseSugar",
        "Return",
        return_stmt,
        filename,
        return_memento,
        "predicate",
        requested_role="FunctionBodyConstraint",
        emitted_formula=_typed_formula_to_rpc(formula, scope_sorts),
        reason=(
            "CPython base64 urlsafe_b64encode translates '+' and '/' away via "
            "_urlsafe_encode_translation"
        ),
    )
    return (
        [function_contract],
        [function_memento, return_memento],
        [audit],
        [walk],
        [],
        [],
    )


def _is_cpython_urlsafe_b64encode_translate(
    callee: SourceFragment, callee_name: str
) -> bool:
    if callee_name != "base64.urlsafe_b64encode":
        return False
    source = getattr(callee.node, "_sugar_source", "") or ""
    normalized = " ".join(source.split())
    if "b64encode(s).translate(_urlsafe_encode_translation)" not in normalized:
        return False
    try:
        import base64
    except ImportError:
        return False
    return getattr(base64, "_urlsafe_encode_translation", None) == bytes.maketrans(
        b"+/", b"-_"
    )


def _dig_universe(
    call_frag: SourceFragment,
    *,
    functions_by_name: dict[str, SourceFragment],
    classes_by_name: dict[str, SourceFragment],
    filename: str,
    memento_file: str,
    source_lines: list[str],
    dig_refusals: list[DigBoundary],
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
    _universe_formulas = _with_python_number_sort_universe(_universe_formulas)
    _universe_formulas = _with_python_bytes_content_universe(_universe_formulas)
    if _is_open_byte_support_universe(_universe_formulas, _universe_bound):
        _record_dig_refusal(
            dig_refusals,
            callee=target_fn.function_name(),
            blame=target_fn.blame,
            caught=ValueError(
                "naked ord-byte body has no enclosing str.eq-bv-blocks universe"
            ),
            reason=(
                "function universe body walker refused open ord-byte support; "
                "concrete callsite projection may still derive the byte value"
            ),
        )
        return None
    if _record_open_universe_refusal(
        dig_refusals,
        callee=target_fn,
        formulas=_universe_formulas,
        bound=_universe_bound,
    ):
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


def _with_python_number_sort_universe(formulas: list[Formula]) -> list[Formula]:
    """Route symbolic Python bitwise bodies through the int32/BV universe.

    A callable post `out == bv32.*` must not hand a naked bv32 term to the
    consistency formula. The Java numeric universe precedent carries the
    width-refined BV tree in `int32.eq-bv-expr(subject, tree)` and lets the
    verifier specialize the subject onto the canonical `call:<callee>` Int
    federation term.
    """

    return [_python_number_sort_formula(formula) for formula in formulas]


def _python_number_sort_formula(formula: Formula) -> Formula:
    if not isinstance(formula, _Atomic) or formula.name != "=":
        return formula
    if len(formula.args) != 2:
        return formula
    left, right = formula.args
    if _is_out_binding_term(left) and _is_bv32_tree(right):
        return _Atomic("int32.eq-bv-expr", (left, right))
    if _is_out_binding_term(right) and _is_bv32_tree(left):
        return _Atomic("int32.eq-bv-expr", (right, left))
    return formula


def _is_out_binding_term(term: Term) -> bool:
    return isinstance(term, _Var) and term.name == "out"


def _is_bv32_tree(term: Term) -> bool:
    if isinstance(term, _Ctor):
        return term.name.startswith("bv32.") or any(
            _is_bv32_tree(arg) for arg in term.args
        )
    return False


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
        [*universe[5], *assertion[5]],
    )


def _record_dig_refusal(
    dig_refusals: list[DigBoundary],
    *,
    callee: str,
    blame: str,
    caught: BaseException,
    reason: str,
) -> None:
    dig_refusals.append(
        DigBoundary(
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
) -> list[CallEdgeDto]:
    edges: list[CallEdgeDto] = []
    seen: set[tuple[str, int, int]] = set()
    for item in sink:
        target_symbol = item["targetSymbol"]
        key = (target_symbol, item["line"], item["column"])
        if key in seen:
            continue
        seen.add(key)
        binding = _binding_for_bridge_symbol(
            contract_bindings, target_symbol, arg_terms=item.get("argTerms")
        )
        formal_actuals = _formal_actuals_for_binding(binding, item.get("argTerms"))
        bridge = BridgeAtom(
            source_contract=source_contract,
            target_symbol=target_symbol,
            target_contract=binding.get("name") if binding is not None else None,
            target_contract_cid=_binding_cid(binding) if binding is not None else None,
            call_site_locus=Locus(memento_file, item["line"], item["column"]),
            formal_actuals=formal_actuals,
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


def _formal_actuals_for_binding(
    binding: dict[str, Any] | None, arg_terms: object
) -> dict[str, Any] | None:
    if binding is None or not isinstance(arg_terms, list):
        return None
    formals = binding.get("formals")
    if not isinstance(formals, list) or not all(
        isinstance(formal, str) for formal in formals
    ):
        return None
    positional: list[Term] = []
    keywords: dict[str, Term] = {}
    for term in arg_terms:
        if (
            isinstance(term, _Ctor)
            and term.name.startswith("kw:")
            and len(term.args) == 1
        ):
            keywords[term.name.removeprefix("kw:")] = term.args[0]
        elif isinstance(
            term, (_Var, _ConstInt, _ConstStr, _ConstBool, _ConstReal, _Ctor)
        ):
            positional.append(term)
        else:
            return None
    actuals: dict[str, Any] = {}
    for index, formal in enumerate(formals):
        if formal in keywords:
            actuals[formal] = _term_to_rpc(keywords[formal])
        elif index < len(positional):
            actuals[formal] = _term_to_rpc(positional[index])
        else:
            return None
    return actuals


def _module_statements(root_frag: SourceFragment) -> list[SourceFragment]:
    statements: list[SourceFragment] = []
    for fragment in root_frag.fragments():
        statements.extend(fragment.statements())
    return statements


def _binding_for_bridge_symbol(
    contract_bindings: list,
    target_symbol: str,
    *,
    arg_terms: object = None,
) -> dict[str, Any] | None:
    target_symbols = _bridge_symbol_match_candidates(target_symbol, arg_terms)
    for binding in contract_bindings:
        if not isinstance(binding, dict):
            continue
        if _binding_bridge_candidates(binding) & target_symbols:
            return binding
    return None


def _bridge_symbol_match_candidates(
    target_symbol: str, arg_terms: object = None
) -> set[str]:
    candidates = {target_symbol}
    if target_symbol.startswith("call:"):
        candidates.add(target_symbol.removeprefix("call:"))
    if target_symbol.startswith("method:"):
        method_name = target_symbol.removeprefix("method:")
        candidates.add(method_name)
        receiver_term = _first_arg_term(arg_terms)
        receiver_ctor = _receiver_constructor_name(receiver_term)
        if receiver_ctor is not None:
            candidates.add(f"{receiver_ctor}.{method_name}")
    return {candidate for candidate in candidates if candidate}


def _binding_bridge_candidates(binding: dict[str, Any]) -> set[str]:
    candidates: set[str] = set()
    for key in ("bridgeSourceSymbol", "name"):
        value = binding.get(key)
        if not isinstance(value, str) or not value:
            continue
        candidates.add(value)
        if value.startswith("call:"):
            candidates.add(value.removeprefix("call:"))
        elif not value.startswith("method:"):
            candidates.add(f"call:{value}")
    for library in _binding_libraries(binding):
        for value in tuple(candidates):
            if value.startswith(("call:", "method:")):
                continue
            if value == library or value.startswith(f"{library}."):
                continue
            candidates.add(f"{library}.{value}")
            candidates.add(f"call:{library}.{value}")
    return candidates


def _binding_libraries(binding: dict[str, Any]) -> tuple[str, ...]:
    libraries: list[str] = []
    for key in ("library", "library_tag", "target_library_tag", "targetLibraryTag"):
        value = binding.get(key)
        if isinstance(value, str) and value:
            libraries.append(value)
    return tuple(dict.fromkeys(libraries))


def _first_arg_term(arg_terms: object) -> Term | None:
    if not isinstance(arg_terms, list) or not arg_terms:
        return None
    first = arg_terms[0]
    return (
        first
        if isinstance(
            first, (_Var, _ConstInt, _ConstStr, _ConstBool, _ConstReal, _Ctor)
        )
        else None
    )


def _receiver_constructor_name(term: Term | None) -> str | None:
    if isinstance(term, _Ctor) and term.name.startswith("call:"):
        return term.name.removeprefix("call:")
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


def _precondition_implications_from_call_edges(
    edges: list[CallEdgeDto], contract_bindings: list
) -> list[ImplicationDto]:
    implications: list[ImplicationDto] = []
    seen: set[tuple[str, str, str]] = set()
    for edge in edges:
        source_contract = edge.get("sourceContract")
        target_contract = edge.get("targetContract")
        if not isinstance(source_contract, str) or not isinstance(target_contract, str):
            continue
        source_binding = _binding_for_contract_name(contract_bindings, source_contract)
        target_binding = _binding_for_contract_name(contract_bindings, target_contract)
        if _binding_bool(source_binding, "has_post"):
            source_slot = "post"
        elif _binding_bool(source_binding, "has_inv"):
            source_slot = "inv"
        else:
            continue
        if not _binding_bool(target_binding, "has_pre"):
            continue
        key = (source_contract, source_slot, target_contract)
        if key in seen:
            continue
        seen.add(key)
        implications.append(
            ImplicationDto(
                name=f"{source_contract}.{source_slot}-implies-{target_contract}.pre",
                antecedent=source_contract,
                consequent=target_contract,
                antecedent_slot=source_slot,
                consequent_slot="pre",
                prover="python-implications",
            )
        )
    return implications


def _binding_for_contract_name(
    contract_bindings: list, contract_name: str
) -> dict[str, Any] | None:
    for binding in contract_bindings:
        if not isinstance(binding, dict):
            continue
        if binding.get("name") == contract_name:
            return binding
    return None


def _binding_bool(binding: dict[str, Any] | None, key: str) -> bool:
    if binding is None:
        return False
    return binding.get(key) is True


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
    module_name: str, attr: str, *, dig_refusals: list[DigBoundary]
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
    dig_refusals: list[DigBoundary],
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
) -> SourceAuditDto:
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
    return FactoryWalkCompleteRowDto(
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
