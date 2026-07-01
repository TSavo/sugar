"""Emit Hypothesis test modules from neutral predicate terms."""

from __future__ import annotations

import keyword
import operator
import re
from dataclasses import dataclass, field
from typing import Any, Callable

import blake3

_CONCEPT_PREFIX = "concept:"

_BINARY_OPS: dict[str, tuple[str, Callable[[Any, Any], bool]]] = {
    "eq": ("==", operator.eq),
    "ne": ("!=", operator.ne),
    "neq": ("!=", operator.ne),
    "lt": ("<", operator.lt),
    "gt": (">", operator.gt),
    "le": ("<=", operator.le),
    "lte": ("<=", operator.le),
    "ge": (">=", operator.ge),
    "gte": (">=", operator.ge),
}


@dataclass(frozen=True)
class EmitPlan:
    """The emit request: neutral predicates plus target function metadata."""

    contract_id: str = ""
    function: str = "test"
    params: list[str] = field(default_factory=list)
    param_types: list[str] = field(default_factory=list)
    predicates: list[dict[str, Any]] = field(default_factory=list)

    @staticmethod
    def from_params(params: dict[str, Any]) -> "EmitPlan":
        if not isinstance(params, dict):
            return EmitPlan()
        contract_id = _first_str(params.get("contract_id"))
        function = (
            _first_str(params.get("function"), params.get("function_name")) or "test"
        )
        formals = _string_list(params.get("params"))
        formal_types = _string_list(params.get("param_types"))
        predicates = [p for p in _list(params.get("predicates")) if isinstance(p, dict)]
        return EmitPlan(contract_id, function, formals, formal_types, predicates)


@dataclass(frozen=True)
class Emission:
    """The emission result: source text, per-predicate gaps, and a CID."""

    source: str
    path: str
    artifact_cid: str
    emitted_predicates: list[str]
    unsupported_predicates: list[str]
    kind: str = "hypothesis-test-emission"

    @property
    def is_complete(self) -> bool:
        return not self.unsupported_predicates and bool(self.emitted_predicates)

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "source": self.source,
            "path": self.path,
            "extension": "py",
            "emitted_artifact_cid": self.artifact_cid,
            "emitted_predicates": list(self.emitted_predicates),
            "unsupported_predicates": list(self.unsupported_predicates),
            "is_complete": self.is_complete,
        }


@dataclass(frozen=True)
class _Term:
    expr: str
    var_name: str | None = None
    const_value: Any = None
    has_const: bool = False


@dataclass
class _RenderContext:
    declarations: list[str] = field(default_factory=list)
    assigned: dict[str, str] = field(default_factory=dict)

    def assign(self, name: str, expr: str) -> None:
        if name in self.assigned:
            return
        self.assigned[name] = expr
        self.declarations.append(f"{name} = {expr}")


def emit(plan: EmitPlan) -> Emission:
    """Emit a Hypothesis test module for the contract described by ``plan``."""
    emitted: list[str] = []
    unsupported: list[str] = []
    functions: list[str] = []

    for idx, predicate in enumerate(plan.predicates):
        head = head_of(predicate)
        rendered = _render_predicate(predicate)
        if head is None or rendered is None:
            unsupported.append(head if head is not None else "<malformed>")
            continue
        emitted.append(head)
        declarations, assertion = rendered
        functions.append(
            _render_test_function(_function_name(head, idx), declarations, assertion)
        )

    source = _render_module(functions)
    cid = "blake3-512:" + blake3.blake3(source.encode("utf-8")).digest(length=64).hex()
    return Emission(source, _module_path(plan.function), cid, emitted, unsupported)


def head_of(predicate: dict[str, Any]) -> str | None:
    """Return the predicate head with the ``concept:`` prefix stripped."""
    if not isinstance(predicate, dict):
        return None
    name = predicate.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    if name.startswith(_CONCEPT_PREFIX):
        return name[len(_CONCEPT_PREFIX) :]
    return name


def supported_predicates() -> list[str]:
    return [
        "concept:eq",
        "concept:ne",
        "concept:lt",
        "concept:gt",
        "concept:le",
        "concept:ge",
        "concept:option-is-some",
        "concept:option-is-none",
    ]


def _render_predicate(predicate: dict[str, Any]) -> tuple[list[str], str] | None:
    head = head_of(predicate)
    args = _args_of(predicate)
    if head in _BINARY_OPS:
        return _render_binary(head, args)
    if head in ("option-is-none",):
        return _render_option(args, expect_none=True)
    if head in ("option-is-some", "not-null"):
        return _render_option(args, expect_none=False)
    return None


def _render_binary(head: str, args: list[Any]) -> tuple[list[str], str] | None:
    if len(args) != 2:
        return None
    left = _render_term(args[0])
    right = _render_term(args[1])
    if left is None or right is None:
        return None

    symbol, const_eval = _BINARY_OPS[head]
    ctx = _RenderContext()
    if not _assign_binary_terms(ctx, head, left, right, const_eval):
        return None
    return ctx.declarations, f"assert {left.expr} {symbol} {right.expr}"


