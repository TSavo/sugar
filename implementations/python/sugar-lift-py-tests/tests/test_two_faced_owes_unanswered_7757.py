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
    effect = UndeterminedRaiseEffect(blame="t", occurrence="t", site=_Site())
    with pytest.raises(TypeError, match="site"):
        ExitSet.two_faced(TermValue(1), effect, guard=atomic("t:completes", []))


def test_an_undetermined_halt_cannot_be_built_without_its_site() -> None:
    """#7766: every undetermined halt states the fragment it halted at, so
    the effect has no siteless constructor: omitted or ``None`` is refused."""
    with pytest.raises(TypeError, match="site"):
        UndeterminedRaiseEffect(blame="t", occurrence="t")
    with pytest.raises(TypeError, match="site=None"):
        UndeterminedRaiseEffect(blame="t", occurrence="t", site=None)


def test_the_one_constructor_owes_after_what_the_path_already_owed() -> None:
    earlier = SourceFragmentCoordinateV1(_SRC, 1, 0, 1, 3)
    prior = UnansweredCallV1("python:m.g", earlier)
    faces = ExitSet.two_faced(
        TermValue(1),
        UndeterminedRaiseEffect(blame="t", occurrence="t", site=_Site()),
        guard=atomic("t:completes", []),
        site=_Site(),
        owed=(prior,),
    )
    assert all(arm.owed == (prior, *_OWED) for arm in faces.exits)


