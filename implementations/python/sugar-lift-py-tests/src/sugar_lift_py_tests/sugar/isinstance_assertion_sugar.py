from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.ir import (
    Formula,
    Term,
    _ConstBool,
    _ConstInt,
    _ConstStr,
    atomic,
    bool_const,
    eq,
    or_,
    str_const,
)
from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.outcome import Incomplete
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witness_examples import isinstance_assertion_witness
from sugar_lift_py_tests.sugar.symbolic_term import symbolic_term


@dataclass(frozen=True)
class IsInstanceAssertionSugar(Sugar, role=SugarRole.ASSERTION):
    source_role = "python.isinstance-assertion-sugar"

    subject: Term
    type_names: tuple[str, ...]
    classinfo_effect: RuntimeEffect | None = None

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Assert":
            return False
        test = site.assert_test()
        return (
            test.observed == "Call"
            and test.call_target_name() == "isinstance"
            and not test.call_has_keywords()
            and test.call_arg_count() == 2
        )

    @classmethod
    def witnesses(cls):
        return isinstance_assertion_witness()

    @classmethod
    def build(cls, site, ctx) -> "IsInstanceAssertionSugar":
        test = site.assert_test()
        subject, type_expr = test.call_args()
        type_names = _type_expr_names_or_effect(type_expr)
        return cls(
            subject=symbolic_term(
                subject,
                owner="isinstance subject",
                import_aliases=ctx.import_aliases or {},
                from_imports=ctx.from_imports or {},
                name_resolver=ctx.name_resolver or {},
                external_bridge_sink=ctx.external_bridge_sink,
            ),
            type_names=() if isinstance(type_names, RuntimeEffect) else type_names,
            classinfo_effect=(
                type_names if isinstance(type_names, RuntimeEffect) else None
            ),
        )

    def assertion_formula(self) -> Formula:
        concrete_values = [
            _concrete_isinstance(self.subject, type_name)
            for type_name in self.type_names
        ]
        if concrete_values and all(value is not None for value in concrete_values):
            return eq(bool_const(any(concrete_values)), bool_const(True))
        if not self.type_names:
            return eq(bool_const(False), bool_const(True))

        formulas = [
            atomic("is_type", [self.subject, str_const(type_name)])
            for type_name in self.type_names
        ]
        if len(formulas) == 1:
            return formulas[0]
        return or_(formulas)

    def desugar(self, ctx):
        del ctx
        if self.classinfo_effect is not None:
            return Incomplete(self.classinfo_effect)
        return self.assertion_formula()


def _type_expr_names_or_effect(site) -> tuple[str, ...] | RuntimeEffect:
    if site.observed == "Name":
        return (site.name_id(),)
    if site.observed == "Attribute":
        receiver = _type_expr_names_or_effect(site.attr_receiver())
        if isinstance(receiver, RuntimeEffect):
            return receiver
        if len(receiver) != 1:
            return _runtime_classinfo_effect(site)
        return (f"{receiver[0]}.{site.attr_name()}",)
    if site.observed == "Tuple":
        names: list[str] = []
        for item in site.terms():
            item_names = _type_expr_names_or_effect(item)
            if isinstance(item_names, RuntimeEffect):
                return item_names
            names.extend(item_names)
        return tuple(names)
    return _runtime_classinfo_effect(site)


def _runtime_classinfo_effect(site) -> RuntimeEffect:
    return RuntimeEffect(
        "isinstance classinfo runtime boundary; "
        f"observed={site.observed} blame={site.blame}; "
        "replacement=use an addressable type or tuple of addressable types, "
        "or add cited runtime classinfo sugar"
    )


def _concrete_isinstance(subject: Term, type_name: str) -> bool | None:
    if isinstance(subject, _ConstBool):
        return type_name in {"bool", "int"}
    if isinstance(subject, _ConstInt):
        return type_name == "int"
    if isinstance(subject, _ConstStr):
        return type_name == "str"
    return None
