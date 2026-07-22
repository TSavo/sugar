"""Expression-bodied lambdas construct callables; calls never inline them."""

import pytest

from sugar_lift_py_tests.floor import SymbolicValue, TermValue
from sugar_lift_py_tests.ir import ctor, num, str_const
from sugar_lift_py_tests.proofir.formulas import _free_vars_in_ir_term
from sugar_source_tree.panic import SugarNotWritten

from conftest import oracle_source_file


def _function(source: str):
    return next(oracle_source_file(source).functions())


def _return_expression(source: str):
    function = _function(source)
    substituted = function.substitute({})
    return substituted.body[-1].value


def _post_term(source: str):
    return _function(source).sugar().desugar().value.post().args[1]


def test_lambda_identity_truthful_and_lying_terms_discriminate():
    truthful = _post_term("def A(v):\n    return (lambda x: x)(v)\n")
    lying = _post_term("def A(v):\n    return (lambda x: x)(v + 1)\n")

    assert truthful.name == "py.call"
    assert truthful.args[0].name == "python:lambda"
    assert truthful.args[1].name == "v"
    assert lying != truthful


def test_lambda_parameter_masks_same_spelled_outer_binding():
    expression = _return_expression(
        "def A():\n    x = 7\n    return lambda x: x\n"
    )
    sugar = expression.sugar()

    assert sugar.formals == ("x",)
    assert sugar.body.name == "x"


def test_lambda_captures_authenticated_outer_binding_while_masking_parameter():
    expression = _return_expression(
        "def A():\n    z = 7\n    return lambda x: x + z\n"
    )
    sugar = expression.sugar()

    assert sugar.formals == ("x",)
    assert sugar.body.left.name == "x"
    assert sugar.body.right.value == 7


def test_lambda_rebinding_changes_constructed_capture():
    first = _return_expression(
        "def A():\n    z = 7\n    return lambda x: x + z\n"
    ).sugar()
    second = _return_expression(
        "def A():\n    z = 8\n    return lambda x: x + z\n"
    ).sugar()

    assert first.body != second.body


@pytest.mark.parametrize(
    "source",
    [
        "def A():\n    return lambda *args: args\n",
        "def A():\n    return lambda **kwargs: kwargs\n",
        "def A():\n    return lambda *, x: x\n",
        "def A():\n    return lambda x=1: x\n",
        "def A():\n    return lambda x, /: x\n",
        "def A():\n    return lambda: 1\n",
        "def A():\n    return lambda x, y: x\n",
    ],
)
def test_unsupported_lambda_parameter_roles_stay_sugar_not_written(source):
    with pytest.raises(SugarNotWritten, match="Lambda.sugar"):
        _return_expression(source).sugar()


def test_lambda_preserves_child_panic_role():
    expression = _return_expression("def A():\n    return lambda x: (yield x)\n")

    with pytest.raises(SugarNotWritten) as caught:
        expression.sugar()

    assert caught.value.owner == "Yield.sugar"


def test_inline_lambda_call_constructs_callable_then_ordinary_computed_call():
    call = _return_expression("def A(v):\n    return (lambda x: x)(v)\n")
    sugar = call.sugar()

    assert type(sugar).__name__ == "ComputedCallSugar"
    assert type(sugar.callee).__name__ == "LambdaSugar"
    assert sugar.callee.formals == ("x",)
    assert sugar.args[0].name == "v"


def test_lambda_coordinate_is_opaque_and_does_not_leak_nested_same_named_formals():
    expression = _return_expression(
        "def A(x):\n    return lambda x: lambda x: x\n"
    )
    outer = expression.sugar().desugar().value

    assert outer.to_term(owner="test") == ctor("python:lambda", [str_const("x")])
    assert _free_vars_in_ir_term(outer.to_term(owner="test")) == frozenset()
    assert outer.body.formals == ("x",)
    assert outer.body.body.name == "x"


def test_parser_backed_lambda_with_unresolved_capture_stays_loud():
    function = _function(
        "def A():\n    z = 7\n    f = lambda x: x + z\n    return f\n"
    )
    parser_backed_lambda = function.body[1].value

    with pytest.raises(SugarNotWritten, match="Lambda.sugar"):
        parser_backed_lambda.sugar()


def test_lambda_application_substitutes_the_formal_in_the_body_term():
    callable_value = _return_expression(
        "def A():\n    return lambda x: x + 1\n"
    ).sugar().desugar().value

    applied = callable_value.apply(TermValue(7), None)

    assert isinstance(applied, SymbolicValue)
    assert applied.term == ctor("+", [num(7), num(1)])
