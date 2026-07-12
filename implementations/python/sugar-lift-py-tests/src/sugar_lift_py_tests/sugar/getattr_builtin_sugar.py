from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import GetattrRuntimeEffect
from sugar_lift_py_tests.floor import ObjectValue, StringValue
from sugar_lift_py_tests.outcome import Incomplete, Outcome
from sugar_lift_py_tests.sugar.attribute_sugar import project_object_attribute
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class GetattrBuiltinSugar(Sugar, role=SugarRole.TERM, comes_before=("CallSugar",)):
    receiver: SugarBody
    static_name: str | None
    dynamic_observed: str | None
    site: object = field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "Call" and site.call_receiver() is None and site.call_target_name() == "getattr" and site.call_arg_count() == 2 and not site.call_has_keywords()

    @classmethod
    def new(cls, site, ctx):
        receiver, name = site.call_args()
        literal = name.literal_value() if name.observed == "PrimitiveLiteral" else None
        return cls(
            ctx.build_body(receiver, SugarRole.TERM),
            literal if isinstance(literal, str) else None,
            None if isinstance(literal, str) else name.observed,
            site,
        )

    @classmethod
    def witnesses(cls):
        prefix = "class Box:\n    def __init__(self):\n        self.x = 1\n\ndef A():\n    return getattr(Box(), 'x')\n\n"
        return _call_pair(name="getattr_builtin_return", owner_sugar=cls.__name__, truthful=prefix+"def test_a():\n    assert A() == 1\n", lying=prefix+"def test_a():\n    assert A() == 2\n")

    def desugar(self, ctx=None) -> Outcome:
        return self.receiver.reduce(ctx).and_then(lambda receiver: self._finish(receiver, ctx))

    def _finish(self, receiver, ctx):
        if self.static_name is None:
            return Incomplete(GetattrRuntimeEffect(f"getattr runtime boundary: attribute name expression `{self.dynamic_observed}` is runtime; blame={self.site}"))
        if not isinstance(receiver, ObjectValue):
            return Incomplete(GetattrRuntimeEffect(f"getattr runtime boundary: receiver reduced to {type(receiver).__name__}; Python resolves attributes at runtime; blame={self.site}"))
        return project_object_attribute(receiver, self.static_name, self.site, ctx)

    def walk_children(self):
        return (self.receiver,)
