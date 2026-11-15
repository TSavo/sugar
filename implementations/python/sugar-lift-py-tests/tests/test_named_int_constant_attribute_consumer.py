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


class _Site:
    def __init__(self, cid):
        self._seal = _Seal(cid)

    def seal(self):
        return self._seal


def test_named_int_constant_name_uses_object_field_owner() -> None:
    receiver = ObjectValue(
        "re._constants._NamedIntConstant",
        (ObjectField("name", StringValue("SRE_FLAG_ASCII")),),
        allocation=FRAME_FRESH,
    )
    first = AttributeSugar(_ReceiverSugar(receiver), "name", _Site("first"))
    outcome = first.desugar()
    assert type(outcome) is ExitSet
    assert outcome.completed_value() == StringValue("SRE_FLAG_ASCII")
    second = AttributeSugar(_ReceiverSugar(receiver), "name", _Site("second"))
    assert first.to_term(owner="test") != second.to_term(owner="test")


def test_named_int_constant_foreign_member_is_the_undecided_read() -> None:
    # No class statement: the receiver's MRO is not read, so Python's absence
    # rule does not decide the read -- never AttributeError, never a panic.
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
