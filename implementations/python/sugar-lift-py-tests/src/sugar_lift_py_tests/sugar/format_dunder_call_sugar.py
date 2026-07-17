from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import StringValue
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class FormatDunderCallSugar(Sugar, role=SugarRole.TERM, comes_before=("CallSugar",)):
    receiver: SugarBody
    spec: SugarBody | None
    site: object = field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return (
            site.observed == "Call"
            and site.call_receiver() is None
            and site.call_target_name() == "format"
            and site.call_arg_count() in (1, 2)
            and not site.call_has_keywords()
        )

    @classmethod
    def new(cls, site, ctx):
        args = site.call_args()
        return cls(
            ctx.build_body(args[0], SugarRole.TERM),
            ctx.build_body(args[1], SugarRole.TERM) if len(args) == 2 else None,
            site,
        )

    @classmethod
    def witnesses(cls):
        prefix = "class Box:\n    def __format__(self, spec):\n        return spec\n\ndef A():\n    return format(Box(), 'x')\n\n"
        opaque = "def A():\n    return format(external_box(), 'brief')\n\n"
        return (
            _call_pair(
                name="format_dunder_return",
                owner_sugar=cls.__name__,
                truthful=prefix + "def test_a():\n    assert A() == 'x'\n",
                lying=prefix + "def test_a():\n    assert A() == 'y'\n",
            ),
            _call_pair(
                name="callsite_format_coordinate",
                owner_sugar=cls.__name__,
                truthful=opaque + "def test_a():\n    assert A() == 'rendered'\n",
                lying=opaque
                + "def test_a():\n"
                + "    assert A() == 'rendered'\n"
                + "    assert A() == 'different'\n",
                family="callsite-format-coordinate",
            ),
        )

    def desugar(self, ctx=None) -> Outcome:
        if self.spec is None:
            return self.receiver.reduce(ctx).and_then(
                lambda receiver: self._finish(receiver, StringValue(""), ctx)
            )
        return self.receiver.reduce(ctx).and_then(
            lambda receiver: self.spec.reduce(ctx).and_then(
                lambda spec: self._finish(receiver, spec, ctx)
            )
        )

    def _finish(self, receiver, spec, ctx):
        return receiver.format_data_model(spec, self.site, ctx)

    def walk_children(self):
        return (self.receiver,) if self.spec is None else (self.receiver, self.spec)
