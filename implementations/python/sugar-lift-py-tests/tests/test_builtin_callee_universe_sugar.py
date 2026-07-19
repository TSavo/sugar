from __future__ import annotations

import ast
from pathlib import Path

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.recognition.callee_universe import (
    CalleeUniverseSupport,
    recognize_callee_universe,
)
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
        "list",
        "set",
        "hasattr",
        "item",
        "numpy.can_cast",
        "numpy.issubdtype",
        "numpy.isnan",
        "numpy.all",
        "numpy.dtype",
        "numpy.shares_memory",
        "numpy._core.multiarray.get_handler_name",
        "numpy._core._multiarray_tests.run_byteorder_converter",
        "re.Pattern.search",
        "json.loads",
        "dataclasses.asdict",
    } <= (BuiltinCalleeUniverseSugar.universe_coordinates)
    assert {
        "all_builtin_universe_coordinate",
        "list_builtin_universe_coordinate",
        "set_builtin_universe_coordinate",
        "hasattr_builtin_universe_coordinate",
        "item_receiver_universe_coordinate",
        "numpy_can_cast_universe_coordinate",
        "numpy_issubdtype_universe_coordinate",
        "numpy_isnan_universe_coordinate",
        "numpy_all_universe_coordinate",
        "numpy_dtype_universe_coordinate",
        "numpy_dtype_result_universe_coordinate",
        "numpy_shares_memory_builtin_universe_coordinate",
        "get_handler_name_builtin_universe_coordinate",
        "conv_builtin_universe_coordinate",
        "regex_search_builtin_universe_coordinate",
        "json_loads_universe_coordinate",
        "dataclasses_asdict_universe_coordinate",
    } <= {pair.name for pair in BuiltinCalleeUniverseSugar.witnesses()}


def test_all_nine_authenticated_conv_rows_select_the_converter_owner() -> None:
    """The #5409 corpus family is bound class testimony, never the name ``conv``."""

    source = (
        "import numpy._core._multiarray_tests as mt\n"
        "\n"
        "class TestClipmodeConverter:\n"
        "    conv = mt.run_clipmode_converter\n"
        "    def test_valid(self):\n"
        "        assert self.conv(0) == 'NPY_CLIP'\n"
        "        assert self.conv(1) == 'NPY_WRAP'\n"
        "        assert self.conv(2) == 'NPY_RAISE'\n"
        "\n"
        "class TestIntpConverter:\n"
        "    conv = mt.run_intp_converter\n"
        "    def test_basic(self):\n"
        "        assert self.conv(1) == (1,)\n"
        "        assert self.conv((1, 2)) == (1, 2)\n"
        "        assert self.conv([1, 2]) == (1, 2)\n"
        "        assert self.conv(()) == ()\n"
        "        assert self.conv(None) == ()\n"
        "        assert self.conv([1] * 64) == (1,) * 64\n"
    )
    calls = [
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "conv"
    ]

    assert len(calls) == 9
    for call in calls:
        site = SourceFragment.from_node(call, "test_conversion_utils.py", source=source)
        context = FactoryBuildContext(
            filename="test_conversion_utils.py",
            catalog=default_catalog(),
        )
        built = build_node(
            site,
            filename="test_conversion_utils.py",
            role=SugarRole.TERM,
            ctx=context,
        )
        assert built.audit_row.selected == "BuiltinCalleeUniverseSugar"


def _method_call_site(source: str, member: str) -> SourceFragment:
    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == member
    )
    return SourceFragment.from_node(call, f"{member}_call.py", source=source)


def test_import_authenticated_regex_search_selects_one_factory_owner() -> None:
    source = (
        "import re\n"
        "\n"
        "def test_search(value):\n"
        "    pattern = re.compile('x')\n"
        "    assert pattern.search(value) is not None\n"
    )
    built = build_node(
        _method_call_site(source, "search"),
        filename="search_call.py",
        role=SugarRole.TERM,
        ctx=FactoryBuildContext(
            filename="search_call.py",
            catalog=default_catalog(),
        ),
    )

    assert built.audit_row.selected == "BuiltinCalleeUniverseSugar"


@pytest.mark.parametrize(
    "source",
    [
        (
            "def test_search(pattern, value):\n"
            "    assert pattern.search(value) is not None\n"
        ),
        (
            "import re\n"
            "\n"
            "def test_search(value):\n"
            "    pattern = re.compile('x')\n"
            "    pattern = replacement\n"
            "    assert pattern.search(value) is not None\n"
        ),
        (
            "import pretend_re as re\n"
            "\n"
            "def test_search(value):\n"
            "    pattern = re.compile('x')\n"
            "    assert pattern.search(value) is not None\n"
        ),
    ],
)
def test_unwarranted_search_receiver_stays_outside_factory_owner(source: str) -> None:
    built = build_node(
        _method_call_site(source, "search"),
        filename="search_call.py",
        role=SugarRole.TERM,
        ctx=FactoryBuildContext(
            filename="search_call.py",
            catalog=default_catalog(),
        ),
    )

    assert built.audit_row.selected != "BuiltinCalleeUniverseSugar"


def _bare_builtin_call_site(source: str, callee: str) -> SourceFragment:
    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == callee
    )
    return SourceFragment.from_node(call, f"{callee}_call.py", source=source)


def _list_call_site(source: str) -> SourceFragment:
    return _bare_builtin_call_site(source, "list")


def test_authenticated_list_selects_one_factory_owner() -> None:
    source = "def test_list(values):\n    assert list(values) == []\n"
    context = FactoryBuildContext(
        filename="list_call.py",
        catalog=default_catalog(),
    )
    built = build_node(
        _list_call_site(source),
        filename="list_call.py",
        role=SugarRole.TERM,
        ctx=context,
    )

    assert built.audit_row.selected == "BuiltinCalleeUniverseSugar"


@pytest.mark.parametrize(
    "source",
    [
        "def test_list(list, values):\n    assert list(values) == []\n",
        (
            "def test_list(values):\n"
            "    assert list(values) == []\n"
            "    list = replacement\n"
        ),
        (
            "class PretendList:\n"
            "    def __call__(self, values):\n"
            "        return values\n"
            "\n"
            "def test_list(list, values):\n"
            "    assert list(values) == []\n"
        ),
    ],
)
def test_unwarranted_list_receiver_is_not_factory_owned(source: str) -> None:
    context = FactoryBuildContext(
        filename="list_call.py",
        catalog=default_catalog(),
    )
    built = build_node(
        _list_call_site(source),
        filename="list_call.py",
        role=SugarRole.TERM,
        ctx=context,
    )

    assert built.audit_row.selected != "BuiltinCalleeUniverseSugar"


def test_list_witness_pair_is_enrolled() -> None:
    assert "list_builtin_universe_coordinate" in {
        pair.name for pair in BuiltinCalleeUniverseSugar.witnesses()
    }


def test_authenticated_set_selects_one_factory_owner() -> None:
    source = "def test_set(values):\n    assert set(values) == set()\n"
    context = FactoryBuildContext(
        filename="set_call.py",
        catalog=default_catalog(),
    )
    built = build_node(
        _bare_builtin_call_site(source, "set"),
        filename="set_call.py",
        role=SugarRole.TERM,
        ctx=context,
    )

    assert built.audit_row.selected == "BuiltinCalleeUniverseSugar"


@pytest.mark.parametrize(
    "source",
    [
        "def test_set(set, values):\n    assert set(values) == set()\n",
        (
            "def test_set(values):\n"
            "    assert set(values) == set()\n"
            "    set = replacement\n"
        ),
        (
            "class PretendSet:\n"
            "    def __call__(self, values):\n"
            "        return values\n"
            "\n"
            "def test_set(set, values):\n"
            "    assert set(values) == set()\n"
        ),
    ],
)
def test_unwarranted_set_receiver_is_not_factory_owned(source: str) -> None:
    context = FactoryBuildContext(
        filename="set_call.py",
        catalog=default_catalog(),
    )
    built = build_node(
        _bare_builtin_call_site(source, "set"),
        filename="set_call.py",
        role=SugarRole.TERM,
        ctx=context,
    )

    assert built.audit_row.selected != "BuiltinCalleeUniverseSugar"


def test_set_witness_pair_is_enrolled() -> None:
    assert "set_builtin_universe_coordinate" in {
        pair.name for pair in BuiltinCalleeUniverseSugar.witnesses()
    }


def test_authenticated_hasattr_selects_one_factory_owner() -> None:
    source = "def test_hasattr(obj, name):\n" "    assert hasattr(obj, name)\n"
    context = FactoryBuildContext(
        filename="hasattr_call.py",
        catalog=default_catalog(),
    )
    built = build_node(
        _bare_builtin_call_site(source, "hasattr"),
        filename="hasattr_call.py",
        role=SugarRole.TERM,
        ctx=context,
    )

    assert built.audit_row.selected == "BuiltinCalleeUniverseSugar"


@pytest.mark.parametrize(
    "source",
    [
        ("def test_hasattr(hasattr, obj, name):\n" "    assert hasattr(obj, name)\n"),
        (
            "def test_hasattr(obj, name):\n"
            "    assert hasattr(obj, name)\n"
            "    hasattr = replacement\n"
        ),
        (
            "class PretendHasattr:\n"
            "    def __call__(self, obj, name):\n"
            "        return True\n"
            "\n"
            "def test_hasattr(hasattr, obj, name):\n"
            "    assert hasattr(obj, name)\n"
        ),
    ],
)
def test_unwarranted_hasattr_receiver_is_not_factory_owned(source: str) -> None:
    context = FactoryBuildContext(
        filename="hasattr_call.py",
        catalog=default_catalog(),
    )
    built = build_node(
        _bare_builtin_call_site(source, "hasattr"),
        filename="hasattr_call.py",
        role=SugarRole.TERM,
        ctx=context,
    )

    assert built.audit_row.selected != "BuiltinCalleeUniverseSugar"


def test_hasattr_witness_pair_is_enrolled() -> None:
    assert "hasattr_builtin_universe_coordinate" in {
        pair.name for pair in BuiltinCalleeUniverseSugar.witnesses()
    }


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


def _issubdtype_call_site(source: str) -> SourceFragment:
    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "issubdtype"
    )
    return SourceFragment.from_node(call, "issubdtype.py", source=source)


def test_authenticated_numpy_issubdtype_selects_one_factory_owner() -> None:
    source = (
        "import numpy as np\n"
        "\n"
        "def test_dtype(left, right):\n"
        "    assert np.issubdtype(left, right)\n"
    )
    context = FactoryBuildContext(
        filename="issubdtype.py",
        catalog=default_catalog(),
    )
    built = build_node(
        _issubdtype_call_site(source),
        filename="issubdtype.py",
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
            "def test_dtype(np, left, right):\n"
            "    assert np.issubdtype(left, right)\n"
        ),
        (
            "import numpy as np\n"
            "\n"
            "def test_dtype(left, right):\n"
            "    assert np.issubdtype(left, right)\n"
            "    np = replacement\n"
        ),
        (
            "class PretendNumpy:\n"
            "    def issubdtype(self, left, right):\n"
            "        return True\n"
            "\n"
            "def test_dtype(np, left, right):\n"
            "    assert np.issubdtype(left, right)\n"
        ),
    ],
)
def test_unwarranted_issubdtype_receiver_is_not_factory_owned(source: str) -> None:
    context = FactoryBuildContext(
        filename="issubdtype.py",
        catalog=default_catalog(),
    )
    built = build_node(
        _issubdtype_call_site(source),
        filename="issubdtype.py",
        role=SugarRole.TERM,
        ctx=context,
    )

    assert built.audit_row.selected != "BuiltinCalleeUniverseSugar"


def test_numpy_issubdtype_witness_pair_is_enrolled() -> None:
    assert "numpy_issubdtype_universe_coordinate" in {
        pair.name for pair in BuiltinCalleeUniverseSugar.witnesses()
    }


def _bound_callable_call_site(source: str) -> SourceFragment:
    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "f"
    )
    return SourceFragment.from_node(call, "bound_callable.py", source=source)


def test_import_anchored_receiver_binding_authenticates_bare_callable() -> None:
    source = (
        "import numpy as np\n"
        "_ArrayMemoryError = np._core._exceptions._ArrayMemoryError\n"
        "\n"
        "def test_size():\n"
        "    f = _ArrayMemoryError._size_to_string\n"
        "    assert f(0) == '0 bytes'\n"
    )
    site = _bound_callable_call_site(source)

    assert (
        recognize_callee_universe("call:f", site=site)
        is CalleeUniverseSupport.BOUND_SOURCE_CALLABLE
    )
    built = build_node(
        site,
        filename="bound_callable.py",
        role=SugarRole.TERM,
        ctx=FactoryBuildContext(
            filename="bound_callable.py",
            catalog=default_catalog(),
        ),
    )
    assert built.audit_row.selected == "BuiltinCalleeUniverseSugar"


@pytest.mark.parametrize(
    "source",
    [
        "def test_size():\n    assert f(0) == '0 bytes'\n",
        (
            "def test_size(receiver):\n"
            "    f = receiver._size_to_string\n"
            "    assert f(0) == '0 bytes'\n"
        ),
        (
            "import numpy as np\n"
            "_ArrayMemoryError = np._core._exceptions._ArrayMemoryError\n"
            "\n"
            "def test_size(f):\n"
            "    assert f(0) == '0 bytes'\n"
        ),
    ],
)
def test_unresolved_or_lookalike_f_stays_unowned(source: str) -> None:
    site = _bound_callable_call_site(source)

    assert recognize_callee_universe("call:f", site=site) is None
    built = build_node(
        site,
        filename="bound_callable.py",
        role=SugarRole.TERM,
        ctx=FactoryBuildContext(
            filename="bound_callable.py",
            catalog=default_catalog(),
        ),
    )
    assert built.audit_row.selected != "BuiltinCalleeUniverseSugar"


def test_bound_source_callable_witness_pair_is_enrolled() -> None:
    assert "bound_source_callable_universe_coordinate" in {
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


def _numpy_dtype_call_site(source: str) -> SourceFragment:
    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "dtype"
    )
    return SourceFragment.from_node(call, "numpy_dtype.py", source=source)


def test_authenticated_numpy_dtype_selects_one_factory_owner() -> None:
    source = (
        "import numpy as np\n"
        "\n"
        "def test_dtype(value):\n"
        "    assert np.dtype(value) == np.dtype(value)\n"
    )
    context = FactoryBuildContext(
        filename="numpy_dtype.py",
        catalog=default_catalog(),
    )
    built = build_node(
        _numpy_dtype_call_site(source),
        filename="numpy_dtype.py",
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
            "def test_dtype(np, value):\n"
            "    assert np.dtype(value) == np.dtype(value)\n"
        ),
        (
            "import numpy as np\n"
            "\n"
            "def test_dtype(value):\n"
            "    assert np.dtype(value) == np.dtype(value)\n"
            "    np = replacement\n"
        ),
        (
            "import struct as np\n"
            "\n"
            "def test_dtype(value):\n"
            "    assert np.dtype(value) == np.dtype(value)\n"
        ),
        (
            "def test_dtype(value):\n"
            "    assert numpy.dtype(value) == numpy.dtype(value)\n"
        ),
    ],
)
def test_unwarranted_numpy_dtype_receiver_is_not_factory_owned(source: str) -> None:
    context = FactoryBuildContext(
        filename="numpy_dtype.py",
        catalog=default_catalog(),
    )
    built = build_node(
        _numpy_dtype_call_site(source),
        filename="numpy_dtype.py",
        role=SugarRole.TERM,
        ctx=context,
    )

    assert built.audit_row.selected != "BuiltinCalleeUniverseSugar"


def test_numpy_dtype_witness_pair_is_enrolled() -> None:
    assert "numpy_dtype_universe_coordinate" in {
        pair.name for pair in BuiltinCalleeUniverseSugar.witnesses()
    }


def _numpy_dtype_result_call_site(source: str) -> SourceFragment:
    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Attribute) and node.func.attr == "asarray")
            or (isinstance(node.func, ast.Name) and node.func.id == "asarray")
        )
    )
    return SourceFragment.from_node(call, "numpy_dtype_result.py", source=source)


def test_authenticated_numpy_dtype_result_selects_one_factory_owner() -> None:
    source = (
        "import numpy as np\n"
        "\n"
        "def test_dtype(value):\n"
        "    assert np.asarray(value).dtype == np.asarray(value).dtype\n"
    )
    context = FactoryBuildContext(
        filename="numpy_dtype_result.py",
        catalog=default_catalog(),
    )
    built = build_node(
        _numpy_dtype_result_call_site(source),
        filename="numpy_dtype_result.py",
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
            "def test_dtype(np, value):\n"
            "    assert np.asarray(value).dtype == value\n"
        ),
        (
            "import numpy as np\n"
            "\n"
            "def test_dtype(value):\n"
            "    assert np.asarray(value).dtype == value\n"
            "    np = replacement\n"
        ),
        (
            "class PretendNumpy:\n"
            "    def asarray(self, value):\n"
            "        return value\n"
            "\n"
            "def test_dtype(np, value):\n"
            "    assert np.asarray(value).dtype == value\n"
        ),
        ("def test_dtype(value):\n" "    assert numpy.asarray(value).dtype == value\n"),
    ],
)
def test_unwarranted_numpy_dtype_result_is_not_factory_owned(source: str) -> None:
    context = FactoryBuildContext(
        filename="numpy_dtype_result.py",
        catalog=default_catalog(),
    )
    built = build_node(
        _numpy_dtype_result_call_site(source),
        filename="numpy_dtype_result.py",
        role=SugarRole.TERM,
        ctx=context,
    )

    assert built.audit_row.selected != "BuiltinCalleeUniverseSugar"


