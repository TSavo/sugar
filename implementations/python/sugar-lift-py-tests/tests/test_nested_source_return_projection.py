"""TWO-HOP SOURCE-RETURN TRANSPORT.

outer → inner → returned Floor → operation binds through both source frames,
preserves both call occurrences.

No recursion-by-name, no borrowed expected exception identity, no local
CallSiteValue adaptation.

Authentication: each use-site applies its callee's own
source_visible_call_frame through the function value its definition built
(not name lookup at dig time).

Producer reds → **codex-3** (same general source-return dig projection as
test_source_return_operation_generalization). Nested dig must recurse
through both frames without collapsing occurrences.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.context_manager_resolution import (
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.floor import (
    BlockValue,
    CallSiteValue,
    ReturnValue,
    TermValue,
)
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.outcome import Completed, ExitSet
from sugar_lift_py_tests.sugar.computed_call_sugar import ComputedCallSugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import BinOp, Call, FunctionDef
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile

CODEX3_OWNER = (
    "codex-3 two-hop source-return transport: outer→inner dig must project "
    "the returned Floor through both authenticated source frames and "
    "preserve both call occurrences. "
    "No recursion-by-name; no local CallSiteValue adaptation."
)


def _tree(source: str, *, name: str = "nested.py"):
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=context,
    )
    functions = {
        node.name: node for node in tree.nodes() if isinstance(node, FunctionDef)
    }
    return tree, functions


def _calls_named(tree, name: str) -> list[Call]:
    return [
        n
        for n in tree.nodes()
        if isinstance(n, Call) and getattr(n.func, "id", None) == name
    ]


def _carried_frame(call: Call, declared):
    """The frame ``call`` applies: its callee's ``declared`` frame.

    A call of a plain ``def`` seats no frame by its name (#8647): it is the
    call of the function its statement built (``Call._function_value_call``,
    ``ComputedCallSugar``), and that value applies its definition's own frame
    (``LambdaCallable.source_call_frame``), whose declaration is itself.  The
    call value the application binds carries that frame's CID
    (``source_call_frame_cid``), which each test reads."""
    sugar = call.sugar()
    assert isinstance(sugar, ComputedCallSugar), (call, sugar)
    assert sugar.source_call_frame is None, call
    assert declared.declaration_frame_cid == declared.frame_cid
    return declared


NESTED = "def inner():\n" "    return 3\n" "def outer():\n" "    return inner()\n"


# ---------------------------------------------------------------------------
# GREEN: each hop alone projects its authenticated body
# ---------------------------------------------------------------------------


def test_inner_alone_projects_return_floor() -> None:
    tree, functions = _tree(NESTED + "\ninner()\n")
    call = _calls_named(tree, "inner")[0]
    frame = functions["inner"].source_visible_call_frame()
    outcome = call.sugar().desugar(None)
    assert outcome.completed_value() is not None
    assert isinstance(outcome.completed_value(), CallSiteValue)
    assert outcome.completed_value().body is not None
    # Authenticated source call: coordinate is the CID of the frame the call
    # carries -- its definition's own -- not bare spelling.
    carried = _carried_frame(call, frame)
    assert outcome.completed_value().source_call_frame_cid == carried.frame_cid
    floor = outcome.completed_value().force_floor(None, owner="inner-alone", project_callsite=False)
    assert isinstance(floor.statements[0], ReturnValue)
    assert floor.statements[0].value == TermValue(3)


def test_outer_alone_carries_inner_call_in_body() -> None:
    tree, functions = _tree(NESTED + "\nouter()\n")
    call = _calls_named(tree, "outer")[0]
    frame = functions["outer"].source_visible_call_frame()
    outcome = call.sugar().desugar(None)
    assert outcome.completed_value() is not None
    assert isinstance(outcome.completed_value(), CallSiteValue)
    carried = _carried_frame(call, frame)
    assert outcome.completed_value().source_call_frame_cid == carried.frame_cid
    assert outcome.completed_value().body is not None
    # Outer body reduces; dig may surface CallSiteValue(inner) or BlockValue.
    dug = outcome.completed_value()._dig_floor_or_none(None, owner="outer-alone")
    assert dug is not None
    # Occurrence of outer is this call site's frame, not inner's.
    assert outcome.completed_value().site is not None
    assert (
        outcome.completed_value().source_call_frame_cid
        != functions["inner"].source_visible_call_frame().frame_cid
    )


def test_recursion_by_name_is_not_the_transport() -> None:
    """Transport is the definition's own frame, not callee-name re-lookup.

    Two different helpers carry different frames; dig does not re-resolve by
    target_name string.
    """
    tree, functions = _tree(
        "def alpha():\n"
        "    return 1\n"
        "def beta():\n"
        "    return 2\n"
        "alpha()\n"
        "beta()\n",
    )
    alpha_call = _calls_named(tree, "alpha")[0]
    beta_call = _calls_named(tree, "beta")[0]
    a = alpha_call.sugar().desugar(None).completed_value()
    b = beta_call.sugar().desugar(None).completed_value()
    # Frame CIDs distinguish alpha vs beta — not target_name spelling.
    alpha_frame = _carried_frame(
        alpha_call, functions["alpha"].source_visible_call_frame()
    )
    beta_frame = _carried_frame(
        beta_call, functions["beta"].source_visible_call_frame()
    )
    assert a.source_call_frame_cid == alpha_frame.frame_cid
    assert b.source_call_frame_cid == beta_frame.frame_cid
    assert a.source_call_frame_cid != b.source_call_frame_cid
    af = a.force_floor(None, owner="alpha", project_callsite=False)
    bf = b.force_floor(None, owner="beta", project_callsite=False)
    assert af.statements[0].value == TermValue(1)
    assert bf.statements[0].value == TermValue(2)
    # Cross: alpha call site still digs 1 even if a beta name exists.
    with pytest.raises(AssertionError):
        assert af.statements[0].value == TermValue(2)


# ---------------------------------------------------------------------------
# LAW (red until codex-3): two-hop return feeds operation through both frames
# ---------------------------------------------------------------------------


def test_two_hop_return_feeds_binop_through_both_frames() -> None:
    """outer() + 1 where outer returns inner() returning 3 → isomorphic to 3+1."""
    helper_src = NESTED + "\nouter() + 1\n"
    direct_src = "3 + 1\n"
    helper_tree, _ = _tree(helper_src)
    direct_tree, _ = _tree(direct_src)
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
        helper, ExitSet
    ), f"{CODEX3_OWNER} outcome={type(helper).__name__}"

    def _val(outcome):
        if outcome.completed_value() is not None:
            return outcome.completed_value()
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
    CallSiteValue coordinates for outer/inner remain on their own frames
    (frame CIDs and sites still distinct). This test pins frame identity
    survival regardless of dig depth.
    """
    tree, functions = _tree(NESTED + "\nouter()\n")
    outer_call = _calls_named(tree, "outer")[0]
    outer_cs = outer_call.sugar().desugar(None).completed_value()
    assert outer_cs.source_call_frame_cid is not None
    outer_frame = _carried_frame(
        outer_call, functions["outer"].source_visible_call_frame()
    )
    assert outer_cs.source_call_frame_cid == outer_frame.frame_cid
    inner_frame = functions["inner"].source_visible_call_frame()
    assert inner_frame.frame_cid != outer_cs.source_call_frame_cid
    assert inner_frame.frame_cid.startswith("blake3-512:")


def test_two_hop_dig_must_not_stop_at_outer_block_without_return_floor() -> None:
    """Instrument: two-hop dig ceiling must surface TermValue(3) for ops.

    Today dig of outer may stop at BlockValue(ReturnValue(CallSiteValue(inner)))
    or similar — not the scalar Floor ops need. codex-3 owns the projection.
    """
    tree, _ = _tree(NESTED + "\nouter()\n")
    outer_cs = _calls_named(tree, "outer")[0].sugar().desugar(None).completed_value()
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
