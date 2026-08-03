"""L3b: nested Name-only unpack targets construct (non-display RHS).

``(a, b), (c, d) = formal`` used to hit Assign.sugar SNW. Flat dynamic unpack
and nested display unpack already constructed — wire the missing nested
non-display arm only.
"""

from __future__ import annotations

from sugar_lift_python_source.canonical import blake3_512_of, cid_of_json
from sugar_lift_py_tests.sugar.dynamic_unpack_assign_sugar import (
    DynamicUnpackAssignSugar,
)
from sugar_lift_py_tests.sugar.nested_dynamic_unpack_assign_sugar import (
    NestedDynamicUnpackAssignSugar,
)
from sugar_source_tree.nodes import (
    Assign,
    RuntimeBindingEntryFactoryV1,
    SubstitutionTraceBuilderV1,
    _BINDING_ENTRY_FACTORY,
    _SCOPE_OWNER_CID,
    _SUBSTITUTION_TRACE_BUILDER,
)
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.tree import SourceFile


def _fn_sugar(src: str):
    sf = SourceFile(
        (src, "l3b_assign.py", blake3_512_of(src.encode())),
        reporter=CollectingReporter(),
    )
    fn = next(sf.functions())
    cid = cid_of_json(
        {
            "kind": "binding-scope-owner",
            "schemaVersion": "1",
            "source": fn.fragment.seal().to_dict(),
        }
    )
    scope = {
        _SCOPE_OWNER_CID: cid,
        _SUBSTITUTION_TRACE_BUILDER: SubstitutionTraceBuilderV1(cid),
        _BINDING_ENTRY_FACTORY: RuntimeBindingEntryFactoryV1(cid),
    }
    return fn.substitute(scope).sugar()


def _first_assign_sugar(src: str):
    sf = SourceFile(
        (src, "l3b_assign.py", blake3_512_of(src.encode())),
        reporter=CollectingReporter(),
    )
    fn = next(sf.functions())
    cid = cid_of_json(
        {
            "kind": "binding-scope-owner",
            "schemaVersion": "1",
            "source": fn.fragment.seal().to_dict(),
        }
    )
    scope = {
        _SCOPE_OWNER_CID: cid,
        _SUBSTITUTION_TRACE_BUILDER: SubstitutionTraceBuilderV1(cid),
        _BINDING_ENTRY_FACTORY: RuntimeBindingEntryFactoryV1(cid),
    }
    body = fn.substitute(scope)
    assign = next(n for n in body.walk() if isinstance(n, Assign))
    return assign.sugar()


def test_nested_name_only_formal_unpack_constructs_nested_dynamic_sugar():
    sugar = _first_assign_sugar("def A(p):\n    (a, b), (c, d) = p\n    return a\n")
    assert isinstance(sugar, NestedDynamicUnpackAssignSugar)
    assert sugar.pattern == (("a", "b"), ("c", "d"))


def test_nested_name_only_formal_function_sugar_constructs():
    sugar = _fn_sugar("def A(p):\n    (a, b), (c, d) = p\n    return a\n")
    assert sugar is not None


def test_flat_dynamic_unpack_still_uses_flat_sugar():
    sugar = _first_assign_sugar("def A(p):\n    a, b = p\n    return a\n")
    assert isinstance(sugar, DynamicUnpackAssignSugar)


def test_nested_display_unpack_still_constructs():
    sugar = _fn_sugar("def A():\n    (a, b), (c, d) = (1, 2), (3, 4)\n    return a\n")
    assert sugar is not None


def test_attr_and_subscript_store_targets_still_construct():
    assert _fn_sugar("def A(o, z):\n    o.x = z\n    return o\n") is not None
    assert _fn_sugar("def A(o, z):\n    o[0] = z\n    return o\n") is not None
    assert _fn_sugar("def A(o, p):\n    a, o.x = p\n    return a\n") is not None
