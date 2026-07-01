from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
    and_,
    ctor,
    eq,
    formula_to_value,
    num,
    str_const,
)
from sugar_lift_py_tests.kit_rpc import (
    BodyUniverseDto,
    FactoryWalkRowDto,
    LiftReportPayloadDto,
    SourceMementoDto,
    SourceSpanDto,
)
from sugar_lift_py_tests.outcome import complete_value

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
    if isinstance(term, _Ctor):
        inner = ",".join(_canonical_term_sig(a) for a in term.args)
        return f"c:{term.name}({inner})"
    return f"?:{term!r}"


def euf_call_term(callee_name: str, arg_terms):
    """The EUF callsite term for ``callee(args)`` -- an uninterpreted ``call:<callee>``
    ctor over the argument terms. The SINGLE constructor of the bridge term, so every
    callsite of the same callee+args builds the byte-identical term that mint coalesces."""
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
    list[BodyUniverseDto],
    list[SourceMementoDto],
    list[dict[str, Any]],
    list[FactoryWalkRowDto],
    list[dict[str, Any]],
]


@dataclass(frozen=True)
class SourceReportBuild:
    payload: LiftReportPayloadDto


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
    contracts: list[BodyUniverseDto] = []
    source_mementos: list[SourceMementoDto] = []
    source_audits: list[dict[str, Any]] = []
    factory_walk: list[FactoryWalkRowDto] = []
    call_edges: list[dict[str, Any]] = []
    local_functions = {
        frag.function_name(): frag
        for frag in root_frag.walk()
        if frag.observed == "FunctionDef"
    }
    import_aliases, from_imports = _import_bindings(root_frag)
    # IMPORT SUGAR: a callee reached through `import numpy as np` / `from mod import f`
    # is not local, so the dig cannot see its body. Resolve each imported callee to
    # its installed source FunctionDef so the SAME dig walks it like a local function.
    # Locals win on name collision; the assert-iteration below stays local-only.
    dig_functions = {
        **_resolve_imported_callees(root_frag, import_aliases, from_imports),
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
                import_aliases=import_aliases,
                from_imports=from_imports,
                contract_bindings=contract_bindings or [],
            )
            # _lift_assert never returns None now: it lifts the assert or PANICS
            # (FactoryGap). A silent skip here would be the cardinal crime.
            lifted_contracts, mementos, audits, rows, edges = lifted
            contracts.extend(lifted_contracts)
            source_mementos.extend(mementos)
            source_audits.extend(audits)
            factory_walk.extend(rows)
            call_edges.extend(edges)
    if not contracts:
        return None
    return SourceReportBuild(
        LiftReportPayloadDto(
            ir=contracts,
            source_mementos=source_mementos,
            source_ledger=_source_ledger(len(source_audits)),
            source_audits=source_audits,
            factory_walk=factory_walk,
            call_edges=call_edges,
        )
    )


def _resolve_bound_lhs(lhs, fn):
    """LHS-as-term, syntactically: a Name bound to a CALL recomposes to that call, so
    ``x = y(5); assert x == 9`` lifts IDENTICALLY to ``assert y(5) == 9`` -- the binding is
    transparent and the bridge falls out wherever the call appears (the same dance, the
    binding just different clothes). Only a call RHS substitutes; a non-call binding leaves
    the Name as-is (which panics as before -- only ``call(...) == literal`` is covered)."""
    if lhs.observed != "Name":
        return lhs
    name = lhs.name_id()
    for stmt in fn.function_body():
        if stmt.observed == "Assign" and stmt.assign_target_name() == name:
            rhs = stmt.assign_value()
            if rhs.observed == "Call":
                return rhs
    return lhs


