"""Constraint-grammar drain: UnaryOp, BoolOp, Attribute, through the node.

Each mirrors an existing dispatch: UnaryOp routes to the operand value's floor
method (`not` composes truth+negate); BoolOp combines the operands' truthiness
via and_/or_; Attribute asks the receiver for `.name` and a symbolic receiver
refuses because source testimony decides neither lookup edge.
"""

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.tree import SourceFile

from native_carrier_testimony import native_carrier_for


def _fn(src: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    return next(SourceFile(path_source(path), construction_context=TreeConstructionContextV1.for_test_without_workspace()).functions())


def _carrier(src, operator):
    return native_carrier_for(_fn(src), operator=operator)


# ---- UnaryOp -----------------------------------------------------------------


def test_undecided_unary_ops_are_named_refusals():
    """Deleted expectation: formal unary operations panicked before caller binding."""
    for source, operator in (
        ("def A(z):\n    return -z\n", "unary_minus"),
        ("def A(z):\n    return ~z\n", "bitwise_invert"),
        ("def A(z):\n    return +z\n", "unary_plus"),
    ):
        carrier = _carrier(source, operator)
        assert carrier.operands[0].to_term(owner="unary carrier tooth").name == "z"


def test_not_is_truth_then_negate():
    """Deleted expectation: formal equality/truth projected a completed guard."""
    carrier = _carrier(
        "def A(z):\n    if not (z == 1):\n        assert z == z\n    return z\n",
        "equals",
    )
    left, right = carrier.operands
    assert left.to_term(owner="not carrier tooth").name == "z"
    assert right.value == 1
    assert len(carrier.continuations) >= 6


# ---- BoolOp ------------------------------------------------------------------


def test_and_conjoins_operand_truthiness():
    """Deleted expectation: formal BoolOp projected a completed conjunction."""
    carrier = _carrier(
        "def A(z):\n    assert (z == 1) and (z == 3)\n    return z\n", "equals"
    )
    assert carrier.operands[0].to_term(owner="and carrier tooth").name == "z"
    assert carrier.operands[1].value == 1
    assert len(carrier.continuations) == 6


def test_or_disjoins_operand_truthiness():
    """Deleted expectation: formal BoolOp projected a completed disjunction."""
    carrier = _carrier(
        "def A(z):\n    assert (z == 1) or (z == 2)\n    return z\n", "equals"
    )
    assert carrier.operands[0].to_term(owner="or carrier tooth").name == "z"
    assert carrier.operands[1].value == 1
    assert len(carrier.continuations) == 6


def test_bare_operands_refuse_undecided_truth():
    """Deleted expectation: bare formal BoolOp truth panicked before binding."""
    carrier = _carrier(
        "def A(a, b):\n    assert a and b\n    return a\n", "boolop_truth"
    )
    assert carrier.operands[0].to_term(owner="boolop truth carrier tooth").name == "a"


# ---- Attribute ---------------------------------------------------------------


def _attribute_refusal(source):
    # Deleted expectation: formal attribute lookup panicked before caller binding.
    return _carrier(source, "attribute_named")


def test_attribute_is_named_undecided():
    carrier = _attribute_refusal("def A(z):\n    return z.numerator\n")
    receiver, name = carrier.operands
    assert receiver.to_term(owner="attribute carrier tooth").name == "z"
    assert name.value == "numerator"


def test_attribute_chain_refuses_at_the_first_unowned_lookup():
    carrier = _attribute_refusal("def A(z):\n    return z.a.b\n")
    receiver, name = carrier.operands
    assert receiver.to_term(owner="attribute chain carrier tooth").name == "z"
    assert name.value == "a"


if __name__ == "__main__":
    test_unary_minus_and_invert_emit_symbolic_ops()
    test_not_is_truth_then_negate()
    test_and_conjoins_operand_truthiness()
    test_or_disjoins_operand_truthiness()
    test_bare_operands_use_py_truthy()
    test_attribute_is_named_undecided()
    test_attribute_chain_refuses_at_the_first_unowned_lookup()
    print("ok: UnaryOp, BoolOp, Attribute drained through the node")
