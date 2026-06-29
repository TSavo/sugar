"""A comment (a docstring / bare-string statement) is inert. The factory classifies
it as Support, and CommentSugar desugars to SupportValue -- it ALWAYS completes and
contributes no first-order logic. A non-comment statement is not Support."""
from __future__ import annotations

import ast

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory import SourceSite
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.floor import SupportValue
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar.comment_sugar import CommentSugar


def _support_candidates(stmt_src: str) -> list[str]:
    node = ast.parse(stmt_src).body[0]
    site = SourceSite.from_node(node, "c.py")
    return [c.name for c in default_catalog().candidates_for(SugarRole.STATEMENT, site)]


def test_factory_classifies_a_comment_as_support():
    assert _support_candidates('"a docstring"') == ["CommentSugar"]


def test_non_comment_statements_get_their_own_sugar_not_comment():
    # an assignment is a statement, but it dispatches to AssignSugar -- not Comment.
    assert _support_candidates("x = 1") == ["AssignSugar"]
    # a bare int expression is neither a comment nor any other statement sugar.
    assert _support_candidates("5") == []


def test_comment_desugars_to_support_and_always_completes():
    assert complete_value(CommentSugar().desugar(), owner="comment") == SupportValue()
