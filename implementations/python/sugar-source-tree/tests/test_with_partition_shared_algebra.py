"""Integration twin: the ``with`` partition is ONE control algebra, two contracts.

Two slices landed independently. Resource ``with`` routes
``body -> ExitSet -> and_exit(exit_es, disposition=<typed>)``. Assertion ``with``
routes ``body -> ExitSet -> EffectBoundary``. Each of their own twins proves
*which sugar gets selected*. Neither proves the two share a control algebra --
and that is the whole difference between a semantic partition and two syntactic
implementations fighting over the ``with`` keyword.

This file builds **one** body ``ExitSet`` and applies **two authenticated
contracts** to it. The source text, the ``with`` item, the body statements and
the resolved use site are byte-identical across both arms; the *only* thing that
differs is the ``semantics`` field of the authenticated contract ref:

    ProtocolResourceSemanticsV1(exit=ExitContractV1(disposition=...))
    EffectBoundarySemanticsV1(ExpectsModeV1(), RaiseEffectKindV1(), ...)

The body is a genuine two-edge partition -- ``if flag: raise ValueError(...)`` --
so both routers receive one ``Halted`` edge and one ``Completed`` edge under
complementary guards, and every law below is about what each contract does to
*those same two edges*.

Laws are paired 1:1 with discrimination bites. The last pair is the lying arm:
it swaps the two contracts and MUST fail, which is what makes the partition
load-bearing rather than documentation.
"""

from __future__ import annotations

from types import MappingProxyType

import pytest

from sugar_lift_py_tests.context_manager_contract import (
    CallParameterV1,
    EffectBoundarySemanticsV1,
    EffectMatcher,
    EnterResultContractV1,
    ExceptionInfoBindingV1,
    ExitContractV1,
    ExpectsModeV1,
    FormalArgumentProjectionV1,
    KeywordOnlyV1,
    LiteralDefaultV1,
    NeverSuppresses,
    NeverSuppressesDispositionV1,
    NoDefaultV1,
    OptionalFormalArgumentProjectionV1,
    PositionalOrKeywordV1,
    ProtocolResourceSemanticsV1,
    RaiseEffectKindV1,
    RuntimeSelected,
    Suppresses,
)
from sugar_lift_py_tests.context_manager_resolution import (
    ContextManagerContractRefV1,
    ImportSignatureV2,
    ResolvedContractRefsV1,
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
    _hash_json,
)
from sugar_lift_py_tests.effect import ExpectationNotMetEffect, RaiseEffect
from sugar_lift_py_tests.floor.call_site_value import ExitSuppressionContract
from sugar_lift_py_tests.ir import PrimitiveSort
from sugar_lift_py_tests.outcome import Incomplete
from sugar_lift_py_tests.outcome.exit_set import (
    Completed,
    ExitSet,
    Halted,
    complement_guard,
)
from sugar_lift_py_tests.sugar.exit_set_routing import (
    promote_raise_halts,
    sugar_outcome_to_exitset,
)
from sugar_lift_py_tests.sugar.function_universe_sugar import reduce_block_to_exitset
from sugar_lift_py_tests.sugar.with_effect_boundary_sugar import WithEffectBoundarySugar
from sugar_lift_py_tests.sugar.with_resource_sugar import WithResourceSugar
from sugar_source_tree.tree import SourceFile

# ---------------------------------------------------------------------------
# One source text. One with-item. One body. Two contracts.
# ---------------------------------------------------------------------------

# Neutral spelling on purpose: the router must not recognize a vendor. The
# contract arrives through the authenticated resolution table, never through
# the manager's name.
MATCHING_BODY = (
    "from contracts import scope as hold\n"
    "def f(flag):\n"
    '    with hold(ValueError, match="boom"):\n'
    "        if flag:\n"
    '            raise ValueError("boom")\n'
)

MISMATCHED_BODY = (
    "from contracts import scope as hold\n"
    "def f(flag):\n"
    '    with hold(ValueError, match="boom"):\n'
    "        if flag:\n"
    '            raise TypeError("boom")\n'
)

RESOURCE_SEMANTICS = ProtocolResourceSemanticsV1(
    enter=EnterResultContractV1(sort=PrimitiveSort("Value")),
    exit=ExitContractV1(disposition=NeverSuppressesDispositionV1()),
)

