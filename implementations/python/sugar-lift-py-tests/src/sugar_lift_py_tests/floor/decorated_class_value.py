from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_python_source.canonical import cid_of_json

from .floor_value import FloorValue


_APPLICATION_AUTHORITY = object()
_PUBLICATION_AUTHORITY = object()
_MEMBER_AUTHORITY = object()
_METACLASS_AUTHORITY = object()


def _floor_cid(value: FloorValue) -> str:
    from sugar_lift_py_tests.ir import _term_content_cid

    if not isinstance(value, FloorValue):
        raise ValueError("decorated class publication requires Floor values")
    return _term_content_cid(value.to_term(owner="decorated class publication"))


@dataclass(frozen=True)
class DecoratorApplicationPublicationV1:
    occurrence: object
    callable_floor: FloorValue = field(compare=False)
    input_floor: FloorValue = field(compare=False)
    output_floor: FloorValue = field(compare=False)
    callable_floor_cid: str
    input_floor_cid: str
    output_floor_cid: str
    application_cid: str
    _authority: object = field(default=None, compare=False, repr=False)

    @classmethod
    def mint(cls, *, occurrence, callable_floor, input_floor, output_floor):
        from sugar_lift_py_tests.context_manager_resolution import (
            SourceFragmentCoordinateV1,
        )

        if type(occurrence) is not SourceFragmentCoordinateV1:
            raise ValueError("decorated class publication requires typed occurrence")
        callable_cid = _floor_cid(callable_floor)
        input_cid = _floor_cid(input_floor)
        output_cid = _floor_cid(output_floor)
        application_cid = cid_of_json(
            {
                "kind": "decorated-class-application",
                "schemaVersion": "1",
                "occurrence": occurrence.wire(),
                "callableFloorCid": callable_cid,
                "inputFloorCid": input_cid,
                "outputFloorCid": output_cid,
            }
        )
        value = cls(
            occurrence,
            callable_floor,
            input_floor,
            output_floor,
            callable_cid,
            input_cid,
            output_cid,
            application_cid,
            _APPLICATION_AUTHORITY,
        )
        return value

    def __post_init__(self):
        if getattr(self, "_authority", None) is not _APPLICATION_AUTHORITY:
            raise ValueError("decorated class publication application is not producer-minted")
        callable_cid = _floor_cid(self.callable_floor)
        input_cid = _floor_cid(self.input_floor)
        output_cid = _floor_cid(self.output_floor)
        application_cid = cid_of_json({"kind": "decorated-class-application", "schemaVersion": "1", "occurrence": self.occurrence.wire(), "callableFloorCid": callable_cid, "inputFloorCid": input_cid, "outputFloorCid": output_cid})
        if (
            self.callable_floor_cid != callable_cid
            or self.input_floor_cid != input_cid
            or self.output_floor_cid != output_cid
            or self.application_cid != application_cid
        ):
            raise ValueError("decorated class publication application CID mismatch")


