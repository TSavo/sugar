from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.ir import Term, ctor

from .floor_value import FloorValue


@dataclass(frozen=True)
class DictLiteralValue(FloorValue):
    """A structural Python dict literal term.

    Dict literals are useful evidence payloads and call arguments, but the current
    production solver path does not give dict constructor equality an independent
    verdict witness. The floor is therefore a typed non-FOL support carrier, while
    still projecting to a term for enclosing claims.
    """

    non_fol_support = True

    entries: tuple[tuple[Term, Term], ...]

    def to_term(self, *, owner: str) -> Term:
        del owner
        return ctor(
            "python:dict",
            [ctor("python:dict_entry", [key, value]) for key, value in self.entries],
        )