ASSERTION_SEMANTICS = EffectBoundarySemanticsV1(
    ExpectsModeV1(),
    RaiseEffectKindV1(),
    FormalArgumentProjectionV1(0),
    OptionalFormalArgumentProjectionV1(1),
    ExceptionInfoBindingV1(),
)

# The manager signature is shared by both arms: the resource arm and the
# assertion arm see the *same* two formals of the *same* call occurrence.
SIGNATURE = ImportSignatureV2(
    (
        CallParameterV1(
            "expected_exception",
            PrimitiveSort("Value"),
            PositionalOrKeywordV1(),
            True,
            NoDefaultV1(),
        ),
        CallParameterV1(
            "match",
            PrimitiveSort("String"),
            KeywordOnlyV1(),
            False,
            LiteralDefaultV1({"kind": "ctor", "name": "None", "args": []}),
        ),
    )
)


def _cid(char: str) -> str:
    return "blake3-512:" + char * 128


def _coordinate(node) -> SourceFragmentCoordinateV1:
    span = node.line_col_span()
    return SourceFragmentCoordinateV1(
        node.unit.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )


def _ref(use_site, semantics) -> ContextManagerContractRefV1:
    """One authenticated ref shape; ``semantics`` is the only variable."""
    return ContextManagerContractRefV1(
        resolution_cid=_cid("r"),
        demand_cid=_cid("d"),
        use_site=use_site,
        use_site_cid=_hash_json(use_site.wire()),
        authenticated_import_use_cid=_cid("u"),
        import_binding_cid=_cid("i"),
        construction_context_generation_cid=_cid("g"),
        contract_cid=_cid("m"),
        payload_cid=_cid("p"),
        provenance_cid=_cid("v"),
        distribution_artifact_cid=_cid("a"),
        dependency_artifact_graph_cid=_cid("b"),
        module_source_cid=_cid("s"),
        resolved_definition_cid=_cid("f"),
        manager_construction_cid=_cid("n"),
        enter_testimony_cid=_cid("1"),
        exit_testimony_cid=_cid("2"),
        import_signature=SIGNATURE,
        semantics=semantics,
    )


def _with_statement(tmp_path, source, semantics, stem="partition"):
    """Construct the sole ``with`` statement of ``source`` under ``semantics``."""
    from sugar_lift_python_source.source_oracle import path_source

    path = tmp_path / f"{stem}.py"
    path.write_text(source)
    identity = path_source(str(path))

    probe = SourceFile(identity)
    node = next(n for n in probe.nodes() if n.kind in {"With", "AsyncWith"})
    use_site = _coordinate(node.items[0].context_expr)

    table = ResolvedContractRefsV1(
        catalog_cid=_cid("c"),
        table_cid=_cid("t"),
        by_use_site=MappingProxyType({use_site: _ref(use_site, semantics)}),
    )
    resolved = SourceFile(
        identity, construction_context=TreeConstructionContextV1(table)
    )
    return next(resolved.functions()).sugar().statements[0]


def _both_arms(tmp_path, source=MATCHING_BODY, stem="partition"):
    """The same ``with`` under both contracts.

    Returns ``(resource, boundary)``. The two sugars are constructed from the
    identical file (same bytes, same CIDs, same use site) so their ``body``
    tuples are the same value -- asserted by the first law below.
    """
    resource = _with_statement(tmp_path, source, RESOURCE_SEMANTICS, stem)
    boundary = _with_statement(tmp_path, source, ASSERTION_SEMANTICS, stem)
    assert isinstance(resource, WithResourceSugar)
    assert isinstance(boundary, WithEffectBoundarySugar)
    return resource, boundary


def _body_exitset(body):
    """THE body ExitSet: the exact expression both routers reduce their body by.

    ``WithResourceSugar.desugar`` and ``WithEffectBoundarySugar.desugar`` each
    compute ``promote_raise_halts(reduce_block_to_exitset(self.body))``. Calling
    it once here is what makes this an integration twin instead of two unit
    twins: there is one body partition and it is fed to both contracts.
    """
    return promote_raise_halts(reduce_block_to_exitset(body))


def _sole(exits, kind):
    found = [exit_ for exit_ in exits.exits if isinstance(exit_, kind)]
    assert len(found) == 1, f"expected exactly one {kind.__name__}, got {found}"
    return found[0]


def _on_guard(exits, guard):
    """The single exit standing on one branch of the body partition.

    Contracts move an edge between ``Completed`` and ``Halted``; they never move
    it between guards. Selecting by guard is therefore how you follow *the same
    incoming edge* through two different contracts.
    """
    found = [exit_ for exit_ in exits.exits if exit_.guard == guard]
    assert len(found) == 1, f"expected exactly one exit on {guard}, got {found}"
    return found[0]


