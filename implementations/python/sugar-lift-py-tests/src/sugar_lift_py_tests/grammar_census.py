"""Body-shape census classifier — the corpus's vote, brought in-repo.

This is the classification function that ran over the top-1000 PyPI
sdists (128,766 files, 1,519,521 functions, battleaxe ~/census.py,
2026-06-12): every FunctionDef body lands in exactly ONE primary shape
bucket, plus orthogonal flags. TOTAL by construction: every last
statement that is not a value-return falls into the parametric
``non-return:<Stmt>`` bucket and every return value that matches no
named shape falls into ``return-other:<Expr>`` — there is no silent
drop, so the bucket vocabulary is exactly (named shapes) ∪ (parametric
buckets over the interpreter's own grammar), which is what lets
grammar_ledger hold an import-time totality floor against it.

Kept byte-faithful to the corpus run's semantics; changing a bucket
boundary here re-buckets the census, so any edit must re-run the corpus.
"""

from __future__ import annotations

from typing import List, Tuple

from .factory.source_fragment import SourceFragment


def _strip_doc(body: List[SourceFragment]) -> List[SourceFragment]:
    return [
        s
        for s in body
        if not (
            s.observed == "Expr"
            and s.expr_value().observed == "PrimitiveLiteral"
            and isinstance(s.expr_value().literal_value(), str)
        )
    ]


def _is_literalish(node: SourceFragment) -> bool:
    return node.observed == "PrimitiveLiteral"


def classify(fn: SourceFragment) -> Tuple[str, List[str]]:
    """Primary bucket + orthogonal flags. TOTAL: always returns a bucket."""
    body = _strip_doc(fn.function_body())
    flags = []
    if not body:
        return "empty", flags

    # guard-then-raise prefix: one or more `if X: raise` leading statements
    guards = 0
    for s in body:
        if (
            s.observed == "If"
            and len(s.if_body()) == 1
            and s.if_body()[0].observed == "Raise"
            and not s.if_orelse()
        ):
            guards += 1
        else:
            break
    if guards:
        flags.append("guard-then-raise-prefix")

    # table-loop: any for-loop whose body subscripts a Name and accumulates
    for s in fn.walk():
        if s.observed in ("For", "AsyncFor"):
            has_sub = any(
                n.observed == "Subscript" and n.subscript_receiver().observed == "Name"
                for n in s.walk()
            )
            has_acc = any(
                n.observed == "AugAssign"
                or (
                    n.observed == "Call"
                    and n.call_is_method_call()
                    and n.call_target_name() in ("append", "extend", "write", "add")
                )
                for n in s.walk()
            )
            if has_sub and has_acc:
                flags.append("table-loop")
                break

    last = body[-1]
    if last.observed != "Return" or last.return_value() is None:
        return f"non-return:{last.observed}", flags
    v = last.return_value()

    if v.observed == "Call":
        if v.call_is_method_call():
            a = v.call_target_name()
            args = v.call_args()
            lit1 = len(args) == 1 and _is_literalish(args[0])
            if a == "translate":
                return "return-translate", flags
            if a in ("rstrip", "lstrip", "strip") and lit1:
                return "return-strip-literal", flags
            if a == "replace" and len(args) == 2 and all(map(_is_literalish, args)):
                return "return-replace-literals", flags
            if a == "join":
                return "return-join", flags
            if a in ("encode", "decode"):
                return "return-encode-decode", flags
            if a == "format":
                return "return-format", flags
            if a in ("upper", "lower", "casefold", "title"):
                return "return-case-method", flags
            return "return-method-call", flags
        if v.call_func().observed == "Name":
            if len(body) == 1:
                return "pure-delegation", flags
            return "return-fn-call", flags
        return "return-call-other", flags
    if v.observed == "Subscript" and v.subscript_receiver().observed == "Name":
        return "return-table-subscript", flags
    if v.observed == "PrimitiveLiteral":
        return "return-constant", flags
    if v.observed == "Name":
        return "return-name", flags
    if v.observed == "BinOp":
        return "return-binop", flags
    if v.observed in ("Compare", "BoolOp") or (
        v.observed == "UnaryOp" and v.operator_kind() == "Not"
    ):
        return "return-predicate", flags
    if v.observed == "IfExp":
        return "return-ifexp", flags
    if v.observed == "JoinedStr":
        return "return-fstring", flags
    if v.observed in ("Tuple", "List", "Dict", "Set"):
        return "return-collection", flags
    if v.observed == "Attribute":
        return "return-attribute", flags
    return f"return-other:{v.observed}", flags
