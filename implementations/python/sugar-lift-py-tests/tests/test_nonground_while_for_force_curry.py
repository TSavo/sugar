"""#5338 residual A / #5367: finite for+while must not mint opaque success.

Product hang (scipy/sparse/csgraph/tests/test_shortest_path.py):
  for k in range(n):  # n parametrized to 10/100/1000 → materialize + unfold
      p = pred[k]; s = sources[k]
      while p != -9999:
          assert sources[p] == s
          p = pred[p]

pred/sources from dig-opaque dijkstra return. Static for-unfold × per-k
EqualityOpSugar on opaque subscript was the 30s reduce_body tip.

Law (#5367 / #5375 / #5383 / compact projection): finite authenticated history
may not become force-curry opacity. Non-ground while under a finite for uses
the shared recognition projection door (one body under py.iter_elem) — never
N-fold Equality, never force-curry Complete, never soft success.
Ground for+while micros still static-unfold.
"""

from __future__ import annotations

import ast
from dataclasses import replace

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
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


def test_nonground_pred_chain_for_while_projects_compact_not_opaque() -> None:
    """Finite opaque for+while projects once — never force-curry Complete."""
    opaque = _opaque_array("dijkstra_pred")
    binds = {"pred": opaque, "sources": opaque}
    value = _reduce_for(_PRED_CHAIN_BODY, binds)
    assert not isinstance(value, CurriedLoopScope), (
        "finite non-ground while must not force-curry; " f"got {type(value).__name__}"
    )
    # Recognition projection yields a block/scope splice, not a finite_unfold panic.
    assert value is not None


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
    assert isinstance(
        value, BlockValue
    ), f"ground for+while must static-unfold to BlockValue; got {type(value).__name__}"
    assert not isinstance(value, CurriedLoopScope)


def test_parametrize_nonground_pred_chain_lift_not_finite_unfold() -> None:
    """File-shaped instrument: compact projection drains finite_unfold owner."""
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
    try:
        payload = lift_file_payload(source, "nonground_pred_chain.py")
    except FactoryPanic as panic:
        assert panic.value.info.owner != "finite_unfold", panic.value.info
        return
    assert payload is not None
