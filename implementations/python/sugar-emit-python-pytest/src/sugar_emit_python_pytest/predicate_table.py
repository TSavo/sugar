"""INLINE predicate -> pytest assertion mapping.

This is the heart of the emitter and the whole point of PR-7's reframe
(issue #1403): the fact that ``concept:eq`` spells as a python ``assert a == b``
statement is PYTHON FRAMEWORK KNOWLEDGE, written here in python code. It is NOT
substrate data. There is no catalog memento family for this mapping and no
catalog read for the framework spelling. (PR-5, #1401, tried to externalize the
mapping into a ``JUnitAssertionTemplateMemento`` family; that was closed as an
architectural mistake.)

This module is the inverse of the python harvester
(``sugar-lift-py-tests``), which recognizes these same assertions and lifts
them back to neutral predicates. If the two ever want to share the table it
becomes a normal python module dependency, never a substrate catalog memento.

Supported neutral predicates (catalog spelling, with the ``concept:`` prefix
stripped by :func:`head_of`):

==================== ==========================================
neutral predicate    emitted pytest assertion
==================== ==========================================
``eq(a, b)``         ``assert a == b``
``ne(a, b)``         ``assert a != b``
``lt(a, b)``         ``assert a < b``
``gt(a, b)``         ``assert a > b``
``le(a, b)``         ``assert a <= b``
``ge(a, b)``         ``assert a >= b``
``option-is-some(x)``  ``assert x is not None``
``option-is-none(x)``  ``assert x is None``
``fallible-err(x)``    ``with pytest.raises(Exception): x()``
==================== ==========================================
"""

from __future__ import annotations

from typing import Any, Callable, Optional

_CONCEPT_PREFIX = "concept:"

# Neutral op heads handled as infix arithmetic inside term subtrees.
_ARITHMETIC = {"+", "-", "*", "/", "%"}


def head_of(predicate: dict[str, Any]) -> Optional[str]:
    """The predicate head with the ``concept:`` prefix stripped.

    Returns ``None`` if the node is malformed. Accepts both the catalog form
    (``kind:"op"``, ``name:"concept:eq"``) and the harvester's internal form
    (``kind:"atomic"``, bare ``name:"eq"``).
    """
    if not isinstance(predicate, dict):
        return None
    name = predicate.get("name")
    if not isinstance(name, str) or not name.strip():
        return None
    if name.startswith(_CONCEPT_PREFIX):
        return name[len(_CONCEPT_PREFIX) :]
    return name


def supports(head: Optional[str]) -> bool:
    """True if this kit can spell an assertion for the given predicate head."""
    return head in _HANDLERS


def render(predicate: dict[str, Any]) -> Optional[str]:
    """Render a single neutral predicate as one pytest assertion statement.

    Returns the assertion source (no trailing newline, no indentation), or
    ``None`` if the predicate head is not in this kit's table, the arity is
    wrong, or a term subtree cannot be rendered.

    Substrate-honest: an unsupported predicate is NOT silently dropped into a
    vacuously-passing assertion; the caller surfaces it as an unemitted gap.
    """
    head = head_of(predicate)
    if head is None:
        return None
    handler = _HANDLERS.get(head)
    if handler is None:
        return None
    args = _args_of(predicate)
    return handler(args)


def placeholder_type(head: Optional[str]) -> str:
    """Default placeholder "type" (informational) when a var is not a formal.

    Drives nothing at runtime in python (it is dynamically typed); kept for
    parity with the java sibling's signature-aware emit and for documentation
    in the generated source.
    """
    if head in ("option-is-some", "option-is-none", "not-null", "fallible-err"):
        return "object"
    return "int"


