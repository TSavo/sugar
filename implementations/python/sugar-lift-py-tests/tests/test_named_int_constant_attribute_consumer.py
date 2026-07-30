"""Bounded consumer instrument for authenticated ``_NamedIntConstant.name``."""

from sugar_lift_py_tests.floor.object_value import ObjectField, ObjectValue
from sugar_lift_py_tests.floor.string_value import StringValue
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.attribute_sugar import AttributeSugar
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
from sugar_source_tree.panic import SugarNotWritten
import pytest


class _ReceiverSugar(ConstructedTermSugar):
    def __init__(self, receiver):
        self.receiver = receiver
        self.site = _Site("receiver")

    @classmethod
    def witnesses(cls):
        raise AssertionError("instrument leaf")

    def desugar(self, ctx=None):
        return Complete(self.receiver)

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
    )
    first = AttributeSugar(_ReceiverSugar(receiver), "name", _Site("first"))
    outcome = first.desugar()
    assert type(outcome) is Complete
    assert outcome.value == StringValue("SRE_FLAG_ASCII")
    second = AttributeSugar(_ReceiverSugar(receiver), "name", _Site("second"))
    assert first.to_term(owner="test") != second.to_term(owner="test")


def test_named_int_constant_foreign_member_stays_typed_loud() -> None:
    receiver = ObjectValue(
        "re._constants._NamedIntConstant",
        (ObjectField("name", StringValue("SRE_FLAG_ASCII")),),
    )
    with pytest.raises(SugarNotWritten, match="ObjectValue.attribute"):
        AttributeSugar(_ReceiverSugar(receiver), "foreign", _Site("foreign")).desugar()
