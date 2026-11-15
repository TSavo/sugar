from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.floor.none_value import NoneValue
from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
from sugar_lift_py_tests.sugar.witnesses import _assertion_pair


@dataclass(frozen=True)
class NoneLiteralSugar(ConstructedTermSugar):
    """The `None` literal. A leaf: it stands as the NoneValue floor -- the
    None-ness IS the type, there is no value to carry."""

    site: object = dataclass_field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        return _assertion_pair(
            name="none_is_return",
            owner_sugar="NoneLiteralSugar",
            statements=(
                "z = 5\n" "if z is None:\n" "    out = 0\n" "else:\n" "    out = z"
            ),
            truthful="out == 5",
            lying="out == 0",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        del ctx
        return ExitSet.completed(NoneValue())

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor

        return ctor(
            "python:none-literal-construction",
            (self.occurrence_term(owner=owner),),
            symbol_kind="coordinate",
        )
