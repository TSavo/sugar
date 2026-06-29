"""Shared harness for the per-sugar ProofIR tests (NOT a test module).

Each `test_<sugar>.py` feeds a Python fragment through the factory and asserts the
exact first-order-logic term it reduces to. This module is the one place that
knows HOW to drive the factory; every sugar gets its own test file."""
from __future__ import annotations

import ast
from dataclasses import replace

from sugar_lift_py_tests.canonicalizer import encode_jcs
from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.factory.literal_call_report import _floor_to_term
from sugar_lift_py_tests.ir import term_to_value
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.temporal import TemporalContext


def reduce_value(expr: str, binds: dict | None = None):
    """Feed a Python expression and return the raw Floor value it reduces to (before
    the ProofIR projection). Use when the value is not a plain term (e.g. an
    EncodedStringValue)."""
    node = ast.parse(expr, mode="eval").body
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    if binds:
        temporal = TemporalContext.empty()
        for name, value in binds.items():
            temporal = temporal.bind_value(name, value)
        ctx = replace(ctx, temporal=temporal)
    return complete_value(ctx.build_body(node, SugarRole.TERM).reduce(ctx), owner="test")


def reduce_term(expr: str, binds: dict | None = None):
    """Feed a Python expression, reduce it through the factory's default catalog,
    and return the ProofIR term it emits. `binds` supplies the symbolic carrier of
    any free name (what a function parameter would be bound to)."""
    return _floor_to_term(reduce_value(expr, binds))


def fol(term) -> str:
    """Canonical wire form of a ProofIR term -- two formulations are the same logic
    iff this string matches."""
    return encode_jcs(term_to_value(term))
