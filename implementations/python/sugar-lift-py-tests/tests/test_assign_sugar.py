"""AssignSugar: `x = <expr>` is a BoundVar -- the name aliases the rhs SOURCE, not
a snapshot of its value. The block threads the binding as a let (support: nothing
joins the record); a reference recomposes the source against the DEFINITION scope
so `x = x + 1` reads the OLD x. Tuple targets stay a loud factory gap."""

from __future__ import annotations

import ast

import pytest

from factory_reduce import compose_block

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import (
    BlockValue,
    ReturnValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.ir import make_var


def test_assign_bind_then_read_folds() -> None:
    assert compose_block("    x = 1\n    return x\n") == BlockValue(
        (ReturnValue(TermValue(1)),)
    )


def test_rebind_reads_the_old_x() -> None:
    # BoundVar.scope is the DEFINITION ctx -- `x = x + 1` terminates on the old x.
    assert compose_block("    x = 1\n    x = x + 1\n    return x\n") == BlockValue(
        (ReturnValue(TermValue(2)),)
    )


def test_assign_aliases_a_symbolic_carrier() -> None:
    assert compose_block(
        "    x = z\n    return x\n",
        binds={"z": SymbolicValue(make_var("z"))},
    ) == BlockValue((ReturnValue(SymbolicValue(make_var("z"))),))


def test_assignment_contributes_nothing_to_the_record() -> None:
    # The record holds ONLY the ReturnValue -- the assign is support (a let).
    record = compose_block("    x = 1\n    return x\n")
    assert record == BlockValue((ReturnValue(TermValue(1)),))
    assert len(record.statements) == 1


def test_starred_tuple_target_is_a_loud_factory_gap() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse("a, *b = 1, 2\n").body[0]
    with pytest.raises(FactoryPanic):
        build_node(node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)
