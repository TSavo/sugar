"""Constraint-grammar drain: UnaryOp, BoolOp, Attribute, through the node.

Each mirrors an existing dispatch: UnaryOp routes to the operand value's floor
method (`not` composes truth+negate); BoolOp combines the operands' truthiness
via and_/or_; Attribute asks the receiver for `.name` and a symbolic receiver
is the two-faced undecided read because source testimony decides neither
lookup edge.
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
    # The block's statement tail waits as an ExitSet-wide step
    # (``after_discharge``), not as a continuation.
    assert len(carrier.continuations) >= 5


# ---- BoolOp ------------------------------------------------------------------


def test_and_conjoins_operand_truthiness():
    """Deleted expectation: formal BoolOp projected a completed conjunction."""
    carrier = _carrier(
        "def A(z):\n    assert (z == 1) and (z == 3)\n    return z\n", "equals"
    )
    assert carrier.operands[0].to_term(owner="and carrier tooth").name == "z"
    assert carrier.operands[1].value == 1
    assert len(carrier.continuations) == 5


def test_or_disjoins_operand_truthiness():
    """Deleted expectation: formal BoolOp projected a completed disjunction."""
    carrier = _carrier(
        "def A(z):\n    assert (z == 1) or (z == 2)\n    return z\n", "equals"
    )
    assert carrier.operands[0].to_term(owner="or carrier tooth").name == "z"
    assert carrier.operands[1].value == 1
    assert len(carrier.continuations) == 5


def test_bare_operands_refuse_undecided_truth():
    """Deleted expectation: bare formal BoolOp truth panicked before binding."""
    carrier = _carrier(
        "def A(a, b):\n    assert a and b\n    return a\n", "boolop_truth"
    )
    assert carrier.operands[0].to_term(owner="boolop truth carrier tooth").name == "a"


# ---- Attribute ---------------------------------------------------------------


def _attribute_operations(node, found, depth=0):
    """Every ``python:attribute_result("<name>", <receiver>, <key>)`` in
    ``node`` -- a parameter's read, keyed per evaluation
    (``floor_value.undecided_attribute_result``): ``(receiver name,
    attribute name)``."""
    if depth > 64:
        return found
    if getattr(node, "name", None) == "python:attribute_result":
        name, receiver = node.args[0], node.args[1]
        found.append((getattr(receiver, "name", None), name.value))
    for child in (
        *(getattr(node, "args", ()) or ()),
        *(getattr(node, "operands", ()) or ()),
    ):
        _attribute_operations(child, found, depth + 1)
    return found


def _undecided_read(source):
    """A formal's attribute read in the function's own proof: the one
    two-faced undecided read (``SymbolicValue.attribute``), never an
    ``attribute_named`` carrier waiting on a caller's actual (#7757 audit 2
    row NEW-1): its halt kept, never one completed value.  Returns the
    ``(receiver, name)`` the read's halt names."""
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )
    from sugar_lift_py_tests.outcome import ExitSet

    outcome = _fn(source).sugar().desugar()
    assert not isinstance(outcome, NativeOperationExitCarrierV1), outcome
    assert isinstance(outcome, ExitSet), outcome
    assert outcome.completed_value() is None
    (halt,) = [
        face
        for face in outcome.halts()
        if face.effect.producer_node_owner == "SymbolicValue.attribute"
    ]
    (operation,) = _attribute_operations(halt.guard, [])
    return operation


def test_attribute_is_named_undecided():
    assert _undecided_read("def A(z):\n    return z.numerator\n") == ("z", "numerator")


def test_attribute_chain_refuses_at_the_first_unowned_lookup():
    assert _undecided_read("def A(z):\n    return z.a.b\n") == ("z", "a")


if __name__ == "__main__":
    test_unary_minus_and_invert_emit_symbolic_ops()
    test_not_is_truth_then_negate()
    test_and_conjoins_operand_truthiness()
    test_or_disjoins_operand_truthiness()
    test_bare_operands_use_py_truthy()
    test_attribute_is_named_undecided()
    test_attribute_chain_refuses_at_the_first_unowned_lookup()
    print("ok: UnaryOp, BoolOp, Attribute drained through the node")
