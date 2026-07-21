"""End to end, down the enumeration ladder: one file, one test function, one
`assert 1 == 1`, lifted to sugar.

SourceTree -> SourceFile (source_files)
           -> functions()            (functions: transitive, classes are namespaces)
           -> the function's Assert  (its testimony)
           -> Assert.sugar()         -> AssertSugar(EqualityOpSugar(IntLit 1, IntLit 1))

Every step is a real tree operation over oracle-pinned source. No factory,
no catalog, no owns anywhere in the chain.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from sugar_source_tree.tree import SourceTree
from sugar_source_tree.nodes import Assert, FunctionDef, AsyncFunctionDef
from sugar_lift_py_tests.sugar.assert_sugar import AssertSugar
from sugar_lift_py_tests.sugar.equality_op_sugar import EqualityOpSugar
from sugar_lift_py_tests.sugar.int_literal_sugar import IntLiteralSugar
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.outcome import Complete

VENDOR_TEST_FILE = "def test_one():\n    assert 1 == 1\n"


def _asserts_of(function: FunctionDef):
    return [n for n in function.walk() if isinstance(n, Assert)]


def test_lift_a_single_assertion_all_the_way_to_sugar():
    with tempfile.TemporaryDirectory() as root:
        (Path(root) / "test_demo.py").write_text(VENDOR_TEST_FILE)

        tree = SourceTree(Path(root))

        # source_files: exactly the one file, as a whole-file fragment
        (source_file,) = list(tree.files())

        # functions: exactly the one test function
        functions = list(source_file.functions())
        assert len(functions) == 1
        (test_fn,) = functions
        assert isinstance(test_fn, (FunctionDef, AsyncFunctionDef))
        assert test_fn.name == "test_one"

        # its testimony: exactly one assertion
        (assert_node,) = _asserts_of(test_fn)

        # lift it: the assertion IS its sugar, built by the tree
        sugar = assert_node.sugar()
        assert isinstance(sugar, AssertSugar)
        assert isinstance(sugar.test, EqualityOpSugar)
        assert isinstance(sugar.test.left, IntLiteralSugar)
        assert isinstance(sugar.test.right, IntLiteralSugar)
        assert sugar.test.left.value == 1
        assert sugar.test.right.value == 1

        # and the operands desugar to the number as floor terms
        assert sugar.test.left.desugar() == Complete(TermValue(1))
        assert sugar.test.right.desugar() == Complete(TermValue(1))

        # the whole assertion desugars — no context, no temporal, no factory:
        #   1 == 1 reduces to True; True states its inv; the assert is testimony
        from sugar_lift_py_tests.outcome import Complete as _C
        outcome = sugar.desugar(None)
        assert isinstance(outcome, _C)
        # the assertion EMITS a fact: the vendor asserted 1 == 1, so the record
        # carries the inv `1 = 1` — a real invariant, trivially valid, with NO
        # call site and no contract. Not SupportValue: the assertion owns the
        # emission; the value does not get to opt out because it is ground-true.
        inv = outcome.value
        assert type(inv).__name__ == "InvValue"
        assert inv.operand_callsites == ()          # no call site
        assert inv.formula.name == "="              # the fact is an equality
        assert [a.value for a in inv.formula.args] == [1, 1]   # 1 = 1
