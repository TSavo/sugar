from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.floor.none_value import NoneValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class NoneLiteralSugar(ConstructedTermSugar):
    """The `None` literal. A leaf: it stands as the NoneValue floor -- the
    None-ness IS the type, there is no value to carry."""

    site: object = dataclass_field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        prefix = "def A(z):\n    if z is None:\n        return 0\n    return z\n\n"
        return _call_pair(
            name="none_is_return",
            owner_sugar="NoneLiteralSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 0\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx
        return Complete(NoneValue())

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor

        return ctor(
            "python:none-literal-construction",
            (self.occurrence_term(owner=owner),),
            symbol_kind="coordinate",
        )
