"""Operators are classes, not an enum.

An enum would reintroduce exactly the tag dispatch the tree exists to
kill: every consumer would ``match`` on the tag. As classes, behavior that
varies by operator lives ON the operator, and asking "which operator" is
``isinstance`` on OUR classes — the blessed form.

Operators carry no children and no span; each concrete class is a singleton
(``Add.instance()`` or the module-level ``ADD``). Identity comparison
(``op is ADD``) is therefore sound.
"""

from __future__ import annotations

from .panic import SourceTreePanic, vocabulary_missing


class Operator:
    """Abstract operator. ``kind`` is the frozen wire word; ``symbol`` the surface."""

    kind: str = ""
    symbol: str = ""
    _instance: "Operator | None" = None

    def __init_subclass__(cls, **kw: object) -> None:
        super().__init_subclass__(**kw)
        cls._instance = None

    @classmethod
    def instance(cls) -> "Operator":
        if cls is Operator or not cls.kind:
            # Internal invariant, not a backend question: operator_for
            # (below) only ever resolves to a concrete registered class, so
            # reaching here means OUR OWN code called .instance() on an
            # abstract class directly. Not a vocabulary gap, not a backend
            # defect — raised as the common base deliberately.
            raise SourceTreePanic(
                owner="operators.Operator.instance",
                observed=f"instance() on abstract {cls.__name__}",
                requested="a concrete operator class",
                fix="only concrete Operator subclasses are instantiable",
            )
        if cls._instance is None:
            cls._instance = object.__new__(cls)
        return cls._instance

    def __repr__(self) -> str:  # pragma: no cover
        return f"<op {self.kind} {self.symbol!r}>"


class BinaryOperator(Operator):
    """Operators of BinOp / AugAssign."""


class UnaryOperator(Operator):
    """Operators of UnaryOp."""


class BooleanOperator(Operator):
    """Operators of BoolOp."""


class ComparisonOperator(Operator):
    """Operators of Compare."""


class Add(BinaryOperator):
    kind, symbol = "Add", "+"


class Sub(BinaryOperator):
    kind, symbol = "Sub", "-"


class Mult(BinaryOperator):
    kind, symbol = "Mult", "*"


class MatMult(BinaryOperator):
    kind, symbol = "MatMult", "@"


class Div(BinaryOperator):
    kind, symbol = "Div", "/"


class Mod(BinaryOperator):
    kind, symbol = "Mod", "%"


class Pow(BinaryOperator):
    kind, symbol = "Pow", "**"


class LShift(BinaryOperator):
    kind, symbol = "LShift", "<<"


class RShift(BinaryOperator):
    kind, symbol = "RShift", ">>"


class BitOr(BinaryOperator):
    kind, symbol = "BitOr", "|"


class BitXor(BinaryOperator):
    kind, symbol = "BitXor", "^"


class BitAnd(BinaryOperator):
    kind, symbol = "BitAnd", "&"


class FloorDiv(BinaryOperator):
    kind, symbol = "FloorDiv", "//"


class UAdd(UnaryOperator):
    kind, symbol = "UAdd", "+"


class USub(UnaryOperator):
    kind, symbol = "USub", "-"


class Not(UnaryOperator):
    kind, symbol = "Not", "not"


class Invert(UnaryOperator):
    kind, symbol = "Invert", "~"


class And(BooleanOperator):
    kind, symbol = "And", "and"


class Or(BooleanOperator):
    kind, symbol = "Or", "or"


class Eq(ComparisonOperator):
    kind, symbol = "Eq", "=="


class NotEq(ComparisonOperator):
    kind, symbol = "NotEq", "!="


class Lt(ComparisonOperator):
    kind, symbol = "Lt", "<"


class LtE(ComparisonOperator):
    kind, symbol = "LtE", "<="


class Gt(ComparisonOperator):
    kind, symbol = "Gt", ">"


class GtE(ComparisonOperator):
    kind, symbol = "GtE", ">="


class Is(ComparisonOperator):
    kind, symbol = "Is", "is"


class IsNot(ComparisonOperator):
    kind, symbol = "IsNot", "is not"


class In(ComparisonOperator):
    kind, symbol = "In", "in"


class NotIn(ComparisonOperator):
    kind, symbol = "NotIn", "not in"


_OPERATORS: dict[str, type[Operator]] = {
    cls.kind: cls
    for cls in (
        Add,
        Sub,
        Mult,
        MatMult,
        Div,
        Mod,
        Pow,
        LShift,
        RShift,
        BitOr,
        BitXor,
        BitAnd,
        FloorDiv,
        UAdd,
        USub,
        Not,
        Invert,
        And,
        Or,
        Eq,
        NotEq,
        Lt,
        LtE,
        Gt,
        GtE,
        Is,
        IsNot,
        In,
        NotIn,
    )
}


def operator_for(kind: str) -> Operator:
    """Frozen-vocabulary lookup: two arms — resolved, or panic."""
    cls = _OPERATORS.get(kind)
    if cls is None:
        vocabulary_missing(
            owner="operators.operator_for",
            observed=f"operator kind {kind!r} not in the frozen vocabulary",
            requested="one of the declared Operator classes",
            fix="a new operator is a new class here, declared on purpose — never a silent addition",
        )
        raise AssertionError("unreachable")
    return cls.instance()
