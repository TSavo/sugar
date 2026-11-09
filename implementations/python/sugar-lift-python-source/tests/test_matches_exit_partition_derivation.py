"""A matches() partition cites expected_exceptions; it does not invent SuppressesMode."""

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
    OptionalFormalArgumentProjectionV1,
)
from sugar_lift_py_tests.floor.branch_result_coordinate import (
    BranchResultAuthentication,
    branch_result_guard,
)
from sugar_lift_py_tests.floor.string_value import StringValue
from sugar_lift_py_tests.ir import and_, atomic, ctor, make_var, not_, str_const
from sugar_source_tree.binding_state import BranchResultSlot
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_py_tests.outcome.exit_set import complement_guard
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_lift_python_source import manager_summary_derivation as derivation


def _expected_var():
    return SymbolicValue(term=make_var("expected_exception"))


def _behavior(*, match=None, extra_actuals=()):
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
            ),
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
                            ctor("python:exit_value", [str_const("exit_face")]),
                        ],
                    )
                ],
            )
        )
    )


def _actual_terms(behavior):
    return tuple(
        value.to_term(owner=behavior.resolved_object_cid)
        for value in behavior.formal_actual_values
    )


def test_matches_formula_projects_the_expected_exceptions_formal():
    behavior = _behavior()
    assert (
        derivation._formal_index_for_matches_expected(
            _matches_formula(), behavior, _actual_terms(behavior)
        )
        == 0
    )


def test_seeded_none_match_does_not_project_a_message_formal():
    behavior = _behavior()
    assert (
        derivation._formal_index_for_matches_message(
            _matches_formula(), behavior, _actual_terms(behavior)
        )
        is None
    )


def test_identity_exit_type_formula_is_not_a_matches_citation():
    behavior = _behavior()
    formula = atomic(
        "identity",
        [
            ctor("python:exit_type", [str_const("exit_face")]),
            make_var("expected_exception"),
        ],
    )
    assert derivation._matches_call_of_exit_value(formula) is None
    assert (
        derivation._formal_index_for_matches_expected(
            formula, behavior, _actual_terms(behavior)
        )
        is None
    )


def test_assertionerror_halt_complements_the_true_return():
    guard = atomic("py.truthy", [make_var("matches-result")])
    halted = Halted(
        guard,
        RaiseEffect.for_builtin("AssertionError", blame="raises.py:711"),
    )
    completed = Completed(
        complement_guard(guard),
        BlockValue(
            (ReturnValue(TrueBoolLiteralSugar(site='return-true')),),
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
        BlockValue((fail, ReturnValue(TrueBoolLiteralSugar(site='return-true'))), can_fall_through=False),
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
        BlockValue((fill, ReturnValue(TrueBoolLiteralSugar(site='return-true'))), can_fall_through=False),
    )
    assert not derivation._completed_faces_have_bodyless_free_calls(
        ExitSet((completed,))
    )


def _no_effect_formula(exit_face_id="exit-face"):
    return atomic(
        "identity",
        [
            ctor("python:exit_type", [str_const(exit_face_id)]),
            ctor("None", []),
        ],
    )


def _nested_did_not_raise_exit(*, match_value=None, extra_actuals=()):
    slot = BranchResultSlot("branch-result:exc-type-is-none")
    absent = branch_result_guard(slot, "if-exc-type-is-none")
    matches = _matches_formula()
    fail_halt = Halted(
        absent,
        RaiseEffect.for_builtin("RuntimeError", blame="support.py:3"),
    )
    match_halt = Halted(
        and_([not_(absent), not_(matches)]),
        RaiseEffect.for_builtin("AssertionError", blame="raises.py:711"),
    )
    completed = Completed(
        and_([not_(absent), matches]),
        BlockValue(
            (
                BranchResultAuthentication(slot, _no_effect_formula(), "if-exc-type-is-none"),
                ReturnValue(TrueBoolLiteralSugar(site="return-true")),
            ),
            can_fall_through=False,
        ),
    )
    return (
        _behavior(match=match_value, extra_actuals=extra_actuals),
        SimpleNamespace(exit_face_id="exit-face"),
        ExitSet((fail_halt, match_halt, completed)),
        fail_halt,
        match_halt,
    )


def test_matches_formula_inside_and_still_cites_expected():
    behavior = _behavior()
    formula = and_([not_(_no_effect_formula()), _matches_formula()])
    assert (
        derivation._formal_index_for_matches_expected(
            formula, behavior, _actual_terms(behavior)
        )
        == 0
    )


def test_nested_not_matches_halt_shares_prefix_with_true_return():
    _behavior_unused, _protocol, exit_set, fail_halt, match_halt = (
        _nested_did_not_raise_exit()
    )
    assert not derivation._halt_complements_true_return(fail_halt, exit_set)
    assert not derivation._halt_complements_true_return(match_halt, exit_set)
    assert not derivation._halt_negates_matches_conjunct_of_true_return(
        fail_halt, exit_set
    )
    assert derivation._halt_negates_matches_conjunct_of_true_return(
        match_halt, exit_set
    )


def test_nested_exit_with_match_formal_seals_expects_and_message():
    boom = StringValue("boom")
    behavior, protocol, exit_set, _fail, _match = _nested_did_not_raise_exit(
        match_value=boom,
        extra_actuals=(boom,),
    )
    result = derivation._derive_effect_boundary(exit_set, protocol, behavior)
    assert isinstance(result, EffectBoundarySemanticsV1)
    assert isinstance(result.mode, ExpectsModeV1)
    assert result.expected_type_operand == FormalArgumentProjectionV1(0)
    assert result.message_pattern_operand == OptionalFormalArgumentProjectionV1(1)


def test_nested_exit_with_seeded_none_match_seals_expects_without_message():
    from sugar_lift_py_tests.context_manager_contract import NoMessagePatternV1

    behavior, protocol, exit_set, _fail, _match = _nested_did_not_raise_exit()
    result = derivation._derive_effect_boundary(exit_set, protocol, behavior)
    assert isinstance(result, EffectBoundarySemanticsV1)
    assert isinstance(result.mode, ExpectsModeV1)
    assert result.expected_type_operand == FormalArgumentProjectionV1(0)
    assert isinstance(result.message_pattern_operand, NoMessagePatternV1)


def test_nested_exit_with_unprojected_match_does_not_invent_no_message():
    boom = StringValue("boom")
    behavior, protocol, exit_set, _fail, _match = _nested_did_not_raise_exit(
        match_value=boom,
    )
    assert derivation._derive_effect_boundary(exit_set, protocol, behavior) is None