def _lift_assert(
    stmt: SourceFragment,
    *,
    fn: SourceFragment,
    filename: str,
    memento_file: str,
    source_lines: list[str],
    functions_by_name: dict[str, SourceFragment],
    import_aliases: dict[str, str],
    from_imports: dict[str, tuple[str, str]],
    contract_bindings: list,
) -> LiftResult | None:
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
        import_aliases=import_aliases,
        from_imports=from_imports,
        contract_bindings=contract_bindings,
    )
    if assertion_sugar is not None:
        return assertion_sugar

    comparison = stmt.assert_test()
    if comparison.observed != "Compare" or len(comparison.compare_ops()) != 1:
        _panic_no_sugar(
            stmt, memento_file,
            observed=f"assert-test:{comparison.observed}",
            requested="EqualityAssertion",
            fix="lift this assertion shape (only `call(...) == literal` is covered)",
        )
    if comparison.compare_ops()[0] != "Eq" or len(comparison.compare_comparators()) != 1:
        _panic_no_sugar(
            stmt, memento_file,
            observed=f"assert-compare-op:{comparison.compare_ops()[0]}",
            requested="EqualityAssertion",
            fix="lift non-`==` comparison assertions",
        )
    comparison_left = _resolve_bound_lhs(comparison.compare_left(), fn)
    callee_name = _callee_name(comparison_left, import_aliases, from_imports)
    if callee_name is None:
        _panic_no_sugar(
            comparison_left, memento_file,
            observed=f"assert-eq-lhs:{comparison_left.observed}",
            requested="CallsiteEquality",
            fix="lift `<lhs> == literal` where the lhs is not a call",
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
    )

    universe: LiftResult | None = None
    if callee_name in functions_by_name:
        # First try to CONSTRUCT: curry the callee over the concrete arg and slam to the
        # floor. If it reduces to a literal we swear the Python value (verify). Only if the
        # peel stops short -- a symbolic arg, an unfoldable op, an effect -- do we fall back
        # to the symbolic universe (the irreducible residue, checked for consistency).
        universe = _construct_callsite(
            stmt,
            comparison_left,
            callee_name,
            fn,
            functions_by_name,
            filename=filename,
            memento_file=memento_file,
            source_lines=source_lines,
        )
        if universe is None:
            universe = _dig_universe(
                comparison_left,
                functions_by_name=functions_by_name,
                filename=filename,
                memento_file=memento_file,
                source_lines=source_lines,
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
    import_aliases: dict[str, str],
    from_imports: dict[str, tuple[str, str]],
    contract_bindings: list,
) -> LiftResult | None:
    from .build import build_node, default_catalog

    catalog = default_catalog()
    candidates = catalog.candidates_for(SugarRole.ASSERTION, stmt)
    if _comparison_assertion_uses_nonfree_name(
        stmt,
        fn,
        import_aliases=import_aliases,
        from_imports=from_imports,
    ):
        catalog = SugarCatalog(
            [
                claim
                for claim in catalog.claims
                if claim.name != "ComparisonAssertionSugar"
            ]
        )
        candidates = catalog.candidates_for(SugarRole.ASSERTION, stmt)
    if not candidates:
        return None
    external_bridge_sink: list[dict[str, Any]] = []
    ctx = FactoryBuildContext(
        filename=filename,
        catalog=catalog,
        name_resolver={name: frag.node for name, frag in functions_by_name.items()},
        import_aliases=import_aliases,
        from_imports=from_imports,
        contract_bindings=contract_bindings,
        external_bridge_sink=external_bridge_sink,
    )
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


def _comparison_assertion_uses_nonfree_name(
    stmt: SourceFragment,
    fn: SourceFragment,
    *,
    import_aliases: dict[str, str],
    from_imports: dict[str, tuple[str, str]],
) -> bool:
    if stmt.observed != "Assert":
        return False
    test = stmt.assert_test()
    if test.observed != "Compare":
        return False
    if len(test.compare_ops()) != 1 or len(test.compare_comparators()) != 1:
        return False
    operator = test.compare_ops()[0]
    if operator not in {"Eq", "NotEq", "Lt", "LtE", "Gt", "GtE"}:
        return False
    safe_names = set(fn.function_params()) | set(import_aliases) | set(from_imports)
    for operand in (test.compare_left(), test.compare_comparators()[0]):
        for name in _names_including_self(operand):
            if name not in safe_names:
                return True
    return False


def _names_including_self(site: SourceFragment) -> list[str]:
    names: list[str] = []
    for fragment in [site, *site.walk()]:
        if fragment.observed == "Name":
            names.append(fragment.name_id())
    return names


