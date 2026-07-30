from __future__ import annotations

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
from sugar_lift_py_tests.floor import BlockValue, ReturnValue
from sugar_lift_py_tests.outcome import Complete, ExitSet


def _outcome(tmp_path, source: str):
    path = tmp_path / "while_return_else.py"
    path.write_text(source, encoding="utf-8")
    function = next(
        open_source_file_for_construction(
            path,
            root=tmp_path,
            construction_context=TreeConstructionContextV1.for_source_call_construction(
                workspace_root=str(tmp_path)
            ),
        ).functions()
    )
    return function.sugar().desugar()


def test_unconditional_while_return_has_no_fabricated_else_face(tmp_path) -> None:
    outcome = _outcome(
        tmp_path,
        "def choose():\n"
        "    while True:\n"
        "        return 7\n"
        "    else:\n"
        "        return 9\n",
    )

    assert isinstance(outcome, Complete), outcome
    assert isinstance(outcome.value.record, BlockValue)
    returns = tuple(
        entry
        for entry in outcome.value.record.statements
        if isinstance(entry, ReturnValue)
    )
    assert len(returns) == 1
    assert returns[0].value.value == 7


def test_symbolic_while_retains_distinct_return_and_else_faces(tmp_path) -> None:
    outcome = _outcome(
        tmp_path,
        "def choose(condition):\n"
        "    while condition:\n"
        "        return 7\n"
        "    else:\n"
        "        return 9\n",
    )

    assert isinstance(outcome, ExitSet), outcome
    assert len(outcome.exits) == 2
