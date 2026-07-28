"""Exception-class testimony: truthful absence vs loud implementation failure.

``_exception_class_testimony_or_absence`` must not convert unexpected errors into
``class_value=None``. Only ``SugarNotWritten`` is authority unavailable.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_python_source.manager_summary_derivation import (
    _exception_class_testimony_or_absence,
    populate_source_derived_resource_refs,
)
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


class _FakeFragment:
    pass


class _FakeNode:
    def __init__(self, unit):
        self.unit = unit
        self.fragment = _FakeFragment()


class _FakeUnit:
    def __init__(self, side_effect):
        self._side_effect = side_effect

    def exception_class_value(self, node):
        if callable(self._side_effect):
            return self._side_effect(node)
        if isinstance(self._side_effect, BaseException):
            raise self._side_effect
        return self._side_effect


def test_sugar_not_written_is_truthful_absence():
    """Expected producer refusal: SugarNotWritten → class_value=None."""
    unit = _FakeUnit(
        SugarNotWritten(
            blame=_FakeFragment(),
            owner="SourceUnit.exception_class_value",
            observed="exception class lacks a closed authenticated base graph",
            requested="source-authenticated ClassValue ancestry",
            fix="keep computed, cyclic, or opaque exception ancestry loud",
        )
    )
    node = _FakeNode(unit)
    assert _exception_class_testimony_or_absence(unit, node) is None


def test_successful_class_value_passes_through():
    """Positive arm: successful projection is returned unchanged."""
    sentinel = object()
    unit = _FakeUnit(lambda node: sentinel)
    node = _FakeNode(unit)
    assert _exception_class_testimony_or_absence(unit, node) is sentinel


def test_unexpected_runtime_error_propagates_loud():
    """Mutation twin: unexpected RuntimeError must not become class_value=None."""
    unit = _FakeUnit(RuntimeError("implementation defect in exception_class_value"))
    node = _FakeNode(unit)
    with pytest.raises(RuntimeError, match="implementation defect"):
        _exception_class_testimony_or_absence(unit, node)


def test_value_error_invariant_propagates_loud():
    """Invariant-style ValueError must not collapse to absence."""
    unit = _FakeUnit(ValueError("class graph CID mismatch"))
    node = _FakeNode(unit)
    with pytest.raises(ValueError, match="CID mismatch"):
        _exception_class_testimony_or_absence(unit, node)


def test_construction_panic_propagates_loud():
    """ConstructionPanic is BaseException-level loud failure, not absence."""
    from sugar_lift_py_tests.gap.info import ConstructionGap, GapKind, GapLocus

    unit = _FakeUnit(
        ConstructionPanic(
            ConstructionGap(
                owner="exception_class_value",
                blame="fake:0:0",
                observed="invariant broken in class graph construction",
                requested="closed ClassValue",
                fix="fix the producer; never swallow into class_value=None",
                gap_kind=GapKind.FLOOR,
                gap_locus=GapLocus.CONSTRUCTION,
            )
        )
    )
    node = _FakeNode(unit)
    with pytest.raises(ConstructionPanic):
        _exception_class_testimony_or_absence(unit, node)


def test_broad_exception_catch_is_gone_from_source():
    """No residual except Exception around exception_class_value."""
    import inspect
    import textwrap

    import sugar_lift_python_source.manager_summary_derivation as derivation

    source = textwrap.dedent(inspect.getsource(derivation))
    # The helper must catch SugarNotWritten only.
    helper = textwrap.dedent(
        inspect.getsource(derivation._exception_class_testimony_or_absence)
    )
    assert "except SugarNotWritten" in helper
    assert "except Exception" not in helper
    # Call site must route through the helper, not a bare broad catch.
    assert "_exception_class_testimony_or_absence" in source
    # Guard against re-introducing the old swallow next to exception_class_value.
    for line in source.splitlines():
        if "exception_class_value" in line and "except Exception" in line:
            pytest.fail(f"broad catch adjacent to exception_class_value: {line}")


def test_builtin_valueerror_formal_still_seals_with_class_value(tmp_path: Path):
    """Successful builtin exception identity path unchanged through populate."""
    import csv
    import importlib.metadata

    package = tmp_path / "arbitrary"
    package.mkdir()
    (package / "__init__.py").write_text(
        "from arbitrary.manager import boundary\n", encoding="utf-8"
    )
    (package / "manager.py").write_text(
        "class Boundary:\n"
        "    def __init__(self, expected, match=None):\n"
        "        self.expected = expected\n"
        "        self.match = match\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        if effect_type is None:\n"
        "            raise RuntimeError()\n"
        "        return effect_type is self.expected\n"
        "\n"
        "def boundary(expected, match=None):\n"
        "    return Boundary(expected, match)\n",
        encoding="utf-8",
    )
    metadata = tmp_path / "arbitrary_dist-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: arbitrary-dist\nVersion: 1.0\n",
        encoding="utf-8",
    )
    files = (
        "arbitrary/__init__.py",
        "arbitrary/manager.py",
        "arbitrary_dist-1.0.dist-info/METADATA",
        "arbitrary_dist-1.0.dist-info/RECORD",
    )
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for file in files:
            writer.writerow((file, "", ""))
    dist = importlib.metadata.Distribution.at(metadata)

    consumer = tmp_path / "consumer.py"
    consumer.write_text(
        "import arbitrary\n"
        "def use():\n"
        "    with arbitrary.boundary(ValueError) as info:\n"
        "        raise ValueError('boom')\n",
        encoding="utf-8",
    )
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        path_source(str(consumer)),
        construction_context=context,
    )
    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=consumer,
        distribution_index={"arbitrary": dist},
    )
    refs = list(context.source_derived_contract_refs.values())
    assert refs, "expected sealed source-derived CM ref for ValueError formal"
    # Identity sealed (not a gap from swallowed class_value failure).
    from sugar_lift_py_tests.context_manager_resolution import (
        ContextManagerResolutionGapV1,
        SourceDerivedContextManagerRefV1,
    )

    assert not isinstance(refs[0], ContextManagerResolutionGapV1)
    assert isinstance(refs[0], SourceDerivedContextManagerRefV1)
