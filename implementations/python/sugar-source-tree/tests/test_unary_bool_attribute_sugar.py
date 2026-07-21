"""Constraint-grammar drain: UnaryOp, BoolOp, Attribute, through the node.

Each mirrors an existing dispatch: UnaryOp routes to the operand value's floor
method (`not` composes truth+negate); BoolOp combines the operands' truthiness
via and_/or_; Attribute asks the receiver for `.name` (a symbolic receiver stays
the opaque py.getattr coordinate, like py.subscript).
"""

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile


def _fn(src: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    return next(SourceFile(path_source(path)).functions())


def _post(src):
    return _fn(src).sugar().desugar().value.post()


def _invs(src):
    return _fn(src).sugar().desugar().value.invs()


# ---- UnaryOp -----------------------------------------------------------------


def test_unary_minus_and_invert_emit_symbolic_ops():
    assert _post("def A(z):\n    return -z\n").args[1].name == "py.neg"
    assert _post("def A(z):\n    return ~z\n").args[1].name == "py.invert"


def test_not_is_truth_then_negate():
    # if not (z == 1): the guard is not(z == 1), so the body's fact rides under it.
    invs = _invs("def A(z):\n    if not (z == 1):\n        assert z == z\n    return z\n")
    guard = invs[0].operands[0]  # antecedent of the guarded implication
    assert guard.kind == "not"
    assert guard.operands[0].name == "py.eq"


# ---- BoolOp ------------------------------------------------------------------


def test_and_conjoins_operand_truthiness():
    invs = _invs("def A(z):\n    assert (z == 1) and (z == 3)\n    return z\n")
    assert invs[0].kind == "and"
    assert all(op.name == "py.eq" for op in invs[0].operands)


def test_or_disjoins_operand_truthiness():
    invs = _invs("def A(z):\n    assert (z == 1) or (z == 2)\n    return z\n")
    assert invs[0].kind == "or"


def test_bare_operands_use_py_truthy():
    invs = _invs("def A(a, b):\n    assert a and b\n    return a\n")
    assert invs[0].kind == "and"
    assert all(op.name == "py.truthy" for op in invs[0].operands)


# ---- Attribute ---------------------------------------------------------------


def test_attribute_is_the_py_getattr_coordinate():
    post = _post("def A(z):\n    return z.numerator\n")
    getattr_term = post.args[1]
    assert getattr_term.name == "py.getattr"
    assert getattr_term.args[0].name == "z"
    assert getattr_term.args[1].value == "numerator"


def test_attribute_chain_nests():
    # z.a.b -> py.getattr(py.getattr(z, "a"), "b")
    post = _post("def A(z):\n    return z.a.b\n")
    outer = post.args[1]
    assert outer.name == "py.getattr" and outer.args[1].value == "b"
    assert outer.args[0].name == "py.getattr" and outer.args[0].args[1].value == "a"


if __name__ == "__main__":
    test_unary_minus_and_invert_emit_symbolic_ops()
    test_not_is_truth_then_negate()
    test_and_conjoins_operand_truthiness()
    test_or_disjoins_operand_truthiness()
    test_bare_operands_use_py_truthy()
    test_attribute_is_the_py_getattr_coordinate()
    test_attribute_chain_nests()
    print("ok: UnaryOp, BoolOp, Attribute drained through the node")
