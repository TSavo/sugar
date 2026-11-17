"""A decorated class's methods read their ``__class__`` cell (#7757 step 6).

PEP 3135: a method that reads ``super`` or ``__class__`` closes over the
class's ``__class__`` cell, which ``type.__new__`` fills with the class the
``class`` statement built, before any decorator runs.  A decorator may bind
the class's name to anything (an imported ``set_module(...)``, a source
``def``'s call, another class): the cell still holds the class.

The lane run on ``d5dcbab5c`` refused 49 pandas methods
(``function_universe_outcome``: "the class statement's key holds a
CallSiteValue"): every method with a cell of a class decorated by a call
nothing here answers -- ``ArrowStringArray``, ``Expanding``,
``BooleanArray``, ``FrozenList``, ``PeriodIndex``, ``CategoricalIndex``,
``IntervalIndex``, ``ODFReader`` -- because the method's universe seated its
cell with the value the class's *name* held after the decorators.  The
module ``class`` statement now binds the class it built under its cell's
key beside its name's (``DecoratorApplicationSugar.cell_evaluation``,
``class_cell_key``), and the method's universe reads that key
(``tree_enumerate._class_cell_read``): the method lifts, its ``super()`` the
dispatched call after the class its statement built.

Solver twins: the class call goes through the decorator's result, whose
call nothing here answers, so the claim after it is carried undecided
(owed): the truthful half is never refuted, the lying half (the base method
always raises) is never ``sat``.
"""

from __future__ import annotations

import json
from pathlib import Path

from sugar_lift_py_tests.witness_harness import (
    claim_verdict,
    run_source_through_real_solver,
)


def _tree(source: str):
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_source_tree.tree import SourceFile

    return SourceFile(
        (source, "test_witness.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )


def _last_function(source: str, name: str):
    from sugar_source_tree import nodes

    found = tuple(
        node
        for node in _tree(source).nodes()
        if isinstance(node, nodes.FunctionDef) and node.name == name
    )
    return max(found, key=lambda node: node.line_col_span().start_line)


_DECORATED = """\
def {decorator}(c):
    return {returned}


class Base:
    def size(self):
        return 1


@{decorator}
class Box(Base):
    def size(self):
        return super().size() + 1
"""


def _method_outcome(decorator: str, returned: str):
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    source = _DECORATED.format(decorator=decorator, returned=returned)
    return function_universe_outcome(_last_function(source, "size"))


def test_a_method_of_a_class_a_source_decorator_wraps_lifts() -> None:
    """``@keep class Box(Base)``: the name holds ``keep(Box)``'s call (its
    coordinate and edge), the cell holds ``Box``.  ``Box.size`` lifts: its
    outcome is a set of arms with a completed face, never the refusal
    "the class statement's key holds a CallSiteValue"."""
    from sugar_lift_py_tests.outcome import Completed, ExitSet

    outcome = _method_outcome("keep", "c")
    assert isinstance(outcome, ExitSet), outcome
    assert any(isinstance(face, Completed) for face in outcome.exits), outcome


def test_a_decorator_that_returns_another_class_leaves_the_cell_alone() -> None:
    """``@swap class Box(Base)`` where ``swap`` returns ``Base``: the name
    is whatever the call returns, the cell is still the class the statement
    built, so ``super()`` in ``Box.size`` starts after ``Box`` and the
    method lifts as it does under ``keep``."""
    from sugar_lift_py_tests.outcome import Completed, ExitSet

    outcome = _method_outcome("swap", "Base")
    assert isinstance(outcome, ExitSet), outcome
    assert any(isinstance(face, Completed) for face in outcome.exits), outcome


_TWIN = """\
def keep(c):
    return c


class Base:
    def check(self):
{body}


@keep
class Child(Base):
    def __init__(self, n):
        self.n = n

    def run(self):
        state = super().check()
        return self.n


def test_child():
    child = Child(2)
    value = child.run()
    assert value == 2
"""


def test_decorated_class_super_call_twins(tmp_path: Path) -> None:
    """The truthful half (the base method returns) is never refuted; the
    lying half (it always raises) is never ``sat``.  ``Child`` is the call
    ``keep(Child)``, whose result's call nothing here answers, so both are
    carried undecided until that call is answered: ``open``."""
    truthful = _TWIN.format(body="        return None")
    lying = _TWIN.format(body="        raise ValueError('bad base')")
    told = run_source_through_real_solver(tmp_path / "truthful", truthful)
    lied = run_source_through_real_solver(tmp_path / "lying", lying)
    print(json.dumps({"truthful": told.verdict, "lying": lied.verdict}))
    (test_line,) = (
        number
        for number, line in enumerate(truthful.splitlines(), start=1)
        if line.startswith("def test_")
    )
    assert told.verdict != "unsat"
    assert claim_verdict(told.prove_doc, claims_from_line=test_line) != "unsat"
    assert lied.verdict != "sat"
    assert claim_verdict(lied.prove_doc, claims_from_line=test_line) != "sat"
