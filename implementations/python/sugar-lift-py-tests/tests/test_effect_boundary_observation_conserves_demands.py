"""Where a consumed observation and a pending caller demand meet on ONE arm.

#6392 gave a pending caller obligation an arm on the completed face: every
face of a partition is downstream of the construction that incurred the
demand, so the demand rides on each face weakened under that face's own guard.

#6391 gave the effect boundary an observation slot: the binding projects the
ROUTED OCCURRENCE and rides the completed arm it belongs to, never a sibling.

Neither PR alone asks what happens when both land on the same arm. This file
does, because getting it wrong in either direction is silent:

- drop the demand while attaching the observation, and an obligation vanishes
  at a conversion boundary where nothing downstream can report it -- the exact
  conservation hole #6358 repaired;
- attach the demand to a sibling arm, and a face owes something it never
  incurred.

The answer these twins pin: the two compose by being INDEPENDENT.
Authenticating an observation slot neither discharges an obligation nor
incurs one, so ``owed`` is threaded unchanged onto whichever arm the verdict
selects, and the observation's facts ride that same arm.
"""

from __future__ import annotations

import types

from sugar_lift_py_tests.caller_parameter_contract import (
    ContractConditionalConstructionV1,
)
from sugar_lift_py_tests.context_manager_contract import (
    AuthenticatedRaiseMatcher,
    EffectBoundaryDisposition,
)
from sugar_lift_py_tests.effect.expectation_not_met_effect import (
    ExpectationNotMetEffect,
)
from sugar_lift_py_tests.floor.inv_value import InvValue
from sugar_lift_py_tests.formal_parameter import FormalParameterCoordinateV1
from sugar_lift_py_tests.ir import PrimitiveSort, atomic, ctor, make_var, num
from sugar_lift_py_tests.outcome.exit_set import (
    Completed,
    ExitSet,
    Halted,
    true_guard,
)

SRC = "blake3-512:" + "b" * 128
SLOT = "observation-slot"


def _demand_entry():
    """One real pending caller obligation: `python:indexable(value)`."""
    owner_def = SourceFragmentCoordinate = __import__(
        "sugar_lift_py_tests.context_manager_resolution",
        fromlist=["SourceFragmentCoordinateV1"],
    ).SourceFragmentCoordinateV1(SRC, 1, 0, 10, 4)
    coordinate = FormalParameterCoordinateV1.mint(
        owner_source_identity_cid=SRC,
        owner_definition_locus=owner_def,
        declaration_locus=SourceFragmentCoordinate,
        ordinal=0,
        parameter_kind="positional-or-keyword",
        declared_name="value",
        sort=PrimitiveSort("Value"),
    )
    span = types.SimpleNamespace(start_line=3, start_col=9, end_line=3, end_col=17)
    site = types.SimpleNamespace(source_cid=SRC, line_col_span=span)
    carrier = ContractConditionalConstructionV1.mint(
        site=site,
        candidate=ctor("py.subscript", [make_var("value"), num(0)]),
        demand_formula=atomic("python:indexable", [make_var("value")]),
        value=None,
        coordinate=coordinate,
    )
    return carrier.demanded_under(true_guard())


def _pre_halt_state():
    """The real pre-effect state a consumed halt is required to carry.

    `EffectBoundaryDisposition` refuses to consume a halt whose pre-halt state
    is absent, because consuming asserts the body reached the raise and stopped
    there. Passing None here would be testing against a fabricated face.
    """
    from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock

    return _ReducedBlock(entries=(), can_fall_through=False, fall_through=())


def _raise_effect(name: str):
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect

    identity = ctor(
        "python:exception_type_identity",
        [__import__("sugar_lift_py_tests.ir", fromlist=["str_const"]).str_const(
            "builtins"
        ), __import__("sugar_lift_py_tests.ir", fromlist=["str_const"]).str_const(name)],
    )
    return RaiseEffect(
        exception_name=name,
        blame=f"{SRC}:3:8",
        exception_type_coordinate=identity,
        exception_type_mro=(identity,),
    )


class _AlwaysMatches:
    """A matcher stand-in: this unit is about arm placement, not matching."""

    def exception_type_identity(self):
        return _raise_effect("ValueError").exception_type_coordinate


