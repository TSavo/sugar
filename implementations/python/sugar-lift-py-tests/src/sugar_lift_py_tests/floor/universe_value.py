from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.ir import Formula

from .floor_value import FloorValue


@dataclass(frozen=True)
class UniverseValue(FloorValue):
    """A function body lowered to its universe: name, formals, record. The
    slots are PROJECTIONS of the record -- each entry answers for itself
    (inv_contribution / post_contribution), the universe just concatenates.
    invs are the stated facts; post is `out == <exit term>`.

    ``after`` -- ``((formal, value), ...)`` -- is what this arm left in each
    closure cell the body rebinds (``FunctionUniverseSugar.cells_after``):
    the post states it as ``python:after(out, <formal>) == <value>``, the one
    term a caller reads the cell by after the call (#7757 step 7), where the
    value is one the contract's own inputs determine
    (``stated_by_its_inputs``); otherwise it states nothing and the caller's
    cell stays undecided.

    ``fields`` -- ``((param, attr, value), ...)`` -- is what this arm left in
    each field the body stores last on a parameter where nothing after the
    store may change it (``FunctionUniverseSugar.fields_after``,
    ``FunctionDef._fields_where_the_body_ends``), and ``plain_stores`` --
    ``((param, attr), ...)`` -- those stores and every field store that may
    run after one.  The post states each field as the plain ``__dict__``
    entry a read of it afterwards returns, ``attr:<attr>(python:after(out,
    "<param>")) == <value>`` and that such a read completes, only under the
    guard that every one of those stores is the plain store:
    ``python:plain_store(class:<param>, "<attr>")`` over the class input the
    caller binds, which prove decides on the class's namespace row (#7757
    step 7).  Where the guard is not decided, nothing is concluded and the
    caller's read stays undecided.

    ``fields_guard`` is the guard under which this arm ran past every
    earlier guarded ``return`` its record still carries (the block's
    fall-through guard), or None where none is pending: the fields hold
    only there, beside the plain-store guard
    (``FunctionUniverseSugar._fields_guard``)."""

    name: str
    formals: tuple[str, ...]
    record: object  # the body's BlockValue
    bridge_source_symbol: str | None = None
    formal_coordinates: tuple = ()
    after: tuple = ()
    fields: tuple = ()
    plain_stores: tuple = ()
    fields_guard: object = None
    #: ``(receiver, names, stores, reads)``: what an ``__init__``'s receiver
    #: may hold where the call leaves it (``nodes._receiver_holds``), or
    #: None (``receiver_holds_facts``).
    receiver_holds: object = None
    #: The method calls this arm made after a stated field's store whose
    #: results a field store keeps (``FunctionUniverseSugar._leaving_calls``):
    #: the fields hold only where each leaves every object it is handed
    #: (``field_facts``); None where one was not read (nothing is stated).
    leaving_calls: object = ()
    #: A generator function's or an ``async def``'s universe
    #: (``FunctionUniverseSugar.suspends``): its call runs none of the body
    #: and returns the generator or the coroutine, so the body's ``return``
    #: (``StopIteration``'s value, an ``await``'s result) and its
    #: fall-through are not the call's result, and ``post`` states nothing of
    #: ``out``.
    suspends: bool = False

    def guarded(self, formula):
        """Ride under a branch by guarding every body record entry.

        Nested ``def`` under ``if`` places this universe as a block entry; the
        if/exit-set router then calls ``entry.guarded(guard)``. Each statement
        already owns its own guarded arm (InvValue → implication, ReturnValue →
        GuardedReturn, …); reassemble the same universe shape over the guarded
        entries. Full-dump: 26 of 32 ``guarded`` panics were UniverseValue.
        """
        from dataclasses import replace

        from sugar_lift_py_tests.floor.block_value import BlockValue

        guarded_entries = tuple(
            entry.guarded(formula) for entry in self.record.statements
        )
        if isinstance(self.record, BlockValue):
            record = replace(self.record, statements=guarded_entries)
        else:
            record = BlockValue(guarded_entries)
        return replace(self, record=record)

    def invs(self) -> tuple[Formula, ...]:
        return tuple(
            formula
            for entry in self.record.statements
            for formula in entry.inv_contribution()
        )

    def post(self) -> Formula:
        from sugar_lift_py_tests.ir import and_

        if self.suspends:
            # A generator's call returns the generator object, a coroutine
            # function's the coroutine, which nothing here decides; what the
            # body returns is ``StopIteration``'s value, read by its
            # consumer's ``next`` or ``await`` (the one undecided read), never
            # the call's ``out``.  The empty conjunction: no claim
            # about the call's result.
            return and_([])
        exits = tuple(
            formula
            for entry in self.record.statements
            for formula in entry.post_contribution()
        )
        after = self.after_facts()
        if not exits:
            # A universe is built only on a completed arm, and a completed
            # record holds no halt (#7826): a raise-only body has no completed
            # arm, so no universe ever answers for it.
            from sugar_lift_py_tests.floor.none_value import NoneValue
            from sugar_lift_py_tests.ir import eq, make_var

            returned = eq(
                make_var("out"),
                NoneValue().to_term(owner="UniverseValue.post"),
            )
            return and_([returned, *after]) if after else returned
        post = exits[0] if len(exits) == 1 else None
        if post is None:
            post = and_(list(exits))
        if not after:
            return post
        return and_([post, *after])

    def after_facts(self) -> tuple:
        """``python:after(out, <formal>) == <value>`` for each cell this arm
        left (``after``) whose value the contract's inputs determine
        (``stated_by_its_inputs``): what a caller reads the cell by after
        the call, joined at prove with ``out`` the caller's call result
        (#7757 step 7)."""
        from sugar_lift_py_tests.ir import eq, make_var
        from sugar_lift_py_tests.source_call_resolution import object_after_call

        facts = []
        for formal, value in self.after:
            term = value.to_term(owner="UniverseValue.after")
            if stated_by_its_inputs(term, self.formals):
                facts.append(eq(object_after_call(make_var("out"), formal), term))
        stored = self.field_facts()
        if stored is not None:
            facts.append(stored)
        facts.extend(self.receiver_holds_facts())
        return tuple(facts)

    def receiver_holds_facts(self) -> tuple:
        """What an ``__init__``'s contract states its receiver's ``__dict__``
        may hold where the call leaves it (``receiver_holds``,
        ``nodes._receiver_holds``, #7757 B2), over ``o = python:after(out,
        "<receiver>")``:

        - decided: ``python:holds_decided(o)`` and one ``python:may_hold(o,
          "<name>")`` per field it may store, under the guard that each of
          its field stores is the plain ``__dict__`` store and each field
          read the plain ``__dict__`` read (``python:plain_store`` /
          ``python:plain_read`` over ``class:<receiver>``), with
          ``python:class_undecided(o)`` under the complement;
        - not decided: ``python:class_undecided(o)``.

        The names are those it may add to what the ``__dict__`` held at
        entry: on the fresh instance a class call makes, every name it
        holds.  Prove composes them with the class row's ``python:type_is``
        into the instance a caller's ``python:constructed(<class>)`` is bound
        to (``consistency::initialized_instance``).  Nothing for any other
        function."""
        if self.receiver_holds is None:
            return ()
        from sugar_lift_py_tests.contract_input import CLASS_INPUT, input_formal
        from sugar_lift_py_tests.ir import (
            and_,
            atomic,
            implies,
            make_var,
            not_,
            str_const,
        )
        from sugar_lift_py_tests.receiver_dispatch import (
            CLASS_UNDECIDED,
            HOLDS_DECIDED,
            MAY_HOLD,
            PLAIN_READ,
            plain_store_atom,
        )
        from sugar_lift_py_tests.source_call_resolution import object_after_call

        receiver, names, stores, reads = self.receiver_holds
        obj = object_after_call(make_var("out"), receiver)
        undecided = atomic(CLASS_UNDECIDED, [obj])
        if names is None:
            return (undecided,)
        held = [atomic(HOLDS_DECIDED, [obj])]
        held.extend(atomic(MAY_HOLD, [obj, str_const(name)]) for name in sorted(names))
        holds = held[0] if len(held) == 1 else and_(held)
        class_term = make_var(input_formal(CLASS_INPUT, receiver))
        guards = [plain_store_atom(class_term, name) for name in stores]
        guards.extend(atomic(PLAIN_READ, [class_term, str_const(name)]) for name in reads)
        if not guards:
            return (holds,)
        guard = guards[0] if len(guards) == 1 else and_(guards)
        return (implies(guard, holds), implies(not_(guard), undecided))

    def field_facts(self):
        """``and(plain_store(class:<p>, "<a>")...) -> and(<field facts>)``:
        for each field this arm left (``fields``) whose value the contract's
        inputs determine (``stated_by_its_inputs``) and that names no call's
        result (``_names_a_call_result``), the field of the parameter's
        object after the call and that a read of it completes
        (``stored_field_facts``), under the guard that every store that may
        run after it is the plain ``__dict__`` store (``plain_stores``,
        ``receiver_dispatch.plain_store_atom``, #7757 step 7).  None where no
        field is stated."""
        from sugar_lift_py_tests.contract_input import CLASS_INPUT, input_formal
        from sugar_lift_py_tests.ir import and_, implies, make_var
        from sugar_lift_py_tests.receiver_dispatch import plain_store_atom
        from sugar_lift_py_tests.source_call_resolution import object_after_call
        from sugar_lift_py_tests.sugar.class_constructor_body_sugar import (
            stored_field_facts,
        )

        stated = []
        for param, attr, value in self.fields:
            term = value.to_term(owner="UniverseValue.fields")
            if not stated_by_its_inputs(term, self.formals) or _names_a_call_result(
                term
            ):
                continue
            stored = object_after_call(make_var("out"), param)
            stated.extend(stored_field_facts(stored, attr, term))
        guards = [
            plain_store_atom(make_var(input_formal(CLASS_INPUT, param)), attr)
            for param, attr in self.plain_stores
        ]
        if not stated or not guards:
            return None
        leaving = call_leaves_atoms(self.leaving_calls)
        if leaving is None:
            return None
        guards.extend(leaving)
        if self.fields_guard is not None:
            # An earlier guarded ``return`` this record still carries ended
            # the frame before the store where its guard fails.
            guards.append(self.fields_guard)
        guard = guards[0] if len(guards) == 1 else and_(guards)
        return implies(guard, and_(stated))

    def call_edges(self):
        # The record entries project their own call edges (CallSiteValue direct,
        # InvValue via carried operand_callsites, GuardedFaces via children).
        return tuple(
            edge
            for entry in self.record.statements
            for edge in entry.edge_contribution(self.name)
        )

    def mints(self):
        # The record entries mint their own rows; the universe mints its post
        # (Derived: the lift composed it from the exits).
        from sugar_lift_py_tests.floor.universe_mint_projection import claim_formula
        from sugar_lift_py_tests.proofir.nodes import (
            ConstructionSite,
            Derived,
            Provenance,
        )
        from sugar_lift_py_tests.proofir.nodes.universe_mint import UniverseMint

        rows = tuple(
            row
            for entry in self.record.statements
            for row in entry.mint_contribution(self.name, self.formals)
        )
        post_provenance = Provenance(
            node_class="UniverseMint",
            construction_site=ConstructionSite(path=self.name, line=0, column=0),
            warrant=Derived(floor_chain=("UniverseValue.post",)),
        )
        return (
            *rows,
            UniverseMint(
                name=self.name,
                slot="post",
                formula=claim_formula(
                    self.post(),
                    formals=self.formals,
                    provenance=post_provenance,
                    role="post",
                ),
                provenance=post_provenance,
                formals=self.formals,
            ),
        )


