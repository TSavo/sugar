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
        "any",
        "min",
        "max",
        "sum",
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
        "numpy.isdtype",
        "numpy.datetime_data",
        "numpy.f2py.crackfortran.markinnerspaces",
        "numpy._core._multiarray_tests.identity_hash_set_item_default",
        "numpy.ndarray.tobytes",
        "numpy._core.multiarray.get_handler_name",
        "numpy._core._multiarray_tests.run_byteorder_converter",
        "re.Pattern.search",
        "json.loads",
        "dataclasses.asdict",
        "dataclasses.is_dataclass",
        "math.isclose",
        "textwrap.dedent",
        "numpy.int64.to_device",
    } <= (BuiltinCalleeUniverseSugar.universe_coordinates)
    assert {
        "all_builtin_universe_coordinate",
        "any_builtin_universe_coordinate",
        "min_builtin_universe_coordinate",
        "max_builtin_universe_coordinate",
        "sum_builtin_universe_coordinate",
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
        "numpy_shares_memory_universe_coordinate",
        "numpy_isdtype_universe_coordinate",
        "numpy_datetime_data_universe_coordinate",
        "numpy_markinnerspaces_universe_coordinate",
        "numpy_identity_hash_set_item_default_universe_coordinate",
        "numpy_array_tobytes_universe_coordinate",
        "get_handler_name_builtin_universe_coordinate",
        "conv_builtin_universe_coordinate",
        "regex_search_builtin_universe_coordinate",
        "json_loads_universe_coordinate",
        "dataclasses_asdict_universe_coordinate",
        "dataclasses_is_dataclass_universe_coordinate",
        "math_isclose_universe_coordinate",
        "textwrap_dedent_universe_coordinate",
        "numpy_to_device_universe_coordinate",
        "type-subroutine_universe_coordinate",
        "simple-subroutine_universe_coordinate",
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


@pytest.mark.parametrize(
    ("callee", "source"),
    [
        ("any", "def test_any(value):\n    assert any(value)\n"),
        ("min", "def test_min(value):\n    assert min(value) == 0\n"),
        ("max", "def test_max(value):\n    assert max(value) == 0\n"),
        ("sum", "def test_sum(value):\n    assert sum(value) == 0\n"),
    ],
)
def test_authenticated_bare_builtin_selects_one_factory_owner(
    callee: str, source: str
) -> None:
    context = FactoryBuildContext(
        filename=f"{callee}_call.py",
        catalog=default_catalog(),
    )
    built = build_node(
        _bare_builtin_call_site(source, callee),
        filename=f"{callee}_call.py",
        role=SugarRole.TERM,
        ctx=context,
    )

    assert built.audit_row.selected == "BuiltinCalleeUniverseSugar"


@pytest.mark.parametrize("callee", ["any", "min", "max", "sum"])
def test_unwarranted_bare_builtin_receiver_is_not_factory_owned(callee: str) -> None:
    sources = [
        f"def test_{callee}({callee}, value):\n    assert {callee}(value)\n",
        (
            f"def test_{callee}(value):\n"
            f"    assert {callee}(value)\n"
            f"    {callee} = replacement\n"
        ),
    ]
    context = FactoryBuildContext(
        filename=f"{callee}_call.py",
        catalog=default_catalog(),
    )
    for source in sources:
        built = build_node(
            _bare_builtin_call_site(source, callee),
            filename=f"{callee}_call.py",
            role=SugarRole.TERM,
            ctx=context,
        )
        assert built.audit_row.selected != "BuiltinCalleeUniverseSugar"


@pytest.mark.parametrize("callee", ["any", "min", "max", "sum"])
def test_bare_builtin_witness_pair_is_enrolled(callee: str) -> None:
    assert f"{callee}_builtin_universe_coordinate" in {
        pair.name for pair in BuiltinCalleeUniverseSugar.witnesses()
    }


def test_authenticated_dataclasses_is_dataclass_selects_one_factory_owner() -> None:
    source = (
        "import dataclasses\n"
        "\n"
        "def test_is_dataclass(value):\n"
        "    assert dataclasses.is_dataclass(value) == dataclasses.is_dataclass(value)\n"
    )
    context = FactoryBuildContext(
        filename="dataclasses_is_dataclass.py",
        catalog=default_catalog(),
    )
    built = build_node(
        _stdlib_attr_call_site(source, "is_dataclass", "dataclasses_is_dataclass.py"),
        filename="dataclasses_is_dataclass.py",
        role=SugarRole.TERM,
        ctx=context,
    )

    assert built.audit_row.selected == "BuiltinCalleeUniverseSugar"


def test_authenticated_from_import_is_dataclass_selects_one_factory_owner() -> None:
    source = (
        "from dataclasses import is_dataclass\n"
        "\n"
        "def test_is_dataclass(value):\n"
        "    assert is_dataclass(value) == is_dataclass(value)\n"
    )
    context = FactoryBuildContext(
        filename="is_dataclass_from.py",
        catalog=default_catalog(),
    )
    built = build_node(
        _stdlib_name_call_site(source, "is_dataclass", "is_dataclass_from.py"),
        filename="is_dataclass_from.py",
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
            "def test_is_dataclass(dataclasses, value):\n"
            "    assert dataclasses.is_dataclass(value)\n"
        ),
        (
            "import dataclasses\n"
            "\n"
            "def test_is_dataclass(value):\n"
            "    assert dataclasses.is_dataclass(value)\n"
            "    dataclasses = replacement\n"
        ),
        (
            "import math as dataclasses\n"
            "\n"
            "def test_is_dataclass(value):\n"
            "    assert dataclasses.is_dataclass(value)\n"
        ),
        (
            "def test_is_dataclass(value):\n"
            "    assert dataclasses.is_dataclass(value)\n"
        ),
    ],
)
def test_unwarranted_is_dataclass_receiver_is_not_factory_owned(source: str) -> None:
    context = FactoryBuildContext(
        filename="dataclasses_is_dataclass.py",
        catalog=default_catalog(),
    )
    built = build_node(
        _stdlib_attr_call_site(source, "is_dataclass", "dataclasses_is_dataclass.py"),
        filename="dataclasses_is_dataclass.py",
        role=SugarRole.TERM,
        ctx=context,
    )

    assert built.audit_row.selected != "BuiltinCalleeUniverseSugar"


