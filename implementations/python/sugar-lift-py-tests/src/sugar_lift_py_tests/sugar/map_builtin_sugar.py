from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.floor import FunctionCallable
from sugar_lift_py_tests.operations import CallableMapOperation, perform_operation
from sugar_lift_py_tests.outcome import Outcome, complete_value

from .function_ref_sugar import FunctionRefSugar, function_ref_sugar_from_site
from .range_sugar import RangeSugar, range_sugar_from_site


@dataclass(frozen=True)
class MapBuiltinSugar:
    callable: FunctionRefSugar
    sequence: RangeSugar
    blame: str
    source_line: int
    source_col: int

    @classmethod
    def from_site(
        cls,
        site,
        *,
        functions_by_name: dict,
        blame: str,
    ) -> "MapBuiltinSugar | None":
        return map_builtin_sugar(site, functions_by_name, blame=blame)

    def desugar(self, ctx=None) -> Outcome:
        receiver = complete_value(
            self.sequence.desugar(ctx), owner="MapBuiltinSugar receiver"
        )
        callable_value = complete_value(
            self.callable.desugar(ctx),
            owner="MapBuiltinSugar callable",
        )
        if not isinstance(callable_value, FunctionCallable):
            raise TypeError("MapBuiltinSugar callable must reduce to a function")
        return perform_operation(
            owner="MapBuiltinSugar",
            blame=self.blame,
            receiver=receiver,
            operation=CallableMapOperation(callable_value),
            ctx=ctx,
        )


def map_builtin_sugar(
    site,
    functions_by_name: dict,
    *,
    blame: str,
) -> MapBuiltinSugar | None:
    if site.observed != "Call":
        return None
    if site.call_is_method_call() or site.call_target_name() != "map":
        return None
    if site.call_has_keywords() or site.call_arg_count() != 2:
        return None
    callable_sugar = function_ref_sugar_from_site(
        site.call_args()[0], functions_by_name
    )
    if callable_sugar is None:
        return None
    sequence = range_sugar_from_site(site.call_args()[1])
    if sequence is None:
        return None
    return MapBuiltinSugar(
        callable=callable_sugar,
        sequence=sequence,
        blame=blame,
        source_line=site.line,
        source_col=site.col,
    )