def _resource_route(body_es, resource, disposition):
    """Apply a resource contract to a body ExitSet through the generic router.

    ``ExitSet.and_exit`` is the production hook point, invoked here with
    production-derived operands: the constructed ``__exit__`` ExitSet of the
    real tree-owned exit sugar, and a typed disposition. Nothing is
    reimplemented.
    """
    exit_es = sugar_outcome_to_exitset(resource.exit.desugar())
    return body_es.and_exit(exit_es, disposition=disposition)


def _assertion_route(boundary):
    """Apply the assertion contract to the same body through its own router."""
    routed = boundary.desugar()
    assert isinstance(routed, ExitSet)
    return routed


# ---------------------------------------------------------------------------
# Law 1 -- one body, two contracts
# ---------------------------------------------------------------------------


def test_one_body_partition_is_what_both_contracts_receive(tmp_path):
    resource, boundary = _both_arms(tmp_path)

    assert resource.body == boundary.body

    body_es = _body_exitset(resource.body)
    assert body_es == _body_exitset(boundary.body)

    halted = _sole(body_es, Halted)
    completed = _sole(body_es, Completed)
    assert isinstance(halted.effect, RaiseEffect)
    assert halted.effect.exception_name == "ValueError"
    assert completed.guard == complement_guard(halted.guard)


def test_discrimination_body_equality_is_not_vacuous(tmp_path):
    resource, _ = _both_arms(tmp_path)
    other, _ = _both_arms(tmp_path, source=MISMATCHED_BODY, stem="other")

    assert resource.body != other.body
    assert _body_exitset(resource.body) != _body_exitset(other.body)


# ---------------------------------------------------------------------------
# Law 2 -- the same completed/halted incoming edges enter both routers
# ---------------------------------------------------------------------------


def test_both_contracts_receive_the_same_completed_and_halted_guards(tmp_path):
    resource, boundary = _both_arms(tmp_path)
    body_es = _body_exitset(resource.body)
    incoming = {_sole(body_es, Halted).guard, _sole(body_es, Completed).guard}

    resource_routed = _resource_route(body_es, resource, resource.disposition)
    assertion_routed = _assertion_route(boundary)

    assert {exit_.guard for exit_ in resource_routed.exits} == incoming
    assert {exit_.guard for exit_ in assertion_routed.exits} == incoming


def test_discrimination_the_guard_set_is_not_a_constant(tmp_path):
    """A guardless body yields a different guard set -- the check has teeth."""
    resource, _ = _both_arms(
        tmp_path,
        source=(
            "from contracts import scope as hold\n"
            "def f(flag):\n"
            '    with hold(ValueError, match="boom"):\n'
            '        raise ValueError("boom")\n'
        ),
        stem="unguarded",
    )
    body_es = _body_exitset(resource.body)
    unguarded = {exit_.guard for exit_ in body_es.exits}

    guarded_resource, _ = _both_arms(tmp_path, stem="guarded")
    guarded = {exit_.guard for exit_ in _body_exitset(guarded_resource.body).exits}

    assert unguarded != guarded


# ---------------------------------------------------------------------------
# Law 3 -- occurrence identities survive both contracts
# ---------------------------------------------------------------------------


def test_both_contracts_preserve_the_same_occurrence_identities(tmp_path):
    resource, boundary = _both_arms(tmp_path)
    body_es = _body_exitset(resource.body)
    body_halt = _sole(body_es, Halted)
    occurrence = body_halt.effect.occurrence
    assert occurrence

    # Within one routing, the resource contract forwards the *same object*: the
    # restored halt is not a rebuilt effect that merely compares equal.
    resource_routed = _resource_route(body_es, resource, resource.disposition)
    restored = _on_guard(resource_routed, body_halt.guard)
    assert restored.effect is body_halt.effect
    assert restored.state is body_halt.state

    # The assertion contract consumes that halt. What it hands forward is the
    # real pre-halt state of the *same* occurrence, never a fabricated
    # continuation -- and the occurrence coordinate is the one both contracts
    # were handed.
    assertion_routed = _assertion_route(boundary)
    consumed = _on_guard(assertion_routed, body_halt.guard)
    assert isinstance(consumed, Completed)
    assert consumed.value == body_halt.state
    assert restored.effect.occurrence == occurrence
    assert (
        _on_guard(_body_exitset(boundary.body), body_halt.guard).effect.occurrence
        == occurrence
    )


