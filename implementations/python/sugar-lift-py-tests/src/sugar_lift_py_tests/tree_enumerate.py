"""Enumeration served by the AST tree, not the factory.

The `universe` level is served by walking the tree the parser produces and
reading each function's one reduction (``owner_reduction``) into its contract
rows. The RPC drives AST walking directly; the factory is not consulted. The
levels that walked below a function (call_sites, assertions, facts) and the
universe seek by a call-site cue had no driver and are deleted (#7757).
"""

from __future__ import annotations

import json
from typing import Optional

from sugar_source_tree.construction_cache import AmbientSet
from sugar_source_tree.tree import SourceFile
from sugar_source_tree.nodes import Assert


def halted_assertion_sites(halted_arms, definition) -> tuple:
    """The ``assert`` statements of ``definition``'s own body at which a
    halted arm of its reduction left.

    Read off the reduction, never off the source: a halted arm's raise carries
    the exception value it raised, and that value carries the fragment it was
    raised at. When that fragment is an ``assert`` statement the reduction
    reached the assertion and control halted there. A raise from inside the
    assertion's operands is sited at the operand, and an ``assert`` no arm
    reached is sited nowhere: neither is an assertion the reduction halted at.

    Only an ``assert`` of ``definition``'s own body is a claim of its
    contract (``own_assertion_sites``); ``None`` owns none.  A class's
    contract is the construction (``class_contract_rows``): an ``assert`` in
    its ``__init__`` that fails is a halt of the call, stated as a panic
    locus (``assert_sugar.halts_where_its_asserts_fail``),
    and its claim is ``__init__``'s own row's.  Stated as the class's, the
    claim held on no completed arm of the construction (the object, never
    ``__init__``'s record) and read ``false``: the class row was refuted
    whatever the actual, and every caller joined to it with it.
    """
    from sugar_lift_py_tests.effect import RaiseEffect
    from sugar_lift_py_tests.floor import ExceptionValue
    from sugar_lift_py_tests.floor.universe_value import assertion_site_key

    own = {assertion_site_key(site) for site in own_assertion_sites(definition)}
    sites = []
    for arm in halted_arms:
        effect = arm.effect
        if not isinstance(effect, RaiseEffect):
            continue
        raised = effect.raised_value
        if not isinstance(raised, ExceptionValue):
            continue
        if (
            isinstance(getattr(raised.site, "node", None), Assert)
            and assertion_site_key(raised.site) in own
        ):
            sites.append(raised.site)
    return tuple(sites)


def own_assertion_sites(definition) -> tuple:
    """The fragments of the ``assert`` statements of ``definition``'s own
    body, in source order: a nested ``def``, ``class`` or ``lambda`` is
    another frame and states its own.  ``None`` (a class's contract, whose
    statement body runs where the class statement stands) owns none."""
    from sugar_source_tree.nodes import (
        AsyncFunctionDef,
        ClassDef,
        FunctionDef,
        Lambda,
        Node,
    )

    if definition is None:
        return ()
    sites = []
    seen_nodes: set = set()
    body = getattr(definition, "body", ()) or ()
    # A ``def``'s body is its statements; a lambda's is one expression,
    # which holds no ``assert``.
    stack = [body] if isinstance(body, Node) else list(reversed(tuple(body)))
    while stack:
        node = stack.pop()
        if id(node) in seen_nodes:
            continue
        seen_nodes.add(id(node))
        if isinstance(node, (FunctionDef, AsyncFunctionDef, ClassDef, Lambda)):
            continue
        if isinstance(node, Assert):
            sites.append(node.fragment)
            continue
        stack.extend(child for _field, _index, child in reversed(node.children()))
    return tuple(sites)


def unreached_assertion_sites(definition, halted_arms) -> tuple:
    """The ``assert`` statements of ``definition``'s own body that no halted
    arm of its reduction passed, for a reduction that has no completed arm.

    The function states these claims; the reduction says whether and how
    each is decided. Only which ``assert`` statements the body holds is read
    off the tree (its own body: a nested ``def``, ``class`` or ``lambda`` is
    another frame and states its own). An assertion a halted arm held on its
    way to the halt rode that arm's record and is not one of these: the arm
    passed it (a fact held before a later halt is not refuted). The
    assertion a halted arm left at is the reduction's own site
    (``halted_assertion_sites``) and is stated there.
    """
    from sugar_lift_py_tests.floor.inv_value import InvValue
    from sugar_lift_py_tests.floor.universe_value import assertion_site_key

    passed = {
        assertion_site_key(entry.site)
        for arm in halted_arms
        for entry in getattr(arm.state, "entries", ())
        if isinstance(entry, InvValue) and entry.site is not None
    }
    return tuple(
        site
        for site in own_assertion_sites(definition)
        if assertion_site_key(site) not in passed
    )


def _stated_fragment(holder):
    """The source fragment ``holder`` states, or ``None`` when it states none:
    the fragment itself, or one an operation still carries as ``site`` or
    ``blame`` (the admission ``resolve_runtime_effect_site`` makes)."""
    from sugar_lift_py_tests.effect.runtime_effect import RuntimeEffectSite

    for candidate in (
        holder,
        getattr(holder, "site", None),
        getattr(holder, "blame", None),
    ):
        if isinstance(candidate, RuntimeEffectSite):
            return candidate
    return None


def halt_site(effect, *, blame):
    """Where a halt happened: the one answer (#7766, #7757).

    Both readers of the question read this: the proof's panic locus
    (``halt_locus``) and every refusal about a halt that states where it
    halted (the raise matcher, ``_message_term``, ``TrySugar``'s except-type
    refusal). Read off the halt record, never off the source:

    * the fragment the halt left at, stated on its effect (``site``: the
      ``raise`` statement, the operation whose two faces it is, the ground
      exit, the ``with`` item whose manager step or exit raised, the
      ``break``/``continue``, the ``warnings.warn`` call, the unmet
      expectation); a runtime effect's witness carries the fragment of its
      boundary;
    * then, for a raise built before its effect carried the fragment, the
      fragment of the exception value it threw.

    The occurrence key is not an answer: it keys the exception object, it is
    not where the halt happened. A halt whose record states no fragment is
    refused by name, blamed on ``blame``: two such halts would be
    indistinguishable, so neither can be stated by where it happened.
    """
    from sugar_lift_py_tests.effect import (
        RaiseEffect,
        RuntimeEffect,
        UndeterminedRaiseEffect,
    )
    from sugar_lift_py_tests.floor import ExceptionValue

    if isinstance(effect, RuntimeEffect):
        fragment = _stated_fragment(effect.witness.site)
    else:
        # Every other halt states the fragment on its own ``site``.
        fragment = _stated_fragment(effect)
        if (
            fragment is None
            and isinstance(effect, (RaiseEffect, UndeterminedRaiseEffect))
            and isinstance(effect.raised_value, ExceptionValue)
        ):
            fragment = _stated_fragment(effect.raised_value.site)
    if fragment is None:
        from sugar_source_tree.panic import SugarNotWritten

        producer = getattr(effect, "producer_node_owner", None)
        raise SugarNotWritten(
            owner="tree_enumerate.halt_site",
            blame=blame,
            observed=(
                f"a halt whose {type(effect).__name__} states no source "
                f"fragment (producer {producer!r})"
            ),
            requested="the fragment the halt left at",
            fix=(
                f"carry the halting operation's fragment on the "
                f"{type(effect).__name__} it builds (its ``site``)"
            ),
        )
    return fragment


def halt_locus(arm, *, formals, def_memento, blame):
    """One halted arm of a reduction, as its panic-locus row (#7766, ruling 3).

    Filled from the reduction: the site, the raised type, and the guard as
    path condition. Read off the arm's own halt record, never off the source.

    * site: where the halt happened (``halt_site``, which refuses by name a
      halt that states none).
    * term: the raised type's coordinate for a raise (``None`` when the type is
      undetermined) and the failing operation for a runtime effect.
    * guard: the arm's guard, in the contract's claim form
      (``universe_value.contract_claim``), scoped to ``formals``.
    """
    from sugar_lift_py_tests.effect import (
        GroupedRaiseEffect,
        RaiseEffect,
        RuntimeEffect,
        UndeterminedRaiseEffect,
    )
    from sugar_lift_py_tests.floor.universe_value import contract_claim
    from sugar_lift_py_tests.ir import Term
    from sugar_lift_py_tests.kit_rpc import PanicLocusDto

    effect = arm.effect
    fragment = halt_site(effect, blame=blame)
    term = None
    if isinstance(effect, RuntimeEffect):
        term = effect.witness.operation
    elif isinstance(effect, (RaiseEffect, UndeterminedRaiseEffect)):
        term = effect.exception_type_coordinate
    elif isinstance(effect, GroupedRaiseEffect) and isinstance(
        effect.exception_type_coordinate, Term
    ):
        term = effect.exception_type_coordinate
    return PanicLocusDto(
        file=fragment.filename,
        line=fragment.line,
        arg_term=term,
        guard=contract_claim(
            arm.guard,
            formals=formals,
            def_memento=def_memento,
            role="guard",
            floor_chain=("Halted.guard",),
        ),
    )