# Terms that name a state no input determines: an object after an operation
# nothing decided, keyed on that operation's occurrence alone
# (``builtin_container_call_sugar._unknown_after``, ``_opaque_pair``), and
# what a comprehension
# over an iterable whose members are not in hand made, its kind over its
# occurrence and evaluation (``ComprehensionSugar._own_coordinate``), with the
# last write a walrus in it carries out (``ComprehensionSugar._symbolic_writes``).
# A contract instantiated at two calls would state one such term for both, so
# it never states one as an ``after`` or field value.
UNDETERMINED_STATES = frozenset(
    {
        "python:receiver_after_call",
        "python:builtin_method",
        "py.listcomp",
        "py.setcomp",
        "py.dictcomp",
        "py.generatorexp",
        "python:comprehension.last_write",
    }
)

# What else a contract never states as a value (``stated_by_its_inputs``):
# a branch's slot (``BranchResultCoordinate``, which arm of one ``if`` ran,
# keyed on its slot alone), and, by prefix, an object's identity and a live
# loop's own publication (``python:loop.post_binding``, ``python:loop.item``,
# ``python:loop.recurrence``, ...), keyed on the loop's occurrence.  A loop's
# rebinding is stated only where the loop's result is decided (an unrolled
# loop's keys), never over a live loop's (#7757 step 7).
_UNSTATED_SLOTS = frozenset({"python:branch_result"})
_UNSTATED_PREFIXES = ("py.object", "python:loop.", "python:loop-")

