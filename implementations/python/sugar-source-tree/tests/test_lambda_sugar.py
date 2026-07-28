"""Expression-bodied lambdas construct callables; calls never inline them."""

import pytest

from sugar_lift_py_tests.floor import (
    BlockValue,
    DictValue,
    ReturnValue,
    StringValue,
    TermValue,
    TupleValue,
)
from sugar_lift_py_tests.ir import str_const
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
    lying = _post_term("def A(v, other):\n    return (lambda x: x)(other)\n")

    assert truthful.name == "py.call"
    assert truthful.args[0].name == "python:lambda"
    assert truthful.args[1].name == "v"
    assert lying != truthful


def test_lambda_body_changes_content_addressed_callable_identity():
    identity = _post_term("def A(v):\n    return (lambda x: x)(v)\n")
    increment = _post_term("def A(v):\n    return (lambda x: x + 1)(v)\n")

    assert identity.name == increment.name == "py.call"
    assert identity.args[1] == increment.args[1]
    assert identity.args[0] != increment.args[0]


def test_lambda_parameter_masks_same_spelled_outer_binding():
    expression = _return_expression("def A():\n    x = 7\n    return lambda x: x\n")
    sugar = expression.sugar()

    assert sugar.formals == ("x",)
    assert sugar.body.name == "x"


def test_lambda_captures_authenticated_outer_binding_while_masking_parameter():
    expression = _return_expression("def A():\n    z = 7\n    return lambda x: x + z\n")
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


def test_nested_lambda_capture_rebinding_changes_opaque_coordinate():
    first = (
        _return_expression(
            "def A():\n    z = 7\n    return lambda x: lambda x: x + z\n"
        )
        .sugar()
        .desugar()
        .value
    )
    second = (
        _return_expression(
            "def A():\n    z = 8\n    return lambda x: lambda x: x + z\n"
        )
        .sugar()
        .desugar()
        .value
    )

    assert first.parameters == second.parameters == ("x",)
    assert first.to_term(owner="test") != second.to_term(owner="test")


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
def test_lambda_parameter_roles_use_the_source_call_frame(source):
    sugar = _return_expression(source).sugar()

    assert sugar.source_call_frame is not None
    assert sugar.source_call_frame.parameters == sugar.formals


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("(lambda x=3: x + 1)()", TermValue(4)),
        ("(lambda *xs: xs)(1, 2)", TupleValue((TermValue(1), TermValue(2)))),
        (
            "(lambda **kw: kw)(renamed=7)",
            DictValue(((StringValue("renamed"), TermValue(7)),)),
        ),
        ("(lambda *, x: x)(x=9)", TermValue(9)),
        ("(lambda x, /: x)(9)", TermValue(9)),
        ("(lambda: 1)()", TermValue(1)),
    ],
)
def test_lambda_signature_roles_bind_through_the_shared_frame(expression, expected):
    call = _return_expression(f"def A():\n    return {expression}\n")
    reduced = (
        call.sugar().desugar().value.force_floor(None, owner="lambda-signature-twin")
    )

    assert reduced.statements[0].value == expected


def test_lambda_preserves_child_panic_role():
    expression = _return_expression("def A():\n    return lambda x: (yield x)\n")

    suspension = expression.sugar()
    with pytest.raises(SugarNotWritten) as caught:
        suspension.body.desugar()

    assert caught.value.owner == "YieldSuspensionSugar.desugar"


def test_inline_lambda_call_constructs_callable_then_ordinary_computed_call():
    call = _return_expression("def A(v):\n    return (lambda x: x)(v)\n")
    sugar = call.sugar()

    assert type(sugar).__name__ == "ComputedCallSugar"
    assert type(sugar.callee).__name__ == "LambdaSugar"
    assert sugar.callee.formals == ("x",)
    assert sugar.args[0].name == "v"


def test_lambda_coordinate_is_opaque_and_does_not_leak_nested_same_named_formals():
    expression = _return_expression("def A(x):\n    return lambda x: lambda x: x\n")
    outer = expression.sugar().desugar().value

    coordinate = outer.to_term(owner="test")
    assert coordinate.name == "python:lambda"
    assert coordinate.args[1] == str_const("x")
    assert _free_vars_in_ir_term(coordinate) == frozenset()
    assert outer.body.formals == ("x",)
    assert outer.body.body.name == "x"


def test_parser_backed_lambda_with_unresolved_capture_stays_loud():
    function = _function("def A():\n    z = 7\n    f = lambda x: x + z\n    return f\n")
    parser_backed_lambda = function.body[1].value

    with pytest.raises(SugarNotWritten, match="Lambda.sugar"):
        parser_backed_lambda.sugar()


def test_lambda_application_uses_body_bearing_callsite_not_private_apply():
    call = _return_expression("def A():\n    return (lambda x: x + 1)(7)\n")
    value = call.sugar().desugar().value

    assert value.body is not None
    assert value.source_call_frame_cid is not None
    assert len(value.formal_coordinate_cids) == 1
    reduced = value.force_floor(None, owner="lambda-call-frame-twin")
    assert isinstance(reduced, BlockValue)
    assert isinstance(reduced.statements[0], ReturnValue)
    assert reduced.statements[0].value == TermValue(8)


def test_lambda_call_frame_binds_runtime_entries_for_each_formal():
    call = _return_expression("def A():\n    return (lambda x, y: x + y)(7, 8)\n")
    frame = call.sugar().source_call_frame

    assert tuple(entry.coordinate.cid for entry in frame.runtime_entries) == tuple(
        coordinate.cid for coordinate in frame.formal_coordinates
    )
    assert all(not hasattr(entry, "sugar") for entry in frame.runtime_entries)


def test_source_visible_callback_reuses_function_call_frame_and_lambda_frame():
    functions = list(
        oracle_source_file(
            "def apply(fn, value):\n"
            "    return fn(value)\n\n"
            "def A():\n"
            "    return apply(lambda renamed: renamed + 1, 4)\n"
        ).functions()
    )
    apply_function, caller = functions
    outer_call = caller.body[-1].value.substitute({})
    apply_frame = apply_function.source_visible_call_frame().bind_node_actuals(
        outer_call.args, ()
    )

    callback_call = apply_frame.body.desugar().value.statements[0].value
    reduced = callback_call.force_floor(None, owner="source-visible-callback-twin")

    assert callback_call.source_call_frame_cid is not None
    assert isinstance(reduced.statements[0], ReturnValue)
    assert reduced.statements[0].value == TermValue(5)
