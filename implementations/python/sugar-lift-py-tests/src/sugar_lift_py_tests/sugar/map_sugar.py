from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import LambdaCallable
from sugar_lift_py_tests.operations import MapOperation, perform_operation
from sugar_lift_py_tests.outcome import Incomplete, Outcome, complete_value
from sugar_lift_py_tests.sugar.array_literal_sugar import _map_method_witness
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import SugarWitnessPair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class MapSugar(Sugar, role=SugarRole.TERM, comes_before=("CallSugar",)):
    blame: str
    receiver: SugarBody
    mapper: SugarBody

    @classmethod
    def owns(cls, site) -> bool:
        return _is_map_call(site)

    @classmethod
    def witnesses(cls) -> SugarWitnessPair:
        return _map_method_witness(
            name="map_method",
            owner_sugar=cls.__name__,
        )

    @classmethod
    def build(cls, site, ctx) -> "MapSugar":
        if not _is_map_call(site):
            raise TypeError("MapSugar claim built a non-map call")
        sugar = cls.from_site(
            site,
            receiver=ctx.build_body(site.call_receiver(), SugarRole.TERM),
            mapper=ctx.build_body(site.call_args()[0], SugarRole.TERM),
        )
        if sugar is None:
            raise TypeError("MapSugar claim built a non-map call")
        return sugar

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
        receiver_outcome = self.receiver.reduce(ctx)
        if isinstance(receiver_outcome, Incomplete):
            return receiver_outcome
        receiver = complete_value(receiver_outcome, owner="MapSugar receiver")
        mapper_outcome = self.mapper.reduce(ctx)
        if isinstance(mapper_outcome, Incomplete):
            return mapper_outcome
        mapper = complete_value(mapper_outcome, owner="MapSugar mapper")
        if not isinstance(mapper, LambdaCallable):
            raise TypeError("MapSugar mapper must reduce to LambdaCallable")
        operation = MapOperation(mapper=mapper, owner="MapSugar", blame=self.blame)
        return perform_operation(
            owner="MapSugar",
            blame=self.blame,
            receiver=receiver,
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


from sugar_lift_py_tests.sugar.sugar_base import registered_claims as _rc  # noqa: E402

MAP_CLAIM = next(c for c in _rc() if c.name == "MapSugar")
