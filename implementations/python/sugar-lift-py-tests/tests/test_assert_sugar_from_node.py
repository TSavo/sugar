"""`assert 1 == 1` → sugar, the first full statement through the tree.

Source string, parsed, the Assert node asked for its sugar: an AssertSugar
whose `test` is the EqualityOpSugar the Compare node produced — the whole
recursion, Assert → Compare → two Constants, all node.sugar() calling
node.sugar(). No factory in the chain. The message operand is provenance
only (never a child sugar): AssertSugar never builds or reduces it.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from sugar_source_tree.tree import SourceFile
from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.sugar.assert_sugar import AssertSugar
from sugar_lift_py_tests.sugar.equality_op_sugar import EqualityOpSugar
from sugar_lift_py_tests.sugar.int_literal_sugar import IntLiteralSugar


def _assert_node(source: str):
    fh = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False)
    fh.write(source)
    fh.close()
    try:
        sf = SourceFile(path_source(fh.name))
        (node,) = [n for n in sf if n.kind == "Assert"]
        return node
    finally:
        Path(fh.name).unlink()


def test_source_string_assert_one_equals_one_gives_back_assert_sugar():
    node = _assert_node("assert 1 == 1\n")
    sugar = node.sugar()
    assert isinstance(sugar, AssertSugar)


def test_the_assert_sugars_test_is_the_equality_it_wraps():
    node = _assert_node("assert 1 == 1\n")
    sugar = node.sugar()
    # the test is the Compare node's own sugar, held whole — the recursion
    assert isinstance(sugar.test, EqualityOpSugar)
    assert isinstance(sugar.test.left, IntLiteralSugar) and sugar.test.left.value == 1
    assert isinstance(sugar.test.right, IntLiteralSugar) and sugar.test.right.value == 1


def test_a_bare_assert_holds_its_terms_sugar():
    # assert x  — the test is a name; here use a literal so the leaf is written
    node = _assert_node("assert 1\n")
    sugar = node.sugar()
    assert isinstance(sugar, AssertSugar)
    assert isinstance(sugar.test, IntLiteralSugar) and sugar.test.value == 1


def test_the_message_is_provenance_not_a_child_sugar():
    # `assert cond, "msg"` — the message must NOT become a child sugar; the
    # sugar holds only the test. Its presence must not change construction.
    node = _assert_node("assert 1 == 1, 'boom'\n")
    sugar = node.sugar()
    assert isinstance(sugar, AssertSugar)
    assert isinstance(sugar.test, EqualityOpSugar)
    # no `message`/`msg` child sugar slot is populated with a sugar
    assert not hasattr(sugar, "message") or sugar.message is None