def test_dataclasses_is_dataclass_witness_pair_is_enrolled() -> None:
    assert "dataclasses_is_dataclass_universe_coordinate" in {
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
                "numpy",
                "np",
                import_target="numpy",
                install_source_checked=True,
                resolved_value=TermValue("numpy"),
            ),
        ),
    )
    sugar = BuiltinCalleeUniverseSugar.new(site, ctx)
    assert isinstance(sugar, BuiltinCalleeUniverseSugar)

    lying = FactoryBuildContext(
        filename="numpy_can_cast.py",
        catalog=default_catalog(),
        temporal=TemporalContext.empty().bind_value(
            "np", ImportAliasValue("other", "np", import_target="other")
        ),
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


def _leaf_attr_call_site(source: str, leaf: str) -> SourceFragment:
    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == leaf
    )
    return SourceFragment.from_node(call, f"{leaf}.py", source=source)


def _bare_call_site(source: str, leaf: str) -> SourceFragment:
    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == leaf
    )
    return SourceFragment.from_node(call, f"{leaf}.py", source=source)


@pytest.mark.parametrize("leaf", ["t0", "selectedintkind", "foo", "to_Dt"])
def test_instance_module_attribute_call_authenticates(leaf: str) -> None:
    source = (
        "class _Mod:\n"
        "    @staticmethod\n"
        f"    def {leaf}(*args):\n"
        "        return args\n"
        "\n"
        "class Host:\n"
        "    module = _Mod\n"
        "\n"
        "    def test_a(self):\n"
        f"        assert self.module.{leaf}(1) == (1,)\n"
    )
    site = _leaf_attr_call_site(source, leaf)
    assert recognize_callee_universe(f"call:{leaf}", site=site) is not None
    built = build_node(
        site,
        filename=f"{leaf}.py",
        role=SugarRole.TERM,
        ctx=FactoryBuildContext(filename=f"{leaf}.py", catalog=default_catalog()),
    )
    assert built.audit_row.selected == "BuiltinCalleeUniverseSugar"


@pytest.mark.parametrize("leaf", ["t0", "selectedintkind", "foo", "to_Dt"])
def test_unresolved_leaf_attribute_call_stays_unowned(leaf: str) -> None:
    source = f"def test_a(module):\n" f"    assert module.{leaf}(1) == (1,)\n"
    site = _leaf_attr_call_site(source, leaf)
    assert recognize_callee_universe(f"call:{leaf}", site=site) is None
    built = build_node(
        site,
        filename=f"{leaf}.py",
        role=SugarRole.TERM,
        ctx=FactoryBuildContext(filename=f"{leaf}.py", catalog=default_catalog()),
    )
    assert built.audit_row.selected != "BuiltinCalleeUniverseSugar"


def test_selectedintkind_assignment_from_instance_module_authenticates() -> None:
    source = (
        "class _Mod:\n"
        "    @staticmethod\n"
        "    def selectedintkind(i):\n"
        "        return i\n"
        "\n"
        "class Host:\n"
        "    module = _Mod\n"
        "\n"
        "    def test_a(self):\n"
        "        selectedintkind = self.module.selectedintkind\n"
        "        assert selectedintkind(3) == 3\n"
    )
    site = _bare_call_site(source, "selectedintkind")
    assert recognize_callee_universe("call:selectedintkind", site=site) is not None
    built = build_node(
        site,
        filename="selectedintkind.py",
        role=SugarRole.TERM,
        ctx=FactoryBuildContext(
            filename="selectedintkind.py", catalog=default_catalog()
        ),
    )
    assert built.audit_row.selected == "BuiltinCalleeUniverseSugar"


