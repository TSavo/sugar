from __future__ import annotations

import ast

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.kit_rpc.factory_walk_row_dto import FactoryWalkRedRowDto
from sugar_lift_py_tests.lift_rpc import lift_file_payload
from sugar_lift_py_tests.recognition.callee_universe import (
    CalleeUniverseRecognition,
    recognize_callee_universe,
)
from sugar_lift_py_tests.recognition.visible_declarations import (
    lexical_function_bindings,
)


def _universe_gaps(payload) -> list[FactoryWalkRedRowDto]:
    return [
        row
        for row in payload.factory_walk
        if isinstance(row, FactoryWalkRedRowDto)
        and "callee universe coverage" in row.reason
    ]


def test_universeless_assertion_emits_named_factory_gap() -> None:
    source = "def test_vendor_only():\n    assert vendor_only(1) == 1\n"

    payload = lift_file_payload(source, "vendor_fixture.py")

    # The stated fact remains valid and present; universe visibility is additive.
    assert any(
        contract.name.startswith("vendor_only#euf#c:call:vendor_only")
        and getattr(contract, "inv", None) is not None
        for contract in payload.ir
    )
    assert any(
        edge.get("targetSymbol") == "call:vendor_only" for edge in payload.call_edges
    )

    gaps = _universe_gaps(payload)
    assert len(gaps) == 1
    gap = gaps[0]
    rpc = gap.to_rpc()
    assert gap.file == "vendor_fixture.py"
    assert gap.line == 2
    assert gap.ast_kind == "call:vendor_only"
    assert rpc["verdict"] == "gap"
    assert rpc["gap_kind"] == "Sugar"
    assert rpc["gap_locus"] == "Construction"
    for testimony in (
        "owner=python.factory",
        "no diggable body",
        "no builtin-universe recognizer claim",
        "no bridge-borne contract",
        "no loaded vendor proof",
        "add builtin-universe recognizer",
        "dig body",
        "bridge coverage",
        "load vendor proof",
    ):
        assert testimony in gap.reason


def test_diggable_callee_emits_no_universe_gap() -> None:
    source = (
        "def covered(value):\n"
        "    return value\n"
        "\n"
        "def test_covered():\n"
        "    assert covered(1) == 1\n"
    )

    payload = lift_file_payload(source, "covered_fixture.py")

    assert any(
        getattr(contract, "bridge_source_symbol", None) == "covered"
        and getattr(contract, "post", None) is not None
        for contract in payload.ir
    )
    assert any(
        edge.get("targetSymbol") == "call:covered" for edge in payload.call_edges
    )
    assert _universe_gaps(payload) == []


def test_import_authenticated_regex_search_has_universe_support() -> None:
    source = (
        "import re\n"
        "\n"
        "def test_search(value):\n"
        "    pattern = re.compile('x')\n"
        "    assert pattern.search(value) is not None\n"
    )

    payload = lift_file_payload(source, "regex_search_covered.py")

    assert _universe_gaps(payload) == []


def test_unresolved_search_receiver_stays_loud() -> None:
    source = (
        "def test_search(pattern, value):\n"
        "    assert pattern.search(value) is not None\n"
    )

    payload = lift_file_payload(source, "regex_search_unresolved.py")

    gaps = _universe_gaps(payload)
    assert len(gaps) == 1
    assert gaps[0].ast_kind == "call:search"
    assert gaps[0].selected is None
    assert "owner=python.factory" in gaps[0].reason


def test_builtin_covered_callee_emits_no_universe_gap() -> None:
    source = "def test_len(value):\n    assert len(value) >= 0\n"

    payload = lift_file_payload(source, "builtin_covered_fixture.py")

    assert any(edge.get("targetSymbol") == "call:len" for edge in payload.call_edges)
    assert _universe_gaps(payload) == []


def test_import_constructed_item_receiver_emits_no_universe_gap() -> None:
    source = (
        "import numpy as np\n"
        "\n"
        "def test_item(value):\n"
        "    arr = np.array([value], dtype=object)\n"
        "    assert arr.item() == value\n"
    )

    payload = lift_file_payload(source, "item_covered_fixture.py")

    assert any(edge.get("targetSymbol") == "call:item" for edge in payload.call_edges)
    assert _universe_gaps(payload) == []


def test_unresolved_item_receiver_stays_unclassified() -> None:
    source = "def test_item(arr):\n    assert arr.item() == 0\n"

    payload = lift_file_payload(source, "item_unresolved_fixture.py")

    gaps = _universe_gaps(payload)
    assert len(gaps) == 1
    assert gaps[0].ast_kind == "call:item"


@pytest.mark.parametrize(
    ("callee", "source"),
    [
        (
            "type",
            "def test_type(value):\n    assert type(value) == int\n",
        ),
        (
            "dtype",
            "def test_dtype():\n    assert dtype('i4') == 'i4'\n",
        ),
        (
            "all",
            "def test_all(value):\n    assert all(value)\n",
        ),
        (
            "any",
            "def test_any(value):\n    assert any(value)\n",
        ),
        (
            "min",
            "def test_min(value):\n    assert min(value) == 0\n",
        ),
        (
            "max",
            "def test_max(value):\n    assert max(value) == 0\n",
        ),
        (
            "sum",
            "def test_sum(value):\n    assert sum(value) == 0\n",
        ),
        (
            "list",
            "def test_list(value):\n    assert list(value) == []\n",
        ),
        (
            "set",
            "def test_set(value):\n    assert set(value) == set()\n",
        ),
        (
            "hasattr",
            "def test_hasattr(obj, name):\n    assert hasattr(obj, name)\n",
        ),
        (
            "get_handler_name",
            "from numpy._core.multiarray import get_handler_name\n"
            "def test_handler():\n"
            "    assert get_handler_name() == get_handler_name()\n",
        ),
        (
            "conv",
            "import numpy._core._multiarray_tests as mt\n"
            "class TestConverter:\n"
            "    conv = mt.run_byteorder_converter\n"
            "    def test_converter(self):\n"
            "        assert self.conv(5) == self.conv(5)\n",
        ),
    ],
)
def test_authenticated_builtin_coordinate_emits_no_universe_gap(
    callee: str, source: str
) -> None:
    payload = lift_file_payload(source, f"{callee}_covered_fixture.py")

    expected_target = (
        "call:numpy._core.multiarray.get_handler_name"
        if callee == "get_handler_name"
        else f"call:{callee}"
    )
    assert any(
        edge.get("targetSymbol") == expected_target for edge in payload.call_edges
    )
    assert _universe_gaps(payload) == []

    if callee in {
        "type",
        "dtype",
        "all",
        "any",
        "min",
        "max",
        "sum",
        "list",
        "set",
        "hasattr",
    }:
        node = ast.parse(f"{callee}(value)", mode="eval").body
        context = FactoryBuildContext(
            filename="coordinate.py", catalog=default_catalog()
        )
        built = build_node(
            node,
            filename="coordinate.py",
            role=SugarRole.TERM,
            ctx=context,
        )
        # bare type() is BuiltinTypeCallSugar; remaining builtins share the
        # BuiltinCalleeUniverseSugar universe-coordinate leaf.
        expected = (
            "BuiltinTypeCallSugar" if callee == "type" else "BuiltinCalleeUniverseSugar"
        )
        assert built.audit_row.selected == expected


