from __future__ import annotations

from dataclasses import replace

import pytest

from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.floor.decorated_class_value import (
    DecoratedClassMemberValue,
    DecoratedClassPublicationV1,
    DecoratedClassValue,
    DecoratorApplicationPublicationV1,
)
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar


SOURCE = "blake3-512:" + "11" * 64


def _publication():
    raw = TermValue("raw-class")
    replaced = TermValue("replacement-class")
    final = TermValue("published-class")
    first = DecoratorApplicationPublicationV1.mint(
        occurrence=SourceFragmentCoordinateV1(SOURCE, 2, 1, 2, 17),
        callable_floor=TermValue("replace-class"),
        input_floor=raw,
        output_floor=replaced,
    )
    second = DecoratorApplicationPublicationV1.mint(
        occurrence=SourceFragmentCoordinateV1(SOURCE, 1, 1, 1, 16),
        callable_floor=TermValue("publish-members"),
        input_floor=replaced,
        output_floor=final,
    )
    publication = DecoratedClassPublicationV1.mint(
        source_cid=SOURCE,
        definition=SourceFragmentCoordinateV1(SOURCE, 3, 0, 5, 9),
        binding_occurrence=SourceFragmentCoordinateV1(SOURCE, 3, 6, 3, 13),
        raw_class=raw,
        decorator_applications=(first, second),
        final_class=final,
        module_construction_receipt_cid="blake3-512:" + "22" * 64,
    )
    return publication, raw, replaced, final, first, second


def test_replacing_decorator_publication_ties_member_to_final_class() -> None:
    publication, _, _, final, _, _ = _publication()
    class_value = DecoratedClassValue(publication)
    member = DecoratedClassMemberValue.mint(
        publication=publication,
        member_definition=SourceFragmentCoordinateV1(SOURCE, 4, 4, 4, 10),
        member_floor=TermValue("member"),
    )

    result = class_value.test_python_type(member, object())

    assert isinstance(result, Complete)
    assert isinstance(result.value, TrueBoolLiteralSugar)
    assert class_value.published_floor is final
    assert member.publication_cid == publication.publication_cid


@pytest.mark.parametrize("variant", ("swapped", "omitted", "duplicated", "raw"))
def test_publication_refuses_decorator_chain_reconstruction(variant: str) -> None:
    publication, raw, _, final, first, second = _publication()
    applications = {
        "swapped": (second, first),
        "omitted": (second,),
        "duplicated": (first, first, second),
        "raw": publication.decorator_applications,
    }[variant]
    kwargs = {"decorator_applications": applications}
    if variant == "raw":
        kwargs["final_class"] = raw

    with pytest.raises(ValueError, match="decorated class publication"):
        DecoratedClassPublicationV1.mint(
            source_cid=publication.source_cid,
            definition=publication.definition,
            binding_occurrence=publication.binding_occurrence,
            raw_class=raw,
            decorator_applications=kwargs["decorator_applications"],
            final_class=kwargs.get("final_class", final),
            module_construction_receipt_cid=publication.module_construction_receipt_cid,
        )


def test_member_refuses_cross_wired_publication() -> None:
    publication, *_ = _publication()
    foreign = replace(
        publication,
        publication_cid="blake3-512:" + "99" * 64,
    )

    with pytest.raises(ValueError, match="publication CID"):
        DecoratedClassMemberValue.mint(
            publication=foreign,
            member_definition=SourceFragmentCoordinateV1(SOURCE, 4, 4, 4, 10),
            member_floor=TermValue("member"),
        )
