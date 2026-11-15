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
    cell stays undecided."""

    name: str
    formals: tuple[str, ...]
    record: object  # the body's BlockValue
    bridge_source_symbol: str | None = None
    formal_coordinates: tuple = ()
    after: tuple = ()

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

    def derived_companions(self) -> tuple[Formula, ...]:
        return tuple(
            formula
            for entry in self.record.statements
            for formula in getattr(entry, "derived_post_contribution", lambda: ())()
        )

    def invs(self) -> tuple[Formula, ...]:
        return tuple(
            formula
            for entry in self.record.statements
            for formula in entry.inv_contribution()
        )

    def post(self) -> Formula:
        from sugar_lift_py_tests.ir import and_

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
        companions = (*self.derived_companions(), *after)
        if not companions:
            return post
        return and_([post, *companions])

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
        return tuple(facts)

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
# (``builtin_container_call_sugar._unknown_after``, ``_opaque_pair``,
# ``NativeOperationExitCarrierV1._unanswered_exits``).  A contract instantiated
# at two calls would state one such term for both, so it never states one.
_UNDETERMINED_STATES = frozenset(
    {
        "python:receiver_after_call",
        "python:builtin_method",
        "python:native_operation_result",
        "python:unanswered_native_operation",
    }
)


def stated_by_its_inputs(term, formals) -> bool:
    """Whether ``term`` is a value a contract over ``formals`` (its
    parameters and inputs) determines: every variable one of its formals, no
    object identity (``py.object.*``: no two calls share one), no lambda, and
    no state keyed on an operation's occurrence alone
    (``_UNDETERMINED_STATES``).  A value the callee does not determine is
    never stated: it stays undecided by name (#7757 step 7)."""
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
            if current.name in _UNDETERMINED_STATES or current.name.startswith(
                "py.object"
            ):
                return False
            pending.extend(current.args)
    return True


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
      halts states the empty conjunction: no claim about any result.
    * every halted arm: one ``panicLoci`` entry on the function-contract row,
      the existing panic-locus shape: the site it halted at, the raised type,
      and the arm's guard as its path condition. A halt is never dropped.
    * one assertion claim per assertion SITE the reduction evaluated: the OR over
      the completed arms that hold the site of ``g_i AND fact_i``. The claim of
      an assertion is that an execution reaches it and it holds there; a guard
      that can be made false must not satisfy it, so this is never
      ``g -> fact``. A site an arm halted at and no completed arm holds states
      the OR over nothing: false.
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
            derived_arms = [
                (guard, [d for inv in invs for d in inv.derived_formulas])
                for guard, invs in arm_rows
            ]
            derived = (
                (or_([and_([guard, *ds]) for guard, ds in derived_arms]),)
                if all(ds for _guard, ds in derived_arms)
                else ()
            )
            combined.append(
                InvValue(
                    or_(
                        [
                            and_([guard, *(inv.formula for inv in invs)])
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
