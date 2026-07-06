from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.factory import (
    FactoryAuditRow,
    FactoryGap,
    FactoryGapInfo,
    GapKind,
    GapLocus,
)
from sugar_lift_py_tests.floor import ObjectField, ObjectMethodValue, ObjectValue
from sugar_lift_py_tests.floor.call_site_value import _ctx_with_curried_args
from sugar_lift_py_tests.outcome import Complete, Incomplete, Outcome, complete_value
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class ConstructorStrategy:
    class_name: str
    fields: tuple[tuple[str, SugarBody], ...]
    parameters: tuple[str, ...] = ()
    arguments: tuple[SugarBody, ...] = ()
    methods: tuple[ObjectMethodValue, ...] = ()
    class_fields: tuple[tuple[str, SugarBody], ...] = ()
    identity: str = ""

    def __post_init__(self) -> None:
        for _name, body in self.fields:
            if not isinstance(body, SugarBody):
                raise TypeError("ConstructorStrategy fields must be factory-built")
        for _name, body in self.class_fields:
            if not isinstance(body, SugarBody):
                raise TypeError(
                    "ConstructorStrategy class fields must be factory-built"
                )
        for argument in self.arguments:
            if not isinstance(argument, SugarBody):
                raise TypeError("ConstructorStrategy arguments must be factory-built")
        for method in self.methods:
            if not isinstance(method, ObjectMethodValue):
                raise TypeError("ConstructorStrategy methods must be factory-built")

    def emit(self, sugar, ctx) -> Outcome:
        del sugar
        arg_values = []
        for argument in self.arguments:
            argument_outcome = argument.reduce(ctx)
            if isinstance(argument_outcome, Incomplete):
                return argument_outcome
            arg_values.append(
                complete_value(
                    argument_outcome,
                    owner=f"{self.class_name} constructor argument",
                )
            )
        field_ctx = _ctx_with_curried_args(ctx, self.parameters, tuple(arg_values))
        return Complete(
            ObjectValue(
                class_name=self.class_name,
                fields=tuple(
                    self._field(name, body, field_ctx) for name, body in self.fields
                ),
                methods=self.methods,
                class_fields=tuple(
                    self._class_field(name, body, ctx)
                    for name, body in self.class_fields
                ),
                identity=self.identity,
            )
        )

    def _field(self, name: str, body: SugarBody, ctx) -> ObjectField:
        try:
            value = complete_value(
                body.reduce(ctx),
                owner=f"{self.class_name}.{name}",
            )
        except TypeError as exc:
            info = FactoryGapInfo(
                owner="python.factory",
                blame=f"{self.class_name}.{name}",
                observed=type(exc).__name__,
                requested="constructor field floor",
                fix=f"write more constructor floor for `{self.class_name}.{name}`: {exc}",
                gap_kind=GapKind.CONSTRUCTOR,
                gap_locus=GapLocus.CONSTRUCTION,
            )
            raise FactoryGap(
                info,
                FactoryAuditRow(
                    role="constructor field floor",
                    status="floor-gap",
                    observed=info.observed,
                    blame=info.blame,
                    selected=None,
                    candidates=[],
                    message=info.message,
                ),
            ) from exc
        return ObjectField(name=name, value=value)

    def _class_field(self, name: str, body: SugarBody, ctx) -> ObjectField:
        value = complete_value(
            body.reduce(ctx),
            owner=f"{self.class_name}.{name}",
        )
        if isinstance(value, ObjectValue) and value.has_method("__set_name__"):
            info = FactoryGapInfo(
                owner="python.factory",
                blame=f"{self.class_name}.{name}",
                observed=f"{self.class_name}.{name}",
                requested="class descriptor __set_name__ effect",
                fix=(
                    f"add class-construction descriptor wiring for "
                    f"`{self.class_name}.{name}` or emit an explicit "
                    "__set_name__ effect"
                ),
                gap_kind=GapKind.CONSTRUCTOR,
                gap_locus=GapLocus.CONSTRUCTION,
            )
            raise FactoryGap(
                info,
                FactoryAuditRow(
                    role="class descriptor __set_name__ effect",
                    status="floor-gap",
                    observed=info.observed,
                    blame=info.blame,
                    selected=None,
                    candidates=[],
                    message=info.message,
                ),
            )
        return ObjectField(name=name, value=value)
