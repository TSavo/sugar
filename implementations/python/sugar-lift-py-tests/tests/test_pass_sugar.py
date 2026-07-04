from __future__ import annotations

import ast

from factory_reduce import compose_block

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory.build import build_node
from sugar_lift_py_tests.floor import BlockValue, ReturnValue, SupportValue, TermValue
from sugar_lift_py_tests.lib import lift_source
from sugar_lift_py_tests.outcome import complete_value


def test_pass_selects_inert_statement_support():
    result = build_node(
        ast.parse("pass").body[0],
        filename="f.py",
        role=SugarRole.STATEMENT,
    )

    assert result.audit_row.selected == "PassSugar"
    assert complete_value(result.sugar.desugar(), owner="pass") == SupportValue()


def test_pass_support_does_not_swallow_following_return():
    assert compose_block("    pass\n    return 5\n") == BlockValue(
        (ReturnValue(TermValue(5)),)
    )


def test_lift_source_builds_statement_fragment_as_statement_support():
    result = lift_source(
        "f.py",
        "try:\n" "    risky()\n" "except ImportError:\n" "    pass\n",
    )

    assert result.audit_row.role == "statement"
    assert result.audit_row.selected == "PassSugar"
