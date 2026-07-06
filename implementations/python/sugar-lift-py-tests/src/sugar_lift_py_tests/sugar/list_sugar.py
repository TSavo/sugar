from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sugar_lift_py_tests.outcome import Outcome

from .map_builtin_sugar import MapBuiltinSugar, map_builtin_sugar


@dataclass(frozen=True)
class ListSugar:
    """Sugar for list(map(fn, range(...))).

    The caller is responsible for building ``body`` (the inner MapBuiltinSugar)
    from the factory and passing it in via ``from_site``; this sugar is a dumb
    value that holds its pre-built body.
    """

    body: MapBuiltinSugar

    @classmethod
    def from_site(
        cls,
        site,
        *,
        body: Optional[MapBuiltinSugar] = None,
        functions_by_name: Optional[dict] = None,
        blame: Optional[str] = None,
    ) -> "ListSugar | None":
        """Build from a SourceFragment.

        When ``body`` is supplied the factory already built the inner sugar --
        just validate the outer shape and wrap it.  When ``body`` is not
        supplied fall back to the standalone builder (legacy call-sites and the
        factory dispatcher for the top-level ``list(...)`` claim).
        """
        if body is not None:
            if site.observed != "Call":
                return None
            if site.call_is_method_call() or site.call_target_name() != "list":
                return None
            if site.call_has_keywords() or site.call_arg_count() != 1:
                return None
            return cls(body=body)
        return list_sugar(site, functions_by_name or {}, blame=blame or "")

    def desugar(self, ctx=None) -> Outcome:
        return self.body.desugar(ctx)


def list_sugar(
    site,
    functions_by_name: dict,
    *,
    blame: str,
) -> "ListSugar | None":
    """Recognise list(map(...)) at a SourceFragment.

    Returns None if the site is not that shape.
    """
    if site.observed != "Call":
        return None
    if site.call_is_method_call() or site.call_target_name() != "list":
        return None
    if site.call_has_keywords() or site.call_arg_count() != 1:
        return None
    body = map_builtin_sugar(
        site.call_args()[0],
        functions_by_name,
        blame=blame,
    )
    if body is None:
        return None
    return ListSugar(body=body)
