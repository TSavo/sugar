from __future__ import annotations

import ast

from factory_reduce import compose_block

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import ReturnValue, SymbolicValue, TermValue
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.outcome import Incomplete


def _site(source: str) -> SourceFragment:
    return SourceFragment.from_node(ast.parse(source).body[0], "vendor.py")


def test_call_receiver_attribute_augassign_has_one_owner() -> None:
    site = _site("type(self).called_wrap += 1")
    candidates = default_catalog().candidates_for(SugarRole.STATEMENT, site)

    assert [candidate.name for candidate in candidates] == [
        "SelectedAttributeAugAssignSugar"
    ]


def test_call_receiver_attribute_augassign_is_a_named_runtime_effect() -> None:
    outcome = compose_block(
        "    type(self).called_wrap += 1\n    return 1\n",
        binds={"self": SymbolicValue(make_var("self"))},
    )

    effect = next(row for row in outcome.statements if isinstance(row, Incomplete))
    assert type(effect.effect).__name__ == "AttributeAugAssignRuntimeEffect"
    assert "runtime-selected receiver" in effect.reason


def test_name_receiver_attribute_augassign_keeps_concrete_owner() -> None:
    site = _site("obj.value += 2")
    candidates = default_catalog().candidates_for(SugarRole.STATEMENT, site)

    assert [candidate.name for candidate in candidates] == ["AttributeAddAssignSugar"]

    built = build_node(
        site,
        filename="vendor.py",
        role=SugarRole.STATEMENT,
        ctx=FactoryBuildContext(filename="vendor.py", catalog=default_catalog()),
    )
    assert type(built.sugar).__name__ == "AttributeAddAssignSugar"

    block = compose_block(
        "    obj.value = 1\n" "    obj.value += 2\n" "    return obj.value\n",
        binds={"obj": SymbolicValue(make_var("obj"))},
    )
    returned = next(row for row in block.statements if isinstance(row, ReturnValue))
    assert returned.value == TermValue(3)