@dataclass(frozen=True)
class DecoratedClassPublicationV1:
    source_cid: str
    definition: object
    binding_occurrence: object
    raw_class: FloorValue = field(compare=False)
    decorator_applications: tuple[DecoratorApplicationPublicationV1, ...]
    final_class: FloorValue = field(compare=False)
    module_construction_receipt_cid: str
    binding_occurrence_cid: str
    raw_class_cid: str
    final_class_cid: str
    publication_cid: str
    _authority: object = field(default=None, compare=False, repr=False)

    @classmethod
    def mint(
        cls,
        *,
        source_cid,
        definition,
        binding_occurrence,
        raw_class,
        decorator_applications,
        final_class,
        module_construction_receipt_cid,
    ):
        from sugar_lift_py_tests.context_manager_resolution import (
            SourceFragmentCoordinateV1,
        )
        from sugar_lift_py_tests.floor.class_definition_value import (
            ClassDefinitionValue,
        )

        if (
            type(definition) is not SourceFragmentCoordinateV1
            or type(binding_occurrence) is not SourceFragmentCoordinateV1
            or definition.source_cid != source_cid
            or binding_occurrence.source_cid != source_cid
        ):
            raise ValueError("decorated class publication source coordinate mismatch")
        if (
            type(raw_class) is not ClassDefinitionValue
            or type(raw_class.binding_target_occurrence)
            is not SourceFragmentCoordinateV1
            or raw_class.binding_target_occurrence != binding_occurrence
            or raw_class.binding_target_occurrence.cid != binding_occurrence.cid
        ):
            raise ValueError("decorated class publication binding target mismatch")
        applications = tuple(decorator_applications)
        current = raw_class
        for application in applications:
            if (
                type(application) is not DecoratorApplicationPublicationV1
                or application.occurrence.source_cid != source_cid
                or application.input_floor is not current
            ):
                raise ValueError("decorated class publication decorator chain mismatch")
            current = application.output_floor
        if current is not final_class:
            raise ValueError("decorated class publication final result mismatch")
        raw_cid = _floor_cid(raw_class)
        final_cid = _floor_cid(final_class)
        publication_cid = cid_of_json(
            {
                "kind": "decorated-class-publication",
                "schemaVersion": "1",
                "sourceCid": source_cid,
                "definition": definition.wire(),
                "bindingOccurrence": binding_occurrence.wire(),
                "rawClassCid": raw_cid,
                "decoratorApplications": [a.application_cid for a in applications],
                "finalClassCid": final_cid,
                "moduleConstructionReceiptCid": module_construction_receipt_cid,
            }
        )
        value = cls(
            source_cid,
            definition,
            binding_occurrence,
            raw_class,
            applications,
            final_class,
            module_construction_receipt_cid,
            binding_occurrence.cid,
            raw_cid,
            final_cid,
            publication_cid,
            _PUBLICATION_AUTHORITY,
        )
        return value

    def __post_init__(self):
        from sugar_lift_py_tests.context_manager_resolution import (
            SourceFragmentCoordinateV1,
        )
        from sugar_lift_py_tests.floor.class_definition_value import (
            ClassDefinitionValue,
        )

        if getattr(self, "_authority", None) is not _PUBLICATION_AUTHORITY:
            raise ValueError("decorated class publication is not producer-minted")
        if (
            self.binding_occurrence_cid != self.binding_occurrence.cid
            or type(self.raw_class) is not ClassDefinitionValue
            or type(self.raw_class.binding_target_occurrence)
            is not SourceFragmentCoordinateV1
            or self.raw_class.binding_target_occurrence != self.binding_occurrence
            or self.raw_class.binding_target_occurrence.cid
            != self.binding_occurrence_cid
        ):
            raise ValueError("decorated class publication binding target mismatch")
        current = self.raw_class
        for application in self.decorator_applications:
            if application.input_floor is not current:
                raise ValueError("decorated class publication decorator chain mismatch")
            current = application.output_floor
        if current is not self.final_class:
            raise ValueError("decorated class publication final result mismatch")
        raw_cid = _floor_cid(self.raw_class)
        final_cid = _floor_cid(self.final_class)
        publication_cid = cid_of_json({"kind": "decorated-class-publication", "schemaVersion": "1", "sourceCid": self.source_cid, "definition": self.definition.wire(), "bindingOccurrence": self.binding_occurrence.wire(), "rawClassCid": raw_cid, "decoratorApplications": [a.application_cid for a in self.decorator_applications], "finalClassCid": final_cid, "moduleConstructionReceiptCid": self.module_construction_receipt_cid})
        if (
            self.raw_class_cid != raw_cid
            or self.final_class_cid != final_cid
            or self.publication_cid != publication_cid
        ):
            raise ValueError("decorated class publication CID mismatch")


@dataclass(frozen=True)
class DecoratedClassValue(FloorValue):
    publication: DecoratedClassPublicationV1

    @property
    def binding_cid(self):
        return self.publication.publication_cid

    @property
    def published_floor(self):
        return self.publication.final_class

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:decorated_class_publication",
            [str_const(self.publication.publication_cid)],
            symbol_kind="coordinate",
        )

    def test_python_type(self, value, site):
        if (
            type(value) is DecoratedClassMemberValue
            and value.publication_cid == self.publication.publication_cid
            and value.publication is self.publication
        ):
            from sugar_lift_py_tests.outcome import Complete
            from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
                TrueBoolLiteralSugar,
            )

            return Complete(TrueBoolLiteralSugar(site=site))
        return super().test_python_type(value, site)


