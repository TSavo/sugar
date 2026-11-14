"""The opaque-cited manager ref: construction that CARRIES its ignorance.

Ruling #7384. A ``with`` over an off-population manager (``pytest.raises``,
``warnings.catch_warnings``) may construct, but only while carrying an
authenticated statement that its enter/exit semantics are UNCITED.

The load-bearing property is PROPAGATION. Every tooth below that matters is a
tooth about a downstream claim staying UNDISCHARGED. A construct that lets
anything reason as if the manager were transparent is worse than the refusal
it replaced, so each tooth asserts the SPECIFIC face or the SPECIFIC refusal
text -- never merely that something went red.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from sugar_lift_py_tests.context_manager_resolution import (
    ContractRefProtocolError,
    OpaqueCitedContextManagerRefV1,
    OpaqueSourceCallObligationV1,
    SourceFragmentCoordinateV1,
    context_manager_resolution_outcome,
    mint_opaque_cited_context_manager_ref,
    opaque_source_call_roster_of,
)
from sugar_lift_py_tests.effect import (
    ContextManagerEnterRuntimeEffect,
    ContextManagerExitRuntimeEffect,
    RaiseEffect,
)
from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
from sugar_lift_py_tests.ir import ctor, str_const
from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.with_opaque_cited_manager_sugar import (
    WithOpaqueCitedManagerSugar,
)
from sugar_source_tree.binding_state import constructed_value_cid_v2

SOURCE_CID = "blake3-512:" + "aa" * 64
OWNER_CID = "blake3-512:" + "bb" * 64


@dataclass(frozen=True)
class Frag:
    filename: str = "t.py"
    line: int = 10
    col: int = 4
    source_cid: str = SOURCE_CID


@dataclass(frozen=True)
class ManagerSugar(Sugar):
    """A cited manager operand: an opaque call-site term, never a body."""

    name: str = "pytest.raises"

    @classmethod
    def witnesses(cls):
        return None

    def desugar(self, ctx=None):
        return ExitSet.completed(
            SymbolicValue(ctor(f"call:{self.name}", [str_const("ValueError")]))
        )


@dataclass(frozen=True)
class RaisingBody(Sugar):
    """A body statement that halts with an authenticated ValueError."""

    @classmethod
    def witnesses(cls):
        return None

    def desugar(self, ctx=None):
        return ExitSet.halted(
            RaiseEffect(
                exception_type_coordinate=ctor("py.type", [str_const("ValueError")]),
                occurrence="t.py:11:8",
                exception_name="ValueError",
                blame="t.py:11",
            )
        )


def _coordinate(*, line: int = 10) -> SourceFragmentCoordinateV1:
    return SourceFragmentCoordinateV1(SOURCE_CID, line, 4, line, 30)


def _roster(*, kind: str = "call-target-off-population", target: str = "pytest.raises"):
    return opaque_source_call_roster_of(
        OpaqueSourceCallObligationV1(_coordinate(), target, OWNER_CID, kind)
    )


def _ref(**kwargs):
    return mint_opaque_cited_context_manager_ref(roster=_roster(**kwargs))


def _node(body=(), *, site=None, ref=None):
    return WithOpaqueCitedManagerSugar(
        manager=ManagerSugar(),
        body=body,
        contract_ref=ref if ref is not None else _ref(),
        site=site if site is not None else Frag(),
    )


def _faces(node):
    """(completes, [(effect type, guard text)]) for one desugared With.

    The With hands its faces to the enclosing reducer as an ExitSet: a
    ``Completed`` face is the with-statement completing (the suppressed face
    included), and each ``Halted`` face is one way it leaves by an effect.
    """
    from sugar_lift_py_tests.outcome.exit_set import Completed, Halted

    exits = node.desugar()
    rows = [
        (type(face.effect).__name__, str(face.guard))
        for face in exits.exits
        if isinstance(face, Halted)
    ]
    completes = any(isinstance(face, Completed) for face in exits.exits)
    return completes, rows


def _guard_for(rows, effect_name: str) -> str:
    matches = [guard for name, guard in rows if name == effect_name]
    assert matches, f"no {effect_name} face; faces present: {[n for n, _ in rows]}"
    assert len(matches) == 1, f"{effect_name} appears {len(matches)} times"
    return matches[0]


# ---------------------------------------------------------------- propagation


def test_body_halt_leaves_as_both_suppression_faces():
    """THE tooth. A body that raises must NOT be decided either way.

    Suppression belongs to a manager sugar cannot see, so the body's own
    RaiseEffect must survive under the open exit-result coordinate, and the
    suppressed face must survive as fall-through. Losing either one is the
    construct becoming a lie: without the RaiseEffect face sugar claims the
    exception is definitely swallowed; without fall-through it claims the
    exception definitely escapes.
    """
    can_fall_through, rows = _faces(_node((RaisingBody(),)))

    # The suppressed face: the with-statement completes.
    assert can_fall_through is True

    # The NOT-suppressed face: the body's own effect, guarded on the OPEN
    # exit-result coordinate -- not unconditional, not dropped.
    guard = _guard_for(rows, "RaiseEffect")
    assert "python:cm_exit_result" in guard, guard
    assert "python:cm_enter_completed" in guard, guard


def test_enter_may_halt_face_survives():
    """``__enter__`` of a cited manager may raise; the body then never runs."""
    _, rows = _faces(_node((RaisingBody(),)))
    guard = _guard_for(rows, ContextManagerEnterRuntimeEffect.__name__)
    assert "not" in guard and "python:cm_enter_completed" in guard, guard


def test_exit_may_halt_face_survives():
    """``__exit__`` of a cited manager may itself raise, on any body edge."""
    _, rows = _faces(_node((RaisingBody(),)))
    guard = _guard_for(rows, ContextManagerExitRuntimeEffect.__name__)
    assert "not" in guard and "python:cm_exit_completed" in guard, guard


def test_empty_body_still_carries_enter_and_exit_openness():
    """Opacity is a property of the MANAGER, not of what the body happens to do."""
    can_fall_through, rows = _faces(_node(()))
    names = {name for name, _ in rows}
    assert can_fall_through is True
    assert ContextManagerEnterRuntimeEffect.__name__ in names
    assert ContextManagerExitRuntimeEffect.__name__ in names


# ------------------------------------------------------- coordinate identity


def test_two_managers_at_one_site_mint_different_symbols():
    """A coordinate is authenticated by the callee it names.

    ``pytest.raises`` and ``warnings.catch_warnings`` at the same coordinate
    must not share an open symbol, or one manager's unknown would be the
    other's.
    """
    _, raises_rows = _faces(_node(()))
    warnings_node = WithOpaqueCitedManagerSugar(
        manager=ManagerSugar(name="warnings.catch_warnings"),
        body=(),
        contract_ref=_ref(),
        site=Frag(),
    )
    _, warnings_rows = _faces(warnings_node)
    assert _guard_for(raises_rows, ContextManagerEnterRuntimeEffect.__name__) != (
        _guard_for(warnings_rows, ContextManagerEnterRuntimeEffect.__name__)
    )


def test_two_occurrences_mint_different_coordinates():
    """Two textually identical ``with`` sites are two independent unknowns."""
    _, first = _faces(_node(()))
    _, second = _faces(_node((), site=Frag(line=99)))
    assert _guard_for(first, ContextManagerEnterRuntimeEffect.__name__) != (
        _guard_for(second, ContextManagerEnterRuntimeEffect.__name__)
    )


# ------------------------------------------------------------- the ref itself


def test_semantics_refuses_rather_than_answering_none():
    """Asking a cited ref for semantics is the bug; it must be LOUD.

    ``None`` would let a consumer's isinstance chain fall through to a default
    arm and reason as if the manager were transparent.
    """
    with pytest.raises(ContractRefProtocolError) as raised:
        _ref().semantics
    message = str(raised.value)
    assert "cited, not " in message
    assert "materialized" in message
    assert "never substitute" in message


def test_ref_cannot_be_constructed_without_producer_authority():
    """Only the mint door speaks. A hand-built citation is not testimony."""
    with pytest.raises(ContractRefProtocolError) as raised:
        OpaqueCitedContextManagerRefV1(
            _coordinate(), "pytest.raises", _roster(), "blake3-512:cid"
        )
    assert "lacks producer authority" in str(raised.value)


def test_ref_refuses_a_nonproducer_value_of_the_authority_category():
    """Naming the category must not let a caller mint producer testimony."""
    from sugar_lift_py_tests.context_manager_resolution import (
        _OPAQUE_CITED_MANAGER_AUTHORITY,
    )

    ref = _ref()
    clone = object.__new__(OpaqueCitedContextManagerRefV1)
    for name, value in (
        ("use_site", ref.use_site),
        ("target_name", ref.target_name),
        ("roster", ref.roster),
        ("citation_cid", ref.citation_cid),
        ("uncited", ref.uncited),
        ("_authority", type(_OPAQUE_CITED_MANAGER_AUTHORITY)()),
    ):
        object.__setattr__(clone, name, value)
    with pytest.raises(ContractRefProtocolError) as raised:
        clone.__post_init__()
    assert "lacks producer authority" in str(raised.value)


def test_ref_refuses_a_roster_naming_another_call():
    """Citation and roster must name ONE call; cross-wired testimony refuses."""
    from sugar_lift_py_tests.context_manager_resolution import (
        _OPAQUE_CITED_MANAGER_AUTHORITY,
    )

    ref = _ref()
    other = SourceFragmentCoordinateV1(SOURCE_CID, 77, 0, 77, 9)
    clone = object.__new__(OpaqueCitedContextManagerRefV1)
    for name, value in (
        ("use_site", other),
        ("target_name", ref.target_name),
        ("roster", ref.roster),
        ("citation_cid", ref.citation_cid),
        ("uncited", ref.uncited),
        ("_authority", _OPAQUE_CITED_MANAGER_AUTHORITY),
    ):
        object.__setattr__(clone, name, value)
    with pytest.raises(ContractRefProtocolError) as raised:
        clone.__post_init__()
    assert "different call coordinates" in str(raised.value)


def test_node_refuses_a_ref_that_is_not_a_citation():
    """Opacity is never inferred from the absence of a contract."""
    with pytest.raises(ValueError) as raised:
        WithOpaqueCitedManagerSugar(
            manager=ManagerSugar(), body=(), contract_ref=None, site=Frag()
        )
    assert "never inferred from the absence" in str(raised.value)


# ------------------------------------------------------------ census / wire


def test_census_projects_a_third_value_not_constructed_or_unconstructed():
    """Known, unknown and absent each get their own spelling."""
    outcome = context_manager_resolution_outcome(_ref())
    assert outcome == "cited-opaque"
    assert outcome not in {"constructed", "unconstructed"}


def test_context_manager_edge_wire_refuses_a_citation():
    """A citation must not ride the CM edge wire as if it were a contract."""
    from sugar_lift_py_tests.kit_rpc import ContextManagerEdgeDtoV1
    from sugar_lift_py_tests.kit_rpc.context_manager_edge_dto import (
        ContextManagerEdgeTransportError,
    )

    ref = _ref()
    with pytest.raises(ContextManagerEdgeTransportError) as raised:
        ContextManagerEdgeDtoV1.from_resolved(ref, ref.use_site)
    assert "authenticated derived ref" in str(raised.value)


def test_producer_authority_has_a_named_constructed_value_category():
    """The real With seat canonicalizes without inventing a reflected category."""
    assert constructed_value_cid_v2(_node()).startswith("blake3-512:")
