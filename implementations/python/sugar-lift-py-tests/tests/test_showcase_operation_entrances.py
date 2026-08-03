"""Showcase regressions must walk the live operation-owned entrances."""

from __future__ import annotations

from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
from sugar_lift_py_tests.ir import ctor, make_var
from sugar_lift_py_tests.operations.subscript_operation import SubscriptOperation
from sugar_lift_py_tests.outcome import Complete


class _RecordingTermIndex:
    def __init__(self) -> None:
        self.term = make_var("index")
        self.owners: list[str] = []

    def to_term(self, *, owner: str):
        self.owners.append(owner)
        return self.term


def test_symbolic_subscript_projects_its_index_through_the_owned_term_door() -> None:
    """The subscript operation must not rediscover the deleted floor shim."""
    index = _RecordingTermIndex()
    receiver = SymbolicValue(make_var("items"))
    operation = SubscriptOperation(
        index=index,
        owner="symbolic-subscript",
        blame="symbolic-subscript-site",
    )

    outcome = operation.subscript_symbolic(receiver, None)

    assert isinstance(outcome, Complete)
    assert outcome.value.term == ctor("py.subscript", [receiver.term, index.term])
    assert index.owners == ["symbolic-subscript index"]
