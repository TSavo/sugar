"""#4387: Derived EUF residue pins ground data ctors, not only primitive consts.

Verifier structural dual refuses `call:A = py.ellipsis` vs `call:A = None`
(and complex / None faces). Residue emission must match that whitelist or the
lying assertion soft-SATs with only a Stated face.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor.call_site_value import (
    CallSiteValue,
    _is_ground_value_term,
)
from sugar_lift_py_tests.floor.predicate_value import PredicateValue
from sugar_lift_py_tests.ir import bool_const, ctor, make_var, num, real_lit, str_const
from sugar_lift_py_tests.outcome import Complete


def test_ground_value_term_accepts_primitive_consts() -> None:
    assert _is_ground_value_term(num(7))
    assert _is_ground_value_term(bool_const(True))
    assert _is_ground_value_term(str_const("x"))
    assert _is_ground_value_term(real_lit("2.0"))


def test_ground_value_term_accepts_verifier_data_ctors() -> None:
    assert _is_ground_value_term(ctor("None", []))
    assert _is_ground_value_term(ctor("py.ellipsis", []))
    assert _is_ground_value_term(ctor("py.complex", [real_lit("0.0"), real_lit("2.0")]))
    assert _is_ground_value_term(ctor("tuple", [num(1), num(2)]))
    assert _is_ground_value_term(ctor("python:bytes", [num(97), num(98)]))
    # Module / type coordinates are structural identities for residue duals.
    assert _is_ground_value_term(ctor("python:module", [str_const("pytest")]))
    assert _is_ground_value_term(ctor("python:type", [str_const("bytes")]))


def test_ground_value_term_rejects_operator_and_call_ctors() -> None:
    assert not _is_ground_value_term(ctor("call:A", [num(5)]))
    assert not _is_ground_value_term(ctor("+", [num(1), num(2)]))
    assert not _is_ground_value_term(
        ctor("py.attr", [ctor("call:m", []), str_const("x")])
    )
    # Nested non-ground arg disqualifies an otherwise-whitelisted ctor.
    assert not _is_ground_value_term(ctor("tuple", [ctor("call:f", [])]))


def test_ground_callsite_truth_panics_before_runtime_effect_authority() -> None:
    term = ctor(
        "py.subscript",
        [
            ctor(
                "py.iter_elem",
                [ctor("array", [ctor("array", [num(1), str_const("x")])])],
            ),
            num(1),
        ],
    )
    site = SourceFragment.from_source("row[1]\n", "t.py").statements()[0]
    value = CallSiteValue(
        target_name="py.subscript",
        arg_values=(),
        parameters=(),
        term=term,
        body=None,
        site=site,
    )

    with pytest.raises(FactoryPanic) as caught:
        value.truth(site)

    assert caught.value.info.owner == "CallSiteValue.truth"


def test_runtime_derived_callsite_truth_remains_a_predicate() -> None:
    site = SourceFragment.from_source("answer(value)\n", "t.py").statements()[0]
    value = CallSiteValue(
        target_name="answer",
        arg_values=(),
        parameters=(),
        term=ctor("call:answer", [make_var("value")]),
        body=None,
        site=site,
    )

    outcome = value.truth(site)

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, PredicateValue)
    assert outcome.value.operand_callsites == (value,)