def test_bound_ufunc_alias_authenticates_parameter_ufunc_stays_loud() -> None:
    bound = (
        "import numpy as np\n"
        "\n"
        "def test_a():\n"
        "    ufunc = np.add\n"
        "    assert ufunc(1, 2) == 3\n"
    )
    param = (
        "import numpy as np\n"
        "\n"
        "def test_a(ufunc):\n"
        "    assert ufunc(1, 2) == 3\n"
    )
    bound_site = _bare_call_site(bound, "ufunc")
    param_site = _bare_call_site(param, "ufunc")
    assert recognize_callee_universe("call:ufunc", site=bound_site) is not None
    assert recognize_callee_universe("call:ufunc", site=param_site) is None
    bound_built = build_node(
        bound_site,
        filename="ufunc.py",
        role=SugarRole.TERM,
        ctx=FactoryBuildContext(filename="ufunc.py", catalog=default_catalog()),
    )
    param_built = build_node(
        param_site,
        filename="ufunc.py",
        role=SugarRole.TERM,
        ctx=FactoryBuildContext(filename="ufunc.py", catalog=default_catalog()),
    )
    assert bound_built.audit_row.selected == "BuiltinCalleeUniverseSugar"
    assert param_built.audit_row.selected != "BuiltinCalleeUniverseSugar"


def test_path_resolve_authenticates_unresolved_stays_loud() -> None:
    good = (
        "import pathlib\n"
        "\n"
        "def test_a(value):\n"
        "    path = pathlib.Path(value)\n"
        "    assert path.resolve() is not None\n"
    )
    bad = "def test_a(path):\n" "    assert path.resolve() is not None\n"
    good_site = _leaf_attr_call_site(good, "resolve")
    bad_site = _leaf_attr_call_site(bad, "resolve")
    assert recognize_callee_universe("call:resolve", site=good_site) is not None
    assert recognize_callee_universe("call:resolve", site=bad_site) is None
    good_built = build_node(
        good_site,
        filename="resolve.py",
        role=SugarRole.TERM,
        ctx=FactoryBuildContext(filename="resolve.py", catalog=default_catalog()),
    )
    bad_built = build_node(
        bad_site,
        filename="resolve.py",
        role=SugarRole.TERM,
        ctx=FactoryBuildContext(filename="resolve.py", catalog=default_catalog()),
    )
    assert good_built.audit_row.selected == "BuiltinCalleeUniverseSugar"
    assert bad_built.audit_row.selected != "BuiltinCalleeUniverseSugar"


def test_batch_six_witness_pairs_are_enrolled() -> None:
    names = {pair.name for pair in BuiltinCalleeUniverseSugar.witnesses()}
    assert {
        "path_resolve_universe_coordinate",
        "ufunc_universe_coordinate",
        "t0_universe_coordinate",
        "selectedintkind_universe_coordinate",
        "foo_universe_coordinate",
        "to-Dt_universe_coordinate",
    } <= names


# --- SciPy / stdlib import-identity batch (#5457–#5461, window 292) ---


def _import_leaf_call_site(source: str, leaf: str, filename: str) -> SourceFragment:
    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Attribute) and node.func.attr == leaf)
            or (isinstance(node.func, ast.Name) and node.func.id == leaf)
        )
    )
    return SourceFragment.from_node(call, filename, source=source)


def test_authenticated_math_isclose_selects_one_factory_owner() -> None:
    source = (
        "import math\n" "\n" "def test_close(a, b):\n" "    assert math.isclose(a, b)\n"
    )
    context = FactoryBuildContext(filename="math_isclose.py", catalog=default_catalog())
    built = build_node(
        _import_leaf_call_site(source, "isclose", "math_isclose.py"),
        filename="math_isclose.py",
        role=SugarRole.TERM,
        ctx=context,
    )
    assert built.audit_row.selected == "BuiltinCalleeUniverseSugar"


@pytest.mark.parametrize(
    "source",
    [
        (
            "import math\n"
            "\n"
            "def test_close(math, a, b):\n"
            "    assert math.isclose(a, b)\n"
        ),
        (
            "import math\n"
            "\n"
            "def test_close(a, b):\n"
            "    assert math.isclose(a, b)\n"
            "    math = replacement\n"
        ),
        ("def test_close(a, b):\n" "    assert math.isclose(a, b)\n"),
    ],
)
def test_unwarranted_math_isclose_is_not_factory_owned(source: str) -> None:
    context = FactoryBuildContext(filename="math_isclose.py", catalog=default_catalog())
    built = build_node(
        _import_leaf_call_site(source, "isclose", "math_isclose.py"),
        filename="math_isclose.py",
        role=SugarRole.TERM,
        ctx=context,
    )
    assert built.audit_row.selected != "BuiltinCalleeUniverseSugar"


def test_math_isclose_witness_pair_is_enrolled() -> None:
    assert "math_isclose_universe_coordinate" in {
        pair.name for pair in BuiltinCalleeUniverseSugar.witnesses()
    }


