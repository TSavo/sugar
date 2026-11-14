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
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.context_manager_resolution import (
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
from sugar_lift_py_tests.outcome import Completed, ExitSet
from sugar_lift_py_tests.sugar.with_effect_boundary_sugar import WithEffectBoundarySugar
from sugar_lift_python_source.manager_summary_derivation import (
    populate_source_derived_resource_refs,
)
from sugar_lift_python_source.dependency_artifact import (
    authenticate_dependency_top_level,
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
    pytest_graph = authenticate_dependency_top_level("pytest")
    if pytest_graph.artifact_kind != "distribution":
        raise AssertionError("installed pytest slice requires a distribution graph")
    session = SourceResolutionSession(
        enrolled_distributions=frozenset({pytest_graph.distribution_name})
    )
    session.dependency_graphs["pytest"] = pytest_graph
    populate_source_derived_resource_refs(tree, root=root, path=path, session=session)
    with_node = next(node for node in tree.nodes() if isinstance(node, With))
    body_expr = with_node.body[0].value
    return context, with_node, body_expr


def _without_pytest_raises_construction_halts(exits):
    """The With's body-route faces after ``AbstractRaises.__init__``'s own halts.

    pytest's ``re.compile(match)`` is an off-population call inside the
    enrolled pytest body, an unanswered ``UnknownCalleeCallV1``, so it may
    raise. Python evaluates
    ``pytest.raises(...)`` before anything is entered, so each such halt is the
    With's own face: the body never runs and ``__exit__`` never runs. pytest's
    ``except re.error`` route reaches ``fail(...)`` (``Failed``); any other
    exception propagates undetermined. Formatting that ``re.error`` into
    ``fail``'s message (``f"...{re_error}"``) runs its class's ``__format__``,
    which the lift does not know is CPython's own, so it may raise too. Every
    remaining face is reached only where that call completed.
    """
    from sugar_lift_py_tests.outcome import Halted

    construction = [
        face
        for face in exits
        if isinstance(face, Halted)
        and _negates_unanswered_call(face.guard, "re.compile")
    ]
    kinds = sorted(
        (
            type(face.effect).__name__,
            getattr(face.effect, "exception_name", None)
            or getattr(face.effect, "producer_node_owner", None),
        )
        for face in construction
    )
    assert kinds == [
        ("RaiseEffect", "Failed"),
        ("UndeterminedRaiseEffect", "BuiltinDunderCall:format"),
        ("UndeterminedRaiseEffect", "UnknownCallee:re.compile"),
    ], kinds
    (failed,) = [face for face in construction if face.effect.exception_name == "Failed"]
    assert "re.error" in repr(failed.guard)
    rest = tuple(face for face in exits if all(face is not c for c in construction))
    for face in rest:
        assert not _negates_unanswered_call(face.guard, "re.compile")
    return rest


def _negates_unanswered_call(guard, target):
    """``guard`` conjoins ``not python:unknown_callee_call.completes(target, _)``."""
    kind = getattr(guard, "kind", None)
    if kind == "not":
        (operand,) = guard.operands
        if getattr(operand, "name", None) != "python:unknown_callee_call.completes":
            return False
        (call,) = operand.args
        return getattr(call.args[0], "value", None) == target
    if kind == "and":
        return any(_negates_unanswered_call(op, target) for op in guard.operands)
    return False


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
def test_installed_pytest_raises_derives_effect_boundary(
    tmp_path: Path,
    family: ProducerFamily,
    body: str,
    expected: str,
    node_type: type,
) -> None:
    """Shared door: populate_source_derived installs WithEffectBoundarySugar."""
    del node_type
    context, with_node, _body = _build_slice(
        tmp_path, family=family, body=body, expected=expected
    )
    reference = next(iter(context.source_derived_contract_refs.values()))
    assert isinstance(reference, SourceDerivedContextManagerRefV1), reference
    boundary = with_node.sugar()
    assert isinstance(boundary, WithEffectBoundarySugar), type(boundary).__name__


@pytest.mark.parametrize(
    "family,body,expected,node_type",
    _FAMILY_SLICES,
    ids=[family.value for family, *_ in _FAMILY_SLICES],
)
def test_full_route_consumes_matching_halt(
    tmp_path: Path,
    family: ProducerFamily,
    body: str,
    expected: str,
    node_type: type,
) -> None:
    """Truthful full route: producer halt is consumed; boundary completes."""
    del node_type
    _context, with_node, _body = _build_slice(
        tmp_path, family=family, body=body, expected=expected
    )
    outcome = with_node.sugar().desugar()
    exits = _without_pytest_raises_construction_halts(outcome.exits)
    assert len(exits) == 1, (family, exits)
    assert isinstance(exits[0], Completed), (
        family,
        type(exits[0]).__name__,
        getattr(exits[0], "effect", None),
    )


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
def test_lying_body_without_matching_halt_fails_expectation(
    tmp_path: Path,
    family: ProducerFamily,
    body: str,
    expected: str,
) -> None:
    """Lying twin: completed body under expects-raise is ExpectationNotMet."""
    from sugar_lift_py_tests.effect import ExpectationNotMetEffect
    from sugar_lift_py_tests.outcome import Halted

    _context, with_node, _body = _build_slice(
        tmp_path, family=family, body=body, expected=expected
    )
    outcome = with_node.sugar().desugar()
    exits = _without_pytest_raises_construction_halts(outcome.exits)
    assert len(exits) == 1
    face = exits[0]
    assert isinstance(face, Halted)
    assert isinstance(face.effect, ExpectationNotMetEffect)


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
