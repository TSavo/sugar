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
from sugar_lift_py_tests.ir import atomic, ctor, make_var, not_, str_const
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
