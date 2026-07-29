"""Bounded consumer instrument for authenticated ``_NamedIntConstant.name``."""

from sugar_lift_py_tests.floor.object_value import ObjectField, ObjectValue
from sugar_lift_py_tests.floor.string_value import StringValue
from sugar_lift_py_tests.outcome import Complete
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.fragment import SourceFragment
import pytest


def test_named_int_constant_name_uses_object_field_owner() -> None:
    receiver = ObjectValue(
        "re._constants._NamedIntConstant",
        (ObjectField("name", StringValue("SRE_FLAG_ASCII")),),
    )
    outcome = receiver.attribute("name", SourceFragment)
    assert type(outcome) is Complete
    assert outcome.value == StringValue("SRE_FLAG_ASCII")


def test_named_int_constant_foreign_member_stays_typed_loud() -> None:
    receiver = ObjectValue(
        "re._constants._NamedIntConstant",
        (ObjectField("name", StringValue("SRE_FLAG_ASCII")),),
    )
    with pytest.raises(SugarNotWritten, match="ObjectValue.attribute"):
        receiver.attribute("foreign", SourceFragment)
