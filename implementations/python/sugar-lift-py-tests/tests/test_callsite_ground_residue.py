"""#4387: Derived EUF residue pins ground data ctors, not only primitive consts.

Verifier structural dual refuses `call:A = py.ellipsis` vs `call:A = None`
(and complex / None faces). Residue emission must match that whitelist or the
lying assertion soft-SATs with only a Stated face.
"""

from __future__ import annotations

from sugar_lift_py_tests.floor.call_site_value import _is_ground_value_term
from sugar_lift_py_tests.ir import bool_const, ctor, num, real_lit, str_const


def test_ground_value_term_accepts_primitive_consts() -> None:
    assert _is_ground_value_term(num(7))
    assert _is_ground_value_term(bool_const(True))
    assert _is_ground_value_term(str_const("x"))
    assert _is_ground_value_term(real_lit("2.0"))


def test_ground_value_term_accepts_verifier_data_ctors() -> None:
    assert _is_ground_value_term(ctor("None", []))
    assert _is_ground_value_term(ctor("py.ellipsis", []))
    assert _is_ground_value_term(
        ctor("py.complex", [real_lit("0.0"), real_lit("2.0")])
    )
    assert _is_ground_value_term(ctor("tuple", [num(1), num(2)]))
    assert _is_ground_value_term(ctor("python:bytes", [num(97), num(98)]))


def test_ground_value_term_rejects_operator_and_call_ctors() -> None:
    assert not _is_ground_value_term(ctor("call:A", [num(5)]))
    assert not _is_ground_value_term(ctor("+", [num(1), num(2)]))
    assert not _is_ground_value_term(ctor("py.attr", [ctor("call:m", []), str_const("x")]))
    # Nested non-ground arg disqualifies an otherwise-whitelisted ctor.
    assert not _is_ground_value_term(ctor("tuple", [ctor("call:f", [])]))
