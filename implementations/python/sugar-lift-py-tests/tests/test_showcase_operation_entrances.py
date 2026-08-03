"""Showcase regressions must walk the live operation-owned entrances."""

from __future__ import annotations

from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
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


class _RecordingSubmittedOperation:
    owner = "callsite-subscript"

    def __init__(self) -> None:
        self.answer = object()
        self.submissions: list[tuple[object, object]] = []

    def submit(self, receiver, ctx):
        self.submissions.append((receiver, ctx))
        return self.answer


def test_callsite_subscript_redispatches_through_operation_owned_submit() -> None:
    callsite = CallSiteValue(
        "pandas.perform_operation",
        (),
        (),
        make_var("pandas-callsite"),
        None,
    )
    operation = _RecordingSubmittedOperation()
    ctx = object()

    answer = callsite.subscript_with(operation, ctx)

    assert answer is operation.answer
    assert len(operation.submissions) == 1
    receiver, submitted_ctx = operation.submissions[0]
    assert isinstance(receiver, SymbolicValue)
    assert receiver.term == callsite.term
    assert submitted_ctx is ctx


class _RecordingSubscriptReceiver:
    def __init__(self) -> None:
        self.subscripts: list[tuple[object, object]] = []

    def subscript_with(self, operation, ctx):
        self.subscripts.append((operation, ctx))
        return Complete(self)


def test_subscript_operation_submits_itself_to_the_receiver_port() -> None:
    operation = SubscriptOperation(
        index=_RecordingTermIndex(),
        owner="operation-submit",
        blame="operation-submit-site",
    )
    receiver = _RecordingSubscriptReceiver()
    ctx = object()

    outcome = operation.submit(receiver, ctx)

    assert isinstance(outcome, Complete)
    assert outcome.value is receiver
    assert receiver.subscripts == [(operation, ctx)]
