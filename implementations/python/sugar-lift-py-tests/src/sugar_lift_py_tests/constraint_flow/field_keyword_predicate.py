from __future__ import annotations

from typing import Any

from ..factory.source_fragment import SourceFragment
from .callee_name import callee_name
from .ge_field_fact import ge_field_fact


def field_keyword_predicate(
    fragment: SourceFragment,
    *,
    owner: str,
    resolved_names: dict[str, str],
) -> tuple[dict[str, Any] | None, list[str]]:
    call = fragment.annassign_value()
    if call is None or call.observed != "Call":
        return None, []
    func_frag = call.call_func()
    callee = callee_name(func_frag)
    if resolved_names.get(callee, callee) != "pydantic.Field":
        return None, []
    for kw_frag in call.call_keywords():
        if kw_frag.keyword_arg_name() != "ge":
            continue
        val_frag = kw_frag.keyword_value()
        if val_frag.observed != "PrimitiveLiteral":
            continue
        val = val_frag.literal_value()
        if not isinstance(val, int):
            continue
        field = fragment.annassign_target_id()
        return (
            ge_field_fact(owner, field, int(val)),
            ["python.term.int-literal", "python.constraint.field-keyword"],
        )
    return None, []
