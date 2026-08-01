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
