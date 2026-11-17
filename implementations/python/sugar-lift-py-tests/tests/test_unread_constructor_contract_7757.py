"""A class whose constructor no lookup reads states its call undecided
(#7757 step 6).

``ClassDef.constructor_is_read`` is False where the one class-namespace
lookup does not decide which ``__new__`` and ``__init__`` a call of the
class runs: an imported base, a ``Protocol``/``Generic``/``ABC`` base, a
metaclass, a decorator that may write either.  A caller's ``Cls(...)`` is
then the one unanswered call (``ClassDefinitionValue.
callable_application_with``).  The class's own constructor contract
(``tree_enumerate.class_universe_outcome``) refused the whole class instead:
173 pandas classes on the ``d5dcbab5c`` lane run ("the constructor X's call
runs is not read").

It now states that same call: the universe of ``return Cls(*args,
**kwargs)`` (``_unread_constructor_outcome``), through the one spread-call
door, which with no exact roster is the one unanswered call -- its result
and its undetermined raise both carried, owed.  No signature is read, so the
formals are ``(*args, **kwargs)``; no ``def`` body is read, so it takes no
input.

Solver twins: what the call makes is undecided, so a claim on it is never
``sat`` for the lie and never refuted for the truth; and where the source's
``__init__`` always raises, the claim after the call is never ``sat`` (the
halt is carried, never dropped).
"""

from __future__ import annotations

import json
from pathlib import Path

from sugar_lift_py_tests.witness_harness import (
    claim_verdict,
    run_source_through_real_solver,
)

_UNREAD = """\
import collections


class Box(collections.OrderedDict):
    def __init__(self, n):
{body}
"""


def _class(tmp_path: Path, source: str, name: str):
    from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
    from sugar_lift_py_tests.tree_enumerate import classes_with_contracts

    producer = tmp_path / "producer.py"
    producer.write_text(source)
    tree = open_source_file_for_construction(producer, root=tmp_path)
    (cls,) = [item for item in classes_with_contracts(tree) if item.name == name]
    return cls


def test_an_unread_constructor_states_the_unanswered_call(tmp_path: Path) -> None:
    """``class Box(collections.OrderedDict)``: the lookup does not decide
    the call, and the class's outcome is the unanswered call's two faces,
    never a refusal."""
    from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
    from sugar_lift_py_tests.tree_enumerate import class_universe_outcome

    cls = _class(tmp_path, _UNREAD.format(body="        self.n = n"), "Box")
    assert not cls.constructor_is_read()
    outcome = class_universe_outcome(cls)
    assert isinstance(outcome, ExitSet), outcome
    assert any(isinstance(face, Completed) for face in outcome.exits), outcome
    assert any(isinstance(face, Halted) for face in outcome.exits), outcome


def test_an_unread_constructor_contract_takes_every_actual(tmp_path: Path) -> None:
    """The row is stated under the class's join symbol over ``(*args,
    **kwargs)``: no signature is read, whatever the class body's own
    ``__init__`` says."""
    from sugar_lift_py_tests.tree_enumerate import class_contract_rows

    cls = _class(tmp_path, _UNREAD.format(body="        self.n = n"), "Box")
    _memento, rows = class_contract_rows(cls, "producer.py")
    assert rows is not None
    contracts = [row for row in rows if row.kind == "function-contract"]
    assert contracts, rows
    for row in contracts:
        assert row.name == "python:producer.Box"
        assert row.bridge_source_symbol == "python:producer.Box"
        assert row.formals == ["args", "kwargs"]


_TWIN = """\
import collections


class Box(collections.OrderedDict):
    def __init__(self, n):
{body}


def test_box():
    box = Box(2)
    assert {claim}
"""


def _verdicts(tmp_path: Path, name: str, source: str) -> tuple[str, str]:
    result = run_source_through_real_solver(tmp_path / name, source)
    (test_line,) = (
        number
        for number, line in enumerate(source.splitlines(), start=1)
        if line.startswith("def test_")
    )
    return result.verdict, claim_verdict(result.prove_doc, claims_from_line=test_line)


def test_an_unread_constructor_result_twins(tmp_path: Path) -> None:
    """``Box(2) is not None`` is true in Python; ``Box(2) is None`` is a lie.
    The call's result is undecided: the truth is never refuted, the lie is
    never ``sat``."""
    body = "        self.n = n"
    told = _verdicts(
        tmp_path, "truthful", _TWIN.format(body=body, claim="box is not None")
    )
    lied = _verdicts(tmp_path, "lying", _TWIN.format(body=body, claim="box is None"))
    print(json.dumps({"truthful": told, "lying": lied}))
    assert "unsat" not in told
    assert "sat" not in lied


def test_an_unread_constructor_keeps_its_halt(tmp_path: Path) -> None:
    """Where ``Box.__init__`` always raises, Python never reaches the claim
    after ``Box(2)``: the lie.  The call's undetermined raise is carried, so
    the claim is never ``sat``; where it returns, the claim is never
    refuted."""
    told = _verdicts(
        tmp_path,
        "truthful",
        _TWIN.format(body="        self.n = n", claim="1 == 1"),
    )
    lied = _verdicts(
        tmp_path,
        "lying",
        _TWIN.format(body="        raise ValueError('no')", claim="1 == 1"),
    )
    print(json.dumps({"truthful": told, "lying": lied}))
    assert "unsat" not in told
    assert "sat" not in lied
