from __future__ import annotations

from sugar_lift_py_tests.factory.source_fragment import SourceFragment


def callee_name(fragment: SourceFragment) -> str:
    if fragment.observed == "Name":
        return fragment.name_id()
    if fragment.observed == "Attribute":
        prefix = callee_name(fragment.attr_receiver())
        return f"{prefix}.{fragment.attr_name()}" if prefix else fragment.attr_name()
    return ""