def test_py_subscript_floor_coordinate_is_not_a_callee_universe_gap() -> None:
    """call:py.subscript is SubscriptSugar's floor coordinate, not a callee.

    Nested ``call(...)[i]`` shares the Call's left-edge col_offset with the
    Subscript, so a call-edge for py.subscript can land on an assertion Call
    locus. That must not demand BuiltinCalleeUniverse coverage.
    """

    source = "def test_index(values):\n" "    assert values.astype(int)[()] == 0\n"
    payload = lift_file_payload(source, "py_subscript_floor.py")

    assert any(
        edge.get("targetSymbol") == "call:py.subscript" for edge in payload.call_edges
    )
    assert not any(
        gap.ast_kind == "call:py.subscript" for gap in _universe_gaps(payload)
    )


def test_bare_subscript_under_assert_is_not_a_callee_universe_gap() -> None:
    source = "def test_index(values, i):\n    assert values[i] == 0\n"
    payload = lift_file_payload(source, "bare_subscript.py")

    assert any(
        edge.get("targetSymbol") == "call:py.subscript" for edge in payload.call_edges
    )
    assert _universe_gaps(payload) == []


@pytest.mark.parametrize(
    "callee",
    [
        "get_handler_name",
        "conv",
        "all",
        "any",
        "min",
        "max",
        "sum",
        "list",
        "set",
        "hasattr",
    ],
)
def test_shadowed_authenticated_coordinate_stays_unclassified(callee: str) -> None:
    source = f"def test_shadowed({callee}):\n" f"    assert {callee}(5) == 5\n"

    payload = lift_file_payload(source, f"shadowed_{callee}.py")

    gaps = _universe_gaps(payload)
    assert len(gaps) == 1
    assert gaps[0].ast_kind == f"call:{callee}"


def test_import_bound_class_attr_converter_authenticates_without_logo() -> None:
    """#5409: class-body assign from import-bound dotted name is BOUND_SOURCE.

    The warrant is assign provenance + instance receiver, not a multiarray
    logo whitelist. ``math.sqrt`` is as import-bound as ``mt.run_*_converter``.
    """

    source = (
        "import math as mt\n"
        "class TestConverter:\n"
        "    conv = mt.sqrt\n"
        "    def test_shadowed(self):\n"
        "        assert self.conv(5) == self.conv(5)\n"
    )

    payload = lift_file_payload(source, "import_bound_receiver_conv.py")

    assert _universe_gaps(payload) == []
    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "conv"
    )
    site = SourceFragment.from_node(
        call, "import_bound_receiver_conv.py", source=source
    )
    assert recognize_callee_universe("call:conv", site=site) is not None


def test_later_local_rebind_revokes_get_handler_name_warrant() -> None:
    """Lying twin: later function-local rebind must break false recognition."""

    source = (
        "from numpy._core.multiarray import get_handler_name\n"
        "\n"
        "def test_handler():\n"
        "    assert get_handler_name() == get_handler_name()\n"
        "    get_handler_name = replacement\n"
    )

    payload = lift_file_payload(source, "handler_late_rebind.py")

    gaps = _universe_gaps(payload)
    assert gaps
    assert {gap.ast_kind for gap in gaps} == {
        "call:numpy._core.multiarray.get_handler_name"
    }

    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "get_handler_name"
    )
    site = SourceFragment.from_node(call, "handler_late_rebind.py", source=source)
    assert CalleeUniverseRecognition.coordinate(site) is None


def test_arbitrary_parameter_receiver_refuses_converter_warrant() -> None:
    """Lying twin: any parameter receiver is not the authenticated instance."""

    source = (
        "import numpy._core._multiarray_tests as mt\n"
        "\n"
        "class TestConverter:\n"
        "    conv = mt.run_byteorder_converter\n"
        "\n"
        "    def test_converter(self, other):\n"
        "        assert other.conv(5) == other.conv(5)\n"
    )

    payload = lift_file_payload(source, "arb_param_receiver.py")

    gaps = _universe_gaps(payload)
    assert len(gaps) >= 1
    assert all(gap.ast_kind == "call:conv" for gap in gaps)

    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "conv"
    )
    site = SourceFragment.from_node(call, "arb_param_receiver.py", source=source)
    assert CalleeUniverseRecognition.coordinate(site) is None


def test_instance_overwrite_before_call_revokes_converter_warrant() -> None:
    """Lying twin: preceding instance reassignment revokes the method warrant."""

    source = (
        "import numpy._core._multiarray_tests as mt\n"
        "\n"
        "class TestConverter:\n"
        "    conv = mt.run_byteorder_converter\n"
        "\n"
        "    def test_converter(self):\n"
        "        replacement = self\n"
        "        self = replacement\n"
        "        assert self.conv(5) == self.conv(5)\n"
    )

    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "conv"
    )
    site = SourceFragment.from_node(call, "instance_overwrite.py", source=source)
    assert CalleeUniverseRecognition.coordinate(site) is None

    payload = lift_file_payload(source, "instance_overwrite.py")
    gaps = _universe_gaps(payload)
    assert len(gaps) >= 1
    assert all(gap.ast_kind == "call:conv" for gap in gaps)


def test_later_local_rebind_revokes_type_builtin_warrant() -> None:
    """type/dtype early path must still honor lexical rebinding."""

    source = (
        "def test_type(value):\n"
        "    assert type(value) == int\n"
        "    type = replacement\n"
    )

    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "type"
    )
    site = SourceFragment.from_node(call, "type_late_rebind.py", source=source)
    assert CalleeUniverseRecognition.coordinate(site) is None


def test_authenticated_numpy_can_cast_has_universe_support() -> None:
    """#5906: kit protocol + import provenance (see protocol test module)."""

    from sugar_lift_py_tests.recognition.callee_universe import (
        CalleeUniverseSupport,
        clear_imported_callee_protocol,
        load_imported_callee_protocol,
    )

    clear_imported_callee_protocol()
    try:
        load_imported_callee_protocol(
            {"numpy.can_cast": CalleeUniverseSupport.NUMPY_CAN_CAST}
        )
        source = (
            "import numpy as np\n"
            "\n"
            "def test_cast(from_, to):\n"
            "    assert np.can_cast(from_, to)\n"
        )

        payload = lift_file_payload(source, "can_cast_covered_fixture.py")

        assert any(
            edge.get("targetSymbol") == "call:numpy.can_cast"
            for edge in payload.call_edges
        )
        assert _universe_gaps(payload) == []

        call = next(
            node
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "can_cast"
        )
        site = SourceFragment.from_node(
            call, "can_cast_covered_fixture.py", source=source
        )
        assert CalleeUniverseRecognition.coordinate(site) == "numpy.can_cast"
        context = FactoryBuildContext(
            filename="can_cast_covered_fixture.py", catalog=default_catalog()
        )
        built = build_node(
            site,
            filename="can_cast_covered_fixture.py",
            role=SugarRole.TERM,
            ctx=context,
        )
        assert built.audit_row.selected == "BuiltinCalleeUniverseSugar"
    finally:
        clear_imported_callee_protocol()


def test_shadowed_numpy_alias_cannot_warrant_can_cast_support() -> None:
    """Lying twin: parameter receiver is not the authenticated numpy import."""

    source = (
        "import numpy as np\n"
        "\n"
        "def test_cast(np, from_, to):\n"
        "    assert np.can_cast(from_, to)\n"
    )

    payload = lift_file_payload(source, "can_cast_shadowed_fixture.py")

    gaps = _universe_gaps(payload)
    assert [gap.ast_kind for gap in gaps] == ["call:numpy.can_cast"]


def test_later_local_rebind_revokes_can_cast_import_warrant() -> None:
    """Lying twin: later function-local rebind must break false recognition."""

    source = (
        "import numpy as np\n"
        "\n"
        "def test_cast(from_, to):\n"
        "    assert np.can_cast(from_, to)\n"
        "    np = replacement\n"
    )

    payload = lift_file_payload(source, "can_cast_late_rebind.py")

    gaps = _universe_gaps(payload)
    assert [gap.ast_kind for gap in gaps] == ["call:numpy.can_cast"]

    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "can_cast"
    )
    site = SourceFragment.from_node(call, "can_cast_late_rebind.py", source=source)
    assert CalleeUniverseRecognition.coordinate(site) is None


