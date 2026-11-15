"""``try ... except*`` runs the one temporal rewrite of a ``try`` (#7757).

``TryStar.substitute`` is ``Try.substitute``: the body threads into ``else``,
each arm begins from the state its routed halts carry, ``finally`` reads what
the route into it bound, and the statement exports what its completion routes
bound. A name the statement binds is read after it as what it bound, never
as the binding standing before the ``try`` (a function local first bound
inside it was read as unbound: a ``NameError`` halt in place of the value).

The arms of an ``except*`` run in turn on one raised group. The rewrite
states one arm per halt, which is an ``except*`` exactly where no arm but the
last changes a binding; an earlier arm that changes one is refused by name
(``TryStar._arm_entry_state``), never begun from the body's halt as if the
earlier arm had not run.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import ReturnValue
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import FunctionDef
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _function(source: str) -> FunctionDef:
    tree = SourceFile(
        (source, "try_star_one_rewrite.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    return next(node for node in tree.nodes() if isinstance(node, FunctionDef))


def _returned_values(source: str) -> list:
    """What the function's one completed arm returns."""
    outcome = _function(source).sugar().desugar(None)
    assert outcome.halts() == (), outcome.exits
    completed = outcome.completed_value()
    assert completed is not None, outcome.exits
    return [
        entry.value.value
        for entry in completed.record.statements
        if isinstance(entry, ReturnValue)
    ]


def test_a_name_the_try_star_body_binds_is_read_after_the_statement() -> None:
    # The body cannot halt: the function returns what it bound. Read as the
    # binding standing before the ``try``, ``x`` is an unbound local and the
    # function's only exit is a ``NameError`` halt.
    assert _returned_values(
        "def f():\n"
        "    try:\n"
        "        x = 1\n"
        "    except* ValueError:\n"
        "        pass\n"
        "    return x\n"
    ) == [1]


def test_a_name_rebound_in_the_try_star_body_is_not_read_as_it_stood_before() -> None:
    # The lying twin: ``x = 0`` before the ``try`` is not what ``f`` returns.
    assert _returned_values(
        "def f():\n"
        "    x = 0\n"
        "    try:\n"
        "        x = 1\n"
        "    except* ValueError:\n"
        "        pass\n"
        "    return x\n"
    ) == [1]


def test_a_try_star_finally_reads_what_the_body_bound() -> None:
    assert _returned_values(
        "def f():\n"
        "    x = 0\n"
        "    try:\n"
        "        x = 1\n"
        "    except* ValueError:\n"
        "        pass\n"
        "    finally:\n"
        "        y = x\n"
        "    return y\n"
    ) == [1]


_ARMS_IN_TURN = (
    "def f():\n"
    "    try:\n"
    "        raise ExceptionGroup('g', [ValueError(), TypeError()])\n"
    "    except* ValueError:\n"
    "        {first}\n"
    "    except* TypeError:\n"
    "        pass\n"
    "    return 0\n"
)


def test_an_earlier_except_star_arm_that_binds_is_refused_by_name() -> None:
    # Both arms run on the one group, the second after the first's store: a
    # state the one-arm-per-halt rewrite does not give the second arm.
    with pytest.raises(SugarNotWritten) as excinfo:
        _function(_ARMS_IN_TURN.format(first="x = 1")).sugar().desugar(None)
    assert "an except* arm changes a binding" in str(excinfo.value)


def test_except_star_arms_that_change_nothing_run_in_turn() -> None:
    # The truthful twin: no arm changes a binding, so every arm begins from
    # the body's halt, and the function completes after both ran.
    assert _returned_values(_ARMS_IN_TURN.format(first="pass")) == [0]


def test_an_earlier_arms_as_name_a_later_arm_does_not_bind_is_refused() -> None:
    # The first arm ends by unbinding ``eg``; the second, which does not bind
    # it itself, would read it as it stood at the body's halt.
    source = (
        "def f():\n"
        "    try:\n"
        "        raise ExceptionGroup('g', [ValueError(), TypeError()])\n"
        "    except* ValueError as eg:\n"
        "        pass\n"
        "    except* TypeError:\n"
        "        pass\n"
        "    return 0\n"
    )
    with pytest.raises(SugarNotWritten) as excinfo:
        _function(source).sugar().desugar(None)
    assert "an except* arm changes a binding" in str(excinfo.value)


def test_except_star_arms_binding_the_same_as_name_run_in_turn() -> None:
    assert _returned_values(
        "def f():\n"
        "    try:\n"
        "        raise ExceptionGroup('g', [ValueError(), TypeError()])\n"
        "    except* ValueError as eg:\n"
        "        pass\n"
        "    except* TypeError as eg:\n"
        "        pass\n"
        "    return 0\n"
    ) == [0]
