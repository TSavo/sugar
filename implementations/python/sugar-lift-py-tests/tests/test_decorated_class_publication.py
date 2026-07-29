from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1
from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.floor import SymbolicValue
from sugar_lift_py_tests.floor.decorated_class_value import (
    DecoratedClassMemberValue,
    DecoratedClassPublicationV1,
    DecoratedClassValue,
    DecoratorApplicationPublicationV1,
)
from sugar_lift_py_tests.ir import _Var
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.source_call_frame import DecoratedClassBindingV1
from sugar_lift_py_tests.sugar.call_site_sugar import _with_frame_mutable_globals
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_source_tree.tree import SourceFile


def _publication(tmp_path: Path, monkeypatch, *, stem: str = "publication"):
    monkeypatch.chdir(tmp_path)
    path = Path(f"{stem}.py")
    path.write_text("class Published:\n    member = 1\n", encoding="utf-8")
    source_file = SourceFile.from_path(path)
    source = source_file.unit.source_cid
    raw = SymbolicValue(_Var("raw_class"))
    replaced = SymbolicValue(_Var("replacement_class"))
    final = SymbolicValue(_Var("published_class"))
    first = DecoratorApplicationPublicationV1.mint(
        occurrence=SourceFragmentCoordinateV1(source, 2, 1, 2, 17),
        callable_floor=SymbolicValue(_Var("replace_class")),
        input_floor=raw,
        output_floor=replaced,
    )
    second = DecoratorApplicationPublicationV1.mint(
        occurrence=SourceFragmentCoordinateV1(source, 1, 1, 1, 16),
        callable_floor=SymbolicValue(_Var("publish_members")),
        input_floor=replaced,
        output_floor=final,
    )
    publication = DecoratedClassPublicationV1.mint(
        source_cid=source,
        definition=SourceFragmentCoordinateV1(source, 3, 0, 5, 9),
        binding_occurrence=SourceFragmentCoordinateV1(source, 3, 6, 3, 13),
        raw_class=raw,
        decorator_applications=(first, second),
        final_class=final,
        module_construction_receipt_cid=source_file.construction_event_receipt_cid,
    )
    return publication, raw, replaced, final, first, second, source_file


def test_replacing_decorator_publication_ties_member_to_final_class(
    tmp_path: Path, monkeypatch
) -> None:
    publication, _, _, final, _, _, _ = _publication(tmp_path, monkeypatch)
    class_value = DecoratedClassValue(publication)
    member = DecoratedClassMemberValue.mint(
        publication=publication,
        member_definition=SourceFragmentCoordinateV1(
            publication.source_cid, 4, 4, 4, 10
        ),
        member_floor=SymbolicValue(_Var("member")),
    )

    result = class_value.test_python_type(member, object())

    assert isinstance(result, Complete)
    assert isinstance(result.value, TrueBoolLiteralSugar)
    assert class_value.published_floor is final
    assert member.publication_cid == publication.publication_cid


@pytest.mark.parametrize("variant", ("swapped", "omitted", "duplicated", "raw"))
def test_publication_refuses_decorator_chain_reconstruction(
    variant: str, tmp_path: Path, monkeypatch
) -> None:
    publication, raw, _, final, first, second, _ = _publication(
        tmp_path, monkeypatch
    )
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


def test_member_refuses_cross_wired_publication(tmp_path: Path, monkeypatch) -> None:
    publication, *_ = _publication(tmp_path, monkeypatch, stem="truthful")
    foreign, *_ = _publication(tmp_path, monkeypatch, stem="foreign")
    with pytest.raises(ValueError, match="publication CID"):
        replace(
            publication,
            publication_cid=foreign.publication_cid,
        )


def test_frame_transports_exact_published_class_and_member_into_module_temporal(
    tmp_path: Path, monkeypatch
) -> None:
    publication, *_ = _publication(tmp_path, monkeypatch)
    class_value = DecoratedClassValue(publication)
    member = DecoratedClassMemberValue.mint(
        publication=publication,
        member_definition=SourceFragmentCoordinateV1(
            publication.source_cid, 4, 4, 4, 10
        ),
        member_floor=SymbolicValue(_Var("member")),
    )
    bindings = (
        DecoratedClassBindingV1("Published", publication, class_value),
        DecoratedClassBindingV1("EXPORTED", publication, member),
    )
    frame = type(
        "Frame",
        (),
        {
            "source_identity_cid": publication.source_cid,
            "mutable_global_bindings": (),
            "decorated_class_bindings": bindings,
        },
    )()

    ctx = _with_frame_mutable_globals(ReduceContext.root(owner="test"), frame)

    assert ctx.temporal.value_for("Published") is class_value
    assert ctx.module_temporal.value_for("Published") is class_value
    assert ctx.temporal.value_for("EXPORTED") is member
