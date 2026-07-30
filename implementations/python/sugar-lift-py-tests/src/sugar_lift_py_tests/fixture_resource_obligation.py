"""Construction law for resources supplied through a formal parameter.

The source frame contains no acquisition boundary for such a resource.  Its
construction obligation therefore attaches to the formal binding and is
discharged only by constructed-value testimony for the actual bound there.
This type deliberately cannot mint ``__enter__``/``__exit__`` work: doing so
would claim a local manager that the source never contained.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Callable

from sugar_lift_python_source.canonical import cid_of_json
from sugar_source_tree.binding_provenance import BindingCoordinateV1
from sugar_source_tree.binding_state import BindingEntryV1, BindingStateWireGap


class FixtureResourceBindingRefusal(ValueError):
    """A named formal coordinate lacks authenticated actual-value testimony."""

    def __init__(self, coordinate: str, detail: str):
        self.coordinate = coordinate
        self.detail = detail
        super().__init__(
            f"fixture resource binding refused at {coordinate}: {detail}"
        )


@dataclass(frozen=True)
class FixtureSuppliedResourceDischargeV1:
    obligation_cid: str
    formal_coordinate_cid: str
    constructed_value_testimony_cid: str


@dataclass(frozen=True)
class FixtureSuppliedResourceObligationV1:
    """One externally acquired resource owed at one authenticated formal."""

    formal_coordinate_cid: str
    obligation_cid: str
    kind: str = "fixture-supplied-resource-obligation"
    schema_version: str = "1"

    @classmethod
    def mint(
        cls, coordinate: BindingCoordinateV1
    ) -> "FixtureSuppliedResourceObligationV1":
        # Decode the wire before accepting the coordinate.  A stale or invented
        # CID cannot become an obligation merely by occupying this field.
        authenticated = BindingCoordinateV1.decode(coordinate.wire())
        preimage = {
            "kind": "fixture-supplied-resource-obligation",
            "schemaVersion": "1",
            "formalCoordinateCid": authenticated.cid,
        }
        return cls(authenticated.cid, cid_of_json(preimage))

    def discharge(
        self, binding: BindingEntryV1
    ) -> FixtureSuppliedResourceDischargeV1:
        if binding.coordinate.cid != self.formal_coordinate_cid:
            raise FixtureResourceBindingRefusal(
                self.formal_coordinate_cid,
                "formal binding coordinate mismatch: "
                f"observed {binding.coordinate.cid}",
            )
        try:
            testimony = binding.require_constructed_value_testimony()
            # The round trip authenticates the testimony preimage and CID.
            testimony_type = type(testimony)
            testimony_type.decode(testimony.wire())
        except (BindingStateWireGap, ValueError) as gap:
            raise FixtureResourceBindingRefusal(
                self.formal_coordinate_cid, str(gap)
            ) from gap
        return FixtureSuppliedResourceDischargeV1(
            obligation_cid=self.obligation_cid,
            formal_coordinate_cid=self.formal_coordinate_cid,
            constructed_value_testimony_cid=testimony.cid,
        )


class FixtureResourceOutcome(str, Enum):
    AUTHENTICATED_EXCEPTIONAL_EXIT = "authenticated-exceptional-exit"
    NAMED_REFUSAL = "named-refusal"


@dataclass(frozen=True)
class FixtureResourceAttribution:
    coordinate: str
    outcome: FixtureResourceOutcome
    detail: str


def classify_fixture_resource_outcome(
    obligation: FixtureSuppliedResourceObligationV1,
    binding: BindingEntryV1,
    evaluator: Callable[[], object],
) -> FixtureResourceAttribution:
    """Classify one formal-bound resource into the closed two-way result.

    Discharging the binding is necessary but not sufficient.  Satisfaction
    requires a positive authenticated exceptional edge from the evaluated
    body; ordinary or empty completion is a named refusal, never success by
    absence. ConstructionPanic is not a result face and propagates unchanged.
    """
    from sugar_lift_py_tests.no_call_body_attribution import (
        _exceptional_exit_effects,
    )

    try:
        obligation.discharge(binding)
    except FixtureResourceBindingRefusal as refusal:
        return FixtureResourceAttribution(
            refusal.coordinate,
            FixtureResourceOutcome.NAMED_REFUSAL,
            refusal.detail,
        )
    evaluated = evaluator()
    if _exceptional_exit_effects(evaluated):
        return FixtureResourceAttribution(
            obligation.formal_coordinate_cid,
            FixtureResourceOutcome.AUTHENTICATED_EXCEPTIONAL_EXIT,
            type(evaluated).__name__,
        )
    return FixtureResourceAttribution(
        obligation.formal_coordinate_cid,
        FixtureResourceOutcome.NAMED_REFUSAL,
        "positive-authenticated-exceptional-exit-absent",
    )
