from __future__ import annotations

from factory_reduce import fol

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import CallSiteValue, TermValue
from sugar_lift_py_tests.ir import ctor, str_const
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar.floor_terms import floor_to_term


def _ctx_for_source(source: str) -> tuple[SourceFragment, FactoryBuildContext]:
    root = SourceFragment.from_source(source, "t.py")
    resolver = {}
    for fragment in _top_level_fragments(root):
        if fragment.observed == "ClassDef":
            resolver[fragment.class_name()] = fragment.node
        if fragment.observed == "FunctionDef":
            resolver[fragment.function_name()] = fragment.node
    catalog = default_catalog()
    return root, FactoryBuildContext(
        filename="t.py",
        catalog=catalog,
        name_resolver=resolver,
    )


def _top_level(root: SourceFragment, name: str) -> SourceFragment:
    for fragment in _top_level_fragments(root):
        if fragment.observed == "ClassDef" and fragment.class_name() == name:
            return fragment
        if fragment.observed == "FunctionDef" and fragment.function_name() == name:
            return fragment
    raise AssertionError(f"missing top-level fragment {name!r}")


def _top_level_fragments(root: SourceFragment) -> list[SourceFragment]:
    fragments = root.fragments()
    if len(fragments) == 1 and fragments[0].observed == "Block":
        return fragments[0].fragments()
    return fragments


def _reduce_expr(source: str, expr: str):
    full_source = f"{source.rstrip()}\n\ndef _probe():\n    return {expr}\n"
    root, ctx = _ctx_for_source(full_source)
    function = _top_level(root, "_probe")
    statement = function.function_body()[0]
    value = statement.return_value()
    assert value is not None
    body = ctx.build_body(value, SugarRole.TERM)
    return complete_value(
        body.reduce(ctx),
        owner="mutation container dunder expression",
    )


def _object_identity(class_name: str, blame: str):
    return ctor("py.object.identity", [str_const(class_name), str_const(blame)])


def test_reversed_builtin_projects_to_dunder_method_bridge() -> None:
    source = """\
class Box:
    def __reversed__(self):
        return 1
"""

    value = _reduce_expr(source, "reversed(Box())")

    assert isinstance(value, CallSiteValue)
    assert value.target_name == "Box.__reversed__"
    assert fol(floor_to_term(value, owner="reversed dunder bridge")) == fol(
        ctor("call:Box.__reversed__", [_object_identity("Box", "t.py:6:20")])
    )


def test_reversed_dunder_can_drive_array_index_value_demand() -> None:
    source = """\
class Box:
    def __reversed__(self):
        return 1
"""

    value = _reduce_expr(source, "[10, 20, 30][reversed(Box())]")

    assert value == TermValue(20)
