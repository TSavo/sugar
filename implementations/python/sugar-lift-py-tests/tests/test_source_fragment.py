"""SourceFragment is THE source fragment -- the one object the factory uses to talk to the
AST. Feed it Python and it breaks down the right way: a module into its body, a body
into its statements, a statement into its terms, a term into its sub-terms. An `if`
breaks into its test term and its branch blocks -- the shape IfSugar composes."""

from __future__ import annotations

import ast

from sugar_lift_py_tests.factory.source_fragment import SourceFragment


def _module(src: str) -> SourceFragment:
    return SourceFragment.from_node(ast.parse(src), "t.py")


def _function_body(src: str) -> SourceFragment:
    # module -> body Block -> the def -> the def's body Block
    fn = _module(src).fragments()[0].statements()[0]
    return next(f for f in fn.fragments() if f.observed == "Block")


def test_module_fragments_into_one_body_block():
    assert [f.observed for f in _module("x = 1\n").fragments()] == ["Block"]


def test_body_breaks_into_its_statements_in_order():
    body = _module("a = 1\nb = 2\nc = 3\n").fragments()[0]
    assert [s.observed for s in body.statements()] == ["Assign", "Assign", "Assign"]


def test_statement_breaks_into_its_terms():
    # `z = x + 1` -> the target Name and the value expression
    assign = _module("z = x + 1\n").fragments()[0].statements()[0]
    assert [t.observed for t in assign.terms()] == ["Name", "BinOp"]


def test_term_breaks_into_its_subterms():
    # `x + 1` -> Name(x), the literal 1 (the operator is not a term)
    binop = _module("z = x + 1\n").fragments()[0].statements()[0].terms()[1]
    assert [t.observed for t in binop.terms()] == ["Name", "PrimitiveLiteral"]


def test_if_breaks_into_its_test_term_and_branch_blocks():
    # the exact shape IfSugar composes: a test term + a then-block + an else-block
    if_stmt = (
        _module("if x == 0:\n    a = 1\nelse:\n    a = 2\n")
        .fragments()[0]
        .statements()[0]
    )
    assert [t.observed for t in if_stmt.terms()] == ["Compare"]
    assert [s.observed for s in if_stmt.statements()] == ["Block", "Block"]


def test_a_whole_function_body_decomposes_statements_then_terms():
    body = _function_body("def f(x):\n    y = x + 1\n    return y\n")
    assert [s.observed for s in body.statements()] == ["Assign", "Return"]
    assert [t.observed for t in body.statements()[0].terms()] == ["Name", "BinOp"]


# ------------------------------------------------------------------
# Accessor tests
# ------------------------------------------------------------------


def _stmt(src: str) -> SourceFragment:
    """Return the first statement SourceFragment from a one-liner."""
    return _module(src).fragments()[0].statements()[0]


def _expr(src: str) -> SourceFragment:
    """Return the value/RHS expression of the first Assign statement."""
    return _stmt(src).assign_value()


def test_name_id():
    site = _module("x = 1\n").fragments()[0].statements()[0].terms()[0]
    assert site.name_id() == "x"


def test_name_id_wrong_kind_raises():
    site = _expr("x = 1\n")
    try:
        site.name_id()
        assert False, "expected TypeError"
    except TypeError:
        pass


def test_literal_value_int():
    site = _expr("x = 42\n")
    assert site.literal_value() == 42


def test_literal_value_str():
    site = _expr("x = 'hello'\n")
    assert site.literal_value() == "hello"


def test_literal_value_bool():
    site = _expr("x = True\n")
    assert site.literal_value() is True


def test_literal_value_none():
    site = _expr("x = None\n")
    assert site.literal_value() is None


def test_attr_name():
    site = _expr("x = obj.foo\n")
    assert site.attr_name() == "foo"


def test_call_is_method_call_true():
    site = _expr("x = obj.method()\n")
    assert site.call_is_method_call() is True


def test_call_is_method_call_false():
    site = _expr("x = func()\n")
    assert site.call_is_method_call() is False


def test_call_receiver():
    site = _expr("x = obj.method(1)\n")
    recv = site.call_receiver()
    assert recv is not None
    assert recv.name_id() == "obj"


def test_call_receiver_plain_call():
    site = _expr("x = func(1)\n")
    assert site.call_receiver() is None


def test_call_target_name_plain():
    site = _expr("x = myfunc(1)\n")
    assert site.call_target_name() == "myfunc"


def test_call_target_name_method():
    site = _expr("x = obj.go(1)\n")
    assert site.call_target_name() == "go"


def test_call_args():
    site = _expr("x = f(1, 2, 3)\n")
    args = site.call_args()
    assert len(args) == 3
    assert [a.literal_value() for a in args] == [1, 2, 3]