def _route(body_exit, *, slot_id):
    """Run one body arm through `and_exit` under an assertion boundary."""
    disposition = EffectBoundaryDisposition(
        matcher=AuthenticatedRaiseMatcher(
            expected=_AlwaysMatches(), message_pattern=None
        ),
        observation_slot_id=slot_id,
        unmet=ExpectationNotMetEffect("raise", None),
    )
    return ExitSet((body_exit,)).and_exit(
        ExitSet.completed(object()), disposition=disposition
    )


def _slot_facts(face):
    state = face.value if isinstance(face, Completed) else face.state
    return tuple(
        entry
        for entry in (getattr(state, "entries", ()) or ())
        if isinstance(entry, InvValue) and "effect_slot" in str(entry.formula)
    )


def _demand_cids(face):
    return tuple(
        demand.demand_cid
        for entry in face.pending_contracts
        for demand in entry.demands
    )


# --- truthful: both survive, on the SAME arm ---------------------------------


def test_consumed_observation_arm_still_owes_the_body_demand():
    """The deciding twin: observation testimony AND the demand, one arm."""
    entry = _demand_entry()
    owed_cids = tuple(demand.demand_cid for demand in entry.demands)
    assert len(owed_cids) == 1

    routed = _route(
        Halted(
            true_guard(),
            _raise_effect("ValueError"),
            _pre_halt_state(),
            pending_contracts=(entry,),
        ),
        slot_id=SLOT,
    )

    assert len(routed.exits) == 1
    face = routed.exits[0]
    # The halt was this boundary's business, so the arm completes ...
    assert isinstance(face, Completed)
    # ... carrying the slot testimony ...
    assert len(_slot_facts(face)) == 3
    # ... and STILL owing exactly what the body incurred. Not one more (a face
    # owing what it never incurred) and not one fewer (a silent drop).
    assert _demand_cids(face) == owed_cids


def test_demand_survives_the_same_arm_without_an_observation_slot():
    """Independence, one direction: no slot, same obligation."""
    entry = _demand_entry()
    owed_cids = tuple(demand.demand_cid for demand in entry.demands)

    routed = _route(
        Halted(
            true_guard(),
            _raise_effect("ValueError"),
            _pre_halt_state(),
            pending_contracts=(entry,),
        ),
        slot_id=None,
    )
    face = routed.exits[0]
    assert isinstance(face, Completed)
    assert _slot_facts(face) == ()
    assert _demand_cids(face) == owed_cids


def test_observation_rides_the_arm_that_owes_nothing_when_nothing_was_incurred():
    """Independence, the other direction: slot without demands stays clean."""
    routed = _route(
        Halted(true_guard(), _raise_effect("ValueError"), _pre_halt_state()),
        slot_id=SLOT,
    )
    face = routed.exits[0]
    assert isinstance(face, Completed)
    assert len(_slot_facts(face)) == 3
    assert _demand_cids(face) == ()


# --- lying: the demand must not follow the observation onto a wrong arm ------


def test_restored_halt_keeps_its_demand_and_gains_no_observation():
    """A nonmatching halt: obligation conserved, slot NOT authenticated.

    The failure this excludes is the demand being treated as something the
    binding carries -- it would then ride only the consumed arm and vanish
    from every restored one.
    """
    entry = _demand_entry()
    owed_cids = tuple(demand.demand_cid for demand in entry.demands)

    routed = _route(
        Halted(
            true_guard(),
            _raise_effect("TypeError"),
            _pre_halt_state(),
            pending_contracts=(entry,),
        ),
        slot_id=SLOT,
    )
    face = routed.exits[0]
    assert isinstance(face, Halted)
    assert _slot_facts(face) == ()
    assert _demand_cids(face) == owed_cids


def test_unmet_expectation_arm_keeps_its_demand_and_gains_no_observation():
    """A body that completed: the demand it incurred is still owed.

    Suppression is not discharge, and neither is an unmet expectation: the
    body ran far enough to incur the obligation before the boundary ruled.
    """
    entry = _demand_entry()
    owed_cids = tuple(demand.demand_cid for demand in entry.demands)

    routed = _route(
        Completed(true_guard(), object(), pending_contracts=(entry,)),
        slot_id=SLOT,
    )
    face = routed.exits[0]
    assert isinstance(face, Halted)
    assert type(face.effect).__name__ == "ExpectationNotMetEffect"
    assert _slot_facts(face) == ()
    assert _demand_cids(face) == owed_cids
