from __future__ import annotations

import pytest

from factory_reduce import compose_block

from sugar_lift_py_tests.factory import FactoryGap
from sugar_lift_py_tests.floor import BlockValue, ReturnValue, SupportValue, TermValue


def test_expression_statement_reduces_to_inert_support_in_block() -> None:
    block = compose_block("    1\n    return 2\n")

    assert block == BlockValue((ReturnValue(TermValue(2)),))


def test_expression_statement_does_not_replace_docstring_comment_sugar() -> None:
    block = compose_block('    "doc"\n')

    assert block == BlockValue(())
    assert SupportValue.non_fol_support is True


def test_expression_statement_propagates_refused_inner_expression() -> None:
    with pytest.raises(FactoryGap, match="observed=Set"):
        compose_block("    {1}\n    return 2\n")
