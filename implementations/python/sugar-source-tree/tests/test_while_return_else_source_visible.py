from __future__ import annotations

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
from sugar_lift_py_tests.floor import BlockValue, ReturnValue
from sugar_lift_py_tests.effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.outcome import Completed, ExitSet
from sugar_lift_py_tests.outcome.exit_set import _is_true
from sugar_lift_py_tests.sugar.loop_recurrence_sugar import LoopRecurrenceSugar


def _function(tmp_path, source: str):
    path = tmp_path / "while_return_else.py"
    path.write_text(source, encoding="utf-8")
    return next(
        open_source_file_for_construction(
            path,
            root=tmp_path,
            construction_context=TreeConstructionContextV1.for_source_call_construction(
                workspace_root=str(tmp_path)
            ),
        ).functions()
    )


def _outcome(tmp_path, source: str):
    return _function(tmp_path, source).sugar().desugar()


def _loop(tmp_path, source: str) -> LoopRecurrenceSugar:
    return next(
        statement
        for statement in _function(tmp_path, source).sugar().statements
        if isinstance(statement, LoopRecurrenceSugar)
    )


def test_a_constant_while_test_is_its_slot_guard_and_the_reduction_decides_it(
    tmp_path,
) -> None:
    # The construction never decides ``while True:``: the item runs under the
    # test's slot guard on the wire, and the symbolic item is handed the test
    # (it reads no binding), which the reduction evaluates through the one
    # truth rule (``LoopRecurrenceSugar._tested``).
    loop = _loop(
        tmp_path,
        "def choose():\n"
        "    while True:\n"
        "        return 7\n"
        "    else:\n"
        "        return 9\n",
    )
    _body, guard = loop._symbolic_item()
    assert not _is_true(guard), guard
    test, decides = loop._symbolic_test()
    assert test is not None and decides


def test_a_while_test_that_reads_a_binding_is_evaluated_but_never_decides(
    tmp_path,
) -> None:
    # ``condition`` may differ from one item to the next: the symbolic item
    # does not stand for every item's test, so it runs under the slot guard.
    # The test is evaluated all the same, as every item evaluates it: it is
    # constructed with the loop and its halts are the loop's.
    loop = _loop(
        tmp_path,
        "def choose(condition):\n"
        "    while condition:\n"
        "        return 7\n"
        "    else:\n"
        "        return 9\n",
    )
    test, decides = loop._symbolic_test()
    assert test is not None and not decides


def test_unconditional_while_return_has_no_fabricated_else_face(tmp_path) -> None:
    outcome = _outcome(
        tmp_path,
        "def choose():\n"
        "    while True:\n"
        "        return 7\n"
        "    else:\n"
        "        return 9\n",
    )

    value = outcome.completed_value()
    assert value is not None, outcome
    assert isinstance(value.record, BlockValue)
    returns = tuple(
        entry
        for entry in value.record.statements
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
    # Two distinct completed faces -- the body's ``return 7`` and the else's
    # ``return 9`` -- and, beside them, the halt of the test's truth:
    # ``bool(condition)`` on a formal can raise, so the ``while`` test's halt
    # is kept as the third face (#7757 NEW-1), never dropped.
    assert len(outcome.exits) == 3, outcome.exits
    completed = [exit_ for exit_ in outcome.exits if isinstance(exit_, Completed)]
    returned = sorted(
        entry.value.value
        for face in completed
        for entry in face.value.record.statements
        if isinstance(entry, ReturnValue)
    )
    assert returned == [7, 9], completed
    halts = outcome.halts()
    assert len(halts) == 1, halts
    assert isinstance(halts[0].effect, UndeterminedRaiseEffect)
    assert halts[0].effect.producer_node_owner == "LoopRecurrenceSugar.while-test"
