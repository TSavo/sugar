"""Every two-faced outcome owes its operation as the one ``undecided`` member.

#7757 item 13. ``ExitSet.two_faced`` is the one constructor of "completes
under this atom, or raises something undetermined under its complement".
What such an operation does is not decided here, and the one way to say so is
the ``undecided`` member (reason ``unanswered``). The constructor attaches
that debt itself (``site=`` is required), so no producer can build the pair
and owe nothing. One representative site per producer family below: each is
two-faced through the one constructor and owes exactly one unanswered item at
its site, on both arms.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1
from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
from sugar_lift_py_tests.floor.term_value import TermValue
from sugar_lift_py_tests.ir import atomic, make_var
from sugar_lift_py_tests.outcome.exit_set import (
    Completed,
    ExitSet,
    Halted,
    complement_guard,
)
from sugar_lift_py_tests.unanswered_calls import UnansweredCallV1, owed_calls

_SRC = "blake3-512:" + "cd" * 64


class _Site:
    """A fragment's two coordinates: its unit's source CID and its span."""

    class _Span:
        start_line, start_col, end_line, end_col = 3, 4, 3, 12

    source_cid = _SRC
    line_col_span = _Span()


_COORDINATE = SourceFragmentCoordinateV1(_SRC, 3, 4, 3, 12)
_OWED = (UnansweredCallV1(None, _COORDINATE),)


def _assert_two_faced_and_owed(faces, owner: str) -> None:
    """One completed arm, one undetermined halt under its complement, and
    both arms owe the operation once, at its site."""
    (done,) = [arm for arm in faces.exits if isinstance(arm, Completed)]
    (halt,) = [arm for arm in faces.exits if isinstance(arm, Halted)]
    assert len(faces.exits) == 2
    assert halt.guard == complement_guard(done.guard)
    assert type(halt.effect) is UndeterminedRaiseEffect
    assert halt.effect.producer_node_owner == owner
    assert done.owed == halt.owed == _OWED
    assert owed_calls(faces) == _OWED


def test_the_one_constructor_cannot_be_called_without_a_site() -> None:
    effect = UndeterminedRaiseEffect(blame="t", occurrence="t")
    with pytest.raises(TypeError, match="site"):
        ExitSet.two_faced(TermValue(1), effect, guard=atomic("t:completes", []))


def test_the_one_constructor_owes_after_what_the_path_already_owed() -> None:
    earlier = SourceFragmentCoordinateV1(_SRC, 1, 0, 1, 3)
    prior = UnansweredCallV1("python:m.g", earlier)
    faces = ExitSet.two_faced(
        TermValue(1),
        UndeterminedRaiseEffect(blame="t", occurrence="t"),
        guard=atomic("t:completes", []),
        site=_Site(),
        owed=(prior,),
    )
    assert all(arm.owed == (prior, *_OWED) for arm in faces.exits)


def test_a_siteless_operation_is_owed_and_refused_by_name_at_the_member_door() -> None:
    from sugar_lift_py_tests import tree_enumerate as _tree

    faces = ExitSet.two_faced(
        TermValue(1),
        UndeterminedRaiseEffect(blame="t", occurrence="t"),
        guard=atomic("t:completes", []),
        site="a-synthetic-slot-id",
    )
    (item,) = owed_calls(faces)
    assert item.site is None
    with pytest.raises(ValueError, match="no site"):
        _tree.unanswered_call_rows((item,), "m.py")


def test_an_opaque_attribute_owes_its_read() -> None:
    from sugar_lift_py_tests.floor.call_site_value import (
        CallSiteValue,
        _opaque_attribute_faces,
    )
    from sugar_lift_py_tests.ir import ctor

    receiver = CallSiteValue("vendor.op", (), (), ctor("call:vendor.op", []), None)
    faces = _opaque_attribute_faces(receiver, "member", _Site())
    _assert_two_faced_and_owed(faces, "CallSiteValue.attribute")


def test_an_opaque_subscript_owes_its_read() -> None:
    from sugar_lift_py_tests.floor.call_site_value import _opaque_subscript_faces

    faces = _opaque_subscript_faces(
        ExitSet.completed(SymbolicValue(make_var("s"))), _Site()
    )
    _assert_two_faced_and_owed(faces, "CallSiteValue.subscript")


def test_an_undecided_binary_operation_owes_its_dispatch() -> None:
    from sugar_lift_py_tests.floor.floor_value import undecided_binary_faces

    faces = undecided_binary_faces(
        SymbolicValue(make_var("s")), TermValue(2), _Site(), "+"
    )
    _assert_two_faced_and_owed(faces, "UndecidedBinary:+")


def test_an_undecided_comparison_owes_its_dispatch() -> None:
    from sugar_lift_py_tests.floor.predicate_value import PredicateValue
    from sugar_lift_py_tests.sugar.comparison_op_sugar import undecided_dispatch_faces

    formula = atomic("py.eq", [make_var("a"), make_var("b")])
    predicate = PredicateValue(formula, _Site())
    faces = undecided_dispatch_faces(predicate, _Site(), "Eq")
    _assert_two_faced_and_owed(faces, "UndecidedCompare:Eq")


def test_an_undecided_builtin_container_method_owes_its_call() -> None:
    from sugar_lift_py_tests.sugar.builtin_container_call_sugar import _opaque_pair

    faces = _opaque_pair("list", "append", _Site())
    _assert_two_faced_and_owed(faces, "BuiltinMethodCall:list.append")


def test_an_undecided_item_mutation_owes_its_setitem() -> None:
    from sugar_lift_py_tests.sugar.store_effect_sugar import (
        undecided_item_mutation_faces,
    )

    faces = undecided_item_mutation_faces(
        _Site(), noun="setitem", method="__setitem__", owner="UndecidedSetitem"
    )
    _assert_two_faced_and_owed(faces, "UndecidedSetitem")


@pytest.mark.parametrize("step", ["construct", "__enter__", "__exit__"])
def test_a_formal_selected_manager_step_owes_the_with_item(step: str) -> None:
    from sugar_lift_py_tests.floor.entered_manager_state_value import (
        EnteredManagerStateValue,
    )
    from sugar_lift_py_tests.floor.formal_selected_manager import (
        FormalSelectedManagerProtocol,
        FormalSelectedManagerValue,
    )

    protocol = FormalSelectedManagerProtocol("p.open", "with-key", _COORDINATE)
    manager = FormalSelectedManagerValue("p.open", "with-key")
    if step == "construct":
        faces = protocol.construct_manager(manager)
    elif step == "__enter__":
        faces = protocol.enter_resource_outcome_for(manager)
    else:
        faces = protocol.exit_outcome_for(
            EnteredManagerStateValue(enter_value=None, receiver_state=manager)
        )
    _assert_two_faced_and_owed(faces, f"FormalSelectedManager:p.open.{step}")


def test_the_formal_head_select_step_owes_the_with_item() -> None:
    from sugar_lift_py_tests.floor.formal_selected_manager import (
        FormalSelectedManagerProtocol,
    )

    protocol = FormalSelectedManagerProtocol("p.open", "with-key", _COORDINATE)
    faces = protocol.step_faces("select", None)
    _assert_two_faced_and_owed(faces, "FormalSelectedManager:p.open.select")
