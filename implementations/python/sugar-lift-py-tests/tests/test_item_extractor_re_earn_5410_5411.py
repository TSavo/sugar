"""Re-earn call:item (#5410) and call:extractor (#5411) without logo tables.

Measurement (main, post-#5614/#5612 logo deletion):

- call:item — still drained by surviving provenance:
  Assign-bound import constructor (``arr = np.array(...); arr.item()``) via
  ``_receiver_has_imported_call_definition`` + receiver leaf ``item``.
  Lookalike parameter receivers stay unowned.
- call:extractor — was loud for for-unpacked lambdas from
  ``interesting_binop_operands``; re-earned via Assign-lambda and for-unpacked
  lambda provenance (no vendor logos).

Lying twins must refute; bare/wrong bindings stay FactoryPanic / unowned.
"""

from __future__ import annotations

import ast

from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.kit_rpc.factory_walk_row_dto import FactoryWalkRedRowDto
from sugar_lift_py_tests.lift_rpc import lift_file_payload
from sugar_lift_py_tests.recognition.callee_universe import (
    CalleeUniverseRecognition,
    CalleeUniverseSupport,
    recognize_callee_universe,
)
from sugar_lift_py_tests.sugar.builtin_callee_universe_sugar import (
    BuiltinCalleeUniverseSugar,
)


def _site(source: str, *, attr: str | None = None, name: str | None = None):
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        if attr and isinstance(node.func, ast.Attribute) and node.func.attr == attr:
            return SourceFragment.from_node(node, "t.py", source=source)
        if name and isinstance(node.func, ast.Name) and node.func.id == name:
            return SourceFragment.from_node(node, "t.py", source=source)
    raise AssertionError("no site")


def _universe_gaps(source: str, leaf: str) -> list:
    payload = lift_file_payload(source, f"{leaf}.py")
    return [
        row
        for row in payload.factory_walk
        if isinstance(row, FactoryWalkRedRowDto)
        and "callee universe coverage" in row.reason
        and leaf in str(row.ast_kind)
    ]


# --- #5410 call:item (still drained by provenance; lock it) ---


def test_item_assign_bound_import_ctor_still_authenticates() -> None:
    source = (
        "import numpy as np\n"
        "\n"
        "def test_a():\n"
        "    arr = np.array([1], dtype=object)\n"
        "    assert arr.item() == 1\n"
    )
    site = _site(source, attr="item")
    assert CalleeUniverseRecognition.coordinate(site) == "item"
    assert BuiltinCalleeUniverseSugar.owns(site) is True
    assert (
        recognize_callee_universe("call:item", site=site)
        is CalleeUniverseSupport.BOUND_SOURCE_CALLABLE
    )
    assert _universe_gaps(source, "item") == []


def test_item_lookalike_parameter_receiver_stays_loud() -> None:
    source = (
        "def test_a(arr):\n"
        "    assert arr.item() == 1\n"
    )
    site = _site(source, attr="item")
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert BuiltinCalleeUniverseSugar.owns(site) is False
    assert recognize_callee_universe(site=site) is None


def test_item_rebind_revokes_receiver_warrant() -> None:
    source = (
        "import numpy as np\n"
        "\n"
        "def test_a(other):\n"
        "    arr = np.array([1], dtype=object)\n"
        "    arr = other\n"
        "    assert arr.item() == 1\n"
    )
    site = _site(source, attr="item")
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert BuiltinCalleeUniverseSugar.owns(site) is False


# --- #5411 call:extractor ---


def test_extractor_assign_lambda_authenticates() -> None:
    source = (
        "def test_a(res):\n"
        "    extractor = lambda x: x\n"
        "    assert extractor(res) == 0\n"
    )
    site = _site(source, name="extractor")
    assert CalleeUniverseRecognition.coordinate(site) == "extractor"
    assert BuiltinCalleeUniverseSugar.owns(site) is True
    assert (
        recognize_callee_universe("call:extractor", site=site)
        is CalleeUniverseSupport.BOUND_SOURCE_CALLABLE
    )
    assert _universe_gaps(source, "extractor") == []


def test_extractor_for_unpacked_lambda_from_generator_authenticates() -> None:
    """Corpus shape: interesting_binop_operands → for …, extractor, …"""

    source = (
        "def interesting_binop_operands(val1, val2, dtype):\n"
        "    extractor = lambda res: res\n"
        "    yield val1, val2, extractor, 'scalars'\n"
        "\n"
        "def test_signed_division_overflow(res):\n"
        "    to_check = interesting_binop_operands(1, -1, 'i')\n"
        "    for op1, op2, extractor, operand_identifier in to_check:\n"
        "        assert extractor(res) == 0\n"
    )
    site = _site(source, name="extractor")
    assert CalleeUniverseRecognition.coordinate(site) == "extractor"
    assert BuiltinCalleeUniverseSugar.owns(site) is True
    assert (
        recognize_callee_universe("call:extractor", site=site)
        is CalleeUniverseSupport.BOUND_SOURCE_CALLABLE
    )
    assert _universe_gaps(source, "extractor") == []


def test_extractor_for_direct_generator_call_authenticates() -> None:
    source = (
        "def interesting():\n"
        "    extractor = lambda res: res\n"
        "    yield 1, extractor\n"
        "\n"
        "def test_a(res):\n"
        "    for op1, extractor in interesting():\n"
        "        assert extractor(res) == 0\n"
    )
    site = _site(source, name="extractor")
    assert BuiltinCalleeUniverseSugar.owns(site) is True
    assert _universe_gaps(source, "extractor") == []


def test_extractor_lookalike_parameter_stays_loud() -> None:
    source = (
        "def test_a(extractor, res):\n"
        "    assert extractor(res) == 0\n"
    )
    site = _site(source, name="extractor")
    assert CalleeUniverseRecognition.coordinate(site) is None
    assert BuiltinCalleeUniverseSugar.owns(site) is False
    assert _universe_gaps(source, "extractor")  # still a universe gap


def test_extractor_for_without_lambda_in_generator_stays_loud() -> None:
    """Lying twin: generator yields a non-lambda third binding."""

    source = (
        "def interesting():\n"
        "    extractor = 1\n"
        "    yield 1, extractor\n"
        "\n"
        "def test_a(res):\n"
        "    for op1, extractor in interesting():\n"
        "        assert extractor(res) == 0\n"
    )
    site = _site(source, name="extractor")
    assert BuiltinCalleeUniverseSugar.owns(site) is False
    assert CalleeUniverseRecognition.coordinate(site) is None
