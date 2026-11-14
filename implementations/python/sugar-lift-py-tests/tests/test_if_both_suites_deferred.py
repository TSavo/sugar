"""An undecided ``if`` whose two suites each hold a formal native operation.

``return -x`` and ``return ~x`` over a formal ``x`` are deferred carriers: each
suite's exits exist only once caller actuals discharge its own demand. The
one-sided join (#7600) waited for the deferred suite's discharge; with BOTH
suites deferred the join fell through to the ordinary union and crashed on
the carrier (``'NativeOperationExitCarrierV1' object has no attribute
'union'``), so the function could not be lifted at all.

Now the join waits for both: the then carrier's discharge hands its faces to a
step that returns the else carrier, which the same caller actuals discharge,
and only then is the ordinary union taken -- each suite's faces under its own
polarity. Neither demand is merged into the other and neither suite is
decided early.
"""

from __future__ import annotations

from sugar_lift_py_tests.caller_parameter_contract import NativeOperationExitCarrierV1
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.ir import _Connective
from sugar_lift_py_tests.outcome import Completed
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import FunctionDef
from sugar_source_tree.tree import SourceFile

HELPER = (
    "import textwrap\n"
    "def helper(x):\n"
    "    if textwrap.dedent('a'):\n"
    "        return -x\n"
    "    else:\n"
    "        return ~x\n"
)


def _helper_outcome(source: str):
    """The helper lifted on its own: formal operands stay deferred carriers."""
    tree = SourceFile(
        (source, "if-both-deferred.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    function = next(node for node in tree.nodes() if isinstance(node, FunctionDef))
    return function.sugar().desugar(None)


def _guarded_returns(exits):
    # ``textwrap`` is not enrolled: its call's may-raise face returns nothing.
    (face,) = [face for face in exits.exits if isinstance(face, Completed)]
    assert [
        other.effect.producer_node_owner
        for other in exits.exits
        if other is not face
    ] == ["UnknownCallee:textwrap.dedent"]
    return [
        entry
        for entry in face.value.record.statements
        if type(entry).__name__ == "GuardedReturn"
    ]


def test_both_deferred_suites_lift_as_one_pending_carrier() -> None:
    pending = _helper_outcome(HELPER)
    assert isinstance(pending, NativeOperationExitCarrierV1)
    assert pending.demand.operator == "unary_minus"


def test_one_discharge_resolves_both_suites_under_opposite_polarity() -> None:
    pending = _helper_outcome(HELPER)
    (formal,) = [cid for cid in pending.demand.operand_coordinate_cids if cid]

    returns = _guarded_returns(pending.discharge(None, {formal: TermValue(3)}))

    assert sorted(entry.value.value for entry in returns) == [-4, -3]
    by_value = {entry.value.value: entry.guards for entry in returns}
    (then_guard,) = by_value[-3]
    (else_guard,) = by_value[-4]
    # The else suite stands under the negation of the then suite's condition.
    assert isinstance(else_guard, _Connective) and else_guard.kind == "not"
    assert else_guard.operands == (then_guard,)


def test_each_discharge_is_its_own_resolution() -> None:
    pending = _helper_outcome(HELPER)
    (formal,) = [cid for cid in pending.demand.operand_coordinate_cids if cid]

    first = _guarded_returns(pending.discharge(None, {formal: TermValue(3)}))
    second = _guarded_returns(pending.discharge(None, {formal: TermValue(5)}))

    assert sorted(entry.value.value for entry in first) == [-4, -3]
    assert sorted(entry.value.value for entry in second) == [-6, -5]
