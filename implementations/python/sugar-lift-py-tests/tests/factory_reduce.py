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
from sugar_lift_py_tests.outcome import Incomplete, complete_value
from sugar_lift_py_tests.temporal import TemporalContext


def compose_block(body_src: str, binds: dict | None = None):
    """Compose a function-body suite through the factory at the STATEMENT role: the
    Block dispatches to BlockSugar, which composes its statement children. Returns the
    BlockValue. `body_src` is the indented body of `def f(x): ...`."""
    from sugar_lift_py_tests.claim import SugarRole
    from sugar_lift_py_tests.factory.block import Block
    from sugar_lift_py_tests.factory.build import build_node

    fn = ast.parse(f"def f(x):\n{body_src}").body[0]
    block = Block.of(fn.body)
    ctx = FactoryBuildContext(filename="f.py", catalog=default_catalog())
    if binds:
        temporal = TemporalContext.empty()
        for name, value in binds.items():
            temporal = temporal.bind_value(name, value)
        ctx = replace(ctx, temporal=temporal)
    result = build_node(block, filename="f.py", role=SugarRole.STATEMENT, ctx=ctx)
    outcome = result.sugar.desugar(ctx)
    if isinstance(outcome, Incomplete):
        return outcome  # the body raised (an effect) -- surface it, do not force-read
    return complete_value(outcome, owner="block")


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


def _array_map_ctx(binds: dict | None = None):
    from sugar_lift_py_tests.factory.array_map_report import _array_map_catalog

    ctx = FactoryBuildContext(filename="t.py", catalog=_array_map_catalog())
    if binds:
        temporal = TemporalContext.empty()
        for name, value in binds.items():
            temporal = temporal.bind_value(name, value)
        ctx = replace(ctx, temporal=temporal)
    return ctx


def array_map_build(expr: str):
    """Build (but do not reduce) the SugarBody for `expr` on the array-map path --
    e.g. the opaque body a lambda is handed."""
    node = ast.parse(expr, mode="eval").body
    return _array_map_ctx().build_body(node, SugarRole.TERM)


def array_map_reduce(expr: str, binds: dict | None = None):
    """Reduce `expr` through the ARRAY-MAP catalog (map/list/range/lambda/add) and
    return the raw Floor value (these sugars transform to concrete values)."""
    ctx = _array_map_ctx(binds)
    node = ast.parse(expr, mode="eval").body
    return complete_value(ctx.build_body(node, SugarRole.TERM).reduce(ctx), owner="test")


def array_map_pairs(source: str):
    """Drive the array-map factory over `source` (a function whose body asserts an
    array/map/list expression equals a literal) and return the pointwise
    (transformed, expected) value pairs of the array-map contract's equality
    conjunction. This is the COMPOSITION: the map/list/range sugar transforms its
    downstream sugars, and the pairs are that transformed result vs the asserted
    expected. All-equal => sat; any unequal => the discrimination (unsat)."""
    from sugar_lift_py_tests.factory.array_map_report import build_array_map_report

    rep = build_array_map_report(source=source, filename="t.py", memento_file="t.py")
    contract = next(
        c for c in rep.payload.ir if str(getattr(c, "name", "")).endswith("::array-map-sugar")
    )
    inv = contract.inv
    assert inv["kind"] == "and", inv
    return [(op["args"][0]["value"], op["args"][1]["value"]) for op in inv["operands"]]
