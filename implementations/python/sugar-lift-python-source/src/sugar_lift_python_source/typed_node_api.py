"""Read-only traversal surface for the legacy reference lifters.

This module is deliberately only a vocabulary over ``sugar_source_tree``
nodes.  It neither parses source nor manufactures nodes: source enters through
``SourceFile`` and every value accepted here is an already-materialized typed
node.  The small visitor helpers let the reference encoders migrate as one
cluster without retaining a second stdlib-AST semantic path.
"""

from __future__ import annotations

from pathlib import Path
import sys

_tree_src = Path(__file__).resolve().parents[3] / "sugar-source-tree" / "src"
if _tree_src.is_dir() and str(_tree_src) not in sys.path:
    sys.path.insert(0, str(_tree_src))

from sugar_source_tree import nodes as _nodes
from sugar_source_tree import operators as _operators
from sugar_source_tree.tree import SourceFile

from .canonical import blake3_512_of

AST = _nodes.Node
stmt = _nodes.Statement
expr = _nodes.Expression
pattern = _nodes.Pattern
operator = _operators.BinaryOperator
unaryop = _operators.UnaryOperator
boolop = _operators.BooleanOperator
cmpop = _operators.ComparisonOperator

# Typed grammar aliases.  Tuple is spelled Tuple_ in the source-tree grammar.
Module = _nodes.Module
FunctionDef = _nodes.FunctionDef
AsyncFunctionDef = _nodes.AsyncFunctionDef
ClassDef = _nodes.ClassDef
Return = _nodes.Return
Delete = _nodes.Delete
Assign = _nodes.Assign
TypeAlias = _nodes.TypeAlias
AugAssign = _nodes.AugAssign
AnnAssign = _nodes.AnnAssign
For = _nodes.For
AsyncFor = _nodes.AsyncFor
While = _nodes.While
If = _nodes.If
With = _nodes.With
AsyncWith = _nodes.AsyncWith
Match = _nodes.Match
Raise = _nodes.Raise
Try = _nodes.Try
TryStar = _nodes.TryStar
Assert = _nodes.Assert
Import = _nodes.Import
ImportFrom = _nodes.ImportFrom
Global = _nodes.Global
Nonlocal = _nodes.Nonlocal
Expr = _nodes.Expr
Pass = _nodes.Pass
Break = _nodes.Break
Continue = _nodes.Continue
ExceptHandler = _nodes.ExceptHandler
match_case = _nodes.MatchCase

BoolOp = _nodes.BoolOp
NamedExpr = _nodes.NamedExpr
BinOp = _nodes.BinOp
UnaryOp = _nodes.UnaryOp
Lambda = _nodes.Lambda
IfExp = _nodes.IfExp
Dict = _nodes.Dict
Set = _nodes.Set
ListComp = _nodes.ListComp
SetComp = _nodes.SetComp
DictComp = _nodes.DictComp
GeneratorExp = _nodes.GeneratorExp
Await = _nodes.Await
Yield = _nodes.Yield
YieldFrom = _nodes.YieldFrom
Compare = _nodes.Compare
Call = _nodes.Call
FormattedValue = _nodes.FormattedValue
JoinedStr = _nodes.JoinedStr
Constant = _nodes.Constant
Attribute = _nodes.Attribute
Subscript = _nodes.Subscript
Starred = _nodes.Starred
Name = _nodes.Name
List = _nodes.List
Tuple = _nodes.Tuple_
Slice = _nodes.Slice
MatchValue = _nodes.MatchValue
MatchSingleton = _nodes.MatchSingleton
MatchSequence = _nodes.MatchSequence
MatchMapping = _nodes.MatchMapping
MatchClass = _nodes.MatchClass
MatchStar = _nodes.MatchStar
MatchAs = _nodes.MatchAs
MatchOr = _nodes.MatchOr
arg = _nodes.Param
alias = _nodes.ImportAlias
keyword = _nodes.Keyword
comprehension = _nodes.Comprehension

Add = _operators.Add
Sub = _operators.Sub
Mult = _operators.Mult
MatMult = _operators.MatMult
Div = _operators.Div
Mod = _operators.Mod
Pow = _operators.Pow
LShift = _operators.LShift
RShift = _operators.RShift
BitOr = _operators.BitOr
BitXor = _operators.BitXor
BitAnd = _operators.BitAnd
FloorDiv = _operators.FloorDiv
UAdd = _operators.UAdd
USub = _operators.USub
Not = _operators.Not
Invert = _operators.Invert
And = _operators.And
Or = _operators.Or
Eq = _operators.Eq
NotEq = _operators.NotEq
Lt = _operators.Lt
LtE = _operators.LtE
Gt = _operators.Gt
GtE = _operators.GtE
Is = _operators.Is
IsNot = _operators.IsNot
In = _operators.In
NotIn = _operators.NotIn


def walk(node: AST):
    return node.walk()


def parse(source: str, *, filename: str) -> Module:
    """Materialize one authenticated typed module through the sole adapter."""
    return SourceFile((source, filename, blake3_512_of(source.encode("utf-8")))).root


def iter_child_nodes(node: AST):
    return (child for _, _, child in node.children())


def iter_fields(node: AST):
    for field_name in type(node)._child_fields:
        yield field_name, getattr(node, field_name)


class TypedNodeWalker:
    """The stdlib visitor protocol over typed children only."""

    def visit(self, node: AST):
        method = getattr(self, f"visit_{type(node).__name__.removesuffix('_')}", None)
        if method is None:
            return self.generic_visit(node)
        return method(node)

    def generic_visit(self, node: AST):
        for child in iter_child_nodes(node):
            self.visit(child)


def unparse(node: AST) -> str:
    """Return the authenticated source spelling of this typed occurrence."""
    return node.fragment.text


def get_docstring(node: FunctionDef | AsyncFunctionDef | ClassDef, clean: bool = True):
    del clean  # Source spelling is already parsed; no second text interpreter.
    if not node.body:
        return None
    first = node.body[0]
    if isinstance(first, Expr) and isinstance(first.value, Constant):
        return first.value.value if isinstance(first.value.value, str) else None
    return None


def literal_eval(node: AST):
    """Project an already-constructed literal tree; reject all computed values."""
    if isinstance(node, Constant):
        return node.value
    if isinstance(node, (List, Tuple, Set)):
        values = [literal_eval(item) for item in node.elts]
        if isinstance(node, List):
            return values
        if isinstance(node, Tuple):
            return tuple(values)
        return set(values)
    if isinstance(node, Dict):
        result = {}
        for item in node.items:
            if item.key is None:
                raise ValueError("dictionary spread is not a literal projection")
            result[literal_eval(item.key)] = literal_eval(item.value)
        return result
    if isinstance(node, UnaryOp) and isinstance(node.op, (UAdd, USub)):
        value = literal_eval(node.operand)
        if not isinstance(value, (int, float, complex)):
            raise ValueError("unary literal operand is not numeric")
        return value if isinstance(node.op, UAdd) else -value
    raise ValueError(f"{type(node).__name__} is not a literal projection")