def test_discrimination_the_consumed_state_is_not_the_completed_body_value(tmp_path):
    resource, boundary = _both_arms(tmp_path)
    body_es = _body_exitset(resource.body)

    body_halt = _sole(body_es, Halted)
    body_completion = _sole(body_es, Completed)
    assert body_halt.state != body_completion.value

    consumed = _on_guard(_assertion_route(boundary), body_halt.guard)
    assert consumed.value != body_completion.value


# ---------------------------------------------------------------------------
# Law 4 -- generic ExitSet routing in both cases
# ---------------------------------------------------------------------------


def test_both_contracts_route_through_generic_exitset_machinery(tmp_path):
    resource, boundary = _both_arms(tmp_path)
    body_es = _body_exitset(resource.body)

    resource_routed = _resource_route(body_es, resource, resource.disposition)
    assertion_routed = _assertion_route(boundary)

    for routed in (resource_routed, assertion_routed):
        assert isinstance(routed, ExitSet)
        assert len(routed.exits) == len(body_es.exits) == 2
        assert routed == routed.normalize()
        assert len([e for e in routed.exits if isinstance(e, Completed)]) == 1
        assert len([e for e in routed.exits if isinstance(e, Halted)]) == 1


def test_discrimination_the_reconstructed_resource_route_matches_production(tmp_path):
    """The ``and_exit`` call above is not a test-local shortcut.

    ``WithResourceSugar.desugar`` projects its routed ExitSet back to the linear
    ``Complete(BlockValue)`` view. Its halted entries must carry exactly the
    effect and guard the reconstructed route produced.
    """
    resource, _ = _both_arms(tmp_path)
    body_es = _body_exitset(resource.body)
    routed = _resource_route(body_es, resource, resource.disposition)
    expected = _sole(routed, Halted)

    produced = resource.desugar()
    incompletes = [
        entry
        for entry in produced.value.statements
        if isinstance(entry, Incomplete)
    ]
    assert len(incompletes) == 1
    assert incompletes[0].effect == expected.effect
    assert incompletes[0].effect.occurrence == expected.effect.occurrence
    assert incompletes[0].branch_conditions == (expected.guard,)


# ---------------------------------------------------------------------------
# Law 5 -- on the halted edge the two paths agree once the contracts correspond
# ---------------------------------------------------------------------------


def test_corresponding_contracts_produce_the_same_halted_edge_outcome(tmp_path):
    """The shared-algebra claim, stated where it is true.

    Substituting a resource contract that consumes exactly what the assertion
    expects reproduces the assertion's halted-edge outcome *identically* -- same
    guard, same carried state, same Completed constructor. The difference
    between the two paths on this edge is the contract and nothing else.
    """
    resource, boundary = _both_arms(tmp_path)
    body_es = _body_exitset(resource.body)
    halted_edge = _sole(body_es, Halted).guard

    as_assertion = _resource_route(
        body_es,
        resource,
        Suppresses(EffectMatcher(kind="raise", name="ValueError")),
    )
    assertion_routed = _assertion_route(boundary)

    resource_edge = _on_guard(as_assertion, halted_edge)
    assertion_edge = _on_guard(assertion_routed, halted_edge)
    assert isinstance(resource_edge, Completed)
    assert isinstance(assertion_edge, Completed)
    assert resource_edge == assertion_edge


def test_discrimination_the_shipped_resource_contract_does_not_agree(tmp_path):
    resource, boundary = _both_arms(tmp_path)
    body_es = _body_exitset(resource.body)

    shipped = _resource_route(body_es, resource, resource.disposition)
    assertion_routed = _assertion_route(boundary)

    assert shipped != assertion_routed
    assert isinstance(_sole(shipped, Halted).effect, RaiseEffect)
    assert isinstance(_sole(assertion_routed, Halted).effect, ExpectationNotMetEffect)


# ---------------------------------------------------------------------------
# Law 6 -- a resource contract cannot consume an assertion just because the
#          exception happens to match
# ---------------------------------------------------------------------------