#: ``python:leaves("<parameter>")``: the function never changes the object
#: its parameter binds nor rebinds it (``tree_enumerate.
#: parameters_left_unchanged``), stated beside its post and read by prove's
#: dispatch (``consistency::PYTHON_LEAVES``).
LEAVES = "python:leaves"

#: ``python:call_leaves(<call>, "<key>")``: the dispatched call ``<call>``
#: leaves the object its operand keyed ``<key>`` binds (its receiver ``"0"``,
#: each positional actual by its position) unchanged -- decided at prove
#: where the call resolves to a method whose contract states
#: ``python:leaves`` of the parameter that operand binds
#: (``consistency::call_leaves_holds``), open anywhere else.
CALL_LEAVES = "python:call_leaves"


def call_leaves_atoms(calls):
    """``python:call_leaves(<call>, "<key>")`` for each operand of each
    dispatched method call in ``calls`` (``UniverseValue.leaving_calls``):
    the guard a field stated across such a call holds under (#7757).  None
    where ``calls`` is None or one of them is no dispatched call (no guard
    could name it, so nothing is stated)."""
    if calls is None:
        return None
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.floor.named_expression_value import peel_walrus_binds
    from sugar_lift_py_tests.ir import atomic, str_const

    atoms = []
    for value in calls:
        call = peel_walrus_binds(value)[1]
        symbol = getattr(call, "authenticated_target_symbol", None) or ""
        if not isinstance(call, CallSiteValue) or not symbol.startswith(
            "python:dispatch:"
        ):
            return None
        if call.keyword_names or symbol.startswith("python:dispatch:."):
            return None
        term = call.to_term(owner="UniverseValue.call_leaves")
        atoms.extend(
            atomic(CALL_LEAVES, [term, str_const(str(position))])
            for position in range(len(call.arg_values))
        )
    return atoms


