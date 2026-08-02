from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.floor.ellipsis_value import EllipsisValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class EllipsisLiteralSugar(ConstructedTermSugar):
    """The `...` (Ellipsis) literal. A leaf: it stands as the EllipsisValue
    floor -- the Ellipsis-ness IS the type, there is no value to carry.
    Mirrors NoneLiteralSugar's shape exactly, including ConstructedTermSugar
    admission: ``x[..., :]`` is nested-construction testimony, not a slot lie.
    """

    site: object = dataclass_field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        prefix = (
            "def A(z):\n" "    if z is ...:\n" "        return 0\n" "    return z\n\n"
        )
        return _call_pair(
            name="ellipsis_is_return",
            owner_sugar="EllipsisLiteralSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 0\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx
        return Complete(EllipsisValue())

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor

        return ctor(
            "python:ellipsis-literal-construction",
            (self.occurrence_term(owner=owner), ctor("py.ellipsis", [])),
            symbol_kind="coordinate",
        )