def _floor_to_term(value: Any) -> Term:
    """Map a reduced Floor value to its ProofIR term. Composition-agnostic: it does
    not care WHICH sugar produced the value, only its Floor type."""
    from sugar_lift_py_tests.floor import (
        ArrayLiteral,
        Bv32Value,
        StringValue,
        SymbolicValue,
        TermValue,
    )

    if isinstance(value, TermValue):
        return num(value.value)
    if isinstance(value, StringValue):
        return str_const(value.value)
    # A symbolic term (a bound variable or a composed operation over one) already
    # IS its ProofIR term -- carry it through; the compiler sorts it.
    if isinstance(value, (SymbolicValue, Bv32Value)):
        return value.term
    if isinstance(value, ArrayLiteral):
        return ctor("array", [_floor_to_term(item) for item in value.items])
    raise TypeError(
        f"write more Floor->Term for `{type(value).__name__}` in the callsite literal"
    )


def _lift_literal_via_factory(frag: SourceFragment, filename: str) -> Term:
    """Lift a literal operand of a callsite equality THROUGH THE FACTORY: the
    catalog's literal sugars (PrimitiveLiteral, ...) build and reduce it, and an
    unhandled shape panics via the catalog's own mouth. No special-casing per type."""
    from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
    from sugar_lift_py_tests.claim import SugarRole as _Role

    from .build import default_catalog

    ctx = FactoryBuildContext(filename=filename, catalog=default_catalog())
    body = ctx.build_body(frag, _Role.TERM)
    return _floor_to_term(complete_value(body.reduce(ctx), owner="callsite literal"))


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
) -> LiftResult | None:
    """The fact. `callee(args) == expected` lifts to the euf callsite obligation
    `eq(call:callee(args), expected)`, contract-named `callee#euf#<arg_sig>::assertion`.
    `call:<callee>` is the callsite-ctor head the verifier recognizes
    (`is_callsite_ctor_term` requires the `call:` prefix) and the head the universe
    post specializes onto. Only concrete-literal args take this path; a symbolic arg
    returns None."""
    # The expected value composes through the factory's literal sugars (string,
    # int, ...). Anything the catalog can't build panics via its own mouth, which
    # names the next sugar -- no string-only special case here.
    expected_term = _lift_literal_via_factory(comparison.compare_comparators()[0], filename)
    # Each arg composes through the factory's literal sugars (string, int, array,
    # ...) -- the same path as the expected. A literal the catalog reduces but can't
    # yet shape into a term (e.g. a nested array) is turned into a clean mouth-panic
    # naming the next sugar, not a crash.
    arg_terms = []
    for arg_frag in callsite.call_args():
        try:
            arg_terms.append(_lift_literal_via_factory(arg_frag, filename))
        except TypeError:
            _panic_no_sugar(
                arg_frag, memento_file,
                observed=f"callsite-arg:{arg_frag.observed}-unliftable",
                requested="LiftableCallArg",
                fix="lift this call-arg shape (e.g. nested arrays, mixed-type lists)",
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
) -> LiftResult:
    """Emit one `<callee>#euf#<args>::assertion` fact: `eq(call:callee(args), value)`.

    The SINGLE emitter for both the sworn facts in play: the VENDOR's stated value (the
    assertion RHS) and the value WE construct by slamming the callee's body to the floor.
    Both land under the same #euf# key, so they conjoin -- agreement discharges, disagreement
    is UNSAT. One emitter means the key is spelled once: a vendor lie and a Python truth meet
    on the same name or they never meet at all."""
    from sugar_lift_py_tests.sugar.call_sugar import AssertionFactStrategy

    fact = AssertionFactStrategy(callee_name, tuple(arg_terms), value_term)
    contract_name = fact.contract_name()
    memento = _statement_source_memento(
        stmt,
        fn,
        memento_file,
        source_lines,
        contract_name=contract_name,
        role="python.literal-call-sugar",
    )
    inv = _formula_to_rpc(fact.fact_formula())
    contract = BodyUniverseDto(
        name=contract_name,
        out_binding="out",
        inv=inv,
        source_warrants=[memento],
    )
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
    return ([contract], [memento], [audit], [walk], [])


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


