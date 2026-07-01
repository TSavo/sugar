from __future__ import annotations

import ast

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import SliceValue, TermValue
from sugar_lift_py_tests.outcome import complete_value


def test_slice_sugar_reduces_bounds_to_slice_value():
    subscript = ast.parse("values[1:3:2]", mode="eval").body
    site = SourceFragment.from_node(subscript, "t.py").subscript_index()
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())

    value = complete_value(
        ctx.build_body(site, SugarRole.TERM).reduce(ctx), owner="test"
    )

    assert value == SliceValue(TermValue(1), TermValue(3), TermValue(2))


def test_slice_sugar_preserves_missing_bounds():
    subscript = ast.parse("values[:]", mode="eval").body
    site = SourceFragment.from_node(subscript, "t.py").subscript_index()
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())

    value = complete_value(
        ctx.build_body(site, SugarRole.TERM).reduce(ctx), owner="test"
    )

    assert value == SliceValue(None, None, None)
