from __future__ import annotations

import z3


def solve_bitvector_binary(operator: str, left: int, right: int) -> int:
    if left < 0 or right < 0:
        raise ValueError("bitvector lowering currently expects nonnegative integers")
    width = _width_for(operator, left, right)
    lhs = z3.BitVecVal(left, width)
    rhs = z3.BitVecVal(right, width)
    if operator == "&":
        expr = lhs.__and__(rhs)
    elif operator == "|":
        expr = lhs.__or__(rhs)
    elif operator == "<<":
        expr = lhs.__lshift__(rhs)
    elif operator == ">>":
        expr = z3.LShR(lhs, rhs)
    else:
        raise TypeError(f"write more Sugar for bitwise operator `{operator}`")
    simplified = z3.simplify(expr)
    return simplified.as_long()


def _width_for(operator: str, left: int, right: int) -> int:
    width = max(8, left.bit_length(), right.bit_length(), 1)
    if operator == "<<":
        return width + right + 1
    return width + 1
