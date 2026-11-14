from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar


@dataclass(frozen=True)
class DecoratedDefinitionRefSugar(ConstructedTermSugar):
    """A read of a decorated local ``def``/``class`` name.

    The bound value is the decorator's result, which is not constructed. The
    read constructs (so an unreached read costs nothing) and refuses by name
    when reduced: never the bare definition, never an unbound NameError.
    """

    definition_name: str
    site: object = field(compare=False)

    @classmethod
    def witnesses(cls):
        # A refusal has no truthful completion to witness.
        return ()

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:decorated-definition-reference",
            (self.occurrence_term(owner=owner), str_const(self.definition_name)),
            symbol_kind="coordinate",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        from sugar_source_tree.panic import SugarNotWritten

        raise SugarNotWritten(
            owner="DecoratedDefinitionRef",
            blame=self.site,
            observed=f"read of decorated local definition {self.definition_name!r}",
            requested="the decorator application's result value",
            fix="construct decorator application, or keep the read loud",
        )
