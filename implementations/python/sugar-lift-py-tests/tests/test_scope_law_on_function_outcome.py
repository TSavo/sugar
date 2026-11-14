"""A function whose operation waits on a caller's actual is read by the one row path.

#7766, steps 6-7. A body whose operation on a formal waits for the caller's
actual (``return x + 10``) reduces to a deferred native operation
(``NativeOperationExitCarrierV1``), the one mechanism a caller applying the
body in place discharges with its actuals. Before this, such a function
emitted no contract row at all (only a scope check on the carrier's demand
formula): its proof silently lacked its claims and its halt.

Now its reduction is the set of arms its own proof states, with no actual
(``tree_enumerate.as_its_own_proof_states``): the operation completes only
under its own undecided guard, halts under the complement, and both faces owe
one ``undecided`` member (``reason: unanswered``) at the operation's site.
The rows are read off those arms like any other function's, and the scope law
is the one every row goes through. The terms name the operator and the
occurrence, never an operand, so a module-level operand (``LIMIT``) is not in
the function's rows: what the operation does is not decided here, and that is
stated once, as the member.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests import lift_rpc
from sugar_lift_py_tests import tree_enumerate as _tree
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_lift_py_tests.unanswered_calls import owed_calls


def _functions(tmp_path: Path, source: str) -> dict:
    path = tmp_path / "m.py"
    path.write_text(source, encoding="utf-8")
    from sugar_source_tree.reporter import CollectingReporter

    tree = lift_rpc.open_source_file_for_construction(
        path, root=tmp_path, reporter=CollectingReporter()
    )
    return {fn.name: fn for fn in tree.functions()}


def _owes_the_operation_at(outcome, line: int) -> None:
    assert isinstance(outcome, ExitSet), type(outcome).__name__
    kinds = {type(arm) for arm in outcome.exits}
    # The operation's two faces: it may complete, and it may raise.
    assert Completed in kinds and Halted in kinds, outcome.exits
    owed = [item for item in owed_calls(outcome) if item.symbol is None]
    assert [item.site.start_line for item in owed] == [line], owed


def test_an_operation_on_a_formal_emits_rows_and_owes_its_operation(
    tmp_path: Path,
) -> None:
    fns = _functions(tmp_path, "def f(x):\n    return x + 10\n")
    _memento, rows = _tree.function_contract_rows(fns["f"], "m.py")
    assert rows, "the function states its contract; it is never silent"
    _owes_the_operation_at(_tree.owner_reduction(fns["f"]).outcome, 2)


def test_a_module_level_operand_is_owed_with_its_operation(tmp_path: Path) -> None:
    fns = _functions(tmp_path, "LIMIT = 10\n\n\ndef f(x):\n    return x + LIMIT\n")
    _memento, rows = _tree.function_contract_rows(fns["f"], "m.py")
    assert rows, "the function states its contract; it is never silent"
    _owes_the_operation_at(_tree.owner_reduction(fns["f"]).outcome, 5)