def _construct_callsite(
    stmt: SourceFragment,
    callsite: SourceFragment,
    callee_name: str,
    caller_fn: SourceFragment,
    functions_by_name: dict[str, SourceFragment],
    *,
    filename: str,
    memento_file: str,
    source_lines: list[str],
) -> LiftResult | None:
    """Construct the callsite tower AND every tower it bridges to, transitively.

    Curry the callee over the concrete arg and reduce the body through the catalog -- every
    operation delegates to Python (the reference), leak-impossible by construction. The body
    reaches one of two floors (the Outcome algebra):
      * a LITERAL -> we swear `call:callee(arg) == <value>` (the leaf).
      * a BRIDGE `call:h(arg2)` -> we swear `call:callee(arg) == call:h(arg2)` AND the reduce
        ENQUEUED h's dig (emit's job: pointer + obligation are one act). h owes a tower, so we
        drain it next -- the bridge's `vendor source` goes Resolved, not Absent.
    The worklist drains transitively, cycle-guarded by the #euf# key so a tower never re-digs
    itself (the fixpoint). A callee with no body, a symbolic arg, or a runtime effect leaves
    the bridge as a dangling axiom and that branch defers; if NOTHING constructs, return None
    and the symbolic universe / the mouth takes over."""
    from .build import default_catalog
    from sugar_lift_py_tests.context.reduce_context import ReduceContext
    from sugar_lift_py_tests.factory.block import Block
    from sugar_lift_py_tests.factory.factory_gap import FactoryGap
    from sugar_lift_py_tests.floor import ReturnValue, SymbolicValue, TermValue
    from sugar_lift_py_tests.outcome import Complete
    from sugar_lift_py_tests.temporal import TemporalContext

    if callsite.call_arg_count() != 1:
        return None
    resolver = {name: f.node for name, f in functions_by_name.items()}
    build_ctx = FactoryBuildContext(
        filename=filename, catalog=default_catalog(), name_resolver=resolver
    )
    # The TOP arg must itself slam to a concrete value (a symbolic arg leaves the whole
    # callsite irreducible -> defer to the symbolic universe).
    try:
        top = build_ctx.build_body(callsite.call_args()[0], SugarRole.TERM).reduce(
            ReduceContext(temporal=TemporalContext.empty())
        )
    except (TypeError, ValueError, FactoryGap):
        return None
    if not isinstance(top, Complete) or isinstance(top.value, SymbolicValue):
        return None

    def _euf_name(cn, arg_value):
        return euf_callsite_name(
            cn, euf_call_term(cn, [_floor_to_term(arg_value)]), suffix="::assertion"
        )

    seen: set[str] = set()
    universes_seen: set[str] = set()
    worklist: list[tuple[str, object]] = [(callee_name, top.value)]
    facts: list[LiftResult] = []
    while worklist:
        cn, arg_value = worklist.pop()
        key = _euf_name(cn, arg_value)
        if key in seen:
            continue  # fixpoint: this tower is already minted (cycle / shared callee)
        seen.add(key)
        callee = functions_by_name.get(cn)
        if callee is None or len(callee.function_params()) != 1:
            continue  # no tower to dig -> `call:cn(arg)` stays a dangling axiom (the vendor's word)
        # Emit the callee's ::callable UNIVERSE once -- the symbolic body walk, warranting each
        # source line (`return h(x)` -> `out == call:h(x)`, `return x+1` -> `out == +(x,1)`). The
        # construction below swears the concrete VALUE at the callsite; the universe warrants the
        # body where its constraints originate, so the visual walk paints the body green too.
        if cn not in universes_seen:
            universes_seen.add(cn)
            uni = _function_universe(
                callee, cn, functions_by_name=functions_by_name,
                filename=filename, memento_file=memento_file, source_lines=source_lines,
            )
            if uni is not None:
                facts.append(uni)
        sink: list[tuple[str, object]] = []
        reduce_ctx = ReduceContext(
            temporal=TemporalContext.empty().bind_value(callee.function_params()[0], arg_value),
            dig_sink=sink,
        )
        try:
            outcome = build_ctx.build_body(Block.of(callee.node.body), SugarRole.STATEMENT).reduce(
                reduce_ctx
            )
        except (TypeError, ValueError, FactoryGap):
            continue  # a shape the catalog cannot peel -> leave the bridge as an axiom
        if not isinstance(outcome, Complete):
            continue  # a runtime effect (Incomplete): unclimbable here
        body_stmts = outcome.value.statements
        if len(body_stmts) != 1 or not isinstance(body_stmts[0], ReturnValue):
            continue
        result = body_stmts[0].value
        if isinstance(result, TermValue):
            value_term = _floor_to_term(result)  # reached a literal floor
        elif isinstance(result, SymbolicValue):
            value_term = result.term  # topped out at a bridge `call:h(arg2)` -- the pointer
        else:
            continue
        if value_term == euf_call_term(cn, [_floor_to_term(arg_value)]):
            # A reflexive self-bridge `call:f(arg) == call:f(arg)` is a recursion cycle: vacuous,
            # and the tower is not finitely constructible. Skip it -> no fact; the callsite falls
            # to the symbolic universe / the mouth, which refuses cleanly rather than swearing
            # a tautology that defines nothing.
            continue
        facts.append(
            _emit_euf_fact(
                stmt,
                caller_fn,
                cn,
                [_floor_to_term(arg_value)],
                value_term,
                filename=filename,
                memento_file=memento_file,
                source_lines=source_lines,
            )
        )
        worklist.extend(sink)  # the bridges this body emitted now owe their own towers
    if not facts:
        return None
    merged = facts[0]
    for extra in facts[1:]:
        merged = _merge_lifts(merged, extra)
    return merged


