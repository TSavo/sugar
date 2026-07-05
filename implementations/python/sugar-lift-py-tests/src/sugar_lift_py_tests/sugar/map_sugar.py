from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.floor import LambdaCallable
from sugar_lift_py_tests.operations import MapOperation, perform_operation
from sugar_lift_py_tests.outcome import Incomplete, Outcome
from sugar_lift_py_tests.sugar.array_literal_sugar import _map_method_witness
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import SugarWitnessPair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class MapSugar(Sugar, role=SugarRole.TERM, comes_before=("CallSugar",)):
    blame: str
    receiver: SugarBody
    mapper: SugarBody
    template_operand_names = ("receiver", "mapper")

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

    def _build(self, ctx=None, *, receiver, mapper) -> Outcome:
        if not isinstance(mapper, LambdaCallable):
            return Incomplete(
                RuntimeEffect(
                    "map mapper runtime boundary: "
                    f"mapper reduced to {type(mapper).__name__}; MapSugar "
                    "requires a LambdaCallable mapper so Python's per-element "
                    "call semantics are not guessed. Add a callable floor for "
                    "this mapper shape or keep the assertion as a typed red "
                    f"effect. blame={self.blame}"
                )
            )
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