def test_authenticated_numpy_result_type_selects_one_factory_owner() -> None:
    source = (
        "import numpy as np\n"
        "\n"
        "def test_rt(a, b):\n"
        "    assert np.result_type(a, b) == np.result_type(a, b)\n"
    )
    context = FactoryBuildContext(filename="result_type.py", catalog=default_catalog())
    built = build_node(
        _import_leaf_call_site(source, "result_type", "result_type.py"),
        filename="result_type.py",
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
            "def test_rt(np, a, b):\n"
            "    assert np.result_type(a, b) == a\n"
        ),
        (
            "import numpy as np\n"
            "\n"
            "def test_rt(a, b):\n"
            "    assert np.result_type(a, b) == a\n"
            "    np = replacement\n"
        ),
        ("def test_rt(a, b):\n" "    assert numpy.result_type(a, b) == a\n"),
    ],
)
def test_unwarranted_numpy_result_type_is_not_factory_owned(source: str) -> None:
    context = FactoryBuildContext(filename="result_type.py", catalog=default_catalog())
    built = build_node(
        _import_leaf_call_site(source, "result_type", "result_type.py"),
        filename="result_type.py",
        role=SugarRole.TERM,
        ctx=context,
    )
    assert built.audit_row.selected != "BuiltinCalleeUniverseSugar"


def test_numpy_result_type_witness_pair_is_enrolled() -> None:
    assert "numpy_result_type_universe_coordinate" in {
        pair.name for pair in BuiltinCalleeUniverseSugar.witnesses()
    }


def test_authenticated_numpy_isdtype_selects_one_factory_owner() -> None:
    source = (
        "import numpy as np\n"
        "\n"
        "def test_id(dt):\n"
        "    assert np.isdtype(dt, 'real floating')\n"
    )
    context = FactoryBuildContext(filename="isdtype.py", catalog=default_catalog())
    built = build_node(
        _import_leaf_call_site(source, "isdtype", "isdtype.py"),
        filename="isdtype.py",
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
            "def test_id(np, dt):\n"
            "    assert np.isdtype(dt, 'real floating')\n"
        ),
        ("def test_id(dt):\n" "    assert isdtype(dt, 'real floating')\n"),
    ],
)
def test_unwarranted_numpy_isdtype_is_not_factory_owned(source: str) -> None:
    context = FactoryBuildContext(filename="isdtype.py", catalog=default_catalog())
    built = build_node(
        _import_leaf_call_site(source, "isdtype", "isdtype.py"),
        filename="isdtype.py",
        role=SugarRole.TERM,
        ctx=context,
    )
    assert built.audit_row.selected != "BuiltinCalleeUniverseSugar"


def test_numpy_isdtype_witness_pair_is_enrolled() -> None:
    assert "numpy_isdtype_universe_coordinate" in {
        pair.name for pair in BuiltinCalleeUniverseSugar.witnesses()
    }


def test_authenticated_numpy_datetime_data_selects_one_factory_owner() -> None:
    source = (
        "import numpy as np\n"
        "\n"
        "def test_dd(dt):\n"
        "    assert np.datetime_data(dt) == np.datetime_data(dt)\n"
    )
    context = FactoryBuildContext(
        filename="datetime_data.py", catalog=default_catalog()
    )
    built = build_node(
        _import_leaf_call_site(source, "datetime_data", "datetime_data.py"),
        filename="datetime_data.py",
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
            "def test_dd(np, dt):\n"
            "    assert np.datetime_data(dt) == 0\n"
        ),
        ("def test_dd(dt):\n" "    assert datetime_data(dt) == 0\n"),
    ],
)
def test_unwarranted_numpy_datetime_data_is_not_factory_owned(source: str) -> None:
    context = FactoryBuildContext(
        filename="datetime_data.py", catalog=default_catalog()
    )
    built = build_node(
        _import_leaf_call_site(source, "datetime_data", "datetime_data.py"),
        filename="datetime_data.py",
        role=SugarRole.TERM,
        ctx=context,
    )
    assert built.audit_row.selected != "BuiltinCalleeUniverseSugar"


def test_numpy_datetime_data_witness_pair_is_enrolled() -> None:
    assert "numpy_datetime_data_universe_coordinate" in {
        pair.name for pair in BuiltinCalleeUniverseSugar.witnesses()
    }


def test_authenticated_scipy_issymmetric_selects_one_factory_owner() -> None:
    source = (
        "import numpy as np\n"
        "from scipy.linalg import issymmetric\n"
        "\n"
        "def test_sym(a):\n"
        "    assert issymmetric(a)\n"
    )
    context = FactoryBuildContext(filename="issym.py", catalog=default_catalog())
    built = build_node(
        _import_leaf_call_site(source, "issymmetric", "issym.py"),
        filename="issym.py",
        role=SugarRole.TERM,
        ctx=context,
    )
    assert built.audit_row.selected == "BuiltinCalleeUniverseSugar"


