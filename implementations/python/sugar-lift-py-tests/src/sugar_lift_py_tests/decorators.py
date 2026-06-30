# SPDX-License-Identifier: Apache-2.0
#
# sugar.decorators: direct contract authoring for Python.
#
# Usage:
#   @sugar.contract(pre=lambda x: x >= 0, post=lambda out: out >= 0)
#   def abs(x: int) -> int:
#       return x if x >= 0 else -x
#
# The decorator captures the contract metadata and registers it with the
# kit collector. When the module is loaded, the contracts are available
# for lifting via sugar.lift or for direct verification.

from __future__ import annotations

import functools
import inspect
import textwrap
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union

from .ir import (
    ContractDecl,
    Formula,
    Int,
    String,
    Bool,
    Sort,
    atomic,
    comparison_with_none_guard,
    eq,
    ne,
    gt,
    gte,
    lt,
    lte,
    make_var,
    num,
    str_const,
    bool_const,
    ctor,
    and_,
    or_,
    not_,
    implies,
)

from .factory.source_fragment import SourceFragment


# ---------------------------------------------------------------------------
# Contract decorator
# ---------------------------------------------------------------------------


def contract(
    *,
    pre: Optional[Union[Callable[..., bool], str]] = None,
    post: Optional[Union[Callable[..., bool], str]] = None,
    inv: Optional[Union[Callable[..., bool], str]] = None,
    out_binding: str = "out",
) -> Callable[[Callable], Callable]:
    """Decorate a function with a Sugar contract.

    The ``pre``, ``post``, and ``inv`` arguments accept either:
      - A Python callable (lambda or function) that the decorator introspects
        to build an IR formula.
      - A string containing a Python boolean expression (e.g. ``"x >= 0"``).

    Example:
        @sugar.contract(pre="x >= 0", post="out >= 0")
        def sqrt(x: float) -> float:
            return x ** 0.5
    """

    def decorator(fn: Callable) -> Callable:
        sig = inspect.signature(fn)
        param_names = list(sig.parameters.keys())

        pre_ir = _parse_contract_expr(pre, param_names, "pre") if pre else None
        post_ir = (
            _parse_contract_expr(post, param_names + [out_binding], "post")
            if post
            else None
        )
        inv_ir = _parse_contract_expr(inv, param_names, "inv") if inv else None

        # Store metadata on the function object for later collection.
        fn._sugar_contract = ContractDecl(  # type: ignore
            name=fn.__qualname__,
            pre=pre_ir,
            post=post_ir,
            inv=inv_ir,
            out_binding=out_binding,
        )

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Runtime contract checking (optional, lightweight).
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            if pre and callable(pre):
                _check_runtime(pre, bound.arguments, "precondition")
            result = fn(*args, **kwargs)
            if post and callable(post):
                post_args = dict(bound.arguments)
                post_args[out_binding] = result
                _check_runtime(post, post_args, "postcondition")
            return result

        wrapper._sugar_contract = fn._sugar_contract  # type: ignore
        return wrapper

    return decorator


def _check_runtime(
    predicate: Callable[..., bool],
    args: Dict[str, Any],
    kind: str,
) -> None:
    """Invoke a runtime predicate and raise ContractViolation on failure."""
    sig = inspect.signature(predicate)
    call_args = {name: args[name] for name in sig.parameters if name in args}
    try:
        ok = predicate(**call_args)
    except Exception as e:
        raise ContractViolation(f"{kind} predicate raised {type(e).__name__}: {e}")
    if not ok:
        raise ContractViolation(f"{kind} violated")


class ContractViolation(Exception):
    """Raised when a runtime contract check fails."""

    pass


# ---------------------------------------------------------------------------
# Expression parser: Python source -> IR Formula
# ---------------------------------------------------------------------------


def _parse_contract_expr(
    expr: Union[Callable[..., bool], str],
    available_names: List[str],
    kind: str,
) -> Optional[Formula]:
    """Parse a Python expression into a canonical IR Formula."""
    if isinstance(expr, str):
        return _parse_expr_string(expr, available_names)
    if callable(expr):
        return _parse_callable(expr, available_names)
    return None


def _parse_expr_string(expr: str, available_names: List[str]) -> Formula:
    """Parse a string expression like ``x >= 0 && y != null``."""
    source = textwrap.dedent(expr).strip()
    root = SourceFragment.from_source(source, "<contract>")
    # Module body is wrapped in a Block; walk to find the first Expr statement.
    for frag in root.walk():
        if frag.observed == "Expr":
            return _translate_expr(frag.expr_value(), available_names)
    raise ValueError(f"empty contract expression: {expr!r}")


