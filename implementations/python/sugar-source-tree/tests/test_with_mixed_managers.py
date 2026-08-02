"""Mixed multi-manager ``with``: BOTH contracts survive the nesting rewrite.

    with manager(), expect_raises(ValueError, match="boom"):
        body

is a single source site with TWO participants under TWO different contracts —
one protocol/resource manager and one assertion effect-boundary. The routing
law is a conjunction, not a disjunction:

- "any resource participant means resource routing" **must not erase the
  assertion participant**, and
- "any assertion participant means boundary routing" must not erase the
  resource participant.

``With._nest_items`` is what makes this structural rather than a policy
decision: the multi-item ``With`` becomes one single-item ``With`` per manager,
so each participant reaches its OWN construction door and gets its own
authenticated contract. Nothing chooses between them, so nothing can drop one.

Python's exit order falls out of the same rewrite: the FIRST source manager is
the outer node (entered first, exited last), so a mixed site folds its two
contracts into reverse exit order without either contract knowing about the
other.

Every law twin here is paired 1:1 with a discrimination arm.
"""

from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType

import pytest

from sugar_lift_py_tests.context_manager_contract import (
    CallParameterV1,
    EffectBoundarySemanticsV1,
    EnterResultContractV1,
    ExceptionInfoBindingV1,
    ExitContractV1,
    ExpectsModeV1,
    FormalArgumentProjectionV1,
    KeywordOnlyV1,
    LiteralDefaultV1,
    NeverSuppressesDispositionV1,
    NoDefaultV1,
    NoMessagePatternV1,
    OptionalFormalArgumentProjectionV1,
    PositionalOrKeywordV1,
    ProtocolResourceSemanticsV1,
    RaiseEffectKindV1,
    WarningEffectKindV1,
    WarningObservationBindingV1,
)
from sugar_lift_py_tests.effect import ExpectationNotMetEffect, WarningEffect
from sugar_lift_py_tests.floor import BlockValue, NoneValue
from sugar_lift_py_tests.floor.warning_observation_value import WarningObservationValue
from sugar_lift_py_tests.context_manager_resolution import (
    ContextManagerContractRefV1,
    ContextManagerResolutionGapV1,
    ImportSignatureV2,
    ResolvedContractRefsV1,
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
    _hash_json,
)
from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
from sugar_lift_py_tests.ir import PrimitiveSort
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.outcome.exit_set import Completed, Halted
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.with_effect_boundary_sugar import WithEffectBoundarySugar
from sugar_lift_py_tests.sugar.with_resource_sugar import WithResourceSugar
from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile

# ---------------------------------------------------------------- tree fixture


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


def _base_ref(use_site, *, signature, semantics) -> ContextManagerContractRefV1:
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
        import_signature=signature,
        semantics=semantics,
    )


def _resource_ref(use_site) -> ContextManagerContractRefV1:
    """A total Value / NeverSuppresses authenticated protocol-resource member."""
    return _base_ref(
        use_site,
        signature=ImportSignatureV2(()),
        semantics=ProtocolResourceSemanticsV1(
            enter=EnterResultContractV1(sort=PrimitiveSort("Value")),
            exit=ExitContractV1(disposition=NeverSuppressesDispositionV1()),
        ),
    )


def _boundary_ref(use_site) -> ContextManagerContractRefV1:
    """An Expects/Raise assertion boundary projecting formal 0 as its type."""
    return _base_ref(
        use_site,
        signature=ImportSignatureV2(
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
        ),
        semantics=EffectBoundarySemanticsV1(
            ExpectsModeV1(),
            RaiseEffectKindV1(),
            FormalArgumentProjectionV1(0),
            OptionalFormalArgumentProjectionV1(1),
            ExceptionInfoBindingV1(),
        ),
    )


def _no_warning_ref(use_site) -> ContextManagerContractRefV1:
    """An inverted warning boundary: literal None means no warning may arrive."""
    return _base_ref(
        use_site,
        signature=ImportSignatureV2(
            (
                CallParameterV1(
                    "expected_warning",
                    PrimitiveSort("Value"),
                    PositionalOrKeywordV1(),
                    True,
                    NoDefaultV1(),
                ),
            )
        ),
        semantics=EffectBoundarySemanticsV1(
            ExpectsModeV1(),
            WarningEffectKindV1(),
            FormalArgumentProjectionV1(0),
            NoMessagePatternV1(),
            WarningObservationBindingV1(),
        ),
    )


