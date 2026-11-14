"""An exit's effect boundary is read off its own formula, never off spellings.

A receiver with fields spelled ``expected_exceptions`` and ``match`` and a
method spelled ``matches`` is not pytest's ``RaisesExc``: an unreduced
``matches(exc_val)`` call is that call's undecided citation, and no field
name stands in for an operand the exit's formula does not read (#7757).
"""

from dataclasses import dataclass
from types import SimpleNamespace

from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.floor import (
    BlockValue,
    NoneValue,
    ObjectValue,
    ReturnValue,
    SymbolicValue,
)
from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
from sugar_lift_py_tests.floor.object_field import ObjectField
from sugar_lift_py_tests.context_manager_contract import (
    EffectBoundarySemanticsV1,
    ExpectsModeV1,
    FormalArgumentProjectionV1,
    NoMessagePatternV1,
)
from sugar_lift_py_tests.floor.branch_result_coordinate import (
    BranchResultAuthentication,
    branch_result_guard,
)
from sugar_lift_py_tests.floor.dict_value import DictValue
from sugar_lift_py_tests.floor.string_value import StringValue
from sugar_lift_py_tests.ir import and_, atomic, ctor, make_var, not_, str_const
from sugar_source_tree.binding_state import BranchResultSlot
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_py_tests.outcome.exit_set import complement_guard
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_lift_python_source import manager_summary_derivation as derivation


@dataclass(frozen=True)
class _Method:
    name: str


def _expected_var():
    return SymbolicValue(term=make_var("expected_exception"))


def _behavior(*, match=None, extra_actuals=()):
    """A user receiver spelled exactly like pytest's ``RaisesExc``."""
    expected = _expected_var()
    match_value = NoneValue() if match is None else match
    return SimpleNamespace(
        resolved_object_cid="manager-object",
        formal_actual_values=(expected, *extra_actuals),
        receiver_state=ObjectValue(
            "RaisesExc",
            (
                ObjectField("expected_exceptions", expected),
                ObjectField("match", match_value),
                ObjectField("check", NoneValue()),
            ),
            methods=(_Method("matches"),),
            identity="receiver",
        ),
    )


def _matches_formula():
    return not_(
        not_(
            atomic(
                "py.truthy",
                [
                    ctor(
                        "call:RaisesExc.matches",
                        [
                            ctor(
                                "py.object.identity",
                                [str_const("RaisesExc"), str_const("receiver")],
                            ),
                            ctor("python:exit_value", [str_const("exit-face")]),
                        ],
                    )
                ],
            )
        )
    )


def _identity_formula():
    return atomic(
        "identity",
        [
            ctor("python:exit_type", [str_const("exit-face")]),
            make_var("expected_exception"),
        ],
    )


def _actual_terms(behavior):
    return tuple(
        value.to_term(owner=behavior.resolved_object_cid)
        for value in behavior.formal_actual_values
    )


def _no_effect_formula(exit_face_id="exit-face"):
    return atomic(
        "identity",
        [
            ctor("python:exit_type", [str_const(exit_face_id)]),
            ctor("None", []),
        ],
    )


def _nested_did_not_raise_exit(decision, *, match_value=None, extra_actuals=()):
    """``if exc_type is None: raise; if <decision>: return True; return False``."""
    slot = BranchResultSlot("branch-result:exc-type-is-none")
    absent = branch_result_guard(slot, "if-exc-type-is-none")
    fail_halt = Halted(
        absent,
        RaiseEffect.for_builtin("RuntimeError", blame="support.py:3"),
    )
    matched = Completed(
        and_([not_(absent), decision]),
        BlockValue(
            (
                BranchResultAuthentication(
                    slot, _no_effect_formula(), "if-exc-type-is-none"
                ),
                ReturnValue(TrueBoolLiteralSugar(site="return-true")),
            ),
            can_fall_through=False,
        ),
    )
    unmatched = Completed(
        and_([not_(absent), not_(decision)]),
        BlockValue(
            (ReturnValue(FalseBoolLiteralSugar(site="return-false")),),
            can_fall_through=False,
        ),
    )
    return (
        _behavior(match=match_value, extra_actuals=extra_actuals),
        SimpleNamespace(exit_face_id="exit-face"),
        ExitSet((fail_halt, matched, unmatched)),
    )


def test_unreduced_matches_call_projects_no_expected_operand():
    """``matches(exc_val)`` is not read through the ``expected_exceptions`` field."""
    behavior = _behavior()
    assert (
        derivation._formal_index_for_coordinate(
            _matches_formula(), _actual_terms(behavior), "python:exit_type"
        )
        is None
    )
    assert (
        derivation._formal_index_for_coordinate(
            _matches_formula(), _actual_terms(behavior), "python:exit_value"
        )
        is None
    )


def test_raises_spelled_user_receiver_is_not_raises_exc():
    """Fields ``match``/``expected_exceptions`` plus ``matches`` seal nothing."""
    boom = StringValue("boom")
    behavior, protocol, exit_set = _nested_did_not_raise_exit(
        _matches_formula(), match_value=boom, extra_actuals=(boom,)
    )
    assert derivation._derive_effect_boundary(exit_set, protocol, behavior) is None