@dataclass(frozen=True, init=False)
class MetaclassClassPublicationV1:
    """One exact metaclass application during module class publication."""

    source_cid: str
    definition: object
    binding_occurrence: object
    metaclass_occurrence: object
    raw_class: FloorValue = field(compare=False)
    metaclass_floor: FloorValue = field(compare=False)
    metaclass_callable: FloorValue = field(compare=False)
    class_name_floor: FloorValue = field(compare=False)
    bases_floor: FloorValue = field(compare=False)
    namespace_floor: FloorValue = field(compare=False)
    final_class: FloorValue = field(compare=False)
    module_construction_receipt_cid: str
    application_cid: str
    publication_cid: str
    _authority: object = field(default=None, init=False, compare=False, repr=False)

    def __post_init__(self):
        from sugar_lift_py_tests.context_manager_resolution import (
            SourceFragmentCoordinateV1,
        )
        from sugar_lift_py_tests.floor.class_definition_value import (
            ClassDefinitionValue,
        )

        if self._authority is not _METACLASS_AUTHORITY:
            raise ValueError("metaclass class publication is not producer-minted")
        if (
            type(self.definition) is not SourceFragmentCoordinateV1
            or type(self.binding_occurrence) is not SourceFragmentCoordinateV1
            or type(self.metaclass_occurrence) is not SourceFragmentCoordinateV1
            or self.definition.source_cid != self.source_cid
            or self.binding_occurrence.source_cid != self.source_cid
            or self.metaclass_occurrence.source_cid != self.source_cid
            or type(self.raw_class) is not ClassDefinitionValue
            or self.raw_class.binding_target_occurrence != self.binding_occurrence
        ):
            raise ValueError("metaclass class publication coordinate mismatch")
        application_cid, publication_cid = _metaclass_publication_cids(
            source_cid=self.source_cid,
            definition=self.definition,
            binding_occurrence=self.binding_occurrence,
            metaclass_occurrence=self.metaclass_occurrence,
            raw_class=self.raw_class,
            metaclass_floor=self.metaclass_floor,
            metaclass_callable=self.metaclass_callable,
            class_name_floor=self.class_name_floor,
            bases_floor=self.bases_floor,
            namespace_floor=self.namespace_floor,
            final_class=self.final_class,
            module_construction_receipt_cid=self.module_construction_receipt_cid,
        )
        if (
            self.application_cid != application_cid
            or self.publication_cid != publication_cid
        ):
            raise ValueError("metaclass class publication CID mismatch")


def _metaclass_publication_cids(
    *,
    source_cid,
    definition,
    binding_occurrence,
    metaclass_occurrence,
    raw_class,
    metaclass_floor,
    metaclass_callable,
    class_name_floor,
    bases_floor,
    namespace_floor,
    final_class,
    module_construction_receipt_cid,
):
    application_cid = cid_of_json(
        {
            "kind": "metaclass-class-application",
            "schemaVersion": "1",
            "occurrence": metaclass_occurrence.wire(),
            "metaclassFloorCid": _floor_cid(metaclass_floor),
            "metaclassCallableCid": _floor_cid(metaclass_callable),
            "actualFloorCids": [
                _floor_cid(metaclass_floor),
                _floor_cid(class_name_floor),
                _floor_cid(bases_floor),
                _floor_cid(namespace_floor),
            ],
            "resultFloorCid": _floor_cid(final_class),
        }
    )
    publication_cid = cid_of_json(
        {
            "kind": "metaclass-class-publication",
            "schemaVersion": "1",
            "sourceCid": source_cid,
            "definition": definition.wire(),
            "bindingOccurrence": binding_occurrence.wire(),
            "rawClassCid": _floor_cid(raw_class),
            "applicationCid": application_cid,
            "moduleConstructionReceiptCid": module_construction_receipt_cid,
        }
    )
    return application_cid, publication_cid


