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
    str_const,
)
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witness_examples import isinstance_assertion_witness
from sugar_lift_py_tests.sugar.symbolic_term import symbolic_term


@dataclass(frozen=True)
class IsInstanceAssertionSugar(Sugar, role=SugarRole.ASSERTION):
    source_role = "python.isinstance-assertion-sugar"

    subject: Term
    type_name: str

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
        return cls(
            subject=symbolic_term(
                subject,
                owner="isinstance subject",
                import_aliases=ctx.import_aliases or {},
                from_imports=ctx.from_imports or {},
                name_resolver=ctx.name_resolver or {},
                external_bridge_sink=ctx.external_bridge_sink,
            ),
            type_name=_type_expr_name(type_expr),
        )

    def assertion_formula(self) -> Formula:
        concrete = _concrete_isinstance(self.subject, self.type_name)
        if concrete is not None:
            return eq(bool_const(concrete), bool_const(True))
        return atomic("is_type", [self.subject, str_const(self.type_name)])

    def desugar(self, ctx):
        del ctx
        return self.assertion_formula()


def _type_expr_name(site) -> str:
    if site.observed == "Name":
        return site.name_id()
    if site.observed == "Attribute":
        return f"{_type_expr_name(site.attr_receiver())}.{site.attr_name()}"
    raise TypeError(
        f"write more Sugar for isinstance type `{site.observed}`: "
        "add a builtin type-expression shape"
    )


def _concrete_isinstance(subject: Term, type_name: str) -> bool | None:
    if isinstance(subject, _ConstBool):
        return type_name in {"bool", "int"}
    if isinstance(subject, _ConstInt):
        return type_name == "int"
    if isinstance(subject, _ConstStr):
        return type_name == "str"
    return None
