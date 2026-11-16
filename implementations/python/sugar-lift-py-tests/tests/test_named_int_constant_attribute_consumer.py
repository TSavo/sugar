"""Bounded consumer instrument for authenticated ``_NamedIntConstant.name``."""

from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor.object_value import ObjectField, ObjectValue
from sugar_lift_py_tests.floor.string_value import StringValue
from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.attribute_sugar import AttributeSugar
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar

from frame_fresh import FRAME_FRESH


class _ReceiverSugar(ConstructedTermSugar):
    def __init__(self, receiver):
        self.receiver = receiver
        self.site = _Site("receiver")

    @classmethod
    def witnesses(cls):
        raise AssertionError("instrument leaf")

    def desugar(self, ctx=None):
        return ExitSet.completed(self.receiver)

    def to_term(self, *, owner):
        del owner
        return self.receiver.to_term(owner="instrument")


class _Seal:
    def __init__(self, cid):
        self.cid = cid
        self.source_cid = "source"
        self.start = 0
        self.end = 1


class _Span:
    def __init__(self, line):
        self.start_line = line
        self.start_col = 0
        self.end_line = line
        self.end_col = 1


class _Site:
    """A source fragment as the reads key it: its seal for the sugar's own
    term, and a source coordinate (``source_cid`` and a span) for the
    occurrence an undecided read is keyed by (``occurrence.named_site_cid``).
    Since #9092 a recorded field's read on an instance with no class term is
    the dispatched read, which keys its undecided read by the site: a site
    naming no coordinate is refused by name there."""

    _lines: dict = {}

    def __init__(self, cid):
        self._seal = _Seal(cid)
        self.source_cid = "source"
        self.line_col_span = _Span(self._lines.setdefault(cid, len(self._lines) + 1))

    def seal(self):
        return self._seal


def test_named_int_constant_name_with_no_class_is_never_the_field_outright() -> None:
    # No class statement: no class term guards the read by prove's
    # ``python:plain_read``, so the recorded field is never read outright
    # (a ``__getattribute__`` or a data descriptor may answer it): the read
    # keeps a halting face (#7757).
    from sugar_lift_py_tests.outcome import Completed

    receiver = ObjectValue(
        "re._constants._NamedIntConstant",
        (ObjectField("name", StringValue("SRE_FLAG_ASCII")),),
        allocation=FRAME_FRESH,
    )
    first = AttributeSugar(_ReceiverSugar(receiver), "name", _Site("first"))
    outcome = first.desugar()
    assert type(outcome) is ExitSet
    assert outcome.halts(), outcome
    assert not [
        arm
        for arm in outcome.exits
        if isinstance(arm, Completed) and arm.value == StringValue("SRE_FLAG_ASCII")
    ], outcome
    second = AttributeSugar(_ReceiverSugar(receiver), "name", _Site("second"))
    assert first.to_term(owner="test") != second.to_term(owner="test")


def test_named_int_constant_foreign_member_is_the_undecided_read() -> None:
    # No class statement: no class is named, so not even prove's walk of the
    # order decides the read -- never AttributeError, never a panic.
    receiver = ObjectValue(
        "re._constants._NamedIntConstant",
        (ObjectField("name", StringValue("SRE_FLAG_ASCII")),),
        allocation=FRAME_FRESH,
    )
    outcome = receiver.attribute("foreign", "foreign-site", None)
    (halt,) = outcome.halts()
    assert isinstance(halt.effect, UndeterminedRaiseEffect)
    assert halt.effect.producer_node_owner == "ObjectValue.attribute"
    assert outcome.owed_items()