def test_resource_contract_does_not_consume_a_matching_exception(tmp_path):
    resource, _ = _both_arms(tmp_path)
    body_es = _body_exitset(resource.body)
    body_halt = _sole(body_es, Halted)
    assert body_halt.effect.exception_name == "ValueError"

    for disposition in (
        NeverSuppresses(),
        NeverSuppressesDispositionV1(),
        ExitSuppressionContract.never_suppresses(),
    ):
        routed = _resource_route(body_es, resource, disposition)
        restored = _sole(routed, Halted)
        assert restored.effect is body_halt.effect
        assert restored.guard == body_halt.guard


def test_discrimination_a_suppressing_contract_can_reach_that_edge(tmp_path):
    """The edge is reachable, so the law above is a refusal, not an inability."""
    resource, _ = _both_arms(tmp_path)
    body_es = _body_exitset(resource.body)

    for disposition in (
        Suppresses(EffectMatcher(kind="raise", name="ValueError")),
        ExitSuppressionContract.suppresses(("ValueError",)),
    ):
        routed = _resource_route(body_es, resource, disposition)
        assert len([e for e in routed.exits if isinstance(e, Halted)]) == 0


# ---------------------------------------------------------------------------
# Law 7 -- an assertion contract cannot behave as a generic ``__exit__``
# ---------------------------------------------------------------------------


ALL_DISPOSITIONS = (
    NeverSuppresses(),
    NeverSuppressesDispositionV1(),
    RuntimeSelected(),
    ExitSuppressionContract.never_suppresses(),
    ExitSuppressionContract.suppresses(("ValueError",)),
    Suppresses(EffectMatcher(kind="raise", name="ValueError")),
    Suppresses(EffectMatcher(kind="raise", name="TypeError")),
)


def test_assertion_contract_cannot_be_spelled_as_a_generic_exit(tmp_path):
    """The completed edge is where the two contracts stop being interchangeable.

    Under ``Expects``, a body that *completed* is a failed expectation and must
    halt. ``and_exit`` decides ``Completed`` incoming before it ever consults
    the disposition, so no resource contract -- for any of the four typed
    disposition families -- can produce that halt. This is the honest boundary
    of the shared algebra and it is asserted exhaustively, not asserted away.
    """
    resource, boundary = _both_arms(tmp_path)
    body_es = _body_exitset(resource.body)
    body_completion = _sole(body_es, Completed)

    assertion_halt = _sole(_assertion_route(boundary), Halted)
    assert isinstance(assertion_halt.effect, ExpectationNotMetEffect)
    assert assertion_halt.guard == body_completion.guard

    for disposition in ALL_DISPOSITIONS:
        routed = _resource_route(body_es, resource, disposition)
        surviving = [
            exit_ for exit_ in routed.exits if exit_.guard == body_completion.guard
        ]
        assert surviving, f"completed edge vanished under {disposition!r}"
        for exit_ in surviving:
            assert isinstance(exit_, Completed), (
                f"{disposition!r} turned the completed edge into a halt; "
                "and_exit is not supposed to be able to express Expects"
            )


def test_discrimination_the_disposition_sweep_is_not_inert(tmp_path):
    """The same sweep does move the *halted* edge -- so it is a real sweep."""
    resource, _ = _both_arms(tmp_path)
    body_es = _body_exitset(resource.body)
    body_halt = _sole(body_es, Halted)

    kinds = set()
    for disposition in ALL_DISPOSITIONS:
        routed = _resource_route(body_es, resource, disposition)
        for exit_ in routed.exits:
            if exit_.guard == body_halt.guard:
                kinds.add(type(exit_).__name__)
    assert kinds == {"Completed", "Halted"}


# ---------------------------------------------------------------------------
# Law 8 -- a mismatched assertion halt stays outgoing
# ---------------------------------------------------------------------------


def test_mismatched_assertion_halt_remains_outgoing(tmp_path):
    resource, boundary = _both_arms(tmp_path, source=MISMATCHED_BODY, stem="mismatch")
    body_es = _body_exitset(resource.body)
    body_halt = _sole(body_es, Halted)
    assert body_halt.effect.exception_name == "TypeError"

    outgoing = _on_guard(_assertion_route(boundary), body_halt.guard)
    assert isinstance(outgoing, Halted)
    assert outgoing.effect == body_halt.effect
    assert outgoing.effect.occurrence == body_halt.effect.occurrence


def test_discrimination_a_matching_halt_does_not_remain_outgoing(tmp_path):
    resource, boundary = _both_arms(tmp_path, stem="match")
    body_halt = _sole(_body_exitset(resource.body), Halted)
    assert body_halt.effect.exception_name == "ValueError"

    outgoing = _on_guard(_assertion_route(boundary), body_halt.guard)
    assert isinstance(outgoing, Completed)


