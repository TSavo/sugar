"""InstrumentScanScope — declared population for instrument runs.

Class (four-for-four today: self_sealing 94→2, swallowed 79→7, spelling 32→6,
vendor 23→~0): an instrument that can emit an offender set without declaring
its population is measuring the wrong world. Expanded multi-root, instrument
tables, and auth-pin inventory all scored as product R.

Law:
  - Unconstructible without a non-empty ``declared_roots``.
  - ``self_exclusion`` and ``auth_pin_exclusion`` are structural True — there
    is no constructor that admits instrument-self or auth-pin inventory as
    product population.
  - Scans take a scope; reports carry ``to_provenance()`` so an R is
    meaningless without declared root set (feeds #6998 InstrumentProvenance).

Teeth: plant the instrument under its own root → not admitted; plant an
auth-pin inventory module → not admitted.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Sequence

_SEAL = object()

# Basenames that name corpus/auth pin inventory — not product logo-dispatch.
# The 15 vendor_arm CORPUS_AUTH_PIN_INVENTORY rows lived in these modules.
AUTH_PIN_INVENTORY_BASENAMES: frozenset[str] = frozenset(
    {
        "authenticated_pytest.py",
        "no_call_body_attribution.py",
        "corpus_pin.py",
        "demand_table_identity.py",
    }
)


class InstrumentScanScopeError(ValueError):
    """Scope construction or path admission refused."""


@dataclass(frozen=True, slots=True)
class InstrumentScanScope:
    """Declared scan population. Sealed — use :func:`instrument_scan_scope`."""

    declared_roots: tuple[Path, ...]
    instrument_self_paths: frozenset[Path]
    self_exclusion: bool
    auth_pin_exclusion: bool
    _seal: object

    def __post_init__(self) -> None:
        if self._seal is not _SEAL:
            raise InstrumentScanScopeError(
                "InstrumentScanScope is sealed: use instrument_scan_scope(...); "
                "an undeclared root set has no constructor"
            )
        if not self.declared_roots:
            raise InstrumentScanScopeError(
                "declared_roots must be non-empty; refusing undeclared population "
                "(wrong-population false green). Name the roots explicitly."
            )
        if self.self_exclusion is not True:
            raise InstrumentScanScopeError(
                "self_exclusion is structural and must be True; cannot construct "
                "a scope that admits instrument-self as product population"
            )
        if self.auth_pin_exclusion is not True:
            raise InstrumentScanScopeError(
                "auth_pin_exclusion is structural and must be True; cannot "
                "construct a scope that admits auth-pin inventory as product "
                "population"
            )
        if not self.instrument_self_paths:
            raise InstrumentScanScopeError(
                "instrument_self_paths must name at least the scanning module "
                "(__file__); self-exclusion by construction needs a self path"
            )

    def admits(self, path: Path) -> bool:
        """True iff *path* is in the declared population and not excluded."""
        try:
            resolved = path.resolve()
        except OSError:
            return False
        if not resolved.is_file() or resolved.suffix != ".py":
            return False
        if "__pycache__" in resolved.parts:
            return False
        if resolved in self.instrument_self_paths:
            return False
        if resolved.name in AUTH_PIN_INVENTORY_BASENAMES:
            return False
        for root in self.declared_roots:
            try:
                root_r = root.resolve()
            except OSError:
                continue
            if root_r.is_file():
                if resolved == root_r:
                    return True
                continue
            try:
                if resolved.is_relative_to(root_r):
                    return True
            except (OSError, ValueError, AttributeError):
                # is_relative_to absent on very old Python; fall back.
                try:
                    resolved.relative_to(root_r)
                    return True
                except ValueError:
                    continue
        return False

    def iter_python_files(self) -> Iterator[Path]:
        """Yield admitted ``*.py`` files under declared roots (deduped)."""
        seen: set[Path] = set()
        for root in self.declared_roots:
            try:
                root_r = root.resolve()
            except OSError:
                continue
            if not root_r.exists():
                continue
            if root_r.is_file():
                candidates: Iterable[Path] = (root_r,)
            else:
                try:
                    candidates = sorted(root_r.rglob("*.py"))
                except OSError:
                    continue
            for path in candidates:
                if not path.is_file():
                    continue
                try:
                    resolved = path.resolve()
                except OSError:
                    continue
                if resolved in seen:
                    continue
                if self.admits(resolved):
                    seen.add(resolved)
                    yield resolved

    def to_provenance(self) -> dict[str, object]:
        """JSON-ready population provenance for reports and #6998 MeasuredAxis."""
        return {
            "declaredRoots": [str(p) for p in self.declared_roots],
            "selfExclusion": True,
            "authPinExclusion": True,
            "instrumentSelfPaths": sorted(
                str(p) for p in self.instrument_self_paths
            ),
            "authPinInventoryBasenames": sorted(AUTH_PIN_INVENTORY_BASENAMES),
        }


def instrument_scan_scope(
    *,
    declared_roots: Sequence[Path],
    instrument_self: Path | Sequence[Path],
) -> InstrumentScanScope:
    """One door for a scan population. Roots required; exclusions always on."""
    roots = tuple(Path(p).resolve() for p in declared_roots)
    if not roots:
        raise InstrumentScanScopeError(
            "declared_roots must be non-empty; refusing undeclared population "
            "(wrong-population false green). Name the roots explicitly."
        )
    if isinstance(instrument_self, (str, Path)):
        selves = frozenset({Path(instrument_self).resolve()})
    else:
        selves = frozenset(Path(p).resolve() for p in instrument_self)
    if not selves:
        raise InstrumentScanScopeError(
            "instrument_self must name at least the scanning module (__file__); "
            "self-exclusion by construction needs a self path"
        )
    return InstrumentScanScope(
        declared_roots=roots,
        instrument_self_paths=selves,
        self_exclusion=True,
        auth_pin_exclusion=True,
        _seal=_SEAL,
    )


def require_declared_roots(roots: Sequence[Path]) -> tuple[Path, ...]:
    """Refuse empty root args at a CLI door (companion to scope construction)."""
    if not roots:
        raise InstrumentScanScopeError(
            "scan roots must be explicit and non-empty; refusing empty or "
            "defaulted path set (wrong-population false green). Construct an "
            "InstrumentScanScope with named declared_roots."
        )
    return tuple(Path(p).resolve() for p in roots)