def stated_by_its_inputs(term, formals) -> bool:
    """Whether ``term`` is a value a contract over ``formals`` (its
    parameters and inputs) determines: every variable one of its formals, no
    object identity (``py.object.*``: no two calls share one), no lambda, and
    no state keyed on an operation's occurrence alone
    (``UNDETERMINED_STATES``; a branch's slot and a live loop's publication,
    ``_UNSTATED_SLOTS``, ``_UNSTATED_PREFIXES``).  A value the callee does
    not determine is never stated: it stays undecided by name (#7757 step
    7)."""
    from sugar_lift_py_tests.ir import _Ctor, _Lambda, _Var

    formals = set(formals)
    pending = [term]
    while pending:
        current = pending.pop()
        if isinstance(current, _Var):
            if current.name not in formals:
                return False
        elif isinstance(current, _Lambda):
            return False
        elif isinstance(current, _Ctor):
            if (
                current.name in UNDETERMINED_STATES
                or current.name in _UNSTATED_SLOTS
                or current.name.startswith(_UNSTATED_PREFIXES)
            ):
                return False
            pending.extend(current.args)
    return True


def _names_a_call_result(term) -> bool:
    """Whether ``term`` names what a call in the body returned
    (``python:call_result(<call>, <occurrence>)``, one evaluation of that
    call).  A field holds the object itself: two calls of the function
    would state one such term for two objects a call may have made fresh
    (``Box()``), so the field is not stated, and a caller's read of it
    stays undecided (#7757 step 7)."""
    from sugar_lift_py_tests.ir import _Ctor

    pending = [term]
    while pending:
        current = pending.pop()
        if isinstance(current, _Ctor):
            if current.name == "python:call_result":
                return True
            pending.extend(current.args)
    return False