def test_unauthenticated_can_cast_fqn_alone_stays_loud() -> None:
    """Lying twin: FQN spelling without import provenance must not silence.

    ``numpy`` is a wholly unbound name here (no import, no parameter) — the
    stronger, more honest current law is that reducing it panics loud at the
    unbound-name floor (``TemporalContext``) rather than silently degrading
    to a graceful universe-coverage gap. Both are refusals; the panic fires
    earlier and cannot be missed.
    """

    source = "def test_cast(from_, to):\n" "    assert numpy.can_cast(from_, to)\n"

    with pytest.raises(FactoryPanic):
        lift_file_payload(source, "can_cast_unauthenticated_fqn.py")

    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "can_cast"
    )
    site = SourceFragment.from_node(
        call, "can_cast_unauthenticated_fqn.py", source=source
    )
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert recognize_callee_universe("call:numpy.can_cast", site=site) is None


def test_authenticated_numpy_isnan_has_universe_support() -> None:
    """#5404 / #5905: kit protocol + import provenance (see protocol test module)."""

    from sugar_lift_py_tests.recognition.callee_universe import (
        CalleeUniverseSupport,
        clear_imported_callee_protocol,
        load_imported_callee_protocol,
    )

    clear_imported_callee_protocol()
    try:
        load_imported_callee_protocol(
            {"numpy.isnan": CalleeUniverseSupport.NUMPY_ISNAN}
        )
        source = (
            "import numpy as np\n"
            "\n"
            "def test_nan(value):\n"
            "    assert np.isnan(value)\n"
        )

        payload = lift_file_payload(source, "isnan_covered_fixture.py")

        assert any(
            edge.get("targetSymbol") == "call:numpy.isnan"
            for edge in payload.call_edges
        )
        assert _universe_gaps(payload) == []

        call = next(
            node
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "isnan"
        )
        site = SourceFragment.from_node(
            call, "isnan_covered_fixture.py", source=source
        )
        assert CalleeUniverseRecognition.coordinate(site) == "numpy.isnan"
        context = FactoryBuildContext(
            filename="isnan_covered_fixture.py", catalog=default_catalog()
        )
        built = build_node(
            site,
            filename="isnan_covered_fixture.py",
            role=SugarRole.TERM,
            ctx=context,
        )
        assert built.audit_row.selected == "BuiltinCalleeUniverseSugar"
    finally:
        clear_imported_callee_protocol()


def test_authenticated_numpy_dtype_has_universe_support() -> None:
    """#5906: kit protocol + import provenance (see protocol test module)."""

    from sugar_lift_py_tests.recognition.callee_universe import (
        CalleeUniverseSupport,
        clear_imported_callee_protocol,
        load_imported_callee_protocol,
    )

    clear_imported_callee_protocol()
    try:
        load_imported_callee_protocol(
            {"numpy.dtype": CalleeUniverseSupport.NUMPY_DTYPE}
        )
        source = (
            "import numpy as np\n"
            "\n"
            "def test_dtype(value):\n"
            "    assert np.dtype(value) == np.dtype(value)\n"
        )

        payload = lift_file_payload(source, "numpy_dtype_covered_fixture.py")

        assert any(
            edge.get("targetSymbol") == "call:numpy.dtype" for edge in payload.call_edges
        )
        assert _universe_gaps(payload) == []
    finally:
        clear_imported_callee_protocol()


def test_non_numpy_import_refutes_numpy_dtype_support() -> None:
    source = (
        "import struct as np\n"
        "\n"
        "def test_dtype(value):\n"
        "    assert np.dtype(value) == np.dtype(value)\n"
    )
    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "dtype"
    )
    site = SourceFragment.from_node(call, "numpy_dtype_lying_fixture.py", source=source)

    assert recognize_callee_universe("call:numpy.dtype", site=site) is None


def test_shadowed_numpy_alias_cannot_warrant_isnan_support() -> None:
    """Lying twin: parameter receiver is not the authenticated numpy import."""

    source = (
        "import numpy as np\n"
        "\n"
        "def test_nan(np, value):\n"
        "    assert np.isnan(value)\n"
    )

    payload = lift_file_payload(source, "isnan_shadowed_fixture.py")

    gaps = _universe_gaps(payload)
    assert [gap.ast_kind for gap in gaps] == ["call:numpy.isnan"]


def test_later_local_rebind_revokes_isnan_import_warrant() -> None:
    """Lying twin: later function-local rebind must break false recognition."""

    source = (
        "import numpy as np\n"
        "\n"
        "def test_nan(value):\n"
        "    assert np.isnan(value)\n"
        "    np = replacement\n"
    )

    payload = lift_file_payload(source, "isnan_late_rebind.py")

    gaps = _universe_gaps(payload)
    assert [gap.ast_kind for gap in gaps] == ["call:numpy.isnan"]

    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "isnan"
    )
    site = SourceFragment.from_node(call, "isnan_late_rebind.py", source=source)
    assert CalleeUniverseRecognition.coordinate(site) is None


def test_unauthenticated_isnan_fqn_alone_stays_loud() -> None:
    """Lying twin: FQN spelling without import provenance must not silence.

    ``numpy`` is a wholly unbound name — the stronger, more honest current
    law panics loud at the unbound-name floor (``TemporalContext``) rather
    than silently degrading to a graceful universe-coverage gap.
    """

    source = "def test_nan(value):\n" "    assert numpy.isnan(value)\n"

    with pytest.raises(FactoryPanic):
        lift_file_payload(source, "isnan_unauthenticated_fqn.py")

    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "isnan"
    )
    site = SourceFragment.from_node(call, "isnan_unauthenticated_fqn.py", source=source)
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert recognize_callee_universe("call:numpy.isnan", site=site) is None


def test_authenticated_numpy_all_has_universe_support() -> None:
    """Qualified numpy.all is distinct from bare builtin all (#5422).

    #5906: kit protocol + import provenance (see protocol test module).
    """

    from sugar_lift_py_tests.recognition.callee_universe import (
        CalleeUniverseSupport,
        clear_imported_callee_protocol,
        load_imported_callee_protocol,
    )

    clear_imported_callee_protocol()
    try:
        load_imported_callee_protocol(
            {"numpy.all": CalleeUniverseSupport.NUMPY_ALL}
        )
        source = (
            "import numpy as np\n"
            "\n"
            "def test_all(value):\n"
            "    assert np.all(value)\n"
        )

        payload = lift_file_payload(source, "numpy_all_covered_fixture.py")

        assert any(
            edge.get("targetSymbol") == "call:numpy.all" for edge in payload.call_edges
        )
        assert _universe_gaps(payload) == []

        call = next(
            node
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "all"
        )
        site = SourceFragment.from_node(
            call, "numpy_all_covered_fixture.py", source=source
        )
        assert CalleeUniverseRecognition.coordinate(site) == "numpy.all"
        context = FactoryBuildContext(
            filename="numpy_all_covered_fixture.py", catalog=default_catalog()
        )
        built = build_node(
            site,
            filename="numpy_all_covered_fixture.py",
            role=SugarRole.TERM,
            ctx=context,
        )
        assert built.audit_row.selected == "BuiltinCalleeUniverseSugar"
    finally:
        clear_imported_callee_protocol()


