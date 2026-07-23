"""One authenticated exception matcher shared by Try and With."""

from __future__ import annotations


def matches_raise_effect(effect, expected) -> bool:
    """Match by constructed exception coordinates and authenticated ancestry.

    Exact identity is sufficient. When the raised type carries source-derived
    MRO testimony, a handler coordinate may match an authenticated ancestor.
    Missing identity is a construction gap; spelling never participates.
    """
    from sugar_source_tree.panic import SugarNotWritten

    identity_reader = getattr(expected, "exception_type_identity", None)
    expected_identity = identity_reader() if identity_reader is not None else None
    raised_identity = getattr(effect, "exception_type_coordinate", None)
    if expected_identity is None or raised_identity is None:
        raise SugarNotWritten(
            owner="matches_raise_effect",
            observed="handler or raised exception lacks authenticated identity",
            requested="authenticated exception-type identity on both operands",
            fix="resolve both exception classes through their lexical coordinates",
        )
    if expected_identity == raised_identity:
        return True
    raised_mro = getattr(effect, "exception_type_mro", None)
    return raised_mro is not None and expected_identity in raised_mro
