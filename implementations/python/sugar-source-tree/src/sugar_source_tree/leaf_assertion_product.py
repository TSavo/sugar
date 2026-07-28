"""Source-construction owner for closed leaf assertion term/call products."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .nodes import Assert, Call, Compare, Constant, Expression, FunctionDef, Name, UnaryOp


class LeafAssertionUnsupported(Exception):
    def __init__(self, message: str, *, line: int) -> None:
        super().__init__(message)
        self.line = line


class LeafAssertionProductMismatch(TypeError):
    pass


class _FrozenJsonDict(dict):
    def _refuse(self, *args, **kwargs):
        del args, kwargs
        raise TypeError("leaf assertion product JSON is immutable")

    __setitem__ = _refuse
    __delitem__ = _refuse
    clear = _refuse
    pop = _refuse
    popitem = _refuse
    setdefault = _refuse
    update = _refuse


class _FrozenJsonList(list):
    def _refuse(self, *args, **kwargs):
        del args, kwargs
        raise TypeError("leaf assertion product JSON is immutable")

    __setitem__ = _refuse
    __delitem__ = _refuse
    __iadd__ = _refuse
    __imul__ = _refuse
    append = _refuse
    clear = _refuse
    extend = _refuse
    insert = _refuse
    pop = _refuse
    remove = _refuse
    reverse = _refuse
    sort = _refuse


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        frozen = _FrozenJsonDict()
        dict.update(frozen, {key: _freeze(item) for key, item in value.items()})
        return frozen
    if isinstance(value, list):
        frozen = _FrozenJsonList()
        list.extend(frozen, (_freeze(item) for item in value))
        return frozen
    return value


@dataclass(frozen=True, init=False)
class _CallRow:
    call: Call = field(repr=False, compare=False)
    target_symbol: str
    source_cid: str
    source_path: str
    line: int
    column: int

    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs
        raise TypeError("_CallRow is source-construction-owned")


@dataclass(frozen=True, init=False)
class _LeafAssertionProduct:
    atom: _FrozenJsonDict
    call_edges: tuple[_FrozenJsonDict, ...]
    _contract: FunctionDef = field(repr=False, compare=False)
    _assertion: Assert = field(repr=False, compare=False)
    _rows: tuple[_CallRow, ...] = field(repr=False, compare=False)

    def __init__(self, *args, **kwargs) -> None:
        del args, kwargs
        raise TypeError("_LeafAssertionProduct is source-construction-owned")

    def __copy__(self):
        raise TypeError("_LeafAssertionProduct cannot be copied")

    def __deepcopy__(self, memo):
        del memo
        raise TypeError("_LeafAssertionProduct cannot be copied")

    def project(self) -> tuple[_FrozenJsonDict, tuple[_FrozenJsonDict, ...]]:
        """Zero-work view: all source authentication happened at construction."""
        return self.atom, self.call_edges


_CMP = {"Eq": "=", "NotEq": "≠", "Lt": "<", "LtE": "≤", "Gt": ">", "GtE": "≥"}


def _mint_row(call: Call, *, assertion_line: int) -> _CallRow:
    if not isinstance(call.func, Name):
        raise LeafAssertionUnsupported(
            "call callee is not a bare identifier", line=assertion_line
        )
    span = call.line_col_span()
    row = object.__new__(_CallRow)
    for name, value in (
        ("call", call),
        ("target_symbol", call.func.id),
        ("source_cid", call.unit.source_cid),
        ("source_path", call.unit.filename),
        ("line", span.start_line),
        ("column", span.start_col),
    ):
        object.__setattr__(row, name, value)
    return row


def _term(
    node: Expression, *, assertion_line: int
) -> tuple[dict[str, Any], tuple[_CallRow, ...]]:
    if isinstance(node, Name):
        return {"kind": "var", "name": node.id}, ()
    if isinstance(node, Constant):
        value = node.value
        if isinstance(value, bool):
            name = "Bool"
        elif isinstance(value, int):
            name = "Int"
        elif isinstance(value, str):
            name = "String"
        elif value is None:
            return {"kind": "ctor", "name": "None", "args": []}, ()
        else:
            raise LeafAssertionUnsupported(
                f"unsupported constant {type(value).__name__}", line=assertion_line
            )
        return {
            "kind": "const",
            "value": value,
            "sort": {"kind": "primitive", "name": name},
        }, ()
    if isinstance(node, UnaryOp) and node.op.kind == "USub":
        operand = node.operand
        if (
            isinstance(operand, Constant)
            and isinstance(operand.value, int)
            and not isinstance(operand.value, bool)
        ):
            return {
                "kind": "const",
                "value": -operand.value,
                "sort": {"kind": "primitive", "name": "Int"},
            }, ()
        raise LeafAssertionUnsupported(
            "unary minus only on int literals", line=assertion_line
        )
    if isinstance(node, Call):
        if node.keywords:
            raise LeafAssertionUnsupported(
                "call has keyword arguments", line=assertion_line
            )
        row = _mint_row(node, assertion_line=assertion_line)
        args = tuple(
            _term(arg, assertion_line=assertion_line) for arg in node.args
        )
        return (
            {"kind": "ctor", "name": row.target_symbol, "args": [term for term, _ in args]},
            (row,) + tuple(call for _, calls in args for call in calls),
        )
    raise LeafAssertionUnsupported(
        f"operand {type(node).__name__} not supported", line=assertion_line
    )


def _is_none(term: dict[str, Any]) -> bool:
    return term.get("kind") == "ctor" and term.get("name") == "None" and term.get("args") == []


def _comparison(name: str, lhs: dict[str, Any], rhs: dict[str, Any]) -> dict[str, Any]:
    return {"kind": "atomic", "name": name, "args": [lhs, rhs]}


def _construct_leaf_assertion_product(
    contract: FunctionDef, assertion: Assert
) -> _LeafAssertionProduct:
    if contract.unit is not assertion.unit:
        raise LeafAssertionProductMismatch(
            "leaf assertion belongs to a foreign authenticated source"
        )
    if not (
        contract.span.start <= assertion.span.start
        and assertion.span.end <= contract.span.end
        and any(statement is assertion for statement in contract.body)
    ):
        raise LeafAssertionProductMismatch(
            "leaf assertion is not an exact statement of the authenticated FunctionDef"
        )
    cache = contract._construction_cache()
    key = (
        "leaf-assertion-product",
        cache.key(contract.ref, contract.reporter, contract.control_context),
        cache.key(assertion.ref, assertion.reporter, assertion.control_context),
    )
    remembered = cache.leaf_assertion_products.get(key)
    if remembered is not None:
        return remembered

    test = assertion.test
    assertion_line = assertion.line_col_span().start_line
    if not isinstance(test, Compare):
        raise LeafAssertionUnsupported(
            "assert is not a comparison", line=assertion_line
        )
    if len(test.ops) != 1 or len(test.comparators) != 1:
        raise LeafAssertionUnsupported(
            "only single-comparison asserts are harvested", line=assertion_line
        )
    lhs, lhs_rows = _term(test.left, assertion_line=assertion_line)
    rhs, rhs_rows = _term(test.comparators[0], assertion_line=assertion_line)
    if test.ops[0].kind in ("Is", "IsNot"):
        if _is_none(lhs) == _is_none(rhs):
            raise LeafAssertionUnsupported(
                "identity comparison is only supported against None",
                line=assertion_line,
            )
        name = "=" if test.ops[0].kind == "Is" else "≠"
        base = _comparison(name, lhs, rhs)
        subject = rhs if _is_none(lhs) else lhs
        guard = "is_none" if name == "=" else "is_some"
        atom = {
            "kind": "and",
            "operands": [base, {"kind": "atomic", "name": guard, "args": [subject]}],
        }
    else:
        name = _CMP.get(test.ops[0].kind)
        if name is None:
            raise LeafAssertionUnsupported(
                f"comparison op {test.ops[0].kind} not in whitelist",
                line=assertion_line,
            )
        atom = _comparison(name, lhs, rhs)

    rows = lhs_rows + rhs_rows
    edges = tuple(
        {
            "kind": "call-edge",
            "sourceContract": contract.name,
            "targetSymbol": row.target_symbol,
            "callSiteLocus": {
                "file": row.source_path,
                "line": row.line,
                "column": row.column,
            },
        }
        for row in rows
    )
    product = object.__new__(_LeafAssertionProduct)
    object.__setattr__(product, "atom", _freeze(atom))
    object.__setattr__(product, "call_edges", tuple(_freeze(edge) for edge in edges))
    object.__setattr__(product, "_contract", contract)
    object.__setattr__(product, "_assertion", assertion)
    object.__setattr__(product, "_rows", rows)
    cache.leaf_assertion_products[key] = product
    return product
