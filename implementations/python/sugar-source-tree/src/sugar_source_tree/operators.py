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
                blame=cls,
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
    """Operators of BinOp / AugAssign.

    ``inplace_operator`` is the native-operation carrier name AugAssign mints
    for formal ``OP=`` (e.g. ``iadd`` for ``+=``).  Declared on the operator
    class so production's enrolled set is derived from constructors — never
    from the projector table (circular equality tooth).
    """

    inplace_operator: str = ""


class UnaryOperator(Operator):
    """Operators of UnaryOp."""


class BooleanOperator(Operator):
    """Operators of BoolOp."""


class ComparisonOperator(Operator):
    """Operators of Compare."""


class Add(BinaryOperator):
    kind, symbol, inplace_operator = "Add", "+", "iadd"


class Sub(BinaryOperator):
    kind, symbol, inplace_operator = "Sub", "-", "isub"


class Mult(BinaryOperator):
    kind, symbol, inplace_operator = "Mult", "*", "imul"


class MatMult(BinaryOperator):
    kind, symbol, inplace_operator = "MatMult", "@", "imatmul"


class Div(BinaryOperator):
    kind, symbol, inplace_operator = "Div", "/", "itruediv"


class Mod(BinaryOperator):
    kind, symbol, inplace_operator = "Mod", "%", "imod"


class Pow(BinaryOperator):
    kind, symbol, inplace_operator = "Pow", "**", "ipow"


class LShift(BinaryOperator):
    kind, symbol, inplace_operator = "LShift", "<<", "ilshift"


class RShift(BinaryOperator):
    kind, symbol, inplace_operator = "RShift", ">>", "irshift"


class BitOr(BinaryOperator):
    kind, symbol, inplace_operator = "BitOr", "|", "ior"


class BitXor(BinaryOperator):
    kind, symbol, inplace_operator = "BitXor", "^", "ixor"


class BitAnd(BinaryOperator):
    kind, symbol, inplace_operator = "BitAnd", "&", "iand"


class FloorDiv(BinaryOperator):
    kind, symbol, inplace_operator = "FloorDiv", "//", "ifloordiv"


# BinaryOperator classes AugAssign may host — production mint set source.
AUGASSIGN_BINARY_OPERATOR_CLASSES: tuple[type[BinaryOperator], ...] = (
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
)


def production_augassign_inplace_operators() -> frozenset[str]:
    """Inplace carrier names AugAssign production may mint.

    Derived **only** from BinaryOperator class attributes — independent of
    any projector table.  Equality tooth: this set must equal the i* keys
    enrolled on the projector side.
    """
    return frozenset(
        cls.inplace_operator
        for cls in AUGASSIGN_BINARY_OPERATOR_CLASSES
        if cls.inplace_operator
    )


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


def operator_for(kind: str, *, blame: object) -> Operator:
    """Frozen-vocabulary lookup: two arms — resolved, or panic."""
    cls = _OPERATORS.get(kind)
    if cls is None:
        vocabulary_missing(
            blame=blame,
            owner="operators.operator_for",
            observed=f"operator kind {kind!r} not in the frozen vocabulary",
            requested="one of the declared Operator classes",
            fix="a new operator is a new class here, declared on purpose — never a silent addition",
        )
        raise AssertionError("unreachable")
    return cls.instance()