def _function_universe(
    callee: SourceFragment,
    callee_name: str,
    *,
    functions_by_name: dict[str, SourceFragment],
    filename: str,
    memento_file: str,
    source_lines: list[str],
) -> LiftResult | None:
    """The `::callable` universe for ONE resolved function, walked from its DEFINITION.

    The construction swears the concrete VALUE at the callsite; this walks the body over its
    formals into `out == <body>` and warrants each source LINE -- so the visual walk paints the
    function body green where its constraints originate, not just the assertion. It calls the
    control-flow walker DIRECTLY (which now lifts `return x + 1` to `out == +(x, 1)` via the
    symbolic-op emission), bypassing build_bridge_body's string-only single-return shortcut.
    Returns None if the body cannot be walked -- the construction still stands; only the
    source-line warrant is absent."""
    from .build import default_catalog
    from .sugar_constructors import build_control_flow_body_sugar

    build_ctx = FactoryBuildContext(
        filename=filename,
        catalog=default_catalog(),
        name_resolver={name: frag.node for name, frag in functions_by_name.items()},
    )
    try:
        universe_sugar = build_control_flow_body_sugar(callee, build_ctx)
        body_steps = universe_sugar.factory_steps(callee.node)
        body_formulas = universe_sugar.constraint_formulas()
        body_step_formulas = universe_sugar.constraint_formula_steps()
    except (TypeError, ValueError, FactoryGap):
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
        _formula_to_rpc(formula) if formula is not None else None for formula in body_step_formulas
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
    function_contract_name = f"{Path(memento_file).stem}::{callee.function_name()}::callable"
    function_memento = _function_source_memento(
        callee, memento_file, source_lines,
        role="python.literal-call-sugar", contract_name=function_contract_name,
    )
    body_mementos = [
        _statement_source_memento(
            SourceFragment.from_node(step_stmt, memento_file), callee, memento_file, source_lines,
            contract_name=function_contract_name, role="python.literal-call-sugar",
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
        callee, return_stmt_frag, memento_file, function_contract_name, body_mementos[-1],
        role="python.literal-call-sugar", ast_kind="Return",
    )
    walk_rows = [
        _walk_row(
            selected, ast_kind, SourceFragment.from_node(step_stmt, memento_file), filename,
            step_memento, output, requested_role="FunctionBodyConstraint",
            emitted_formula=body_step_formula_values[index]
            if index < len(body_step_formula_values) else None,
        )
        for index, ((selected, ast_kind, step_stmt, output), step_memento) in enumerate(
            zip(body_steps, body_mementos)
        )
    ]
    return ([function_contract], [function_memento, *body_mementos], [audit], walk_rows, [])


def _dig_universe(
    call_frag: SourceFragment,
    *,
    functions_by_name: dict[str, SourceFragment],
    filename: str,
    memento_file: str,
    source_lines: list[str],
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
        name_resolver={name: frag.node for name, frag in functions_by_name.items()},
    )
    # Route through the CATALOG -- no side door. A resolved call builds a CallSugar whose
    # strategy is a BridgeStrategy carrying the callee's universe (the body walked over its
    # formals). The bridge IS the dig's source; never a side-door constructor.
    from sugar_lift_py_tests.sugar.call_sugar import BridgeStrategy

    try:
        call_body = factory_ctx.build_body(call_frag, SugarRole.TERM)
    except TypeError as exc:
        _panic_no_sugar(
            call_frag, memento_file,
            observed=f"dig-body:{call_frag.observed}",
            requested="FunctionBodyConstraint",
            fix=f"lift this function body for the dig ({exc})",
        )
    call_sugar = getattr(call_body.sugar, "strategy", None)
    if not isinstance(call_sugar, BridgeStrategy):
        _panic_no_sugar(
            call_frag, memento_file,
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
            target_fn, memento_file,
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
    function_contract_name = f"{Path(memento_file).stem}::{target_fn.function_name()}::callable"
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
            emitted_formula=body_step_formula_values[index]
            if index < len(body_step_formula_values)
            else None,
        )
        for index, (
            (selected, ast_kind, step_stmt, output),
            step_memento,
        ) in enumerate(zip(body_steps, body_mementos))
    ]
    return ([function_contract], [function_memento, *body_mementos], [audit], walk_rows, [])


