from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.ir import Formula, Term, atomic, bool_const, ctor, make_var, num, str_const
from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class IsInstanceAssertionSugar(Sugar, role=SugarRole.ASSERTION):
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
    def build(cls, site, ctx) -> "IsInstanceAssertionSugar":
        test = site.assert_test()
        subject, type_expr = test.call_args()
        return cls(
            subject=_subject_term(subject),
            type_name=_type_expr_name(type_expr),
        )

    def assertion_formula(self) -> Formula:
        return atomic("is_type", [self.subject, str_const(self.type_name)])

    def desugar(self, ctx):
        del ctx
        return self.assertion_formula()


def _subject_term(site) -> Term:
    if site.observed == "Name":
        return make_var(site.name_id())
    if site.observed == "PrimitiveLiteral":
        value = site.literal_value()
        if isinstance(value, bool):
            return bool_const(value)
        if isinstance(value, int):
            return num(value)
        if isinstance(value, str):
            return str_const(value)
    if site.observed == "List":
        return ctor("array", [_subject_term(item) for item in site.terms()])
    if site.observed == "Attribute":
        return ctor("py.attr", [_subject_term(site.attr_receiver()), str_const(site.attr_name())])
    if site.observed == "Subscript":
        return ctor(
            "py.subscript",
            [_subject_term(site.subscript_receiver()), _subject_term(site.subscript_index())],
        )
    if site.observed == "Call":
        target = site.call_target_name()
        if target is not None:
            args = [_subject_term(arg) for arg in site.call_args()]
            for keyword in site.call_keywords():
                arg_name = keyword.keyword_arg_name()
                if arg_name is None:
                    raise TypeError(
                        "write more Sugar for isinstance subject `**kwargs`: "
                        "add symbolic keyword expansion"
                    )
                args.append(ctor(f"kw:{arg_name}", [_subject_term(keyword.keyword_value())]))
            return ctor(f"call:{target}", args)
    raise TypeError(
        f"write more Sugar for isinstance subject `{site.observed}`: "
        "add a symbolic subject term shape"
    )


def _type_expr_name(site) -> str:
    if site.observed == "Name":
        return site.name_id()
    if site.observed == "Attribute":
        return f"{_type_expr_name(site.attr_receiver())}.{site.attr_name()}"
    raise TypeError(
        f"write more Sugar for isinstance type `{site.observed}`: "
        "add a builtin type-expression shape"
    )