def _stated_formal_sorts(formals, formal_coordinates):
    """One sort per formal, or none at all.

    A formal coordinate of an abstract definition carries its sort; the
    binding coordinate of a frame applied at a call (``BindingCoordinateV1``)
    carries none. A signature is stated only when every formal has a sorted
    coordinate: a partial signature would be a claim nothing made.
    """
    sorts = [getattr(coordinate, "sort", None) for coordinate in formal_coordinates]
    if len(sorts) != len(formals) or any(sort is None for sort in sorts):
        return []
    return [{"kind": "primitive", "name": sort.name} for sort in sorts]


#: The kind of variadic parameter a formal coordinate states, as the
#: contract names it (``variadicFormals``, read by prove's one binder,
#: ``consistency::contract_binder_formals``).
_VARIADIC_KINDS = {
    "variadic-positional": "positional",
    "variadic-keyword": "keyword",
}


def _stated_variadic_formals(formals, formal_coordinates):
    """``((kind, formal), ...)``: the ``*args`` (``positional``) and
    ``**kwargs`` (``keyword``) parameters among ``formals``, read off the
    parameter kind each one's formal coordinate states
    (``FormalParameterCoordinateV1.parameter_kind``).  Prove's one binder
    binds a ``*args`` formal to the tuple of the positional arguments no
    other parameter takes and a ``**kwargs`` formal to the dict of the
    keyword arguments no other parameter takes (#7757), so a call spelled
    as Python spells it (``__exit__(m, t, v, tb)`` for ``def
    __exit__(self, *exc)``) fits.  A coordinate stating no kind (a frame's
    binding coordinate) states none."""
    stated = []
    for formal, coordinate in zip(formals, formal_coordinates):
        kind = _VARIADIC_KINDS.get(getattr(coordinate, "parameter_kind", None))
        if kind is not None:
            stated.append((kind, formal))
    return tuple(stated)


def contract_claim(formula, *, formals, def_memento, role, floor_chain):
    """One formula of a function's contract row, in the one claim form.

    The post and every halted arm's guard (``PanicLocusDto.guard``) are both
    stated through here: scoped to the function's formals, warranted at its
    definition, so the guard is written exactly as the post is.
    """
    from sugar_lift_py_tests.floor.universe_mint_projection import claim_formula
    from sugar_lift_py_tests.proofir.nodes import (
        ConstructionSite,
        Derived,
        Provenance,
    )

    span = def_memento.span
    provenance = Provenance(
        node_class="BodyUniverseDto",
        construction_site=ConstructionSite(
            path=def_memento.file,
            line=span.start_line,
            column=span.start_col,
        ),
        warrant=Derived(floor_chain=tuple(floor_chain)),
    )
    return claim_formula(formula, formals=formals, provenance=provenance, role=role)


