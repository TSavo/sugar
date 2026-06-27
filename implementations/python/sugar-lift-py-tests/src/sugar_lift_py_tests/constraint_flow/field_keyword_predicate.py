from __future__ import annotations

import ast
from typing import Any

from .callee_name import callee_name
from .ge_field_fact import ge_field_fact


def field_keyword_predicate(
    node: ast.AnnAssign,
    *,
    owner: str,
    resolved_names: dict[str, str],
) -> tuple[dict[str, Any] | None, list[str]]:
    call = node.value
    if not isinstance(call, ast.Call):
        return None, []
    callee = callee_name(call.func)
    if resolved_names.get(callee, callee) != "pydantic.Field":
        return None, []
    for keyword in call.keywords:
        if (
            keyword.arg == "ge"
            and isinstance(keyword.value, ast.Constant)
            and isinstance(keyword.value.value, int)
        ):
            field = node.target.id
            return (
                ge_field_fact(owner, field, int(keyword.value.value)),
                ["python.term.int-literal", "python.constraint.field-keyword"],
            )
    return None, []
