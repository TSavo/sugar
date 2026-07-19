from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.call_sugar import CallSugar
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


_AUTHENTICATED_COORDINATES = frozenset({"type", "dtype"})
_AUTHENTICATED_IMPORTED_COORDINATES = frozenset({"numpy.can_cast"})


@dataclass(frozen=True)
class BuiltinCalleeUniverseSugar(
    Sugar, role=SugarRole.TERM, comes_before=("CallSugar",)
):
    """Authenticated deterministic coordinates for ``type`` and ``dtype``.

    CallSugar remains the construction owner for arguments, import/body
    resolution, and the resulting call coordinate. This registered leaf adds
    the missing universe testimony: each coordinate has a verdict-bearing
    witness whose bad twin contradicts deterministic call substitution.
    """

    universe_coordinates = _AUTHENTICATED_COORDINATES

    call: CallSugar
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return (
            site.observed == "Call"
            and (
                (
                    site.call_receiver() is None
                    and site.call_target_name() in _AUTHENTICATED_COORDINATES
                )
                or (
                    site.call_receiver() is not None
                    and site.call_target_name() == "can_cast"
                )
            )
            and not site.call_has_keywords()
        )

    @classmethod
    def new(cls, site, ctx) -> "BuiltinCalleeUniverseSugar":
        if site.call_receiver() is not None:
            from sugar_lift_py_tests.floor import ImportAliasValue

            receiver = site.call_receiver()
            receiver_name = getattr(getattr(receiver, "node", None), "id", None)
            bound = (
                ctx.temporal.value_if_bound(receiver_name)
                if receiver_name is not None and ctx is not None
                else None
            )
            if not (
                type(bound) is ImportAliasValue
                and bound.install_source_checked
                and bound.resolved_value is not None
            ):
                from sugar_lift_py_tests.factory.factory_gap import factory_panic_gap

                factory_panic_gap(
                    owner="BuiltinCalleeUniverseSugar",
                    blame=site.blame,
                    observed="unproven imported receiver",
                    requested="authenticated NumPy callee universe",
                    fix="bind the receiver to the authenticated numpy import coordinate",
                )
        return cls(call=CallSugar.new(site, ctx), site=site)

    @classmethod
    def witnesses(cls):
        return (
            _coordinate_witness("type", "5", "6"),
            _coordinate_witness("dtype", "'i4'", "'i8'"),
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self.call.desugar(ctx)

    def walk_children(self):
        return self.call.walk_children()


def _coordinate_witness(callee: str, argument: str, lying_value: str):
    prefix = (
        f"def {callee}(value):\n"
        "    return value\n"
        "\n"
        f"def A(z):\n    return {callee}(z)\n\n"
    )
    return _call_pair(
        name=f"{callee}_builtin_universe_coordinate",
        owner_sugar="BuiltinCalleeUniverseSugar",
        truthful=(
            prefix
            + f"def test_a():\n    assert A({argument}) == {argument}\n"
        ),
        lying=(
            prefix
            + f"def test_a():\n    assert A({argument}) == {lying_value}\n"
        ),
        family="builtin-universe-coordinate",
    )