class OwnerReduction:
    """One reduction of a function (or module) and what it recorded.

    ``outcome`` is the reduction's outcome: an assert inside it reaches the
    proof only through the outcome's rows. Its unanswered calls are owed by
    the outcome's own arms (``unanswered_calls.owed_calls``). ``ends`` is,
    for a module, each completed arm of its run holding the context it ended
    with, under the arm's guard and faces (``ModuleBlockSugar.run``); a
    function's reduction has none.
    """

    __slots__ = ("unit", "outcome", "ends")

    def __init__(self, unit, outcome, ends=()):
        self.unit = unit
        self.outcome = outcome
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

    Every reader of a function's reduction reads this one: the universe rows
    and the link-unit enrollment. An assert is therefore reduced once, in
    context, and never alone. A refusal is not kept: it propagates to the
    reader, named.
    The unanswered calls the reduction left are owed by its outcome's arms,
    so a reduction read back from here carries them as the first one did.
    A module's reduction is its body's one run (``ModuleBlockSugar.run``),
    under no module execution site, as an import runs it; it keeps the
    context each completed arm ended with (``OwnerReduction.ends``).  It
    is the module's run under way (``_MODULE_RUNS_UNDER_WAY``), however it
    is asked for: the marker is set by this reduction's own row, so it is
    never ambient to that row, and the row is served after the run, from
    ``module_end_contexts`` or not, without running the module again.  A
    row computed inside the run that read the marker still records it.
    """
    from sugar_source_tree.construction_cache import (
        abandon_row,
        close_row,
        open_row,
        serve,
    )

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
        if owner is not None:
            from sugar_source_tree.nodes import ClassDef

            outcome = (
                class_universe_outcome(owner)
                if isinstance(owner, ClassDef)
                else function_universe_outcome(owner)
            )
        else:
            outcome, ends = _module_run(node.unit, sf)
    except BaseException:
        # A refusal is not kept: what the reduction read and said belongs
        # to the computation around it.
        abandon_row(computation)
        raise
    held = OwnerReduction(node.unit, outcome, ends)
    close_row(_OWNER_REDUCTIONS, key, computation, node.reporter, value=held)
    return held


# The units whose module run is under way.  Set by the module's own
# reduction row (``_module_run``), so it is never ambient to that row; it is
# ambient to every other memo row: an answer computed inside a module's run
# that read that run as under way (a cycle back to its final bindings, or
# another module's run reached through it) is served only where it is under
# way again.
_MODULE_RUNS_UNDER_WAY: AmbientSet = AmbientSet("module_runs_under_way")


def _module_run(unit, sf) -> tuple:
    """``unit``'s module body run once, under no module execution site, as
    an import runs it, marked under way while it runs.  Called with the
    module's reduction row (``owner_reduction``) innermost, so the marker
    is that row's own act: its reads of it are not its inputs."""
    from sugar_source_tree.nodes import construct_at_module_execution_site

    _MODULE_RUNS_UNDER_WAY.add(id(unit))
    try:
        return construct_at_module_execution_site(
            None, lambda: sf.root.sugar().run(None)
        )
    finally:
        _MODULE_RUNS_UNDER_WAY.discard(id(unit))


# Each unit's module run, remembered through the one door for memo rows
# (``construction_cache``): the run's reduction (its outcome and the context
# each completed arm ended with), or the refusal the run raised, re-raised on
# every hit.  Keyed by the unit's id; the unit is pinned beside its rows, so
# the id is never recycled under them.
_MODULE_RUNS: dict = {}
_MODULE_RUN_UNITS: dict = {}


def module_end_contexts(unit) -> tuple:
    """The completed arms of ``unit``'s module run, each holding the context
    it ended with under its own guard and faces (``ModuleBlockSugar.run``):
    the one source of module-final global values (#7757 item 7).

    The run is THE module reduction (``owner_reduction`` with no owner),
    run once, at the root occurrence path, as an import runs it, wherever
    it is asked for (``_module_run_reduction``).  A function called after
    import reads a global through the module's final binding of it, the key
    of the module body's last write; the value the run bound under that key
    is its value, whatever the write evaluated (a literal, ``x += e``, a
    call's result, a list), evaluated once and read only where the key is
    read (``call_site_sugar.ModuleFinalValue``).  Only completed arms: a
    function is called after an import that completed.

    Empty, so each such read is refused by name, where the run completes on
    no arm (every arm halts: ``module_run_halts`` is what a read of a class
    statement's key is then), and where it is asked for while it runs (a
    run that reaches, through another module's function, a read of this
    module's final binding).
    """
    held = _module_run_reduction(unit)
    return () if held is None else held.ends


def module_run_halts(unit) -> tuple:
    """The halted arms of ``unit``'s module run where it completes on no
    arm, read off the one module reduction (``_module_run_reduction``); else
    empty.

    No import of such a module completes: every route to a function of it
    goes through one of these halts, which is how Python ends that import
    (``X = 1 // 0``, a class statement whose body or base raises).  So a read
    after import of a key only that run binds, which no completed arm bound
    because there is none, is the run's halts, each as the run reached it
    (``DecoratorApplicationSugar``, a read of a class's name; #7757 item 21,
    #7766).  The halts are the run's own arms, carried; nothing is reduced
    again for the reader.  Empty while the run is under way, where some arm
    completes, and where the run is not a set of arms (it waits on a
    caller's actuals): a read with nothing bound there is refused by name.
    """
    from sugar_lift_py_tests.outcome import Completed, ExitSet

    held = _module_run_reduction(unit)
    if held is None or held.ends:
        return ()
    outcome = getattr(held, "outcome", None)
    if not isinstance(outcome, ExitSet):
        return ()
    if any(isinstance(face, Completed) for face in outcome.exits):
        return ()
    return tuple(outcome.halts())


MODULE_RUN_NAME = "<module>"
"""The name the module body's one run is stated under, Python's own name for
a module's code (``co_name``): the module is no function and has no target
symbol of its own."""


def module_run_memento(sf: SourceFile, file_rel: str):
    """The SourceMemento of the module itself (``statement_memento`` over
    its root, under ``MODULE_RUN_NAME``): the warrant of what its one run
    owes (``module_run_owed_calls``) or refuses (``refused_module_row``)."""
    return statement_memento(sf.root, MODULE_RUN_NAME, file_rel)


def module_run_owed_calls(sf: SourceFile) -> tuple:
    """Every unanswered call the module body's one run owes, read off THE
    module reduction's final arms (``_module_run_reduction``) by the one
    reader a function's reduction is read by (``unanswered_calls.owed_calls``).

    The module run is a reduction like a function's: what its arms left
    unanswered (a module-level ``x = undecided_call()``, an imported
    decorator's application ``@elsewhere.wrap``) is owed by the file's proof
    exactly as a function's is (step 8), whether or not any function reads
    what it made.  A refusal by name of the run propagates to the caller,
    who states it (``refused_module_row``)."""
    from sugar_lift_py_tests.unanswered_calls import owed_calls

    held = _module_run_reduction(sf.unit)
    if held is None:
        raise ValueError(
            "the module run's debts were asked for while the run is under way: "
            "owner=module_run_owed_calls "
            "replacement=read them after the run, from the file scan"
        )
    return owed_calls(held.outcome)


