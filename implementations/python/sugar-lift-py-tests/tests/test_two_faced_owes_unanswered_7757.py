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
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.ir import ctor

    receiver = CallSiteValue("vendor.op", (), (), ctor("call:vendor.op", []), None)
    faces = receiver.attribute("member", _Site(), None)
    _assert_two_faced_and_owed(faces, "CallSiteValue.attribute")


def test_an_attribute_on_an_undecided_value_is_two_faced_and_owes_its_read() -> None:
    faces = SymbolicValue(make_var("s")).attribute("member", _Site(), None)
    _assert_two_faced_and_owed(faces, "SymbolicValue.attribute")
    (done,) = [arm for arm in faces.exits if isinstance(arm, Completed)]
    assert "python:attribute.completes" in repr(done.guard)
    assert "AttributeError" not in repr(faces)


def test_a_subscript_on_an_undecided_value_is_two_faced_and_owes_its_read() -> None:
    faces = SymbolicValue(make_var("s")).subscript(TermValue(0), _Site())
    _assert_two_faced_and_owed(faces, "SymbolicValue.subscript")
    (done,) = [arm for arm in faces.exits if isinstance(arm, Completed)]
    assert "python:subscript.completes" in repr(done.guard)
    assert "py.subscript" in repr(done.value)
    assert "KeyError" not in repr(faces) and "IndexError" not in repr(faces)


def test_an_undecided_read_with_no_site_is_the_lifters_gap() -> None:
    from sugar_source_tree.panic import SugarNotWritten

    receiver = SymbolicValue(make_var("s"))
    with pytest.raises(SugarNotWritten, match="no source site"):
        receiver.undecided_attribute("member", None, owner="t")
    with pytest.raises(SugarNotWritten, match="no source site"):
        receiver.undecided_subscript(TermValue(0), None, owner="t")


def _subscript_operation():
    from sugar_lift_py_tests.operations.subscript_operation import (
        SubscriptOperation,
    )

    return SubscriptOperation(index=TermValue(0), owner="SubscriptSugar", blame=_Site())


def test_an_opaque_subscript_owes_its_read() -> None:
    """The opaque arm of ``CallSiteValue.subscript_with`` answers the faces
    once: one completed arm, one halt, one debt -- not faces wrapped around
    faces."""
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.ir import ctor

    receiver = CallSiteValue("vendor.op", (), (), ctor("call:vendor.op", []), None)
    faces = receiver.subscript_with(_subscript_operation(), None)
    _assert_two_faced_and_owed(faces, "CallSiteValue.subscript")


def test_a_symbolic_subscript_through_its_operation_owes_its_read() -> None:
    """``SymbolicValue.subscript_with`` (every ``symbolic[k]`` in source, by
    ``SubscriptSugar``) is the same two faces as ``SymbolicValue.subscript``:
    it never completes without the undecided face."""
    operation = _subscript_operation()
    faces = operation.submit(SymbolicValue(make_var("s")), None)
    _assert_two_faced_and_owed(faces, "SymbolicValue.subscript")
    (done,) = [arm for arm in faces.exits if isinstance(arm, Completed)]
    assert "python:subscript.completes" in repr(done.guard)
    assert faces.completed_value() is None


def test_iter_on_an_undecided_value_is_two_faced_and_owes_its_call() -> None:
    """``iter(symbolic)`` through its operation: the one two-faced form, not
    a construction gap and not a sole completion."""
    from sugar_lift_py_tests.operations import IteratorOperation

    operation = IteratorOperation(owner="project_iter", blame=_Site())
    faces = operation.submit(SymbolicValue(make_var("s")), None)
    _assert_two_faced_and_owed(faces, "SymbolicValue.iter")
    (done,) = [arm for arm in faces.exits if isinstance(arm, Completed)]
    assert "python:iter.completes" in repr(done.guard)
    assert "py.iter" in repr(done.value)
    assert faces.completed_value() is None
    assert "TypeError" not in repr(faces)


def test_next_on_an_undecided_value_is_two_faced_and_owes_its_call() -> None:
    """``next(symbolic)``: completes with the opaque next value or raises
    something undetermined; ``StopIteration`` is never named here."""
    from sugar_lift_py_tests.operations import NextOperation

    operation = NextOperation(owner="project_next", blame=_Site())
    faces = operation.submit(SymbolicValue(make_var("s")), None)
    _assert_two_faced_and_owed(faces, "SymbolicValue.next")
    (done,) = [arm for arm in faces.exits if isinstance(arm, Completed)]
    assert "python:next.completes" in repr(done.guard)
    assert "py.next" in repr(done.value)
    assert faces.completed_value() is None
    assert "StopIteration" not in repr(faces)


def test_the_named_iter_and_next_projectors_answer_the_same_faces() -> None:
    from sugar_lift_py_tests.caller_parameter_contract import (
        project_iter,
        project_next,
    )
    from sugar_lift_py_tests.operations import IteratorOperation, NextOperation

    receiver = SymbolicValue(make_var("s"))
    site = _Site()
    assert project_iter(receiver, site, None) == IteratorOperation(
        owner="project_iter", blame=site
    ).submit(receiver, None)
    assert project_next(receiver, site, None) == NextOperation(
        owner="project_next", blame=site
    ).submit(receiver, None)


def test_next_on_an_opaque_operator_result_owes_its_call() -> None:
    """``next(opaque_op(...))`` used to complete alone with ``call:next``: a
    dropped halt.  It is the downstream's one two-faced form now."""
    from sugar_lift_py_tests.floor.opaque_op_callsite import OpaqueOpCallsite
    from sugar_lift_py_tests.operations import NextOperation

    receiver = OpaqueOpCallsite(callee="itertuples", arg=SymbolicValue(make_var("d")))
    faces = NextOperation(owner="project_next", blame=_Site()).submit(receiver, None)
    _assert_two_faced_and_owed(faces, "SymbolicValue.next")
    assert faces.completed_value() is None


def test_a_siteless_iter_or_next_is_the_lifters_gap() -> None:
    from sugar_source_tree.panic import SugarNotWritten

    receiver = SymbolicValue(make_var("s"))
    with pytest.raises(SugarNotWritten, match="no source site"):
        receiver.undecided_iteration(None, owner="t")
    with pytest.raises(SugarNotWritten, match="no source site"):
        receiver.undecided_next(None, owner="t")


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
