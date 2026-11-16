"""A function whose operation on a formal is undecided is read by the one row path.

#7766, steps 6-7. A body with a binary operation on a formal
(``return x + 10``) once reduced to a deferred native operation that waited
on a caller's actual; such a function emitted no contract row at all: its
proof silently lacked its claims and its halt.

A binary operator with a parameter operand is now the undecided two faces
where it runs (``undecided_binary_faces``, #7757 audit row NEW-1): the
operation completes only under its own undecided guard, halts under the
complement, and both faces owe one ``undecided`` member
(``reason: unanswered``) at the operation's site. The rows are read off those
arms like any other function's, and the scope law is the one every row goes
through. A module-level operand (``LIMIT``) is owed with its operation: what
the operation does is not decided here, and that is stated once, as the
member.
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