def _module_run_reduction(unit):
    """``unit``'s module run: THE module reduction (``owner_reduction`` with
    no owner, an ``OwnerReduction``), run once, at the root occurrence path,
    as an import runs it, wherever it is asked for.  None where it is asked
    for while it runs.

    Where the run refuses (a construction gap), the refusal is remembered as
    loudly as an answer, by the memo row's own door
    (``construction_cache.close_row``), and the same refusal reaches every
    read that asks: the run is never run again for the next reader, and its
    refusal is never caught to read as an answer.
    """
    from sugar_lift_py_tests.occurrence import occurrence_path
    from sugar_source_tree.construction_cache import (
        abandon_row,
        close_row,
        open_row,
        serve,
    )
    from sugar_source_tree.panic import LifterRefusal

    key = id(unit)
    if key in _MODULE_RUNS_UNDER_WAY:
        return None
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
    try:
        # The module's reduction marks its own run under way
        # (``_module_run``): a reduction row served here or computed here
        # is the one a later ``owner_reduction(None)`` is served.
        with occurrence_path(()):
            held = owner_reduction(None, unit.constructed_module)
    except LifterRefusal as panic:
        # The one refusal (either family), remembered as loudly as an answer
        # and raised on.
        _MODULE_RUN_UNITS[key] = unit
        close_row(_MODULE_RUNS, memo, computation, reporter, panic=panic)
        raise
    except BaseException:
        # Anything else is a property of this traversal, never remembered.
        abandon_row(computation)
        raise
    _MODULE_RUN_UNITS[key] = unit
    close_row(_MODULE_RUNS, memo, computation, reporter, value=held)
    return held


LAMBDA_NAME = "<lambda>"
"""The source name a lambda is stated under, Python's own name for it
(``__name__``, ``co_name``): a lambda binds no name of its own."""


def function_def_memento(fn, file_rel: str):
    """The function's own SourceMemento (the def warrant payload_rows needs):
    a ``def`` under its name, a ``lambda`` under ``LAMBDA_NAME``."""
    from sugar_lift_py_tests.kit_rpc.source_memento_dto import SourceMementoDto
    from sugar_lift_py_tests.kit_rpc.source_span_dto import SourceSpanDto
    from sugar_source_tree.nodes import Lambda

    lc = fn.line_col_span()
    return SourceMementoDto(
        file=file_rel,
        span=SourceSpanDto(lc.start_line, lc.start_col, lc.end_line, lc.end_col),
        source_cid=fn.fragment.seal().cid,
        source_function_name=LAMBDA_NAME if isinstance(fn, Lambda) else fn.name,
        param_names=[p.name for p in fn.params],
    )


# What one definition's rows may state inline, in serialized bytes.  A proof
# states every term inline (#7843): the fold resolves every term-ref a row
# carries into its term before mint (``tree::decode_enumerate_result``), so a
# row whose term DAG is small can state a term many times its DAG's size --
# a subterm shared by every arm is written out once per arm.  Past the
# transport's finite-or-refuse bound (256 MiB, ``kit_path::lift_plugin``)
# the WHOLE file's response is swapped for a marker that is no lift response
# at all, and mint ended the file on it (``lift response missing `kind`
# field``: pandas ``core/interchange/utils.py``, ``io/formats/style_render.py``,
# run 43960179946).  The definition that cannot be stated is the one
# refused, by name, inside the file's proof; the rest of the file is served.
# Sixteen definitions at the bound still fit the transport's.
STATED_DEFINITION_BYTE_BOUND = 16 * 1024 * 1024


class StatedRow:
    """One row already lowered through the scan's term table: what
    ``stated_rows`` measured is what the wire carries, lowered once."""

    __slots__ = ("wire",)

    def __init__(self, wire):
        self.wire = wire

    def to_rpc_with_term_table(self, _table):
        return self.wire


def stated_rows(rows, term_table, memento):
    """``rows`` (one definition's contract rows, or None for an effect)
    lowered through ``term_table`` as the universe scan writes them, or the
    definition at ``memento`` refused by name when they state more than
    ``STATED_DEFINITION_BYTE_BOUND`` bytes inline.

    Raised inside the scan's one ``try`` for the definition, the refusal is
    its ``undecided`` row by the one rule (``refused_function_row``,
    ``refused_class_row``); nothing is truncated and no row is dropped.  The
    size is the inline statement's, read off the DAG once per term
    (``stated_inline_bytes``), never by expanding it."""
    if not rows:
        return rows
    wire = [row.to_rpc_with_term_table(term_table) for row in rows]
    stated = stated_inline_bytes(wire, term_table.nodes)
    if stated <= STATED_DEFINITION_BYTE_BOUND:
        return [StatedRow(row) for row in wire]
    from types import SimpleNamespace

    from sugar_source_tree.panic import SugarNotWritten

    raise SugarNotWritten(
        owner="tree_enumerate.stated_definition_bound",
        blame=SimpleNamespace(
            filename=memento.file,
            line=memento.span.start_line,
            col=memento.span.start_col,
        ),
        observed=(
            f"rows stating {stated} bytes inline, past the "
            f"{STATED_DEFINITION_BYTE_BOUND}-byte bound of one definition"
        ),
        requested="a statement of the definition's terms within the bound",
        fix=(
            "find the term the definition's arms share and state it once "
            "(a carried value, never a copy per arm); do not raise the bound"
        ),
    )


def stated_inline_bytes(value, nodes) -> int:
    """Bytes of ``value`` serialized compactly with every term-ref replaced by
    the term it names (``nodes``: a ``TermTableBuilder``'s CID-keyed rows),
    as the fold resolves it.

    Each term's size is counted once and read from its CID thereafter, on an
    explicit worklist: the DAG is walked, the expansion never built, and a
    deep term spine does not lean on the call stack.  A CID ``nodes`` lacks
    is counted as the reference itself; the fold's decode is what refuses a
    dangling reference."""
    sizes: dict[str, int] = {}

    def scalar(item) -> int:
        return len(
            json.dumps(item, separators=(",", ":"), ensure_ascii=False).encode(
                "utf-8"
            )
        )

    def term_ref_cid(item):
        if (
            isinstance(item, dict)
            and item.get("kind") == "term-ref"
            and isinstance(item.get("cid"), str)
        ):
            return item["cid"]
        return None

    def refs_in(item) -> list:
        found = []
        pending = [item]
        while pending:
            current = pending.pop()
            cid = term_ref_cid(current)
            if cid is not None:
                found.append(cid)
            elif isinstance(current, dict):
                pending.extend(current.values())
            elif isinstance(current, (list, tuple)):
                pending.extend(current)
        return found

    def measure(item) -> int:
        # Every term-ref ``item`` holds is already sized.
        total = 0
        pending = [item]
        while pending:
            current = pending.pop()
            cid = term_ref_cid(current)
            if cid is not None and cid in sizes:
                total += sizes[cid]
            elif isinstance(current, dict):
                total += 2 + max(len(current) - 1, 0)
                for key, child in current.items():
                    total += scalar(str(key)) + 1
                    pending.append(child)
            elif isinstance(current, (list, tuple)):
                total += 2 + max(len(current) - 1, 0)
                pending.extend(current)
            else:
                total += scalar(current)
        return total

    entered: set[str] = set()
    work = [(cid, False) for cid in refs_in(value)]
    while work:
        cid, ready = work.pop()
        if cid in sizes:
            continue
        node = nodes.get(cid)
        if node is None or (not ready and cid in entered):
            # Dangling, or a cycle no content address can make: counted as
            # the reference, left for the fold's decode to refuse.
            sizes[cid] = scalar({"kind": "term-ref", "cid": cid})
            continue
        if not ready:
            entered.add(cid)
            work.append((cid, True))
            work.extend((child, False) for child in refs_in(node) if child not in sizes)
            continue
        sizes[cid] = measure(node)
    return measure(value)


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
    """The ``undecided`` row for a function the lifter refuses by name.

    One rule (step 8): any ``LifterRefusal`` (either family, every subclass
    but ``BackendDefect``) raised constructing or reducing the function. The
    reason is the refusal's own testimony (``diagnostic``): its name
    (``owner``) and what it observed. The symbol is read off the definition
    (``FunctionDef.bridge_source_symbol``), never off its construction, which
    is what refused.
    """
    return _refused_row(
        function_def_memento(fn, file_rel),
        fn.bridge_source_symbol(),
        refusal,
        file_rel,
    )


def refused_module_row(sf: SourceFile, file_rel: str, refusal) -> UndecidedRow:
    """The ``undecided`` row for a module body whose one run the lifter
    refuses by name (``module_run_owed_calls``), by the same rule as a
    refused function (``refused_function_row``): the refusal's own name and
    what it observed, at the module (``module_run_memento``).  The module
    has no target symbol of its own (``None``).  What the run would have
    owed is not known, so the refusal is stated, never dropped."""
    return _refused_row(module_run_memento(sf, file_rel), None, refusal, file_rel)