def test_module_scope_numpy_from_import_all_has_universe_support() -> None:
    """from numpy import all; all(...) authenticates as numpy.all, not bare all.

    #5906: kit protocol + import provenance (see protocol test module).
    """

    from sugar_lift_py_tests.recognition.callee_universe import (
        CalleeUniverseSupport,
        clear_imported_callee_protocol,
        load_imported_callee_protocol,
    )

    clear_imported_callee_protocol()
    try:
        load_imported_callee_protocol(
            {"numpy.all": CalleeUniverseSupport.NUMPY_ALL}
        )
        source = "from numpy import all\nassert all([True])\n"

        payload = lift_file_payload(source, "numpy_all_from_import_fixture.py")

        assert any(
            edge.get("targetSymbol") == "call:numpy.all" for edge in payload.call_edges
        )
        assert _universe_gaps(payload) == []
    finally:
        clear_imported_callee_protocol()


def test_shadowed_numpy_alias_cannot_warrant_all_support() -> None:
    """Lying twin: parameter receiver is not the authenticated numpy import."""

    source = (
        "import numpy as np\n"
        "\n"
        "def test_all(np, value):\n"
        "    assert np.all(value)\n"
    )

    payload = lift_file_payload(source, "numpy_all_shadowed_fixture.py")

    gaps = _universe_gaps(payload)
    assert [gap.ast_kind for gap in gaps] == ["call:numpy.all"]


def test_later_local_rebind_revokes_numpy_all_import_warrant() -> None:
    """Lying twin: later function-local rebind must break false recognition."""

    source = (
        "import numpy as np\n"
        "\n"
        "def test_all(value):\n"
        "    assert np.all(value)\n"
        "    np = replacement\n"
    )

    payload = lift_file_payload(source, "numpy_all_late_rebind.py")

    gaps = _universe_gaps(payload)
    assert [gap.ast_kind for gap in gaps] == ["call:numpy.all"]

    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "all"
    )
    site = SourceFragment.from_node(call, "numpy_all_late_rebind.py", source=source)
    assert CalleeUniverseRecognition.coordinate(site) is None


def test_unauthenticated_numpy_all_fqn_alone_stays_loud() -> None:
    """Lying twin: FQN spelling without import provenance must not silence.

    ``numpy`` is a wholly unbound name — the stronger, more honest current
    law panics loud at the unbound-name floor (``TemporalContext``) rather
    than silently degrading to a graceful universe-coverage gap.
    """

    source = "def test_all(value):\n" "    assert numpy.all(value)\n"

    with pytest.raises(FactoryPanic):
        lift_file_payload(source, "numpy_all_unauthenticated_fqn.py")

    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "all"
    )
    site = SourceFragment.from_node(
        call, "numpy_all_unauthenticated_fqn.py", source=source
    )
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert recognize_callee_universe("call:numpy.all", site=site) is None


def test_authenticated_numpy_issubdtype_has_universe_support() -> None:
    """#5400: requires kit protocol load (see test_imported_callee_protocol_*)."""

    from sugar_lift_py_tests.recognition.callee_universe import (
        CalleeUniverseSupport,
        clear_imported_callee_protocol,
        load_imported_callee_protocol,
    )

    clear_imported_callee_protocol()
    try:
        load_imported_callee_protocol(
            {"numpy.issubdtype": CalleeUniverseSupport.NUMPY_ISSUBDTYPE}
        )
        source = (
            "import numpy as np\n"
            "\n"
            "def test_dtype(left, right):\n"
            "    assert np.issubdtype(left, right)\n"
        )
        payload = lift_file_payload(source, "issubdtype_covered_fixture.py")
        assert any(
            edge.get("targetSymbol") == "call:numpy.issubdtype"
            for edge in payload.call_edges
        )
        assert _universe_gaps(payload) == []
    finally:
        clear_imported_callee_protocol()


def test_shadowed_numpy_alias_cannot_warrant_issubdtype_support() -> None:
    from sugar_lift_py_tests.recognition.callee_universe import (
        CalleeUniverseSupport,
        clear_imported_callee_protocol,
        load_imported_callee_protocol,
    )

    clear_imported_callee_protocol()
    try:
        load_imported_callee_protocol(
            {"numpy.issubdtype": CalleeUniverseSupport.NUMPY_ISSUBDTYPE}
        )
        source = (
            "import numpy as np\n"
            "\n"
            "def test_dtype(np, left, right):\n"
            "    assert np.issubdtype(left, right)\n"
        )
        payload = lift_file_payload(source, "issubdtype_shadowed_fixture.py")
        gaps = _universe_gaps(payload)
        assert [gap.ast_kind for gap in gaps] == ["call:numpy.issubdtype"]
    finally:
        clear_imported_callee_protocol()


def test_authenticated_numpy_allclose_has_universe_support() -> None:
    """#5906: kit protocol + import provenance (see protocol test module)."""

    from sugar_lift_py_tests.recognition.callee_universe import (
        CalleeUniverseSupport,
        clear_imported_callee_protocol,
        load_imported_callee_protocol,
    )

    clear_imported_callee_protocol()
    try:
        load_imported_callee_protocol(
            {"numpy.allclose": CalleeUniverseSupport.NUMPY_ALLCLOSE}
        )
        source = (
            "import numpy as np\n"
            "\n"
            "def test_values(left, right):\n"
            "    assert np.allclose(left, right)\n"
        )

        payload = lift_file_payload(source, "allclose_covered_fixture.py")

        assert any(
            edge.get("targetSymbol") == "call:numpy.allclose"
            for edge in payload.call_edges
        )
        assert _universe_gaps(payload) == []
    finally:
        clear_imported_callee_protocol()


def test_authenticated_numpy_isnan_has_universe_support_corpus_shape() -> None:
    """Truthful corpus shape: the imported receiver warrants ``numpy.isnan``.

    #5404 / #5905: kit protocol + import provenance (see protocol test
    module). Distinct fixture name from
    ``test_authenticated_numpy_isnan_has_universe_support`` above — same law,
    the corpus-realistic ``test_umath.py`` shape (#5905 repro).
    """

    from sugar_lift_py_tests.recognition.callee_universe import (
        CalleeUniverseSupport,
        clear_imported_callee_protocol,
        load_imported_callee_protocol,
    )

    clear_imported_callee_protocol()
    try:
        load_imported_callee_protocol(
            {"numpy.isnan": CalleeUniverseSupport.NUMPY_ISNAN}
        )
        source = (
            "import numpy as np\n"
            "\n"
            "def test_floor_division(div):\n"
            "    assert np.isnan(div), f'div: {div}'\n"
        )

        payload = lift_file_payload(source, "test_umath.py")

        assert any(
            edge.get("targetSymbol") == "call:numpy.isnan" for edge in payload.call_edges
        )
        assert _universe_gaps(payload) == []
    finally:
        clear_imported_callee_protocol()


def test_non_numpy_receiver_refutes_isnan_support() -> None:
    """Lying twin: identical spelling from another import remains unclassified."""

    source = (
        "import math as np\n"
        "\n"
        "def test_floor_division(div):\n"
        "    assert np.isnan(div), f'div: {div}'\n"
    )
    tree = ast.parse(source)
    call = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "isnan"
    )
    site = SourceFragment.from_node(call, "lying_test_umath.py", source=source)

    assert recognize_callee_universe("call:numpy.isnan", site=site) is None


