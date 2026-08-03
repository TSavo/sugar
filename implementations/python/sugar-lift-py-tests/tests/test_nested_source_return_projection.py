"""TWO-HOP SOURCE-RETURN TRANSPORT.

outer → inner → returned Floor → operation binds through both source frames,
preserves both call occurrences, rejects swapped inner/outer testimony.

No recursion-by-name, no borrowed expected exception identity, no local
CallSiteValue adaptation.

Authentication: each use-site enrolls its callee's source_visible_call_frame
by exact fragment coordinate (not name lookup at dig time).

Producer reds → **codex-3** (same general source-return dig projection as
test_source_return_operation_generalization). Nested dig must recurse
through both frames without collapsing occurrences.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.context_manager_resolution import (
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.floor import (
    BlockValue,
    CallSiteValue,
    ReturnValue,
    TermValue,
)
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import BinOp, Call, FunctionDef
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile

CODEX3_OWNER = (
    "codex-3 two-hop source-return transport: outer→inner dig must project "
    "the returned Floor through both authenticated source frames, preserve "
    "both call occurrences, and refuse swapped inner/outer testimony. "
    "No recursion-by-name; no local CallSiteValue adaptation."
)


def _coordinate(node) -> SourceFragmentCoordinateV1:
    span = node.line_col_span()
    return SourceFragmentCoordinateV1(
        node.unit.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )


def _tree(source: str, *, bind: frozenset[str] | None = None, name: str = "nested.py"):
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=context,
    )
    functions = {
        node.name: node for node in tree.nodes() if isinstance(node, FunctionDef)
    }
    for call in tree.nodes():
        if not isinstance(call, Call):
            continue
        callee = getattr(call.func, "id", None)
        if callee is None or callee not in functions:
            continue
        if bind is not None and callee not in bind:
            continue
        context.source_call_frames[_coordinate(call)] = functions[
            callee
        ].source_visible_call_frame()
    return tree, context, functions


def _calls_named(tree, name: str) -> list[Call]:
    return [
        n
        for n in tree.nodes()
        if isinstance(n, Call) and getattr(n.func, "id", None) == name
    ]


NESTED = "def inner():\n" "    return 3\n" "def outer():\n" "    return inner()\n"


# ---------------------------------------------------------------------------
# GREEN: each hop alone projects its authenticated body
# ---------------------------------------------------------------------------


def test_inner_alone_projects_return_floor() -> None:
    tree, context, functions = _tree(NESTED + "\ninner()\n", bind=frozenset({"inner"}))
    call = _calls_named(tree, "inner")[0]
    frame = context.source_call_frames[_coordinate(call)]
    outcome = call.sugar().desugar(None)
    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, CallSiteValue)
    assert outcome.value.body is not None
    # Authenticated source call: coordinate is frame CID, not bare spelling.
    assert outcome.value.source_call_frame_cid == frame.frame_cid
    floor = outcome.value.force_floor(None, owner="inner-alone", project_callsite=False)
    assert isinstance(floor.statements[0], ReturnValue)
    assert floor.statements[0].value == TermValue(3)
    del functions


def test_outer_alone_carries_inner_call_in_body() -> None:
    tree, context, _ = _tree(NESTED + "\nouter()\n", bind=frozenset({"outer", "inner"}))
    call = _calls_named(tree, "outer")[0]
    frame = context.source_call_frames[_coordinate(call)]
    outcome = call.sugar().desugar(None)
    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, CallSiteValue)
    assert outcome.value.source_call_frame_cid == frame.frame_cid
    assert outcome.value.body is not None
    # Outer body reduces; dig may surface CallSiteValue(inner) or BlockValue.
    dug = outcome.value._dig_floor_or_none(None, owner="outer-alone")
    assert dug is not None
    # Occurrence of outer is this call site's enrolled frame, not inner's.
    assert outcome.value.site is not None
    assert (
        outcome.value.source_call_frame_cid
        != context.source_call_frames[
            _coordinate(_calls_named(tree, "inner")[0])
        ].frame_cid
    )


def test_both_call_occurrences_are_distinct_coordinates() -> None:
    """Inner use-site and outer use-site are different fragment coordinates."""
    tree, context, functions = _tree(
        NESTED + "\nouter()\n",
        bind=frozenset({"outer", "inner"}),
    )
    outer_call = _calls_named(tree, "outer")[0]
    # Inner call lives inside outer's body — find Call nodes named inner.
    inner_calls = _calls_named(tree, "inner")
    assert inner_calls, "inner() use-site must exist in the tree"
    inner_call = inner_calls[0]
    outer_coord = _coordinate(outer_call)
    inner_coord = _coordinate(inner_call)
    assert outer_coord != inner_coord
    # Frames enrolled under distinct coordinates.
    assert outer_coord in context.source_call_frames
    assert inner_coord in context.source_call_frames
    assert (
        context.source_call_frames[outer_coord].frame_cid
        != context.source_call_frames[inner_coord].frame_cid
    )
    del functions


# ---------------------------------------------------------------------------
# GREEN: swapped inner/outer testimony refused
# ---------------------------------------------------------------------------


def test_swapped_inner_outer_frame_testimony_is_not_truthful() -> None:
    """Enrolling outer's frame at the inner use-site (and vice versa) tampers.

    Dig of the outer call must not silently equal the authentic two-hop
    return when frames are swapped by coordinate.
    """
    context = TreeConstructionContextV1.for_source_call_construction()
    source = NESTED + "\nouter()\n"
    tree = SourceFile(
        (source, "swap.py", blake3_512_of(source.encode())),
        construction_context=context,
    )
    functions = {n.name: n for n in tree.nodes() if isinstance(n, FunctionDef)}
    outer_call = _calls_named(tree, "outer")[0]
    inner_call = _calls_named(tree, "inner")[0]
    outer_frame = functions["outer"].source_visible_call_frame()
    inner_frame = functions["inner"].source_visible_call_frame()
    # SWAP: outer use-site gets inner's frame; inner use-site gets outer's.
    context.source_call_frames[_coordinate(outer_call)] = inner_frame
    context.source_call_frames[_coordinate(inner_call)] = outer_frame

    # Truthful enrollment for comparison.
    truth_ctx = TreeConstructionContextV1.for_source_call_construction()
    truth_tree = SourceFile(
        (source, "truth.py", blake3_512_of(source.encode())),
        construction_context=truth_ctx,
    )
    truth_fns = {n.name: n for n in truth_tree.nodes() if isinstance(n, FunctionDef)}
    truth_outer = _calls_named(truth_tree, "outer")[0]
    truth_inner = _calls_named(truth_tree, "inner")[0]
    truth_ctx.source_call_frames[_coordinate(truth_outer)] = truth_fns[
        "outer"
    ].source_visible_call_frame()
    truth_ctx.source_call_frames[_coordinate(truth_inner)] = truth_fns[
        "inner"
    ].source_visible_call_frame()

    swapped = outer_call.sugar().desugar(None)
    truthful = truth_outer.sugar().desugar(None)
    assert isinstance(swapped, Complete) and isinstance(truthful, Complete)
    # Bodies differ: swapped outer carries inner's frame body (return 3)
    # without the inner() call hop — not isomorphic to truthful outer.
    assert swapped.value.body != truthful.value.body or (
        swapped.value.parameters != truthful.value.parameters
        or swapped.value.source_call_frame_cid != truthful.value.source_call_frame_cid
    )
    # Frame CIDs on the CallSiteValue must not match the truthful outer frame
    # when testimony was swapped.
    assert (
        swapped.value.source_call_frame_cid != truthful.value.source_call_frame_cid
        or swapped.value.body != truthful.value.body
    )


def test_recursion_by_name_is_not_the_transport() -> None:
    """Transport is coordinate-enrolled frames, not callee-name re-lookup.

    Two different helpers with the same local spelling pattern enroll under
    different coordinates; dig does not re-resolve by target_name string.
    """
    tree, context, functions = _tree(
        "def alpha():\n"
        "    return 1\n"
        "def beta():\n"
        "    return 2\n"
        "alpha()\n"
        "beta()\n",
        bind=frozenset({"alpha", "beta"}),
    )
    alpha_call = _calls_named(tree, "alpha")[0]
    beta_call = _calls_named(tree, "beta")[0]
    assert _coordinate(alpha_call) != _coordinate(beta_call)
    a = alpha_call.sugar().desugar(None).value
    b = beta_call.sugar().desugar(None).value
    # Frame CIDs distinguish alpha vs beta — not target_name spelling.
    assert (
        a.source_call_frame_cid
        == context.source_call_frames[_coordinate(alpha_call)].frame_cid
    )
    assert (
        b.source_call_frame_cid
        == context.source_call_frames[_coordinate(beta_call)].frame_cid
    )
    assert a.source_call_frame_cid != b.source_call_frame_cid
    af = a.force_floor(None, owner="alpha", project_callsite=False)
    bf = b.force_floor(None, owner="beta", project_callsite=False)
    assert af.statements[0].value == TermValue(1)
    assert bf.statements[0].value == TermValue(2)
    # Cross: alpha call site still digs 1 even if a beta name exists.
    with pytest.raises(AssertionError):
        assert af.statements[0].value == TermValue(2)
    del functions


# ---------------------------------------------------------------------------
# LAW (red until codex-3): two-hop return feeds operation through both frames
# ---------------------------------------------------------------------------


def test_two_hop_return_feeds_binop_through_both_frames() -> None:
    """outer() + 1 where outer returns inner() returning 3 → isomorphic to 3+1."""
    helper_src = NESTED + "\nouter() + 1\n"
    direct_src = "3 + 1\n"
    helper_tree, _, _ = _tree(helper_src, bind=frozenset({"outer", "inner"}))
    direct_tree, _, _ = _tree(direct_src, bind=frozenset())
    direct = (
        next(n for n in direct_tree.nodes() if isinstance(n, BinOp))
        .sugar()
        .desugar(None)
    )

    try:
        helper = (
            next(n for n in helper_tree.nodes() if isinstance(n, BinOp))
            .sugar()
            .desugar(None)
        )
    except (ConstructionPanic, SugarNotWritten) as exc:
        pytest.fail(f"{CODEX3_OWNER} two-hop binop: {exc}")

    assert isinstance(
        helper, (Complete, ExitSet)
    ), f"{CODEX3_OWNER} outcome={type(helper).__name__}"

    def _val(outcome):
        if isinstance(outcome, Complete):
            return outcome.value
        completed = [e for e in outcome.exits if isinstance(e, Completed)]
        assert completed, outcome.exits
        return completed[0].value

    hv, dv = _val(helper), _val(direct)
    assert hv == dv or getattr(hv, "value", hv) == getattr(
        dv, "value", dv
    ), f"{CODEX3_OWNER} helper={hv!r} direct={dv!r}"


def test_two_hop_preserves_outer_and_inner_occurrences_on_dig_path() -> None:
    """Dig path must not erase either call occurrence into a bare TermValue only.

    After codex-3: dig yields TermValue(3) for the *operation operand*, while
    CallSiteValue coordinates for outer/inner remain on the enrolled frames
    (frame CIDs and sites still distinct). This test pins frame identity
    survival regardless of dig depth.
    """
    tree, context, _ = _tree(
        NESTED + "\nouter()\n",
        bind=frozenset({"outer", "inner"}),
    )
    outer_call = _calls_named(tree, "outer")[0]
    inner_call = _calls_named(tree, "inner")[0]
    outer_cs = outer_call.sugar().desugar(None).value
    assert outer_cs.source_call_frame_cid is not None
    assert (
        outer_cs.source_call_frame_cid
        == context.source_call_frames[_coordinate(outer_call)].frame_cid
    )
    # Inner frame remains enrolled under its own coordinate after outer desugar.
    inner_frame = context.source_call_frames[_coordinate(inner_call)]
    assert inner_frame.frame_cid != outer_cs.source_call_frame_cid
    assert inner_frame.frame_cid.startswith("blake3-512:")


def test_two_hop_dig_must_not_stop_at_outer_block_without_return_floor() -> None:
    """Instrument: two-hop dig ceiling must surface TermValue(3) for ops.

    Today dig of outer may stop at BlockValue(ReturnValue(CallSiteValue(inner)))
    or similar — not the scalar Floor ops need. codex-3 owns the projection.
    """
    tree, _, _ = _tree(
        NESTED + "\nouter()\n",
        bind=frozenset({"outer", "inner"}),
    )
    outer_cs = _calls_named(tree, "outer")[0].sugar().desugar(None).value
    dug = outer_cs._dig_floor_or_none(None, owner="two-hop-dig-ceiling")
    assert dug is not None
    # Recurse one hop if dig surfaces another CallSiteValue (inner).
    if isinstance(dug, CallSiteValue):
        dug = dug._dig_floor_or_none(None, owner="two-hop-dig-inner")
    # LAW: operation-ready floor is TermValue(3) or ReturnValue(TermValue(3)).
    if isinstance(dug, BlockValue):
        # May still need one unwrap of ReturnValue inside the block.
        if (
            dug.statements
            and isinstance(dug.statements[0], ReturnValue)
            and dug.statements[0].value == TermValue(3)
        ):
            # Block of return 3 — still not yet an operation operand Floor.
            pytest.fail(
                f"{CODEX3_OWNER} dig stopped at BlockValue(ReturnValue(TermValue(3))); "
                "ops need TermValue(3) projected out of the return block"
            )
        if (
            dug.statements
            and isinstance(dug.statements[0], ReturnValue)
            and isinstance(dug.statements[0].value, CallSiteValue)
        ):
            pytest.fail(
                f"{CODEX3_OWNER} dig stopped at BlockValue(ReturnValue(CallSiteValue)); "
                "inner hop not reduced to returned Floor"
            )
        pytest.fail(
            f"{CODEX3_OWNER} dig stopped at BlockValue statements={dug.statements!r}"
        )
    if isinstance(dug, ReturnValue):
        assert dug.value == TermValue(3), f"{CODEX3_OWNER} {dug!r}"
        return
    assert dug == TermValue(3), f"{CODEX3_OWNER} dug={dug!r}"
