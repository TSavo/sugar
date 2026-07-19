from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.sugar.builtin_callee_universe_sugar import (
    BuiltinCalleeUniverseSugar,
)
from sugar_lift_py_tests.context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import ImportAliasValue, TermValue
from sugar_lift_py_tests.temporal import TemporalContext
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def test_next_unclassified_coordinate_batch_is_enrolled() -> None:
    assert {
        "all",
        "numpy._core.multiarray.get_handler_name",
        "numpy._core._multiarray_tests.run_byteorder_converter",
    } <= (BuiltinCalleeUniverseSugar.universe_coordinates)
    assert {
        "all_builtin_universe_coordinate",
        "get_handler_name_builtin_universe_coordinate",
        "conv_builtin_universe_coordinate",
    } <= {pair.name for pair in BuiltinCalleeUniverseSugar.witnesses()}


@pytest.mark.parametrize(
    "pair",
    BuiltinCalleeUniverseSugar.witnesses(),
    ids=lambda pair: pair.name,
)
def test_builtin_callee_universe_witness_refutes_bad_twin(pair, tmp_path: Path) -> None:
    truthful = run_source_through_real_solver(
        tmp_path / f"{pair.name}-truthful", pair.truthful.source
    )
    lying = run_source_through_real_solver(
        tmp_path / f"{pair.name}-lying", pair.lying.source
    )

    assert truthful.verdict == "sat"
    assert lying.verdict == "unsat"
    assert "BuiltinCalleeUniverseSugar" in truthful.selected_sugars
    assert "BuiltinCalleeUniverseSugar" in lying.selected_sugars


def test_numpy_can_cast_requires_authenticated_receiver() -> None:
    site = SourceFragment.from_node(
        __import__("ast").parse("np.can_cast(x, y)").body[0].value,
        "numpy_can_cast.py",
    )
    assert BuiltinCalleeUniverseSugar.owns(site)
    ctx = FactoryBuildContext(
        filename="numpy_can_cast.py",
        catalog=default_catalog(),
        temporal=TemporalContext.empty().bind_value(
            "np",
            ImportAliasValue(
                "numpy", "np", import_target="numpy", install_source_checked=True,
                resolved_value=TermValue("numpy"),
            ),
        ),
    )
    sugar = BuiltinCalleeUniverseSugar.new(site, ctx)
    assert isinstance(sugar, BuiltinCalleeUniverseSugar)

    lying = FactoryBuildContext(
        filename="numpy_can_cast.py", catalog=default_catalog(), temporal=TemporalContext.empty().bind_value(
            "np", ImportAliasValue("other", "np", import_target="other")
        )
    )
    with pytest.raises(FactoryPanic):
        BuiltinCalleeUniverseSugar.new(site, lying)
