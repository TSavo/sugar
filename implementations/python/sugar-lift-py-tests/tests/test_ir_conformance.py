# SPDX-License-Identifier: MIT OR Apache-2.0
#
# Pinned Rust→Python conformance tests for full IR formulas. The JCS string
# and BLAKE3-512 hash literals come from
# implementations/rust/examples/layer2_py_probe.rs.

from __future__ import annotations

from sugar_lift_py_tests.canonicalizer import encode_jcs, jcs_hash
from sugar_lift_py_tests.ir import (
    Int,
    and_,
    atomic,
    connective,
    ctor,
    eq,
    formula_to_value,
    gte,
    implies,
    lt,
    make_var,
    num,
    str_const,
)

# Expected JCS bytes. Identical to Rust output captured 2026-04-30.
PATTERN1_JCS = (
    '{"body":{"kind":"implies","operands":'
    '[{"kind":"and","operands":'
    '[{"args":[{"kind":"var","name":"x"},'
    '{"kind":"const","sort":{"kind":"primitive","name":"Int"},"value":0}],'
    '"kind":"atomic","name":"≥"},'
    '{"args":[{"kind":"var","name":"x"},'
    '{"kind":"const","sort":{"kind":"primitive","name":"Int"},"value":100}],'
    '"kind":"atomic","name":"<"}]},'
    '{"args":[{"kind":"var","name":"x"},'
    '{"kind":"const","sort":{"kind":"primitive","name":"Int"},"value":0}],'
    '"kind":"atomic","name":"≥"}]},'
    '"kind":"forall","name":"x","sort":{"kind":"primitive","name":"Int"}}'
)
PATTERN1_HASH = (
    "blake3-512:edace2a0634b696ec24a369d37580cf9ab77f2d7c3e83869240b77305aaefc48"
    "68054bc3cee789f74408e1adf0b1d88e6fdfcd9cc2e351ff586077dbb3a3bcea"
)

EQ_JCS = (
    '{"args":[{"args":[{"kind":"const","sort":{"kind":"primitive","name":"String"},'
    '"value":"42"}],"kind":"ctor","name":"parse_int"},'
    '{"kind":"const","sort":{"kind":"primitive","name":"Int"},"value":42}],'
    '"kind":"atomic","name":"="}'
)
EQ_HASH = (
    "blake3-512:5eade72c08811b2d38adcb158eced38f3d319de090d59b2fa7a77ad830169e18"
    "539d2b75d2a2838c545e644a688cf137603674523ff37f1586a650f6dd05aeaa"
)


def test_pattern1_bounded_loop_jcs_matches_rust():
    var = make_var("x")
    lower = gte(var, num(0))
    upper = lt(var, num(100))
    antecedent = and_([lower, upper])
    inner = gte(var, num(0))
    body = implies(antecedent, inner)
    from sugar_lift_py_tests.ir import _Quantifier  # type: ignore

    q = _Quantifier("forall", "x", Int(), body)
    v = formula_to_value(q)
    assert encode_jcs(v) == PATTERN1_JCS


def test_pattern1_bounded_loop_hash_matches_rust():
    var = make_var("x")
    body = implies(
        and_([gte(var, num(0)), lt(var, num(100))]),
        gte(var, num(0)),
    )
    from sugar_lift_py_tests.ir import _Quantifier  # type: ignore

    q = _Quantifier("forall", "x", Int(), body)
    v = formula_to_value(q)
    assert jcs_hash(v) == PATTERN1_HASH


def test_eq_atomic_jcs_matches_rust():
    lhs = ctor("parse_int", [str_const("42")])
    f = eq(lhs, num(42))
    v = formula_to_value(f)
    assert encode_jcs(v) == EQ_JCS


def test_eq_atomic_hash_matches_rust():
    lhs = ctor("parse_int", [str_const("42")])
    f = eq(lhs, num(42))
    v = formula_to_value(f)
    assert jcs_hash(v) == EQ_HASH
