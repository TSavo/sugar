from __future__ import annotations

import ast

from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.sugar.ann_assign_sugar import AnnAssignSugar
from sugar_lift_py_tests.sugar.annotation_union_sugar import AnnotationUnionSugar
from sugar_lift_py_tests.sugar.assign_sugar import AssignSugar
from sugar_lift_py_tests.sugar.async_with_sugar import AsyncWithSugar
from sugar_lift_py_tests.sugar.attribute_assign_sugar import AttributeAssignSugar
from sugar_lift_py_tests.sugar.bool_op_sugar import BoolOpSugar
from sugar_lift_py_tests.sugar.call_sugar import CallSugar
from sugar_lift_py_tests.sugar.constructor_call_sugar import ConstructorCallSugar
from sugar_lift_py_tests.sugar.for_sugar import ForSugar
from sugar_lift_py_tests.sugar.joined_str_sugar import JoinedStrSugar
from sugar_lift_py_tests.sugar.named_expr_sugar import NamedExprSugar
from sugar_lift_py_tests.sugar.nested_attribute_assign_sugar import (
    NestedAttributeAssignSugar,
)
from sugar_lift_py_tests.sugar.nested_tuple_for_sugar import NestedTupleForSugar
from sugar_lift_py_tests.sugar.test_function_def_sugar import TestFunctionDefSugar
from sugar_lift_py_tests.sugar.try_sugar import TrySugar
from sugar_lift_py_tests.sugar.tuple_for_sugar import TupleForSugar


def _statement(source: str) -> SourceFragment:
    return SourceFragment.from_node(ast.parse(source).body[0], "owner.py")


def _term(source: str) -> SourceFragment:
    return SourceFragment.from_node(ast.parse(source, mode="eval").body, "owner.py")


def test_registered_sugars_own_every_promoted_semantic_family() -> None:
    call = _term("pkg.fn(1)")
    assign = _statement("item = 1")
    attribute = _statement("self.item = 1")
    nested_attribute = _statement("self.state.item = 1")
    annassign = _statement("item: int = 1")
    loop = _statement("for item in items:\n    pass")
    tuple_loop = _statement("for (left, right) in items:\n    pass")
    nested_loop = _statement("for (left, (middle, right)) in items:\n    pass")
    with_site = _statement("async with lock as token:\n    pass")
    handler = _statement(
        "try:\n    pass\nexcept (ValueError, TypeError):\n    pass"
    ).try_handlers()[0]
    boolop = _term("left and right")
    joined = _term("f'fixed'")
    test_function = _statement(
        "@pytest.mark.parametrize('value', [1, 2])\n"
        "def test_value(value):\n"
        "    assert value\n"
    )

    assert CallSugar.qualified_target_name(call) == "pkg.fn"
    assert AssignSugar.recognize_target_name(assign) == "item"
    assert AttributeAssignSugar.recognize_target(attribute) == ("self", "item")
    assert NestedAttributeAssignSugar.recognize_target_path(nested_attribute) == (
        "self",
        "state",
        "item",
    )
    assert AnnAssignSugar.recognize_target_id(annassign) == "item"
    assert ForSugar.recognize_target_name(loop) == "item"
    assert TupleForSugar.recognize_target_names(tuple_loop) == ("left", "right")
    assert NestedTupleForSugar.recognize_target_paths(nested_loop) is not None
    assert AsyncWithSugar.recognize_optional_name(with_site) == "token"
    assert TrySugar.recognize_handler_type_names(handler) == (
        "ValueError",
        "TypeError",
    )
    assert BoolOpSugar.recognize_operator(boolop) == "and"
    assert JoinedStrSugar.recognize_static_text(joined) == "fixed"
    assert TestFunctionDefSugar.recognize_parameter_rows(test_function) == (
        (("value",), ((1,), (2,))),
    )
    assert (
        ConstructorCallSugar.recognize_initializer_call(
            _statement("super().__init__()"), receiver_name="self"
        ).kind
        == "super"
    )
    assert NamedExprSugar.recognize_target_name(_term("(seen := value)")) == "seen"
    assert AnnotationUnionSugar.witnesses()


def test_promoted_owner_families_all_publish_discrimination_witnesses() -> None:
    owners = (
        AnnotationUnionSugar,
        CallSugar,
        ConstructorCallSugar,
        NamedExprSugar,
        AssignSugar,
        AttributeAssignSugar,
        NestedAttributeAssignSugar,
        AnnAssignSugar,
        ForSugar,
        TupleForSugar,
        NestedTupleForSugar,
        AsyncWithSugar,
        TrySugar,
        BoolOpSugar,
        JoinedStrSugar,
        TestFunctionDefSugar,
    )

    witnesses = {owner.__name__: owner.witnesses() for owner in owners}
    assert set(witnesses) == {owner.__name__ for owner in owners}
    assert all(witnesses.values())
