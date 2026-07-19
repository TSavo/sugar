from __future__ import annotations

import ast

import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
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


def test_builtin_covered_callee_emits_no_universe_gap() -> None:
    source = "def test_len(value):\n    assert len(value) >= 0\n"

    payload = lift_file_payload(source, "builtin_covered_fixture.py")

    assert any(edge.get("targetSymbol") == "call:len" for edge in payload.call_edges)
    assert _universe_gaps(payload) == []


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

    if callee in {"type", "dtype", "all"}:
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
        assert built.audit_row.selected == "BuiltinCalleeUniverseSugar"


@pytest.mark.parametrize("callee", ["get_handler_name", "conv", "all"])
def test_shadowed_authenticated_coordinate_stays_unclassified(callee: str) -> None:
    source = f"def test_shadowed({callee}):\n" f"    assert {callee}(5) == 5\n"

    payload = lift_file_payload(source, f"shadowed_{callee}.py")

    gaps = _universe_gaps(payload)
    assert len(gaps) == 1
    assert gaps[0].ast_kind == f"call:{callee}"


def test_unwarranted_receiver_converter_stays_unclassified() -> None:
    source = (
        "import math as mt\n"
        "class TestConverter:\n"
        "    conv = mt.sqrt\n"
        "    def test_shadowed(self):\n"
        "        assert self.conv(5) == 5\n"
    )

    payload = lift_file_payload(source, "shadowed_receiver_conv.py")

    gaps = _universe_gaps(payload)
    assert len(gaps) == 1
    assert gaps[0].ast_kind == "call:conv"


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
    source = (
        "import numpy as np\n"
        "\n"
        "def test_cast(from_, to):\n"
        "    assert np.can_cast(from_, to)\n"
    )

    payload = lift_file_payload(source, "can_cast_covered_fixture.py")

    assert any(
        edge.get("targetSymbol") == "call:numpy.can_cast" for edge in payload.call_edges
    )
    assert _universe_gaps(payload) == []

    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "can_cast"
    )
    site = SourceFragment.from_node(call, "can_cast_covered_fixture.py", source=source)
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
    """Lying twin: FQN spelling without import provenance must not silence."""

    source = "def test_cast(from_, to):\n" "    assert numpy.can_cast(from_, to)\n"

    payload = lift_file_payload(source, "can_cast_unauthenticated_fqn.py")

    gaps = _universe_gaps(payload)
    assert gaps
    assert all("can_cast" in gap.ast_kind for gap in gaps)

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
    source = (
        "import numpy as np\n"
        "\n"
        "def test_nan(value):\n"
        "    assert np.isnan(value)\n"
    )

    payload = lift_file_payload(source, "isnan_covered_fixture.py")

    assert any(
        edge.get("targetSymbol") == "call:numpy.isnan" for edge in payload.call_edges
    )
    assert _universe_gaps(payload) == []

    call = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "isnan"
    )
    site = SourceFragment.from_node(call, "isnan_covered_fixture.py", source=source)
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
    """Lying twin: FQN spelling without import provenance must not silence."""

    source = "def test_nan(value):\n" "    assert numpy.isnan(value)\n"

    payload = lift_file_payload(source, "isnan_unauthenticated_fqn.py")

    gaps = _universe_gaps(payload)
    assert gaps
    assert all("isnan" in gap.ast_kind for gap in gaps)

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
    """Qualified numpy.all is distinct from bare builtin all (#5422)."""

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
    site = SourceFragment.from_node(call, "numpy_all_covered_fixture.py", source=source)
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


def test_module_scope_numpy_from_import_all_has_universe_support() -> None:
    """from numpy import all; all(...) authenticates as numpy.all, not bare all."""

    source = "from numpy import all\nassert all([True])\n"

    payload = lift_file_payload(source, "numpy_all_from_import_fixture.py")

    assert any(
        edge.get("targetSymbol") == "call:numpy.all" for edge in payload.call_edges
    )
    assert _universe_gaps(payload) == []


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
    """Lying twin: FQN spelling without import provenance must not silence."""

    source = "def test_all(value):\n" "    assert numpy.all(value)\n"

    payload = lift_file_payload(source, "numpy_all_unauthenticated_fqn.py")

    gaps = _universe_gaps(payload)
    assert gaps
    # Without import provenance the leaf spelling is the only testimony
    # (call:all), not the qualified numpy.all coordinate.
    assert all(gap.ast_kind in {"call:all", "call:numpy.all"} for gap in gaps)

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


def test_shadowed_numpy_alias_cannot_warrant_issubdtype_support() -> None:
    source = (
        "import numpy as np\n"
        "\n"
        "def test_dtype(np, left, right):\n"
        "    assert np.issubdtype(left, right)\n"
    )

    payload = lift_file_payload(source, "issubdtype_shadowed_fixture.py")

    gaps = _universe_gaps(payload)
    assert [gap.ast_kind for gap in gaps] == ["call:numpy.issubdtype"]


def test_authenticated_numpy_allclose_has_universe_support() -> None:
    source = (
        "import numpy as np\n"
        "\n"
        "def test_values(left, right):\n"
        "    assert np.allclose(left, right)\n"
    )

    payload = lift_file_payload(source, "allclose_covered_fixture.py")

    assert any(
        edge.get("targetSymbol") == "call:numpy.allclose" for edge in payload.call_edges
    )
    assert _universe_gaps(payload) == []


def test_module_scope_numpy_from_import_has_universe_support() -> None:
    """Module-level imports establish the name; do not revoke as free-var shadow."""

    source = "from numpy import allclose\nassert allclose(1, 1)\n"

    payload = lift_file_payload(source, "allclose_module_fixture.py")

    assert any(
        edge.get("targetSymbol") == "call:numpy.allclose" for edge in payload.call_edges
    )
    assert _universe_gaps(payload) == []


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
    source = (
        "import numpy as np\n"
        "\n"
        "def test_values(left, right):\n"
        "    assert np.allclose(left, right)\n"
        "    aliases = [np for np in ()]\n"
    )

    payload = lift_file_payload(source, "numpy_comprehension_scope_fixture.py")

    assert _universe_gaps(payload) == []


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