def test_raises_spelled_receiver_with_none_match_is_not_raises_exc():
    behavior, protocol, exit_set = _nested_did_not_raise_exit(_matches_formula())
    assert derivation._derive_effect_boundary(exit_set, protocol, behavior) is None


def test_raises_spelled_receiver_with_kwargs_match_is_not_raises_exc():
    kwargs = DictValue(((StringValue("match"), StringValue("boom")),))
    behavior, protocol, exit_set = _nested_did_not_raise_exit(
        _matches_formula(), extra_actuals=(kwargs,)
    )
    assert derivation._derive_effect_boundary(exit_set, protocol, behavior) is None


def test_identity_exit_reads_its_expected_operand_off_the_formula():
    """The expected type is the formal the exit's own identity test reads."""
    behavior, protocol, exit_set = _nested_did_not_raise_exit(_identity_formula())
    result = derivation._derive_effect_boundary(exit_set, protocol, behavior)
    assert isinstance(result, EffectBoundarySemanticsV1)
    assert isinstance(result.mode, ExpectsModeV1)
    assert result.expected_type_operand == FormalArgumentProjectionV1(0)
    assert isinstance(result.message_pattern_operand, NoMessagePatternV1)


def test_a_field_spelled_match_is_not_a_message_pattern():
    """A stored ``match`` the exit never reads leaves the message unconstrained.

    The exit decides on ``exc_type`` alone; the raised value appears nowhere
    in its formula, so it consumes any message. The field's spelling is not
    read in either direction.
    """
    behavior, protocol, exit_set = _nested_did_not_raise_exit(
        _identity_formula(), match_value=StringValue("boom")
    )
    result = derivation._derive_effect_boundary(exit_set, protocol, behavior)
    assert isinstance(result, EffectBoundarySemanticsV1)
    assert isinstance(result.message_pattern_operand, NoMessagePatternV1)


def test_exit_reading_the_raised_value_without_an_operand_is_refused():
    """A decision on ``exc_val`` with no projected formal is not NoMessagePattern."""
    reads_value = atomic(
        "py.truthy",
        [
            ctor(
                "call:Checker.check",
                [ctor("python:exit_value", [str_const("exit-face")])],
            )
        ],
    )
    behavior, protocol, exit_set = _nested_did_not_raise_exit(
        and_([_identity_formula(), reads_value])
    )
    assert derivation._derive_effect_boundary(exit_set, protocol, behavior) is None


def test_assertionerror_halt_complements_the_true_return():
    guard = atomic("py.truthy", [make_var("matches-result")])
    halted = Halted(
        guard,
        RaiseEffect.for_builtin("AssertionError", blame="raises.py:711"),
    )
    completed = Completed(
        complement_guard(guard),
        BlockValue(
            (ReturnValue(TrueBoolLiteralSugar(site="return-true")),),
            can_fall_through=False,
        ),
    )
    exit_set = ExitSet((halted, completed))
    assert derivation._halt_complements_true_return(halted, exit_set)
    assert not derivation._halt_complements_true_return(completed, exit_set)


def test_bodyless_free_fail_on_a_completed_face_is_unresolved():
    fail = CallSiteValue(
        "fail",
        (),
        (),
        ctor("call:fail", []),
        None,
    )
    completed = Completed(
        complement_guard(atomic("py.truthy", [make_var("matches-result")])),
        BlockValue(
            (fail, ReturnValue(TrueBoolLiteralSugar(site="return-true"))),
            can_fall_through=False,
        ),
    )
    assert derivation._completed_faces_have_bodyless_free_calls(ExitSet((completed,)))


def test_method_callsite_on_a_completed_face_is_not_a_free_fail():
    fill = CallSiteValue(
        "fill_unfilled",
        (),
        (),
        ctor("call:fill_unfilled", []),
        None,
        runtime_dispatch_receiver=ObjectValue("ExceptionInfo", (), identity="excinfo"),
    )
    completed = Completed(
        complement_guard(atomic("py.truthy", [make_var("matches-result")])),
        BlockValue(
            (fill, ReturnValue(TrueBoolLiteralSugar(site="return-true"))),
            can_fall_through=False,
        ),
    )
    assert not derivation._completed_faces_have_bodyless_free_calls(
        ExitSet((completed,))
    )


def test_none_func_formal_is_not_cited_by_exc_type_is_none():
    """``func=None`` is not the expected type of ``if exc_type is None``."""
    behavior, _protocol, _exit_set = _nested_did_not_raise_exit(
        _identity_formula(), extra_actuals=(NoneValue(),)
    )
    formula = and_([not_(_no_effect_formula()), _identity_formula()])
    assert (
        derivation._formal_index_for_coordinate(
            formula, _actual_terms(behavior), "python:exit_type"
        )
        == 0
    )
