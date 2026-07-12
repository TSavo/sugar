from __future__ import annotations

import ast

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory.build import build_node
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.lift_rpc import audit_lift_file


def test_static_range_unfolds_mid_loop_first_binding_across_iterations() -> None:
    source = (
        "def f():\n"
        "    total = 0\n"
        "    for comp in range(0, 3):\n"
        "        if comp == 0:\n"
        "            first = 7\n"
        "        total += first\n"
        "    return total\n"
    )
    _payload, gaps = audit_lift_file(source, "static.py", hold_panic=True)
    assert not [gap for gap in gaps if gap.info.get("observed") == "first"]


def test_symbolic_range_keeps_deferred_curry() -> None:
    node = ast.parse("for i in range(stop):\n    if i:\n        break\n").body[0]
    sugar = build_node(node, filename="symbolic.py", role=SugarRole.STATEMENT).sugar
    assert sugar.static_elements is None
    assert sugar.curried is True


def test_static_unfold_cap_panics_loudly() -> None:
    node = ast.parse("for i in range(65):\n    pass\n").body[0]
    with pytest.raises(FactoryPanic, match="at most 64 concrete loop self-applications"):
        build_node(node, filename="large.py", role=SugarRole.STATEMENT)


def test_literal_tuple_is_structurally_static() -> None:
    node = ast.parse("for i in (1, 2, 3):\n    pass\n").body[0]
    sugar = build_node(node, filename="tuple.py", role=SugarRole.STATEMENT).sugar
    assert len(sugar.static_elements) == 3
