"""`assert 1 == 1` → sugar, the first full statement through the tree.

Source string, parsed, the Assert node asked for its sugar: an AssertSugar
whose `test` is the EqualityOpSugar the Compare node produced — the whole
recursion, Assert → Compare → two Constants, all node.sugar() calling
node.sugar(). No factory in the chain. The message operand is a child built
with the test (its spelling rides ``assertMessage`` provenance); it is
evaluated only where the assert fails.
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


def test_assert_with_message_builds_and_carries_message_provenance():
    node = _assert_node("assert 1 == 1, 'boom'\n")
    sugar = node.sugar()
    outcome = sugar.desugar()

    assert isinstance(sugar, AssertSugar)
    assert sugar.message == node.msg.sugar()
    support = outcome.completed_value()
    assert support is not None
    assert support.site.memento().extra["assertMessage"] == "'boom'"
    assert support.site.memento().to_rpc()["assertMessage"] == "'boom'"


def test_assert_support_retains_its_own_occurrence_not_a_foreign_site():
    left = _assert_node("assert 1 == 1, 'left'\n")
    right = _assert_node("assert 1 == 1, 'right'\n")

    left_support = left.sugar().desugar().completed_value()
    right_support = right.sugar().desugar().completed_value()

    assert left_support.site == left.fragment
    assert right_support.site == right.fragment
    assert left_support.site != right_support.site


def test_an_unbuilt_message_refuses_the_assert_at_construction():
    # The message is a child built with the statement: one with no sugar
    # refuses the assert by name, even where the assert cannot fail. ``await``
    # is a node with no sugar written (``Yield`` has one now, see below).
    import pytest

    from sugar_source_tree.panic import SugarNotWritten

    node = _assert_node("assert 1 == 1, (await 2)\n")
    with pytest.raises(SugarNotWritten) as refused:
        node.sugar()
    assert refused.value.owner == "Await.sugar"


def test_unbuilt_condition_child_preserves_its_own_gap():
    import pytest

    from sugar_source_tree.panic import SugarNotWritten

    node = _assert_node("assert (await 1)\n")
    with pytest.raises(SugarNotWritten) as refused:
        node.sugar()
    assert refused.value.owner == "Await.sugar"


def test_a_yield_child_is_built_with_the_statement():
    # ``Yield`` constructs its own sugar, so an assert holding one as its
    # message or its test is built whole: the child is the Yield node's sugar.
    from sugar_lift_py_tests.sugar.yield_suspension_sugar import (
        YieldSuspensionSugar,
    )

    message = _assert_node("assert 1 == 1, (yield 2)\n")
    assert isinstance(message.sugar().message, YieldSuspensionSugar)
    assert message.sugar().message == message.msg.sugar()

    test = _assert_node("assert (yield 1)\n")
    assert isinstance(test.sugar().test, YieldSuspensionSugar)
    assert test.sugar().test == test.test.sugar()