def _mint_metaclass_class_publication(
    *,
    source_cid,
    definition,
    binding_occurrence,
    metaclass_occurrence,
    raw_class,
    metaclass_floor,
    metaclass_callable,
    class_name_floor,
    bases_floor,
    namespace_floor,
    final_class,
    module_construction_receipt_cid,
):
    application_cid, publication_cid = _metaclass_publication_cids(
        source_cid=source_cid,
        definition=definition,
        binding_occurrence=binding_occurrence,
        metaclass_occurrence=metaclass_occurrence,
        raw_class=raw_class,
        metaclass_floor=metaclass_floor,
        metaclass_callable=metaclass_callable,
        class_name_floor=class_name_floor,
        bases_floor=bases_floor,
        namespace_floor=namespace_floor,
        final_class=final_class,
        module_construction_receipt_cid=module_construction_receipt_cid,
    )
    value = object.__new__(MetaclassClassPublicationV1)
    for name, field_value in (
        ("source_cid", source_cid),
        ("definition", definition),
        ("binding_occurrence", binding_occurrence),
        ("metaclass_occurrence", metaclass_occurrence),
        ("raw_class", raw_class),
        ("metaclass_floor", metaclass_floor),
        ("metaclass_callable", metaclass_callable),
        ("class_name_floor", class_name_floor),
        ("bases_floor", bases_floor),
        ("namespace_floor", namespace_floor),
        ("final_class", final_class),
        ("module_construction_receipt_cid", module_construction_receipt_cid),
        ("application_cid", application_cid),
        ("publication_cid", publication_cid),
    ):
        object.__setattr__(value, name, field_value)
    object.__setattr__(value, "_authority", _METACLASS_AUTHORITY)
    value.__post_init__()
    return value


@dataclass(frozen=True)
class MetaclassClassValue(FloorValue):
    publication: MetaclassClassPublicationV1

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:metaclass_class_publication",
            [str_const(self.publication.publication_cid)],
            symbol_kind="coordinate",
        )


@dataclass(frozen=True)
class DecoratedClassMemberValue(FloorValue):
    publication: DecoratedClassPublicationV1 = field(compare=False)
    member_definition: object
    member_floor: FloorValue = field(compare=False)
    member_floor_cid: str
    publication_cid: str
    member_cid: str
    _authority: object = field(default=None, compare=False, repr=False)

    @classmethod
    def mint(cls, *, publication, member_definition, member_floor):
        from sugar_lift_py_tests.context_manager_resolution import (
            SourceFragmentCoordinateV1,
        )

        if (
            type(publication) is not DecoratedClassPublicationV1
            or type(member_definition) is not SourceFragmentCoordinateV1
            or member_definition.source_cid != publication.source_cid
        ):
            raise ValueError("decorated class member publication source mismatch")
        floor_cid = _floor_cid(member_floor)
        member_cid = cid_of_json(
            {
                "kind": "decorated-class-member-publication",
                "schemaVersion": "1",
                "publicationCid": publication.publication_cid,
                "memberDefinition": member_definition.wire(),
                "memberFloorCid": floor_cid,
            }
        )
        value = cls(
            publication,
            member_definition,
            member_floor,
            floor_cid,
            publication.publication_cid,
            member_cid,
            _MEMBER_AUTHORITY,
        )
        return value

    def __post_init__(self):
        if getattr(self, "_authority", None) is not _MEMBER_AUTHORITY:
            raise ValueError("decorated class member is not producer-minted")
        if self.publication_cid != self.publication.publication_cid:
            raise ValueError("decorated class member publication CID mismatch")
        floor_cid = _floor_cid(self.member_floor)
        member_cid = cid_of_json({"kind": "decorated-class-member-publication", "schemaVersion": "1", "publicationCid": self.publication.publication_cid, "memberDefinition": self.member_definition.wire(), "memberFloorCid": floor_cid})
        if self.member_floor_cid != floor_cid or self.member_cid != member_cid:
            raise ValueError("decorated class member CID mismatch")

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:decorated_class_member",
            [str_const(self.member_cid)],
            symbol_kind="coordinate",
        )
