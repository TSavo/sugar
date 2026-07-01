"""INLINE predicate -> unittest assertion mapping.

The mapping from neutral predicates to ``unittest`` assertion methods is Python
framework knowledge, so it belongs in this Python kit rather than in the Rust
CLI or a substrate catalog template.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

_CONCEPT_PREFIX = "concept:"
_ARITHMETIC = {"+", "-", "*", "/", "%"}


def head_of(predicate: dict[str, Any]) -> Optional[str]:
    """Return the predicate head with any ``concept:`` prefix stripped."""
    if not isinstance(predicate, dict):
        return None
    name = predicate.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    if name.startswith(_CONCEPT_PREFIX):
        return name[len(_CONCEPT_PREFIX) :]
    return name


def supports(head: Optional[str]) -> bool:
    """True if this kit can spell an assertion for ``head``."""
    return head in _HANDLERS


def render(predicate: dict[str, Any]) -> Optional[str]:
    """Render one neutral predicate as a unittest assertion statement.

    Returns ``None`` for unsupported predicate heads, wrong arity, malformed
    terms, or term shapes this emitter cannot safely spell.
    """
    head = head_of(predicate)
    if head is None:
        return None
    handler = _HANDLERS.get(head)
    if handler is None:
        return None
    return handler(_args_of(predicate))


def placeholder_value(head: Optional[str], var_index: int) -> str:
    """Return a placeholder value that makes the standalone emitted test pass."""
    if head == "option-is-none":
        return "None"
    if head in ("option-is-some", "not-null"):
        return "object()"
    if head == "fallible-err":
        return "lambda: (_ for _ in ()).throw(ValueError('contract error'))"
    if head == "lt":
        return "0" if var_index == 0 else "1"
    if head == "gt":
        return "1" if var_index == 0 else "0"
    if head == "ne":
        return "0" if var_index == 0 else "1"
    return "0"


def render_term(term: Any) -> Optional[str]:
    """Render a neutral term subtree to a Python expression."""
    if not isinstance(term, dict):
        return None
    kind = term.get("kind")
    if kind == "var":
        name = term.get("name")
        return name if isinstance(name, str) and name.strip() else None
    if kind == "const":
        return _render_const(term)
    if kind in ("op", "ctor"):
        return _render_application(term)
    return None


def free_vars(term: Any, out: Optional[list[str]] = None) -> list[str]:
    """Collect ``kind:"var"`` names in deterministic encounter order."""
    if out is None:
        out = []
    if not isinstance(term, dict):
        return out
    if term.get("kind") == "var":
        name = term.get("name")
        if isinstance(name, str) and name.strip() and name not in out:
            out.append(name)
        return out
    args = term.get("args")
    if isinstance(args, list):
        for arg in args:
            free_vars(arg, out)
    return out


def supported_predicates() -> list[str]:
    """Catalog-form names of every predicate this kit can emit."""
    return [
        "concept:eq",
        "concept:ne",
        "concept:lt",
        "concept:gt",
        "concept:le",
        "concept:ge",
        "concept:option-is-some",
        "concept:option-is-none",
        "concept:fallible-err",
    ]


def _render_const(obj: dict[str, Any]) -> Optional[str]:
    if "value" not in obj:
        return None
    value = obj["value"]
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, str):
        return repr(value)
    return None


def _render_application(obj: dict[str, Any]) -> Optional[str]:
    name = obj.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    if name.startswith(_CONCEPT_PREFIX):
        name = name[len(_CONCEPT_PREFIX) :]

    rendered_args: list[str] = []
    raw_args = obj.get("args")
    if isinstance(raw_args, list):
        for arg in raw_args:
            rendered = render_term(arg)
            if rendered is None:
                return None
            rendered_args.append(rendered)

    if name in _ARITHMETIC and len(rendered_args) == 2:
        return f"({rendered_args[0]} {name} {rendered_args[1]})"
    return f"{name}({', '.join(rendered_args)})"


def _args_of(predicate: dict[str, Any]) -> list[Any]:
    args = predicate.get("args")
    return args if isinstance(args, list) else []


def _binary(make: Callable[[str, str], str]) -> Callable[[list[Any]], Optional[str]]:
    def handler(args: list[Any]) -> Optional[str]:
        if len(args) != 2:
            return None
        left = render_term(args[0])
        right = render_term(args[1])
        if left is None or right is None:
            return None
        return make(left, right)

    return handler


def _unary(make: Callable[[str], str]) -> Callable[[list[Any]], Optional[str]]:
    def handler(args: list[Any]) -> Optional[str]:
        if len(args) != 1:
            return None
        value = render_term(args[0])
        if value is None:
            return None
        return make(value)

    return handler


_HANDLERS: dict[str, Callable[[list[Any]], Optional[str]]] = {
    "eq": _binary(lambda a, b: f"self.assertEqual({a}, {b})"),
    "ne": _binary(lambda a, b: f"self.assertNotEqual({a}, {b})"),
    "neq": _binary(lambda a, b: f"self.assertNotEqual({a}, {b})"),
    "lt": _binary(lambda a, b: f"self.assertTrue({a} < {b})"),
    "gt": _binary(lambda a, b: f"self.assertTrue({a} > {b})"),
    "le": _binary(lambda a, b: f"self.assertTrue({a} <= {b})"),
    "lte": _binary(lambda a, b: f"self.assertTrue({a} <= {b})"),
    "ge": _binary(lambda a, b: f"self.assertTrue({a} >= {b})"),
    "gte": _binary(lambda a, b: f"self.assertTrue({a} >= {b})"),
    "option-is-some": _unary(lambda x: f"self.assertIsNotNone({x})"),
    "not-null": _unary(lambda x: f"self.assertIsNotNone({x})"),
    "option-is-none": _unary(lambda x: f"self.assertIsNone({x})"),
    "fallible-err": _unary(lambda x: f"with self.assertRaises(Exception):\n    {x}()"),
}
