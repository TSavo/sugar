from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .sugar_role import SugarRole


@dataclass(frozen=True)
class SugarClaim:
    name: str
    role: SugarRole
    owns: Callable[[object], bool]
    comes_before: tuple[str, ...] = ()
    witnesses: Callable[[], object] | None = None
    # Closed callee coordinates for which this Sugar carries authenticated
    # universe testimony. This is registry evidence, not an audit-side
    # name whitelist: enrollment still requires the Sugar's witnesses.
    universe_coordinates: frozenset[str] = frozenset()
    # Construction: given the recognized source site + build context, `new` builds
    # this sugar's child bodies through the factory and constructs it. No reduction
    # happens here -- that is desugar's job.
    new: Callable[[object, object], object] | None = None