def function_contract_row(
    *,
    name,
    formals,
    bridge_source_symbol,
    formal_coordinates,
    post,
    def_memento,
    panic_loci=(),
    assertions=(),
):
    """The one contract row of a function: its post, its assertions, its halts.

    A function is one contract (#7766, step 7): one row, one name. Its
    ``post`` is the reduction's completed arms; its ``inv`` is what its
    assertions state (``assertions``, the ``UniverseMint`` rows the record
    entries mint, ``assertion_claims``), conjoined; its ``panicLoci`` are the
    halted arms. Before this, each assertion was a second ``contract`` row
    under the same name, and prove loaded two contracts for one function and
    refused the second as a duplicate name.

    ``formalSorts`` states one sort per formal, the sort its authenticated
    formal coordinate carries (the same statement ``ParameterOwnedContractV1``
    makes). The linker's catalog reads a contract's signature from it.

    ``variadicFormals`` names the ``*args`` and ``**kwargs`` among the
    formals (``_stated_variadic_formals``), which prove's one binder binds as
    Python binds them.

    ``panic_loci`` states the reduction's halted arms, one entry each, in the
    existing ``panicLoci`` shape (#7766), each with its arm's guard.

    ``bridge_source_symbol`` is stated only by a row that has one: a
    definition's one join symbol (``SourceUnit.definition_symbol``:
    ``python:<module>.<qualname>``, ``@<line>:<col>`` where the qualname alone
    is not unique), which is the row's ``name`` too, so two methods of one
    name never share a contract name. A contract dug at a call site has
    none and states none, so it is not an entry of the linker's catalog and
    never stands beside the callee's definition under a second spelling
    (#7762).
    """
    import dataclasses

    from sugar_lift_py_tests.kit_rpc import BodyUniverseDto

    inv = None
    proofir_provenance = None
    source_warrants = [def_memento]
    if assertions:
        from sugar_lift_py_tests.floor.universe_mint_projection import claim_formula

        provenance = _assertions_provenance(assertions)
        inv = claim_formula(
            _conjoined([row.formula.ir_formula for row in assertions]),
            formals=formals,
            provenance=provenance,
            role="inv",
        )
        proofir_provenance = provenance.to_rpc()
        for row in assertions:
            for stated in row.source_warrants:
                # A warrant names the source function as its ``def`` spells it
                # (the memento the source oracle reads back), never the
                # contract's join symbol.
                warrant = dataclasses.replace(
                    stated,
                    source_function_name=def_memento.source_function_name,
                    role="assertion",
                )
                if warrant not in source_warrants:
                    source_warrants.append(warrant)
    return BodyUniverseDto(
        name=name,
        post=contract_claim(
            post,
            formals=formals,
            def_memento=def_memento,
            role="post",
            floor_chain=("UniverseValue.post",),
        ),
        inv=inv,
        source_warrants=source_warrants,
        proofir_provenance=proofir_provenance,
        formals=list(formals),
        formal_sorts=_stated_formal_sorts(formals, formal_coordinates),
        variadic_formals=_stated_variadic_formals(formals, formal_coordinates),
        kind="function-contract",
        bridge_source_symbol=bridge_source_symbol,
        panic_loci=tuple(panic_loci),
    )


def assertion_claims(name, formals, entries):
    """What the record entries state for themselves (``mint_contribution``):
    the ``UniverseMint`` rows a function's contract carries as its ``inv``."""
    return [row for entry in entries for row in entry.mint_contribution(name, formals)]


def _conjoined(formulas):
    """One formula for several assertion claims: the one claim as itself, or
    the conjunction of every distinct top-level conjunct, in order."""
    from sugar_lift_py_tests.ir import _Connective, and_

    formulas = list(formulas)
    if len(formulas) == 1:
        return formulas[0]
    conjuncts = []
    for formula in formulas:
        parts = (
            formula.operands
            if isinstance(formula, _Connective) and formula.kind == "and"
            else (formula,)
        )
        for part in parts:
            if part not in conjuncts:
                conjuncts.append(part)
    if len(conjuncts) == 1:
        return conjuncts[0]
    return and_(conjuncts)


def _assertions_provenance(assertions):
    """The assertions' provenance, as one: every warrant any of them states,
    once each, in order, at the first assertion's construction site."""
    from sugar_lift_py_tests.proofir.nodes import Provenance

    first = assertions[0].provenance()
    warrants = []
    for row in assertions:
        for warrant in row.provenance().warrants:
            if warrant not in warrants:
                warrants.append(warrant)
    return Provenance(
        node_class=first.node_class,
        construction_site=first.construction_site,
        warrant=tuple(warrants),
    )


def assertion_site_key(site):
    """An assertion site's identity: the fragment's own address."""
    from sugar_lift_py_tests.effect.runtime_effect import resolve_runtime_effect_site

    fragment = resolve_runtime_effect_site(site)
    return (fragment.filename, fragment.line, fragment.col)


