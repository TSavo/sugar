"""LambdaSugar is agnostic to its body: it holds WHATEVER body sugar the factory
hands it, verbatim, and wraps it in a LambdaCallable. It never inspects what the
body computes -- a new body operation is MORE SUGAR (a leaf body), not a smarter
Lambda. Proven over three structurally different bodies (add, identity, constant)."""
from __future__ import annotations

import ast

from factory_reduce import array_map_build

from sugar_lift_py_tests.factory import SourceSite
from sugar_lift_py_tests.floor import LambdaCallable
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar.lambda_sugar import LambdaSugar


def _lambda(src: str):
    node = ast.parse(src, mode="eval").body
    body = array_map_build(ast.unparse(node.body))
    return LambdaSugar.from_site(SourceSite.from_node(node, "l.py"), body=body), body


def test_lambda_holds_whatever_body_verbatim_and_wraps_it():
    for src in ("lambda x: x + 1", "lambda x: x", "lambda x: 7"):
        sugar, body = _lambda(src)
        assert sugar.parameter == "x"
        assert sugar.body is body  # verbatim -- the body is opaque to the lambda
        assert complete_value(sugar.desugar(None), owner="lambda") == LambdaCallable(
            parameter="x", body=body
        )
