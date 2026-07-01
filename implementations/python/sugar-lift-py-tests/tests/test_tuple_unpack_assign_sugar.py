from __future__ import annotations

import ast

from factory_reduce import compose_block

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory.build import build_node
from sugar_lift_py_tests.floor import BlockValue, ReturnValue, SymbolicValue
from sugar_lift_py_tests.ir import ctor, make_var, num


def test_tuple_unpack_assign_binds_projection_from_symbolic_rhs() -> None:
    assert compose_block(
        "    x, y = values\n    return y\n",
        binds={"values": SymbolicValue(make_var("values"))},
    ) == BlockValue(
        (ReturnValue(SymbolicValue(ctor("py.unpack", [make_var("values"), num(1)]))),)
    )


def test_list_unpack_assign_binds_projection_from_symbolic_rhs() -> None:
    assert compose_block(
        "    [x, y] = values\n    return x\n",
        binds={"values": SymbolicValue(make_var("values"))},
    ) == BlockValue(
        (ReturnValue(SymbolicValue(ctor("py.unpack", [make_var("values"), num(0)]))),)
    )


def test_tuple_unpack_assign_selects_dedicated_sugar_for_non_literal_rhs() -> None:
    result = build_node(
        ast.parse("x, y = values").body[0],
        filename="f.py",
        role=SugarRole.STATEMENT,
    )

    assert result.audit_row.selected == "TupleUnpackAssignSugar"
