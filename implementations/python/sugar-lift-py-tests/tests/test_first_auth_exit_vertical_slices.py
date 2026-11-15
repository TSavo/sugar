"""First authenticated exceptional exits: producer → ExitSet → assertion boundary.

Product metric was 0 authenticated exceptional exits across the six no-call
producer families.  Two shared breaks zeroed the complete route even when
individual floors already minted their raise (then ``RaiseValue``, since
#7821 a halt):

1. ``UnaryOp not`` refused ``CallSiteValue`` truth, so installed-source
   ``pytest.raises`` ``__exit__`` derivation collapsed to ``exit-may-halt``.
2. Expression raise entries were not promoted to Halted faces, so
   assertion boundaries saw completed bodies and minted
   ``ExpectationNotMetEffect``.

This module pins one source-visible representative per family through the
production doors only: workspace-relative ``SourceFile``,
``populate_source_derived_resource_refs``, ``With.sugar().desugar()``.

``pytest.raises`` is an imported call: a coordinate plus an edge, cited by its
import target and never derived from the installed pytest body (#7884). What
it does with the body's halt is the imported proof's to answer; the lift keeps
the body's halt on the cited manager's open exit and decides no expectation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.context_manager_resolution import (
    OpaqueCitedContextManagerRefV1,
    SourceDerivedContextManagerRefV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.no_call_body_attribution import (
    AttributionOutcome,
    BodyProbe,
    ProducerFamily,
    attribute_body_probes,
    _exceptional_exit_effects,
)
from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.with_opaque_cited_manager_sugar import (
    WithOpaqueCitedManagerSugar,
)
from sugar_lift_python_source.manager_summary_derivation import (
    populate_source_derived_resource_refs,
)
from sugar_lift_python_source.resolution_session import SourceResolutionSession
from sugar_lift_python_source.source_oracle import workspace_path_source
from sugar_source_tree.nodes import (
    Attribute,
    BinOp,
    BoolOp,
    Compare,
    Subscript,
    UnaryOp,
    With,
)
from sugar_source_tree.tree import SourceFile

# One source-visible body per family.  Runtime raises under the stated
# pytest.raises type; operands are literals so floors decide without fixtures.
_FAMILY_SLICES: tuple[tuple[ProducerFamily, str, str, type], ...] = (
    (ProducerFamily.BINOP, "1 + 'a'", "TypeError", BinOp),
    (ProducerFamily.SUBSCRIPT, "[0][1]", "IndexError", Subscript),
    (ProducerFamily.COMPARE, "1 < 'a'", "TypeError", Compare),
    (ProducerFamily.UNARYOP, "~3.5", "TypeError", UnaryOp),
    (ProducerFamily.ATTRIBUTE, "None.foo", "AttributeError", Attribute),
    (ProducerFamily.BOOLOP, "[] or 1 / 0", "ZeroDivisionError", BoolOp),
)


def _build_slice(
    tmp_path: Path, *, family: ProducerFamily, body: str, expected: str
) -> tuple[TreeConstructionContextV1, With, object]:
    """Production doors only: workspace-relative source + populate + With node."""
    source = (
        "import pytest\n"
        f"def use_{family.value.lower()}_boundary():\n"
        f"    with pytest.raises({expected}):\n"
        f"        {body}\n"
    )
    path = tmp_path / f"{family.value}_auth_exit.py"
    path.write_text(source, encoding="utf-8")
    root = tmp_path
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        workspace_path_source(str(path), root=str(root)),
        construction_context=context,
    )
    populate_source_derived_resource_refs(
        tree,
        root=root,
        path=path,
        session=SourceResolutionSession(enrolled_distributions=frozenset()),
    )
    with_node = next(node for node in tree.nodes() if isinstance(node, With))
    body_expr = with_node.body[0].value
    return context, with_node, body_expr


def _raises_named(outcome, expected: str) -> tuple:
    """The halts of ``outcome`` that raise ``expected`` by name."""
    return tuple(
        effect
        for effect in _exceptional_exit_effects(outcome)
        if getattr(effect, "exception_name", None) == expected
    )


@pytest.mark.parametrize(
    "family,body,expected,node_type",
    _FAMILY_SLICES,
    ids=[family.value for family, *_ in _FAMILY_SLICES],
)
def test_producer_emits_authenticated_exceptional_exit(
    tmp_path: Path,
    family: ProducerFamily,
    body: str,
    expected: str,
    node_type: type,
) -> None:
    """Truthful: the body expression alone publishes its RaiseEffect."""
    _context, _with_node, body_expr = _build_slice(
        tmp_path, family=family, body=body, expected=expected
    )
    assert isinstance(body_expr, node_type)

    outcome = body_expr.sugar().desugar(None)

    effects = _exceptional_exit_effects(outcome)
    assert effects, (family, type(outcome).__name__, outcome)
    assert all(effect.exception_name == expected for effect in effects)
    report = attribute_body_probes(
        (
            BodyProbe(
                body_id=f"vertical/{family.value}",
                family=family,
                evaluator=lambda: outcome,
            ),
        )
    )
    assert report.by_family[family].authenticated_exceptional_exits == 1
    assert report.bodies[0].outcome is AttributionOutcome.AUTHENTICATED_EXIT


@pytest.mark.parametrize(
    "family,body,expected,node_type",
    _FAMILY_SLICES,
    ids=[family.value for family, *_ in _FAMILY_SLICES],
)
def test_imported_pytest_raises_is_cited_by_its_target(
    tmp_path: Path,
    family: ProducerFamily,
    body: str,
    expected: str,
    node_type: type,
) -> None:
    """Shared door: the imported manager is cited by its import target, never
    derived from the installed pytest body (#7884)."""
    del node_type
    context, with_node, _body = _build_slice(
        tmp_path, family=family, body=body, expected=expected
    )
    (reference,) = tuple(context.source_derived_contract_refs.values())
    assert not isinstance(reference, SourceDerivedContextManagerRefV1), reference
    assert isinstance(reference, OpaqueCitedContextManagerRefV1), reference
    assert reference.target_name == "python:pytest.raises", reference
    assert reference.roster.resolution_kind == "call-target-off-population"
    boundary = with_node.sugar()
    assert isinstance(boundary, WithOpaqueCitedManagerSugar), type(boundary).__name__


@pytest.mark.parametrize(
    "family,body,expected,node_type",
    _FAMILY_SLICES,
    ids=[family.value for family, *_ in _FAMILY_SLICES],
)
def test_full_route_keeps_the_producer_halt(
    tmp_path: Path,
    family: ProducerFamily,
    body: str,
    expected: str,
    node_type: type,
) -> None:
    """Truthful full route: the body's producer halt leaves the cited manager.

    The manager's exit disposition is open, so the halt stays on the exit's
    falsity face; it is never consumed by a law the lift does not hold."""
    del node_type
    _context, with_node, _body = _build_slice(
        tmp_path, family=family, body=body, expected=expected
    )
    outcome = with_node.sugar().desugar()
    assert _raises_named(outcome, expected), (family, outcome)


@pytest.mark.parametrize(
    "family,body,expected",
    (
        (ProducerFamily.BINOP, "1 + 2", "TypeError"),
        (ProducerFamily.SUBSCRIPT, "[0][0]", "IndexError"),
        (ProducerFamily.COMPARE, "1 < 2", "TypeError"),
        (ProducerFamily.UNARYOP, "~3", "TypeError"),
        (ProducerFamily.ATTRIBUTE, "None.__class__", "AttributeError"),
        (ProducerFamily.BOOLOP, "[] or 0", "ZeroDivisionError"),
    ),
    ids=["BinOp", "Subscript", "Compare", "UnaryOp", "Attribute", "BoolOp"],
)
def test_lying_body_without_matching_halt_carries_none(
    tmp_path: Path,
    family: ProducerFamily,
    body: str,
    expected: str,
) -> None:
    """Lying twin: a completing body leaves no halt named ``expected``, and the
    lift decides no expectation for a manager whose law it does not hold."""
    from sugar_lift_py_tests.effect import ExpectationNotMetEffect

    _context, with_node, _body = _build_slice(
        tmp_path, family=family, body=body, expected=expected
    )
    outcome = with_node.sugar().desugar()
    assert not _raises_named(outcome, expected), (family, outcome)
    assert not any(
        isinstance(face.effect, ExpectationNotMetEffect) for face in outcome.halts()
    ), (family, outcome)


def test_callsite_not_is_not_refused_for_manager_derivation() -> None:
    """Shared fix pin: ``not CallSiteValue`` reaches truth, not SugarNotWritten."""
    from sugar_lift_py_tests.floor import CallSiteValue
    from sugar_lift_py_tests.ir import ctor
    from sugar_lift_py_tests.sugar.unary_op_sugar import UnaryOpSugar
    from sugar_lift_py_tests.sugar.sugar_base import Sugar

    class _Site:
        filename = "first_auth_exit_vertical_slices.py"
        line = 1
        col = 0
        unit = type("_Unit", (), {"source": "not call_result\n"})()

    class _Operand(Sugar):
        def desugar(self, ctx=None):
            del ctx
            return ExitSet.completed(
                CallSiteValue(
                    "source-constructor",
                    (),
                    (),
                    ctor("call:source-constructor", []),
                    None,
                )
            )

        @classmethod
        def witnesses(cls):
            return ()

    outcome = UnaryOpSugar("Not", _Operand(), _Site()).desugar(None)
    assert outcome.completed_value() is not None