def _testimony(site) -> bool:
    """Whether a fact a record carries at ``site`` is testimony rather than
    an assertion's claim.  Only an ``assert`` statement's fact (``AssertSugar``
    states it at its own fragment) claims that an execution reaches its site
    and it holds there; the fragment names its node, as a raise's site does
    for ``tree_enumerate.halted_assertion_sites``."""
    from sugar_source_tree.nodes import Assert

    return not isinstance(getattr(site, "node", None), Assert)


def exit_arms_payload_rows(
    *,
    name,
    formals,
    bridge_source_symbol,
    formal_coordinates,
    arms,
    halted_assertion_sites,
    halt_loci,
    def_memento,
    unreached_assertion_sites,
    halted_guards,
    leaves=(),
):
    """Every arm of one reduction, projected to the wire (#7766): ONE row.

    A function is one contract under one name (``function_contract_row``):
    the post, every assertion claim below as its ``inv``, and every halted
    arm as a ``panicLoci`` entry. No second row is ever emitted for the same
    function.

    ``arms`` are the completed arms ``(guard, UniverseValue)``.
    ``halted_assertion_sites`` are the ``assert`` statements at which a halted
    arm of the SAME reduction left: the reduction reached the assertion and
    control halted there. ``halt_loci`` are the reduction's halted arms, one
    ``PanicLocusDto`` each, wherever they left. ``halted_guards`` are those
    arms' guards. ``unreached_assertion_sites`` are, for a reduction with no
    completed arm, the function's own ``assert`` statements no arm reached
    (``tree_enumerate.unreached_assertion_sites``).

    * post: the conjunction over completed arms of ``g_i -> post_i``, and
      nothing else. A halted arm adds nothing to it, so a function that only
      halts states the empty conjunction: no claim about any result. Beside
      it, one ``python:leaves("<parameter>")`` per parameter the body never
      changes (``leaves``, ``tree_enumerate.parameters_left_unchanged``):
      what prove asks of a dispatched call binding one object to two formals
      (step 8). It states nothing about a result.
    * every halted arm: one ``panicLoci`` entry on the function-contract row,
      the existing panic-locus shape: the site it halted at, the raised type,
      and the arm's guard as its path condition. A halt is never dropped.
    * one assertion claim per assertion SITE the reduction evaluated: the OR over
      the completed arms that hold the site of ``g_i AND fact_i``. The claim of
      an assertion is that an execution reaches it and it holds there; a guard
      that can be made false must not satisfy it, so this is never
      ``g -> fact``. A site an arm halted at and no completed arm holds states
      the OR over nothing: false.
    * a fact that is no assertion's (``_testimony``: a handler's effect slot,
      a manager's slots, a loop's recurrence) is what holds where its arm
      ran. Held on only some completed arms it is stated as the conjunction
      of ``g_i -> fact_i``: never a claim that one of those arms ran.
    * when no arm completed, one assertion claim per ``assert`` of the function
      no arm reached: the conjunction over the halted arms of ``not g_h``.
      Every execution the reduction states halts before it, so an execution
      reaching it is one no halted arm's guard admits; the OR over completed
      arms is over nothing, and the halted guards are what prove reads to
      decide that. Halted arms whose guards cover every execution (a certain
      halt) state a claim no execution satisfies (``false`` where the guards
      fold, as a halt under truth does), so a test that certainly raises is
      refuted at prove; a halt under a guard that may be false states a
      satisfiable claim and is never refuted.

    Where a completed arm exists, every site comes from the reduction. An
    ``assert`` no arm evaluated there (dead code: a handler that never runs, a
    branch the floor decided away) has no claim, because the function
    completes without it; and a fact held on an arm that later halts
    elsewhere is not a completed arm's fact.

    This is the ONE projection from a reduction to rows; a single arm under
    guard true is its one-arm case and states the claims it always had.
    """
    from sugar_lift_py_tests.floor.inv_value import InvValue
    from sugar_lift_py_tests.ir import and_, implies, or_
    from sugar_lift_py_tests.outcome.exit_set import (
        _and_guards,
        _is_true,
        complement_guard,
        false_guard,
        true_guard,
    )

    if len(arms) == 1 and _is_true(arms[0][0]):
        guard, value = arms[0]
        post = value.post()
        assertions = assertion_claims(name, formals, value.record.statements)
        reached = {
            assertion_site_key(entry.site)
            for entry in value.record.statements
            if isinstance(entry, InvValue)
        }
    else:
        post = and_([implies(guard, value.post()) for guard, value in arms])
        by_site: dict = {}
        for arm_index, (guard, value) in enumerate(arms):
            for entry in value.record.statements:
                if isinstance(entry, InvValue):
                    key = assertion_site_key(entry.site)
                    by_site.setdefault(key, {}).setdefault(arm_index, (guard, []))[
                        1
                    ].append(entry)
                    continue
                if entry.mint_contribution(name, formals):
                    from sugar_source_tree.panic import SugarNotWritten

                    raise SugarNotWritten(
                        owner="exit_arms_payload_rows",
                        blame=name,
                        observed=f"{type(entry).__name__} mints rows on one arm of several",
                        requested="the entry's rows under its arm's guard",
                        fix=(
                            f"give {type(entry).__name__} the arm-guarded "
                            "projection InvValue has"
                        ),
                    )
        reached = set(by_site)
        combined = []
        for per_arm in by_site.values():
            arm_rows = list(per_arm.values())
            first = arm_rows[0][1][0]
            # Only an ``assert`` claims that an execution reaches its site.
            # Any other fact a record carries is testimony given where its
            # arm ran (a handler's effect slot, a manager's slots, a loop's
            # recurrence): held on only some completed arms, it is stated
            # under each one's guard, never as a claim that one of them ran
            # (#7757: the handler's slot facts in ``try: C(1); ok = True
            # except AssertionError: pass`` claimed the handler ran and
            # refuted ``ok == True``).  Held on every completed arm, the two
            # read the same wherever the function completes.
            given = _testimony(first.site) and len(arm_rows) < len(arms)

            def stated(parts, given=given):
                # ``parts``: each arm's guard with what it holds at the site.
                if given:
                    return and_(
                        [implies(guard, and_(list(held))) for guard, held in parts]
                    )
                return or_([and_([guard, *held]) for guard, held in parts])

            derived_arms = [
                (guard, [d for inv in invs for d in inv.derived_formulas])
                for guard, invs in arm_rows
            ]
            derived = (
                (stated(derived_arms),)
                if all(ds for _guard, ds in derived_arms)
                else ()
            )
            combined.append(
                InvValue(
                    stated(
                        [
                            (guard, [inv.formula for inv in invs])
                            for guard, invs in arm_rows
                        ]
                    ),
                    first.site,
                    tuple(
                        callsite
                        for _guard, invs in arm_rows
                        for inv in invs
                        for callsite in inv.operand_callsites
                    ),
                    derived,
                    tuple(
                        chain
                        for _guard, invs in arm_rows
                        for inv in invs
                        for chain in inv.rewrite_chains
                    ),
                )
            )
        assertions = assertion_claims(name, formals, combined)
    never_held = []
    for site in halted_assertion_sites:
        key = assertion_site_key(site)
        if key in reached:
            continue
        reached.add(key)
        never_held.append(InvValue(false_guard(), site))
    if unreached_assertion_sites:
        no_halt = true_guard()
        for guard in halted_guards:
            no_halt = _and_guards(no_halt, complement_guard(guard))
        for site in unreached_assertion_sites:
            key = assertion_site_key(site)
            if key in reached:
                continue
            reached.add(key)
            never_held.append(InvValue(no_halt, site))
    assertions.extend(assertion_claims(name, formals, never_held))
    if leaves:
        from sugar_lift_py_tests.ir import atomic, str_const

        post = and_(
            [post, *(atomic(LEAVES, [str_const(parameter)]) for parameter in leaves)]
        )
    return [
        function_contract_row(
            name=name,
            formals=formals,
            bridge_source_symbol=bridge_source_symbol,
            formal_coordinates=formal_coordinates,
            post=post,
            def_memento=def_memento,
            panic_loci=halt_loci,
            assertions=assertions,
        )
    ]