HEADER = (
    "from dependency import manager\n" "from pytest import raises as expect_raises\n"
)

RESOURCE_FIRST = HEADER + (
    "def f():\n"
    '    with manager(), expect_raises(ValueError, match="boom"):\n'
    '        raise ValueError("boom")\n'
)

BOUNDARY_FIRST = HEADER + (
    "def f():\n"
    '    with expect_raises(ValueError, match="boom"), manager():\n'
    '        raise ValueError("boom")\n'
)

RESOURCE_ONLY = HEADER + (
    "def f():\n" "    with manager():\n" '        raise ValueError("boom")\n'
)

NO_WARNING_RESOURCE = (
    "from dependency import no_warning, resource, configure, emit\n"
    "def f(warn_category, filter_category):\n"
    "    with no_warning(None), resource():\n"
    '        configure(category=filter_category, action="ignore")\n'
    '        emit("test", category=warn_category)\n'
)

PANDAS_TEST_ERRORS_SOURCE_CID = (
    "blake3-512:e0c0e46661f4028ee20659af69bba7b9f87b047b6b1126491bfd5d5c941119c1"
    "113df8ed9daeb5413832a45b7434689a4768068013d513dc0f634e683b212a33"
)
PANDAS_MANIFEST_CID = (
    "blake3-512:6f317a5a489eb7e730064d79792f0d1656723130603309e2f2ed9cbedb604eda1"
    "c4b77a26dc90c980411292ea3994af9015da4cd850b5a307af5a4998b563530"
)


def _mixed_sugar(tmp_path, source: str, *, refs):
    """Construct ``f``'s sugar, resolving each With item by ``refs`` position.

    ``refs`` is a per-item-index factory tuple, so a site can be authenticated
    as resource-then-boundary or boundary-then-resource without any manager
    spelling reaching production.
    """
    source_file = _mixed_source_file(tmp_path, source, refs=refs)
    return next(source_file.functions()).sugar()


def _mixed_source_file(tmp_path, source: str, *, refs):
    """Build the same native site while retaining its per-item resolution table."""
    path = tmp_path / "mixed_resolution.py"
    path.write_text(source, encoding="utf-8")
    identity = path_source(str(path))
    probe = SourceFile(identity)
    with_node = next(node for node in probe.nodes() if node.kind == "With")
    rows = {}
    for index, item in enumerate(with_node.items):
        coordinate = _coordinate(item.context_expr)
        rows[coordinate] = refs[index](coordinate)
    context = TreeConstructionContextV1(
        ResolvedContractRefsV1(_cid("c"), _cid("t"), MappingProxyType(rows))
    )
    return SourceFile(identity, construction_context=context)


def _with_chain(sugar):
    """Outermost-first chain of With routers reachable from a function sugar."""
    chain = []

    def walk(node):
        if isinstance(node, (WithResourceSugar, WithEffectBoundarySugar)):
            chain.append(node)
            for child in node.body:
                walk(child)
            return
        for field in ("body", "statements", "entries"):
            for child in getattr(node, field, ()) or ():
                walk(child)

    walk(sugar)
    return chain


class _Record(Sugar):
    """A completed body carrying the producer entries selected by a twin."""

    def __init__(self, entries):
        self.entries = tuple(entries)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        del ctx
        return Complete(BlockValue(self.entries))


def _mixed_no_warning_sugar(tmp_path, *, entries=()):
    """Construct the native two-item spelling, then select its body testimony."""
    outer, inner = _with_chain(
        _mixed_sugar(
            tmp_path,
            NO_WARNING_RESOURCE,
            refs=(_no_warning_ref, _resource_ref),
        )
    )
    routed_inner = replace(inner, body=(_Record(entries),))
    return replace(outer, body=(routed_inner,)), routed_inner


# ------------------------------------------------- LAW: both contracts retained