def test_authenticated_numpy_array_tobytes_has_universe_support() -> None:
    """#5906: kit protocol + import provenance (see protocol test module)."""

    from sugar_lift_py_tests.recognition.callee_universe import (
        CalleeUniverseSupport,
        clear_imported_callee_protocol,
        load_imported_callee_protocol,
    )

    clear_imported_callee_protocol()
    try:
        load_imported_callee_protocol(
            {
                "numpy.array.tobytes": CalleeUniverseSupport.NUMPY_ARRAY_TOBYTES,
                "numpy.ndarray.tobytes": CalleeUniverseSupport.NUMPY_ARRAY_TOBYTES,
            }
        )
        source = (
            "import numpy as np\n"
            "\n"
            "def test_bytes():\n"
            "    value = np.array(b'abc')\n"
            "    assert value.tobytes() == b'abc'\n"
        )

        payload = lift_file_payload(source, "tobytes_covered_fixture.py")

        assert any(
            row.get("selected") == "BuiltinCalleeUniverseSugar"
            and row.get("blame") == "tobytes_covered_fixture.py:5:11"
            for row in payload.factory_audits
        )
        assert _universe_gaps(payload) == []

        call = next(
            node
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "tobytes"
        )
        site = SourceFragment.from_node(
            call, "tobytes_covered_fixture.py", source=source
        )
        # Result-call identity joins the constructor import with the member
        # (``numpy.array.tobytes``); bound-native shape spells the class coordinate
        # (``numpy.ndarray.tobytes``). Both are the same authenticated family.
        assert CalleeUniverseRecognition.coordinate(site) in {
            "numpy.array.tobytes",
            "numpy.ndarray.tobytes",
        }
        assert recognize_callee_universe("call:tobytes", site=site) is not None
    finally:
        clear_imported_callee_protocol()


def test_tobytes_spelling_without_native_receiver_stays_loud() -> None:
    source = "def test_bytes(value):\n" "    assert value.tobytes() == b'abc'\n"

    payload = lift_file_payload(source, "tobytes_opaque_receiver.py")

    gaps = _universe_gaps(payload)
    assert [gap.ast_kind for gap in gaps] == ["call:tobytes"]

    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "tobytes"
    )
    site = SourceFragment.from_node(call, "tobytes_opaque_receiver.py", source=source)
    assert CalleeUniverseRecognition.coordinate(site) is None


def test_tobytes_native_receiver_warrant_is_revoked_by_rebind() -> None:
    """Lying twin: rebinding the receiver to opaque data revokes the warrant."""

    source = (
        "import numpy as np\n"
        "\n"
        "def test_bytes(opaque):\n"
        "    value = np.array(b'abc')\n"
        "    value = opaque\n"
        "    assert value.tobytes() == b'abc'\n"
    )

    payload = lift_file_payload(source, "tobytes_rebound_receiver.py")

    gaps = _universe_gaps(payload)
    assert [gap.ast_kind for gap in gaps] == ["call:tobytes"]


def test_authenticated_numpy_shares_memory_has_universe_support() -> None:
    """#5906: kit protocol + import provenance (see protocol test module)."""

    from sugar_lift_py_tests.recognition.callee_universe import (
        CalleeUniverseSupport,
        clear_imported_callee_protocol,
        load_imported_callee_protocol,
    )

    clear_imported_callee_protocol()
    try:
        load_imported_callee_protocol(
            {"numpy.shares_memory": CalleeUniverseSupport.NUMPY_SHARES_MEMORY}
        )
        source = (
            "import numpy as np\n"
            "\n"
            "def test_values(left, right):\n"
            "    assert np.shares_memory(left, right)\n"
        )

        payload = lift_file_payload(source, "shares_memory_covered_fixture.py")

        assert any(
            edge.get("targetSymbol") == "call:numpy.shares_memory"
            for edge in payload.call_edges
        )
        assert _universe_gaps(payload) == []
    finally:
        clear_imported_callee_protocol()


@pytest.mark.parametrize(
    ("source", "expected_kind"),
    (
        (
            "import numpy as np\n"
            "def test_values(np, left, right):\n"
            "    assert np.shares_memory(left, right)\n",
            "call:numpy.shares_memory",
        ),
        (
            "def test_values(left, right):\n" "    assert shares_memory(left, right)\n",
            "call:shares_memory",
        ),
    ),
)
def test_unowned_shares_memory_lookalikes_stay_loud(
    source: str, expected_kind: str
) -> None:
    """Parameter shadow and unimported spelling stay loud universe gaps."""

    payload = lift_file_payload(source, "shares_memory_unowned_fixture.py")

    gaps = _universe_gaps(payload)
    assert [gap.ast_kind for gap in gaps] == [expected_kind]


def test_authenticated_numpy_isdtype_has_universe_support() -> None:
    """#5906: kit protocol + import provenance (see protocol test module)."""

    from sugar_lift_py_tests.recognition.callee_universe import (
        CalleeUniverseSupport,
        clear_imported_callee_protocol,
        load_imported_callee_protocol,
    )

    clear_imported_callee_protocol()
    try:
        load_imported_callee_protocol(
            {"numpy.isdtype": CalleeUniverseSupport.NUMPY_ISDTYPE}
        )
        source = (
            "import numpy as np\n"
            "\n"
            "def test_values(dt):\n"
            "    assert np.isdtype(dt, 'real floating')\n"
        )

        payload = lift_file_payload(source, "isdtype_covered_fixture.py")

        assert any(
            edge.get("targetSymbol") == "call:numpy.isdtype"
            for edge in payload.call_edges
        )
        assert _universe_gaps(payload) == []
    finally:
        clear_imported_callee_protocol()


@pytest.mark.parametrize(
    ("source", "expected_kind"),
    (
        (
            "import numpy as np\n"
            "def test_values(np, dt):\n"
            "    assert np.isdtype(dt, 'real floating')\n",
            "call:numpy.isdtype",
        ),
        (
            "def test_values(dt):\n" "    assert isdtype(dt, 'real floating')\n",
            "call:isdtype",
        ),
    ),
)
def test_unowned_isdtype_lookalikes_stay_loud(source: str, expected_kind: str) -> None:
    """Parameter shadow and unimported spelling stay loud universe gaps."""

    payload = lift_file_payload(source, "isdtype_unowned_fixture.py")

    gaps = _universe_gaps(payload)
    assert [gap.ast_kind for gap in gaps] == [expected_kind]


def test_authenticated_numpy_datetime_data_has_universe_support() -> None:
    """#5906: kit protocol + import provenance (see protocol test module)."""

    from sugar_lift_py_tests.recognition.callee_universe import (
        CalleeUniverseSupport,
        clear_imported_callee_protocol,
        load_imported_callee_protocol,
    )

    clear_imported_callee_protocol()
    try:
        load_imported_callee_protocol(
            {"numpy.datetime_data": CalleeUniverseSupport.NUMPY_DATETIME_DATA}
        )
        source = (
            "import numpy as np\n"
            "\n"
            "def test_values(dt):\n"
            "    assert np.datetime_data(dt) == np.datetime_data(dt)\n"
        )

        payload = lift_file_payload(source, "datetime_data_covered_fixture.py")

        assert any(
            edge.get("targetSymbol") == "call:numpy.datetime_data"
            for edge in payload.call_edges
        )
        assert _universe_gaps(payload) == []
    finally:
        clear_imported_callee_protocol()


@pytest.mark.parametrize(
    ("source", "expected_kind"),
    (
        (
            "import numpy as np\n"
            "def test_values(np, dt):\n"
            "    assert np.datetime_data(dt) == 0\n",
            "call:numpy.datetime_data",
        ),
        (
            "def test_values(dt):\n" "    assert datetime_data(dt) == 0\n",
            "call:datetime_data",
        ),
    ),
)
def test_unowned_datetime_data_lookalikes_stay_loud(
    source: str, expected_kind: str
) -> None:
    """Parameter shadow and unimported spelling stay loud universe gaps."""

    payload = lift_file_payload(source, "datetime_data_unowned_fixture.py")

    gaps = _universe_gaps(payload)
    assert [gap.ast_kind for gap in gaps] == [expected_kind]



