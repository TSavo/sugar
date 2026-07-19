"""#5338 residual A: For→While over dig-opaque array chain must force-curry.

Product hang (scipy/sparse/csgraph/tests/test_shortest_path.py):
  for k in range(n):  # n parametrized to 10/100/1000 → materialize + unfold
      p = pred[k]; s = sources[k]
      while p != -9999:
          assert sources[p] == s
          p = pred[p]

pred/sources from dig-opaque dijkstra return. Static for-unfold × per-k
EqualityOpSugar on opaque subscript was the 30s reduce_body tip.

Replacement: non-ground free names under nested While → single CurriedLoopScope
for the outer for, not per-k Equality reduce. Ground for+while micros still
static-unfold.
"""

from __future__ import annotations

import ast
import time
from dataclasses import replace

from factory_reduce import compose_block

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.block import Block
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.floor import (
    BlockValue,
    CallSiteValue,
    CurriedLoopScope,
    ListValue,
    TermValue,
)
from sugar_lift_py_tests.ir import ctor
from sugar_lift_py_tests.lift_rpc import lift_file_payload
from sugar_lift_py_tests.temporal import TemporalContext


def _opaque_array(name: str = "opaque_array") -> CallSiteValue:
    return CallSiteValue(
        target_name=name,
        arg_values=(),
        parameters=(),
        term=ctor(f"call:{name}", ()),
        body=None,
        site=f"{name}.py:1",
    )


def _reduce_for(body_src: str, binds: dict) -> object:
    """Reduce the sole for-statement of an indented body; return its FloorValue."""
    fn = ast.parse(f"def f(x):\n{body_src}").body[0]
    for_node = next(stmt for stmt in fn.body if isinstance(stmt, ast.For))
    temporal = TemporalContext.empty()
    for name, value in binds.items():
        temporal = temporal.bind_value(name, value)
    ctx = replace(
        FactoryBuildContext(filename="f.py", catalog=default_catalog()),
        temporal=temporal,
    )
    sugar = build_node(
        for_node, filename="f.py", role=SugarRole.STATEMENT, ctx=ctx
    ).sugar
    return sugar.desugar(ctx).value


_PRED_CHAIN_BODY = (
    "    for k in range(1000):\n"
    "        p = pred[k]\n"
    "        s = sources[k]\n"
    "        while p != -9999:\n"
    "            assert sources[p] == s\n"
    "            p = pred[p]\n"
)


def test_nonground_pred_chain_for_while_force_curries_not_hangs() -> None:
    """Opaque pred/sources + for+while chain → CurriedLoopScope, completes fast."""
    opaque = _opaque_array("dijkstra_pred")
    binds = {"pred": opaque, "sources": opaque}
    started = time.perf_counter()
    value = _reduce_for(_PRED_CHAIN_BODY, binds)
    # Full block path must also complete (scope-only contribution is empty).
    block = compose_block(_PRED_CHAIN_BODY, binds=binds)
    elapsed = time.perf_counter() - started

    assert elapsed < 5.0, f"opaque for+while chain hung ({elapsed:.2f}s)"
    assert isinstance(value, CurriedLoopScope), (
        f"expected CurriedLoopScope for non-ground while chain; got {type(value).__name__}"
    )
    assert isinstance(block, BlockValue)


def test_ground_pred_chain_for_while_still_static_unfolds() -> None:
    """Ground lists keep static discharge — not forced into curry by While alone."""
    # Terminal chain: every node ends immediately (p = -9999).
    pred = ListValue(tuple(TermValue(-9999) for _ in range(20)))
    sources = ListValue(tuple(TermValue(0) for _ in range(20)))
    body = (
        "    for k in range(20):\n"
        "        p = pred[k]\n"
        "        s = sources[k]\n"
        "        while p != -9999:\n"
        "            assert sources[p] == s\n"
        "            p = pred[p]\n"
    )
    value = _reduce_for(body, {"pred": pred, "sources": sources})
    assert isinstance(value, BlockValue), (
        f"ground for+while must static-unfold to BlockValue; got {type(value).__name__}"
    )
    assert not isinstance(value, CurriedLoopScope)


def test_parametrize_nonground_pred_chain_lift_completes() -> None:
    """File-shaped instrument: parametrize n∈{10,100,1000} + opaque dig-like call.

    Mirrors product shape without scipy. Opaque arrays arrive as CallSiteValue
    from an undiggable helper return face.
    """
    source = (
        "def opaque_arrays():\n"
        "    return __import__('operator')\n"
        "\n"
        "@pytest.mark.parametrize('n', (10, 100, 1000))\n"
        "def test_pred_chain(n):\n"
        "    pred = opaque_arrays()\n"
        "    sources = opaque_arrays()\n"
        "    for k in range(n):\n"
        "        p = pred[k]\n"
        "        s = sources[k]\n"
        "        while p != -9999:\n"
        "            assert sources[p] == s\n"
        "            p = pred[p]\n"
    )
    started = time.perf_counter()
    payload = lift_file_payload(source, "nonground_pred_chain.py")
    elapsed = time.perf_counter() - started
    assert elapsed < 15.0, f"parametrize opaque pred-chain hung ({elapsed:.2f}s)"
    # Completion under bound is the instrument: shape moved off per-k Equality hang.
    assert payload is not None
