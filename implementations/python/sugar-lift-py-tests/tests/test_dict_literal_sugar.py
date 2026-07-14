"""DictLiteralSugar: `{"k": 1, "j": 2}` reduces each key and value; the result is
a dict of those pairs. Order is source order. A bare dict statement is discarded
(expression statement is support). ``**`` merges concrete dictionaries and
retains a named effect when the mapping contents exist only at runtime."""

from __future__ import annotations

import ast

from factory_reduce import compose_block

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.floor import (
    BlockValue,
    DictValue,
    ReturnValue,
    StringValue,
    TermValue,
)
from sugar_lift_py_tests.outcome import Complete


def test_dict_literal_selects_and_reduces_entries() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse('{"k": 1, "j": 2}', mode="eval").body
    result = build_node(node, filename="t.py", role=SugarRole.TERM, ctx=ctx)

    assert result.audit_row.selected == "DictLiteralSugar"
    assert result.sugar.desugar(ctx) == Complete(
        DictValue(
            (
                (StringValue("k"), TermValue(1)),
                (StringValue("j"), TermValue(2)),
            )
        )
    )


def test_empty_dict_literal_reduces_to_empty_dict_value() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse("{}", mode="eval").body
    result = build_node(node, filename="t.py", role=SugarRole.TERM, ctx=ctx)

    assert result.audit_row.selected == "DictLiteralSugar"
    assert result.sugar.desugar(ctx) == Complete(DictValue(()))


def test_bare_dict_statement_is_discarded_in_block() -> None:
    outcome = compose_block('    {"k": 1}\n    return 2\n')

    assert outcome == BlockValue((ReturnValue(TermValue(2)),))


def test_dict_star_star_expansion_selects_dict_literal_owner() -> None:
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    node = ast.parse("{**x}", mode="eval").body
    result = build_node(node, filename="t.py", role=SugarRole.TERM, ctx=ctx)

    assert result.audit_row.selected == "DictLiteralSugar"