def test_call_arg_count():
    site = _expr("x = f(1, 2)\n")
    assert site.call_arg_count() == 2


def test_call_has_keywords_true():
    site = _expr("x = f(a=1)\n")
    assert site.call_has_keywords() is True


def test_call_has_keywords_false():
    site = _expr("x = f(1)\n")
    assert site.call_has_keywords() is False


def test_operator_kind_binop():
    site = _expr("x = a + b\n")
    assert site.operator_kind() == "Add"


def test_operator_kind_unaryop():
    site = _expr("x = -a\n")
    assert site.operator_kind() == "USub"


def test_binop_left():
    site = _expr("x = a + b\n")
    assert site.binop_left().name_id() == "a"


def test_binop_right():
    site = _expr("x = a + b\n")
    assert site.binop_right().name_id() == "b"


def test_subscript_receiver():
    site = _expr("x = arr[0]\n")
    assert site.subscript_receiver().name_id() == "arr"


def test_subscript_index():
    site = _expr("x = arr[2]\n")
    assert site.subscript_index().literal_value() == 2


def test_lambda_body():
    site = _expr("x = lambda a: a + 1\n")
    body = site.lambda_body()
    assert body.observed == "BinOp"


def test_return_value():
    fn = _module("def f():\n    return 42\n").fragments()[0].statements()[0]
    ret = fn.function_body()[0]
    rv = ret.return_value()
    assert rv is not None
    assert rv.literal_value() == 42


def test_return_value_bare():
    fn = _module("def f():\n    return\n").fragments()[0].statements()[0]
    ret = fn.function_body()[0]
    assert ret.return_value() is None


def test_assign_target_name():
    site = _stmt("x = 1\n")
    assert site.assign_target_name() == "x"


def test_assign_value():
    site = _stmt("x = 99\n")
    assert site.assign_value().literal_value() == 99


def test_if_test():
    site = _stmt("if x == 0:\n    pass\n")
    test = site.if_test()
    assert test.observed == "Compare"


def test_if_body():
    site = _stmt("if x == 0:\n    y = 1\n    z = 2\n")
    body = site.if_body()
    assert len(body) == 2
    assert all(s.observed == "Assign" for s in body)


def test_if_orelse_empty():
    site = _stmt("if x == 0:\n    pass\n")
    assert site.if_orelse() == []


def test_if_orelse_populated():
    site = _stmt("if x == 0:\n    y = 1\nelse:\n    y = 2\n")
    orelse = site.if_orelse()
    assert len(orelse) == 1
    assert orelse[0].observed == "Assign"


def test_function_params():
    fn = _module("def f(a, b, c):\n    pass\n").fragments()[0].statements()[0]
    assert fn.function_params() == ["a", "b", "c"]


def test_function_body():
    fn = _module("def f(x):\n    y = x\n    return y\n").fragments()[0].statements()[0]
    stmts = fn.function_body()
    assert [s.observed for s in stmts] == ["Assign", "Return"]


def test_compare_ops():
    site = _expr("x = a == b\n")
    assert site.compare_ops() == ["Eq"]


def test_compare_left():
    site = _expr("x = a < b\n")
    assert site.compare_left().name_id() == "a"


def test_compare_comparators():
    site = _expr("x = a == b\n")
    comps = site.compare_comparators()
    assert len(comps) == 1
    assert comps[0].name_id() == "b"


def test_wrong_kind_raises_typeerror():
    site = _expr("x = 1\n")
    try:
        site.binop_left()
        assert False, "expected TypeError"
    except TypeError as e:
        assert "BinOp" in str(e)


# ------------------------------------------------------------------
# New accessors added in numpy-import-sugar sweep
# ------------------------------------------------------------------


def test_from_source_returns_module_fragment():
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment

    root = SourceFragment.from_source("x = 1\n", "t.py")
    assert root.observed == "Module"


def test_has_position_true():
    site = _stmt("x = 1\n")
    assert site.has_position() is True


def test_has_position_false_on_module():
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment

    root = SourceFragment.from_source("x = 1\n", "t.py")
    assert root.has_position() is False


def test_end_line():
    site = _stmt("x = 1\n")
    assert site.end_line >= 1


def test_end_col():
    site = _stmt("x = 1\n")
    assert isinstance(site.end_col, int)


def test_source_text():
    src = "x = 1\n"
    site = _stmt(src)
    text = site.source_text(src)
    assert text is not None
    assert "x" in text


def test_walk_yields_descendants():
    root = _module("x = a + b\n")
    children = root.walk()
    observed = {f.observed for f in children}
    assert "BinOp" in observed
    assert "Name" in observed


def test_is_node_type_true():
    site = _stmt("x = 1\n")
    assert site.is_node_type(ast.Assign) is True


