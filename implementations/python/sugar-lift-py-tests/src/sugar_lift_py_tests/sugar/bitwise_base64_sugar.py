from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from typing import Protocol

from sugar_lift_py_tests.canonicalizer import encode_jcs
from sugar_lift_py_tests.ir import Term, bvadd, bvand, bvlshr, bvor, bvshl, make_var, num, term_to_value


class Base64Expr(Protocol):
    def bv_term(self) -> Term: ...

    def output_indices(self, alphabet_name: str) -> list[Term]: ...


@dataclass(frozen=True)
class NameExpr:
    name: str

    def bv_term(self) -> Term:
        return make_var(self.name)

    def output_indices(self, alphabet_name: str) -> list[Term]:
        raise ValueError(f"base64 output expected alphabet subscript, got `{self.name}`")


@dataclass(frozen=True)
class IntExpr:
    value: int

    def bv_term(self) -> Term:
        return num(self.value)

    def output_indices(self, alphabet_name: str) -> list[Term]:
        raise ValueError("base64 output expected alphabet subscript, got int literal")


@dataclass(frozen=True)
class SubscriptExpr:
    receiver: Base64Expr
    index: Base64Expr

    def bv_term(self) -> Term:
        raise ValueError("base64 alphabet subscript is a string output, not a bv32 term")

    def output_indices(self, alphabet_name: str) -> list[Term]:
        if not isinstance(self.receiver, NameExpr) or self.receiver.name != alphabet_name:
            raise ValueError("base64 output subscript must index the alphabet literal")
        return [self.index.bv_term()]


@dataclass(frozen=True)
class BinaryExpr:
    operator: str
    left: Base64Expr
    right: Base64Expr

    def bv_term(self) -> Term:
        return _bv_operator(self.operator, self.left.bv_term(), self.right.bv_term())

    def output_indices(self, alphabet_name: str) -> list[Term]:
        if self.operator != "+":
            raise ValueError("base64 output must concatenate alphabet subscripts")
        return self.left.output_indices(alphabet_name) + self.right.output_indices(
            alphabet_name
        )


@dataclass(frozen=True)
class BitwiseBase64Sugar:
    expression: Base64Expr

    @classmethod
    def from_site(cls, site, _ctx=None) -> "BitwiseBase64Sugar | None":
        stmt = site.node
        if not isinstance(stmt, ast.Return) or stmt.value is None:
            return None
        try:
            expression = _lower_expr(stmt.value)
        except ValueError:
            return None
        return cls(expression=expression)

    def payload_json(self, *, alphabet: str, alphabet_name: str, byte_names: list[str]) -> str:
        payload = {
            "vars": byte_names,
            "per_char": [
                _term_json(term) for term in self.expression.output_indices(alphabet_name)
            ],
            "table": [ord(ch) for ch in alphabet],
        }
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def _lower_expr(node: ast.AST) -> Base64Expr:
    if isinstance(node, ast.BinOp):
        operator = _operator(node.op)
        if operator is None:
            raise ValueError("unsupported base64 binary op")
        return BinaryExpr(
            operator=operator,
            left=_lower_expr(node.left),
            right=_lower_expr(node.right),
        )
    if isinstance(node, ast.Subscript):
        return SubscriptExpr(
            receiver=_lower_expr(node.value),
            index=_lower_expr(node.slice),
        )
    if isinstance(node, ast.Name):
        return NameExpr(node.id)
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return IntExpr(node.value)
    raise ValueError(f"unsupported base64 expression: {type(node).__name__}")


def _operator(op: ast.operator) -> str | None:
    if isinstance(op, ast.Add):
        return "+"
    if isinstance(op, ast.BitAnd):
        return "&"
    if isinstance(op, ast.BitOr):
        return "|"
    if isinstance(op, ast.LShift):
        return "<<"
    if isinstance(op, ast.RShift):
        return ">>"
    return None


def _bv_operator(operator: str, left: Term, right: Term) -> Term:
    if operator == "&":
        return bvand(left, right)
    if operator == "|":
        return bvor(left, right)
    if operator == "<<":
        return bvshl(left, right)
    if operator == ">>":
        return bvlshr(left, right)
    if operator == "+":
        return bvadd(left, right)
    raise ValueError(f"unsupported base64 bv operator `{operator}`")


def _term_json(term: Term) -> dict:
    return json.loads(encode_jcs(term_to_value(term)))
