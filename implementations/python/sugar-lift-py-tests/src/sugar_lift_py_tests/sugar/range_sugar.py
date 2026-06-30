from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.floor import ArrayLiteral, TermValue
from sugar_lift_py_tests.outcome import Complete, Outcome


@dataclass(frozen=True)
class RangeSugar:
    start: int
    stop: int

    @classmethod
    def from_site(cls, site, _ctx=None) -> "RangeSugar | None":
        return _from_site(site)

    def desugar(self) -> Outcome:
        return Complete(
            ArrayLiteral(tuple(TermValue(value) for value in range(self.start, self.stop)))
        )


def range_sugar(node) -> "RangeSugar | None":
    """Backward-compatible entry point that accepts a raw AST node.

    Wraps the node in a SourceSite so callers that have not yet migrated off raw
    AST (e.g. map_builtin_sugar) continue to work without importing ast themselves.
    """
    from sugar_lift_py_tests.factory.source_site import SourceSite

    return _from_site(SourceSite.from_node(node, ""))


def range_sugar_from_site(site) -> "RangeSugar | None":
    """Public site-based entry point -- no raw AST required."""
    return _from_site(site)


def _from_site(site) -> "RangeSugar | None":
    """Build a RangeSugar from a SourceSite using only SourceSite accessors."""
    if site.observed != "Call":
        return None
    if site.call_is_method_call() or site.call_target_name() != "range":
        return None
    if site.call_has_keywords():
        return None
    if site.call_arg_count() != 2:
        return None
    args = site.call_args()
    start = _int_const_from_site(args[0])
    stop = _int_const_from_site(args[1])
    if start is None or stop is None:
        return None
    return RangeSugar(start=start, stop=stop)


def _int_const_from_site(site) -> "int | None":
    """Return the int value of a PrimitiveLiteral site that holds a plain int, else None.

    bool is excluded because bool is a subclass of int in Python; a literal True/False
    is not a valid range bound.
    """
    if site.observed != "PrimitiveLiteral":
        return None
    v = site.literal_value()
    if isinstance(v, int) and not isinstance(v, bool):
        return v
    return None