def test_mixed_site_retains_both_contracts(tmp_path):
    """LAW: one resource router AND one boundary router — exact cardinality.

    ``!= 1`` is satisfied by 0 and by 2, so each participant is counted
    exactly, not merely asserted present.
    """
    chain = _with_chain(
        _mixed_sugar(tmp_path, RESOURCE_FIRST, refs=(_resource_ref, _boundary_ref))
    )
    resources = [n for n in chain if isinstance(n, WithResourceSugar)]
    boundaries = [n for n in chain if isinstance(n, WithEffectBoundarySugar)]
    assert len(chain) == 2, f"mixed site must build two routers, got {len(chain)}"
    assert len(resources) == 1, "the resource participant was erased or duplicated"
    assert len(boundaries) == 1, "the assertion participant was erased or duplicated"


def test_discrimination_mixed_site_is_not_two_resource_routers(tmp_path):
    """BITE: 'any resource participant means resource routing' would make the
    boundary count 0 and the resource count 2. Assert that and show it fails."""
    chain = _with_chain(
        _mixed_sugar(tmp_path, RESOURCE_FIRST, refs=(_resource_ref, _boundary_ref))
    )
    resources = [n for n in chain if isinstance(n, WithResourceSugar)]
    with pytest.raises(AssertionError):
        assert len(resources) == 2, "resource-wins routing would build two resources"


def test_discrimination_mixed_site_is_not_two_boundary_routers(tmp_path):
    """BITE: the symmetric erasure — boundary-wins routing — also fails."""
    chain = _with_chain(
        _mixed_sugar(tmp_path, RESOURCE_FIRST, refs=(_resource_ref, _boundary_ref))
    )
    boundaries = [n for n in chain if isinstance(n, WithEffectBoundarySugar)]
    with pytest.raises(AssertionError):
        assert len(boundaries) == 2, "boundary-wins routing would build two boundaries"


# ------------------------------------------------- LAW: order is source order


def test_resource_first_puts_the_resource_outside(tmp_path):
    """LAW: the FIRST source manager is the OUTER node — so its ``__exit__``
    runs LAST. Python's reverse exit order, inherited from the nesting."""
    outer, inner = _with_chain(
        _mixed_sugar(tmp_path, RESOURCE_FIRST, refs=(_resource_ref, _boundary_ref))
    )
    assert isinstance(outer, WithResourceSugar)
    assert isinstance(inner, WithEffectBoundarySugar)
    assert inner in outer.body


def test_boundary_first_puts_the_boundary_outside(tmp_path):
    """LAW: same site, swapped source order, swapped nesting — both retained."""
    outer, inner = _with_chain(
        _mixed_sugar(tmp_path, BOUNDARY_FIRST, refs=(_boundary_ref, _resource_ref))
    )
    assert isinstance(outer, WithEffectBoundarySugar)
    assert isinstance(inner, WithResourceSugar)
    assert inner in outer.body


def test_discrimination_nesting_order_is_not_contract_kind(tmp_path):
    """BITE: nesting follows SOURCE order, not a preference for one contract.

    If the router picked an order by contract kind, the two spellings above
    would produce the same outer type. Assert that and show it fails."""
    resource_first_outer = _with_chain(
        _mixed_sugar(tmp_path, RESOURCE_FIRST, refs=(_resource_ref, _boundary_ref))
    )[0]
    boundary_first_outer = _with_chain(
        _mixed_sugar(tmp_path, BOUNDARY_FIRST, refs=(_boundary_ref, _resource_ref))
    )[0]
    with pytest.raises(AssertionError):
        assert type(resource_first_outer) is type(boundary_first_outer)


# --------------------------------- LAW: the assertion participant still decides


def test_inner_boundary_still_consumes_its_matching_halt(tmp_path):
    """LAW: nesting under a resource does not disarm the assertion contract.

    The body raises exactly what the inner boundary expects, so the boundary
    consumes that halt and its face completes — the same verdict it would give
    standing alone."""
    outer, inner = _with_chain(
        _mixed_sugar(tmp_path, RESOURCE_FIRST, refs=(_resource_ref, _boundary_ref))
    )
    faces = inner.desugar().exits
    assert len(faces) == 1
    assert isinstance(faces[0], Completed), "the boundary must consume its own halt"
    del outer


