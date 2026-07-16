from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.equality_op_sugar import EqualityOpSugar
from sugar_lift_py_tests.sugar.witnesses import _refused_call_return_pair


@dataclass(frozen=True)
class ObjectEqualityTermSugar(
    EqualityOpSugar,
    role=SugarRole.TERM,
    comes_before=("EqualityOpSugar",),
):
    """Opaque object equality stays ``py.eq`` until a sort warrants FOL ``=``."""

    @classmethod
    def owns(cls, site) -> bool:
        return (
            EqualityOpSugar.owns(site)
            and site.compare_left().observed == "Call"
            and site.compare_comparators()[0].observed == "Call"
        )

    @classmethod
    def new(cls, site, ctx) -> "ObjectEqualityTermSugar":
        base = EqualityOpSugar.new(site, ctx)
        return cls(left=base.left, right=base.right, site=base.site)

    @classmethod
    def witnesses(cls):
        prefix = "class C:\n    def __init__(self, x):\n        self.x = x\n\n"
        explicit_eq_prefix = (
            "class C:\n"
            "    def __init__(self, x):\n"
            "        self.x = x\n"
            "    def __eq__(self, other):\n"
            "        return self.x == other.x\n\n"
        )
        return (
            _refused_call_return_pair(
                name="object_equality_identity_return",
                owner_sugar=cls.__name__,
                body="C(z) == C(z)",
                truthful="False",
                lying="True",
                prefix=prefix,
            ),
            _refused_call_return_pair(
                name="object_equality_return",
                owner_sugar=cls.__name__,
                body="C(z) == C(z)",
                truthful="True",
                lying="False",
                prefix=explicit_eq_prefix,
            ),
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return super().desugar(ctx)
