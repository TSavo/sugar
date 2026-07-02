from __future__ import annotations

from pathlib import Path

from .dunder_frontier_report import DunderFrontierReport
from .dunder_slot import DunderSlot

_TRACKED_SLOTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("lifecycle", ("__init__",)),
    (
        "call_container",
        ("__call__", "__getitem__", "__contains__", "__iter__", "__next__"),
    ),
    (
        "mutation_container",
        ("__setitem__", "__delitem__", "__reversed__", "__missing__"),
    ),
    ("truth_hash", ("__bool__", "__len__", "__hash__")),
    ("comparison", ("__eq__", "__ne__", "__lt__", "__le__", "__gt__", "__ge__")),
    (
        "numeric_binary",
        (
            "__add__",
            "__sub__",
            "__mul__",
            "__matmul__",
            "__truediv__",
            "__floordiv__",
            "__mod__",
            "__divmod__",
            "__pow__",
            "__lshift__",
            "__rshift__",
            "__and__",
            "__xor__",
            "__or__",
        ),
    ),
    (
        "reflected_binary",
        (
            "__radd__",
            "__rsub__",
            "__rmul__",
            "__rmatmul__",
            "__rtruediv__",
            "__rfloordiv__",
            "__rmod__",
            "__rdivmod__",
            "__rpow__",
            "__rlshift__",
            "__rrshift__",
            "__rand__",
            "__rxor__",
            "__ror__",
        ),
    ),
    (
        "inplace_binary",
        (
            "__iadd__",
            "__isub__",
            "__imul__",
            "__imatmul__",
            "__itruediv__",
            "__ifloordiv__",
            "__imod__",
            "__ipow__",
            "__ilshift__",
            "__irshift__",
            "__iand__",
            "__ixor__",
            "__ior__",
        ),
    ),
    (
        "unary_numeric",
        (
            "__pos__",
            "__neg__",
            "__abs__",
            "__invert__",
            "__round__",
            "__floor__",
            "__ceil__",
            "__trunc__",
        ),
    ),
    ("numeric_conversion", ("__int__", "__float__", "__complex__", "__index__")),
    ("display_conversion", ("__str__", "__repr__", "__bytes__", "__format__")),
    (
        "attribute_descriptor",
        (
            "__getattr__",
            "__getattribute__",
            "__setattr__",
            "__delattr__",
            "__dir__",
            "__get__",
            "__set__",
            "__delete__",
            "__set_name__",
        ),
    ),
    (
        "context_async",
        (
            "__enter__",
            "__exit__",
            "__aenter__",
            "__aexit__",
            "__await__",
            "__aiter__",
            "__anext__",
        ),
    ),
)


def collect_dunder_frontier(root: Path) -> DunderFrontierReport:
    del root
    owners = _owned_dunder_slots()
    slots: list[DunderSlot] = []
    for axis, names in _TRACKED_SLOTS:
        for name in names:
            owner = owners.get(name, "")
            slots.append(
                DunderSlot(
                    axis=axis,
                    name=name,
                    status="owned" if owner else "missing",
                    owner=owner,
                    fix=_fix(axis, name) if not owner else "",
                )
            )
    return DunderFrontierReport(slots=slots)


def _owned_dunder_slots() -> dict[str, str]:
    from sugar_lift_py_tests.floor import object_value
    from sugar_lift_py_tests.sugar import builtin_call_sugar
    from sugar_lift_py_tests.sugar.object_rich_comparison_term_sugar import (
        _RICH_COMPARISON_DUNDERS,
    )

    owners = {
        "__init__": "ConstructorStrategy",
        "__call__": "CallSugar.ObjectCallStrategy",
        "__getitem__": "SubscriptOperation",
        "__contains__": "ObjectValue.contains_with",
        "__iter__": "SequenceProjectionOperation",
        "__next__": "NextOperation",
        "__bool__": "object_truthiness",
        "__getattr__": "AttributeLookupOperation",
        "__getattribute__": "AttributeLookupOperation.__getattribute__",
        "__setattr__": "AttributeMutationOperation",
        "__delattr__": "AttributeDeleteOperation",
        "__get__": "DescriptorOperation.__get__",
        "__set__": "DescriptorOperation.__set__",
        "__delete__": "DescriptorOperation.__delete__",
        "__set_name__": "ConstructorStrategy.__set_name__ floor",
        "__enter__": "ContextManagerOperation",
        "__exit__": "ContextManagerOperation",
        "__str__": "StrCoercionOperation",
        "__format__": "FormatBuiltinSugar",
    }
    for name in object_value._BINARY_DUNDER_METHODS.values():
        owners[name] = "ObjectValue._BINARY_DUNDER_METHODS"
    for name in object_value._BITWISE_DUNDER_METHODS.values():
        owners[name] = "ObjectValue._BITWISE_DUNDER_METHODS"
    for name in object_value._REFLECTED_BINARY_DUNDER_METHODS.values():
        owners[name] = "ObjectValue._REFLECTED_BINARY_DUNDER_METHODS"
    for name in object_value._INPLACE_BINARY_DUNDER_METHODS.values():
        owners[name] = "ObjectValue._INPLACE_BINARY_DUNDER_METHODS"
    for name in object_value._UNARY_DUNDER_METHODS.values():
        owners[name] = "ObjectValue._UNARY_DUNDER_METHODS"
    for name in builtin_call_sugar._BUILTIN_DUNDER_METHODS.values():
        owners[name] = "BuiltinCallSugar._BUILTIN_DUNDER_METHODS"
    for name in _RICH_COMPARISON_DUNDERS.values():
        owners[name] = "ObjectRichComparisonTermSugar"
    return owners


def _fix(axis: str, name: str) -> str:
    return (
        f"write {name} sugar/floor dispatch for the `{axis}` data-model slot; "
        "the kit must lower by ownership or loudly effect/refuse"
    )
