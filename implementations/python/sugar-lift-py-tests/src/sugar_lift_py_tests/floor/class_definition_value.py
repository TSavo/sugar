from __future__ import annotations

from dataclasses import dataclass, field

from sugar_source_tree.panic import SugarNotWritten

from .floor_value import FloorValue


@dataclass(frozen=True)
class ConstructedClassMethodV1:
    name: str
    definition_fragment_cid: str
    body: object = field(compare=False)


@dataclass(frozen=True)
class ClassDefinitionValue(FloorValue):
    class_name: str
    class_definition_cid: str
    methods: tuple[ConstructedClassMethodV1, ...]
    initializer: ConstructedClassMethodV1 | None

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:class-definition",
            [str_const(self.class_definition_cid)],
            symbol_kind="coordinate",
        )

    def construct_receiver_state(self, actuals: tuple[object, ...]):
        del actuals
        raise SugarNotWritten(
            owner="ClassDefinitionValue.construct_receiver_state",
            observed="awaiting-binding-coordinate",
            requested="BindingCoordinateV1 receiver and field projections",
            fix=(
                "wire the shared scope-owner/binding-site/projection-path spine; "
                "never infer receiver fields by name"
            ),
        )