# ---------------------------------------------------------------------------
# Law 9 -- exit / boundary halt supersedes on every incoming edge
# ---------------------------------------------------------------------------


def test_exit_halt_supersedes_every_incoming_edge(tmp_path):
    resource, _ = _both_arms(tmp_path)
    body_es = _body_exitset(resource.body)
    cleanup_failure = RaiseEffect(exception_name="OSError", occurrence="exit:1:0")

    routed = body_es.and_exit(
        ExitSet.halted(cleanup_failure), disposition=resource.disposition
    )

    assert all(isinstance(exit_, Halted) for exit_ in routed.exits)
    assert {exit_.effect for exit_ in routed.exits} == {cleanup_failure}


def test_discrimination_a_completed_exit_does_not_supersede(tmp_path):
    resource, _ = _both_arms(tmp_path)
    body_es = _body_exitset(resource.body)

    routed = _resource_route(body_es, resource, resource.disposition)

    assert isinstance(_sole(routed, Halted).effect, RaiseEffect)
    assert _sole(routed, Halted).effect is _sole(body_es, Halted).effect
    assert _sole(routed, Completed).value is _sole(body_es, Completed).value


# ---------------------------------------------------------------------------
# Law 10 -- neither router branches on the keyword, the vendor, or the spelling
# ---------------------------------------------------------------------------


ROUTER_SOURCES = (
    "sugar_lift_py_tests/outcome/exit_set.py",
    "sugar_lift_py_tests/outcome/resource_exit_disposition.py",
    "sugar_lift_py_tests/sugar/with_effect_boundary_sugar.py",
)

FORBIDDEN_IN_ROUTERS = (
    "pytest",
    "unittest",
    "contextlib",
    "pandas",
    "numpy",
    "hypothesis",
    '"with"',
    "'with'",
    "AsyncWith",
)


def _router_text():
    import pathlib

    import sugar_lift_py_tests

    root = pathlib.Path(sugar_lift_py_tests.__file__).parent.parent
    return {
        name: (root / name).read_text(encoding="utf-8") for name in ROUTER_SOURCES
    }


def test_routers_do_not_branch_on_keyword_vendor_or_manager_spelling():
    for name, text in _router_text().items():
        for token in FORBIDDEN_IN_ROUTERS:
            assert token not in text, f"{name} recognizes {token!r}"


def test_discrimination_the_router_scan_reads_real_files():
    text = _router_text()
    assert len(text) == len(ROUTER_SOURCES)
    assert "def and_exit(" in text["sugar_lift_py_tests/outcome/exit_set.py"]
    assert (
        "def disposition_verdict("
        in text["sugar_lift_py_tests/outcome/resource_exit_disposition.py"]
    )
    assert (
        "ExpectationNotMetEffect"
        in text["sugar_lift_py_tests/sugar/with_effect_boundary_sugar.py"]
    )


# ---------------------------------------------------------------------------
# The lying arm -- swap the contracts and the twin MUST fail
# ---------------------------------------------------------------------------


def _swap_the_contracts(tmp_path):
    """Claim the two contracts are interchangeable on the same body.

    Route the one body under the shipped resource contract and assert it equals
    the assertion routing. If the partition were nominal -- two spellings of one
    behaviour -- this would hold. It must not.
    """
    resource, boundary = _both_arms(tmp_path, stem="lying")
    body_es = _body_exitset(resource.body)

    lied = _resource_route(body_es, resource, resource.disposition)
    truth = _assertion_route(boundary)
    assert lied == truth, "resource contract reproduced the assertion routing"


def test_lying_arm_swapping_the_contracts_fails(tmp_path):
    with pytest.raises(AssertionError, match="reproduced the assertion routing"):
        _swap_the_contracts(tmp_path)


def test_discrimination_the_lying_arm_is_not_failing_for_an_unrelated_reason(tmp_path):
    """It fails on the routing, not on setup: both halves construct fine."""
    resource, boundary = _both_arms(tmp_path, stem="lying_setup")
    body_es = _body_exitset(resource.body)

    lied = _resource_route(body_es, resource, resource.disposition)
    truth = _assertion_route(boundary)

    assert isinstance(lied, ExitSet) and len(lied.exits) == 2
    assert isinstance(truth, ExitSet) and len(truth.exits) == 2
    assert {e.guard for e in lied.exits} == {e.guard for e in truth.exits}
    assert lied != truth
