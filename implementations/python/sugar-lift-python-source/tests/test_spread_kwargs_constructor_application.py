"""A typed ``**kwargs`` constructor spread binds ``match`` as an actual.

What the bound actual means to the manager is read from the exit's own
formula. ``effect.message`` is an attribute of the raised value, decided by
that value's class, and a class spelled like pytest's ``RaisesExc`` is not
that class (#7757): neither is an effect boundary.
"""

from __future__ import annotations

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.manager_summary_derivation import (
    populate_source_derived_resource_refs,
)
from sugar_lift_python_source.resolution_session import SourceResolutionSession
from sugar_source_tree.nodes import Call, With
from sugar_source_tree.tree import SourceFile


_LOCAL_BOUNDARY = """class Boundary:
    def __init__(self, expected, *, match=None):
        self.expected = expected
        self.match = match
    def __enter__(self):
        return self
    def __exit__(self, effect_type, effect, traceback):
        if effect_type is None:
            raise RuntimeError()
        return (effect_type is self.expected) and (effect.message == self.match)

with Boundary(ValueError, **{"match": "boom"}):
    raise ValueError("boom")
"""

_RAISES_SHAPED = """class RaisesExc:
    def __init__(self, expected_exception=None, /, *, match=None, check=None):
        self.expected_exceptions = expected_exception
        self.match = match
        self.check = check
    def matches(self, exc_val):
        return True
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            raise RuntimeError()
        return (exc_type is self.expected_exceptions) and (
            exc_val.message == self.match
        )

with RaisesExc(ValueError, **{"match": "boom"}):
    raise ValueError("boom")
"""


def _tree_for(tmp_path, source: str):
    path = tmp_path / "local_cm.py"
    path.write_text(source, encoding="utf-8")
    from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1

    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (source, str(path), blake3_512_of(source.encode("utf-8"))),
        construction_context=context,
    )
    return tree, context, path


def _populate_local(tmp_path, source: str):
    tree, context, path = _tree_for(tmp_path, source)
    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=path,
        distribution_index={},
        session=SourceResolutionSession(enrolled_distributions=frozenset()),
    )
    return tree, context


def test_local_spread_kwargs_collects_match_actual(tmp_path):
    """Spread desugar binds ``match='boom'`` onto the constructor application."""
    from sugar_lift_py_tests.context.reduce_context import ReduceContext
    from sugar_lift_py_tests.floor import StringValue
    from sugar_lift_py_tests.sugar.spread_sugar import SpreadCallSugar
    from sugar_lift_py_tests.temporal import builtin_name_temporal
    from sugar_lift_python_source.manager_summary_derivation import (
        _constructor_application_from_spread,
    )

    tree, _context, _path = _tree_for(tmp_path, _LOCAL_BOUNDARY)
    call = next(node for node in tree.nodes() if isinstance(node, With)).items[0].context_expr
    assert isinstance(call, Call)
    sugar = call.sugar()
    assert isinstance(sugar, SpreadCallSugar)
    outcome = _constructor_application_from_spread(
        sugar, ReduceContext(temporal=builtin_name_temporal())
    )
    application = outcome.completed_value()
    assert application.keyword_names == ("match",)
    assert any(
        isinstance(argument, StringValue) and argument.value == "boom"
        for argument in application.arguments
    )


def _no_effect_boundary(context):
    from sugar_lift_py_tests.context_manager_contract import EffectBoundarySemanticsV1
    from sugar_lift_py_tests.context_manager_resolution import (
        FactoredSourceDerivedContextManagerRefV1,
    )

    for reference in context.source_derived_contract_refs.values():
        assert not isinstance(reference, FactoredSourceDerivedContextManagerRefV1), (
            reference
        )
        assert not isinstance(
            getattr(reference, "semantics", None), EffectBoundarySemanticsV1
        ), reference


def test_local_message_attribute_is_not_a_message_pattern(tmp_path):
    """``effect.message == self.match`` seals no EffectBoundary by its spelling."""
    _tree, context = _populate_local(tmp_path, _LOCAL_BOUNDARY)
    _no_effect_boundary(context)


def test_raises_spelled_user_class_is_not_raises_exc(tmp_path):
    """Fields ``match``/``expected_exceptions`` and a ``matches`` method on a
    user class are not pytest's ``RaisesExc``: no EffectBoundary is sealed."""
    _tree, context = _populate_local(tmp_path, _RAISES_SHAPED)
    _no_effect_boundary(context)
