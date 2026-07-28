"""A demand joined onto a partition must land on a face, or be LOUD.

``rewrap_pending`` gained an arm for a pending obligation meeting a partition:
the demand is owed on EVERY face, because every face is downstream of the
construction that incurred it. That arm is right, and it carries the obligation
only while there IS a face.

Over a partition with **zero** faces the same loop puts it **nowhere**. The
obligation vanishes, the join returns a clean ``ExitSet``, and the caller
discharges nothing while looking resolved -- the exact silent drop this module
exists to make loud, and the same conservation hole ``outcome_to_exitset`` had
at the effect->halted boundary.

``test_a_partition_still_has_nowhere_to_carry_a_demand`` had been red on main
for the whole window. It is not a superseded panic: its name states the surviving
law exactly. A partition with no face still has nowhere to carry a demand.

The guard is a CONSERVATION POST-CONDITION, not an emptiness check, and it runs
AFTER ``normalize()``. Two different ways to arrive with nothing left to carry --
an ExitSet that was already empty, and one whose faces ``normalize`` dropped as
provably false -- are one property: every demand must be found on some surviving
face.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from sugar_lift_py_tests.caller_parameter_contract import (
    ContractConditionalConstructionV1,
)
from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
from sugar_lift_py_tests.floor.single_outcome_law import rewrap_pending
from sugar_lift_py_tests.floor.term_value import TermValue
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.ir import ctor
from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet, Halted

OWNER = "renamed_join"
BLAME = "renamed_module.py:1:0"


@dataclass(frozen=True)
class _Demand:
    demand_cid: str

    def demanded_under(self, guard):
        del guard
        return self


def _pending(cid: str, value):
    return ContractConditionalConstructionV1(
        source_node=BLAME,
        candidate=ctor("renamed_candidate", []),
        candidate_cid=f"blake3-512:{cid}",
        demands=(_Demand(f"blake3-512:{cid}"),),
        value=value,
    )


def _carried(result) -> set[str]:
    return {
        demand.demand_cid
        for exit_ in getattr(result, "exits", ())
        for contract in exit_.pending_contracts
        for demand in contract.demands
    }


# -- positive arm: a face exists, so the demand is owed on it ----------------


def test_every_face_of_a_partition_carries_the_demand() -> None:
    """The arm that already worked, pinned so the guard cannot swallow it."""
    partition = ExitSet(
        (
            Completed(ctor("g_true", []), TermValue(7), (), ()),
            Halted(
                ctor("g_false", []),
                RaiseEffect(exception_name="ValueError", blame=BLAME),
                None,
                (),
                (),
            ),
        )
    )

    result = rewrap_pending(
        _pending("aaaa", TermValue(1)), partition, owner=OWNER, blame=BLAME
    )

    assert _carried(result) == {"blake3-512:aaaa"}
    # Owed on EVERY face -- owing it on one only would drop it on the others.
    for exit_ in result.exits:
        assert any(
            demand.demand_cid == "blake3-512:aaaa"
            for contract in exit_.pending_contracts
            for demand in contract.demands
        )


def test_a_single_face_partition_still_carries() -> None:
    partition = ExitSet((Completed(ctor("g", []), TermValue(7), (), ()),))

    result = rewrap_pending(
        _pending("bbbb", TermValue(1)), partition, owner=OWNER, blame=BLAME
    )

    assert _carried(result) == {"blake3-512:bbbb"}


# -- the hole: nowhere to carry ---------------------------------------------


def test_an_empty_partition_has_nowhere_to_carry_and_stays_loud() -> None:
    """The measured drop. Before the guard this returned a clean ExitSet with
    the obligation nowhere -- a caller could discharge nothing and still look
    resolved."""
    with pytest.raises(ConstructionPanic) as raised:
        rewrap_pending(
            _pending("aaaa", TermValue(1)),
            ExitSet(()),
            owner=OWNER,
            blame=BLAME,
        )

    observed = raised.value.info.observed
    assert "no surviving face to carry" in observed
    # The gap names the obligation that would have been dropped.
    assert "blake3-512:aaaa" in observed


def test_the_gap_names_every_demand_that_would_have_been_dropped() -> None:
    pending = ContractConditionalConstructionV1(
        source_node=BLAME,
        candidate=ctor("renamed_candidate", []),
        candidate_cid="blake3-512:aaaa",
        demands=(_Demand("blake3-512:aaaa"), _Demand("blake3-512:bbbb")),
        value=TermValue(1),
    )

    with pytest.raises(ConstructionPanic) as raised:
        rewrap_pending(pending, ExitSet(()), owner=OWNER, blame=BLAME)

    observed = raised.value.info.observed
    assert "blake3-512:aaaa" in observed
    assert "blake3-512:bbbb" in observed


def test_the_guard_is_a_conservation_check_not_an_emptiness_check() -> None:
    """Checked AFTER ``normalize()``, so a partition whose faces normalize
    drops as provably false is caught by the same property -- not by a second
    special case for a second symptom.
    """
    false_faced = ExitSet((Completed(ctor("python:false", []), TermValue(7), (), ()),))

    # If normalize keeps the face, the demand rides it and this is not the
    # scenario; if normalize drops it, conservation must fire. Either is
    # correct -- what is NOT correct is a clean result carrying nothing.
    try:
        result = rewrap_pending(
            _pending("cccc", TermValue(1)), false_faced, owner=OWNER, blame=BLAME
        )
    except ConstructionPanic as panic:
        assert "no surviving face to carry" in panic.info.observed
    else:
        assert _carried(result) == {"blake3-512:cccc"}


# -- discriminating arm: the other three arms are untouched ------------------


def test_a_value_still_takes_the_obligation_back() -> None:
    from sugar_lift_py_tests.outcome import Complete

    result = rewrap_pending(
        _pending("aaaa", TermValue(1)),
        Complete(TermValue(9)),
        owner=OWNER,
        blame=BLAME,
    )

    assert isinstance(result, ContractConditionalConstructionV1)
    assert result.value == TermValue(9)
    assert {demand.demand_cid for demand in result.demands} == {"blake3-512:aaaa"}


def test_no_pending_demand_passes_the_partition_through_untouched() -> None:
    """The guard must not fire where there was never an obligation."""
    partition = ExitSet(())

    assert rewrap_pending(None, partition, owner=OWNER, blame=BLAME) is partition
