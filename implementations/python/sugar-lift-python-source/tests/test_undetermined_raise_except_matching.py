"""``except T`` around a may-raise operation tests the exception it threw.

An unanswered call, an unprojected source call, an imported source-class construction,
and an opaque subscript each halt with an ``UndeterminedRaiseEffect``: the
operation may raise, and nothing testified to the class. Ordinary ``except``
refused every such halt (``SugarNotWritten [TrySugar._effect_match_verdict]``)
because the effect carried no value to state the type test over, and the raise
site is not admissible as one.

The effect now carries its own exception value, ``UndeterminedExceptionValue``
(term ``python:undetermined_exception(occurrence, producer)``): the one
exception object that occurrence threw. ``except T`` splits the halt into a
caught face under ``adt.is_python_type(<that exception>, T)`` and the original
halt under the complement. ``except BaseException`` and bare ``except`` catch
it totally; ``except Exception`` does not (a C call or a Python callee can
leave with ``KeyboardInterrupt``/``SystemExit``). ``as e`` binds that same
value, whose reads stay refusals, and ``raise e`` re-raises the same object.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor.undetermined_exception_value import (
    UndeterminedExceptionValue,
)
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted, outcome_to_exitset
from sugar_source_tree.nodes import FunctionDef

from test_contextlib_suppress_source_exit_faces import _corpus, _open

# A call nothing here answers (not bridged): the one two-faced unknown callee.
C_CALL = ("", "h()", "UnknownCallee:h")
SOURCE_CALL = (
    "import textwrap\n",
    'textwrap.dedent("x")',
    "UnknownCallee:textwrap.dedent",
)


def _exits(tmp_path: Path, source: str):
    source_file = _open(_corpus(tmp_path, source))
    func = next(
        n for n in source_file.nodes() if isinstance(n, FunctionDef) and n.name == "f"
    )
    return outcome_to_exitset(func.sugar().desugar())


def _try(prelude: str, operation: str, *arms: tuple[str, str]) -> str:
    source = f"{prelude}def f():\n    try:\n        return {operation}\n"
    for handler, body in arms:
        source += f"    except {handler}:\n        {body}\n"
    return source


def _entries(exits):
    """Every return/halt the function can leave by, with its guard text.

    A routed face carries its guard on the face; an entry inside a face may
    carry more.  The guard text is both, face first."""
    rows = []
    for face in exits.exits:
        if isinstance(face, Halted):
            rows.append(("halt", face.effect, repr(face.guard)))
            continue
        face_guard = repr(face.guard)
        record = getattr(face.value, "record", None)
        for entry in getattr(record, "statements", ()):
            name = type(entry).__name__
            if name == "GuardedReturn":
                rows.append(("return", entry.value, face_guard + repr(entry.guards)))
            elif name == "ReturnValue":
                rows.append(("return", entry.value, face_guard))
            elif isinstance(entry, ExitSet) and entry.halts() == entry.exits:
                for halt in entry.halts():
                    rows.append(("halt", halt.effect, face_guard + repr(halt.guard)))
    return rows


def _undetermined_halts(exits, producer: str):
    return [
        row
        for row in _entries(exits)
        if row[0] == "halt"
        and isinstance(row[1], UndeterminedRaiseEffect)
        and row[1].producer_node_owner == producer
    ]


def _returns_one(exits):
    return [row for row in _entries(exits) if row[0] == "return" and "value=1)" in repr(row[1])]


def _subject(producer: str) -> str:
    return (
        "_Atomic(name='adt.is_python_type', args=(_Ctor(name='python:undetermined_exception', "
    ), f"value='{producer}'"


def _handler(name: str) -> str:
    return f"_ConstStr(value='{name}', sort=PrimitiveSort(name='String'))"


@pytest.mark.parametrize(
    "prelude, operation, producer",
    [
        C_CALL,
        SOURCE_CALL,
        (
            "import json\n",
            'json.JSONDecodeError("m", "d", 0)',
            "UnknownCallee:json.JSONDecodeError",
        ),
        ("import textwrap\n", 'textwrap.dedent("x")[0]', "CallSiteValue.subscript"),
    ],
    ids=["unanswered-call", "source-call", "construction", "opaque-subscript"],
)
def test_typed_except_splits_on_the_raised_exception(tmp_path, prelude, operation, producer) -> None:
    exits = _exits(tmp_path, _try(prelude, operation, ("ValueError", "return 1")))
    atom_head, producer_text = _subject(producer)
    caught = [row for row in _returns_one(exits) if producer_text in row[2]]
    (row,) = caught
    assert atom_head in row[2] and _handler("ValueError") in row[2]
    (escaping,) = _undetermined_halts(exits, producer)
    assert "kind='not', operands=(" + atom_head in escaping[2]
    assert producer_text in escaping[2]


def test_caught_face_names_the_occurrence_and_producer(tmp_path) -> None:
    prelude, operation, producer = C_CALL
    exits = _exits(tmp_path, _try(prelude, operation, ("ValueError", "return 1")))
    (caught,) = _returns_one(exits)
    (halt,) = _undetermined_halts(exits, producer)
    _, producer_text = _subject(producer)
    assert producer_text in caught[2]
    assert f"value={halt[1].occurrence_id!r}" in caught[2]
    assert "kind='not'" in halt[2] and producer_text in halt[2]


@pytest.mark.parametrize("handler", ["BaseException", ""])
def test_base_exception_and_bare_except_catch_totally(tmp_path, handler) -> None:
    prelude, operation, producer = C_CALL
    source = _try(prelude, operation, ("X", "return 1")).replace(
        "except X:", f"except {handler}:" if handler else "except:"
    )
    exits = _exits(tmp_path, source)
    assert _returns_one(exits)
    assert _undetermined_halts(exits, producer) == []
    assert "python:undetermined_exception" not in repr(exits)


def test_except_exception_is_not_total(tmp_path) -> None:
    prelude, operation, producer = C_CALL
    exits = _exits(tmp_path, _try(prelude, operation, ("Exception", "return 1")))
    (caught,) = _returns_one(exits)
    assert _handler("Exception") in caught[2]
    assert len(_undetermined_halts(exits, producer)) == 1


def test_tuple_handler_is_a_disjunction(tmp_path) -> None:
    prelude, operation, producer = C_CALL
    exits = _exits(tmp_path, _try(prelude, operation, ("(ValueError, KeyError)", "return 1")))
    (caught,) = _returns_one(exits)
    assert "kind='or'" in caught[2]
    assert _handler("ValueError") in caught[2] and _handler("KeyError") in caught[2]
    assert len(_undetermined_halts(exits, producer)) == 1


def test_later_arm_sees_the_complement_of_earlier_arms(tmp_path) -> None:
    prelude, operation, producer = C_CALL
    exits = _exits(
        tmp_path,
        _try(prelude, operation, ("ValueError", "return 1"), ("KeyError", "return 2")),
    )
    second = [row for row in _entries(exits) if row[0] == "return" and "value=2)" in repr(row[1])]
    (row,) = second
    assert "kind='not'" in row[2] and _handler("ValueError") in row[2]
    assert _handler("KeyError") in row[2]
    assert len(_undetermined_halts(exits, producer)) == 1


def test_as_binds_the_same_exception_value(tmp_path) -> None:
    prelude, operation, producer = C_CALL
    exits = _exits(tmp_path, _try(prelude, operation, ("ValueError as e", "return e")))
    bound = [
        row for row in _entries(exits)
        if row[0] == "return" and isinstance(row[1], UndeterminedExceptionValue)
    ]
    (row,) = bound
    (halt,) = _undetermined_halts(exits, producer)
    assert row[1] == halt[1].exception_value
    assert row[1].producer == producer


def test_reads_on_the_bound_exception_are_not_invented(tmp_path) -> None:
    prelude, operation, _ = C_CALL
    with pytest.raises(ConstructionPanic):
        _exits(tmp_path, _try(prelude, operation, ("ValueError as e", "return e.args")))


def test_raise_e_reraises_the_same_exception(tmp_path) -> None:
    prelude, operation, producer = C_CALL
    exits = _exits(tmp_path, _try(prelude, operation, ("ValueError as e", "raise e")))
    halts = [
        row for row in _entries(exits)
        if row[0] == "halt" and isinstance(row[1], UndeterminedRaiseEffect)
    ]
    (original,) = _undetermined_halts(exits, producer)
    reraised = [row for row in halts if row is not original and row[1] is not original[1]]
    assert reraised
    assert {row[1].exception_value for row in reraised} == {original[1].exception_value}


def test_each_call_site_raises_its_own_exception(tmp_path) -> None:
    source = (
        "import textwrap\n"
        "def f():\n"
        "    try:\n"
        '        textwrap.dedent("a")\n'
        '        return textwrap.dedent("b")\n'
        "    except ValueError:\n"
        "        return 1\n"
    )
    exits = _exits(tmp_path, source)
    halts = _undetermined_halts(exits, SOURCE_CALL[2])
    assert len(halts) == 2
    assert len({row[1].exception_value for row in halts}) == 2


def test_occurrence_less_halt_has_no_exception_value() -> None:
    assert UndeterminedRaiseEffect().exception_value is None
    assert UndeterminedRaiseEffect(occurrence="e.py:1:0", raised_value=object()).exception_value is None


def test_formal_raise_keeps_its_operand_as_the_subject(tmp_path) -> None:
    exits = _exits(
        tmp_path,
        "def f(exc):\n    try:\n        raise exc\n    except ValueError:\n        return 1\n",
    )
    (caught,) = _returns_one(exits)
    assert "adt.is_python_type" in caught[2]
    assert "python:undetermined_exception" not in caught[2]