def _parse_callable(fn: Callable[..., bool], available_names: List[str]) -> Formula:
    """Introspect a lambda/function AST to extract its body expression."""
    try:
        source = inspect.getsource(fn)
    except OSError:
        # Fallback: if source unavailable, treat as opaque.
        return atomic("py_predicate", [str_const(fn.__name__)])
    source = textwrap.dedent(source).strip()
    root = SourceFragment.from_source(source, "<callable>")
    # Search for Lambda first (separate pass so we don't accidentally
    # match a nested FunctionDef from enclosing scope).
    for frag in root.walk():
        if frag.observed == "Lambda":
            return _translate_expr(frag.lambda_body(), available_names)
    # Then search for FunctionDef.
    for frag in root.walk():
        if frag.observed in ("FunctionDef", "AsyncFunctionDef"):
            body = frag.function_body()
            if body and body[-1].observed == "Return":
                rv = body[-1].return_value()
                if rv is not None:
                    return _translate_expr(rv, available_names)
            if len(body) == 1 and body[0].observed == "Expr":
                return _translate_expr(body[0].expr_value(), available_names)
    # Fallback: opaque predicate
    return atomic("py_predicate", [str_const(fn.__name__)])


_COMPARE_OPS_STR = {
    "Eq": "=",
    "NotEq": "≠",
    "Lt": "<",
    "LtE": "≤",
    "Gt": ">",
    "GtE": "≥",
    "Is": "=",
    "IsNot": "≠",
}


def _translate_expr(fragment: SourceFragment, available_names: List[str]) -> Formula:
    """Translate a SourceFragment expression into an IR Formula."""
    obs = fragment.observed

    if obs == "BoolOp":
        operands = [_translate_expr(v, available_names) for v in fragment.boolop_values()]
        kind = fragment.boolop_op_kind()
        if kind == "and":
            return and_(operands)
        if kind == "or":
            return or_(operands)
        raise ValueError(f"unsupported bool op: {obs}")

    if obs == "UnaryOp" and fragment.operator_kind() == "Not":
        inner = _translate_expr(fragment.unaryop_operand(), available_names)
        return not_(inner)

    if obs == "Compare":
        ops = fragment.compare_ops()
        comparators = fragment.compare_comparators()
        if len(ops) != 1 or len(comparators) != 1:
            raise ValueError("chained comparisons are not supported")
        sym = _COMPARE_OPS_STR.get(ops[0])
        if sym is None:
            raise ValueError(f"unsupported comparison: {ops[0]}")
        l = _translate_term(fragment.compare_left(), available_names)
        r = _translate_term(comparators[0], available_names)
        return comparison_with_none_guard(sym, l, r)

    if obs == "BinOp" and fragment.operator_kind() == "Add":
        l = _translate_term(fragment.binop_left(), available_names)
        r = _translate_term(fragment.binop_right(), available_names)
        return eq(ctor("+", [l, r]), ctor("+", [l, r]))  # placeholder

    # Single term treated as truthiness assertion.
    t = _translate_term(fragment, available_names)
    return eq(t, bool_const(True))


def _translate_term(fragment: SourceFragment, available_names: List[str]):
    """Translate a SourceFragment expression into an IR Term."""
    from .ir import Term

    obs = fragment.observed

    if obs == "Name":
        id_ = fragment.name_id()
        if id_ == "None":
            return ctor("None", [])
        if id_ == "True":
            return bool_const(True)
        if id_ == "False":
            return bool_const(False)
        return make_var(id_)

    if obs == "PrimitiveLiteral":
        v = fragment.literal_value()
        if isinstance(v, bool):
            return bool_const(v)
        if isinstance(v, int):
            return num(v)
        if isinstance(v, str):
            return str_const(v)
        if v is None:
            return ctor("None", [])
        raise ValueError(f"unsupported constant: {type(v).__name__}")

    if obs == "UnaryOp" and fragment.operator_kind() == "USub":
        operand = fragment.unaryop_operand()
        if operand.observed == "PrimitiveLiteral":
            v = operand.literal_value()
            if isinstance(v, int):
                return num(-v)
        raise ValueError("unary minus only supported on integer literals")

    if obs == "Call":
        if fragment.call_is_method_call():
            raise ValueError("only simple-name calls are supported")
        name = fragment.call_target_name()
        if name is None:
            raise ValueError("only simple-name calls are supported")
        args = [_translate_term(a, available_names) for a in fragment.call_args()]
        return ctor(name, args)

    if obs == "BinOp":
        op = fragment.operator_kind()
        l = _translate_term(fragment.binop_left(), available_names)
        r = _translate_term(fragment.binop_right(), available_names)
        if op == "Add":
            return ctor("+", [l, r])
        if op == "Sub":
            return ctor("-", [l, r])
        if op == "Mult":
            return ctor("*", [l, r])
        if op == "Div":
            return ctor("/", [l, r])
        raise ValueError(f"unsupported binary op: {op}")

    raise ValueError(f"unsupported expression: {obs}")


# ---------------------------------------------------------------------------
# Collector: gather all decorated functions in a module
# ---------------------------------------------------------------------------


def collect_module(module) -> List[ContractDecl]:
    """Collect all @sugar.contract declarations from a loaded module."""
    decls: List[ContractDecl] = []
    for name in dir(module):
        obj = getattr(module, name)
        if hasattr(obj, "_sugar_contract"):
            decls.append(obj._sugar_contract)
    return decls