def _refused_row(memento, symbol, refusal, file_rel: str) -> UndecidedRow:
    """The one ``undecided`` row of a refusal by name at ``memento``'s
    span: ``symbol`` (or ``None``), the refusal's testimony as the reason."""
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceFragmentCoordinateV1,
    )

    coordinate = SourceFragmentCoordinateV1(
        memento.source_cid,
        memento.span.start_line,
        memento.span.start_col,
        memento.span.end_line,
        memento.span.end_col,
    )
    testimony = refusal.diagnostic()
    return UndecidedRow(
        symbol=symbol,
        site=_undecided_site(file_rel, coordinate),
        reason={
            "refused": {
                "owner": testimony["owner"],
                "observed": testimony["observed"],
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


def statement_memento(statement, name: str, file_rel: str):
    """The SourceMemento of a module-level node under ``name``: the statement
    that binds ``name`` (a ``class``, or a package's re-exporting ``from ...
    import``), its ancestry row's warrant; or the module itself, its one
    run's rows' warrant (``module_run_memento``)."""
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
        memento = statement_memento(statement, name, file_rel)
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


CLASS_NAMESPACE_SUFFIX = "::namespace"
"""The contract-name suffix of a class's namespace row: ``<symbol>`` + this.
The verifier reads the class symbol off the row name by this suffix, and the
row is a statement of fact, never a claim to check (``consistency.rs``,
``CLASS_NAMESPACE_SUFFIX``)."""

#: The kinds of namespace value the dispatch joins, each stated with the join
#: symbol of the function it holds and bound at prove as Python's descriptor
#: protocol binds it read off an instance (``consistency::
#: DISPATCH_*_KIND``, ``DispatchReceiver``): a plain ``def`` the body wrote
#: (bound to the instance); a function the class holds as a field
#: (``m = lambda self: ...``, bound to the instance); a ``def`` under the
#: builtin ``staticmethod`` (nothing bound), ``classmethod`` (the instance's
#: class bound) or ``property`` (its getter, called with the instance where
#: the attribute is read).
_FUNCTION_KIND = "function"
_FIELD_KIND = "field"
#: A single-target assignment of a literal or a display to the name
#: (``x = 1``, ``x = (a, b)``, ``x = {}``): a value of a builtin class that
#: defines no ``__get__``, so a read of it off an instance is the value
#: itself where no hook runs (``consistency::NAMESPACE_VALUE_KIND``,
#: ``class_read_holds``).  It names no function: no dispatch joins it.
_VALUE_KIND = "value"
#: A name only CPython's type creation may write (``nodes._TYPE_CREATION_NAMES``
#: the body does not bind and no module store names): whether the class holds
#: it is undecided as for ``undecided``, and what it may hold is type
#: creation's own entry -- for ``__dict__`` the instance-dict descriptor, the
#: plain ``__dict__`` path itself (``consistency::NAMESPACE_CREATION_KIND``,
#: never a hook of ``plain_access_holds``).
_CREATION_KIND = "creation"
_DESCRIPTOR_KINDS = frozenset({"staticmethod", "classmethod", "property"})


def class_namespace_row(cls, file_rel: str) -> list:
    """The one row a class this file states a constructor contract for
    (``classes_with_contracts``) states when its namespace is closed: what a method call
    on an instance of it is dispatched on at prove (#7757 step 8,
    ``consistency::dispatched_symbol``).

    The row is a ``contract`` named ``<class symbol>::namespace`` whose
    ``inv`` states, read off the class statement alone (nothing is reduced):

    - ``python:class_mro(<C>, <C>, <entry>...)``: its order, the one base walk
      (``ClassDef.method_resolution_order``), a source class by its join
      symbol, a builtin class as ``builtins.<name>``;
    - ``python:class_binds(<C>, <name>, <kind>, <symbol>)`` for each name its
      own namespace may hold (``ClassDef.namespace_binds`` not False), with
      the join symbol of the function it holds where its kind is one the
      dispatch binds (``_namespace_value_kind``): ``function`` for a plain
      ``def`` the body wrote and holds (``namespace_value_is_body``:
      undecorated, not a generator, not ``async``); ``staticmethod``,
      ``classmethod`` or ``property`` for such a ``def`` under that one
      builtin decorator (``ClassDef._method_descriptor_kind``); ``field``
      for a lambda the body assigns to the name; ``value`` (no symbol) for
      a literal or display the body assigns to the name (``_VALUE_KIND``:
      its class defines no ``__get__``); ``undecided`` where the
      lookup does not decide whether it holds it (``creation`` where that is
      only because type creation may write it, ``_CREATION_KIND``); ``other``
      for anything
      else (another decorator, a field of any other value, a nested class);
    - ``python:class_object(<C>, <class term>)``, where a ``classmethod`` is
      bound: the term the class object is spelled by
      (``class_definition_value.class_definition_term``), what a
      ``classmethod`` read off an instance binds first.  A class whose
      statement is refused by name states none, and its ``classmethod``s
      stay owed at prove.

    A class whose order is not read, one with a source class of no join
    symbol in it, or one whose namespace is open (a keyword, a decorator the
    lifter does not model, a module store that may write any name,
    ``ClassDef._creation_writes``) states no row: a method call on it is not
    dispatched.  A refusal by name reading the namespace (or the class
    statement a ``classmethod``'s class object is spelled by) is not caught
    here: the scan reads this row inside the class's one ``try``
    (``lift_rpc._handle_enumerate``), so the refusal is the class's refused
    member, the one ``undecided`` row, never a row silently left out.

    Returns ``(memento, dto)`` pairs (none or one), the shape of the universe
    scan's rows.
    """
    from sugar_lift_py_tests.floor.universe_mint_projection import claim_formula
    from sugar_lift_py_tests.ir import and_, atomic, str_const
    from sugar_lift_py_tests.proofir.nodes import (
        ConstructionSite,
        Provenance,
        Stated,
    )
    from sugar_lift_py_tests.proofir.nodes.universe_mint import UniverseMint

    facts = _class_namespace_facts(cls)
    if facts is None:
        return []
    symbol, mro, binds, class_object = facts
    statements = [
        atomic(
            "python:class_mro",
            [str_const(symbol), *(str_const(entry) for entry in mro)],
        )
    ] + [
        atomic(
            "python:class_binds",
            [
                str_const(symbol),
                str_const(name),
                str_const(kind),
                str_const(target),
            ],
        )
        for name, kind, target in binds
    ]
    if class_object is not None:
        statements.append(
            atomic("python:class_object", [str_const(symbol), class_object])
        )
    memento = statement_memento(cls, cls.name, file_rel)
    locus = ConstructionSite(
        path=file_rel, line=memento.span.start_line, column=memento.span.start_col
    )
    provenance = Provenance(
        node_class="UniverseMint",
        construction_site=locus,
        warrant=Stated(locus=locus),
    )
    formula = statements[0] if len(statements) == 1 else and_(statements)
    row = UniverseMint(
        name=f"{symbol}{CLASS_NAMESPACE_SUFFIX}",
        slot="inv",
        formula=claim_formula(
            formula, formals=(), provenance=provenance, role="inv"
        ),
        provenance=provenance,
        source_warrants=(memento,),
    )
    return [(memento.to_rpc(), row.to_body_universe())]


def _class_namespace_facts(cls):
    """``(symbol, mro, binds, class_object)`` for ``class_namespace_row``,
    or None when the class states no namespace row.  ``class_object`` is the
    class object's term where a ``classmethod`` is bound and the class
    statement constructs (``_class_object_term``), else None."""
    from sugar_source_tree.nodes import _TYPE_CREATION_NAMES, ClassDef

    symbol = cls.bridge_source_symbol()
    order = cls.method_resolution_order()
    if symbol is None or order is None:
        return None
    mro = []
    for entry in order:
        if isinstance(entry, ClassDef):
            entry_symbol = entry.bridge_source_symbol()
            if entry_symbol is None:
                return None
            mro.append(entry_symbol)
        else:
            mro.append(f"builtins.{entry}")
    stores = cls.unit.class_namespace_stores
    stored = stores(cls)
    writes, may_write, open_ = cls._creation_writes(stores)
    if open_ or "*" in stored:
        return None
    table = cls.unit.class_symtable(cls.name, cls.line_col_span().start_line)
    candidates = {
        item.get_name()
        for item in table.get_symbols()
        if item.is_local()
        and not item.is_declared_global()
        and not item.is_nonlocal()
    }
    candidates |= set(writes) | set(may_write) | (set(stored) - {"*"})
    binds = []
    for name in sorted(candidates):
        held = cls.namespace_binds(name)
        if held is False:
            continue
        if held is None:
            created = (
                name in _TYPE_CREATION_NAMES
                and name not in writes
                and name not in stored
                and cls._body_binding(name) is False
            )
            binds.append((name, _CREATION_KIND if created else "undecided", ""))
            continue
        kind, target = _namespace_value_kind(cls, name)
        if target is None:
            binds.append((name, "other", ""))
        else:
            binds.append((name, kind, target))
    class_object = None
    if any(kind == "classmethod" for _name, kind, _target in binds):
        class_object = _class_object_term(cls)
    return symbol, tuple(mro), tuple(binds), class_object


def _namespace_value_kind(cls, name: str) -> tuple:
    """``(kind, join symbol)`` of the value the class ``cls`` holds for
    ``name``, read off the class statement alone, when it is a function the
    dispatch binds (``_FUNCTION_KIND``, ``_FIELD_KIND``,
    ``_DESCRIPTOR_KINDS``); ``(None, None)`` for anything else.

    The value is the one its body bound (``namespace_value_is_body``) by a
    statement of the body itself (never one under an ``if``): a ``def`` that
    is neither a generator nor ``async``, undecorated or under exactly one
    builtin descriptor decorator (``ClassDef._method_descriptor_kind``, the
    kind the one method door binds by); or a single-target assignment of a
    lambda to the name, whose function is that lambda.  Its join symbol is
    the function's own (``bridge_source_symbol``), whose contract is the
    function's body: a descriptor decorator wraps the function without
    changing what a call of it runs.

    ``(_VALUE_KIND, "")`` for a single-target assignment (or an annotated
    one) of a literal or a display to the name, by a statement of the body
    itself: its value's class (``int``, ``str``, ``bytes``, ``float``,
    ``complex``, ``bool``, ``NoneType``, ``ellipsis``, ``tuple``, ``list``,
    ``dict``, ``set``) defines no ``__get__``, read off the syntax alone,
    whatever a display holds.  Any other value (a call such as
    ``property(f)`` or ``SomeDescriptor()``, a name) may be a descriptor:
    ``other``."""
    from sugar_source_tree.nodes import (
        AnnAssign,
        Assign,
        Constant,
        Dict,
        FunctionDef,
        Lambda,
        List,
        Name,
        Set,
        Tuple_,
    )

    if not cls.namespace_value_is_body(name):
        return None, None
    binder = cls.body_binder(name)
    if not any(item is binder for item in cls.body):
        return None, None
    if type(binder) is FunctionDef:
        if FunctionDef._owns_yield(binder.body):
            return None, None
        if not binder.decorators:
            kind = _FUNCTION_KIND
        else:
            kind = cls._method_descriptor_kind(binder)
            if kind not in _DESCRIPTOR_KINDS:
                return None, None
        return kind, binder.bridge_source_symbol()
    if (
        isinstance(binder, Assign)
        and len(binder.targets) == 1
        and isinstance(binder.targets[0], Name)
        and binder.targets[0].id == name
        and isinstance(binder.value, Lambda)
    ):
        return _FIELD_KIND, binder.value.bridge_source_symbol()
    if isinstance(binder, Assign):
        targets = binder.targets
    elif isinstance(binder, AnnAssign) and binder.value is not None:
        targets = (binder.target,)
    else:
        return None, None
    if (
        len(targets) == 1
        and isinstance(targets[0], Name)
        and targets[0].id == name
        and type(binder.value) in (Constant, Tuple_, List, Dict, Set)
    ):
        return _VALUE_KIND, ""
    return None, None


def _class_object_term(cls):
    """The term the class object of ``cls`` is spelled by
    (``class_definition_value.class_definition_term``), off the class
    statement's one construction (step 5; the cached sugar every reading of
    the class reads), or None when that construction states no class object.
    A refusal by name of the statement propagates: it is the class's refused
    member (``class_namespace_row``)."""
    from sugar_lift_py_tests.floor.class_definition_value import (
        class_definition_term,
    )

    sugar = cls.sugar()
    cid = getattr(sugar, "class_definition_cid", None)
    return None if cid is None else class_definition_term(cid)


def function_universe_outcome(fn):
    """Construct one function universe through its authenticated entrance.

    ``fn`` is a ``def``, ``async def`` or ``lambda``; its universe is its own
    contract (``contract_universe``), reduced with symbolic formals.  An
    ``__init__`` is one too (#7757 B2): its receiver is its first formal, and
    its contract states what it leaves in that object over
    ``python:after(out, "<self>")`` and its halts, as any method's does.  A
    class call reaches it through the dispatched ``__init__`` edge, joined at
    prove; no receiver is made here.

    A method whose own frame has a ``__class__`` cell (PEP 3135: it reads
    ``super`` or ``__class__``, ``_class_cell_statement``) runs with that cell
    holding the class its statement built, read through the cell's key in
    the state the module's one run left (``_class_cell_read``): the class
    ``type.__new__`` made, before any decorator ran, so a decorated class's
    methods read their cell as an undecorated one's do (PEP 3135); a
    zero-argument ``super()`` in it is
    then the dispatched call after that class (#7757 entry 6), in an
    ``__init__`` as in any method.

    A function's contract is stated over its inputs (#7757 step 5, #8292:
    one contract per function).  Each module global a call of it reads
    (``nodes._contract_inputs``: assignment, loop and branch-merge
    bindings, ``global:<name>``) is read as the free input: the keys its
    final binding reads through are bound to it at the entry
    (``call_site_sugar.bind_global_inputs``), before anything else binds
    them.  The row states the value the module's run left for each
    (``stated_global_values``), and prove's one binder binds the input to
    it where no call supplies one: pytest's call after import, the row's
    own claims among them.  A definition the body reads (a class, a
    decorated ``def``) is no input: the entry binds its key to the value
    the module body's run bound it to, demanded only where it is read
    (``call_site_sugar.with_module_final_globals``,
    ``module_end_contexts``), as it binds the function's own default
    keys.

    The outcome is always a set of arms.
    """
    from sugar_lift_py_tests.sugar.call_site_sugar import (
        bind_global_inputs,
        with_module_final_globals,
    )
    from sugar_source_tree.nodes import current_module_execution_site

    sugar = fn.contract_universe()
    site = current_module_execution_site()
    cell = _class_cell_statement(fn)
    if cell is None:
        entry = with_module_final_globals(
            bind_global_inputs(None, fn, owner="function_universe_outcome"),
            (fn,),
            site=site,
        )
        return sugar.desugar(entry)

    from sugar_lift_py_tests.context import ReduceContext
    from sugar_lift_py_tests.floor.class_definition_value import (
        ClassDefinitionValue,
    )
    from sugar_lift_py_tests.floor.named_expression_value import peel_walrus_binds
    from sugar_source_tree.panic import SugarNotWritten

    entry = with_module_final_globals(
        bind_global_inputs(
            ReduceContext.root(owner="function_universe_outcome"),
            fn,
            owner="function_universe_outcome",
        ),
        (fn,),
        site=site,
    )

    def in_its_cell(read):
        value = peel_walrus_binds(read)[1]
        if not isinstance(value, ClassDefinitionValue):
            raise SugarNotWritten(
                owner="function_universe_outcome",
                blame=fn.fragment,
                observed=(
                    f"the class statement's __class__ cell holds a "
                    f"{type(value).__name__}"
                ),
                requested="the class its __class__ cell holds (PEP 3135)",
                fix="seat the cell with the class its statement bound",
            )
        temporal = entry.temporal.bind_value(
            "__class__", value, blame=f"{value.class_name}.{fn.name}"
        )
        receiver = _first_positional_formal(fn)
        if receiver is not None:
            # A zero-argument ``super()`` binds the frame's first positional
            # formal, read by the name the ``def`` declares
            # (``builtin_semantic_callable.zero_argument_super_receiver``):
            # here the free formal of this contract, the very value a read of
            # it in the body is (``FormalRefSugar``), so the dispatched call
            # after the class is made on the receiver the contract states
            # over (``class:<self>``).
            name, formal = receiver
            temporal = temporal.bind_value(
                name, formal, blame=f"{value.class_name}.{fn.name}"
            )
        held = entry.with_temporal(temporal)
        return sugar.desugar(held)

    return _class_cell_read(cell, entry).and_then(in_its_cell)


def _class_cell_read(cls, entry):
    """The class the ``__class__`` cell of a method of ``cls`` holds, as a
    reader after import meets it (PEP 3135): the class the statement
    ``cls`` built, never what its decorators returned.  A class of the
    module body is read through its cell's key in the state the module's
    one run left (``DecoratorApplicationSugar.class_cell_read``: the key
    the statement bound the class it built under, beside its name's).  A
    class a class body holds is read as ``Outer.Inner`` is
    (``_class_statement_read``), refused by name there where that is not
    the class the statement built."""
    if _enclosing_class(cls) is not None:
        return _class_statement_read(cls, entry)
    return cls.statement_value_ref().sugar().class_cell_read(entry)


def _first_positional_formal(fn):
    """``(name, value)``: ``fn``'s first parameter where it is positional, and
    its value in ``fn``'s own contract -- the free formal
    (``SymbolicValue`` carrying its ``FormalParameterCoordinateV1``), exactly
    what ``FormalRefSugar`` reads it as.  None where the first parameter is
    not positional or there is none."""
    from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
    from sugar_lift_py_tests.ir import make_var

    if not fn.params or fn.params[0].param_kind not in (
        "positional_only",
        "positional_or_keyword",
    ):
        return None
    coordinate = fn.formal_coordinates()[0]
    return fn.params[0].name, SymbolicValue(
        make_var(coordinate.declared_name), formal_coordinate=coordinate
    )


def _class_cell_statement(fn):
    """The class statement whose class the ``__class__`` cell of ``fn``'s own
    frame holds (PEP 3135, ``SourceUnit.frame_class_cell``): a ``def`` in a
    class body whose code reads ``super`` or ``__class__``.  None where its
    frame has no cell, and where no reader after import reads that class (a
    class statement in a function body binds it in no module state,
    ``_class_statement_read``)."""
    from sugar_source_tree.nodes import (
        AsyncFunctionDef,
        ClassDef,
        FunctionDef,
        Lambda,
    )
    from sugar_source_tree.occurrence import SourceOccurrenceIdentityV1

    if not isinstance(fn, (FunctionDef, AsyncFunctionDef)):
        return None
    # A statement that runs in ``fn``'s own frame: never a nested scope's.
    inside = next(
        (
            statement
            for statement in fn.body
            if not isinstance(
                statement, (FunctionDef, AsyncFunctionDef, ClassDef, Lambda)
            )
        ),
        None,
    )
    if inside is None:
        return None
    decided, cell = fn.unit.frame_class_cell(inside.line_col_span())
    if not decided or cell is None:
        return None
    module_classes = {
        SourceOccurrenceIdentityV1.of(statement)
        for statement in fn.unit.typed_module.body
        if isinstance(statement, ClassDef)
    }
    if (
        SourceOccurrenceIdentityV1.of(cell) in module_classes
        or _enclosing_class(cell) is not None
    ):
        return cell
    return None


def class_universe_outcome(cls):
    """A class's constructor contract (#7757 step 6): the universe of
    ``return Cls(<formals>)``, named by the class's join symbol
    (``ClassDef.bridge_source_symbol``, ``python:<module>.<Class>``), which a
    call of the class is joined to at prove as a call of a ``def`` is.

    Its formals are the constructor frame's (``ClassDef.
    source_visible_constructor_frame``: the formals after the first of the
    ``def`` that states the call's signature), each standing free as a
    ``def``'s does, then its inputs (``ClassDef.contract_inputs``: the cells,
    defaults and module globals of that ``def``).  The body is the one
    constructor every class call ran (``ClassConstructorBodySugar``),
    entered on the class the statement bound, read through the statement's
    key in the state the module's one run left, as an ``__init__``'s own
    universe reads it (``function_universe_outcome``); the instance it makes
    is allocated by this construction (``call_site``: the class statement).
    A source ``__init__`` is never applied here: the construction makes the
    fresh instance and dispatches ``type(obj).__init__(obj, ...)`` on it, an
    edge joined at prove to the ``__init__``'s own contract (#7757 B3,
    ``ClassConstructorBodySugar._dispatched_initializer``), whose halts are
    this call's halts.  Nor is a source ``__new__``: the construction
    dispatches it as a static method on the class, then ``type(obj).
    __init__`` on what it returned, both edges joined at prove (#7757 A4,
    ``ClassConstructorBodySugar._returned_by_new``).  Each completed arm
    returns the instance: its class and its state as the ``__init__`` call
    left it (``InitializedInstanceValue``), or, where the construction runs
    here (a dataclass's generated stores, which no source ``def`` states),
    the fields it set (``ConstructedInstanceValue``), never its identity;
    each halt of the constructor is a halted arm (its panic locus).

    The module globals the signature's ``def`` reads are free inputs, bound
    at the entry (``bind_global_inputs``) before the definition keys and
    defaults (``with_module_final_globals``).

    A class whose constructor no lookup reads (``ClassDef.
    constructor_is_read``) states its call as the one unanswered call over
    ``(*args, **kwargs)``, undecided and owed, its halt kept
    (``_unread_constructor_outcome``): never a refusal of the class."""
    from dataclasses import replace

    from sugar_lift_py_tests.context import ReduceContext
    from sugar_lift_py_tests.floor.call_site_value import _ctx_with_curried_args
    from sugar_lift_py_tests.floor.class_definition_value import (
        ClassDefinitionValue,
    )
    from sugar_lift_py_tests.floor.named_expression_value import peel_walrus_binds
    from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
    from sugar_lift_py_tests.ir import make_var
    from sugar_lift_py_tests.sugar.call_site_sugar import (
        bind_global_inputs,
        with_module_final_globals,
    )
    from sugar_lift_py_tests.sugar.class_constructor_body_sugar import (
        ConstructedInstanceSugar,
    )
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        FunctionUniverseSugar,
    )
    from sugar_lift_py_tests.sugar.return_sugar import ReturnSugar
    from sugar_source_tree.nodes import current_module_execution_site
    from sugar_source_tree.panic import SugarNotWritten

    if not cls.constructor_is_read():
        # No lookup decides what a call of the class runs: the contract
        # states the call as the one unanswered call, undecided and owed,
        # never a refusal of the class (``_unread_constructor_outcome``).
        return _unread_constructor_outcome(cls)
    frame = cls.source_visible_constructor_frame()
    constructor = cls.constructor_definition()
    readers = () if constructor is None else (constructor,)
    entry = ReduceContext.root(owner="class_universe_outcome")
    if constructor is not None:
        entry = bind_global_inputs(entry, constructor, owner="class_universe_outcome")
    entry = with_module_final_globals(
        entry, readers, site=current_module_execution_site()
    )
    parameters = tuple(frame.parameters)
    # Each formal as its own proof reads it: free, carrying the formal
    # coordinate of the signature's ``def`` where that ``def`` states it, as
    # a ``def``'s ``FormalRefSugar`` does.
    declared = _class_contract_formal_coordinates(cls, frame)
    formals = tuple(
        SymbolicValue(
            make_var(name),
            formal_coordinate=coordinate
            if hasattr(coordinate, "declared_name")
            else None,
        )
        for name, coordinate in zip(parameters, declared, strict=True)
    )
    entered = _ctx_with_curried_args(
        entry,
        parameters,
        formals,
        tuple(coordinate.cid for coordinate in frame.formal_coordinates),
    )
    site = cls.fragment

    def on_its_class(read):
        value = peel_walrus_binds(read)[1]
        if not isinstance(value, ClassDefinitionValue):
            raise SugarNotWritten(
                owner="class_universe_outcome",
                blame=site,
                observed=(
                    f"the class statement's key holds a {type(value).__name__}"
                ),
                requested="the class the statement built, whose call this contract states",
                fix="state the constructor contract on the class its statement bound",
            )
        body = replace(frame.body, class_value=value, call_site=frame.body.site)
        universe = FunctionUniverseSugar(
            name=cls.contract_name(),
            formals=parameters,
            statements=(
                ReturnSugar(
                    value=ConstructedInstanceSugar(body, site=site), site=site
                ),
            ),
            site=site,
            bridge_source_symbol=cls.bridge_source_symbol(),
            formal_coordinates=declared,
            inputs=cls.contract_inputs(),
        )
        return universe.desugar(entered)

    return _class_statement_read(cls, entry).and_then(on_its_class)


# The formals of a constructor contract no lookup reads the signature of
# (``_unread_constructor_signature``): ``(*args, **kwargs)``.
_UNREAD_CONSTRUCTOR_FORMALS = ("args", "kwargs")


def _unread_constructor_signature(cls) -> tuple:
    """``(parameters, coordinates)`` of the constructor contract of a class
    whose constructor is not read (``ClassDef.constructor_is_read``): no
    lookup decides which ``__new__`` and ``__init__`` a call runs, so no
    signature is read, and the contract takes every actual a call may pass,
    ``(*args, **kwargs)``.  Each formal's coordinate is minted on the class
    statement, as the inherited-exception frame mints its ``args``
    (``ClassDef.source_visible_constructor_frame``)."""
    from sugar_source_tree.binding_provenance import BindingCoordinateV1

    owner_cid = cls.fragment.seal().cid
    return _UNREAD_CONSTRUCTOR_FORMALS, tuple(
        BindingCoordinateV1.mint(
            owner_cid, cls.fragment, ("unread-constructor-formal", index)
        )
        for index in range(len(_UNREAD_CONSTRUCTOR_FORMALS))
    )


def _class_contract_signature(cls) -> tuple:
    """``(parameters, coordinates)``: the formals a class's constructor
    contract states (``class_universe_outcome``, ``class_contract_rows``).
    Where the constructor is read, the constructor frame's
    (``ClassDef.source_visible_constructor_frame``,
    ``_class_contract_formal_coordinates``); else ``(*args, **kwargs)``
    (``_unread_constructor_signature``)."""
    if not cls.constructor_is_read():
        return _unread_constructor_signature(cls)
    frame = cls.source_visible_constructor_frame()
    return tuple(frame.parameters), _class_contract_formal_coordinates(cls, frame)


def _unread_constructor_outcome(cls):
    """The constructor contract of a class whose constructor is not read
    (``ClassDef.constructor_is_read``: a base, a metaclass or a decorator
    the one class-namespace lookup does not decide; 173 pandas classes on
    the ``d5dcbab5c`` lane run): the universe of ``return Cls(*args,
    **kwargs)``, ``Cls`` read as every reader after import reads the class
    statement (``_class_statement_read``), the call through the one
    spread-call door (``UnreadConstructorCallSugar``).  Nothing decides what
    it runs, so its one completed face is the call's own result and its halt
    the call's undetermined raise, both owed (``UnknownCalleeCallV1``): the
    class's call carried undecided, its halt kept, instead of the whole class
    refused.  It is the call a caller of the class makes
    (``ClassDefinitionValue.callable_application_with``); no ``__init__`` or
    ``__new__`` body is read, so the contract takes no input."""
    from sugar_lift_py_tests.context import ReduceContext
    from sugar_lift_py_tests.floor.call_site_value import _ctx_with_curried_args
    from sugar_lift_py_tests.floor.named_expression_value import peel_walrus_binds
    from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
    from sugar_lift_py_tests.ir import make_var
    from sugar_lift_py_tests.sugar.call_site_sugar import with_module_final_globals
    from sugar_lift_py_tests.sugar.class_constructor_body_sugar import (
        UnreadConstructorCallSugar,
    )
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        FunctionUniverseSugar,
    )
    from sugar_lift_py_tests.sugar.return_sugar import ReturnSugar
    from sugar_source_tree.nodes import current_module_execution_site

    parameters, declared = _unread_constructor_signature(cls)
    entry = with_module_final_globals(
        ReduceContext.root(owner="class_universe_outcome"),
        (),
        site=current_module_execution_site(),
    )
    formals = tuple(SymbolicValue(make_var(name)) for name in parameters)
    entered = _ctx_with_curried_args(
        entry,
        parameters,
        formals,
        tuple(coordinate.cid for coordinate in declared),
    )
    site = cls.fragment

    def on_its_class(read):
        universe = FunctionUniverseSugar(
            name=cls.contract_name(),
            formals=parameters,
            statements=(
                ReturnSugar(
                    value=UnreadConstructorCallSugar(
                        cls.name, peel_walrus_binds(read)[1], formals, site=site
                    ),
                    site=site,
                ),
            ),
            site=site,
            bridge_source_symbol=cls.bridge_source_symbol(),
            formal_coordinates=declared,
        )
        return universe.desugar(entered)

    return _class_statement_read(cls, entry).and_then(on_its_class)


def _enclosing_class(cls):
    """The class statement whose body holds ``cls``, or None for a class of
    the module body: the nesting ``classes_with_contracts`` walks (a class a
    class body holds, in turn)."""
    from sugar_source_tree.nodes import ClassDef
    from sugar_source_tree.occurrence import SourceOccurrenceIdentityV1

    identity = SourceOccurrenceIdentityV1.of(cls)
    pending = [
        statement
        for statement in cls.unit.typed_module.body
        if isinstance(statement, ClassDef)
    ]
    while pending:
        outer = pending.pop()
        for statement in outer.body:
            if not isinstance(statement, ClassDef):
                continue
            if SourceOccurrenceIdentityV1.of(statement) == identity:
                return outer
            pending.append(statement)
    return None


def _class_statement_read(cls, entry):
    """The class the statement ``cls`` bound, as a reader after import meets
    it.  A class of the module body is read through its statement's key in
    the state the module's one run left (``ClassDef.statement_value_ref``).
    A class a class body holds is bound in that body's namespace, never in
    the module's state: it is read as ``Outer.Inner`` is, the one
    class-namespace lookup (``ClassDefinitionValue.namespace_member``) on the
    class its enclosing statement bound, read the same way in turn.  A lookup
    that does not give the class ``cls`` built is refused by name."""
    from sugar_lift_py_tests.floor.class_definition_value import (
        ClassDefinitionValue,
    )
    from sugar_lift_py_tests.floor.named_expression_value import peel_walrus_binds
    from sugar_lift_py_tests.outcome import ExitSet
    from sugar_source_tree.occurrence import SourceOccurrenceIdentityV1
    from sugar_source_tree.panic import SugarNotWritten

    outer = _enclosing_class(cls)
    if outer is None:
        return cls.statement_value_ref().sugar().desugar(entry)

    def member_of(read):
        holder = peel_walrus_binds(read)[1]
        found = (
            holder.namespace_member(cls.name)
            if isinstance(holder, ClassDefinitionValue)
            else (False, None, None, None, None)
        )
        decided, _found, _holder, method, value = found
        if (
            decided
            and method is None
            and isinstance(value, ClassDefinitionValue)
            and value.class_definition is not None
            and SourceOccurrenceIdentityV1.of(value.class_definition)
            == SourceOccurrenceIdentityV1.of(cls)
        ):
            return ExitSet.completed(value)
        raise SugarNotWritten(
            owner="class_universe_outcome",
            blame=cls.fragment,
            observed=(
                f"{outer.name}.{cls.name} is not the class the nested "
                f"statement {cls.name} built"
            ),
            requested="the class the enclosing class's namespace holds under its name",
            fix="state the nested class's contract on the class its statement bound",
        )

    return _class_statement_read(outer, entry).and_then(member_of)


def _class_contract_formal_coordinates(cls, frame) -> tuple:
    """The coordinates of a class contract's formals (the constructor
    frame's): the formal coordinates of the ``def`` that states the call's
    signature after its first (``ClassDef.constructor_definition``), where
    they are the frame's formals by name; else the frame's own."""
    parameters = tuple(frame.parameters)
    constructor = cls.constructor_definition()
    declared = (
        () if constructor is None else tuple(constructor.formal_coordinates())[1:]
    )
    if tuple(getattr(item, "declared_name", None) for item in declared) == parameters:
        return declared
    return tuple(frame.formal_coordinates)


def reduction_rows(outcome, *, owner, blame, def_memento, definition):
    """THE projection from one reduction to its wire rows (#7766).

    A function body's one reduction (``function_contract_rows``) becomes rows
    here and nowhere else; enumerate never applies a body at a call itself
    (#7757 item 12: a contract is applied at prove). ``outcome`` is an
    ``ExitSet`` of completed and halted arms (one completed arm under guard
    true is the one-arm case); ``owner`` states the name, formals and symbol
    when no arm completed. ``None`` when the outcome is not a set of arms.

    ``definition`` is the function the reduction is of. When no arm of the
    reduction completed, each ``assert`` of its body that no arm reached
    (``unreached_assertion_sites``) states its row from the halted arms'
    guards (``exit_arms_payload_rows``), so a certain halt is decided at
    prove.
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
        halted = tuple(exit_ for exit_ in outcome.exits if isinstance(exit_, Halted))
        halted_sites = halted_assertion_sites(halted, definition)
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
    # The formals are the contract's whatever arms the reduction leaves: a
    # completed arm's universe states its parameters and its inputs
    # (``FunctionUniverseSugar.desugar``), and with no completed arm the
    # owner states the same tuple (``contract_formals``).  Its parameters
    # alone would leave a halt guard over an input (a ``global:`` read, a
    # captured cell) outside the row's scope, and the whole function refused.
    if arms:
        stated = arms[0][1]
        formals = tuple(stated.formals)
        formal_coordinates = tuple(stated.formal_coordinates)
    else:
        stated = owner
        formals = tuple(owner.contract_formals())
        formal_coordinates = tuple(owner.contract_formal_coordinates())
    halt_loci = tuple(
        halt_locus(
            arm,
            formals=formals,
            def_memento=def_memento,
            blame=blame,
        )
        for arm in halted
    )
    unreached = ()
    if halted and not arms:
        unreached = unreached_assertion_sites(definition, halted)
    return exit_arms_payload_rows(
        name=stated.name,
        formals=formals,
        bridge_source_symbol=stated.bridge_source_symbol,
        formal_coordinates=formal_coordinates,
        arms=arms,
        halted_assertion_sites=halted_sites,
        halt_loci=halt_loci,
        def_memento=def_memento,
        unreached_assertion_sites=unreached,
        halted_guards=tuple(arm.guard for arm in halted),
        leaves=parameters_left_unchanged(definition, formals),
    )


def parameters_left_unchanged(definition, formals) -> tuple:
    """The formals among ``formals`` whose object a call of ``definition``
    never changes and whose binding it never rebinds, read off its own body
    (``nodes._names_a_call_may_change``, #7757 step 7): each parameter it
    never changes, and each captured cell or module global input
    (``cell:<n>``, ``global:<n>``) it never changes where it runs no code
    this body does not see (``runs_unseen_code``: such code may change a
    cell or global).  The contract states each (``python:leaves``,
    ``exit_arms_payload_rows``): the one fact prove asks of the contract it
    joins to a call whose operands may share an object, a dispatched call
    and a same-file definition's alike (``consistency::shared_operands_
    left_unchanged``, step 9; the owner's ruling of 2026-11-15: what the
    caller needs from the callee is stated by the callee's contract).  None
    for a contract that is no function's (a class's: ``definition`` None),
    a generator or ``async def``, or anything the body is not read for
    (``EVERY_NAME``); no other contract input (``class:``, ``field:``,
    ``default:``) is stated."""
    from sugar_lift_py_tests.contract_input import CELL_INPUT, GLOBAL_INPUT
    from sugar_source_tree.nodes import EVERY_NAME, _names_a_call_may_change

    if definition is None:
        return ()
    changed = _names_a_call_may_change(definition)
    if changed is EVERY_NAME:
        return ()
    names, runs_unseen_code = changed
    left = []
    for formal in formals:
        kind, colon, name = formal.partition(":")
        if not colon:
            if formal not in names:
                left.append(formal)
        elif (
            kind in (CELL_INPUT, GLOBAL_INPUT)
            and not runs_unseen_code
            and name not in names
        ):
            left.append(formal)
    return tuple(left)


def function_contract_rows(fn, file_rel: str):
    """A function's contract DTO rows, read off EVERY arm of its one reduction.

    ``fn`` is a ``def``, ``async def`` or ``lambda``: a lambda is a function
    and states its contract the same way (``Lambda.contract_universe``: the
    universe of ``return <body>`` over its formals).
    `fn.contract_universe()` constructs the FunctionUniverseSugar; desugar reduces the body
    to an ``ExitSet`` of completed and halted arms. ``exit_arms_payload_rows``
    projects all of them: the post over every completed arm, one panic locus
    per halted arm (``halt_locus``), and one row per assertion site (see
    there). One completed arm under guard true is the one-arm case.

    A halt is an arm: a body that only
    halts states its halted arms like any other set. Every row is read off
    this one reduction; no other lifter adds to it (#7767). A SugarNotWritten
    from an unported body statement propagates (the whole function is a
    frontier gap).
    """
    def_memento = function_def_memento(fn, file_rel)
    rows = reduction_rows(
        owner_reduction(fn).outcome,
        owner=fn.contract_universe(),
        blame=fn.fragment,
        def_memento=def_memento,
        definition=fn,
    )
    # The value the module's run left for each module global input the
    # contract states its post and claims over (#7757 step 5): prove's one
    # binder binds an input no call supplies to it, the row's own claims
    # (pytest's call after import) among them.
    from sugar_lift_py_tests.sugar.call_site_sugar import stated_global_values

    stated = stated_global_values(fn)
    if rows is not None and stated:
        import dataclasses

        rows = [dataclasses.replace(row, input_values=stated) for row in rows]
    return def_memento, rows


def classes_with_contracts(sf: SourceFile) -> tuple:
    """Every class statement whose constructor contract this file states
    (``class_contract_rows``): each class of the module body and, in turn,
    each class a class body holds, in source order.  A class a function body
    holds is made by each run of that body; no module run binds it, so its
    calls stay owed by its join symbol."""
    from sugar_source_tree.nodes import ClassDef

    found = []
    pending = list(reversed(tuple(sf.unit.typed_module.body)))
    while pending:
        statement = pending.pop()
        if isinstance(statement, ClassDef):
            found.append(statement)
            pending.extend(reversed(tuple(statement.body)))
    return tuple(found)


def class_memento(cls, file_rel: str, parameters: tuple = ()):
    """The class's own SourceMemento: its statement under its name
    (``statement_memento``), with the formals a call of it binds."""
    import dataclasses

    return dataclasses.replace(
        statement_memento(cls, cls.name, file_rel), param_names=list(parameters)
    )


def refused_class_row(cls, file_rel: str, refusal) -> UndecidedRow:
    """The ``undecided`` row for a class whose constructor contract the
    lifter refuses by name, cited by its join symbol, by the rule a refused
    function follows (``refused_function_row``)."""
    return _refused_row(
        class_memento(cls, file_rel), cls.bridge_source_symbol(), refusal, file_rel
    )


def class_contract_rows(cls, file_rel: str):
    """A class's constructor contract rows (#7757 step 6), read off every arm
    of its one reduction (``class_universe_outcome``) by the one row path a
    function's are (``reduction_rows``): the post over each completed arm
    (the fields the construction left), one panic locus per halted arm.
    Each module global input the signature's ``def`` reads states the value
    the module's run left (``stated_global_values``), as a function's row
    does."""
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        FunctionUniverseSugar,
    )

    parameters, coordinates = _class_contract_signature(cls)
    memento = class_memento(cls, file_rel, parameters)
    # What the row states its name, formals and symbol by when no arm of the
    # construction completes (``reduction_rows``' ``owner``).
    stated_by = FunctionUniverseSugar(
        name=cls.contract_name(),
        formals=parameters,
        statements=(),
        site=cls.fragment,
        bridge_source_symbol=cls.bridge_source_symbol(),
        formal_coordinates=coordinates,
    )
    # No ``definition``: the class statement's own body runs where the class
    # statement stands, never at a call of the class, so none of its
    # ``assert`` statements is this contract's; nor is one of its
    # ``__init__``'s, whose failure is a halt of the call (a panic locus),
    # never a claim of the class (``halted_assertion_sites``).
    rows = reduction_rows(
        owner_reduction(cls).outcome,
        owner=stated_by,
        blame=cls.fragment,
        def_memento=memento,
        definition=None,
    )
    # A contract whose constructor is not read reads no ``def``'s body, so
    # it takes no input and states no global value
    # (``_unread_constructor_outcome``).
    constructor = (
        cls.constructor_definition() if cls.constructor_is_read() else None
    )
    from sugar_lift_py_tests.sugar.call_site_sugar import stated_global_values

    stated = () if constructor is None else stated_global_values(constructor)
    if rows is not None and stated:
        import dataclasses

        rows = [dataclasses.replace(row, input_values=stated) for row in rows]
    return memento, rows


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