def test_discrimination_a_nonmatching_halt_is_not_consumed(tmp_path):
    """BITE: the completion above comes from the MATCH, not from nesting."""
    source = HEADER + (
        "def f():\n"
        '    with manager(), expect_raises(ValueError, match="boom"):\n'
        '        raise TypeError("boom")\n'
    )
    _outer, inner = _with_chain(
        _mixed_sugar(tmp_path, source, refs=(_resource_ref, _boundary_ref))
    )
    faces = inner.desugar().exits
    assert len(faces) == 1
    assert isinstance(faces[0], Halted), "a mismatched halt must stay outgoing"


# ----------------------------------- LAW: the resource participant still routes


def test_outer_resource_runs_its_exit_on_the_halted_edge(tmp_path):
    """LAW: E1 — the resource ``__exit__`` runs on EVERY outgoing body edge.

    The inner boundary is made to leave a halt outgoing (mismatched raise); the
    outer resource must still route that halted edge through its own exit and,
    under NeverSuppresses, restore it."""
    source = HEADER + (
        "def f():\n"
        '    with manager(), expect_raises(ValueError, match="boom"):\n'
        '        raise TypeError("boom")\n'
    )
    outer, _inner = _with_chain(
        _mixed_sugar(tmp_path, source, refs=(_resource_ref, _boundary_ref))
    )
    reds = _outgoing_halts(outer.desugar())
    assert len(reds) == 1, f"expected exactly one restored halt, got {len(reds)}"
    assert reds[0].effect.exception_name == "TypeError"


def test_discrimination_a_matched_halt_leaves_no_outgoing_halt(tmp_path):
    """BITE: the halt above survives because the BOUNDARY did not consume it.

    With the matching raise, the boundary consumes and the same resource
    routing produces no outgoing halt — so the assertion above is reading the
    boundary's verdict, not an unconditional property of the resource."""
    outer, _inner = _with_chain(
        _mixed_sugar(tmp_path, RESOURCE_FIRST, refs=(_resource_ref, _boundary_ref))
    )
    reds = _outgoing_halts(outer.desugar())
    with pytest.raises(AssertionError):
        assert reds, "a consumed halt must not still be outgoing"


def _outgoing_halts(outcome):
    """The typed red effects the routed site still emits, in linear view.

    ``WithResourceSugar.desugar`` returns the collapsed linear ``Outcome``, so
    a restored halt rides as an ``Incomplete`` entry of the block, not as an
    ``ExitSet`` arm. Read it where it lives; re-projecting the ``Complete``
    through ``sugar_outcome_to_exitset`` would manufacture a single completed
    arm and hide every red the block carries.
    """
    from sugar_lift_py_tests.outcome import Incomplete

    return [e for e in outcome.value.contribution() if isinstance(e, Incomplete)]


# ------------------------- LAW: a routed inner block reduces inside the outer


def test_consumed_inner_boundary_routes_through_the_outer_block_reduction(tmp_path):
    """LAW: the outer resource reduces an inner ROUTED BLOCK, not a floor value.

    When the inner boundary consumes its halt, its completed face carries the
    inner block's own reduced state. The outer resource's block reducer must
    splice that block's entries onto its prefix. Before #6325's sibling fix
    this path raised a bare ``AttributeError``
    (``'_ReducedBlock' object has no attribute 'contribution'``) from
    ``function_universe_sugar.project`` — an untyped crash escape on exactly
    the mixed resource/assertion site this file exists to pin.
    """
    outer, _inner = _with_chain(
        _mixed_sugar(tmp_path, RESOURCE_FIRST, refs=(_resource_ref, _boundary_ref))
    )
    outcome = outer.desugar()
    assert _outgoing_halts(outcome) == [], "the boundary consumed its own halt"
    assert outcome.value.contribution(), "the routed site must still emit testimony"


def test_discrimination_the_same_reduction_carries_a_surviving_halt(tmp_path):
    """BITE: the reduction above is real routing, not an empty success path."""
    source = HEADER + (
        "def f():\n"
        '    with manager(), expect_raises(ValueError, match="boom"):\n'
        '        raise TypeError("boom")\n'
    )
    outer, _inner = _with_chain(
        _mixed_sugar(tmp_path, source, refs=(_resource_ref, _boundary_ref))
    )
    with pytest.raises(AssertionError):
        assert _outgoing_halts(outer.desugar()) == []


