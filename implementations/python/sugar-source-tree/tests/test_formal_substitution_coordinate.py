"""Twins for the formal-substitution authority boundary.

Governing law
-------------
Formal substitution replaces the value associated with an *authenticated
binding coordinate* while preserving that coordinate's source/rewrite
occurrence identity.  It never falls back to a route-time name map and it
never reconstructs sugar or the AST.

The single door is ``BindingCoordinateRefSugar.desugar``: it reads the
coordinate CID out of the reducing ``TemporalContext`` and returns the exact
constructed actual, or it panics.  Every twin below either exercises that door
or shows its discrimination arm biting when the coordinate identity is
perturbed.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from sugar_lift_py_tests.context_manager_resolution import (
    OpaqueSourceCallObligationV1,
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.floor import (
    BlockValue,
    CallSiteValue,
    InvValue,
    ReturnValue,
    TermValue,
)
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.source_call_frame import SourceCallBindingGap
from sugar_lift_py_tests.sugar.binding_coordinate_ref_sugar import (
    BindingCoordinateRefSugar,
)
from sugar_lift_py_tests.sugar.call_site_sugar import CallSiteSugar
from sugar_lift_py_tests.sugar.starred_sugar import StarredSugar
from sugar_lift_py_tests.temporal import TemporalContext
from sugar_source_tree.nodes import Call, FunctionDef
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _source_file(source: str, *, context=None) -> SourceFile:
    from sugar_lift_python_source.canonical import blake3_512_of

    return SourceFile(
        (source, "renamed_fixture.py", blake3_512_of(source.encode("utf-8"))),
        construction_context=context,
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


def _tree(source: str):
    """Parse, and return (context, {name: FunctionDef}, [Call, ...])."""
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = _source_file(source, context=context)
    functions = {
        node.name: node for node in tree.nodes() if isinstance(node, FunctionDef)
    }
    calls = [node for node in tree.nodes() if isinstance(node, Call)]
    return context, functions, calls


def _install(context, call, function):
    frame = function.source_visible_call_frame()
    context.source_call_frames[_coordinate(call)] = frame
    return frame


def _coordinate_refs(sugar) -> list[BindingCoordinateRefSugar]:
    """Every BindingCoordinateRefSugar reachable in a constructed body."""
    found: list[BindingCoordinateRefSugar] = []
    seen: set[int] = set()

    def walk(node) -> None:
        if id(node) in seen:
            return
        seen.add(id(node))
        if isinstance(node, BindingCoordinateRefSugar):
            found.append(node)
        for field in getattr(node, "__dataclass_fields__", {}):
            value = getattr(node, field, None)
            if hasattr(value, "__dataclass_fields__"):
                walk(value)
            elif isinstance(value, tuple):
                for item in value:
                    if hasattr(item, "__dataclass_fields__"):
                        walk(item)

    walk(sugar)
    return found


class _ReduceCtx:
    """The minimum shape ``BindingCoordinateRefSugar.desugar`` reads."""

    def __init__(self, temporal: TemporalContext) -> None:
        self.temporal = temporal


# ---------------------------------------------------------------------------
# 0. Opaque source calls refuse only at their reached coordinate.
# ---------------------------------------------------------------------------


def test_opaque_source_call_obligation_precedes_spread_selection() -> None:
    context, _, calls = _tree("func(*[1], **{})\nordinary(2)\n")
    opaque_call, ordinary_call = calls
    coordinate = _coordinate(opaque_call)
    obligation = OpaqueSourceCallObligationV1(
        coordinate,
        "func",
        "blake3-512:" + "c" * 128,
    )
    context.opaque_source_call_obligations[coordinate] = obligation

    opaque = opaque_call.sugar()

    assert isinstance(opaque, CallSiteSugar)
    assert isinstance(opaque.args[0], StarredSugar)
    opaque.args[0].to_term(owner="authenticated opaque spread")
    with pytest.raises(
        TypeError,
        match="requires an authenticated source occurrence for StarredSugar",
    ):
        replace(opaque.args[0], site=object()).to_term(owner="foreign spread")
    assert opaque.contract_resolution_gap == "opaque-call-target:func"
    with pytest.raises(SugarNotWritten) as raised:
        opaque.desugar()
    assert raised.value.observed == "opaque-call-target:func"
    assert context.opaque_source_call_obligations[coordinate] is obligation

    ordinary = ordinary_call.sugar()
    assert isinstance(ordinary, CallSiteSugar)
    assert ordinary.contract_resolution_gap is None


# ---------------------------------------------------------------------------
# 1. The same formal coordinate substitutes the supplied actual.
# ---------------------------------------------------------------------------


def test_same_formal_coordinate_substitutes_the_supplied_actual() -> None:
    context, functions, calls = _tree(
        "def identity_formal(value):\n" "    return value\n\n" "identity_formal(7)\n"
    )
    frame = _install(context, calls[-1], functions["identity_formal"])

    constructed = (
        calls[-1]
        .sugar()
        .desugar()
        .value.force_floor(None, owner="same-coordinate", project_callsite=False)
    )

    assert isinstance(constructed, BlockValue)
    assert constructed.statements[0].value == TermValue(7)
    assert len(frame.formal_coordinates) == 1

    # Discrimination: the *same* body with that coordinate unbound is loud.
    ref = _coordinate_refs(frame.body)[0]
    with pytest.raises(SugarNotWritten):
        ref.desugar(_ReduceCtx(TemporalContext.empty()))


# ---------------------------------------------------------------------------
# 2. Different formal coordinates with the same name do not alias.
# ---------------------------------------------------------------------------


def test_distinct_formals_sharing_a_name_never_alias() -> None:
    _context, functions, _calls = _tree(
        "def outer_alpha(value):\n"
        "    return value\n\n"
        "def outer_beta(value):\n"
        "    return value\n\n"
        "outer_alpha(7)\n"
        "outer_beta(9)\n"
    )
    alpha = functions["outer_alpha"].source_visible_call_frame()
    beta = functions["outer_beta"].source_visible_call_frame()

    assert alpha.parameters == beta.parameters == ("value",)
    assert alpha.formal_coordinates[0].cid != beta.formal_coordinates[0].cid

    alpha_ref = _coordinate_refs(alpha.body)[0]
    bound = TemporalContext.empty().bind_value(
        alpha.formal_coordinates[0].cid, TermValue(7)
    )
    assert alpha_ref.desugar(_ReduceCtx(bound)).value == TermValue(7)

    # Discrimination: binding the *other* coordinate of the same name does not
    # satisfy this read.  A name map would have resolved it; the coordinate
    # door stays loud.
    aliased = TemporalContext.empty().bind_value(
        beta.formal_coordinates[0].cid, TermValue(9)
    )
    with pytest.raises(SugarNotWritten):
        alpha_ref.desugar(_ReduceCtx(aliased))


# ---------------------------------------------------------------------------
# 3. No route-time name map exists behind the coordinate door.
# ---------------------------------------------------------------------------


def test_no_name_based_fallback_behind_the_coordinate_door() -> None:
    _context, functions, _calls = _tree(
        "def identity_formal(value):\n" "    return value\n\n" "identity_formal(7)\n"
    )
    frame = functions["identity_formal"].source_visible_call_frame()
    ref = _coordinate_refs(frame.body)[0]

    # The declared *name* is bound, and bound to a value that would be an
    # attractive answer.  The door must not take it.
    by_name = TemporalContext.empty().bind_value("value", TermValue(42))
    with pytest.raises(SugarNotWritten):
        ref.desugar(_ReduceCtx(by_name))

    # Discrimination: the identical context plus the coordinate CID resolves.
    by_coordinate = by_name.bind_value(ref.coordinate.cid, TermValue(7))
    assert ref.desugar(_ReduceCtx(by_coordinate)).value == TermValue(7)

    # And the door could not build a name map even if it wanted one: the
    # authenticated coordinate carries scope owner, binding site, and
    # projection path — no identifier.  A name-keyed route has nothing to key.
    fields = set(type(ref.coordinate).__dataclass_fields__)
    assert fields == {
        "scope_owner_cid",
        "binding_site",
        "projection_path",
        "cid",
        "_interned",
    }
    assert not any("name" in field for field in fields)


# ---------------------------------------------------------------------------
# 4. Substitution reuses the authenticated actual; it reconstructs nothing.
# ---------------------------------------------------------------------------


def test_substitution_reuses_the_actual_and_reconstructs_no_sugar() -> None:
    _context, functions, _calls = _tree(
        "def identity_formal(value):\n" "    return value\n\n" "identity_formal(7)\n"
    )
    frame = functions["identity_formal"].source_visible_call_frame()
    ref = _coordinate_refs(frame.body)[0]

    actual = TermValue(7)
    bound = TemporalContext.empty().bind_value(ref.coordinate.cid, actual)
    outcome = ref.desugar(_ReduceCtx(bound))

    # The exact constructed object comes back — not an equal rebuild, and
    # certainly not a re-parse of consumer syntax.
    assert outcome.value is actual

    # Discrimination: an equal-but-distinct value is a distinguishable object,
    # so the identity assertion above is not vacuous.
    twin = TermValue(7)
    assert twin == actual
    assert twin is not actual
    assert ref.desugar(_ReduceCtx(bound)).value is not twin


# ---------------------------------------------------------------------------
# 5. A shadowed inner formal does not consume the outer binding.
# ---------------------------------------------------------------------------


def test_shadowed_inner_formal_does_not_consume_the_outer_binding() -> None:
    context, functions, calls = _tree(
        "def shadow_outer(value):\n"
        "    def shadow_inner(value):\n"
        "        return value\n"
        "    return shadow_inner(99)\n\n"
        "shadow_outer(7)\n"
    )
    outer = functions["shadow_outer"].source_visible_call_frame()
    inner = functions["shadow_inner"].source_visible_call_frame()

    assert outer.parameters == inner.parameters == ("value",)
    assert outer.formal_coordinates[0].cid != inner.formal_coordinates[0].cid

    outer_call = calls[-1]
    context.source_call_frames[_coordinate(outer_call)] = outer
    constructed = (
        outer_call.sugar()
        .desugar()
        .value.force_floor(None, owner="shadowing", project_callsite=False)
    )

    # The outer actual 7 is bound at the outer coordinate only.  The inner
    # `value` read is never answered with it.
    rendered = repr(constructed)
    assert "shadow_inner" in rendered
    assert "TermValue(value=7)" not in rendered

    # Discrimination: the inner formal read stays under the *inner* coordinate,
    # and binding the outer coordinate does not satisfy it.
    inner_ref = _coordinate_refs(inner.body)[0]
    outer_bound = TemporalContext.empty().bind_value(
        outer.formal_coordinates[0].cid, TermValue(7)
    )
    with pytest.raises(SugarNotWritten):
        inner_ref.desugar(_ReduceCtx(outer_bound))


# ---------------------------------------------------------------------------
# 6. Repeated reference to one formal keeps one coordinate and one value.
# ---------------------------------------------------------------------------


def test_repeated_formal_reads_share_one_coordinate_and_one_value() -> None:
    context, functions, calls = _tree(
        "def repeat_formal(value):\n"
        "    return value + value\n\n"
        "repeat_formal(7)\n"
    )
    frame = _install(context, calls[-1], functions["repeat_formal"])

    # Both reads of `value` intern to the one coordinate ref: the body holds a
    # single authenticated coordinate, not one resolved name per occurrence.
    refs = _coordinate_refs(frame.body)
    assert len(refs) == 1
    assert len({ref.coordinate.cid for ref in refs}) == 1

    constructed = (
        calls[-1]
        .sugar()
        .desugar()
        .value.force_floor(None, owner="repeated-read", project_callsite=False)
    )
    assert constructed.statements[0].value == TermValue(14)

    # Discrimination: a different actual moves both reads together — the two
    # occurrences are one coordinate, never two independently resolved names.
    context2, functions2, calls2 = _tree(
        "def repeat_formal(value):\n"
        "    return value + value\n\n"
        "repeat_formal(8)\n"
    )
    _install(context2, calls2[-1], functions2["repeat_formal"])
    other = (
        calls2[-1]
        .sugar()
        .desugar()
        .value.force_floor(None, owner="repeated-read", project_callsite=False)
    )
    assert other.statements[0].value == TermValue(16)


# ---------------------------------------------------------------------------
# 7. Two call occurrences retain distinct call/binding occurrences.
# ---------------------------------------------------------------------------


def test_two_call_occurrences_retain_distinct_occurrences() -> None:
    context, functions, calls = _tree(
        "def outer_alpha(value):\n"
        "    return value\n\n"
        "outer_alpha(7)\n"
        "outer_alpha(11)\n"
    )
    first, second = calls[-2], calls[-1]
    _install(context, first, functions["outer_alpha"])
    _install(context, second, functions["outer_alpha"])

    first_value = first.sugar().desugar().value
    second_value = second.sugar().desugar().value
    assert isinstance(first_value, CallSiteValue)
    assert isinstance(second_value, CallSiteValue)

    # One declaration: one frame identity, one formal coordinate.
    assert first_value.source_call_frame_cid == second_value.source_call_frame_cid
    assert first_value.formal_coordinate_cids == second_value.formal_coordinate_cids

    # Two occurrences: distinct call sites, distinct substituted actuals.
    assert first_value.site != second_value.site
    first_result = first_value.force_floor(
        None, owner="occurrence", project_callsite=False
    )
    second_result = second_value.force_floor(
        None, owner="occurrence", project_callsite=False
    )
    assert first_result.statements[0].value == TermValue(7)
    assert second_result.statements[0].value == TermValue(11)

    # Discrimination: the shared coordinate is not a shared *value* cell.  If
    # occurrence identity collapsed, reducing the second would have rewritten
    # the first.
    replayed = first_value.force_floor(None, owner="occurrence", project_callsite=False)
    assert replayed.statements[0].value == TermValue(7)


# ---------------------------------------------------------------------------
# 8. A missing actual stays typed-loud.
# ---------------------------------------------------------------------------


def test_missing_actual_stays_typed_loud() -> None:
    context, functions, calls = _tree(
        "def needs_two(first, second):\n" "    return first\n\n" "needs_two(7)\n"
    )
    _install(context, calls[-1], functions["needs_two"])

    with pytest.raises(SourceCallBindingGap):
        calls[-1].sugar()

    # Discrimination: the same declaration with the actual supplied constructs.
    context2, functions2, calls2 = _tree(
        "def needs_two(first, second):\n" "    return first\n\n" "needs_two(7, 9)\n"
    )
    _install(context2, calls2[-1], functions2["needs_two"])
    constructed = (
        calls2[-1]
        .sugar()
        .desugar()
        .value.force_floor(None, owner="supplied-actual", project_callsite=False)
    )
    assert constructed.statements[0].value == TermValue(7)


# ---------------------------------------------------------------------------
# 9. Cyclic substitution stays loud.
# ---------------------------------------------------------------------------


def test_cyclic_substitution_stays_loud() -> None:
    context, functions, calls = _tree(
        "def recur(value):\n" "    return recur(value)\n\n" "recur(7)\n"
    )
    _install(context, calls[-1], functions["recur"])

    constructed = (
        calls[-1]
        .sugar()
        .desugar()
        .value.force_floor(None, owner="cyclic", project_callsite=False)
    )
    inner = constructed.statements[0].value
    assert isinstance(inner, CallSiteValue)

    # The recursive edge refused to carry a body, so it cannot be unrolled and
    # it cannot silently answer a formal read.  Forcing it panics.
    assert inner.body is None
    assert inner.formal_coordinate_cids == ()
    with pytest.raises(ConstructionPanic):
        inner.force_floor(None, owner="cyclic-inner", project_callsite=False)

    # Discrimination: the non-recursive twin of the same shape constructs.
    context2, functions2, calls2 = _tree(
        "def base(value):\n"
        "    return value\n\n"
        "def wraps(value):\n"
        "    return base(value)\n\n"
        "wraps(7)\n"
    )
    _install(context2, calls2[-1], functions2["wraps"])
    outer = (
        calls2[-1]
        .sugar()
        .desugar()
        .value.force_floor(None, owner="acyclic", project_callsite=False)
    )
    assert isinstance(outer.statements[0].value, CallSiteValue)
    assert outer.statements[0].value.arg_values == (TermValue(7),)


# ---------------------------------------------------------------------------
# 10. Formulas carry the substituted actual.
# ---------------------------------------------------------------------------


def test_formula_operand_carries_the_substituted_actual() -> None:
    context, functions, calls = _tree(
        "def formula(value):\n"
        "    assert value == 7\n"
        "    return value\n\n"
        "formula(7)\n"
    )
    _install(context, calls[-1], functions["formula"])

    constructed = (
        calls[-1]
        .sugar()
        .desugar()
        .value.force_floor(None, owner="formula", project_callsite=False)
    )
    invariant = constructed.statements[0]
    assert isinstance(invariant, InvValue)
    assert invariant.formula.args[0] == invariant.formula.args[1]
    assert isinstance(constructed.statements[1], ReturnValue)

    # Discrimination: a different actual reaches the same formula slot, so the
    # operand is genuinely the substituted value and not the literal 7 that the
    # comparison already carried.
    context2, functions2, calls2 = _tree(
        "def formula(value):\n"
        "    assert value == 7\n"
        "    return value\n\n"
        "formula(9)\n"
    )
    _install(context2, calls2[-1], functions2["formula"])
    other = (
        calls2[-1]
        .sugar()
        .desugar()
        .value.force_floor(None, owner="formula", project_callsite=False)
    )
    assert other.statements[0].formula.args[0] != other.statements[0].formula.args[1]
