"""Verify-facing dialect transform for the Python source lifter.

This is the Python analog of Go's ``LiftSourceCore`` / ``NormalizeCoreArith``
(PR #1445). The round-trip source lifter (``lifter.py``) emits a
``function-contract`` whose ``post`` is::

    (= (var return_value) (python:return (python:mul (var x) (const 2 Int))))

with namespaced ops, the ``return_value`` result variable, a ``python:return``
wrapper, and ``Value`` sorts. That form is byte-identical to what the
round-trip / realize pipeline depends on and MUST NOT change on disk.

The verifier's ``body_discharge::CatalogResolver`` instead needs a
z3-dischargeable ``function-contract`` whose ``post`` is::

    (= (var result) (* (var x) (const 2 Int)))

i.e. the SMT result var ``result``, no ``python:return`` wrapper, SMT-core op
symbols (``*``, ``+``, ``<`` ...), and ``Int`` formal/return sorts. This module
performs exactly that transform and REFUSES (returns ``None`` with a reason)
rather than emit an unsound contract.

Supra omnia, rectum: the cardinal rule mirrored from the Go division lesson is
that ``python:div`` / ``python:floordiv`` / ``python:mod`` are LEFT
NAMESPACED (uninterpreted). SMT-LIB ``div``/``mod`` floor toward -inf and
diverge from Python truncation / float semantics on negatives, so mapping them
would let a Python-false assertion discharge with a signed witness. Leaving
them uninterpreted makes the obligation Undecidable instead -- the honest
refusal.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any

Json = dict[str, Any]

# SMT result variable the verifier's body-discharge seam equates the call's
# result with (matches libsugar::wp::DEFAULT_RESULT_VAR == "result").
RESULT_VAR = "result"

# KEPT (faithful core): the SMT-LIB symbol for each namespaced arithmetic /
# comparison / boolean op whose Int (or Bool) semantics coincide with the
# SMT-LIB core theory for the value domain we model.
#
# EXCLUDED (deliberately absent -> stay namespaced -> Undecidable):
#   python:div       true division `/`  (float result; not integer SMT div)
#   python:floordiv  floor division `//`
#   python:mod       modulo `%`
#   python:pow, shifts, bitwise ops, is/in comparisons
# All of these have no faithful core mapping for signed ints, so a contract
# that uses them refuses to z3 rather than risk a false discharge.
_CORE_ARITH_OP: dict[str, str] = {
    "python:add": "+",
    "python:sub": "-",
    "python:mul": "*",
    "python:neg": "-",
    "python:not": "not",
    "python:and": "and",
    "python:or": "or",
}

# Comparison operators carried as the string head of a `python:compare` ctor.
_CORE_CMP_OP: dict[str, str] = {
    "==": "=",
    "!=": "≠",
    "<": "<",
    "<=": "≤",
    ">": ">",
    ">=": "≥",
}

# Annotation surfaces that faithfully map to an SMT sort. Anything else
# (no annotation, `float`, custom types) refuses for a typed body. `str` maps to
# SMT `String` so dig-shape string functions (`if x == "ccc": return "yyy"`)
# can emit a bridgeable function-contract -- the same ambient-post path the
# int arithmetic cases already ride.
_INT_ANNOTATIONS = {"int"}
_BOOL_ANNOTATIONS = {"bool"}
_STRING_ANNOTATIONS = {"str"}


class VerifyDialectRefusal(Exception):
    """Raised when a lifted function-contract cannot be faithfully lowered to
    the z3-dischargeable verify-facing dialect. The caller turns this into a
    diagnostic and SKIPS emitting a contract -- never an unsound one."""

    def __init__(self, fn_name: str, reason: str):
        self.fn_name = fn_name
        self.reason = reason
        super().__init__(f"{fn_name}: {reason}")


@dataclass(frozen=True)
class _Sorts:
    """SMT sorts for a function's formals + return, derived from the source
    `: int` / `-> int` annotations (the round-trip lifter erases these to
    `Value`)."""

    formal_sorts: dict[str, str]  # formal name -> "Int" | "Bool" | "String"
    return_sort: str | None  # "Int" | "Bool" | "String" | None


def prim_sort(name: str) -> Json:
    return {"kind": "primitive", "name": name}


def collect_int_signatures(source: str, module_path: str = "") -> dict[str, _Sorts]:
    """Parse `source` and return, per QUALIFIED function name, the SMT sorts of
    its annotated formals + return. Only `int` / `bool` annotations are
    recorded; others are omitted (the transform refuses when a needed sort is
    missing).

    The key mirrors the lifter's `fnName` (`lifter._qualname` /
    `_DefinitionCollector`): class scopes prepend the class name, nested
    function scopes prepend `<name>.<locals>`, and -- when `module_path` is
    given -- the whole qualname is prefixed with `module_path.`, matching
    `f"{module_path}.{qualname}"` byte-for-byte. Two functions that share only
    a bare leaf name (a method on another class, a nested helper shadowing a
    module-level function of the same name, ...) get DISTINCT keys here; a
    lookup by bare leaf name would collide them."""
    out: dict[str, _Sorts] = {}
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return out

    def visit(node: ast.AST, scope: list[tuple[str, str]]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.ClassDef):
                visit(child, scope + [("class", child.name)])
            elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualname = _qualified_name(scope, child.name)
                key = f"{module_path}.{qualname}" if module_path else qualname
                formal_sorts: dict[str, str] = {}
                for arg in child.args.args:
                    sort = _sort_for_annotation(arg.annotation)
                    if sort is not None:
                        formal_sorts[arg.arg] = sort
                return_sort = _sort_for_annotation(child.returns)
                out[key] = _Sorts(formal_sorts=formal_sorts, return_sort=return_sort)
                visit(child, scope + [("function", child.name)])
            else:
                visit(child, scope)

    visit(tree, [])
    return out


def _qualified_name(scope: list[tuple[str, str]], name: str) -> str:
    """Mirrors `lifter._qualname`: class scopes contribute their bare name,
    function scopes contribute `<name>.<locals>`."""
    parts: list[str] = []
    for kind, scope_name in scope:
        if kind == "class":
            parts.append(scope_name)
        elif kind == "function":
            parts.extend([scope_name, "<locals>"])
    parts.append(name)
    return ".".join(parts)


def _sort_for_annotation(annotation: ast.expr | None) -> str | None:
    if annotation is None:
        return None
    if isinstance(annotation, ast.Name):
        if annotation.id in _INT_ANNOTATIONS:
            return "Int"
        if annotation.id in _BOOL_ANNOTATIONS:
            return "Bool"
        if annotation.id in _STRING_ANNOTATIONS:
            return "String"
    return None


def to_verify_dialect(contract: Json, sorts: _Sorts) -> Json:
    """Lower a round-trip `function-contract` to the z3-dischargeable
    verify-facing dialect, or raise `VerifyDialectRefusal`.

    Steps (mirroring Go LiftSourceCore + the result-var/return-unwrap that Go
    did not need):
      1. Strip the `python:return` wrapper from the post's value expression.
      2. Rename the result var `return_value` -> `result`.
      3. Normalize `python:*` ops to SMT-core symbols; refuse on any op with
         no faithful core mapping (div/mod/floordiv/pow/shifts/...).
      4. Replace the `Value` formal/return sorts with `Int`/`Bool` from the
         source annotations; refuse if a formal touched by arithmetic lacks an
         int/bool annotation.
    """
    fn_name = str(contract.get("fnName", "<unknown>"))
    post = contract.get("post")
    if not isinstance(post, dict) or post.get("name") != "=":
        raise VerifyDialectRefusal(fn_name, "post is not an `=` atomic")
    args = post.get("args")
    if not isinstance(args, list) or len(args) != 2:
        raise VerifyDialectRefusal(fn_name, "post `=` does not have exactly two args")
    lhs, rhs = args[0], args[1]
    if not (
        isinstance(lhs, dict)
        and lhs.get("kind") == "var"
        and lhs.get("name") == "return_value"
    ):
        raise VerifyDialectRefusal(
            fn_name, "post LHS is not the `return_value` result var"
        )
    precondition_guarded_body = _body_has_precondition_guard_prefix(rhs)

    # 1. Unwrap the single `python:return(<value>)` the body folds to. A body
    #    that is anything other than exactly one bare return (e.g. a sequence,
    #    a conditional, an assignment) does NOT produce a `result == value`
    #    shape and is refused here -- the honest posture, not a mangle.
    value_expr = _unwrap_return(rhs, fn_name)

    # 2 + 3. Normalize the value expression's ops + literals to core SMT.
    formal_sorts_map = sorts.formal_sorts
    core_value = _normalize_term(value_expr, fn_name, formal_sorts_map)
    core_pre = _normalize_formula(contract.get("pre"), fn_name, formal_sorts_map)

    # 4. Sorts: every formal must carry an Int/Bool annotation (the lifter
    #    erased them to `Value`, which z3 cannot reason about for arithmetic).
    formals = contract.get("formals")
    if not isinstance(formals, list):
        raise VerifyDialectRefusal(fn_name, "contract has no formals array")
    new_formal_sorts: list[Json] = []
    for formal in formals:
        sort = formal_sorts_map.get(str(formal))
        if sort is None:
            raise VerifyDialectRefusal(
                fn_name,
                f"formal `{formal}` lacks an `int`/`bool`/`str` annotation; refusing "
                f"rather than emit a `Value`-sorted obligation z3 cannot discharge",
            )
        new_formal_sorts.append(prim_sort(sort))
    return_sort = sorts.return_sort
    if return_sort is None:
        raise VerifyDialectRefusal(
            fn_name, "return lacks an `int`/`bool`/`str` annotation; refusing"
        )

    out = dict(contract)
    if precondition_guarded_body:
        guard_exception_classes = _panic_locus_exception_classes(out.get("panicLoci"))
        out.pop("panicLoci", None)
        effects = out.get("effects")
        if isinstance(effects, list):
            out["effects"] = [
                effect
                for effect in effects
                if not _is_guard_raise_effect(effect, guard_exception_classes)
            ]
    out["formalSorts"] = new_formal_sorts
    out["returnSort"] = prim_sort(return_sort)
    out["post"] = {
        "kind": "atomic",
        "name": "=",
        "args": [{"kind": "var", "name": RESULT_VAR}, core_value],
    }
    out["pre"] = core_pre
    # The bridge-writer (#1443) keys the auto-bridge on `bridgeSourceSymbol`;
    # the harvested callsite ctor uses the bare function name. Set it so
    # `enumerate_callsites` matches `double(3)`.
    out["bridgeSourceSymbol"] = _bare_symbol(fn_name)
    return out


def _unwrap_return(term: Json, fn_name: str) -> Json:
    if (
        isinstance(term, dict)
        and term.get("kind") == "ctor"
        and term.get("name") == "python:return"
    ):
        inner = term.get("args")
        if isinstance(inner, list) and len(inner) == 1:
            return inner[0]
        raise VerifyDialectRefusal(fn_name, "python:return wrapper is malformed")
    # Dig-shape value if: `if cond: return a` / `return b` (else is pass) lowers
    # to `ite(cond, a, b)`. This is the ambient-post body the mint auto-bridges
    # so `assert enc("ccc") == "yyy"` can specialise through the body.
    dig_ite = _dig_shape_if_return_return(term, fn_name)
    if dig_ite is not None:
        return dig_ite
    statements = _flatten_sequence(term)
    if len(statements) >= 2 and all(
        _is_precondition_guard_statement(statement) for statement in statements[:-1]
    ):
        tail = statements[-1]
        if (
            isinstance(tail, dict)
            and tail.get("kind") == "ctor"
            and tail.get("name") == "python:return"
        ):
            inner = tail.get("args")
            if isinstance(inner, list) and len(inner) == 1:
                return inner[0]
            raise VerifyDialectRefusal(fn_name, "python:return wrapper is malformed")
    # A body that did not fold to exactly one return after supported precondition
    # guards (or a dig-shape if-return/return) is not a value-op.
    raise VerifyDialectRefusal(
        fn_name,
        "body does not reduce to supported precondition guard(s) followed by "
        "a single `return <expr>`; refusing",
    )


def _dig_shape_if_return_return(term: Json, fn_name: str) -> Json | None:
    """`if cond: return a` then `return b` (else pass) -> ite(cond, a, b).

    Also accepts a single `if cond: return a else: return b`. Returns None when
    the shape does not match (caller falls through to the existing refusal).
    """
    del fn_name
    # Single if with both arms returning.
    both_arms = _if_both_arms_return(term)
    if both_arms is not None:
        return both_arms
    statements = _flatten_sequence(term)
    if len(statements) != 2:
        return None
    head, tail = statements
    if not _is_python_return(tail):
        return None
    if_parts = _if_then_return_else_pass(head)
    if if_parts is None:
        return None
    cond, then_value = if_parts
    else_value = tail["args"][0]
    return {
        "kind": "ctor",
        "name": "ite",
        "args": [cond, then_value, else_value],
    }


def _if_both_arms_return(term: Json) -> Json | None:
    if (
        not isinstance(term, dict)
        or term.get("kind") != "ctor"
        or term.get("name") != "python:if"
    ):
        return None
    args = term.get("args")
    if not isinstance(args, list) or len(args) != 3:
        return None
    cond, then_branch, else_branch = args
    if not (_is_python_return(then_branch) and _is_python_return(else_branch)):
        return None
    return {
        "kind": "ctor",
        "name": "ite",
        "args": [cond, then_branch["args"][0], else_branch["args"][0]],
    }


def _if_then_return_else_pass(term: Json) -> tuple[Json, Json] | None:
    if (
        not isinstance(term, dict)
        or term.get("kind") != "ctor"
        or term.get("name") != "python:if"
    ):
        return None
    args = term.get("args")
    if not isinstance(args, list) or len(args) != 3:
        return None
    cond, then_branch, else_branch = args
    if not (_is_python_return(then_branch) and _is_python_pass(else_branch)):
        return None
    return cond, then_branch["args"][0]


def _is_python_return(term: Json) -> bool:
    if (
        not isinstance(term, dict)
        or term.get("kind") != "ctor"
        or term.get("name") != "python:return"
    ):
        return False
    args = term.get("args")
    return isinstance(args, list) and len(args) == 1


def _flatten_sequence(term: Json) -> list[Json]:
    if (
        isinstance(term, dict)
        and term.get("kind") == "ctor"
        and term.get("name") == "python:seq"
    ):
        args = term.get("args")
        if isinstance(args, list) and len(args) == 2:
            return [*_flatten_sequence(args[0]), *_flatten_sequence(args[1])]
    return [term]


def _body_has_precondition_guard_prefix(term: Json) -> bool:
    statements = _flatten_sequence(term)
    return len(statements) >= 2 and all(
        _is_precondition_guard_statement(statement) for statement in statements[:-1]
    )


def _panic_locus_exception_classes(value: object) -> set[str]:
    if not isinstance(value, list):
        return set()
    out: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        exception_class = item.get("exceptionClass")
        if isinstance(exception_class, str) and exception_class:
            out.add(exception_class)
    return out


def _is_guard_raise_effect(effect: object, exception_classes: set[str]) -> bool:
    if not isinstance(effect, dict):
        return False
    if effect.get("kind") == "panics":
        return True
    return (
        effect.get("kind") == "unresolved_call"
        and isinstance(effect.get("name"), str)
        and effect["name"] in exception_classes
    )


def _is_precondition_guard_statement(term: Json) -> bool:
    if (
        not isinstance(term, dict)
        or term.get("kind") != "ctor"
        or term.get("name") != "python:if"
    ):
        return False
    args = term.get("args")
    if not isinstance(args, list) or len(args) != 3:
        return False
    condition, then_branch, else_branch = args
    return (
        _is_flat_guard_condition(condition)
        and _is_python_raise(then_branch)
        and _is_python_pass(else_branch)
    )


def _is_flat_guard_condition(term: Json) -> bool:
    if not isinstance(term, dict) or term.get("kind") != "ctor":
        return False
    name = term.get("name")
    args = term.get("args")
    if not isinstance(args, list):
        return False
    if name == "python:compare":
        if len(args) != 3:
            return False
        op_const = args[0]
        op_str = op_const.get("value") if isinstance(op_const, dict) else None
        return (
            str(op_str) in _CORE_CMP_OP
            and _is_flat_guard_term(args[1])
            and _is_flat_guard_term(args[2])
        )
    if name in {"python:and", "python:or"}:
        return len(args) == 2 and all(_is_flat_guard_condition(arg) for arg in args)
    if name == "python:not":
        return len(args) == 1 and _is_flat_guard_condition(args[0])
    return False


def _is_flat_guard_term(term: Json) -> bool:
    if not isinstance(term, dict):
        return False
    kind = term.get("kind")
    if kind == "var":
        return True
    if kind != "const":
        return False
    sort = term.get("sort")
    sort_name = sort.get("name") if isinstance(sort, dict) else None
    return sort_name in {"Int", "Bool", "String"}


def _is_python_raise(term: Json) -> bool:
    return (
        isinstance(term, dict)
        and term.get("kind") == "ctor"
        and term.get("name") == "python:raise"
    )


def _is_python_pass(term: Json) -> bool:
    if (
        not isinstance(term, dict)
        or term.get("kind") != "ctor"
        or term.get("name") != "python:pass"
    ):
        return False
    args = term.get("args")
    return isinstance(args, list) and len(args) == 1


def _normalize_formula(
    formula: object, fn_name: str, formal_sorts: dict[str, str]
) -> Json:
    if not isinstance(formula, dict):
        raise VerifyDialectRefusal(fn_name, "precondition is not an object")
    kind = formula.get("kind")
    if kind == "atomic":
        name = str(formula.get("name", ""))
        raw_args = formula.get("args")
        args = raw_args if isinstance(raw_args, list) else []
        if name in {"true", "false"}:
            if args:
                raise VerifyDialectRefusal(fn_name, f"`{name}` precondition has args")
            return {"kind": "atomic", "name": name, "args": []}
        if name not in {"=", "≠", "<", "≤", ">", "≥"}:
            raise VerifyDialectRefusal(
                fn_name, f"precondition atom `{name}` is not core"
            )
        if len(args) != 2:
            raise VerifyDialectRefusal(
                fn_name, f"precondition atom `{name}` arity != 2"
            )
        return {
            "kind": "atomic",
            "name": name,
            "args": [
                _normalize_term(args[0], fn_name, formal_sorts),
                _normalize_term(args[1], fn_name, formal_sorts),
            ],
        }
    if kind in {"and", "or", "not", "implies"}:
        operands = formula.get("operands")
        if not isinstance(operands, list):
            raise VerifyDialectRefusal(
                fn_name, f"`{kind}` precondition operands missing"
            )
        return {
            "kind": kind,
            "operands": [
                _normalize_formula(operand, fn_name, formal_sorts)
                for operand in operands
            ],
        }
    raise VerifyDialectRefusal(fn_name, f"unsupported precondition kind `{kind}`")


def _normalize_term(term: Json, fn_name: str, formal_sorts: dict[str, str]) -> Json:
    """Recursively rewrite a value-expression term into SMT-core form, or
    refuse. Vars / int / bool consts pass through; `python:compare` becomes the
    core comparison atomic-as-term; other `python:*` ctors map via
    `_CORE_ARITH_OP` or refuse."""
    if not isinstance(term, dict):
        raise VerifyDialectRefusal(fn_name, "non-object term in value expression")
    kind = term.get("kind")
    if kind == "var":
        return term
    if kind == "const":
        sort = term.get("sort")
        sort_name = sort.get("name") if isinstance(sort, dict) else None
        if sort_name in {"Int", "Bool", "String"}:
            return term
        raise VerifyDialectRefusal(
            fn_name,
            f"constant of sort `{sort_name}` is not Int/Bool/String; refusing",
        )
    if kind != "ctor":
        raise VerifyDialectRefusal(fn_name, f"unexpected term kind `{kind}`")

    name = term.get("name", "")
    raw_args = term.get("args")
    args = raw_args if isinstance(raw_args, list) else []

    # Dig-shape value if already lowered by _unwrap_return to `ite(cond, a, b)`.
    if name == "ite":
        if len(args) != 3:
            raise VerifyDialectRefusal(fn_name, "ite arity != 3")
        return {
            "kind": "ctor",
            "name": "ite",
            "args": [
                _normalize_term(args[0], fn_name, formal_sorts),
                _normalize_term(args[1], fn_name, formal_sorts),
                _normalize_term(args[2], fn_name, formal_sorts),
            ],
        }

    if name == "python:compare":
        # python:compare(str_const(op), lhs, rhs) -> core comparison ctor.
        if len(args) != 3:
            raise VerifyDialectRefusal(fn_name, "python:compare arity != 3")
        op_const = args[0]
        op_str = op_const.get("value") if isinstance(op_const, dict) else None
        core_op = _CORE_CMP_OP.get(str(op_str))
        if core_op is None:
            raise VerifyDialectRefusal(
                fn_name, f"comparison op `{op_str}` has no faithful SMT-core mapping"
            )
        return {
            "kind": "ctor",
            "name": core_op,
            "args": [
                _normalize_term(args[1], fn_name, formal_sorts),
                _normalize_term(args[2], fn_name, formal_sorts),
            ],
        }

    core = _CORE_ARITH_OP.get(name)
    if core is None:
        # Includes python:div / python:floordiv / python:mod / python:pow /
        # shifts / bitwise -- all deliberately UNINTERPRETED. We do NOT refuse
        # the whole contract: instead the op stays NAMESPACED so the bridge is
        # still written and wp hits an opaque symbol it cannot reduce, yielding
        # `WpError::Refused` -> the verifier reports Undecidable (exit 3, no
        # witness) via the proven-safe body-discharge refusal path. This
        # mirrors Go's `coreArithOp` returning (_, false) for go:div and is the
        # cardinal-sin guard: a division claim becomes Undecidable, NEVER a
        # false discharge. (Refusing the contract entirely would drop the
        # bridge and fall through to the refinement path, whose honesty for an
        # unbound-ctor callsite is not guaranteed -- see body_discharge.rs.)
        return {
            "kind": "ctor",
            "name": name,
            "args": [
                _normalize_term_uninterpreted(a, fn_name, formal_sorts) for a in args
            ],
        }
    return {
        "kind": "ctor",
        "name": core,
        "args": [_normalize_term(a, fn_name, formal_sorts) for a in args],
    }


def _normalize_term_uninterpreted(
    term: Json, fn_name: str, formal_sorts: dict[str, str]
) -> Json:
    """Normalize the operands of an uninterpreted op. Core arith inside an
    uninterpreted op is still normalized (so `(x + 1) // 2` keeps the `+`),
    but the surrounding uninterpreted op is preserved by `_normalize_term`.
    This is just `_normalize_term`; named separately for intent clarity."""
    return _normalize_term(term, fn_name, formal_sorts)


def _bare_symbol(fn_name: str) -> str:
    """`double.double` / `pkg.mod.double` -> `double` (the bare ident the
    harvested call ctor and the bridge sourceSymbol use)."""
    name = fn_name
    if "(" in name:
        name = name[: name.index("(")]
    if "." in name:
        name = name[name.rindex(".") + 1 :]
    return name
