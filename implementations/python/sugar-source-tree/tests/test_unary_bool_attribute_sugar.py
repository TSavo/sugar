"""Constraint-grammar drain: UnaryOp, BoolOp, Attribute, through the node.

Each mirrors an existing dispatch: UnaryOp routes to the operand value's floor
method (`not` composes truth+negate); BoolOp combines the operands' truthiness
via and_/or_; Attribute asks the receiver for `.name` and a symbolic receiver
refuses because source testimony decides neither lookup edge.
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


def test_undecided_unary_ops_are_named_refusals():
    """``-z`` / ``~z`` / ``+z`` cannot invent a success face without z's type."""
    from sugar_lift_py_tests.gap.panic import ConstructionPanic

    for source, operator in (
        ("def A(z):\n    return -z\n", "-"),
        ("def A(z):\n    return ~z\n", "~"),
        ("def A(z):\n    return +z\n", "+"),
    ):
        try:
            _post(source)
        except ConstructionPanic as panic:
            assert panic.info.owner == "unary_operation_exception_floor"
            assert panic.info.observed == f"SymbolicValue {operator}"
        else:
            raise AssertionError(f"undecided unary {operator} invented a completion")


def test_not_is_truth_then_negate():
    # if not (z == 1): the guard is not(z == 1), so the body's fact rides under it.
    invs = _invs(
        "def A(z):\n    if not (z == 1):\n        assert z == z\n    return z\n"
    )
    authentication = invs[0]
    observed = authentication.operands[0].operands[1]
    assert observed.kind == "not"
    assert observed.operands[0].name == "py.eq"


# ---- BoolOp ------------------------------------------------------------------


def test_and_conjoins_operand_truthiness():
    invs = _invs("def A(z):\n    assert (z == 1) and (z == 3)\n    return z\n")
    assert invs[0].kind == "and"
    assert all(op.name == "py.eq" for op in invs[0].operands)


def test_or_disjoins_operand_truthiness():
    invs = _invs("def A(z):\n    assert (z == 1) or (z == 2)\n    return z\n")
    assert invs[0].kind == "or"


def test_bare_operands_refuse_undecided_truth():
    """``a and b`` cannot invent ``py.truthy`` when operand runtime types are open."""
    from sugar_lift_py_tests.gap.panic import ConstructionPanic

    try:
        _invs("def A(a, b):\n    assert a and b\n    return a\n")
    except ConstructionPanic as panic:
        assert panic.info.owner == "boolean_operation_exception_floor"
        assert panic.info.observed == "SymbolicValue and"
    else:
        raise AssertionError("undecided BoolOp invented py.truthy")


# ---- Attribute ---------------------------------------------------------------


def _attribute_refusal(source):
    from sugar_lift_py_tests.gap.panic import ConstructionPanic

    try:
        _post(source)
    except ConstructionPanic as panic:
        return panic.info
    raise AssertionError("symbolic attribute invented a completed projection")


def test_attribute_is_named_undecided():
    info = _attribute_refusal("def A(z):\n    return z.numerator\n")
    assert info.owner == "SymbolicValue.attribute"
    assert info.observed.endswith("SymbolicValue.numerator")


def test_attribute_chain_refuses_at_the_first_unowned_lookup():
    info = _attribute_refusal("def A(z):\n    return z.a.b\n")
    assert info.owner == "SymbolicValue.attribute"
    assert info.observed.endswith("SymbolicValue.a")


if __name__ == "__main__":
    test_unary_minus_and_invert_emit_symbolic_ops()
    test_not_is_truth_then_negate()
    test_and_conjoins_operand_truthiness()
    test_or_disjoins_operand_truthiness()
    test_bare_operands_use_py_truthy()
    test_attribute_is_named_undecided()
    test_attribute_chain_refuses_at_the_first_unowned_lookup()
    print("ok: UnaryOp, BoolOp, Attribute drained through the node")
