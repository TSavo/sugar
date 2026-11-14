from __future__ import annotations

from typing import NoReturn

from sugar_lift_py_tests.gap.panic import ConstructionPanic, construction_panic
from sugar_lift_py_tests.gap.info import ConstructionGap, GapKind, GapLocus


class FreeVariableRefusal(ConstructionPanic):
    """The scope law: a formula names a variable its declared scope does not.

    Still a ``ConstructionPanic`` everywhere it propagates. It is typed so the
    one place that turns a function's rows into the wire can refuse that one
    function by name and keep the rest of the file (#7785). ``names`` are the
    free names, sorted.
    """

    def __init__(self, info: ConstructionGap, names: tuple[str, ...]) -> None:
        self.names = names
        super().__init__(info)


def _law_gap(*, owner: str, observed: str, requested: str, fix: str) -> ConstructionGap:
    return ConstructionGap(
        owner=owner,
        blame="proofir-construction-law",
        observed=observed,
        requested=requested,
        fix=fix,
        gap_kind=GapKind.PROOFIR,
        gap_locus=GapLocus.CONSTRUCTION_LAW,
    )


def proofir_construction_gap(
    *,
    owner: str,
    observed: str,
    requested: str,
    fix: str,
) -> NoReturn:
    construction_panic(
        _law_gap(owner=owner, observed=observed, requested=requested, fix=fix)
    )


def proofir_free_variable_refusal(
    *,
    owner: str,
    names,
    requested: str,
    fix: str,
) -> NoReturn:
    names = tuple(sorted(names))
    info = _law_gap(
        owner=owner,
        observed=f"illegal free var(s): {', '.join(names)}",
        requested=requested,
        fix=fix,
    )
    raise FreeVariableRefusal(info, names)