def test_a_siteless_operation_is_owed_and_refused_by_name_at_the_member_door() -> None:
    from sugar_lift_py_tests import tree_enumerate as _tree

    faces = ExitSet.two_faced(
        TermValue(1),
        UndeterminedRaiseEffect(
            blame="t", occurrence="t", site="a-synthetic-slot-id"
        ),
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
    assert "python:subscript_op.completes" in repr(done.guard)
    assert "python:subscript_result" in repr(done.value)
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
    assert "python:subscript_op.completes" in repr(done.guard)
    assert faces.completed_value() is None


def test_iter_on_an_undecided_value_is_two_faced_and_owes_its_call() -> None:
    """``iter(symbolic)`` through its operation: the one two-faced form, not
    a construction gap and not a sole completion."""
    from sugar_lift_py_tests.operations import IteratorOperation

    operation = IteratorOperation(owner="project_iter", blame=_Site())
    faces = operation.submit(SymbolicValue(make_var("s")), None)
    _assert_two_faced_and_owed(faces, "SymbolicValue.iter")
    (done,) = [arm for arm in faces.exits if isinstance(arm, Completed)]
    assert "python:iter_op.completes" in repr(done.guard)
    assert "python:iter_result" in repr(done.value)
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
    assert "python:next_op.completes" in repr(done.guard)
    assert "python:next_result" in repr(done.value)
    assert faces.completed_value() is None
    assert "StopIteration" not in repr(faces)


def test_a_formals_iter_and_next_are_the_same_two_faces() -> None:
    """#7757 NEW-1: a parameter's ``iter`` / ``next`` mints no carrier
    waiting on a caller's actual; it is the one two-faced form, the same a
    symbolic value with no formal coordinate takes."""
    from sugar_lift_py_tests.operations import IteratorOperation, NextOperation

    formal = SymbolicValue(make_var("s"), formal_coordinate=object())
    free = SymbolicValue(make_var("s"))
    for operation, owner in (
        (IteratorOperation(owner="t", blame=_Site()), "SymbolicValue.iter"),
        (NextOperation(owner="t", blame=_Site()), "SymbolicValue.next"),
    ):
        faces = operation.submit(formal, None)
        _assert_two_faced_and_owed(faces, owner)
        assert faces == operation.submit(free, None)


@pytest.mark.parametrize(
    ("method", "operator"),
    [("unary_minus", "-"), ("unary_plus", "+"), ("bitwise_invert", "~")],
)
def test_a_formals_unary_operator_is_two_faced_and_owes_it(
    method: str, operator: str
) -> None:
    """#7757 NEW-1: ``-p`` / ``+p`` / ``~p`` on a parameter is the undecided
    two faces (``FloorValue.undecided_unary``), owed, its halt kept: no
    carrier, no ``TypeError`` guessed, no result folded.  Its value is
    ``python:unary_result("<op>", p, <key>)``, keyed per evaluation."""
    from sugar_lift_py_tests.ir import str_const
    from sugar_lift_py_tests.occurrence import occurrence_key

    formal = SymbolicValue(make_var("p"), formal_coordinate=object())
    faces = getattr(formal, method)(_Site())
    _assert_two_faced_and_owed(faces, f"SymbolicValue.{method}")
    (done,) = [arm for arm in faces.exits if isinstance(arm, Completed)]
    (halt,) = [arm for arm in faces.exits if isinstance(arm, Halted)]
    key = occurrence_key(_Site())
    term = done.value.term
    assert term.name == "python:unary_result"
    assert term.args == (str_const(operator), make_var("p"), str_const(key))
    assert "python:unary_op.completes" in repr(done.guard)
    assert halt.effect.occurrence == key
    assert faces.completed_value() is None
    assert "TypeError" not in repr(faces)


def test_two_evaluations_of_one_formal_operation_are_two_unknowns() -> None:
    """#7757 NEW-1 key rule: each evaluation's value names its own
    occurrence, so two ``next(p)`` (or ``-p``) at two sites are never one
    term, and a truthful ``a != b`` over them cannot read ``unsat``."""
    from sugar_lift_py_tests.operations import IteratorOperation, NextOperation

    class _Other(_Site):
        class _Span:
            start_line, start_col, end_line, end_col = 4, 4, 4, 12

        line_col_span = _Span()

    formal = SymbolicValue(make_var("p"), formal_coordinate=object())
    for operate in (
        lambda site: NextOperation(owner="t", blame=site).submit(formal, None),
        lambda site: IteratorOperation(owner="t", blame=site).submit(formal, None),
        lambda site: formal.unary_minus(site),
    ):
        first = operate(_Site())
        second = operate(_Other())
        (one,) = [arm for arm in first.exits if isinstance(arm, Completed)]
        (two,) = [arm for arm in second.exits if isinstance(arm, Completed)]
        assert one.value.term != two.value.term


def test_a_formals_truth_is_two_faced_and_owes_it() -> None:
    """#7757 NEW-1: ``bool(p)`` asked of a parameter is the one undecided
    truth (``bool_op_sugar._unanswered_truth``): ``python:truth_result(p,
    <key>)`` under ``python:truth.completes(python:truth(p, <key>))``, an
    undetermined halt at the same key under its complement."""
    from sugar_lift_py_tests.ir import str_const

    formal = SymbolicValue(make_var("p"), formal_coordinate=object())
    faces = formal.truth(_Site())
    _assert_two_faced_and_owed(faces, "SymbolicValue.truth")
    (done,) = [arm for arm in faces.exits if isinstance(arm, Completed)]
    (halt,) = [arm for arm in faces.exits if isinstance(arm, Halted)]
    assert "python:truth.completes" in repr(done.guard)
    assert done.value.formula == atomic(
        "python:truth_result",
        [make_var("p"), str_const(halt.effect.occurrence)],
    )
    assert "py.truthy" not in repr(done.value.formula)


def test_a_direct_truth_is_the_one_truth_rules_two_faces() -> None:
    """#7757 NEW-5: ``.truth`` asked directly of a value whose type is not
    decided (a non-formal symbol, a call result) is what ``truth_of``
    answers -- the two faces, owed -- never a halt-less ``py.truthy``."""
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.ir import ctor
    from sugar_lift_py_tests.sugar.bool_op_sugar import truth_of

    for value, owner in (
        (SymbolicValue(make_var("s")), "SymbolicValue.truth"),
        (
            CallSiteValue(
                "opaque", (), (), ctor("call:opaque", [make_var("xs")]), None
            ),
            "CallSiteValue.truth",
        ),
    ):
        site = _Site()
        faces = value.truth(site)
        _assert_two_faced_and_owed(faces, owner)
        (done,) = [arm for arm in faces.exits if isinstance(arm, Completed)]
        assert done.value.formula.name == "python:truth_result"
        ruled = truth_of(value, site, owner=owner)
        assert [arm.guard for arm in ruled.exits] == [arm.guard for arm in faces.exits]
        assert [
            arm.value.formula for arm in ruled.exits if isinstance(arm, Completed)
        ] == [done.value.formula]


def test_two_evaluations_of_one_comparison_or_truth_are_two_unknowns() -> None:
    """#7757 NEW-1 key rule, comparisons and truth (option (b)): the value
    of ``p == q`` and of ``bool(p)`` names its own occurrence, so two
    evaluations at two sites (a counting ``__eq__`` asked twice) are two
    atoms, and a truthful ``(p == q) != (p == q)`` cannot read ``unsat``."""
    from sugar_lift_py_tests.floor.predicate_value import PredicateValue
    from sugar_lift_py_tests.ir import str_const
    from sugar_lift_py_tests.sugar.comparison_op_sugar import undecided_dispatch_faces

    class _Other(_Site):
        class _Span:
            start_line, start_col, end_line, end_col = 4, 4, 4, 12

        line_col_span = _Span()

    formal = SymbolicValue(make_var("p"), formal_coordinate=object())
    equality = atomic("py.eq", [make_var("p"), make_var("q")])
    for operate in (
        lambda site: undecided_dispatch_faces(
            PredicateValue(equality, site), site, "Eq"
        ),
        lambda site: formal.truth(site),
    ):
        first = operate(_Site())
        second = operate(_Other())
        (one,) = [arm for arm in first.exits if isinstance(arm, Completed)]
        (two,) = [arm for arm in second.exits if isinstance(arm, Completed)]
        (halt,) = [arm for arm in first.exits if isinstance(arm, Halted)]
        assert one.value.formula != two.value.formula
        assert one.value.formula.args[-1] == str_const(halt.effect.occurrence)


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