def _merge_lifts(universe: LiftResult | None, assertion: LiftResult) -> LiftResult:
    """Universe first (the function-contract), then the assertion -- the order the
    consumers expect when both are present."""
    if universe is None:
        return assertion
    return tuple(  # type: ignore[return-value]
        [*u, *a] for u, a in zip(universe, assertion)
    )


def _panic_no_sugar(frag: SourceFragment, memento_file: str, *, observed: str, requested: str, fix: str):
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
    cid = binding.get("contract_cid") or binding.get("contractCid") or binding.get("targetContractCid")
    return cid if isinstance(cid, str) and cid else None


def _binding_proof_cid(binding: dict[str, Any] | None) -> str | None:
    if binding is None:
        return None
    cid = binding.get("target_proof_cid") or binding.get("targetProofCid")
    return cid if isinstance(cid, str) and cid else None


def _import_bindings(tree_frag: SourceFragment) -> tuple[dict[str, str], dict[str, tuple[str, str]]]:
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
        elif frag.observed == "ImportFrom" and frag.importfrom_module() and frag.importfrom_level() == 0:
            module = frag.importfrom_module()
            for name, asname in frag.importfrom_names():
                from_imports[asname or name] = (module, name)
    return aliases, from_imports


def _source_funcdef(module_name: str, attr: str) -> SourceFragment | None:
    """Resolve ``module_name.attr`` to its installed-source FunctionDef SourceFragment.

    The callee must be importable in the lifter's environment and have readable
    Python source. Decorators are dropped (the dig walks the body, not the
    dispatch wrapper). Anything unresolvable returns None -- the dig then has no
    universe for that callee, which is the honest outcome."""
    import importlib
    import inspect
    import textwrap

    try:
        module = importlib.import_module(module_name)
        obj = getattr(module, attr)
        source = textwrap.dedent(inspect.getsource(obj))
    except (ImportError, AttributeError, OSError, TypeError):
        return None
    # getsourcefile is best-effort: it raises TypeError on dispatch-wrapped callees
    # (e.g. numpy's @array_function_dispatch) where getsource still works -- a failure
    # here must NOT abort the resolution, only drop the filename label.
    try:
        sourcefile = inspect.getsourcefile(obj) or f"<{module_name}>"
    except TypeError:
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
        funcdef = _source_funcdef(module_name, attr)
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
    return frag.call_import_target_name(import_aliases, from_imports) or frag.call_target_name()


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
    )
