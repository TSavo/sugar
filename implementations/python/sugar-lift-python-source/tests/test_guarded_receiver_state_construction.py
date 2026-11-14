import pytest

from sugar_lift_py_tests.floor import (
    ObjectValue,
    TermValue,
    GuardedReceiverStateValue,
)
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.ir import and_, eq, make_var, num

from frame_fresh import FRAME_FRESH


def test_guarding_a_snapshot_retains_and_conjoins_its_branch_not_an_unconditional_state():
    receiver = ObjectValue("Renamed", (), identity="owned", allocation=FRAME_FRESH)
    first = eq(make_var("first"), num(1))
    second = eq(make_var("second"), num(2))
    guarded = receiver.guarded(first).guarded(second)
    assert isinstance(guarded, GuardedReceiverStateValue)
    assert guarded.receiver is receiver
    assert guarded.guard == and_([second, first])
    assert guarded.to_term(owner="test") != receiver.to_term(owner="test")


def test_guarded_snapshot_rejects_a_non_receiver_instead_of_silently_ignoring_it():
    with pytest.raises(ConstructionPanic, match="GuardedReceiverStateValue"):
        GuardedReceiverStateValue(TermValue(7), and_([]))