# ---------------------------------------------- LAW: the mix is not degenerate


def test_discrimination_single_manager_site_builds_one_router(tmp_path):
    """BITE: the two-router count above is caused by the MIX, not by the walk."""
    chain = _with_chain(_mixed_sugar(tmp_path, RESOURCE_ONLY, refs=(_resource_ref,)))
    assert len(chain) == 1
    assert isinstance(chain[0], WithResourceSugar)


# ------------------ LAW: inverted warning assertion + resource juxtaposition


def test_authenticated_pandas_303_site_has_two_independent_manager_items():
    """The concrete reproducer is the canonical corpus site, not a path guess."""
    corpus = authenticated_pandas_corpus()
    assert (corpus.version, corpus.manifest_cid, corpus.file_count) == (
        "3.0.3",
        PANDAS_MANIFEST_CID,
        1421,
    )
    path = corpus.root / "tests/test_errors.py"
    assert blake3_512_of(path.read_bytes()) == PANDAS_TEST_ERRORS_SOURCE_CID
    tree = open_source_file_for_construction(
        path,
        root=corpus.root.parent,
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
        populate_derived=False,
    )
    site = next(
        node
        for node in tree.nodes()
        if node.kind == "With" and node.line_col_span().start_line == 142
    )

    assert len(site.items) == 2
    assert [item.context_expr.kind for item in site.items] == ["Call", "Call"]
    assert [item.context_expr.func.kind for item in site.items] == [
        "Attribute",
        "Attribute",
    ]
    assert [
        (
            item.context_expr.line_col_span().start_line,
            item.context_expr.line_col_span().start_col,
            item.context_expr.line_col_span().end_col,
        )
        for item in site.items
    ] == [(142, 9, 41), (142, 43, 68)]


def test_mixed_site_reads_one_resolution_per_item_coordinate(tmp_path):
    """Truthful twin: later resource testimony cannot inherit item zero's law."""
    source_file = _mixed_source_file(
        tmp_path,
        NO_WARNING_RESOURCE,
        refs=(_no_warning_ref, _resource_ref),
    )
    site = next(node for node in source_file.nodes() if node.kind == "With")
    resolutions = [site._prebound_manager_resolution(item) for item in site.items]

    assert len(resolutions) == 2
    assert isinstance(resolutions[0], ContextManagerContractRefV1)
    assert isinstance(resolutions[0].semantics, EffectBoundarySemanticsV1)
    assert isinstance(resolutions[0].semantics.effect_kind, WarningEffectKindV1)
    assert isinstance(resolutions[1], ContextManagerContractRefV1)
    assert isinstance(resolutions[1].semantics, ProtocolResourceSemanticsV1)


def test_later_incompatible_resolution_is_not_painted_from_item_zero(tmp_path):
    """Load-bearing lying twin: first-item painting fails this exact assertion."""
    source_file = _mixed_source_file(
        tmp_path,
        NO_WARNING_RESOURCE,
        refs=(_no_warning_ref, _resource_ref),
    )
    site = next(node for node in source_file.nodes() if node.kind == "With")
    first = site._require_narrow_cm_ref(site.items[0])
    later = site._require_narrow_cm_ref(site.items[1])

    assert isinstance(first.semantics, EffectBoundarySemanticsV1)
    assert isinstance(first.semantics.effect_kind, WarningEffectKindV1)
    assert isinstance(later.semantics, ProtocolResourceSemanticsV1)
    assert type(first.semantics) is not type(later.semantics)
    outer, inner = _with_chain(next(source_file.functions()).sugar())
    assert isinstance(outer, WithEffectBoundarySugar)
    assert isinstance(inner, WithResourceSugar)


