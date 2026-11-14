"""Enumeration served by the AST tree, not the factory.

The wire protocol's levels below `functions` — call_sites, assertions, facts —
were serviced by lifting the whole file through the factory and reading its IR
rows. Here they are serviced by walking the tree the parser produces and
asking each Assert node for its sugar and its desugared fact. The RPC drives
AST walking directly; the factory is not consulted.

For `assert <test>`: the assertion IS the Assert node; its fact is the InvValue
its sugar desugars to (formula on the wire via formula_to_value). A bare
assertion carries no call site — call_sites and assertions are the same locus,
1:1, exactly as the factory's protocol Section 4 already had them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from sugar_source_tree.construction_cache import AmbientSet
from sugar_source_tree.tree import SourceFile
from sugar_source_tree.nodes import Assert, AsyncFunctionDef, FunctionDef


def functions_of(sf: SourceFile):
    return list(sf.functions())


def asserts_of(node) -> list:
    """Every Assert in a function body, in source order."""
    return [n for n in node.walk() if isinstance(n, Assert)]


def halted_assertion_sites(halted_arms) -> tuple:
    """The ``assert`` statements at which a halted arm of a reduction left.

    Read off the reduction, never off the source: a halted arm's raise carries
    the exception value it raised, and that value carries the fragment it was
    raised at. When that fragment is an ``assert`` statement the reduction
    reached the assertion and control halted there. A raise from inside the
    assertion's operands is sited at the operand, and an ``assert`` no arm
    reached is sited nowhere: neither is an assertion the reduction halted at.
    """
    from sugar_lift_py_tests.effect import RaiseEffect
    from sugar_lift_py_tests.floor import ExceptionValue

    sites = []
    for arm in halted_arms:
        effect = arm.effect
        if not isinstance(effect, RaiseEffect):
            continue
        raised = effect.raised_value
        if not isinstance(raised, ExceptionValue):
            continue
        if isinstance(getattr(raised.site, "node", None), Assert):
            sites.append(raised.site)
    return tuple(sites)


def find_function(sf: SourceFile, name: Optional[str], span: Optional[dict]):
    for fn in sf.functions():
        if name is not None and fn.name != name:
            continue
        if span and not _span_matches(fn, span):
            continue
        return fn
    return None


class FunctionBindingMiss(Exception):
    """Named refusal: no unique authenticated function binding.

    Absence is a decision. Returning bare ``None`` made a miss
    indistinguishable from a soft skip; callers that need soft handling must
    catch this named throw explicitly.
    """

    def __init__(self, *, name: str, reason: str) -> None:
        self.name = name
        self.reason = reason
        super().__init__(f"FunctionBindingMiss name={name!r} reason={reason}")


def find_function_by_name(sf: SourceFile, name: str):
    """Resolve the unique module-direct function binding for ``name``.

    Authority is ``module_direct_bindings`` (bind-time roster), never
    first-match-by-spelling over transitive ``functions()`` (class methods and
    nested defs share spellings). Miss or competing bindings THROW named —
    they are not soft ``None``.
    """
    bindings = (sf.unit.module_direct_bindings or {}).get(name, ())
    functions = [
        binding
        for binding in bindings
        if isinstance(binding, (FunctionDef, AsyncFunctionDef))
    ]
    if len(functions) == 1:
        return functions[0]
    if not functions:
        raise FunctionBindingMiss(name=name, reason="no module-direct function binding")
    raise FunctionBindingMiss(
        name=name,
        reason=f"{len(functions)} competing module-direct function bindings",
    )


def resolve_function_for_call(call):
    """Resolve the callee through binding/coordinate at an exact call site.

    Uses ``SourceUnit.source_function_definition_for_call`` — lexical rows and
    module-direct bindings, not spelling walks. THROW named on a miss.
    """
    from sugar_source_tree.nodes import Name

    unit = call.unit
    definition = unit.source_function_definition_for_call(call)
    if definition is not None:
        return definition
    name = call.func.id if isinstance(call.func, Name) else type(call.func).__name__
    raise FunctionBindingMiss(
        name=name,
        reason="no unique authenticated function binding at call site",
    )


def call_target_names(sf: SourceFile, span: Optional[dict]) -> list:
    """The callee names cued by the assertion at `span`: the func-name of every
    plain Call inside it. This is how a call-site cue resolves to the callee(s)
    whose universe it digs -- by NAME, directly, no bridge-matching heuristics
    (the tree kept the names the factory had to reconstruct)."""
    from sugar_source_tree.nodes import Call, Name

    _source, node = temporally_rewritten_assert(sf, span)
    if node is None:
        return []
    names = []
    for call in node.walk():
        if isinstance(call, Call) and isinstance(call.func, Name):
            if call.func.id not in names:
                names.append(call.func.id)
    return names


def find_assert(sf: SourceFile, span: Optional[dict]):
    for node in sf:
        if isinstance(node, Assert) and (span is None or _span_matches(node, span)):
            return node
    return None


def temporally_rewritten_assert(sf: SourceFile, span: Optional[dict]):
    """Return ``(source_assert, rewritten_assert)`` for an exact locus.

    An assertion is not a construction root.  Its meaning depends on every
    binding before it in the enclosing function (or module), so constructing
    its Sugar directly from the parser-backed tree is a temporal side door.
    Find the narrowest enclosing function, rewrite that scope as a block, and
    only then return the assertion on which callers may invoke ``sugar()``.

    The source node is returned separately because its fragment/memento is the
    durable address.  Shadow rewrites deliberately borrow that address, but
    keeping the two roles explicit prevents a future caller from mistaking
    source lookup for construction readiness.

    Its readers look for the calls inside the rewritten assert; nothing reduces
    it. What the assert reduces to is read off its owner's one reduction
    (``assert_outcome``, item 28).
    """
    source_assert = find_assert(sf, span)
    if source_assert is None:
        return None, None

    owner = _assert_owner(sf, source_assert)
    rewritten_owner = (owner or sf.root).substitute({})

    for node in rewritten_owner.walk():
        if isinstance(node, Assert) and _span_matches(node, span or {}):
            return source_assert, node
    return source_assert, None


def _assert_owner(sf: SourceFile, source_assert):
    """The narrowest function holding ``source_assert``; ``None`` for the module."""
    target = source_assert.line_col_span()

    def contains(node) -> bool:
        locus = node.line_col_span()
        return (
            locus.start_line <= target.start_line and locus.end_line >= target.end_line
        )

    owners = [fn for fn in sf.functions() if contains(fn)]
    if not owners:
        # Module assertions are temporally owned by the module block.
        return None
    # Nested functions are also yielded by SourceFile.functions(); temporal
    # ownership belongs to the narrowest one, never its enclosing function.
    return min(
        owners,
        key=lambda fn: (
            fn.line_col_span().end_line - fn.line_col_span().start_line,
            fn.line_col_span().end_col - fn.line_col_span().start_col,
        ),
    )


class OwnerReduction:
    """One reduction of a function (or module) and what it recorded.

    ``outcome`` is the reduction's outcome; ``asserts`` is every
    ``(coordinate, outcome)`` an assert inside it reduced to, in reduction
    order. Its unanswered calls are owed by the outcome's own arms
    (``unanswered_calls.owed_calls``). ``ends`` is, for a module, each
    completed arm of its run holding the context it ended with, under the
    arm's guard and faces (``ModuleBlockSugar.run``); a function's
    reduction has none.
    """

    __slots__ = ("unit", "outcome", "asserts", "ends")

    def __init__(self, unit, outcome, asserts, ends=()):
        self.unit = unit
        self.outcome = outcome
        self.asserts = asserts
        self.ends = ends


# Each owner's reduction, remembered through the one door for memo rows
# (``construction_cache``): served only where every ambient value the
# reduction read (the module execution site, the occurrence path, the frames
# and module runs under way, ...) is still equal.  Keyed by the unit's id and
# the owner's span; each row's ``OwnerReduction`` holds its unit, so the id
# is never recycled under a live row.
_OWNER_REDUCTIONS: dict = {}
_OWNER_REDUCTIONS_BOUND = 256


def owner_reduction(owner, sf: Optional[SourceFile] = None) -> OwnerReduction:
    """THE reduction of a function (``owner``) or of a module (``owner`` None,
    ``sf`` given: anything holding the module's ``root``, a ``SourceFile`` or
    its unit's ``constructed_module``), once per resident unit and ambient
    state (#7757, inventory items 28 and 44).

    Every reader of a function's reduction reads this one: the universe rows,
    the link-unit enrollment, and the ``facts`` row of each assert in it. An assert is therefore reduced once, in context, and
    never alone. A refusal is not kept: it propagates to the reader, named.
    The unanswered calls the reduction left are owed by its outcome's arms,
    so a reduction read back from here carries them as the first one did.
    A module's reduction is its body's one run (``ModuleBlockSugar.run``),
    under no module execution site, as an import runs it; it keeps the
    context each completed arm ended with (``OwnerReduction.ends``).
    """
    from sugar_lift_py_tests import assert_reductions
    from sugar_source_tree.construction_cache import (
        abandon_row,
        close_row,
        open_row,
        serve,
    )
    from sugar_source_tree.nodes import construct_at_module_execution_site

    node = owner if owner is not None else sf.root
    lc = node.line_col_span()
    key = (id(node.unit), node.kind, lc.start_line, lc.start_col, lc.end_line, lc.end_col)
    row = serve(_OWNER_REDUCTIONS, key, node.reporter)
    if row is not None:
        return row.value
    if len(_OWNER_REDUCTIONS) >= _OWNER_REDUCTIONS_BOUND:
        _OWNER_REDUCTIONS.clear()
    computation = open_row()
    try:
        ends = ()
        with assert_reductions.collecting() as asserts:
            if owner is not None:
                outcome = function_universe_outcome(owner)
            else:
                outcome, ends = construct_at_module_execution_site(
                    None, lambda: sf.root.sugar().run(None)
                )
    except BaseException:
        # A refusal is not kept: what the reduction read and said belongs
        # to the computation around it.
        abandon_row(computation)
        raise
    held = OwnerReduction(node.unit, outcome, tuple(asserts), ends)
    close_row(_OWNER_REDUCTIONS, key, computation, node.reporter, value=held)
    return held


# Each unit's module run, remembered through the one door for memo rows
# (``construction_cache``): the context each completed arm ended with, or
# the refusal the run raised, re-raised on every hit.  Keyed by the unit's
# id; the unit is pinned beside its rows, so the id is never recycled under
# them.
_MODULE_RUNS: dict = {}
_MODULE_RUN_UNITS: dict = {}
# The units whose module run is under way.  Ambient to every memo row: an
# answer computed while another module's run is under way, that read that
# run as under way, is served only where it is under way again.
_MODULE_RUNS_UNDER_WAY: AmbientSet = AmbientSet("module_runs_under_way")


def module_end_contexts(unit) -> tuple:
    """The completed arms of ``unit``'s module run, each holding the context
    it ended with under its own guard and faces (``ModuleBlockSugar.run``):
    the one source of module-final global values (#7757 item 7).

    The run is THE module reduction (``owner_reduction`` with no owner),
    run once, at the root occurrence path, as an import runs it, wherever
    it is asked for.  A function called after import reads a global
    through the module's final binding of it, the key of the module body's
    last write; the value the run bound under that key is its value,
    whatever the write evaluated (a literal, ``x += e``, a call's result,
    a list), evaluated once and read only where the key is read
    (``call_site_sugar.ModuleFinalValue``).  Only completed arms: a
    function is called after an import that completed.

    Empty, so each such read is refused by name, where the run completes on
    no arm (every arm halts), and where it is asked for while it runs (a
    run that reaches, through another module's function, a read of this
    module's final binding).  Where the run refuses (a construction gap),
    the refusal is remembered as loudly as an answer, by the memo row's own
    door (``construction_cache.close_row``), and the same refusal reaches
    every read that asks: the run is never run again for the next reader,
    and its refusal is never caught to read as an answer.
    """
    from sugar_lift_py_tests.gap.panic import ConstructionPanic
    from sugar_lift_py_tests.occurrence import occurrence_path
    from sugar_source_tree.construction_cache import (
        abandon_row,
        close_row,
        open_row,
        serve,
    )
    from sugar_source_tree.panic import SourceTreePanic

    key = id(unit)
    if key in _MODULE_RUNS_UNDER_WAY:
        return ()
    memo = (key,)
    reporter = unit.constructed_module.root.reporter
    if _MODULE_RUN_UNITS.get(key) is unit:
        row = serve(_MODULE_RUNS, memo, reporter)
        if row is not None:
            if row.panic is not None:
                # The run's refusal, every time: the same panic, re-raised.
                raise row.panic
            return row.value
    if len(_MODULE_RUNS) >= _OWNER_REDUCTIONS_BOUND:
        _MODULE_RUNS.clear()
        _MODULE_RUN_UNITS.clear()
    computation = open_row()
    # Running it is this computation's own act: never ambient to its row.
    _MODULE_RUNS_UNDER_WAY.add(key)
    try:
        try:
            with occurrence_path(()):
                ends = owner_reduction(None, unit.constructed_module).ends
        finally:
            _MODULE_RUNS_UNDER_WAY.discard(key)
    except (SourceTreePanic, ConstructionPanic) as panic:
        # The two sanctioned construction gaps, remembered as loudly as an
        # answer and raised on.
        _MODULE_RUN_UNITS[key] = unit
        close_row(_MODULE_RUNS, memo, computation, reporter, panic=panic)
        raise
    except BaseException:
        # Anything else is a property of this traversal, never remembered.
        abandon_row(computation)
        raise
    _MODULE_RUN_UNITS[key] = unit
    close_row(_MODULE_RUNS, memo, computation, reporter, value=ends)
    return ends


def assert_outcome(sf: SourceFile, span: Optional[dict]):
    """Return ``(source_assert, outcome)``: what the assert at ``span`` reduced
    to inside its owner's one reduction (``owner_reduction``).

    ``outcome`` is ``None`` when the owner's reduction never reached the
    assert. An assert reached more than once (a loop body, a recursive owner)
    has no one outcome to read: that is refused by name, never answered with
    one of its reaches.
    """
    from sugar_lift_py_tests.caller_parameter_contract import source_coordinate
    from sugar_source_tree.panic import SugarNotWritten

    source_assert = find_assert(sf, span)
    if source_assert is None:
        return None, None
    reduction = owner_reduction(_assert_owner(sf, source_assert), sf)
    site = source_coordinate(source_assert.fragment).wire()
    reached = [
        outcome
        for coordinate, outcome in reduction.asserts
        if coordinate.wire() == site
    ]
    if len(reached) > 1:
        raise SugarNotWritten(
            owner="assert_outcome",
            blame=source_assert.fragment,
            observed=f"the assert is reached {len(reached)} times in its owner's reduction",
            requested="one outcome for the assert",
            fix="give each reach of the assert its own row, under its path",
        )
    return source_assert, (reached[0] if reached else None)


def _span_matches(node, span: dict) -> bool:
    lc = node.line_col_span()
    return lc.start_line == span.get("start_line") and lc.start_col == span.get(
        "start_col"
    )


def assert_memento(node, file_rel: str) -> dict:
    """The Assert's own self-locating memento: file + its span + CID."""
    lc = node.line_col_span()
    sealed = node.fragment.seal()
    return {
        "kind": "source-memento",
        "file": file_rel,
        "function_name": "",
        "source_function_name": "",
        "span": {
            "start_line": lc.start_line,
            "start_col": lc.start_col,
            "end_line": lc.end_line,
            "end_col": lc.end_col,
        },
        "source_cid": sealed.cid,
    }


def fact_of(outcome) -> Optional[Any]:
    """The assertion's InvValue's formula is the fact, on the wire.

    ``outcome`` is what the assert reduced to in its owner's one reduction
    (``assert_outcome``); the assert is never reduced here. None when the
    assertion emits no fact (e.g. inert support) or was not reached.
    """
    import json

    from sugar_lift_py_tests.canonicalizer import encode_jcs
    from sugar_lift_py_tests.ir import formula_to_value

    inv = getattr(outcome, "value", None)
    formula = getattr(inv, "formula", None)
    if formula is None:
        return None
    # Same shape the factory's facts payload carried (ir.py `item["inv"]`):
    # the formula's JCS Value tree, flattened to a plain JSON dict.
    return json.loads(encode_jcs(formula_to_value(formula)))


def function_def_memento(fn, file_rel: str):
    """The function's own SourceMemento (the def warrant payload_rows needs)."""
    from sugar_lift_py_tests.kit_rpc.source_memento_dto import SourceMementoDto
    from sugar_lift_py_tests.kit_rpc.source_span_dto import SourceSpanDto

    lc = fn.line_col_span()
    return SourceMementoDto(
        file=file_rel,
        span=SourceSpanDto(lc.start_line, lc.start_col, lc.end_line, lc.end_col),
        source_cid=fn.fragment.seal().cid,
        source_function_name=fn.name,
        param_names=[p.name for p in fn.params],
    )


class UndecidedRow:
    """What a proof does not decide, and why: one ``undecided`` row (step 8).

    The one member kind for it (the owner, 2026-11-12). Two cases, one shape:

    - a function the lifter refuses by name (``refused_function_row``):
      ``symbol`` is the function's own ``bridgeSourceSymbol``, ``site`` its
      ``def``, ``reason`` ``{"refused": {owner, observed}}``;
    - a call nothing here answers (``unanswered_call_row``): ``symbol`` is the
      import door's target symbol or ``None``, ``site`` the call,
      ``reason`` ``{"unanswered": {}}``.

    ``site`` is a ``SourceFragmentCoordinateV1`` wire plus the
    workspace-relative ``file``. Mint turns the row into the member through
    ``sugar_claim_envelope::mint_undecided``.
    """

    __slots__ = ("symbol", "site", "reason")

    def __init__(self, *, symbol, site, reason):
        self.symbol = symbol
        self.site = site
        self.reason = reason

    def to_rpc_with_term_table(self, _table):
        return {
            "kind": "undecided",
            "symbol": self.symbol,
            "site": dict(self.site),
            "reason": self.reason,
        }


def _undecided_site(file_rel: str, coordinate) -> dict:
    return {"file": file_rel, **coordinate.wire()}


def refused_function_row(fn, file_rel: str, refusal) -> UndecidedRow:
    """The ``undecided`` row for a function refused by the scope law (#7785).

    One rule: a row of the function, or the formula its outcome carries,
    names a variable outside its declared scope (formals plus ``out``). What
    the function sees of that name is not decided here.
    """
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceFragmentCoordinateV1,
    )

    memento = function_def_memento(fn, file_rel)
    coordinate = SourceFragmentCoordinateV1(
        memento.source_cid,
        memento.span.start_line,
        memento.span.start_col,
        memento.span.end_line,
        memento.span.end_col,
    )
    return UndecidedRow(
        symbol=fn.sugar().bridge_source_symbol,
        site=_undecided_site(file_rel, coordinate),
        reason={
            "refused": {
                "owner": refusal.info.owner,
                "observed": refusal.info.observed,
            }
        },
    )


def unanswered_call_row(symbol, coordinate, file_rel: str) -> UndecidedRow:
    """The ``undecided`` row for one call nothing in this proof answers.

    ``symbol`` is the one import table's target symbol (an import-bound
    callee) or ``None`` (Q5); ``coordinate`` is the call's
    ``SourceFragmentCoordinateV1``.
    The row records the call, never what answers it: the join to an imported
    contract is prove's (step 9), so the row is the same staged or unstaged.
    """
    return UndecidedRow(
        symbol=symbol,
        site=_undecided_site(file_rel, coordinate),
        reason={"unanswered": {}},
    )


def unanswered_call_rows(calls, file_rel: str) -> list:
    """One ``undecided`` row per distinct (symbol, site) a reduction owes.

    ``calls`` is ``unanswered_calls.owed_calls`` of the reduction's final
    outcome: ``UnansweredCallV1`` items, in arm order. A site reduced more
    than once (an unrolled loop, a re-reduction under another guard) is one
    call, so one row. A call with no site cannot be a member, and is refused
    by name rather than dropped.
    """
    rows = []
    seen = set()
    for call in calls:
        symbol, coordinate = call.symbol, call.site
        if coordinate is None:
            raise ValueError(
                "an unanswered call reached the proof with no site: "
                f"owner=unanswered_call_rows symbol={symbol!r} "
                "replacement=carry the call's fragment to UnknownCalleeCallV1"
            )
        key = (symbol, tuple(sorted(coordinate.wire().items())))
        if key in seen:
            continue
        seen.add(key)
        rows.append(unanswered_call_row(symbol, coordinate, file_rel))
    return rows


EXCEPTION_ANCESTRY_SUFFIX = "::exception-ancestry"
"""The contract-name suffix of a class's ancestry row: ``<symbol>`` + this.
The verifier reads the class symbol off the row name by this suffix, and the
row is a statement of fact, never a claim to check (``consistency.rs``)."""


def ancestry_statement_memento(statement, name: str, file_rel: str):
    """The SourceMemento of the statement that binds ``name`` (a ``class``, or
    a package's re-exporting ``from ... import``): its ancestry row's warrant."""
    from sugar_lift_py_tests.kit_rpc.source_memento_dto import SourceMementoDto
    from sugar_lift_py_tests.kit_rpc.source_span_dto import SourceSpanDto

    lc = statement.line_col_span()
    return SourceMementoDto(
        file=file_rel,
        span=SourceSpanDto(lc.start_line, lc.start_col, lc.end_line, lc.end_col),
        source_cid=statement.fragment.seal().cid,
        source_function_name=name,
    )


def exception_ancestry_rows(sf: SourceFile, file_rel: str) -> list:
    """One row per exception class the module defines, and per name a package
    re-exports: its ancestry (#7757).

    The row is a ``contract`` named ``<class symbol>::exception-ancestry``
    whose ``inv`` states ``adt.is_python_type(<class>, <ancestor>)`` for every
    ancestor the class's source testifies to
    (``SourceUnit.exception_class_ancestry``). Both operands are the
    coordinates a consumer mints for the same classes, so a consumer's open
    ``adt.is_python_type(<class>, <handler>)`` is answered at prove by joining
    on the class's target symbol and closing across the staged proofs (step
    9). The row is read off the binding statement alone; nothing is reduced
    here.

    Returns ``(memento, dto)`` pairs, the shape of the universe scan's rows.
    """
    from sugar_lift_py_tests.floor.universe_mint_projection import claim_formula
    from sugar_lift_py_tests.ir import and_, atomic
    from sugar_lift_py_tests.proofir.nodes import (
        ConstructionSite,
        Provenance,
        Stated,
    )
    from sugar_lift_py_tests.proofir.nodes.universe_mint import UniverseMint

    rows = []
    for statement, name, symbol, identity, ancestors in (
        sf.unit.exception_class_ancestry()
    ):
        memento = ancestry_statement_memento(statement, name, file_rel)
        locus = ConstructionSite(
            path=file_rel, line=memento.span.start_line, column=memento.span.start_col
        )
        provenance = Provenance(
            node_class="UniverseMint",
            construction_site=locus,
            warrant=Stated(locus=locus),
        )
        facts = [
            atomic("adt.is_python_type", [identity, ancestor]) for ancestor in ancestors
        ]
        formula = facts[0] if len(facts) == 1 else and_(facts)
        row = UniverseMint(
            name=f"{symbol}{EXCEPTION_ANCESTRY_SUFFIX}",
            slot="inv",
            formula=claim_formula(
                formula, formals=(), provenance=provenance, role="inv"
            ),
            provenance=provenance,
            source_warrants=(memento,),
        )
        rows.append((memento.to_rpc(), row.to_body_universe()))
    return rows


def require_outcome_in_scope(outcome, owner) -> None:
    """The scope law on an outcome that is not a set of arms (#7785).

    One rule for every function's outcome, carrier or not. A deferred native
    operation (``NativeOperationExitCarrierV1``) emits no row, but it carries
    a formula: its guards and its demand, the antecedent of the only post it
    can state. That formula goes through the same ``ScopedFormula`` over the
    formals plus ``out`` the rows go through, so a carrier that names a
    module-level name raises ``FreeVariableRefusal`` and the function is
    refused by name. A carrier within scope passes and still emits nothing.
    A bare effect carries no formula. A name read inside a deferred
    continuation is not in the formula and is not seen here.
    """
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
        _conjoin_guards,
    )

    if not isinstance(outcome, NativeOperationExitCarrierV1):
        return
    from sugar_lift_py_tests.proofir.formulas import formula_from_ir
    from sugar_lift_py_tests.proofir.scope import ScopedFormula
    from sugar_lift_py_tests.proofir.sorts import UnknownSort

    sort = UnknownSort(reason="lift is sort-silent; the compiler decides")
    allowed = {name: sort for name in (*owner.formals, "out")}
    formula = _conjoin_guards((*outcome.guards, outcome.demand.demanded_formula))
    ScopedFormula(formula_from_ir(formula, var_sorts=allowed), allowed_vars=allowed)


def function_universe_outcome(fn):
    """Construct one function universe through its authenticated entrance.

    Ordinary functions reduce with symbolic formals.  The active ``__init__``
    of a source class is different: its first parameter is the receiver that
    the class call itself creates.  The backend's exact lexical-owner relation
    selects the class, and its one constructor
    (``ClassDef.source_visible_constructor_frame().body``, the
    ``ClassConstructorBodySugar`` every class call applies) makes that
    receiver and runs this universe on it (``enter_initializer``).  So the
    class statement's halts (#7794) are this universe's halts, an unrun
    source ``__new__`` refuses it by name, and no receiver is made here.

    A function reduced on its own is called from outside its module's run:
    its body reads each module global through the module's final binding,
    and the frame entry every call takes binds those keys, before the body
    runs, to the values the module body's run bound them to, each demanded
    only where its key is read (``call_site_sugar.
    with_module_final_globals``, ``module_end_contexts``).
    """
    from sugar_lift_py_tests.sugar.call_site_sugar import with_module_final_globals
    from sugar_source_tree.nodes import current_module_execution_site

    sugar = fn.sugar()
    site = current_module_execution_site()
    owner = fn._active_initializer_owner()
    if owner is None:
        return sugar.desugar(with_module_final_globals(None, (fn,), site=site))

    from sugar_lift_py_tests.context import ReduceContext
    from sugar_source_tree.panic import SugarNotWritten

    if not fn.params:
        raise SugarNotWritten(
            owner="function_universe_outcome",
            blame=fn.fragment,
            observed="class initializer has no receiver parameter",
            requested="the active initializer receiver coordinate",
            fix="preserve the parsed receiver parameter on __init__",
        )
    receiver_coordinate = fn._constructed_receiver_coordinate(owner, fn.params[0])
    constructor = owner.source_visible_constructor_frame().body
    if constructor.receiver_coordinate_cid != receiver_coordinate.cid:
        raise SugarNotWritten(
            owner="function_universe_outcome",
            blame=fn.fragment,
            observed="the class call seats its initializer receiver elsewhere",
            requested="the receiver the class call makes for this initializer",
            fix="construct the initializer through its lexical class owner",
        )
    return constructor.enter_initializer(
        with_module_final_globals(
            ReduceContext.root(owner="function_universe_outcome"), (fn,), site=site
        ),
        lambda _definition, initializer_ctx: sugar.desugar(initializer_ctx),
    )


def reduction_rows(outcome, *, owner, blame, def_memento):
    """THE projection from one reduction to its wire rows (#7766).

    A function body's one reduction (``function_contract_rows``) becomes rows
    here and nowhere else; enumerate never applies a body at a call itself
    (#7757 item 12: a contract is applied at prove). ``outcome`` is an
    ``ExitSet`` of completed and halted arms (one completed arm under guard
    true is the one-arm case); ``owner`` states the name, formals and symbol
    when no arm completed. ``None`` when the outcome is not a set of arms.
    """
    from sugar_lift_py_tests.floor.universe_value import (
        UniverseValue,
        exit_arms_payload_rows,
    )
    from sugar_lift_py_tests.outcome import ExitSet
    from sugar_lift_py_tests.outcome.exit_set import Completed, Halted

    if isinstance(outcome, ExitSet):
        arms = tuple(
            (exit_.guard, exit_.value)
            for exit_ in outcome.exits
            if isinstance(exit_, Completed)
        )
        halted_sites = halted_assertion_sites(
            exit_ for exit_ in outcome.exits if isinstance(exit_, Halted)
        )
        unread = [
            type(exit_).__name__
            for exit_ in outcome.exits
            if not isinstance(exit_, (Completed, Halted))
        ]
        if unread:
            from sugar_source_tree.panic import SugarNotWritten

            raise SugarNotWritten(
                owner="reduction_rows",
                blame=blame,
                observed=f"exit arms {sorted(set(unread))}",
                requested="a completed or halted arm",
                fix="give the exit algebra's arm its projection to rows",
            )
    else:
        return None
    for _guard, value in arms:
        if not isinstance(value, UniverseValue):
            from sugar_source_tree.panic import SugarNotWritten

            raise SugarNotWritten(
                owner="reduction_rows",
                blame=blame,
                observed=f"completed arm holds {type(value).__name__}",
                requested="the function body's UniverseValue",
                fix="complete a function body arm with its universe",
            )
    stated = arms[0][1] if arms else owner
    return exit_arms_payload_rows(
        name=stated.name,
        formals=tuple(stated.formals),
        bridge_source_symbol=stated.bridge_source_symbol,
        formal_coordinates=tuple(stated.formal_coordinates),
        arms=arms,
        halted_assertion_sites=halted_sites,
        def_memento=def_memento,
    )


def function_contract_rows(fn, file_rel: str):
    """A function's contract DTO rows, read off EVERY arm of its one reduction.

    `fn.sugar()` constructs the FunctionUniverseSugar; desugar reduces the body
    to an ``ExitSet`` of completed and halted arms. ``exit_arms_payload_rows``
    projects all of them: the post over every completed arm, and one row per
    assertion site (see there). One completed arm under guard true is the
    one-arm case.

    An outcome that is not a set of arms (a deferred native operation,
    ``NativeOperationExitCarrierV1``, whose arms exist only once a caller
    discharges it with actuals) emits no contract: the function is
    (memento, None). Its carrier's own formula still meets the scope law
    (``require_outcome_in_scope``). A halt is an arm: a body that only halts
    states its halted arms like any other set. Every row is read off this one
    reduction; no other lifter adds to it (#7767). A SugarNotWritten from an
    unported body statement propagates (the whole function is a frontier gap).
    """
    from sugar_lift_py_tests.outcome import ExitSet

    def_memento = function_def_memento(fn, file_rel)
    outcome = owner_reduction(fn).outcome
    if not isinstance(outcome, ExitSet):
        require_outcome_in_scope(outcome, fn.sugar())
        return def_memento, None
    return def_memento, reduction_rows(
        outcome,
        owner=fn.sugar(),
        blame=fn.fragment,
        def_memento=def_memento,
    )


def call_nodes_in_assert(sf: SourceFile, span: Optional[dict]) -> list:
    """The plain named Call nodes inside the assertion at `span`, in walk order.
    The cue's own AST: each carries the callee name AND the actual argument
    nodes -- the pre this call fills."""
    from sugar_source_tree.nodes import Call, Name

    _source, node = temporally_rewritten_assert(sf, span)
    if node is None:
        return []
    return [
        call
        for call in node.walk()
        if isinstance(call, Call) and isinstance(call.func, Name)
    ]


def _roll_call_identity(entry) -> tuple:
    """The SAME identity ``MinorityReport`` uses for present/minority.

    Equal source text seals to one CID at distinct loci; those seats are
    distinct obligations. Never key presence by CID alone.
    """
    return (entry.file, entry.start_line, entry.start_col, entry.kind, entry.cid)


def assert_source_audit_ledger(
    *,
    warranted: int,
    unresolved: int,
    source_loci: int,
    report_R: int,
) -> None:
    """Panic tooth for source-audit ledger conservation.

    The historical dual-producer drift (SIN CLUSTER 7 / lift_rpc path) was:
    status keyed by CID alone (inflating warranted) while ``source_unresolved``
    was taken from ``report.R`` (still counting the absent shared-CID seat).
    Then ``warranted + report.R > source_loci`` and Yellow silently became Blue.

    The tooth that sings is therefore:

        warranted + report_R == source_loci
        AND unresolved == report_R

    A status-only sum ``warranted + unresolved == source_loci`` is NOT a tooth:
    when every locus is assigned exactly one of {warranted, unresolved}, that
    equality is tautological and stays green under the illegal CID-alone map.
    That decorative shell was deleted; this function is the live replacement.

    Retirement path: if presence status becomes unconstructable except via
    full-tuple identity (typed present set / closed seat key), this assert
    remains as contact panic for ledger arithmetic only, or retires if the
    wire totals become derived fields of a single typed partition value.
    """
    if warranted + report_R != source_loci:
        raise AssertionError(
            f"source-audit conservation broken: warranted({warranted}) + "
            f"report.R({report_R}) != source_loci({source_loci}); "
            "CID-alone presence inflates warranted while R still counts the "
            "absent seat — key presence by (file, line, col, kind, cid)"
        )
    if unresolved != report_R:
        raise AssertionError(
            f"source-audit unresolved({unresolved}) != report.R({report_R}); "
            "presence must use the full roll-call identity, not CID alone"
        )


def source_audit_from_report(report, file_rel: str) -> dict:
    """ONE door: project a ``MinorityReport`` onto the source-audit wire.

    Presence is keyed by the full roll-call identity
    ``(file, line, col, kind, cid)`` — the same tuple ``MinorityReport`` uses.
    Status and the three ledger totals are derived once from that partition.
    There is no second producer of ``source_unresolved`` (no independent
    ``report.R`` path, no CID-only set kept "in sync").

    Conservation is a tooth, not a print: ``warranted + report.R == source_loci``
    (and ``unresolved == report.R``). See ``assert_source_audit_ledger``.
    """
    present_keys = {_roll_call_identity(entry) for entry in report.present}
    loci = []
    for entry in report.roster:
        status = (
            "warranted" if _roll_call_identity(entry) in present_keys else "unresolved"
        )
        loci.append(
            {
                "status": status,
                "kind": entry.kind,
                "name": entry.name,
                "source_cid": entry.cid,
                "locus": {
                    "file": file_rel,
                    "line": entry.start_line,
                    "col": entry.start_col,
                },
            }
        )
    warranted = sum(1 for locus in loci if locus["status"] == "warranted")
    unresolved = sum(1 for locus in loci if locus["status"] == "unresolved")
    source_loci = len(loci)
    assert_source_audit_ledger(
        warranted=warranted,
        unresolved=unresolved,
        source_loci=source_loci,
        report_R=report.R,
    )
    return {
        "role": file_rel,
        "loci": loci,
        "totals": {
            "source_loci": source_loci,
            "source_warranted": warranted,
            "source_unresolved": unresolved,
        },
    }
