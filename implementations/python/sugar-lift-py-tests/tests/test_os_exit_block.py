"""End to end: a block that halts on os.exit short-circuits. The factory builds the
`if`, the True condition dispatches to the then-block, and the block reduces its
statements in order until os.exit halts it -- everything after stays unresolved.

The block record holds floor values (not Complete wrappers). Incomplete contributes
itself; unreached tail stays raw sugar.

    if True:
        True          -> TrueBoolLiteralSugar (value contributes itself)
        False         -> FalseBoolLiteralSugar (value contributes itself)
        os.exit(0)    -> Incomplete(OSExitRuntimeEffect)   <- halts
        True          -> unresolved sugar (never reduced)
        False         -> unresolved sugar
"""

from __future__ import annotations

import ast

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.effect import OSExitRuntimeEffect
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.outcome import Incomplete
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_lift_py_tests.sugar_body import SugarBody

_SOURCE = "if True:\n    True\n    False\n    os.exit(0)\n    True\n    False\n"


def test_block_short_circuits_on_os_exit() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse(_SOURCE).body[0]

    record = build_node(
        node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx
    ).sugar.desugar(ctx).value.statements

    assert len(record) == 5

    # ran, in order -- floor values contribute themselves
    assert isinstance(record[0], TrueBoolLiteralSugar)
    assert isinstance(record[1], FalseBoolLiteralSugar)

    # halted here -- the effect entry is the Incomplete
    assert isinstance(record[2], Incomplete)
    assert isinstance(record[2].effect, OSExitRuntimeEffect)

    # unreachable: kept as raw, unreduced sugar -- NOT outcomes
    assert isinstance(record[3], SugarBody)
    assert isinstance(record[4], SugarBody)
