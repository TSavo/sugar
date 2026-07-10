"""The factory builds an IfSugar from an `if` statement in Python source."""

from __future__ import annotations

import ast

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.sugar.if_sugar import IfSugar


def test_factory_builds_if_sugar() -> None:
    if_node = ast.parse("if True:\n    pass").body[0]
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())

    result = build_node(if_node, filename="t.py", role=SugarRole.STATEMENT, ctx=ctx)

    assert isinstance(result.sugar, IfSugar)