def test_authenticated_numpy_markinnerspaces_has_universe_support() -> None:
    """#5906: kit protocol + import provenance (see protocol test module)."""

    from sugar_lift_py_tests.recognition.callee_universe import (
        CalleeUniverseSupport,
        clear_imported_callee_protocol,
        load_imported_callee_protocol,
    )

    clear_imported_callee_protocol()
    try:
        load_imported_callee_protocol(
            {
                "numpy.f2py.crackfortran.markinnerspaces": (
                    CalleeUniverseSupport.NUMPY_MARKINNERSPACES
                )
            }
        )
        source = (
            "from numpy.f2py.crackfortran import markinnerspaces\n"
            "\n"
            "def test_values(s):\n"
            "    assert markinnerspaces(s) == markinnerspaces(s)\n"
        )

        payload = lift_file_payload(source, "markinnerspaces_covered_fixture.py")

        assert any(
            edge.get("targetSymbol") == "call:numpy.f2py.crackfortran.markinnerspaces"
            or edge.get("targetSymbol") == "call:markinnerspaces"
            for edge in payload.call_edges
        )
        assert _universe_gaps(payload) == []
    finally:
        clear_imported_callee_protocol()


@pytest.mark.parametrize(
    ("source", "expected_kind"),
    (
        (
            "from numpy.f2py.crackfortran import markinnerspaces\n"
            "def test_values(markinnerspaces, s):\n"
            "    assert markinnerspaces(s) == s\n",
            "call:markinnerspaces",
        ),
        (
            "def test_values(s):\n"
            "    assert markinnerspaces(s) == s\n",
            "call:markinnerspaces",
        ),
    ),
)
def test_unowned_markinnerspaces_lookalikes_stay_loud(
    source: str, expected_kind: str
) -> None:
    payload = lift_file_payload(source, "markinnerspaces_unowned_fixture.py")

    gaps = _universe_gaps(payload)
    assert [gap.ast_kind for gap in gaps] == [expected_kind]


def test_authenticated_identity_hash_set_item_default_has_universe_support() -> None:
    """#5906: kit protocol + import provenance (see protocol test module)."""

    from sugar_lift_py_tests.recognition.callee_universe import (
        CalleeUniverseSupport,
        clear_imported_callee_protocol,
        load_imported_callee_protocol,
    )

    clear_imported_callee_protocol()
    try:
        load_imported_callee_protocol(
            {
                "numpy._core._multiarray_tests.identity_hash_set_item_default": (
                    CalleeUniverseSupport.NUMPY_IDENTITY_HASH_SET_ITEM_DEFAULT
                )
            }
        )
        source = (
            "from numpy._core._multiarray_tests import identity_hash_set_item_default\n"
            "\n"
            "def test_values(ht, key, value):\n"
            "    assert identity_hash_set_item_default(ht, key, value) is value\n"
        )

        payload = lift_file_payload(source, "identity_hash_covered_fixture.py")

        assert any(
            edge.get("targetSymbol")
            == "call:numpy._core._multiarray_tests.identity_hash_set_item_default"
            or edge.get("targetSymbol") == "call:identity_hash_set_item_default"
            for edge in payload.call_edges
        )
        assert _universe_gaps(payload) == []
    finally:
        clear_imported_callee_protocol()


@pytest.mark.parametrize(
    ("source", "expected_kind"),
    (
        (
            "from numpy._core._multiarray_tests import identity_hash_set_item_default\n"
            "def test_values(identity_hash_set_item_default, ht, key, value):\n"
            "    assert identity_hash_set_item_default(ht, key, value) is value\n",
            "call:identity_hash_set_item_default",
        ),
        (
            "def test_values(ht, key, value):\n"
            "    assert identity_hash_set_item_default(ht, key, value) is value\n",
            "call:identity_hash_set_item_default",
        ),
    ),
)
def test_unowned_identity_hash_set_item_default_lookalikes_stay_loud(
    source: str, expected_kind: str
) -> None:
    payload = lift_file_payload(source, "identity_hash_unowned_fixture.py")

    gaps = _universe_gaps(payload)
    assert [gap.ast_kind for gap in gaps] == [expected_kind]



def test_module_scope_numpy_from_import_has_universe_support() -> None:
    """Module-level imports establish the name; do not revoke as free-var shadow.

    #5906: kit protocol + import provenance (see protocol test module).
    """

    from sugar_lift_py_tests.recognition.callee_universe import (
        CalleeUniverseSupport,
        clear_imported_callee_protocol,
        load_imported_callee_protocol,
    )

    clear_imported_callee_protocol()
    try:
        load_imported_callee_protocol(
            {"numpy.allclose": CalleeUniverseSupport.NUMPY_ALLCLOSE}
        )
        source = "from numpy import allclose\nassert allclose(1, 1)\n"

        payload = lift_file_payload(source, "allclose_module_fixture.py")

        assert any(
            edge.get("targetSymbol") == "call:numpy.allclose"
            for edge in payload.call_edges
        )
        assert _universe_gaps(payload) == []
    finally:
        clear_imported_callee_protocol()


def test_shadowed_numpy_alias_cannot_warrant_allclose_support() -> None:
    source = (
        "import numpy as np\n"
        "\n"
        "def test_values(np, left, right):\n"
        "    assert np.allclose(left, right)\n"
    )

    payload = lift_file_payload(source, "allclose_shadowed_fixture.py")

    gaps = _universe_gaps(payload)
    assert [gap.ast_kind for gap in gaps] == ["call:numpy.allclose"]


@pytest.mark.parametrize(
    "callee", ["issubdtype", "allclose", "can_cast", "isnan", "all"]
)
def test_later_function_local_binding_revokes_numpy_import_warrant(
    callee: str,
) -> None:
    source = (
        "import numpy as np\n"
        "\n"
        "def test_values(left, right):\n"
        f"    assert np.{callee}(left, right)\n"
        "    np = replacement\n"
    )

    payload = lift_file_payload(source, "numpy_late_shadow_fixture.py")

    gaps = _universe_gaps(payload)
    assert [gap.ast_kind for gap in gaps] == [f"call:numpy.{callee}"]


def test_later_exception_target_revokes_numpy_import_warrant() -> None:
    source = (
        "import numpy as np\n"
        "\n"
        "def test_values(left, right):\n"
        "    assert np.allclose(left, right)\n"
        "    try:\n"
        "        raise ValueError()\n"
        "    except ValueError as np:\n"
        "        pass\n"
    )

    payload = lift_file_payload(source, "numpy_except_shadow_fixture.py")

    gaps = _universe_gaps(payload)
    assert [gap.ast_kind for gap in gaps] == ["call:numpy.allclose"]


def test_comprehension_target_does_not_revoke_numpy_import_warrant() -> None:
    """#5906: kit protocol + import provenance (see protocol test module)."""

    from sugar_lift_py_tests.recognition.callee_universe import (
        CalleeUniverseSupport,
        clear_imported_callee_protocol,
        load_imported_callee_protocol,
    )

    clear_imported_callee_protocol()
    try:
        load_imported_callee_protocol(
            {"numpy.allclose": CalleeUniverseSupport.NUMPY_ALLCLOSE}
        )
        source = (
            "import numpy as np\n"
            "\n"
            "def test_values(left, right):\n"
            "    assert np.allclose(left, right)\n"
            "    aliases = [np for np in ()]\n"
        )

        payload = lift_file_payload(source, "numpy_comprehension_scope_fixture.py")

        assert _universe_gaps(payload) == []
    finally:
        clear_imported_callee_protocol()


