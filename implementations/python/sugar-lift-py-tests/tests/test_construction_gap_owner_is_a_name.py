"""``ConstructionGap.owner`` is the panic board's dispatch key: it is a NAME.

A panic row is worked as (owner x value category). A row whose ``owner`` field
holds an object projection or a source coordinate names an address instead of a
law, so it cannot be dispatched by owner at all and one law with no arm scatters
into one undispatchable row per call site.

Two faces per claim: the shape that IS a name constructs, the shape that is not
is refused, and the refusal names the replacement.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.floor.floor_value import FloorValue
from sugar_lift_py_tests.gap.info import ConstructionGap, GapKind, GapLocus
from sugar_lift_py_tests.gap.panic import ConstructionPanic

# The exact string a caller mints today: ``SourceFragment`` defines no
# ``__str__``, so ``str(site)`` yields its ``__repr__``.
FRAGMENT_REPR = "<SourceFragment 'renamed_module.py' [412, 431) node=Call>"
SOURCE_COORDINATE = "renamed_module.py:412:8"


def _gap(owner: object) -> ConstructionGap:
    return ConstructionGap(
        owner=owner,  # type: ignore[arg-type]
        blame="renamed_module.py:412:8",
        observed="RenamedValue",
        requested="project this floor value to a term",
        fix="write more Floor",
        gap_kind=GapKind.FLOOR,
        gap_locus=GapLocus.PROJECTION,
    )


# --------------------------------------------------------------------------
# the tooth: which owners are names
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "owner",
    [
        "add",
        "guarded",
        "collection ListValue",
        "StringValue.contains",
        "ContractConditionalConstructionV1.and_then",
        "FunctionCallable decorator result:renamed_target",
    ],
)
def test_a_name_is_admitted(owner: str) -> None:
    """Real owners on the board: spaces, dots and colons are all part of names."""
    assert _gap(owner).owner == owner


def test_an_object_projection_is_refused() -> None:
    with pytest.raises(TypeError) as excinfo:
        _gap(FRAGMENT_REPR)
    message = str(excinfo.value)
    assert "must be a name, not an object projection" in message
    assert "carry the fragment in blame" in message


def test_a_source_coordinate_is_refused() -> None:
    with pytest.raises(TypeError) as excinfo:
        _gap(SOURCE_COORDINATE)
    assert "must be a name, not a source coordinate" in str(excinfo.value)


@pytest.mark.parametrize("owner", ["", None, 12, object()])
def test_an_absent_owner_is_refused(owner: object) -> None:
    with pytest.raises(TypeError) as excinfo:
        _gap(owner)
    assert "must be a non-empty name" in str(excinfo.value)


# --------------------------------------------------------------------------
# the mechanism: FloorValue.to_term names its own projection law
# --------------------------------------------------------------------------


class RenamedUnprojectableValue(FloorValue):
    """A floor value with no ``to_term`` arm -- inherits the base None arm."""


class RenamedProjectableValue(FloorValue):
    """The other face: a value that CAN project answers with a term."""

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import str_const

        return str_const("renamed")


def test_to_term_gap_owner_is_the_projection_law_not_the_requester() -> None:
    with pytest.raises(ConstructionPanic) as excinfo:
        RenamedUnprojectableValue().to_term(owner=FRAGMENT_REPR)
    info = excinfo.value.info
    # The dispatch key is the law that has no arm.
    assert info.owner == "RenamedUnprojectableValue.to_term"
    # Nothing is discarded: the requester coordinate moves to blame.
    assert info.blame == FRAGMENT_REPR
    assert info.observed == "RenamedUnprojectableValue"
    assert info.gap_locus is GapLocus.PROJECTION


def test_a_value_that_can_project_does_not_panic() -> None:
    """The discriminating face -- the arm exists, so no row is minted."""
    assert RenamedProjectableValue().to_term(owner=FRAGMENT_REPR) is not None


def test_two_requesters_of_one_missing_law_share_one_owner() -> None:
    """The whole point: one law with no arm is ONE board bucket, not N."""
    owners = set()
    for requester in (
        FRAGMENT_REPR,
        "<SourceFragment 'other_renamed.py' [7, 9) node=BinOp>",
        SOURCE_COORDINATE,
    ):
        with pytest.raises(ConstructionPanic) as excinfo:
            RenamedUnprojectableValue().to_term(owner=requester)
        owners.add(excinfo.value.info.owner)
    assert len(owners) == 1
