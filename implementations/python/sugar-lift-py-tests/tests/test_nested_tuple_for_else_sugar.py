from __future__ import annotations

import ast

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment


def _site(source: str) -> SourceFragment:
    return SourceFragment.from_node(
        ast.parse(source).body[0],
        "vendor.py",
        source=source,
    )


def _build(source: str):
    ctx = FactoryBuildContext(filename="vendor.py", catalog=default_catalog())
    return build_node(
        _site(source),
        filename="vendor.py",
        role=SugarRole.STATEMENT,
        ctx=ctx,
    )


def test_nested_tuple_for_else_has_one_factory_owner() -> None:
    source = (
        "for index, (left, right) in rows:\n"
        "    if left:\n"
        "        break\n"
        "else:\n"
        "    return 0\n"
    )

    candidates = default_catalog().candidates_for(
        SugarRole.STATEMENT,
        _site(source),
    )

    assert [candidate.name for candidate in candidates] == ["ForElseSugar"]
    assert _build(source).sugar.targets == (
        ((0,), "index"),
        ((1, 0), "left"),
        ((1, 1), "right"),
    )


@pytest.mark.parametrize(
    "source",
    (
        ("for head, *rest in rows:\n" "    break\n" "else:\n" "    return 0\n"),
        ("for holder.value in rows:\n" "    break\n" "else:\n" "    return 0\n"),
    ),
)
def test_unrecognized_for_else_targets_stay_loud(source: str) -> None:
    with pytest.raises(FactoryPanic, match="observed=For requested=statement"):
        _build(source)
