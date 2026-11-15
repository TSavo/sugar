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
production doors only: workspace-relative ``SourceFile`` under the step-3
table its ``with`` enrolls, ``With.sugar().desugar()``.

``pytest.raises`` is an imported call: a coordinate plus an edge, never
derived from the installed pytest body (#7884). What it does with the body's
halt is the imported proof's to answer; the ``with``'s manager is what the
head reduces to (#7757), the undecided manager here, whose open exit keeps
the body's halt and decides no expectation.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.context_manager_resolution import (
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.lift_rpc import per_source_provisional_contract_refs
from sugar_lift_py_tests.no_call_body_attribution import (
    AttributionOutcome,
    BodyProbe,
    ProducerFamily,
    attribute_body_probes,
    _exceptional_exit_effects,
)
from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.with_source_resource_sugar import (
    WithReducedManagerSugar,
)
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
    """Production doors only: workspace-relative source + its table + With node."""
    source = (
        "import pytest\n"
        f"def use_{family.value.lower()}_boundary():\n"
        f"    with pytest.raises({expected}):\n"
        f"        {body}\n"
    )
    path = tmp_path / f"{family.value}_auth_exit.py"
    path.write_text(source, encoding="utf-8")
    root = tmp_path
    context = TreeConstructionContextV1(
        contract_refs=per_source_provisional_contract_refs(root),
    )
    tree = SourceFile(
        workspace_path_source(str(path), root=str(root)),
        construction_context=context,
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
def test_imported_pytest_raises_is_the_heads_reduced_value(
    tmp_path: Path,
    family: ProducerFamily,
    body: str,
    expected: str,
    node_type: type,
) -> None:
    """Shared door: the imported manager is never derived from the installed
    pytest body (#7884); it is what the head reduces to (#7757)."""
    del node_type
    _context, with_node, _body = _build_slice(
        tmp_path, family=family, body=body, expected=expected
    )
    boundary = with_node.sugar()
    assert isinstance(boundary, WithReducedManagerSugar), type(boundary).__name__


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
    """Truthful full route: the body's producer halt leaves the undecided manager.

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


def test_callsite_not_is_not_refused_for_manager_derivation(tmp_path: Path) -> None:
    """Shared fix pin: ``not CallSiteValue`` reaches truth, not SugarNotWritten.

    A call result's type is undecided, so ``bool()`` of it may run its
    ``__bool__`` / ``__len__``.  The one truth rule (``bool_op_sugar.truth_of``)
    answers the undecided member's two faces: the negated truth under the
    site's ``truth.completes`` guard, or an undetermined raise.  Nothing is
    refused, and nothing is claimed as one unconditional completion.

    The operand is a constructed term sugar and the site a real source
    fragment, the only shapes ``UnaryOpSugar`` receives
    (``require_constructed_term_sugar``; the truth is keyed by the site's
    coordinate).
    """
    from dataclasses import dataclass

    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.floor import CallSiteValue
    from sugar_lift_py_tests.ir import ctor
    from sugar_lift_py_tests.outcome import Completed
    from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
    from sugar_lift_py_tests.sugar.unary_op_sugar import UnaryOpSugar

    path = tmp_path / "not_call_result.py"
    path.write_text("result = not call_result\n")
    tree = SourceFile(workspace_path_source(str(path), root=str(tmp_path)))
    site = next(node for node in tree.nodes() if isinstance(node, UnaryOp)).fragment

    @dataclass(frozen=True)
    class _Operand(ConstructedTermSugar):
        value: object

        def desugar(self, ctx=None):
            del ctx
            return ExitSet.completed(self.value)

        @classmethod
        def witnesses(cls):
            return ()

        def to_term(self, *, owner):
            return self.value.to_term(owner=owner)

    call_result = CallSiteValue(
        "source-constructor",
        (),
        (),
        ctor("call:source-constructor", []),
        None,
    )
    outcome = UnaryOpSugar("Not", _Operand(call_result), site).desugar(None)

    completed = [exit_ for exit_ in outcome.exits if isinstance(exit_, Completed)]
    halted = outcome.halts()
    assert len(completed) == 1 and len(halted) == 1, outcome
    assert completed[0].value is not None
    assert isinstance(halted[0].effect, UndeterminedRaiseEffect), halted[0].effect
    assert halted[0].effect.producer_node_owner == "UnaryOpSugar.not"