@pytest.mark.parametrize(
    "source",
    [
        (
            "from scipy.linalg import issymmetric\n"
            "\n"
            "def test_sym(issymmetric, a):\n"
            "    assert issymmetric(a)\n"
        ),
        ("def test_sym(a):\n" "    assert scipy.linalg.issymmetric(a)\n"),
    ],
)
def test_unwarranted_scipy_issymmetric_is_not_factory_owned(source: str) -> None:
    context = FactoryBuildContext(filename="issym.py", catalog=default_catalog())
    built = build_node(
        _import_leaf_call_site(source, "issymmetric", "issym.py"),
        filename="issym.py",
        role=SugarRole.TERM,
        ctx=context,
    )
    assert built.audit_row.selected != "BuiltinCalleeUniverseSugar"


def test_scipy_issymmetric_witness_pair_is_enrolled() -> None:
    assert "scipy_linalg_issymmetric_universe_coordinate" in {
        pair.name for pair in BuiltinCalleeUniverseSugar.witnesses()
    }


def test_authenticated_scipy_ishermitian_selects_one_factory_owner() -> None:
    source = (
        "import numpy as np\n"
        "from scipy.linalg import ishermitian\n"
        "\n"
        "def test_herm(a):\n"
        "    assert ishermitian(a)\n"
    )
    context = FactoryBuildContext(filename="isherm.py", catalog=default_catalog())
    built = build_node(
        _import_leaf_call_site(source, "ishermitian", "isherm.py"),
        filename="isherm.py",
        role=SugarRole.TERM,
        ctx=context,
    )
    assert built.audit_row.selected == "BuiltinCalleeUniverseSugar"


@pytest.mark.parametrize(
    "source",
    [
        (
            "from scipy.linalg import ishermitian\n"
            "\n"
            "def test_herm(ishermitian, a):\n"
            "    assert ishermitian(a)\n"
        ),
        ("def test_herm(a):\n" "    assert scipy.linalg.ishermitian(a)\n"),
    ],
)
def test_unwarranted_scipy_ishermitian_is_not_factory_owned(source: str) -> None:
    context = FactoryBuildContext(filename="isherm.py", catalog=default_catalog())
    built = build_node(
        _import_leaf_call_site(source, "ishermitian", "isherm.py"),
        filename="isherm.py",
        role=SugarRole.TERM,
        ctx=context,
    )
    assert built.audit_row.selected != "BuiltinCalleeUniverseSugar"


def test_scipy_ishermitian_witness_pair_is_enrolled() -> None:
    assert "scipy_linalg_ishermitian_universe_coordinate" in {
        pair.name for pair in BuiltinCalleeUniverseSugar.witnesses()
    }


def test_authenticated_scipy_fft_get_workers_selects_one_factory_owner() -> None:
    source = (
        "import scipy.fft as fft\n"
        "\n"
        "def test_workers():\n"
        "    assert fft.get_workers() == fft.get_workers()\n"
    )
    context = FactoryBuildContext(filename="get_workers.py", catalog=default_catalog())
    built = build_node(
        _import_leaf_call_site(source, "get_workers", "get_workers.py"),
        filename="get_workers.py",
        role=SugarRole.TERM,
        ctx=context,
    )
    assert built.audit_row.selected == "BuiltinCalleeUniverseSugar"


@pytest.mark.parametrize(
    "source",
    [
        (
            "import scipy.fft as fft\n"
            "\n"
            "def test_workers(fft):\n"
            "    assert fft.get_workers() == 1\n"
        ),
        (
            "import scipy.fft as fft\n"
            "\n"
            "def test_workers():\n"
            "    assert fft.get_workers() == 1\n"
            "    fft = replacement\n"
        ),
        ("def test_workers():\n" "    assert scipy.fft.get_workers() == 1\n"),
    ],
)
def test_unwarranted_scipy_fft_get_workers_is_not_factory_owned(source: str) -> None:
    context = FactoryBuildContext(filename="get_workers.py", catalog=default_catalog())
    built = build_node(
        _import_leaf_call_site(source, "get_workers", "get_workers.py"),
        filename="get_workers.py",
        role=SugarRole.TERM,
        ctx=context,
    )
    assert built.audit_row.selected != "BuiltinCalleeUniverseSugar"


def test_scipy_fft_get_workers_witness_pair_is_enrolled() -> None:
    assert "scipy_fft_get_workers_universe_coordinate" in {
        pair.name for pair in BuiltinCalleeUniverseSugar.witnesses()
    }


def test_pathlib_path_authenticates_unresolved_stays_loud() -> None:
    good = (
        "import pathlib\n"
        "\n"
        "def test_a(value):\n"
        "    assert pathlib.Path(value) is not None\n"
    )
    bad = "def test_a(pathlib, value):\n" "    assert pathlib.Path(value) is not None\n"
    good_site = _leaf_attr_call_site(good, "Path")
    bad_site = _leaf_attr_call_site(bad, "Path")
    assert recognize_callee_universe("call:pathlib.Path", site=good_site) is not None
    assert recognize_callee_universe("call:pathlib.Path", site=bad_site) is None
    good_built = build_node(
        good_site,
        filename="pathlib_path.py",
        role=SugarRole.TERM,
        ctx=FactoryBuildContext(filename="pathlib_path.py", catalog=default_catalog()),
    )
    bad_built = build_node(
        bad_site,
        filename="pathlib_path.py",
        role=SugarRole.TERM,
        ctx=FactoryBuildContext(filename="pathlib_path.py", catalog=default_catalog()),
    )
    assert good_built.audit_row.selected == "BuiltinCalleeUniverseSugar"
    assert bad_built.audit_row.selected != "BuiltinCalleeUniverseSugar"


def test_standard_gamma_authenticates_helper_and_direct_unresolved_stays_loud() -> None:
    helper = (
        "from numpy.random import MT19937, Generator\n"
        "\n"
        "class TestRegression:\n"
        "    def _create_generator(self):\n"
        "        return Generator(MT19937(121263137472525314065))\n"
        "\n"
        "    def test_gamma_0(self):\n"
        "        mt19937 = self._create_generator()\n"
        "        assert mt19937.standard_gamma(0.0) == 0.0\n"
    )
    direct = (
        "from numpy.random import MT19937, Generator\n"
        "\n"
        "def test_gamma():\n"
        "    mt19937 = Generator(MT19937(1))\n"
        "    assert mt19937.standard_gamma(0.0) == 0.0\n"
    )
    lookalike = (
        "def test_gamma(mt19937):\n" "    assert mt19937.standard_gamma(0.0) == 0.0\n"
    )
    helper_site = _leaf_attr_call_site(helper, "standard_gamma")
    direct_site = _leaf_attr_call_site(direct, "standard_gamma")
    bad_site = _leaf_attr_call_site(lookalike, "standard_gamma")
    assert (
        recognize_callee_universe("call:standard_gamma", site=helper_site) is not None
    )
    assert (
        recognize_callee_universe("call:standard_gamma", site=direct_site) is not None
    )
    assert recognize_callee_universe("call:standard_gamma", site=bad_site) is None
    for site, expect_owned in (
        (helper_site, True),
        (direct_site, True),
        (bad_site, False),
    ):
        built = build_node(
            site,
            filename="standard_gamma.py",
            role=SugarRole.TERM,
            ctx=FactoryBuildContext(
                filename="standard_gamma.py", catalog=default_catalog()
            ),
        )
        if expect_owned:
            assert built.audit_row.selected == "BuiltinCalleeUniverseSugar"
        else:
            assert built.audit_row.selected != "BuiltinCalleeUniverseSugar"


def test_subrout_default_authenticates_unresolved_module_stays_loud() -> None:
    good = (
        "class _Mod:\n"
        "    @staticmethod\n"
        "    def subrout_default(a, b):\n"
        "        return a + b\n"
        "\n"
        "class Host:\n"
        "    module = _Mod\n"
        "\n"
        "    def test_a(self):\n"
        "        assert self.module.subrout_default(200, 12) == 212\n"
    )
    bad = "def test_a(module):\n" "    assert module.subrout_default(200, 12) == 212\n"
    good_site = _leaf_attr_call_site(good, "subrout_default")
    bad_site = _leaf_attr_call_site(bad, "subrout_default")
    assert recognize_callee_universe("call:subrout_default", site=good_site) is not None
    assert recognize_callee_universe("call:subrout_default", site=bad_site) is None
    good_built = build_node(
        good_site,
        filename="subrout.py",
        role=SugarRole.TERM,
        ctx=FactoryBuildContext(filename="subrout.py", catalog=default_catalog()),
    )
    bad_built = build_node(
        bad_site,
        filename="subrout.py",
        role=SugarRole.TERM,
        ctx=FactoryBuildContext(filename="subrout.py", catalog=default_catalog()),
    )
    assert good_built.audit_row.selected == "BuiltinCalleeUniverseSugar"
    assert bad_built.audit_row.selected != "BuiltinCalleeUniverseSugar"


def test_eval_scalar_authenticates_parameter_lookalike_stays_loud() -> None:
    good = (
        "from numpy.f2py import crackfortran\n"
        "\n"
        "class TestEval:\n"
        "    def test_eval_scalar(self):\n"
        "        eval_scalar = crackfortran._eval_scalar\n"
        "        assert eval_scalar('123', {}) == '123'\n"
    )
    bad = (
        "def test_eval_scalar(eval_scalar):\n"
        "    assert eval_scalar('123', {}) == '123'\n"
    )
    good_site = _bare_call_site(good, "eval_scalar")
    bad_site = _bare_call_site(bad, "eval_scalar")
    assert recognize_callee_universe("call:eval_scalar", site=good_site) is not None
    assert recognize_callee_universe("call:eval_scalar", site=bad_site) is None
    good_built = build_node(
        good_site,
        filename="eval_scalar.py",
        role=SugarRole.TERM,
        ctx=FactoryBuildContext(filename="eval_scalar.py", catalog=default_catalog()),
    )
    bad_built = build_node(
        bad_site,
        filename="eval_scalar.py",
        role=SugarRole.TERM,
        ctx=FactoryBuildContext(filename="eval_scalar.py", catalog=default_catalog()),
    )
    assert good_built.audit_row.selected == "BuiltinCalleeUniverseSugar"
    assert bad_built.audit_row.selected != "BuiltinCalleeUniverseSugar"


def test_numpy_batch_four_witness_pairs_are_enrolled() -> None:
    names = {pair.name for pair in BuiltinCalleeUniverseSugar.witnesses()}
    assert {
        "pathlib_path_universe_coordinate",
        "numpy_standard_gamma_universe_coordinate",
        "numpy_subrout_default_universe_coordinate",
        "numpy_eval_scalar_universe_coordinate",
    } <= names


def test_authenticated_numpy_markinnerspaces_selects_one_factory_owner() -> None:
    source = (
        "from numpy.f2py.crackfortran import markinnerspaces\n"
        "\n"
        "def test_mark(s):\n"
        "    assert markinnerspaces(s) == markinnerspaces(s)\n"
    )
    context = FactoryBuildContext(
        filename="markinnerspaces.py", catalog=default_catalog()
    )
    built = build_node(
        _import_leaf_call_site(source, "markinnerspaces", "markinnerspaces.py"),
        filename="markinnerspaces.py",
        role=SugarRole.TERM,
        ctx=context,
    )
    assert built.audit_row.selected == "BuiltinCalleeUniverseSugar"


@pytest.mark.parametrize(
    "source",
    [
        (
            "from numpy.f2py.crackfortran import markinnerspaces\n"
            "\n"
            "def test_mark(markinnerspaces, s):\n"
            "    assert markinnerspaces(s) == s\n"
        ),
        (
            "def test_mark(s):\n"
            "    assert markinnerspaces(s) == s\n"
        ),
    ],
)
def test_unwarranted_numpy_markinnerspaces_is_not_factory_owned(source: str) -> None:
    context = FactoryBuildContext(
        filename="markinnerspaces.py", catalog=default_catalog()
    )
    built = build_node(
        _import_leaf_call_site(source, "markinnerspaces", "markinnerspaces.py"),
        filename="markinnerspaces.py",
        role=SugarRole.TERM,
        ctx=context,
    )
    assert built.audit_row.selected != "BuiltinCalleeUniverseSugar"


def test_numpy_markinnerspaces_witness_pair_is_enrolled() -> None:
    assert "numpy_markinnerspaces_universe_coordinate" in {
        pair.name for pair in BuiltinCalleeUniverseSugar.witnesses()
    }


def test_authenticated_identity_hash_set_item_default_selects_one_factory_owner() -> None:
    source = (
        "from numpy._core._multiarray_tests import identity_hash_set_item_default\n"
        "\n"
        "def test_hash(ht, key, value):\n"
        "    assert identity_hash_set_item_default(ht, key, value) is value\n"
    )
    context = FactoryBuildContext(
        filename="identity_hash.py", catalog=default_catalog()
    )
    built = build_node(
        _import_leaf_call_site(
            source, "identity_hash_set_item_default", "identity_hash.py"
        ),
        filename="identity_hash.py",
        role=SugarRole.TERM,
        ctx=context,
    )
    assert built.audit_row.selected == "BuiltinCalleeUniverseSugar"


@pytest.mark.parametrize(
    "source",
    [
        (
            "from numpy._core._multiarray_tests import identity_hash_set_item_default\n"
            "\n"
            "def test_hash(identity_hash_set_item_default, ht, key, value):\n"
            "    assert identity_hash_set_item_default(ht, key, value) is value\n"
        ),
        (
            "def test_hash(ht, key, value):\n"
            "    assert identity_hash_set_item_default(ht, key, value) is value\n"
        ),
    ],
)
def test_unwarranted_identity_hash_set_item_default_is_not_factory_owned(
    source: str,
) -> None:
    context = FactoryBuildContext(
        filename="identity_hash.py", catalog=default_catalog()
    )
    built = build_node(
        _import_leaf_call_site(
            source, "identity_hash_set_item_default", "identity_hash.py"
        ),
        filename="identity_hash.py",
        role=SugarRole.TERM,
        ctx=context,
    )
    assert built.audit_row.selected != "BuiltinCalleeUniverseSugar"


def test_identity_hash_set_item_default_witness_pair_is_enrolled() -> None:
    assert "numpy_identity_hash_set_item_default_universe_coordinate" in {
        pair.name for pair in BuiltinCalleeUniverseSugar.witnesses()
    }


def test_authenticated_textwrap_dedent_selects_one_factory_owner() -> None:
    source = (
        "import textwrap\n"
        "\n"
        "def test_dedent(payload):\n"
        "    assert textwrap.dedent(payload) == textwrap.dedent(payload)\n"
    )
    built = build_node(
        _stdlib_attr_call_site(source, "dedent", "textwrap_dedent.py"),
        filename="textwrap_dedent.py",
        role=SugarRole.TERM,
        ctx=FactoryBuildContext(
            filename="textwrap_dedent.py",
            catalog=default_catalog(),
        ),
    )
    assert built.audit_row.selected == "BuiltinCalleeUniverseSugar"