def placeholder_value(head: Optional[str], var_index: int) -> str:
    """A python literal placeholder for a free variable so the emitted

    assertion *passes* when run standalone under pytest.

    The catalog contract is about the SHAPE of the assertion, not concrete
    runtime values; placeholders are chosen per-predicate so the assertion is
    satisfied when every free variable is a fresh placeholder. ``var_index`` is
    the variable's position in the predicate's free-variable encounter order
    (0-based), used so ordering predicates get operands that actually satisfy
    the relation.

    Examples (two-operand predicates use index 0 / 1):

    - ``eq`` -> both ``0`` so ``assert 0 == 0`` passes.
    - ``ne`` -> ``0`` then ``1`` so ``assert 0 != 1`` passes.
    - ``lt`` -> ``0`` then ``1`` so ``assert 0 < 1`` passes.
    - ``gt`` -> ``1`` then ``0`` so ``assert 1 > 0`` passes.
    - ``le`` -> both ``0`` so ``assert 0 <= 0`` passes.
    - ``ge`` -> both ``0`` so ``assert 0 >= 0`` passes.
    - ``option-is-some`` -> ``object()`` so ``assert x is not None`` passes.
    - ``option-is-none`` -> ``None`` so ``assert x is None`` passes.
    - ``fallible-err`` -> a zero-arg callable that raises so ``x()`` throws.
    """
    if head in ("option-is-none",):
        return "None"
    if head in ("option-is-some", "not-null"):
        return "object()"
    if head == "fallible-err":
        # A zero-arg callable whose call raises, so ``with pytest.raises: x()``
        # is satisfied. Uses a generator-expression .throw trick to raise from
        # an expression-only lambda body.
        return "lambda: (_ for _ in ()).throw(ValueError('contract error'))"
    if head in ("lt",):
        return "0" if var_index == 0 else "1"
    if head in ("gt",):
        return "1" if var_index == 0 else "0"
    # eq / ne / le / ge and fallbacks.
    if head == "ne":
        return "0" if var_index == 0 else "1"
    # eq, le, ge: equal operands satisfy ==, <=, >=.
    return "0"


# --- term rendering -------------------------------------------------------


def render_term(term: Any) -> Optional[str]:
    """Render a neutral term subtree (a predicate ``args`` element) into a

    python expression string.

    Neutral term forms (catalog spelling):

    - ``{"kind":"var","name":"x"}``                  -> ``x``
    - ``{"kind":"const","value":7}``                 -> ``7``
    - ``{"kind":"const","value":"hi"}``              -> ``'hi'``
    - ``{"kind":"const","value":null}``              -> ``None``
    - ``{"kind":"const","value":true}``              -> ``True``
    - ``{"kind":"op"|"ctor","name":"+","args":[a,b]}`` -> ``(a + b)``
    - ``{"kind":"op"|"ctor","name":"foo","args":[a]}`` -> ``foo(a)``

    Substrate-honest: a term shape this renderer does not understand yields
    ``None`` so the caller refuses rather than emit a silently-wrong
    expression.
    """
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
    """Collect ``kind:"var"`` names referenced by a term in encounter order."""
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
        for a in args:
            free_vars(a, out)
    return out


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
        return _quote(value)
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
        for a in raw_args:
            r = render_term(a)
            if r is None:
                return None
            rendered_args.append(r)

    if name in _ARITHMETIC and len(rendered_args) == 2:
        return f"({rendered_args[0]} {name} {rendered_args[1]})"

    return f"{name}({', '.join(rendered_args)})"


def _quote(s: str) -> str:
    return repr(s)


def _args_of(predicate: dict[str, Any]) -> list[Any]:
    args = predicate.get("args")
    return args if isinstance(args, list) else []


# --- the inline table -----------------------------------------------------


def _binary(make: Callable[[str, str], str]) -> Callable[[list[Any]], Optional[str]]:
    def handler(args: list[Any]) -> Optional[str]:
        if len(args) != 2:
            return None
        a = render_term(args[0])
        b = render_term(args[1])
        if a is None or b is None:
            return None
        return make(a, b)

    return handler


def _unary(make: Callable[[str], str]) -> Callable[[list[Any]], Optional[str]]:
    def handler(args: list[Any]) -> Optional[str]:
        if len(args) != 1:
            return None
        x = render_term(args[0])
        if x is None:
            return None
        return make(x)

    return handler


# The whole point of the PR: this table is python framework knowledge, inline.
_HANDLERS: dict[str, Callable[[list[Any]], Optional[str]]] = {
    "eq": _binary(lambda a, b: f"assert {a} == {b}"),
    "ne": _binary(lambda a, b: f"assert {a} != {b}"),
    "neq": _binary(lambda a, b: f"assert {a} != {b}"),  # harvester internal spelling
    "lt": _binary(lambda a, b: f"assert {a} < {b}"),
    "gt": _binary(lambda a, b: f"assert {a} > {b}"),
    "le": _binary(lambda a, b: f"assert {a} <= {b}"),
    "lte": _binary(lambda a, b: f"assert {a} <= {b}"),
    "ge": _binary(lambda a, b: f"assert {a} >= {b}"),
    "gte": _binary(lambda a, b: f"assert {a} >= {b}"),
    "option-is-some": _unary(lambda x: f"assert {x} is not None"),
    "not-null": _unary(lambda x: f"assert {x} is not None"),
    "option-is-none": _unary(lambda x: f"assert {x} is None"),
    "fallible-err": _unary(lambda x: f"with pytest.raises(Exception):\n        {x}()"),
}


def supported_predicates() -> list[str]:
    """Catalog-form names of every predicate this kit can emit, deduplicated."""
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