def test_later_match_capture_is_a_lexical_function_binding() -> None:
    source = (
        "def test_values(left, right):\n"
        "    assert np.allclose(left, right)\n"
        "    match left:\n"
        "        case np:\n"
        "            pass\n"
    )
    tree = ast.parse(source)
    call = next(node for node in ast.walk(tree) if isinstance(node, ast.Call))
    site = SourceFragment.from_node(
        call,
        "numpy_match_shadow_fixture.py",
        source=source,
    )

    assert "np" in lexical_function_bindings(site)


@pytest.mark.parametrize(
    "assertion",
    [
        "(lambda np: np.allclose(left, right))(left)",
        "all(np.allclose(left, right) for np in sources)",
        (
            "(lambda value: value)(left) or "
            "(lambda np: np.allclose(left, right))(left)"
        ),
    ],
)
def test_nested_scope_binding_cannot_warrant_outer_numpy_import(
    assertion: str,
) -> None:
    source = (
        "import numpy as np\n"
        "\n"
        "def test_values(left, right, sources):\n"
        f"    assert {assertion}\n"
    )
    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "allclose"
    )
    site = SourceFragment.from_node(
        call,
        "numpy_nested_scope_fixture.py",
        source=source,
    )

    assert recognize_callee_universe("call:numpy.allclose", site=site) is None


def test_floor_protocol_method_named_test_is_not_an_assertion_source() -> None:
    source = (
        "class Protocol:\n"
        "    def test_python_type(self, value):\n"
        "        return native_type_tester(value)\n"
    )

    payload = lift_file_payload(source, "floor_protocol.py")

    assert any(
        edge.get("targetSymbol") == "call:native_type_tester"
        for edge in payload.call_edges
    )
    assert _universe_gaps(payload) == []


def test_authenticated_json_loads_has_universe_support() -> None:
    source = (
        "import json\n"
        "\n"
        "def test_loads(payload):\n"
        "    assert json.loads(payload) is not None\n"
    )

    payload = lift_file_payload(source, "json_loads_covered_fixture.py")

    assert any(
        edge.get("targetSymbol") == "call:json.loads" for edge in payload.call_edges
    )
    assert _universe_gaps(payload) == []

    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "loads"
    )
    site = SourceFragment.from_node(
        call, "json_loads_covered_fixture.py", source=source
    )
    assert CalleeUniverseRecognition.coordinate(site) == "json.loads"
    context = FactoryBuildContext(
        filename="json_loads_covered_fixture.py", catalog=default_catalog()
    )
    built = build_node(
        site,
        filename="json_loads_covered_fixture.py",
        role=SugarRole.TERM,
        ctx=context,
    )
    assert built.audit_row.selected == "BuiltinCalleeUniverseSugar"


def test_authenticated_from_import_json_loads_has_universe_support() -> None:
    # Prefer non-equality use of the free parameter so install-source dig does
    # not recurse into the stdlib json body under this fixture.
    source = (
        "from json import loads\n"
        "\n"
        "def test_loads(payload):\n"
        "    assert loads(payload) is not None\n"
    )

    payload = lift_file_payload(source, "json_loads_from_covered.py")

    assert any(
        edge.get("targetSymbol") == "call:json.loads" for edge in payload.call_edges
    )
    assert _universe_gaps(payload) == []


def test_shadowed_json_alias_cannot_warrant_loads_support() -> None:
    """Lying twin: parameter receiver is not the authenticated json import."""

    source = (
        "import json\n"
        "\n"
        "def test_loads(json, payload):\n"
        "    assert json.loads(payload) is not None\n"
    )

    payload = lift_file_payload(source, "json_loads_shadowed_fixture.py")

    gaps = _universe_gaps(payload)
    assert [gap.ast_kind for gap in gaps] == ["call:json.loads"]


def test_later_local_rebind_revokes_json_loads_import_warrant() -> None:
    """Lying twin: later function-local rebind must break false recognition."""

    source = (
        "import json\n"
        "\n"
        "def test_loads(payload):\n"
        "    assert json.loads(payload) is not None\n"
        "    json = replacement\n"
    )

    payload = lift_file_payload(source, "json_loads_late_rebind.py")

    gaps = _universe_gaps(payload)
    assert [gap.ast_kind for gap in gaps] == ["call:json.loads"]

    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "loads"
    )
    site = SourceFragment.from_node(call, "json_loads_late_rebind.py", source=source)
    assert CalleeUniverseRecognition.coordinate(site) is None


def test_unauthenticated_json_loads_fqn_alone_stays_loud() -> None:
    """Lying twin: FQN spelling without import provenance must not silence."""

    source = "def test_loads(payload):\n" "    assert json.loads(payload) is not None\n"

    payload = lift_file_payload(source, "json_loads_unauthenticated_fqn.py")

    gaps = _universe_gaps(payload)
    assert gaps
    assert all("loads" in gap.ast_kind for gap in gaps)

    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "loads"
    )
    site = SourceFragment.from_node(
        call, "json_loads_unauthenticated_fqn.py", source=source
    )
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert recognize_callee_universe("call:json.loads", site=site) is None


def test_authenticated_dataclasses_asdict_has_universe_support() -> None:
    source = (
        "import dataclasses\n"
        "\n"
        "def test_asdict(value):\n"
        "    assert dataclasses.asdict(value) is not None\n"
    )

    payload = lift_file_payload(source, "asdict_covered_fixture.py")

    assert any(
        edge.get("targetSymbol") == "call:dataclasses.asdict"
        for edge in payload.call_edges
    )
    assert _universe_gaps(payload) == []

    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "asdict"
    )
    site = SourceFragment.from_node(call, "asdict_covered_fixture.py", source=source)
    assert CalleeUniverseRecognition.coordinate(site) == "dataclasses.asdict"
    context = FactoryBuildContext(
        filename="asdict_covered_fixture.py", catalog=default_catalog()
    )
    built = build_node(
        site,
        filename="asdict_covered_fixture.py",
        role=SugarRole.TERM,
        ctx=context,
    )
    assert built.audit_row.selected == "BuiltinCalleeUniverseSugar"


def test_authenticated_from_import_asdict_has_universe_support() -> None:
    source = (
        "from dataclasses import asdict\n"
        "\n"
        "def test_asdict(value):\n"
        "    assert asdict(value) is not None\n"
    )

    payload = lift_file_payload(source, "asdict_from_covered.py")

    assert any(
        edge.get("targetSymbol") == "call:dataclasses.asdict"
        for edge in payload.call_edges
    )
    assert _universe_gaps(payload) == []


def test_shadowed_dataclasses_alias_cannot_warrant_asdict_support() -> None:
    """Lying twin: parameter receiver is not the authenticated dataclasses import."""

    source = (
        "import dataclasses\n"
        "\n"
        "def test_asdict(dataclasses, value):\n"
        "    assert dataclasses.asdict(value) is not None\n"
    )

    payload = lift_file_payload(source, "asdict_shadowed_fixture.py")

    gaps = _universe_gaps(payload)
    assert [gap.ast_kind for gap in gaps] == ["call:dataclasses.asdict"]


def test_later_local_rebind_revokes_asdict_import_warrant() -> None:
    """Lying twin: later function-local rebind must break false recognition."""

    source = (
        "from dataclasses import asdict\n"
        "\n"
        "def test_asdict(value):\n"
        "    assert asdict(value) is not None\n"
        "    asdict = replacement\n"
    )

    payload = lift_file_payload(source, "asdict_late_rebind.py")

    gaps = _universe_gaps(payload)
    assert [gap.ast_kind for gap in gaps] == ["call:dataclasses.asdict"]

    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "asdict"
    )
    site = SourceFragment.from_node(call, "asdict_late_rebind.py", source=source)
    assert CalleeUniverseRecognition.coordinate(site) is None


