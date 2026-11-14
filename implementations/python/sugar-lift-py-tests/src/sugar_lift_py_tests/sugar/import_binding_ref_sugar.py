from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar


@dataclass(frozen=True)
class ImportBindingRefSugar(ConstructedTermSugar):
    """A read of a module name an import binds, away from the import table's
    row for that read (``ImportBindingRef``): an arm of the phi a ``try``
    route builds (``try: import json`` / ``except ImportError: json =
    None``), or a read the table does not row.

    The binding is decided -- the import table's row for it, ``target_symbol``
    -- but the imported value is not constructed here.  The read constructs
    (so an unreached arm costs nothing) and refuses by name when reduced:
    never the name read in its place.
    """

    name: str
    target_symbol: str
    site: object = field(compare=False)

    @classmethod
    def witnesses(cls):
        # A refusal has no truthful completion to witness.
        return ()

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:import-binding-reference",
            (
                self.occurrence_term(owner=owner),
                str_const(self.name),
                str_const(self.target_symbol),
            ),
            symbol_kind="coordinate",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        from sugar_source_tree.panic import SugarNotWritten

        raise SugarNotWritten(
            owner="ImportBindingRef",
            blame=self.site,
            observed=(
                f"read of `{self.name}` bound by its import of "
                f"{self.target_symbol} away from the import table's row"
            ),
            requested="the imported value at this read",
            fix=(
                "construct the import's value where the read is not its own "
                "table row, or keep the read loud"
            ),
        )