def test_undecided_later_item_stays_named_and_does_not_contaminate_sibling(
    tmp_path,
):
    """UNDECIDED is typed testimony at item one, never False or item zero's ref."""

    def undecided(use_site):
        return ContextManagerResolutionGapV1(
            demand_cid=_cid("d"),
            use_site=use_site,
            target_symbol=None,
            kind="runtime-selected",
            candidate_member_cids=(),
            detail="later manager remains source-undecided",
        )

    source_file = _mixed_source_file(
        tmp_path,
        NO_WARNING_RESOURCE,
        refs=(_no_warning_ref, undecided),
    )
    site = next(node for node in source_file.nodes() if node.kind == "With")
    first = site._prebound_manager_resolution(site.items[0])
    later = site._prebound_manager_resolution(site.items[1])

    assert isinstance(first, ContextManagerContractRefV1)
    assert isinstance(first.semantics, EffectBoundarySemanticsV1)
    assert isinstance(first.semantics.effect_kind, WarningEffectKindV1)
    assert isinstance(later, ContextManagerResolutionGapV1)
    assert later.kind == "runtime-selected"
    assert later.detail == "later manager remains source-undecided"
    assert later.use_site == _coordinate(site.items[1].context_expr)
    assert later.use_site != first.use_site

    with pytest.raises(SugarNotWritten) as caught:
        next(source_file.functions()).sugar()
    assert caught.value.kind == "runtime-selected"
    assert caught.value.coordinate == later.use_site


def test_each_mixed_item_keeps_its_own_runtime_outcome(tmp_path):
    """The inner resource completes while the outer no-warning contract fails."""
    warning = WarningObservationValue(WarningEffect("computed-warning"))
    outer, inner = _mixed_no_warning_sugar(tmp_path, entries=(warning,))

    inner_outcome = inner.desugar()
    outer_outcome = outer.desugar()
    assert isinstance(inner_outcome, Complete)
    assert len(outer_outcome.exits) == 1
    assert isinstance(outer_outcome.exits[0], Halted)
    assert isinstance(outer_outcome.exits[0].effect, ExpectationNotMetEffect)


def test_no_warning_resource_site_retains_both_routers_in_source_order(tmp_path):
    outer, inner = _mixed_no_warning_sugar(tmp_path)

    assert isinstance(outer, WithEffectBoundarySugar)
    assert isinstance(inner, WithResourceSugar)
    assert outer.body == (inner,)


def test_no_warning_expected_operand_remains_literal_none(tmp_path):
    outer, _inner = _mixed_no_warning_sugar(tmp_path)

    manager = outer.manager.desugar(None)
    assert isinstance(manager, Complete)
    assert len(manager.value.arg_values) == 1
    assert isinstance(manager.value.arg_values[0], NoneValue)


def test_parametrized_warning_classes_survive_native_multi_item_construction(
    tmp_path,
):
    path = tmp_path / "computed_categories.py"
    path.write_text(NO_WARNING_RESOURCE, encoding="utf-8")
    source = SourceFile(path_source(str(path)))
    with_node = next(node for node in source.nodes() if node.kind == "With")

    assert len(with_node.items) == 2
    calls = [node for node in with_node.body if node.kind == "Expr"]
    assert [call.value.keywords[0].value.id for call in calls] == [
        "filter_category",
        "warn_category",
    ]


def test_clean_inner_resource_satisfies_inverted_warning_boundary(tmp_path):
    outer, _inner = _mixed_no_warning_sugar(tmp_path)

    routed = outer.desugar()
    assert len(routed.exits) == 1
    assert isinstance(routed.exits[0], Completed)


def test_warning_arriving_through_inner_resource_fails_inverted_boundary(tmp_path):
    warning = WarningObservationValue(WarningEffect("computed-warning"))
    outer, _inner = _mixed_no_warning_sugar(tmp_path, entries=(warning,))

    routed = outer.desugar()
    assert len(routed.exits) == 1
    face = routed.exits[0]
    assert isinstance(face, Halted)
    assert isinstance(face.effect, ExpectationNotMetEffect)


def test_lying_warning_arrival_cannot_be_reported_as_clean_completion(tmp_path):
    warning = WarningObservationValue(WarningEffect("computed-warning"))
    outer, _inner = _mixed_no_warning_sugar(tmp_path, entries=(warning,))

    with pytest.raises(AssertionError):
        assert isinstance(outer.desugar().exits[0], Completed)
