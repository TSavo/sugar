from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

import pytest

from sugar_lift_py_tests.factory import FactoryGap
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.operations import perform_operation


@dataclass(frozen=True)
class MissingMethodNameOperation:
    owner: str = "test"
    blame: str = "t.py:1:0"


@dataclass(frozen=True)
class TypoedMethodNameOperation:
    method_name: ClassVar[str] = "attribute_wiht"
    owner: str = "test"
    blame: str = "t.py:1:0"


def test_operation_without_method_name_refuses_at_operation_class() -> None:
    with pytest.raises(FactoryGap) as raised:
        perform_operation(
            owner="test",
            blame="t.py:1:0",
            receiver=TermValue(1),
            operation=MissingMethodNameOperation(),
            ctx=object(),
        )

    assert raised.value.info.to_json() == {
        "owner": "test",
        "blame": "t.py:1:0",
        "observed": "MissingMethodNameOperation",
        "requested": "method_name",
        "fix": (
            "declare MissingMethodNameOperation.method_name as a ClassVar[str] "
            "owned by the operation"
        ),
        "gap_kind": "Operation",
        "gap_locus": "method_name",
    }


def test_typoed_operation_method_name_blames_operation_not_receiver() -> None:
    with pytest.raises(FactoryGap) as raised:
        perform_operation(
            owner="test",
            blame="t.py:1:0",
            receiver=TermValue(1),
            operation=TypoedMethodNameOperation(),
            ctx=object(),
        )

    assert raised.value.info.to_json() == {
        "owner": "test",
        "blame": "t.py:1:0",
        "observed": "TypoedMethodNameOperation",
        "requested": "attribute_wiht",
        "fix": (
            "check TypoedMethodNameOperation.method_name or add "
            "TermValue.attribute_wiht"
        ),
        "gap_kind": "Operation",
        "gap_locus": "method_name",
    }