def _render_option(args: list[Any], expect_none: bool) -> tuple[list[str], str] | None:
    if len(args) != 1:
        return None
    term = _render_term(args[0])
    if term is None:
        return None
    ctx = _RenderContext()
    if term.var_name is not None:
        if expect_none:
            ctx.assign(term.var_name, "data.draw(st.none())")
        else:
            ctx.assign(
                term.var_name,
                "data.draw(st.one_of(st.integers(), st.text(), st.booleans()))",
            )
    elif term.has_const:
        if (term.const_value is None) != expect_none:
            return None
    else:
        return None
    predicate = "is None" if expect_none else "is not None"
    return ctx.declarations, f"assert {term.expr} {predicate}"


def _assign_binary_terms(
    ctx: _RenderContext,
    head: str,
    left: _Term,
    right: _Term,
    const_eval: Callable[[Any, Any], bool],
) -> bool:
    if left.has_const and right.has_const:
        return bool(const_eval(left.const_value, right.const_value))
    if left.var_name is not None and right.var_name is not None:
        return _assign_var_var(ctx, head, left.var_name, right.var_name)
    if left.var_name is not None and right.has_const:
        return _assign_var_const(
            ctx, head, left.var_name, right.const_value, const_on_right=True
        )
    if left.has_const and right.var_name is not None:
        return _assign_var_const(
            ctx, head, right.var_name, left.const_value, const_on_right=False
        )
    return False


def _assign_var_var(ctx: _RenderContext, head: str, left: str, right: str) -> bool:
    if left == right:
        if head in ("eq", "le", "lte", "ge", "gte"):
            ctx.assign(left, "data.draw(st.integers())")
            return True
        return False

    ctx.assign(left, "data.draw(st.integers())")
    if head == "eq":
        ctx.assign(right, left)
    elif head in ("ne", "neq", "lt"):
        ctx.assign(right, f"data.draw(st.integers(min_value={left} + 1))")
    elif head == "gt":
        ctx.assign(right, f"data.draw(st.integers(max_value={left} - 1))")
    elif head in ("le", "lte"):
        ctx.assign(right, f"data.draw(st.integers(min_value={left}))")
    elif head in ("ge", "gte"):
        ctx.assign(right, f"data.draw(st.integers(max_value={left}))")
    else:
        return False
    return True


def _assign_var_const(
    ctx: _RenderContext,
    head: str,
    var_name: str,
    const_value: Any,
    *,
    const_on_right: bool,
) -> bool:
    if head == "eq":
        if not _is_literal_const(const_value):
            return False
        ctx.assign(var_name, f"data.draw(st.just({_render_const_value(const_value)}))")
        return True
    if head in ("ne", "neq"):
        if not _is_int_const(const_value):
            return False
        ctx.assign(
            var_name,
            "data.draw(st.one_of("
            f"st.integers(max_value={const_value - 1}), "
            f"st.integers(min_value={const_value + 1})"
            "))",
        )
        return True
    if not _is_int_const(const_value):
        return False

    lower_heads = {"lt", "le", "lte"}
    greater_heads = {"gt", "ge", "gte"}
    inclusive_heads = {"le", "lte", "ge", "gte"}
    delta = 0 if head in inclusive_heads else 1

    if (head in lower_heads and const_on_right) or (
        head in greater_heads and not const_on_right
    ):
        ctx.assign(var_name, f"data.draw(st.integers(max_value={const_value - delta}))")
        return True
    if (head in greater_heads and const_on_right) or (
        head in lower_heads and not const_on_right
    ):
        ctx.assign(var_name, f"data.draw(st.integers(min_value={const_value + delta}))")
        return True
    return False


def _render_term(term: Any) -> _Term | None:
    if not isinstance(term, dict):
        return None
    kind = term.get("kind")
    if kind == "var":
        name = term.get("name")
        if not _is_identifier(name):
            return None
        return _Term(expr=name, var_name=name)
    if kind == "const":
        if "value" not in term:
            return None
        value = term["value"]
        if not _is_literal_const(value):
            return None
        return _Term(expr=_render_const_value(value), const_value=value, has_const=True)
    return None


def _render_const_value(value: Any) -> str:
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "True" if value else "False"
    return repr(value)


def _is_identifier(value: Any) -> bool:
    return (
        isinstance(value, str) and value.isidentifier() and not keyword.iskeyword(value)
    )


def _is_literal_const(value: Any) -> bool:
    return value is None or isinstance(value, (bool, int, str))


def _is_int_const(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _args_of(predicate: dict[str, Any]) -> list[Any]:
    args = predicate.get("args")
    return args if isinstance(args, list) else []


def _module_path(function: str) -> str:
    safe = re.sub(r"[^0-9A-Za-z_]+", "_", function or "").strip("_").lower()
    if not safe:
        safe = "contract"
    return f"test_{safe}_hypothesis_contract.py"


def _render_test_function(name: str, declarations: list[str], assertion: str) -> str:
    lines = ["@given(data=st.data())", f"def {name}(data):"]
    for decl in declarations:
        lines.append(f"    {decl}")
    lines.append(f"    {assertion}")
    return "\n".join(lines) + "\n"


def _render_module(functions: list[str]) -> str:
    parts = ["from hypothesis import given, strategies as st\n\n"]
    parts.append("\n".join(functions))
    return "".join(parts)


def _function_name(head: str | None, idx: int) -> str:
    safe = (head or "predicate").replace("-", "_")
    return f"test_verifies_{safe}_{idx}"


def _first_str(*candidates: Any) -> str:
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    return ""


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []
