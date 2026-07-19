from __future__ import annotations

import ast
from pathlib import Path

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.sugar.builtin_callee_universe_sugar import (
    BuiltinCalleeUniverseSugar,
)
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def test_next_unclassified_coordinate_batch_is_enrolled() -> None:
    assert {
        "all",
        "numpy.can_cast",
        "numpy.isnan",
        "numpy.all",
        "numpy._core.multiarray.get_handler_name",
        "numpy._core._multiarray_tests.run_byteorder_converter",
    } <= (BuiltinCalleeUniverseSugar.universe_coordinates)
    assert {
        "all_builtin_universe_coordinate",
        "numpy_can_cast_universe_coordinate",
        "numpy_isnan_universe_coordinate",
        "numpy_all_universe_coordinate",
        "get_handler_name_builtin_universe_coordinate",
        "conv_builtin_universe_coordinate",
    } <= {pair.name for pair in BuiltinCalleeUniverseSugar.witnesses()}


def _can_cast_call_site(source: str) -> SourceFragment:
    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Attribute) and node.func.attr == "can_cast")
            or (isinstance(node.func, ast.Name) and node.func.id == "can_cast")
        )
    )
    return SourceFragment.from_node(call, "can_cast.py", source=source)


def test_authenticated_numpy_can_cast_selects_one_factory_owner() -> None:
    source = (
        "import numpy as np\n"
        "\n"
        "def test_cast(from_, to):\n"
        "    assert np.can_cast(from_, to)\n"
    )
    context = FactoryBuildContext(
        filename="can_cast.py",
        catalog=default_catalog(),
    )
    built = build_node(
        _can_cast_call_site(source),
        filename="can_cast.py",
        role=SugarRole.TERM,
        ctx=context,
    )

    assert built.audit_row.selected == "BuiltinCalleeUniverseSugar"


@pytest.mark.parametrize(
    "source",
    [
        (
            "import numpy as np\n"
            "\n"
            "def test_cast(np, from_, to):\n"
            "    assert np.can_cast(from_, to)\n"
        ),
        (
            "import numpy as np\n"
            "\n"
            "def test_cast(from_, to):\n"
            "    assert np.can_cast(from_, to)\n"
            "    np = replacement\n"
        ),
        (
            "class PretendNumpy:\n"
            "    def can_cast(self, from_, to):\n"
            "        return True\n"
            "\n"
            "def test_cast(np, from_, to):\n"
            "    assert np.can_cast(from_, to)\n"
        ),
        (
            # Unauthenticated FQN spelling alone must not own the coordinate.
            "def test_cast(from_, to):\n"
            "    assert numpy.can_cast(from_, to)\n"
        ),
    ],
)
def test_unwarranted_can_cast_receiver_is_not_factory_owned(source: str) -> None:
    context = FactoryBuildContext(
        filename="can_cast.py",
        catalog=default_catalog(),
    )
    built = build_node(
        _can_cast_call_site(source),
        filename="can_cast.py",
        role=SugarRole.TERM,
        ctx=context,
    )

    assert built.audit_row.selected != "BuiltinCalleeUniverseSugar"


def test_numpy_can_cast_witness_pair_is_enrolled() -> None:
    assert "numpy_can_cast_universe_coordinate" in {
        pair.name for pair in BuiltinCalleeUniverseSugar.witnesses()
    }


def _isnan_call_site(source: str) -> SourceFragment:
    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Attribute) and node.func.attr == "isnan")
            or (isinstance(node.func, ast.Name) and node.func.id == "isnan")
        )
    )
    return SourceFragment.from_node(call, "isnan.py", source=source)


def test_authenticated_numpy_isnan_selects_one_factory_owner() -> None:
    source = (
        "import numpy as np\n"
        "\n"
        "def test_nan(value):\n"
        "    assert np.isnan(value)\n"
    )
    context = FactoryBuildContext(
        filename="isnan.py",
        catalog=default_catalog(),
    )
    built = build_node(
        _isnan_call_site(source),
        filename="isnan.py",
        role=SugarRole.TERM,
        ctx=context,
    )

    assert built.audit_row.selected == "BuiltinCalleeUniverseSugar"


