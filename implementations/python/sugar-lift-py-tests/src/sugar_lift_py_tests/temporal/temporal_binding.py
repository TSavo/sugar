from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.floor import FloorValue


@dataclass(frozen=True)
class TemporalBinding:
    name: str
    value: FloorValue
    blame: str | None = None


@dataclass(frozen=True)
class FormalActualBinding(TemporalBinding):
    """A followed call's binding of one of its callee's formals -- by the
    formal's name and by its coordinate -- to the caller's actual
    (``call_site_value._ctx_with_curried_args``, the one door a followed call
    installs its formals through).

    Its kind is its type, never its blame text: a read of the name
    (``NameSugar``) is that actual as the formal holds it
    (``object_identity.as_bound_formals``), where any other binding the
    reduction installed -- a module global, a generator's write -- reached
    the read by binding (``object_identity.arrived``).  A rebind that
    advances the same object (the alias scan, ``as_the_alias_holds``) keeps
    the kind (``TemporalContext.bind_value``'s ``kind``); any other write of
    the name is a plain binding."""
