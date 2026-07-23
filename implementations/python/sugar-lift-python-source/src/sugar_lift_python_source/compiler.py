"""IR-to-Python compiler boundary.

The public compiler deals only in IR dictionaries and source text.  Backend
AST construction is contained in ``python_ast_adapter``; no backend-native
node crosses this module's API.
"""

from __future__ import annotations

from typing import Any

Json = dict[str, Any]


def compile_ir_document(ir: list[Json]) -> str:
    from .python_ast_adapter import compile_ir_document as compile_with_python_ast

    return compile_with_python_ast(ir)


def compile_body_term(
    term: Json, *, fn_name: str = "f", formals: list[str] | None = None
) -> str:
    from .python_ast_adapter import compile_body_term as compile_with_python_ast

    return compile_with_python_ast(term, fn_name=fn_name, formals=formals)


__all__ = ["compile_body_term", "compile_ir_document"]
