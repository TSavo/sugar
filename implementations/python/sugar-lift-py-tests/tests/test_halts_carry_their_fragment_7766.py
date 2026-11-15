"""Every halt states the source fragment it left at on its effect's ``site``
(#7766, after #8185): the halts that still had none.

``tree_enumerate.halt_locus`` refuses by name a halt whose effect states no
fragment, so each producer below carries the real fragment from where it
builds the effect: the ``with`` whose generator ``__exit__`` refuses, the ``break``/``continue``
statement, the ``warnings.warn`` call.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.outcome.exit_set import Halted

_CID = "blake3-512:" + "ef" * 64


class _Fragment:
    """What a panic locus reads off a fragment: file, line, column."""

    filename = "pkg/mod.py"
    line = 3
    col = 4

    def __str__(self) -> str:
        return "pkg/mod.py:3:4"


def test_a_generator_manager_exit_refusal_halts_at_the_with() -> None:
    from sugar_lift_py_tests.generator_manager_exit import (
        _pep479,
        _refusal,
        observed_exit_refusals,
    )

    fragment = _Fragment()
    refusal = _refusal(observed_exit_refusals().did_not_stop, site=fragment)
    assert refusal.site is fragment
    assert refusal.blame == str(fragment)
    converted = _pep479(refusal, site=fragment)
    assert converted.site is fragment


def test_a_loop_control_halt_states_its_statement() -> None:
    from sugar_lift_py_tests.effect.loop_control_effect import LoopControlEffect

    fragment = _Fragment()
    effect = LoopControlEffect("break", _CID, _CID, site=fragment)
    assert effect.site is fragment
    # The occurrence is the identity; the site is testimony.
    assert effect == LoopControlEffect("break", _CID, _CID)


def test_a_warning_states_the_call_it_was_observed_at() -> None:
    from sugar_lift_py_tests.effect.warning_effect import WarningEffect

    fragment = _Fragment()
    effect = WarningEffect("UserWarning", site=fragment)
    assert effect.site is fragment
    assert "pkg/mod.py:3:4" in effect.reason


class _OperationFragment(_Fragment):
    """An operation's fragment: what a panic locus reads (file, line,
    column) and what its occurrence is keyed on (unit CID and span)."""

    class _Span:
        start_line, start_col, end_line, end_col = 3, 4, 3, 12

    source_cid = _SRC
    line_col_span = _Span()


def _the_halt(faces, owner: str):
    """The one undetermined halt ``owner`` built, among ``faces``' arms."""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect

    (halt,) = [
        arm
        for arm in faces.exits
        if isinstance(arm, Halted)
        and type(arm.effect) is UndeterminedRaiseEffect
        and arm.effect.producer_node_owner == owner
    ]
    return halt


def test_an_undecided_binary_operation_halts_at_its_own_fragment() -> None:
    from sugar_lift_py_tests.floor.floor_value import undecided_binary_faces
    from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
    from sugar_lift_py_tests.floor.term_value import TermValue
    from sugar_lift_py_tests.ir import make_var

    fragment = _OperationFragment()
    faces = undecided_binary_faces(
        SymbolicValue(make_var("s")), TermValue(2), fragment, "+"
    )
    assert _the_halt(faces, "UndecidedBinary:+").effect.site is fragment


def test_a_binary_operation_with_no_site_is_refused_by_name_not_keyed_empty() -> None:
    """The BinOp with no fragment is the lifter's gap, refused where the key
    is taken, as every other undecided operation is; it never halts at no
    site under an empty key."""
    from sugar_lift_py_tests.floor.floor_value import undecided_binary_faces
    from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
    from sugar_lift_py_tests.floor.term_value import TermValue
    from sugar_lift_py_tests.gap.panic import ConstructionPanic
    from sugar_lift_py_tests.ir import make_var

    with pytest.raises(ConstructionPanic):
        undecided_binary_faces(SymbolicValue(make_var("s")), TermValue(2), None, "+")


def test_an_undecided_comparison_halts_at_its_own_fragment() -> None:
    from sugar_lift_py_tests.floor.predicate_value import PredicateValue
    from sugar_lift_py_tests.ir import atomic, make_var
    from sugar_lift_py_tests.sugar.comparison_op_sugar import undecided_dispatch_faces

    fragment = _OperationFragment()
    predicate = PredicateValue(
        atomic("py.eq", [make_var("a"), make_var("b")]), fragment
    )
    faces = undecided_dispatch_faces(predicate, fragment, "Eq")
    assert _the_halt(faces, "UndecidedCompare:Eq").effect.site is fragment


def test_an_undecided_builtin_method_call_halts_at_its_own_fragment() -> None:
    from sugar_lift_py_tests.sugar.builtin_container_call_sugar import _opaque_pair

    fragment = _OperationFragment()
    faces = _opaque_pair("list", "append", fragment)
    assert _the_halt(faces, "BuiltinMethodCall:list.append").effect.site is fragment


def test_an_unknown_callee_call_halts_at_its_own_fragment() -> None:
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.ir import ctor
    from sugar_lift_py_tests.source_call_resolution import UnknownCalleeCallV1

    fragment = _OperationFragment()
    callsite = CallSiteValue("h", (), (), ctor("call:h", []), None)
    faces = UnknownCalleeCallV1("h").faces(callsite, fragment)
    assert _the_halt(faces, "UnknownCallee:h").effect.site is fragment


def test_a_bool_op_truth_halts_at_its_own_fragment() -> None:
    from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
    from sugar_lift_py_tests.floor.term_value import TermValue
    from sugar_lift_py_tests.ir import make_var
    from sugar_lift_py_tests.outcome import ExitSet
    from sugar_lift_py_tests.sugar.bool_op_sugar import select_boolop_operand

    fragment = _OperationFragment()
    faces = select_boolop_operand(
        SymbolicValue(make_var("s")),
        op_kind="And",
        site=fragment,
        index=0,
        on_continue=lambda: ExitSet.completed(TermValue(1)),
    )
    assert _the_halt(faces, "BoolOpSugar.truth").effect.site is fragment
