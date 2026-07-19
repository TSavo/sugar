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
        "numpy._core.multiarray.get_handler_name",
        "re.Pattern.search",
        *_CONVERTER_COORDINATES,
    }
)
# Must match recognition.callee_universe bare-builtin warrants this leaf owns.
# ``type`` is intentionally absent: BuiltinTypeCallSugar is its construction owner.
_BUILTIN_COORDINATES = frozenset(
    {"dtype", "all", "list", "set", "hasattr"}
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
        CalleeUniverseSupport.NUMPY_CONVERTER,
        CalleeUniverseSupport.REGEX_SEARCH,
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
            if target not in _AUTHENTICATED_PLAIN_LEAVES:
                return (
                    recognize_callee_universe(site=site)
                    is CalleeUniverseSupport.BOUND_SOURCE_CALLABLE
                )
        elif receiver.observed != "Name":
            # Only instance-parameter method form can authenticate converters.
            return False
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
            _imported_method_coordinate_witness(
                setup=("import numpy._core._multiarray_tests as mt\n"),
            ),
            _regex_search_coordinate_witness(),
            _numpy_can_cast_witness(),
            _numpy_issubdtype_witness(),
            _numpy_isnan_witness(),
            _numpy_all_witness(),
            _numpy_dtype_witness(),
            *(_numpy_batch_witness(name) for name in (
                "timedelta64", "read", "__array_wrap__", "__dlpack_device__",
                "astype", "dtypes", "get_npyiter_ndim", "get_npyiter_size",
                "asarray", "drop_metadata", "_has_method_heading", "_repr_latex_",
                "binomial", "conv_intp", "create", "exists", "func", "iter_goto", "median",
            )),
            _numpy_may_share_memory_witness(),
            _bound_source_callable_witness(),
            _numpy_dtype_result_witness(),
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
