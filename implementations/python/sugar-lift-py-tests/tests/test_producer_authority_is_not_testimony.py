"""A producer-authority token on a frozen value is never testimony.

Values minted only by their producer carry a private ``object()`` sentinel in
``_authority``. Walking that field made constructed-value testimony refuse
with ``unclassified constructed value category builtins.object`` (pandas
``tests/series/accessors/test_dt_accessor.py:197`` via
``ImportedCallValueSubsumptionV1``). Every such field is declared
``metadata={"testimony": "authority"}``, as ``TupleCoordinateValue`` already
was, so the content coordinate is the semantic fields alone.
"""

from __future__ import annotations

from dataclasses import fields

import pytest

from sugar_lift_py_tests.context_manager_resolution import (
    ImportedCallValueSubsumptionV1,
)
from sugar_lift_py_tests.floor.import_member_value import ImportMemberValue
from sugar_source_tree.binding_state import constructed_value_cid_v2
from sugar_source_tree import nodes



def _authority_classes():
    from sugar_lift_py_tests import import_binding

    found = [ImportedCallValueSubsumptionV1, ImportMemberValue]
    for module in (nodes, import_binding):
        for value in vars(module).values():
            if isinstance(value, type) and value.__module__ == module.__name__:
                if any(f.name == "_authority" for f in getattr(value, "__dataclass_fields__", {}).values()):
                    found.append(value)
    return found


@pytest.mark.parametrize("cls", _authority_classes(), ids=lambda c: c.__qualname__)
def test_every_authority_field_is_declared_non_testimony(cls):
    authority = next(f for f in fields(cls) if f.name == "_authority")
    assert authority.metadata.get("testimony") == "authority"



def test_a_sealed_authority_token_does_not_enter_the_content_coordinate():
    from dataclasses import dataclass, field

    @dataclass(frozen=True)
    class Sealed:
        name: str
        _authority: object = field(
            default=None, compare=False, metadata={"testimony": "authority"}
        )

    assert constructed_value_cid_v2(Sealed("a", object())) == constructed_value_cid_v2(
        Sealed("a", object())
    )
    assert constructed_value_cid_v2(Sealed("a", object())) != constructed_value_cid_v2(
        Sealed("b", object())
    )