def test_numpy_dtype_result_follows_authenticated_receiver_assignment() -> None:
    source = (
        "import numpy as np\n"
        "\n"
        "def test_dtype(value):\n"
        "    arr = np.array(value)\n"
        "    assert arr.astype(float).dtype == arr.astype(float).dtype\n"
    )
    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "astype"
    )
    context = FactoryBuildContext(
        filename="numpy_dtype_assignment.py",
        catalog=default_catalog(),
    )
    built = build_node(
        SourceFragment.from_node(
            call,
            "numpy_dtype_assignment.py",
            source=source,
        ),
        filename="numpy_dtype_assignment.py",
        role=SugarRole.TERM,
        ctx=context,
    )

    assert built.audit_row.selected == "BuiltinCalleeUniverseSugar"


def test_numpy_dtype_result_witness_pair_is_enrolled() -> None:
    assert "numpy_dtype_result_universe_coordinate" in {
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


def _item_call_site(source: str) -> SourceFragment:
    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "item"
    )
    return SourceFragment.from_node(call, "item.py", source=source)


def test_import_constructed_item_receiver_selects_one_factory_owner() -> None:
    source = (
        "import numpy as np\n"
        "\n"
        "def test_item(value):\n"
        "    arr = np.array([value], dtype=object)\n"
        "    assert arr.item() == value\n"
    )
    context = FactoryBuildContext(
        filename="item.py",
        catalog=default_catalog(),
    )
    built = build_node(
        _item_call_site(source),
        filename="item.py",
        role=SugarRole.TERM,
        ctx=context,
    )

    assert built.audit_row.selected == "BuiltinCalleeUniverseSugar"


@pytest.mark.parametrize(
    "source",
    [
        "def test_item(arr):\n    assert arr.item() == 0\n",
        (
            "def make(value):\n"
            "    return value\n"
            "\n"
            "def test_item(value):\n"
            "    arr = make(value)\n"
            "    assert arr.item() == value\n"
        ),
        (
            "def make(value):\n"
            "    return value\n"
            "\n"
            "def test_item(value):\n"
            "    assert make(value).item() == value\n"
        ),
        (
            "import numpy as np\n"
            "\n"
            "def test_item(value):\n"
            "    arr = np.array([value], dtype=object)\n"
            "    arr = replacement\n"
            "    assert arr.item() == value\n"
        ),
    ],
)
def test_unresolved_item_receiver_is_not_factory_owned(source: str) -> None:
    context = FactoryBuildContext(
        filename="item.py",
        catalog=default_catalog(),
    )
    built = build_node(
        _item_call_site(source),
        filename="item.py",
        role=SugarRole.TERM,
        ctx=context,
    )

    assert built.audit_row.selected != "BuiltinCalleeUniverseSugar"


def test_item_witness_pair_is_enrolled() -> None:
    assert "item_receiver_universe_coordinate" in {
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


def _stdlib_attr_call_site(source: str, member: str, filename: str) -> SourceFragment:
    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == member
    )
    return SourceFragment.from_node(call, filename, source=source)


def _stdlib_name_call_site(source: str, name: str, filename: str) -> SourceFragment:
    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == name
    )
    return SourceFragment.from_node(call, filename, source=source)


def test_authenticated_json_loads_selects_one_factory_owner() -> None:
    source = (
        "import json\n"
        "\n"
        "def test_loads(payload):\n"
        "    assert json.loads(payload) == json.loads(payload)\n"
    )
    context = FactoryBuildContext(
        filename="json_loads.py",
        catalog=default_catalog(),
    )
    built = build_node(
        _stdlib_attr_call_site(source, "loads", "json_loads.py"),
        filename="json_loads.py",
        role=SugarRole.TERM,
        ctx=context,
    )

    assert built.audit_row.selected == "BuiltinCalleeUniverseSugar"


def test_authenticated_from_import_json_loads_selects_one_factory_owner() -> None:
    source = (
        "from json import loads\n"
        "\n"
        "def test_loads(payload):\n"
        "    assert loads(payload) == loads(payload)\n"
    )
    context = FactoryBuildContext(
        filename="json_loads_from.py",
        catalog=default_catalog(),
    )
    built = build_node(
        _stdlib_name_call_site(source, "loads", "json_loads_from.py"),
        filename="json_loads_from.py",
        role=SugarRole.TERM,
        ctx=context,
    )

    assert built.audit_row.selected == "BuiltinCalleeUniverseSugar"


