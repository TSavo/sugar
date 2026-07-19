from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.recognition.callee_universe import (
    CalleeUniverseSupport,
    CalleeUniverseRecognition,
    recognize_authenticated_callee_identity,
    recognize_callee_universe,
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
        # bare ``type`` is owned by BuiltinTypeCallSugar (construction + universe).
        "dtype",
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
        "numpy.may_share_memory",
        "numpy.shares_memory",
        "numpy.ndarray.tobytes",
        "numpy.array.tobytes",
        "numpy.empty.tobytes",
        "numpy.empty_like.tobytes",
        "numpy.zeros.tobytes",
        "numpy.lib.stride_tricks.as_strided.tobytes",
        "numpy._core.multiarray.get_handler_name",
        "numpy._core.multiarray.get_handler_version",
        "checks.test_get_multi_index_iter_next",
        "numpy.f2py.extension.sum_and_double",
        "re.Pattern.search",
        "pathlib.Path",
        "pathlib.Path.resolve",
        "numpy.random.Generator.standard_gamma",
        "numpy.f2py.crackfortran._eval_scalar",
        "json.loads",
        "dataclasses.asdict",
        "dataclasses.is_dataclass",
        "math.isclose",
        "numpy.result_type",
        "scipy.linalg.issymmetric",
        "scipy.linalg.ishermitian",
        "scipy.fft.get_workers",
        "numpy.isdtype",
        "numpy.datetime_data",
        "numpy.f2py.crackfortran.markinnerspaces",
        "numpy._core._multiarray_tests.identity_hash_set_item_default",
        "textwrap.dedent",
        "numpy.int64.to_device",
        "numpy.uint64.to_device",
        "numpy.float64.to_device",
        "numpy.complex128.to_device",
        "numpy.bool.to_device",
        "numpy.bool_.to_device",
        *_CONVERTER_COORDINATES,
    }
)
# Must match recognition.callee_universe bare-builtin warrants this leaf owns.
# ``type`` is intentionally absent: BuiltinTypeCallSugar is its construction owner.
_BUILTIN_COORDINATES = frozenset(
    {"dtype", "all", "any", "min", "max", "sum", "list", "set", "hasattr"}
)
_RECEIVER_COORDINATES = frozenset({"item"})
# Leaf spellings that can still resolve into an authenticated coordinate.
# Plain-call owns refuses full import-identity work when the callee leaf cannot
# match; method receivers keep the Name-only path (class attribute aliases).
_AUTHENTICATED_PLAIN_LEAVES = frozenset(
    coordinate.rsplit(".", 1)[-1] for coordinate in _AUTHENTICATED_COORDINATES
)
_OWNED_IMPORTED_SUPPORT = frozenset(
    set(CalleeUniverseSupport)
    | {
        CalleeUniverseSupport.NUMPY_CAN_CAST,
        CalleeUniverseSupport.NUMPY_ISSUBDTYPE,
        CalleeUniverseSupport.NUMPY_ISNAN,
        CalleeUniverseSupport.NUMPY_ALL,
        CalleeUniverseSupport.NUMPY_DTYPE,
        CalleeUniverseSupport.NUMPY_MAY_SHARE_MEMORY,
        CalleeUniverseSupport.NUMPY_HANDLER_NAME,
        CalleeUniverseSupport.NUMPY_HANDLER_VERSION,
        CalleeUniverseSupport.NUMPY_CONVERTER,
        CalleeUniverseSupport.NUMPY_CHECKS,
        CalleeUniverseSupport.NUMPY_F2PY_EXTENSION,
        CalleeUniverseSupport.REGEX_SEARCH,
        CalleeUniverseSupport.JSON_LOADS,
        CalleeUniverseSupport.DATACLASSES_ASDICT,
        CalleeUniverseSupport.DATACLASSES_IS_DATACLASS,
        CalleeUniverseSupport.MATH_ISCLOSE,
        CalleeUniverseSupport.NUMPY_RESULT_TYPE,
        CalleeUniverseSupport.SCIPY_LINALG_ISSYMMETRIC,
        CalleeUniverseSupport.SCIPY_LINALG_ISHERMITIAN,
        CalleeUniverseSupport.SCIPY_FFT_GET_WORKERS,
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
        # factory.select asks every TERM claim. After parsed_locus_index, the
        # residual wall is import-identity / symtable work on Attribute Calls
        # whose attr cannot authenticate (``random.multinomial``, …). Refuse
        # that path structurally; one coordinate resolution is enough — do not
        # double-pay recognize_callee_universe + coordinate.
        if site.observed != "Call" or site.call_has_keywords():
            return False
        target = site.call_target_name()
        if target is None:
            return False
        receiver = site.call_receiver()
        if receiver is None:
            # Bound-source / nested FunctionDef warrants take precedence over
            # bare-leaf spelling (a local ``def dtype`` is not the builtin).
            if (
                recognize_callee_universe(site=site)
                is CalleeUniverseSupport.BOUND_SOURCE_CALLABLE
            ):
                return True
            if target not in _AUTHENTICATED_PLAIN_LEAVES:
                return recognize_callee_universe(site=site) is not None
        elif receiver.observed == "Attribute":
            # Nested Attribute receivers (``self.module.t0`` / F2Py chains)
            # authenticate only through provenance-bound support.
            return recognize_callee_universe(site=site) is not None
        elif receiver.observed != "Name":
            # Only instance-parameter method form can authenticate converters.
            return False
        if recognize_callee_universe(site=site) is not None:
            return True
        coordinate = CalleeUniverseRecognition.coordinate(site)
        if coordinate is None:
            return False
        if coordinate in _BUILTIN_COORDINATES:
            return True
        if coordinate in _RECEIVER_COORDINATES:
            return True
        return (
            recognize_authenticated_callee_identity(coordinate)
            in _OWNED_IMPORTED_SUPPORT
        )

    @classmethod
    def new(cls, site, ctx) -> "BuiltinCalleeUniverseSugar":
        owner = MethodCallSugar if site.call_receiver() is not None else CallSugar
        return cls(call=owner.new(site, ctx), site=site)

    @classmethod
    def witnesses(cls):
        return (
            _coordinate_witness("dtype", "'i4'", "'i8'"),
            _coordinate_witness("all", "True", "False"),
            _coordinate_witness("any", "True", "False"),
            _coordinate_witness("min", "0", "1"),
            _coordinate_witness("max", "0", "1"),
            _coordinate_witness("sum", "0", "1"),
            _coordinate_witness("list", "[]", "[0]"),
            _coordinate_witness("set", "[]", "[0]"),
            _coordinate_witness("hasattr", "True", "False"),
            _item_receiver_coordinate_witness(),
            _imported_coordinate_witness(
                name="get_handler_name",
                setup=("from numpy._core.multiarray import get_handler_name\n"),
                callee="get_handler_name",
                argument="5",
            ),
            _imported_coordinate_witness(
                name="get_handler_version",
                setup=(
                    "from numpy._core.multiarray import get_handler_version\n"
                ),
                callee="get_handler_version",
                argument="5",
            ),
            _imported_method_coordinate_witness(
                setup=("import numpy._core._multiarray_tests as mt\n"),
            ),
            _checks_test_get_multi_index_iter_next_witness(),
            _compare_dtypes_local_source_witness(),
            _f2py_sum_and_double_witness(),
            _regex_search_coordinate_witness(),
            _numpy_can_cast_witness(),
            _numpy_issubdtype_witness(),
            _numpy_isnan_witness(),
            _numpy_all_witness(),
            _numpy_dtype_witness(),
            *(
                _numpy_batch_witness(name)
                for name in (
                    "timedelta64",
                    "read",
                    "__array_wrap__",
                    "__dlpack_device__",
                    "astype",
                    "dtypes",
                    "get_npyiter_ndim",
                    "get_npyiter_size",
                    "asarray",
                    "drop_metadata",
                    "_has_method_heading",
                    "_repr_latex_",
                    "binomial",
                    "conv_intp",
                    "create",
                    "exists",
                    "func",
                    "iter_goto",
                    "median",
                )
            ),
            _numpy_may_share_memory_witness(),
            _numpy_shares_memory_witness(),
            _numpy_array_tobytes_witness(),
            _bound_source_callable_witness(),
            _pathlib_path_witness(),
            _numpy_standard_gamma_witness(),
            _numpy_subrout_default_witness(),
            _numpy_eval_scalar_witness(),
            _numpy_dtype_result_witness(),
            _json_loads_witness(),
            _dataclasses_asdict_witness(),
            _dataclasses_is_dataclass_witness(),
            _path_resolve_coordinate_witness(),
            _ufunc_coordinate_witness(),
            *(
                _bound_leaf_coordinate_witness(name)
                for name in (
                    "t0",
                    "selectedintkind",
                    "foo",
                    "to_Dt",
                )
            ),
            _math_isclose_witness(),
            _numpy_result_type_witness(),
            _scipy_linalg_issymmetric_witness(),
            _scipy_linalg_ishermitian_witness(),
            _scipy_fft_get_workers_witness(),
            _numpy_isdtype_witness(),
            _numpy_datetime_data_witness(),
            _numpy_markinnerspaces_witness(),
            _numpy_identity_hash_set_item_default_witness(),
            # #5555 / #5564 — multi-hop self.module.<leaf> bound-source twins
            # (non-vacuous conjunction). #5561 textwrap. #5563 constructor to_device.
            _bound_module_member_witness("type_subroutine"),
            _bound_module_member_witness("simple_subroutine"),
            _textwrap_dedent_witness(),
            _numpy_to_device_witness(),
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
        truthful=(prefix + f"def test_a():\n    assert A({argument}) == {argument}\n"),
        lying=(prefix + f"def test_a():\n    assert A({argument}) == {lying_value}\n"),
        family="builtin-universe-coordinate",
    )


def _imported_coordinate_witness(*, name: str, setup: str, callee: str, argument: str):
    prefix = setup + f"\ndef A():\n    return {callee}({argument})\n\n"
    return _call_pair(
        name=f"{name}_builtin_universe_coordinate",
        owner_sugar="BuiltinCalleeUniverseSugar",
        truthful=(prefix + "def test_a():\n" + "    assert A() == 0 and A() == 0\n"),
        lying=(prefix + "def test_a():\n" + "    assert A() == 0 and A() != 0\n"),
        family="builtin-universe-coordinate",
    )


def _item_receiver_coordinate_witness():
    prefix = (
        "import numpy as np\n"
        "\n"
        "def A(value):\n"
        "    arr = np.array([value], dtype=object)\n"
        "    return arr.item()\n"
        "\n"
    )
    return _call_pair(
        name="item_receiver_universe_coordinate",
        owner_sugar="BuiltinCalleeUniverseSugar",
        truthful=prefix + "def test_a():\n    assert A(5) == A(5)\n",
        lying=prefix + "def test_a():\n    assert A(5) == A(5) and A(5) != A(5)\n",
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


def _regex_search_coordinate_witness():
    prefix = (
        "import re\n"
        "\n"
        "def A(value):\n"
        "    pattern = re.compile('x')\n"
        "    return pattern.search(value)\n"
        "\n"
    )
    return _call_pair(
        name="regex_search_builtin_universe_coordinate",
        owner_sugar="BuiltinCalleeUniverseSugar",
        truthful=(
            prefix
            + "def test_a():\n"
            + "    assert A('x') == A('x') and A('x') == A('x')\n"
        ),
        lying=(
            prefix
            + "def test_a():\n"
            + "    assert A('x') == A('x') and A('x') != A('x')\n"
        ),
        family="builtin-universe-coordinate",
    )


def _numpy_can_cast_witness():
    prefix = (
        "import numpy as np\n"
        "\n"
        "def A():\n"
        "    return np.can_cast('i4', 'i8')\n"
        "\n"
    )
    return _call_pair(
        name="numpy_can_cast_universe_coordinate",
        owner_sugar="BuiltinCalleeUniverseSugar",
        # Conjunction gives the consistency checker a sibling constraint so
        # determinism of the authenticated coordinate is load-bearing.
        truthful=prefix + "def test_a():\n    assert A() == A() and A() == A()\n",
        lying=prefix + "def test_a():\n    assert A() == A() and A() != A()\n",
        family="builtin-universe-coordinate",
    )


def _numpy_issubdtype_witness():
    prefix = (
        "import numpy as np\n"
        "\n"
        "def A():\n"
        "    return np.issubdtype('i4', np.integer)\n"
        "\n"
    )
    return _call_pair(
        name="numpy_issubdtype_universe_coordinate",
        owner_sugar="BuiltinCalleeUniverseSugar",
        truthful=prefix + "def test_a():\n    assert A() == A()\n",
        lying=prefix + "def test_a():\n    assert A() != A()\n",
        family="builtin-universe-coordinate",
    )


def _numpy_isnan_witness():
    prefix = "import numpy as np\n" "\n" "def A():\n" "    return np.isnan(0.0)\n" "\n"
    return _call_pair(
        name="numpy_isnan_universe_coordinate",
        owner_sugar="BuiltinCalleeUniverseSugar",
        # Conjunction gives the consistency checker a sibling constraint so
        # determinism of the authenticated coordinate is load-bearing.
        truthful=prefix + "def test_a():\n    assert A() == A() and A() == A()\n",
        lying=prefix + "def test_a():\n    assert A() == A() and A() != A()\n",
        family="builtin-universe-coordinate",
    )


def _numpy_all_witness():
    prefix = "import numpy as np\n" "\n" "def A():\n" "    return np.all(True)\n" "\n"
    return _call_pair(
        name="numpy_all_universe_coordinate",
        owner_sugar="BuiltinCalleeUniverseSugar",
        # Conjunction gives the consistency checker a sibling constraint so
        # determinism of the authenticated coordinate is load-bearing.
        # Distinct from bare builtin ``all``: import-bound ``numpy.all``.
        truthful=prefix + "def test_a():\n    assert A() == A() and A() == A()\n",
        lying=prefix + "def test_a():\n    assert A() == A() and A() != A()\n",
        family="builtin-universe-coordinate",
    )


def _numpy_dtype_witness():
    prefix = "import numpy as np\n" "\n" "def A():\n" "    return np.dtype('i4')\n" "\n"
    return _call_pair(
        name="numpy_dtype_universe_coordinate",
        owner_sugar="BuiltinCalleeUniverseSugar",
        truthful=prefix + "def test_a():\n    assert A() == A() and A() == A()\n",
        lying=prefix + "def test_a():\n    assert A() == A() and A() != A()\n",
        family="builtin-universe-coordinate",
    )


def _numpy_may_share_memory_witness():
    prefix = (
        "import numpy as np\n"
        "\n"
        "def A():\n"
        "    return np.may_share_memory(np.array([1]), np.array([1]))\n"
        "\n"
    )
    return _call_pair(
        name="numpy_may_share_memory_universe_coordinate",
        owner_sugar="BuiltinCalleeUniverseSugar",
        truthful=prefix + "def test_a():\n    assert A() == A()\n",
        lying=prefix + "def test_a():\n    assert A() != A()\n",
        family="builtin-universe-coordinate",
    )


def _numpy_shares_memory_witness():
    prefix = (
        "import numpy as np\n"
        "\n"
        "def A():\n"
        "    return np.shares_memory(np.array([1]), np.array([1]))\n"
        "\n"
    )
    return _call_pair(
        name="numpy_shares_memory_universe_coordinate",
        owner_sugar="BuiltinCalleeUniverseSugar",
        truthful=prefix + "def test_a():\n    assert A() == A()\n",
        lying=prefix + "def test_a():\n    assert A() != A()\n",
        family="builtin-universe-coordinate",
    )


def _numpy_array_tobytes_witness():
    prefix = (
        "import numpy as np\n"
        "\n"
        "def A():\n"
        "    value = np.array(b'abc')\n"
        "    return value.tobytes()\n"
        "\n"
    )
    return _call_pair(
        name="numpy_array_tobytes_universe_coordinate",
        owner_sugar="BuiltinCalleeUniverseSugar",
        truthful=prefix + "def test_a():\n    assert A() == A() and A() == A()\n",
        lying=prefix + "def test_a():\n    assert A() == A() and A() != A()\n",
        family="builtin-universe-coordinate",
    )


def _numpy_batch_witness(name: str):
    prefix = f"import numpy as np\n\ndef A():\n    return np.{name}(0)\n\n"
    return _call_pair(
        name=f"numpy_{name.replace('_', '-')}_universe_coordinate",
        owner_sugar="BuiltinCalleeUniverseSugar",
        truthful=prefix + "def test_a():\n    assert A() == A()\n",
        lying=prefix + "def test_a():\n    assert A() != A()\n",
        family="builtin-universe-coordinate",
    )


def _bound_source_callable_witness():
    prefix = (
        "import numpy as np\n"
        "_ArrayMemoryError = np._core._exceptions._ArrayMemoryError\n"
        "\n"
        "def test_a():\n"
        "    f = _ArrayMemoryError._size_to_string\n"
    )
    return _call_pair(
        name="bound_source_callable_universe_coordinate",
        owner_sugar="BuiltinCalleeUniverseSugar",
        truthful=prefix + "    assert f(0) == f(0) and f(0) == f(0)\n",
        lying=prefix + "    assert f(0) == f(0) and f(0) != f(0)\n",
        family="builtin-universe-coordinate",
    )


def _checks_test_get_multi_index_iter_next_witness():
    prefix = (
        "import checks\n"
        "\n"
        "def A():\n"
        "    return checks.test_get_multi_index_iter_next(0, 0)\n"
        "\n"
    )
    return _call_pair(
        name="checks_test_get_multi_index_iter_next_universe_coordinate",
        owner_sugar="BuiltinCalleeUniverseSugar",
        # Conjunction keeps deterministic call substitution load-bearing.
        truthful=prefix + "def test_a():\n    assert A() == 0 and A() == 0\n",
        lying=prefix + "def test_a():\n    assert A() == 0 and A() != 0\n",
        family="builtin-universe-coordinate",
    )


def _compare_dtypes_local_source_witness():
    # Nested FunctionDef matches the corpus shape (``test_drop_metadata``).
    truthful = (
        "def test_a():\n"
        "    def _compare_dtypes(dt1, dt2):\n"
        "        return dt1\n"
        "    assert _compare_dtypes(0, 1) == 0 and _compare_dtypes(0, 1) == 0\n"
    )
    lying = (
        "def test_a():\n"
        "    def _compare_dtypes(dt1, dt2):\n"
        "        return dt1\n"
        "    assert _compare_dtypes(0, 1) == 0 and _compare_dtypes(0, 1) != 0\n"
    )
    return _call_pair(
        name="compare_dtypes_local_source_universe_coordinate",
        owner_sugar="BuiltinCalleeUniverseSugar",
        truthful=truthful,
        lying=lying,
        family="builtin-universe-coordinate",
    )


def _f2py_sum_and_double_witness():
    truthful = (
        "from . import util\n"
        "\n"
        "class TestUsedModule(util.F2PyTest):\n"
        "    def test_a(self):\n"
        "        assert self.module.useops.sum_and_double(3, 7) == 0 and "
        "self.module.useops.sum_and_double(3, 7) == 0\n"
    )
    lying = (
        "from . import util\n"
        "\n"
        "class TestUsedModule(util.F2PyTest):\n"
        "    def test_a(self):\n"
        "        assert self.module.useops.sum_and_double(3, 7) == 0 and "
        "self.module.useops.sum_and_double(3, 7) != 0\n"
    )
    return _call_pair(
        name="f2py_sum_and_double_universe_coordinate",
        owner_sugar="BuiltinCalleeUniverseSugar",
        truthful=truthful,
        lying=lying,
        family="builtin-universe-coordinate",
    )


def _numpy_dtype_result_witness():
    prefix = (
        "import numpy as np\n"
        "\n"
        "def A():\n"
        "    return np.asarray([1]).dtype\n"
        "\n"
    )
    return _call_pair(
        name="numpy_dtype_result_universe_coordinate",
        owner_sugar="BuiltinCalleeUniverseSugar",
        truthful=prefix + "def test_a():\n    assert A() == A() and A() == A()\n",
        lying=prefix + "def test_a():\n    assert A() == A() and A() != A()\n",
        family="builtin-universe-coordinate",
    )


def _json_loads_witness():
    prefix = "import json\n" "\n" "def A():\n" "    return json.loads('0')\n" "\n"
    return _call_pair(
        name="json_loads_universe_coordinate",
        owner_sugar="BuiltinCalleeUniverseSugar",
        # Conjunction makes deterministic call substitution load-bearing.
        truthful=prefix + "def test_a():\n    assert A() == A() and A() == A()\n",
        lying=prefix + "def test_a():\n    assert A() == A() and A() != A()\n",
        family="builtin-universe-coordinate",
    )


def _math_isclose_witness():
    prefix = (
        "import math\n" "\n" "def A():\n" "    return math.isclose(1.0, 1.0)\n" "\n"
    )
    return _call_pair(
        name="math_isclose_universe_coordinate",
        owner_sugar="BuiltinCalleeUniverseSugar",
        truthful=prefix + "def test_a():\n    assert A() == A() and A() == A()\n",
        lying=prefix + "def test_a():\n    assert A() == A() and A() != A()\n",
        family="builtin-universe-coordinate",
    )


def _numpy_result_type_witness():
    prefix = (
        "import numpy as np\n"
        "\n"
        "def A():\n"
        "    return np.result_type(np.float32, np.float64)\n"
        "\n"
    )
    return _call_pair(
        name="numpy_result_type_universe_coordinate",
        owner_sugar="BuiltinCalleeUniverseSugar",
        truthful=prefix + "def test_a():\n    assert A() == A() and A() == A()\n",
        lying=prefix + "def test_a():\n    assert A() == A() and A() != A()\n",
        family="builtin-universe-coordinate",
    )


def _scipy_linalg_issymmetric_witness():
    prefix = (
        "import numpy as np\n"
        "from scipy.linalg import issymmetric\n"
        "\n"
        "def A():\n"
        "    return issymmetric(np.eye(2))\n"
        "\n"
    )
    return _call_pair(
        name="scipy_linalg_issymmetric_universe_coordinate",
        owner_sugar="BuiltinCalleeUniverseSugar",
        truthful=prefix + "def test_a():\n    assert A() == A() and A() == A()\n",
        lying=prefix + "def test_a():\n    assert A() == A() and A() != A()\n",
        family="builtin-universe-coordinate",
    )


def _scipy_linalg_ishermitian_witness():
    prefix = (
        "import numpy as np\n"
        "from scipy.linalg import ishermitian\n"
        "\n"
        "def A():\n"
        "    return ishermitian(np.eye(2))\n"
        "\n"
    )
    return _call_pair(
        name="scipy_linalg_ishermitian_universe_coordinate",
        owner_sugar="BuiltinCalleeUniverseSugar",
        truthful=prefix + "def test_a():\n    assert A() == A() and A() == A()\n",
        lying=prefix + "def test_a():\n    assert A() == A() and A() != A()\n",
        family="builtin-universe-coordinate",
    )


def _scipy_fft_get_workers_witness():
    prefix = (
        "import scipy.fft as fft\n"
        "\n"
        "def A():\n"
        "    return fft.get_workers()\n"
        "\n"
    )
    return _call_pair(
        name="scipy_fft_get_workers_universe_coordinate",
        owner_sugar="BuiltinCalleeUniverseSugar",
        truthful=prefix + "def test_a():\n    assert A() == A() and A() == A()\n",
        lying=prefix + "def test_a():\n    assert A() == A() and A() != A()\n",
        family="builtin-universe-coordinate",
    )


def _dataclasses_asdict_witness():
    prefix = (
        "from dataclasses import asdict, dataclass\n"
        "\n"
        "@dataclass\n"
        "class Point:\n"
        "    x: int\n"
        "\n"
        "def A():\n"
        "    return asdict(Point(0))\n"
        "\n"
    )
    return _call_pair(
        name="dataclasses_asdict_universe_coordinate",
        owner_sugar="BuiltinCalleeUniverseSugar",
        truthful=prefix + "def test_a():\n    assert A() == A() and A() == A()\n",
        lying=prefix + "def test_a():\n    assert A() == A() and A() != A()\n",
        family="builtin-universe-coordinate",
    )


def _dataclasses_is_dataclass_witness():
    prefix = (
        "from dataclasses import is_dataclass, dataclass\n"
        "\n"
        "@dataclass\n"
        "class Point:\n"
        "    x: int\n"
        "\n"
        "def A():\n"
        "    return is_dataclass(Point)\n"
        "\n"
    )
    return _call_pair(
        name="dataclasses_is_dataclass_universe_coordinate",
        owner_sugar="BuiltinCalleeUniverseSugar",
        truthful=prefix + "def test_a():\n    assert A() == A() and A() == A()\n",
        lying=prefix + "def test_a():\n    assert A() == A() and A() != A()\n",
        family="builtin-universe-coordinate",
    )


def _pathlib_path_witness():
    """Import-bound ``pathlib.Path`` constructor (corpus: test_configtool)."""
    prefix = (
        "import pathlib\n"
        "\n"
        "def A(value):\n"
        "    return pathlib.Path(value)\n"
        "\n"
    )
    return _call_pair(
        name="pathlib_path_universe_coordinate",
        owner_sugar="BuiltinCalleeUniverseSugar",
        truthful=prefix
        + "def test_a():\n    assert A('.') == A('.') and A('.') == A('.')\n",
        lying=prefix
        + "def test_a():\n    assert A('.') == A('.') and A('.') != A('.')\n",
        family="builtin-universe-coordinate",
    )


def _numpy_standard_gamma_witness():
    """Generator-bound standard_gamma via import-constructed receiver."""
    prefix = (
        "from numpy.random import MT19937, Generator\n"
        "\n"
        "def A():\n"
        "    mt19937 = Generator(MT19937(1))\n"
        "    return mt19937.standard_gamma(0.0)\n"
        "\n"
    )
    return _call_pair(
        name="numpy_standard_gamma_universe_coordinate",
        owner_sugar="BuiltinCalleeUniverseSugar",
        truthful=prefix + "def test_a():\n    assert A() == A() and A() == A()\n",
        lying=prefix + "def test_a():\n    assert A() == A() and A() != A()\n",
        family="builtin-universe-coordinate",
    )


def _numpy_subrout_default_witness():
    """Multi-hop instance-module call ``self.module.subrout_default``."""
    truthful = (
        "class _Mod:\n"
        "    @staticmethod\n"
        "    def subrout_default(a, b):\n"
        "        return a + b\n"
        "\n"
        "class Host:\n"
        "    module = _Mod\n"
        "\n"
        "    def test_a(self):\n"
        "        assert (\n"
        "            self.module.subrout_default(200, 12)\n"
        "            == self.module.subrout_default(200, 12)\n"
        "            and self.module.subrout_default(200, 12)\n"
        "            == self.module.subrout_default(200, 12)\n"
        "        )\n"
    )
    lying = (
        "class _Mod:\n"
        "    @staticmethod\n"
        "    def subrout_default(a, b):\n"
        "        return a + b\n"
        "\n"
        "class Host:\n"
        "    module = _Mod\n"
        "\n"
        "    def test_a(self):\n"
        "        assert (\n"
        "            self.module.subrout_default(200, 12)\n"
        "            == self.module.subrout_default(200, 12)\n"
        "            and self.module.subrout_default(200, 12)\n"
        "            != self.module.subrout_default(200, 12)\n"
        "        )\n"
    )
    return _call_pair(
        name="numpy_subrout_default_universe_coordinate",
        owner_sugar="BuiltinCalleeUniverseSugar",
        truthful=truthful,
        lying=lying,
        family="builtin-universe-coordinate",
    )


def _numpy_eval_scalar_witness():
    """Assignment alias of crackfortran._eval_scalar (corpus locus shape)."""
    prefix = (
        "from numpy.f2py import crackfortran\n"
        "\n"
        "def A():\n"
        "    eval_scalar = crackfortran._eval_scalar\n"
        "    return eval_scalar('123', {})\n"
        "\n"
    )
    return _call_pair(
        name="numpy_eval_scalar_universe_coordinate",
        owner_sugar="BuiltinCalleeUniverseSugar",
        truthful=prefix + "def test_a():\n    assert A() == A() and A() == A()\n",
        lying=prefix + "def test_a():\n    assert A() == A() and A() != A()\n",
        family="builtin-universe-coordinate",
    )


def _path_resolve_coordinate_witness():
    prefix = (
        "import pathlib\n"
        "\n"
        "def A(value):\n"
        "    path = pathlib.Path(value)\n"
        "    return path.resolve()\n"
        "\n"
    )
    return _call_pair(
        name="path_resolve_universe_coordinate",
        owner_sugar="BuiltinCalleeUniverseSugar",
        truthful=prefix + "def test_a():\n    assert A('.') == A('.')\n",
        lying=prefix + "def test_a():\n    assert A('.') != A('.')\n",
        family="builtin-universe-coordinate",
    )


def _ufunc_coordinate_witness():
    """Bound import-anchored ufunc alias — parameter ufunc stays unowned."""
    prefix = (
        "import numpy as np\n"
        "\n"
        "def A(x, y):\n"
        "    ufunc = np.add\n"
        "    return ufunc(x, y)\n"
        "\n"
    )
    return _call_pair(
        name="ufunc_universe_coordinate",
        owner_sugar="BuiltinCalleeUniverseSugar",
        truthful=prefix + "def test_a():\n    assert A(1, 2) == A(1, 2)\n",
        lying=prefix + "def test_a():\n    assert A(1, 2) != A(1, 2)\n",
        family="builtin-universe-coordinate",
    )


def _bound_leaf_coordinate_witness(name: str):
    """Truthful self.module.<leaf> call; lying twin refutes equality."""
    truthful = (
        "class _Mod:\n"
        "    @staticmethod\n"
        f"    def {name}(*args):\n"
        "        return args\n"
        "\n"
        "class Host:\n"
        "    module = _Mod\n"
        "\n"
        "    def test_a(self):\n"
        f"        assert self.module.{name}(1) == self.module.{name}(1)\n"
    )
    lying = (
        "class _Mod:\n"
        "    @staticmethod\n"
        f"    def {name}(*args):\n"
        "        return args\n"
        "\n"
        "class Host:\n"
        "    module = _Mod\n"
        "\n"
        "    def test_a(self):\n"
        f"        assert self.module.{name}(1) != self.module.{name}(1)\n"
    )
    return _call_pair(
        name=f"{name.replace('_', '-')}_universe_coordinate",
        owner_sugar="BuiltinCalleeUniverseSugar",
        truthful=truthful,
        lying=lying,
        family="builtin-universe-coordinate",
    )


def _numpy_isdtype_witness():
    prefix = (
        "import numpy as np\n"
        "\n"
        "def A():\n"
        "    return np.isdtype(np.float64, 'real floating')\n"
        "\n"
    )
    return _call_pair(
        name="numpy_isdtype_universe_coordinate",
        owner_sugar="BuiltinCalleeUniverseSugar",
        truthful=prefix + "def test_a():\n    assert A() == A() and A() == A()\n",
        lying=prefix + "def test_a():\n    assert A() == A() and A() != A()\n",
        family="builtin-universe-coordinate",
    )


def _numpy_datetime_data_witness():
    prefix = (
        "import numpy as np\n"
        "\n"
        "def A():\n"
        "    return np.datetime_data(np.dtype('M8[D]'))\n"
        "\n"
    )
    return _call_pair(
        name="numpy_datetime_data_universe_coordinate",
        owner_sugar="BuiltinCalleeUniverseSugar",
        truthful=prefix + "def test_a():\n    assert A() == A() and A() == A()\n",
        lying=prefix + "def test_a():\n    assert A() == A() and A() != A()\n",
        family="builtin-universe-coordinate",
    )


def _numpy_markinnerspaces_witness():
    """Direct from-import of crackfortran.markinnerspaces (corpus locus shape)."""
    prefix = (
        "from numpy.f2py.crackfortran import markinnerspaces\n"
        "\n"
        "def A(value):\n"
        "    return markinnerspaces(value)\n"
        "\n"
    )
    return _call_pair(
        name="numpy_markinnerspaces_universe_coordinate",
        owner_sugar="BuiltinCalleeUniverseSugar",
        truthful=(
            prefix + "def test_a():\n    assert A('x y') == A('x y') and A('x y') == A('x y')\n"
        ),
        lying=(
            prefix + "def test_a():\n    assert A('x y') == A('x y') and A('x y') != A('x y')\n"
        ),
        family="builtin-universe-coordinate",
    )


def _numpy_identity_hash_set_item_default_witness():
    """From-import of multiarray_tests.identity_hash_set_item_default."""
    # Determinism twin: same call returns equal values under conjunction.
    prefix = (
        "from numpy._core._multiarray_tests import (\n"
        "    create_identity_hash,\n"
        "    identity_hash_set_item_default,\n"
        ")\n"
        "\n"
        "def A():\n"
        "    ht = create_identity_hash(1)\n"
        "    key = (0,)\n"
        "    return identity_hash_set_item_default(ht, key, 1)\n"
        "\n"
    )
    return _call_pair(
        name="numpy_identity_hash_set_item_default_universe_coordinate",
        owner_sugar="BuiltinCalleeUniverseSugar",
        truthful=prefix + "def test_a():\n    assert A() == A() and A() == A()\n",
        lying=prefix + "def test_a():\n    assert A() == A() and A() != A()\n",
        family="builtin-universe-coordinate",
    )


def _bound_module_member_witness(member: str):
    """Truthful/lying twin for multi-hop ``self.module.<member>`` bound-source."""

    call = f"self.module.{member}(1)"
    prefix = (
        "class _Mod:\n"
        "    @staticmethod\n"
        f"    def {member}(*args):\n"
        "        return args\n"
        "\n"
        "class Host:\n"
        "    module = _Mod\n"
        "\n"
        "    def test_a(self):\n"
    )
    return _call_pair(
        name=f"{member.replace('_', '-')}_universe_coordinate",
        owner_sugar="BuiltinCalleeUniverseSugar",
        truthful=prefix + f"        assert {call} == {call} and {call} == {call}\n",
        lying=prefix + f"        assert {call} == {call} and {call} != {call}\n",
        family="builtin-universe-coordinate",
    )


def _textwrap_dedent_witness():
    prefix = (
        "import textwrap\n"
        "\n"
        "def A():\n"
        "    return textwrap.dedent('x')\n"
        "\n"
    )
    return _call_pair(
        name="textwrap_dedent_universe_coordinate",
        owner_sugar="BuiltinCalleeUniverseSugar",
        truthful=prefix + "def test_a():\n    assert A() == A() and A() == A()\n",
        lying=prefix + "def test_a():\n    assert A() == A() and A() != A()\n",
        family="builtin-universe-coordinate",
    )


def _numpy_to_device_witness():
    """Constructor-bound scalar only — not parametrize-injected parameters."""

    prefix = (
        "import numpy as np\n"
        "\n"
        "def A():\n"
        "    scalar = np.int64(1)\n"
        "    return scalar.to_device('cpu')\n"
        "\n"
    )
    return _call_pair(
        name="numpy_to_device_universe_coordinate",
        owner_sugar="BuiltinCalleeUniverseSugar",
        truthful=prefix + "def test_a():\n    assert A() == A() and A() == A()\n",
        lying=prefix + "def test_a():\n    assert A() == A() and A() != A()\n",
        family="builtin-universe-coordinate",
    )
