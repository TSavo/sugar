from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class IsinstanceCallSugar(Sugar, role=SugarRole.TERM, comes_before=("CallSugar",)):
    """The vendor call ``isinstance(value, builtin_type)``.

    This sugar recognizes the vendor's runtime type predicate. It never
    classifies our own sugar or floor objects. The type child reduces through
    BuiltinTypeNameSugar to ``python:type(<name>)`` and dispatches the test to
    the value floor. Local and unknown type names remain loud because the
    factory cannot honestly identify their runtime type coordinate yet.

    Exactly two positional arguments and no keywords are owned. Tuple-of-types,
    starred arguments, keywords, and malformed arities remain outside this
    partition and therefore stay on the existing CallSugar or loud-gap path.
    """

    value: SugarBody
    type_arg: SugarBody
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return (
            site.observed == "Call"
            and site.call_receiver() is None
            and site.call_target_name() == "isinstance"
            and site.call_arg_count() == 2
            and not site.call_has_keywords()
            and not any(arg.observed == "Starred" for arg in site.call_args())
        )

    @classmethod
    def new(cls, site, ctx) -> "IsinstanceCallSugar":
        args = site.call_args()
        return cls(
            value=ctx.build_body(args[0], SugarRole.TERM),
            type_arg=ctx.build_body(args[1], SugarRole.TERM),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        return _call_pair(
            name="isinstance_predicate",
            owner_sugar="IsinstanceCallSugar",
            truthful="def test_a():\n    assert isinstance(1, int)\n",
            lying="def test_a():\n    assert isinstance(1, str)\n",
            family="assertion",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self.value.reduce(ctx).and_then(
            lambda value: self.type_arg.reduce(ctx).and_then(
                lambda type_value: type_value.test_python_type(value, self.site)
            )
        )

    def walk_children(self):
        return (self.value, self.type_arg)