@pytest.mark.parametrize(
    "source",
    [
        (
            "import json\n"
            "\n"
            "def test_loads(json, payload):\n"
            "    assert json.loads(payload) == json.loads(payload)\n"
        ),
        (
            "import json\n"
            "\n"
            "def test_loads(payload):\n"
            "    assert json.loads(payload) == json.loads(payload)\n"
            "    json = replacement\n"
        ),
        (
            "import math as json\n"
            "\n"
            "def test_loads(payload):\n"
            "    assert json.loads(payload) == json.loads(payload)\n"
        ),
        (
            "def test_loads(payload):\n"
            "    assert json.loads(payload) == json.loads(payload)\n"
        ),
    ],
)
def test_unwarranted_json_loads_receiver_is_not_factory_owned(source: str) -> None:
    context = FactoryBuildContext(
        filename="json_loads.py",
        catalog=default_catalog(),
    )
    built = build_node(
        _stdlib_attr_call_site(source, "loads", "json_loads.py"),
        filename="json_loads.py",
        role=SugarRole.TERM,
        ctx=context,
    )

    assert built.audit_row.selected != "BuiltinCalleeUniverseSugar"


def test_json_loads_witness_pair_is_enrolled() -> None:
    assert "json_loads_universe_coordinate" in {
        pair.name for pair in BuiltinCalleeUniverseSugar.witnesses()
    }


def test_authenticated_dataclasses_asdict_selects_one_factory_owner() -> None:
    source = (
        "import dataclasses\n"
        "\n"
        "def test_asdict(value):\n"
        "    assert dataclasses.asdict(value) == dataclasses.asdict(value)\n"
    )
    context = FactoryBuildContext(
        filename="dataclasses_asdict.py",
        catalog=default_catalog(),
    )
    built = build_node(
        _stdlib_attr_call_site(source, "asdict", "dataclasses_asdict.py"),
        filename="dataclasses_asdict.py",
        role=SugarRole.TERM,
        ctx=context,
    )

    assert built.audit_row.selected == "BuiltinCalleeUniverseSugar"


def test_authenticated_from_import_asdict_selects_one_factory_owner() -> None:
    source = (
        "from dataclasses import asdict\n"
        "\n"
        "def test_asdict(value):\n"
        "    assert asdict(value) == asdict(value)\n"
    )
    context = FactoryBuildContext(
        filename="asdict_from.py",
        catalog=default_catalog(),
    )
    built = build_node(
        _stdlib_name_call_site(source, "asdict", "asdict_from.py"),
        filename="asdict_from.py",
        role=SugarRole.TERM,
        ctx=context,
    )

    assert built.audit_row.selected == "BuiltinCalleeUniverseSugar"


@pytest.mark.parametrize(
    "source",
    [
        (
            "import dataclasses\n"
            "\n"
            "def test_asdict(dataclasses, value):\n"
            "    assert dataclasses.asdict(value) == dataclasses.asdict(value)\n"
        ),
        (
            "import dataclasses\n"
            "\n"
            "def test_asdict(value):\n"
            "    assert dataclasses.asdict(value) == dataclasses.asdict(value)\n"
            "    dataclasses = replacement\n"
        ),
        (
            "import math as dataclasses\n"
            "\n"
            "def test_asdict(value):\n"
            "    assert dataclasses.asdict(value) == dataclasses.asdict(value)\n"
        ),
        (
            "def test_asdict(value):\n"
            "    assert dataclasses.asdict(value) == dataclasses.asdict(value)\n"
        ),
    ],
)
def test_unwarranted_dataclasses_asdict_receiver_is_not_factory_owned(
    source: str,
) -> None:
    context = FactoryBuildContext(
        filename="dataclasses_asdict.py",
        catalog=default_catalog(),
    )
    built = build_node(
        _stdlib_attr_call_site(source, "asdict", "dataclasses_asdict.py"),
        filename="dataclasses_asdict.py",
        role=SugarRole.TERM,
        ctx=context,
    )

    assert built.audit_row.selected != "BuiltinCalleeUniverseSugar"


def test_dataclasses_asdict_witness_pair_is_enrolled() -> None:
    assert "dataclasses_asdict_universe_coordinate" in {
        pair.name for pair in BuiltinCalleeUniverseSugar.witnesses()
    }
