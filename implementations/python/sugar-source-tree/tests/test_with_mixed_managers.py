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
    OptionalFormalArgumentProjectionV1,
    PositionalOrKeywordV1,
    ProtocolResourceSemanticsV1,
    RaiseEffectKindV1,
)
from sugar_lift_py_tests.context_manager_resolution import (
    ContextManagerContractRefV1,
    ImportSignatureV2,
    ResolvedContractRefsV1,
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
    _hash_json,
)
from sugar_lift_py_tests.ir import PrimitiveSort
from sugar_lift_py_tests.outcome.exit_set import Completed, Halted
from sugar_lift_py_tests.sugar.with_effect_boundary_sugar import WithEffectBoundarySugar
from sugar_lift_py_tests.sugar.with_resource_sugar import WithResourceSugar
from sugar_lift_python_source.source_oracle import path_source
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


HEADER = (
    "from dependency import manager\n"
    "from pytest import raises as expect_raises\n"
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
    "def f():\n"
    "    with manager():\n"
    '        raise ValueError("boom")\n'
)


def _mixed_sugar(tmp_path, source: str, *, refs):
    """Construct ``f``'s sugar, resolving each With item by ``refs`` position.

    ``refs`` is a per-item-index factory tuple, so a site can be authenticated
    as resource-then-boundary or boundary-then-resource without any manager
    spelling reaching production.
    """
    path = tmp_path / "mixed.py"
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
    source_file = SourceFile(identity, construction_context=context)
    return next(source_file.functions()).sugar()


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
    chain = _with_chain(
        _mixed_sugar(tmp_path, RESOURCE_ONLY, refs=(_resource_ref,))
    )
    assert len(chain) == 1
    assert isinstance(chain[0], WithResourceSugar)
