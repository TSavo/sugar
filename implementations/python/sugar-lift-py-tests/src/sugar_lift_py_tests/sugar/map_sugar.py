from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarClaim, SugarRole
from sugar_lift_py_tests.factory.sugar_constructors import build_map_sugar
from sugar_lift_py_tests.floor import LambdaCallable
from sugar_lift_py_tests.operations import MapOperation, perform_operation
from sugar_lift_py_tests.outcome import Outcome, complete_value
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class MapSugar:
    blame: str
    receiver: SugarBody
    mapper: SugarBody

    @classmethod
    def from_site(
        cls, site, *, receiver: SugarBody, mapper: SugarBody
    ) -> "MapSugar | None":
        if not _is_map_call(site):
            return None
        return cls(
            blame=site.blame,
            receiver=receiver,
            mapper=mapper,
        )

    def desugar(self, ctx=None) -> Outcome:
        receiver = complete_value(self.receiver.reduce(ctx), owner="MapSugar receiver")
        mapper = complete_value(self.mapper.reduce(ctx), owner="MapSugar mapper")
        if not isinstance(mapper, LambdaCallable):
            raise TypeError("MapSugar mapper must reduce to LambdaCallable")
        operation = MapOperation(mapper=mapper, owner="MapSugar", blame=self.blame)
        return perform_operation(
            owner="MapSugar",
            blame=self.blame,
            receiver=receiver,
            method_name="map_with",
            operation=operation,
            ctx=ctx,
        )


def _is_map_call(site) -> bool:
    return (
        site.observed == "Call"
        and site.call_is_method_call()
        and site.call_target_name() == "map"
        and site.call_arg_count() == 1
    )


def _owns(site) -> bool:
    return _is_map_call(site)


MAP_CLAIM = SugarClaim(
    name="MapSugar",
    role=SugarRole.TERM,
    owns=_owns,
    build=build_map_sugar,
)
