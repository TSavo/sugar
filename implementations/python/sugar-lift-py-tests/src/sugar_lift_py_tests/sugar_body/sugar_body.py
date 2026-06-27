from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Any

from sugar_lift_py_tests.claim import SugarRole


@dataclass(frozen=True)
class SugarBody:
    sugar: object
    role: SugarRole
    audit_row: Any = None

    def reduce(self, ctx):
        reducer = getattr(self.sugar, "desugar", None)
        if reducer is None:
            raise TypeError(
                f"write more Floor for this construction: owner=SugarBody "
                f"observed={type(self.sugar).__name__} requested=desugar "
                f"fix=add desugar to {type(self.sugar).__name__}"
            )
        if inspect.signature(reducer).parameters:
            return reducer(ctx)
        return reducer()