@pytest.mark.parametrize(
    "source",
    [
        (
            "import numpy as np\n"
            "\n"
            "def test_nan(np, value):\n"
            "    assert np.isnan(value)\n"
        ),
        (
            "import numpy as np\n"
            "\n"
            "def test_nan(value):\n"
            "    assert np.isnan(value)\n"
            "    np = replacement\n"
        ),
        (
            "class PretendNumpy:\n"
            "    def isnan(self, value):\n"
            "        return True\n"
            "\n"
            "def test_nan(np, value):\n"
            "    assert np.isnan(value)\n"
        ),
        (
            # Unauthenticated FQN spelling alone must not own the coordinate.
            "def test_nan(value):\n"
            "    assert numpy.isnan(value)\n"
        ),
    ],
)
def test_unwarranted_isnan_receiver_is_not_factory_owned(source: str) -> None:
    context = FactoryBuildContext(
        filename="isnan.py",
        catalog=default_catalog(),
    )
    built = build_node(
        _isnan_call_site(source),
        filename="isnan.py",
        role=SugarRole.TERM,
        ctx=context,
    )

    assert built.audit_row.selected != "BuiltinCalleeUniverseSugar"


def test_numpy_isnan_witness_pair_is_enrolled() -> None:
    assert "numpy_isnan_universe_coordinate" in {
        pair.name for pair in BuiltinCalleeUniverseSugar.witnesses()
    }


def _numpy_all_call_site(source: str) -> SourceFragment:
    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Attribute) and node.func.attr == "all")
            or (isinstance(node.func, ast.Name) and node.func.id == "all")
        )
    )
    return SourceFragment.from_node(call, "numpy_all.py", source=source)


def test_authenticated_numpy_all_selects_one_factory_owner() -> None:
    source = (
        "import numpy as np\n"
        "\n"
        "def test_all(value):\n"
        "    assert np.all(value)\n"
    )
    context = FactoryBuildContext(
        filename="numpy_all.py",
        catalog=default_catalog(),
    )
    built = build_node(
        _numpy_all_call_site(source),
        filename="numpy_all.py",
        role=SugarRole.TERM,
        ctx=context,
    )

    assert built.audit_row.selected == "BuiltinCalleeUniverseSugar"


@pytest.mark.parametrize(
    "source",
    [
        (
            "import numpy as np\n"
            "\n"
            "def test_all(np, value):\n"
            "    assert np.all(value)\n"
        ),
        (
            "import numpy as np\n"
            "\n"
            "def test_all(value):\n"
            "    assert np.all(value)\n"
            "    np = replacement\n"
        ),
        (
            "class PretendNumpy:\n"
            "    def all(self, value):\n"
            "        return True\n"
            "\n"
            "def test_all(np, value):\n"
            "    assert np.all(value)\n"
        ),
        (
            # Unauthenticated FQN spelling alone must not own the coordinate.
            "def test_all(value):\n"
            "    assert numpy.all(value)\n"
        ),
    ],
)
def test_unwarranted_numpy_all_receiver_is_not_factory_owned(source: str) -> None:
    context = FactoryBuildContext(
        filename="numpy_all.py",
        catalog=default_catalog(),
    )
    built = build_node(
        _numpy_all_call_site(source),
        filename="numpy_all.py",
        role=SugarRole.TERM,
        ctx=context,
    )

    assert built.audit_row.selected != "BuiltinCalleeUniverseSugar"


def test_numpy_all_witness_pair_is_enrolled() -> None:
    assert "numpy_all_universe_coordinate" in {
        pair.name for pair in BuiltinCalleeUniverseSugar.witnesses()
    }


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
