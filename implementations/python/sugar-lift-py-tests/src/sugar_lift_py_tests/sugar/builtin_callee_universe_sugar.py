from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.recognition.callee_universe import (
    CalleeUniverseRecognition,
)
from sugar_lift_py_tests.sugar.call_sugar import CallSugar
from sugar_lift_py_tests.sugar.method_call_sugar import MethodCallSugar
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


_CONVERTER_COORDINATES = frozenset(
    {
        "numpy._core._multiarray_tests.run_byteorder_converter",
        "numpy._core._multiarray_tests.run_sortkind_converter",
        "numpy._core._multiarray_tests.run_selectkind_converter",
        "numpy._core._multiarray_tests.run_searchside_converter",
        "numpy._core._multiarray_tests.run_order_converter",
        "numpy._core._multiarray_tests.run_clipmode_converter",
        "numpy._core._multiarray_tests.run_casting_converter",
        "numpy._core._multiarray_tests.run_intp_converter",
    }
)
_AUTHENTICATED_COORDINATES = frozenset(
    {
        "type",
        "dtype",
        "numpy._core.multiarray.get_handler_name",
        *_CONVERTER_COORDINATES,
    }
)


@dataclass(frozen=True)
class BuiltinCalleeUniverseSugar(
    Sugar,
    role=SugarRole.TERM,
    comes_before=("CallSugar", "MethodCallSugar"),
):
    """Authenticated deterministic call coordinates.

    CallSugar remains the construction owner for arguments, import/body
    resolution, and the resulting call coordinate. This registered leaf adds
    the missing universe testimony: each coordinate has a verdict-bearing
    witness whose bad twin contradicts deterministic call substitution.
    """

    universe_coordinates = _AUTHENTICATED_COORDINATES

    call: CallSugar | MethodCallSugar
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return (
            CalleeUniverseRecognition.coordinate(site)
            in _AUTHENTICATED_COORDINATES
        )

    @classmethod
    def new(cls, site, ctx) -> "BuiltinCalleeUniverseSugar":
        owner = MethodCallSugar if site.call_receiver() is not None else CallSugar
        return cls(call=owner.new(site, ctx), site=site)

    @classmethod
    def witnesses(cls):
        return (
            _coordinate_witness("type", "5", "6"),
            _coordinate_witness("dtype", "'i4'", "'i8'"),
            _imported_coordinate_witness(
                name="get_handler_name",
                setup=(
                    "from numpy._core.multiarray import get_handler_name\n"
                ),
                callee="get_handler_name",
                argument="5",
            ),
            _imported_method_coordinate_witness(
                setup=(
                    "import numpy._core._multiarray_tests as mt\n"
                ),
            ),
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


def _imported_coordinate_witness(
    *, name: str, setup: str, callee: str, argument: str
):
    prefix = setup + f"\ndef A():\n    return {callee}({argument})\n\n"
    return _call_pair(
        name=f"{name}_builtin_universe_coordinate",
        owner_sugar="BuiltinCalleeUniverseSugar",
        truthful=(
            prefix
            + "def test_a():\n"
            + "    assert A() == 0 and A() == 0\n"
        ),
        lying=(
            prefix
            + "def test_a():\n"
            + "    assert A() == 0 and A() != 0\n"
        ),
        family="builtin-universe-coordinate",
    )


def _imported_method_coordinate_witness(*, setup: str):
    truthful = (
        setup
        + "\nclass TestConverter:\n"
        + "    conv = mt.run_byteorder_converter\n"
        + "    def test_a(self):\n"
        + "        assert self.conv(5) == 0 and self.conv(5) == 0\n"
    )
    lying = (
        setup
        + "\nclass TestConverter:\n"
        + "    conv = mt.run_byteorder_converter\n"
        + "    def test_a(self):\n"
        + "        assert self.conv(5) == 0 and self.conv(5) != 0\n"
    )
    return _call_pair(
        name="conv_builtin_universe_coordinate",
        owner_sugar="BuiltinCalleeUniverseSugar",
        truthful=truthful,
        lying=lying,
        family="builtin-universe-coordinate",
    )
