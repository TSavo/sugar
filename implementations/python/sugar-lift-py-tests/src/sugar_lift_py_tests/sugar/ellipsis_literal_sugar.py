from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.floor.ellipsis_value import EllipsisValue
from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
from sugar_lift_py_tests.sugar.witnesses import _assertion_pair


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
        return _assertion_pair(
            name="ellipsis_is_return",
            owner_sugar="EllipsisLiteralSugar",
            statements=(
                "z = 5\n" "if z is ...:\n" "    out = 0\n" "else:\n" "    out = z"
            ),
            truthful="out == 5",
            lying="out == 0",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        del ctx
        return ExitSet.completed(EllipsisValue())

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor

        return ctor(
            "python:ellipsis-literal-construction",
            (self.occurrence_term(owner=owner), ctor("py.ellipsis", [])),
            symbol_kind="coordinate",
        )
