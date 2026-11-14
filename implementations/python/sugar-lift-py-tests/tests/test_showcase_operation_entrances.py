"""Showcase regressions must walk the live operation-owned entrances."""

from __future__ import annotations

from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
from sugar_lift_py_tests.ir import ctor, make_var
from sugar_lift_py_tests.operations.subscript_operation import SubscriptOperation
from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.outcome.exit_set import Completed, Halted


class _Site:
    """A fragment's two coordinates: its unit's source CID and its span."""

    class _Span:
        start_line, start_col, end_line, end_col = 3, 4, 3, 12

    source_cid = "blake3-512:" + "ab" * 64
    line_col_span = _Span()


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
        blame=_Site(),
    )

    outcome = operation.submit(receiver, None)

    (done,) = [arm for arm in outcome.exits if isinstance(arm, Completed)]
    assert done.value.term == ctor("py.subscript", [receiver.term, index.term])
    assert index.owners == ["SymbolicValue.subscript"]


def test_opaque_callsite_subscript_is_the_one_undecided_read() -> None:
    """The opaque arm answers the two faces itself, once: no resubmission
    to a symbolic stand-in, no wrapper rebuilding its faces."""
    callsite = CallSiteValue(
        "pandas.perform_operation",
        (),
        (),
        make_var("pandas-callsite"),
        None,
    )
    index = _RecordingTermIndex()
    operation = SubscriptOperation(
        index=index,
        owner="callsite-subscript",
        blame=_Site(),
    )

    outcome = callsite.subscript_with(operation, object())

    (done,) = [arm for arm in outcome.exits if isinstance(arm, Completed)]
    (halt,) = [arm for arm in outcome.exits if isinstance(arm, Halted)]
    assert len(outcome.exits) == 2
    assert done.value.term == ctor("py.subscript", [callsite.term, index.term])
    assert halt.effect.producer_node_owner == "CallSiteValue.subscript"
    assert index.owners == ["CallSiteValue.subscript"]


class _RecordingSubscriptReceiver:
    def __init__(self) -> None:
        self.subscripts: list[tuple[object, object]] = []

    def subscript_with(self, operation, ctx):
        self.subscripts.append((operation, ctx))
        return ExitSet.completed(self)


def test_subscript_operation_submits_itself_to_the_receiver_port() -> None:
    operation = SubscriptOperation(
        index=_RecordingTermIndex(),
        owner="operation-submit",
        blame="operation-submit-site",
    )
    receiver = _RecordingSubscriptReceiver()
    ctx = object()

    outcome = operation.submit(receiver, ctx)

    assert outcome.completed_value() is receiver
    assert receiver.subscripts == [(operation, ctx)]
