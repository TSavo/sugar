"""Public Python compiler orchestration.

Backend-native syntax construction belongs to ``compiler_adapter``.  This
module is the stable public door and never owns or exposes a backend AST.
"""

from __future__ import annotations

from typing import Any

from .compiler_adapter import emit_body_term, emit_ir_document

Json = dict[str, Any]


def compile_ir_document(ir: list[Json]) -> str:
    """Compile a typed IR document through the Python backend adapter."""
    return emit_ir_document(ir)


def compile_body_term(
    term: Json, *, fn_name: str = "f", formals: list[str] | None = None
) -> str:
    """Compile one typed function body through the Python backend adapter."""
    return emit_body_term(term, fn_name=fn_name, formals=formals)


__all__ = ["compile_body_term", "compile_ir_document"]
