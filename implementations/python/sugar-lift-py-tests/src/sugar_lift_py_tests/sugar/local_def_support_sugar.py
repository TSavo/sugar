# SPDX-License-Identifier: MIT OR Apache-2.0
"""Nested local definitions inside a walked body are support, not construction.

Option A widened body dig to zero-parameter functions (`def A(): return
len([...])`). A body can also contain nested `class` / `def` / `async def`
statements (e.g. numpy's `new_and_old_dlpack` nests `class OldDLPack`) and
nested `import` / `from … import` (e.g. pandas `iris_table_metadata` imports
sqlalchemy inside the function). Those local defs/imports are scaffolding for
the body's runtime — they are not evaluated as part of the return-contract
universe the dig builds. Treating them as `SupportValue` accounts for them
without inventing class/function/import sugars that would wrongly lift
definitions as proof content.
"""

from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import SupportValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witness_examples import inert_statement_return_witness
from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing, SugarWitnessPair

_LOCAL_DEF_OBSERVED = frozenset(
    {
        "FunctionDef",
        "AsyncFunctionDef",
        "ClassDef",
        "Import",
        "ImportFrom",
    }
)


@dataclass(frozen=True)
class LocalDefSupportSugar(Sugar, role=SugarRole.STATEMENT):
    """A nested local def/class/import inside a function body: inert for the return universe."""

    kind: str

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed in _LOCAL_DEF_OBSERVED

    @classmethod
    def witnesses(cls) -> tuple[NotVerdictBearing, SugarWitnessPair]:
        return (
            NotVerdictBearing(
                sugar_name=cls.__name__,
                floor_name="SupportValue",
                reason=(
                    "nested FunctionDef/AsyncFunctionDef/ClassDef/Import/ImportFrom "
                    "are local definitions, not part of the body return universe"
                ),
            ),
            inert_statement_return_witness(
                name="local_def_support_return",
                owner_sugar=cls.__name__,
                statement=(
                    "class _Local:\n"
                    "    pass\n"
                    "def _helper():\n"
                    "    return 0"
                ),
            ),
        )

    @classmethod
    def build(cls, site, ctx) -> "LocalDefSupportSugar":
        if not cls.owns(site):
            raise TypeError(
                "LocalDefSupportSugar claim built a non-local-def statement: "
                f"observed={site.observed!r}"
            )
        return cls(kind=site.observed)

    def _build(self, ctx=None) -> Outcome:
        return Complete(SupportValue())