def test_is_node_type_false():
    site = _stmt("x = 1\n")
    assert site.is_node_type(ast.Return) is False


def test_is_node_type_multiple():
    site = _stmt("x = 1\n")
    assert site.is_node_type(ast.Return, ast.Assign) is True


def test_assert_test():
    site = _stmt("assert x == 1\n")
    test = site.assert_test()
    assert test.observed == "Compare"


def test_expr_value():
    site = _stmt("foo()\n")
    val = site.expr_value()
    assert val.observed == "Call"


def test_unaryop_operand():
    site = _expr("x = -a\n")
    operand = site.unaryop_operand()
    assert operand.name_id() == "a"


def test_boolop_op_kind_and():
    site = _expr("x = a and b\n")
    assert site.boolop_op_kind() == "and"


def test_boolop_op_kind_or():
    site = _expr("x = a or b\n")
    assert site.boolop_op_kind() == "or"


def test_boolop_values():
    site = _expr("x = a and b\n")
    vals = site.boolop_values()
    assert len(vals) == 2
    assert vals[0].name_id() == "a"
    assert vals[1].name_id() == "b"


def test_attr_receiver():
    site = _expr("x = obj.foo\n")
    recv = site.attr_receiver()
    assert recv.name_id() == "obj"


def test_call_func_plain():
    site = _expr("x = func(1)\n")
    func = site.call_func()
    assert func.name_id() == "func"


def test_call_func_method():
    site = _expr("x = obj.method(1)\n")
    func = site.call_func()
    assert func.observed == "Attribute"


def test_call_keywords():
    site = _expr("x = f(a=1, b=2)\n")
    kws = site.call_keywords()
    assert len(kws) == 2


def test_call_qualified_target_name_preserves_attribute_owner():
    site = _expr("x = np.testing.assert_equal(a, b)\n")
    assert site.call_qualified_target_name() == "np.testing.assert_equal"


def test_keyword_arg_name():
    site = _expr("x = f(key=42)\n")
    kw = site.call_keywords()[0]
    assert kw.keyword_arg_name() == "key"


def test_keyword_value():
    site = _expr("x = f(key=42)\n")
    kw = site.call_keywords()[0]
    assert kw.keyword_value().literal_value() == 42


def test_annassign_target():
    site = _stmt("x: int = 1\n")
    assert site.annassign_target().name_id() == "x"


def test_annassign_annotation():
    site = _stmt("x: int = 1\n")
    ann = site.annassign_annotation()
    assert ann.name_id() == "int"


def test_annassign_value_present():
    site = _stmt("x: int = 5\n")
    val = site.annassign_value()
    assert val is not None
    assert val.literal_value() == 5


def test_annassign_value_absent():
    site = _stmt("x: int\n")
    assert site.annassign_value() is None


def test_annassign_target_id():
    site = _stmt("x: int = 1\n")
    assert site.annassign_target_id() == "x"


def test_import_names():
    site = _stmt("import os\n")
    names = site.import_names()
    assert names == [("os", None)]


def test_import_names_alias():
    site = _stmt("import numpy as np\n")
    names = site.import_names()
    assert names == [("numpy", "np")]


def test_importfrom_module():
    site = _stmt("from os import path\n")
    assert site.importfrom_module() == "os"


def test_importfrom_level():
    site = _stmt("from os import path\n")
    assert site.importfrom_level() == 0


def test_importfrom_names():
    site = _stmt("from os import path, getcwd\n")
    names = site.importfrom_names()
    assert len(names) == 2
    assert ("path", None) in names
    assert ("getcwd", None) in names


def test_function_decorators_empty():
    fn = _module("def f():\n    pass\n").fragments()[0].statements()[0]
    assert fn.function_decorators() == []


def test_function_decorators_present():
    fn = _module("@staticmethod\ndef f():\n    pass\n").fragments()[0].statements()[0]
    decs = fn.function_decorators()
    assert len(decs) == 1
    assert decs[0].name_id() == "staticmethod"


def test_aug_assign_op():
    site = _stmt("x += 1\n")
    assert site.aug_assign_op() == "Add"


def test_aug_assign_target():
    site = _stmt("x += 1\n")
    assert site.aug_assign_target().name_id() == "x"


def test_aug_assign_value():
    site = _stmt("x += 1\n")
    assert site.aug_assign_value().literal_value() == 1


def test_raise_exc():
    site = _stmt("raise ValueError\n")
    exc = site.raise_exc()
    assert exc is not None
    assert exc.name_id() == "ValueError"


def test_raise_exc_bare():
    site = _stmt("raise\n")
    assert site.raise_exc() is None


def test_for_body():
    site = _stmt("for x in items:\n    pass\n")
    body = site.for_body()
    assert len(body) == 1
    assert body[0].observed == "Pass"
