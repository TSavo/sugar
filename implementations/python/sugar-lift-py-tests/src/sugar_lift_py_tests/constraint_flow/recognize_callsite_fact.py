from __future__ import annotations

from typing import Any

from ..factory.source_fragment import SourceFragment
from .callsite_constraint_fact import CallsiteConstraintFact
from .ge_field_fact import ge_field_fact


def recognize_callsite_fact(
    fragment,  # SourceFragment or raw node (legacy callers); wrapped automatically
    *,
    source_memento: dict[str, Any],
) -> CallsiteConstraintFact | None:
    if not isinstance(fragment, SourceFragment):
        fragment = SourceFragment.from_node(fragment, "<unknown>")
    if fragment.observed != "Assert":
        return None
    compare_frag = fragment.assert_test()
    ops = compare_frag.compare_ops()
    comparators = compare_frag.compare_comparators()
    if not (
        compare_frag.observed == "Compare"
        and len(ops) == 1
        and ops[0] == "GtE"
        and len(comparators) == 1
    ):
        return None

    left_frag = compare_frag.compare_left()
    right_frag = comparators[0]
    if not (
        left_frag.observed == "Attribute"
        and left_frag.attr_receiver().observed == "Call"
        and left_frag.attr_receiver().call_func().observed == "Name"
        and right_frag.observed == "PrimitiveLiteral"
        and isinstance(right_frag.literal_value(), int)
    ):
        return None

    call_frag = left_frag.attr_receiver()
    owner = call_frag.call_func().name_id()
    field = left_frag.attr_name()
    return CallsiteConstraintFact(
        sugar_name="python.vendor-test.callsite-assert",
        callsite=call_frag.unparse(),
        subject=f"{owner}.{field}",
        fact=ge_field_fact(owner, field, int(right_frag.literal_value())),
        source_memento=dict(source_memento),
        target_symbol=owner,
    )