def test_unauthenticated_asdict_fqn_alone_stays_loud() -> None:
    """Lying twin: FQN spelling without import provenance must not silence."""

    source = (
        "def test_asdict(value):\n" "    assert dataclasses.asdict(value) is not None\n"
    )

    payload = lift_file_payload(source, "asdict_unauthenticated_fqn.py")

    gaps = _universe_gaps(payload)
    assert gaps
    assert all("asdict" in gap.ast_kind for gap in gaps)

    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "asdict"
    )
    site = SourceFragment.from_node(
        call, "asdict_unauthenticated_fqn.py", source=source
    )
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert recognize_callee_universe("call:dataclasses.asdict", site=site) is None


def test_authenticated_dataclasses_is_dataclass_has_universe_support() -> None:
    source = (
        "import dataclasses\n"
        "\n"
        "def test_is_dataclass(value):\n"
        "    assert dataclasses.is_dataclass(value) is not None\n"
    )

    payload = lift_file_payload(source, "is_dataclass_covered_fixture.py")

    assert any(
        edge.get("targetSymbol") == "call:dataclasses.is_dataclass"
        for edge in payload.call_edges
    )
    assert _universe_gaps(payload) == []

    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "is_dataclass"
    )
    site = SourceFragment.from_node(
        call, "is_dataclass_covered_fixture.py", source=source
    )
    assert CalleeUniverseRecognition.coordinate(site) == "dataclasses.is_dataclass"
    context = FactoryBuildContext(
        filename="is_dataclass_covered_fixture.py", catalog=default_catalog()
    )
    built = build_node(
        site,
        filename="is_dataclass_covered_fixture.py",
        role=SugarRole.TERM,
        ctx=context,
    )
    assert built.audit_row.selected == "BuiltinCalleeUniverseSugar"


def test_authenticated_from_import_is_dataclass_has_universe_support() -> None:
    source = (
        "from dataclasses import is_dataclass\n"
        "\n"
        "def test_is_dataclass(value):\n"
        "    assert is_dataclass(value) is not None\n"
    )

    payload = lift_file_payload(source, "is_dataclass_from_covered.py")

    assert any(
        edge.get("targetSymbol") == "call:dataclasses.is_dataclass"
        for edge in payload.call_edges
    )
    assert _universe_gaps(payload) == []


def test_shadowed_dataclasses_alias_cannot_warrant_is_dataclass_support() -> None:
    """Lying twin: parameter receiver is not the authenticated dataclasses import."""

    source = (
        "import dataclasses\n"
        "\n"
        "def test_is_dataclass(dataclasses, value):\n"
        "    assert dataclasses.is_dataclass(value) is not None\n"
    )

    payload = lift_file_payload(source, "is_dataclass_shadowed_fixture.py")

    gaps = _universe_gaps(payload)
    assert [gap.ast_kind for gap in gaps] == ["call:dataclasses.is_dataclass"]


def test_later_local_rebind_revokes_is_dataclass_import_warrant() -> None:
    """Lying twin: later function-local rebind must break false recognition."""

    source = (
        "from dataclasses import is_dataclass\n"
        "\n"
        "def test_is_dataclass(value):\n"
        "    assert is_dataclass(value) is not None\n"
        "    is_dataclass = replacement\n"
    )

    payload = lift_file_payload(source, "is_dataclass_late_rebind.py")

    gaps = _universe_gaps(payload)
    assert [gap.ast_kind for gap in gaps] == ["call:dataclasses.is_dataclass"]

    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "is_dataclass"
    )
    site = SourceFragment.from_node(call, "is_dataclass_late_rebind.py", source=source)
    assert CalleeUniverseRecognition.coordinate(site) is None


def test_unauthenticated_is_dataclass_fqn_alone_stays_loud() -> None:
    """Lying twin: FQN spelling without import provenance must not silence."""

    source = (
        "def test_is_dataclass(value):\n"
        "    assert dataclasses.is_dataclass(value) is not None\n"
    )

    payload = lift_file_payload(source, "is_dataclass_unauthenticated_fqn.py")

    gaps = _universe_gaps(payload)
    assert gaps
    assert all("is_dataclass" in gap.ast_kind for gap in gaps)

    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "is_dataclass"
    )
    site = SourceFragment.from_node(
        call, "is_dataclass_unauthenticated_fqn.py", source=source
    )
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert recognize_callee_universe("call:dataclasses.is_dataclass", site=site) is None


def test_authenticated_math_isclose_has_universe_support() -> None:
    source = (
        "import math\n"
        "\n"
        "def test_isclose(a, b):\n"
        "    assert math.isclose(a, b) is not None\n"
    )

    payload = lift_file_payload(source, "isclose_covered_fixture.py")

    assert any(
        edge.get("targetSymbol") == "call:math.isclose" for edge in payload.call_edges
    )
    assert _universe_gaps(payload) == []

    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "isclose"
    )
    site = SourceFragment.from_node(call, "isclose_covered_fixture.py", source=source)
    assert CalleeUniverseRecognition.coordinate(site) == "math.isclose"
    context = FactoryBuildContext(
        filename="isclose_covered_fixture.py", catalog=default_catalog()
    )
    built = build_node(
        site,
        filename="isclose_covered_fixture.py",
        role=SugarRole.TERM,
        ctx=context,
    )
    assert built.audit_row.selected == "BuiltinCalleeUniverseSugar"


def test_authenticated_from_import_isclose_has_universe_support() -> None:
    source = (
        "from math import isclose\n"
        "\n"
        "def test_isclose(a, b):\n"
        "    assert isclose(a, b) is not None\n"
    )

    payload = lift_file_payload(source, "isclose_from_covered.py")

    assert any(
        edge.get("targetSymbol") == "call:math.isclose" for edge in payload.call_edges
    )
    assert _universe_gaps(payload) == []


def test_shadowed_math_alias_cannot_warrant_isclose_support() -> None:
    """Lying twin: parameter receiver is not the authenticated math import."""

    source = (
        "import math\n"
        "\n"
        "def test_isclose(math, a, b):\n"
        "    assert math.isclose(a, b) is not None\n"
    )

    payload = lift_file_payload(source, "isclose_shadowed_fixture.py")

    gaps = _universe_gaps(payload)
    assert [gap.ast_kind for gap in gaps] == ["call:math.isclose"]


def test_later_local_rebind_revokes_isclose_import_warrant() -> None:
    """Lying twin: later function-local rebind must break false recognition."""

    source = (
        "from math import isclose\n"
        "\n"
        "def test_isclose(a, b):\n"
        "    assert isclose(a, b) is not None\n"
        "    isclose = replacement\n"
    )

    payload = lift_file_payload(source, "isclose_late_rebind.py")

    gaps = _universe_gaps(payload)
    assert [gap.ast_kind for gap in gaps] == ["call:math.isclose"]

    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "isclose"
    )
    site = SourceFragment.from_node(call, "isclose_late_rebind.py", source=source)
    assert CalleeUniverseRecognition.coordinate(site) is None


def test_unauthenticated_isclose_fqn_alone_stays_loud() -> None:
    """Lying twin: FQN spelling without import provenance must not silence."""

    source = "def test_isclose(a, b):\n" "    assert math.isclose(a, b) is not None\n"

    payload = lift_file_payload(source, "isclose_unauthenticated_fqn.py")

    gaps = _universe_gaps(payload)
    assert gaps
    assert all("isclose" in gap.ast_kind for gap in gaps)

    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "isclose"
    )
    site = SourceFragment.from_node(
        call, "isclose_unauthenticated_fqn.py", source=source
    )
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert recognize_callee_universe("call:math.isclose", site=site) is None