@pytest.mark.parametrize(
    "source",
    [
        (
            "import textwrap\n"
            "\n"
            "def test_dedent(textwrap, payload):\n"
            "    assert textwrap.dedent(payload) == textwrap.dedent(payload)\n"
        ),
        (
            "import math as textwrap\n"
            "\n"
            "def test_dedent(payload):\n"
            "    assert textwrap.dedent(payload) == textwrap.dedent(payload)\n"
        ),
        (
            "def test_dedent(payload):\n"
            "    assert textwrap.dedent(payload) == textwrap.dedent(payload)\n"
        ),
    ],
)
def test_unwarranted_textwrap_dedent_receiver_is_not_factory_owned(source: str) -> None:
    built = build_node(
        _stdlib_attr_call_site(source, "dedent", "textwrap_dedent.py"),
        filename="textwrap_dedent.py",
        role=SugarRole.TERM,
        ctx=FactoryBuildContext(
            filename="textwrap_dedent.py",
            catalog=default_catalog(),
        ),
    )
    assert built.audit_row.selected != "BuiltinCalleeUniverseSugar"


def test_authenticated_to_device_selects_one_factory_owner() -> None:
    """Constructor-bound scalar — import identity of np.int64 + member."""
    source = (
        "import numpy as np\n"
        "\n"
        "def test_to_device():\n"
        "    scalar = np.int64(1)\n"
        "    assert scalar.to_device('cpu') is scalar\n"
    )
    built = build_node(
        _method_call_site(source, "to_device"),
        filename="to_device.py",
        role=SugarRole.TERM,
        ctx=FactoryBuildContext(filename="to_device.py", catalog=default_catalog()),
    )
    assert built.audit_row.selected == "BuiltinCalleeUniverseSugar"


def test_parametrized_to_device_stays_loud_without_logo_match() -> None:
    """Corpus form injects the receiver via decorator parameters.

    No structural decorator provenance without a vendor-literal match on
    pytest.mark.parametrize (ruled illegal; window 289 owns the real contract).
    The row stays loud — that is the correct outcome.
    """

    source = (
        "import pytest\n"
        "import numpy as np\n"
        "\n"
        "class TestDevice:\n"
        "    scalars = [np.int64(1), np.float64(1.0)]\n"
        "\n"
        "    @pytest.mark.parametrize('scalar', scalars)\n"
        "    def test_to_device(self, scalar):\n"
        "        assert scalar.to_device('cpu') is scalar\n"
    )
    filename = "numpy/_core/tests/test_scalar_methods.py"
    built = build_node(
        _method_call_site(source, "to_device"),
        filename=filename,
        role=SugarRole.TERM,
        ctx=FactoryBuildContext(filename=filename, catalog=default_catalog()),
    )
    assert built.audit_row.selected != "BuiltinCalleeUniverseSugar"


@pytest.mark.parametrize(
    "source",
    [
        "def test_to_device(scalar):\n    assert scalar.to_device('cpu') is scalar\n",
        (
            "import numpy as np\n"
            "\n"
            "def test_to_device():\n"
            "    scalar = np.int64(1)\n"
            "    scalar = replacement\n"
            "    assert scalar.to_device('cpu') is scalar\n"
        ),
    ],
)
def test_unwarranted_to_device_receiver_is_not_factory_owned(source: str) -> None:
    built = build_node(
        _method_call_site(source, "to_device"),
        filename="to_device.py",
        role=SugarRole.TERM,
        ctx=FactoryBuildContext(filename="to_device.py", catalog=default_catalog()),
    )
    assert built.audit_row.selected != "BuiltinCalleeUniverseSugar"


@pytest.mark.parametrize("member", ["type_subroutine", "simple_subroutine"])
def test_bound_f2py_module_member_selects_one_factory_owner(member: str) -> None:
    source = (
        "from . import util\n"
        "\n"
        "class TestExtension(util.F2PyTest):\n"
        "    sources = ['x.f']\n"
        "\n"
        "    def test_member(self):\n"
        f"        assert self.module.{member}(0) == 0\n"
    )
    filename = "numpy/f2py/tests/test_regression.py"
    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == member
    )
    site = SourceFragment.from_node(call, filename, source=source)
    built = build_node(
        site,
        filename=filename,
        role=SugarRole.TERM,
        ctx=FactoryBuildContext(filename=filename, catalog=default_catalog()),
    )
    assert built.audit_row.selected == "BuiltinCalleeUniverseSugar"
    assert (
        recognize_callee_universe(f"call:{member}", site=site)
        is CalleeUniverseSupport.BOUND_SOURCE_CALLABLE
    )


@pytest.mark.parametrize("member", ["type_subroutine", "simple_subroutine"])
def test_unwarranted_f2py_module_member_is_not_factory_owned(member: str) -> None:
    source = (
        "def test_member(module):\n"
        f"    assert module.{member}(0) == 0\n"
    )
    built = build_node(
        _method_call_site(source, member),
        filename="x.py",
        role=SugarRole.TERM,
        ctx=FactoryBuildContext(filename="x.py", catalog=default_catalog()),
    )
    assert built.audit_row.selected != "BuiltinCalleeUniverseSugar"
