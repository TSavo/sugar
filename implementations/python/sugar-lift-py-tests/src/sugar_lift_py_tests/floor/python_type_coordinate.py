"""Authenticated ``python:type`` coordinate door for isinstance dispatch.

LAW OF ONE: the type operand's identity is the coordinate the tree carried
(``python:type("…")``), never the display ``type_name`` string. Under builtin
shadowing the same spelling can name a foreign type; deciding True/False from
that string is a second mechanism inventing meaning outside the tree.

Throwing when the coordinate is unreachable is honorable: the producer has not
written authentication yet.
"""

from __future__ import annotations


def authenticated_python_type_spelling(type_term, *, owner: str, site) -> str:
    """Return the builtins type spelling from an authenticated ``python:type`` term.

    Display ``type_name`` is never consulted. Wrong-shape or missing coordinate
    raises ``SugarNotWritten``.
    """
    from sugar_lift_py_tests.ir import _ConstStr, _Ctor
    from sugar_source_tree.panic import SugarNotWritten

    if (
        type(type_term) is not _Ctor
        or type_term.name != "python:type"
        or len(type_term.args) != 1
        or type(type_term.args[0]) is not _ConstStr
    ):
        raise SugarNotWritten(
            blame=str(site),
            owner=owner,
            observed=f"type_term={type(type_term).__name__}",
            requested='authenticated python:type("…") coordinate',
            fix=(
                "thread the type operand's coordinate; never decide "
                "isinstance by type_name spelling"
            ),
        )
    return type_term.args[0].value


# The real method resolution order (``type.__mro__``, by name) of every
# builtin class a floor knows a value of exactly, or names as classinfo.  The
# ONE table: every floor that knows its value's builtin type answers
# isinstance from its row here (:func:`builtin_order_isinstance`), never from
# a list of its own.  Each class in it has metaclass ``type`` exactly.
_OWN_BASE_IS_OBJECT = (
    "int",
    "float",
    "complex",
    "str",
    "bytes",
    "bytearray",
    "memoryview",
    "list",
    "tuple",
    "dict",
    "set",
    "frozenset",
    "range",
    "slice",
    "NoneType",
    "ellipsis",
    "property",
    "staticmethod",
    "classmethod",
    "super",
    "enumerate",
    "zip",
    "map",
    "filter",
    "reversed",
)

BUILTIN_TYPE_ORDER: dict[str, tuple[str, ...]] = {
    "object": ("object",),
    "type": ("type", "object"),
    "bool": ("bool", "int", "object"),
    **{own: (own, "object") for own in _OWN_BASE_IS_OBJECT},
}


def _builtin_class_of_metaclass_type(authenticated: str) -> bool:
    """Whether ``authenticated`` names a builtin class whose metaclass is
    ``type`` exactly: a row of :data:`BUILTIN_TYPE_ORDER`, or a builtin
    exception class.  Its ``__instancecheck__`` is ``type``'s own."""
    from sugar_lift_py_tests.temporal.builtin_name_bindings import (
        BUILTIN_EXCEPTION_NAMES,
    )

    return (
        authenticated in BUILTIN_TYPE_ORDER
        or authenticated in BUILTIN_EXCEPTION_NAMES
    )


def builtin_order_isinstance(
    value_type: str, type_term, site, *, owner: str, exact: bool = True
):
    """``isinstance(<a value of the builtin class value_type>, <type_term>)``
    from ``value_type``'s real order (:data:`BUILTIN_TYPE_ORDER`), or
    ``None`` where that order does not decide it.

    ``PyObject_IsInstance`` (Objects/abstract.c) over a classinfo whose
    metaclass is ``type`` exactly is ``object_isinstance``: True at once
    where ``type(value)`` is a subclass, so every class of the order --
    ``object`` and the real bases included (a ``bool`` is an ``int``) --
    is ``True`` and reads nothing that may raise.  Where it is no subclass,
    ``value.__class__`` is read; for a value whose type is ``value_type``
    exactly (``exact``) that is ``object``'s own ``__class__``, which
    answers ``type(value)`` and cannot raise, so a builtin class of
    metaclass ``type`` not in the order is ``False``.

    ``exact=False`` is a value whose type is some subclass of
    ``value_type`` the lift does not name (``type(y)``'s result: a class
    whose metaclass is undecided): only the order's classes are decided
    (``True``); a ``__class__`` its metaclass defines may raise, so nothing
    is ``False``.

    Anything else -- an ABC whose metaclass runs its own
    ``__instancecheck__``, a builtin name that is no class -- is ``None``:
    the caller's undecided type test, its halt kept
    (``floor_value.undecided_type_test``, #7757)."""
    from sugar_lift_py_tests.outcome import ExitSet
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
        FalseBoolLiteralSugar,
    )
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
        TrueBoolLiteralSugar,
    )

    authenticated = authenticated_python_type_spelling(
        type_term, owner=owner, site=site
    )
    if authenticated in BUILTIN_TYPE_ORDER[value_type]:
        return ExitSet.completed(TrueBoolLiteralSugar(site=site))
    if exact and _builtin_class_of_metaclass_type(authenticated):
        return ExitSet.completed(FalseBoolLiteralSugar(site=site))
    return None
