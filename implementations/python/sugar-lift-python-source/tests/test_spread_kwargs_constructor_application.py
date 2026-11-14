"""A typed ``**kwargs`` constructor spread cites match as a formal."""

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


def test_local_spread_kwargs_cites_match_formal(tmp_path):
    """Same-module ``with Boundary(..., **{'match': 'boom'})`` cites formal 1."""
    from sugar_lift_py_tests.context_manager_contract import (
        EffectBoundarySemanticsV1,
        ExpectsModeV1,
        OptionalFormalArgumentProjectionV1,
    )
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceDerivedContextManagerRefV1,
    )

    _tree, context = _populate_local(tmp_path, _LOCAL_BOUNDARY)
    assert context.source_derived_contract_refs
    reference = next(iter(context.source_derived_contract_refs.values()))
    assert isinstance(reference, SourceDerivedContextManagerRefV1), reference
    assert isinstance(reference.semantics, EffectBoundarySemanticsV1), reference.semantics
    assert isinstance(reference.semantics.mode, ExpectsModeV1)
    assert reference.semantics.message_pattern_operand == OptionalFormalArgumentProjectionV1(
        1
    )


def test_raises_shaped_spread_kwargs_cites_match_formal(tmp_path):
    """Keyword-only ``match`` plus unused ``check`` default still cites match."""
    from sugar_lift_py_tests.context_manager_contract import (
        EffectBoundarySemanticsV1,
        ExpectsModeV1,
        OptionalFormalArgumentProjectionV1,
    )
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceDerivedContextManagerRefV1,
    )

    _tree, context = _populate_local(tmp_path, _RAISES_SHAPED)
    assert context.source_derived_contract_refs
    reference = next(iter(context.source_derived_contract_refs.values()))
    assert isinstance(reference, SourceDerivedContextManagerRefV1), reference
    assert isinstance(reference.semantics, EffectBoundarySemanticsV1), reference.semantics
    assert isinstance(reference.semantics.mode, ExpectsModeV1)
    assert reference.semantics.message_pattern_operand == OptionalFormalArgumentProjectionV1(
        1
    )
