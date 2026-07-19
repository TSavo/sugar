"""Prove ``resolution_kind`` carries the recognizer's own discarded testimony.

#5252/#5913 audit: ``recognize_callee_universe`` already computes local-
binding, imported-identity, and receiver-shape testimony on every call before
deciding pass/fail, then threw the testimony away once the boolean answer was
made. ``classify_callee_resolution`` keeps that same testimony as a coarse
partition; ``FactoryGapInfo``/``universe_coverage_gaps``/the unclassified
locus schema thread it through instead of discarding it again.

Fixtures are the four confirmed classes from the audit:

- ``pd.DataFrame.lookup`` — removed vendor API: resolves to an imported
  definition, no recognizer family covers it -> ``imported_unresolved``.
- a locally-bound test lambda -> ``local_binding``.
- ``hash(x)`` — a Python builtin, not a vendor method -> ``builtin``.
- ``a.b.c.method()`` — receiver is a chained attribute expression, not a
  bindable name -> ``chained_receiver``.

Each test also proves recognize_callee_universe itself returns None for the
fixture (i.e. it is genuinely an unclassified-locus candidate, not something
already recognized under a different name).
"""

from __future__ import annotations

import ast

import pytest

from sugar_lift_py_tests.canonicalizer import blake3_512_of
from sugar_lift_py_tests.factory.factory_gap_info import FactoryGapInfo, GapKind, GapLocus
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.idd.factory_walk_unclassified_locus import (
    locus_is_addressable,
    project_unclassified_locus,
)
from sugar_lift_py_tests.kit_rpc.factory_walk_row_dto import (
    FactoryWalkRedRowDto,
    FactoryWalkStatus,
)
from sugar_lift_py_tests.kit_rpc.source_memento_dto import SourceMementoDto
from sugar_lift_py_tests.kit_rpc.source_span_dto import SourceSpanDto
from sugar_lift_py_tests.recognition.callee_universe import (
    CalleeResolutionKind,
    classify_callee_resolution,
    recognize_callee_universe,
)


def _call_site(source: str, *, attr: str | None = None, name: str | None = None):
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        if attr and isinstance(node.func, ast.Attribute) and node.func.attr == attr:
            return SourceFragment.from_node(node, "t.py", source=source)
        if name and isinstance(node.func, ast.Name) and node.func.id == name:
            return SourceFragment.from_node(node, "t.py", source=source)
    raise AssertionError("no matching Call site in fixture source")


IMPORTED_UNRESOLVED_SOURCE = (
    "import pandas as pd\n"
    "\n"
    "def test_lookup(rows, cols):\n"
    "    df = pd.DataFrame({'a': [1, 2]})\n"
    "    assert df.lookup(rows, cols) is not None\n"
)

LOCAL_BINDING_SOURCE = (
    # Module-level test-file helper lambda (the #5923 corpus shape): assigned
    # outside any enclosing function, so it is source-bound but not
    # *function*-local — recognize_callee_universe's BOUND_SOURCE_CALLABLE
    # path requires the Lambda assign to be function-local and stays loud,
    # yet the call is still, structurally, a local (non-vendor) binding.
    "drepr = lambda x: x._repr_base()\n"
    "\n"
    "def test_drepr(value):\n"
    "    assert drepr(value) == value\n"
)

BUILTIN_SOURCE = "def test_hash(value):\n    assert hash(value) != 0\n"

CHAINED_RECEIVER_SOURCE = (
    "def test_chained(a):\n    assert a.b.c.method() is not None\n"
)


@pytest.mark.parametrize(
    ("source", "callee_leaf", "expected"),
    [
        (
            IMPORTED_UNRESOLVED_SOURCE,
            "lookup",
            CalleeResolutionKind.IMPORTED_UNRESOLVED,
        ),
        (LOCAL_BINDING_SOURCE, "drepr", CalleeResolutionKind.LOCAL_BINDING),
        (BUILTIN_SOURCE, "hash", CalleeResolutionKind.BUILTIN),
        (
            CHAINED_RECEIVER_SOURCE,
            "method",
            CalleeResolutionKind.CHAINED_RECEIVER,
        ),
    ],
)
def test_classify_callee_resolution_per_class(source, callee_leaf, expected) -> None:
    site = _call_site(source, attr=callee_leaf, name=callee_leaf)
    target = f"call:{callee_leaf}"

    # Genuinely unclassified: the existing recognizer does not accept it.
    assert recognize_callee_universe(target, site=site) is None

    assert classify_callee_resolution(target, site=site) is expected


def test_recognized_call_never_reclassified_as_unresolved() -> None:
    """A call the recognizer already accepts must classify as RECOGNIZED.

    ``re.compile('x').search(value)`` is a known-recognized surface method
    (regex search) — proves classify_callee_resolution never mislabels an
    accepted call as one of the unresolved classes.
    """
    source = (
        "import re\n"
        "\n"
        "def test_search(value):\n"
        "    pattern = re.compile('x')\n"
        "    assert pattern.search(value) is not None\n"
    )
    site = _call_site(source, attr="search")
    target = "call:search"

    assert recognize_callee_universe(target, site=site) is not None
    assert (
        classify_callee_resolution(target, site=site)
        is CalleeResolutionKind.RECOGNIZED
    )


def test_factory_gap_info_carries_resolution_kind_in_to_json() -> None:
    info = FactoryGapInfo(
        owner="python.factory",
        blame="t.py:2:0",
        observed="call:lookup",
        requested="callee universe coverage",
        fix="add builtin-universe recognizer",
        gap_kind=GapKind.SUGAR,
        gap_locus=GapLocus.CONSTRUCTION,
        resolution_kind=CalleeResolutionKind.IMPORTED_UNRESOLVED.value,
    )
    assert info.to_json()["resolution_kind"] == "imported_unresolved"


def test_factory_gap_info_defaults_resolution_kind_empty() -> None:
    """Producers that never computed a callee resolution stay honestly empty."""
    info = FactoryGapInfo(
        owner="python.factory",
        blame="t.py:2:0",
        observed="Assign",
        requested="source→factory classification",
        fix="remove the pre-factory skip or classify an explicit boundary",
        gap_kind=GapKind.SUGAR,
        gap_locus=GapLocus.CONSTRUCTION,
    )
    assert info.to_json()["resolution_kind"] == ""


def _red_row(*, ast_kind: str, resolution_kind: str) -> FactoryWalkRedRowDto:
    memento = SourceMementoDto(
        file="t.py",
        span=SourceSpanDto(start_line=2, start_col=0, end_line=2, end_col=0),
        source_cid=blake3_512_of(b""),
    )
    return FactoryWalkRedRowDto(
        file="t.py",
        line=2,
        requested_role="callee universe coverage",
        ast_kind=ast_kind,
        selected=None,
        status=FactoryWalkStatus.UNCLASSIFIED,
        output="SUGAR_GAP",
        source_memento=memento,
        reason="no universe sugar for this callee",
        extra={"resolution_kind": resolution_kind},
    )


def test_unclassified_locus_projects_resolution_kind_from_extra() -> None:
    row = _red_row(ast_kind="call:lookup", resolution_kind="imported_unresolved")
    locus = project_unclassified_locus(row)
    assert locus is not None
    assert locus["resolution_kind"] == "imported_unresolved"
    # Addressability is unaffected by the new field — never gates on it.
    assert locus_is_addressable(locus)


def test_unclassified_locus_resolution_kind_empty_when_absent() -> None:
    row = _red_row(ast_kind="call:whatever", resolution_kind="")
    row = FactoryWalkRedRowDto(
        file=row.file,
        line=row.line,
        requested_role=row.requested_role,
        ast_kind=row.ast_kind,
        selected=row.selected,
        status=row.status,
        output=row.output,
        source_memento=row.source_memento,
        reason=row.reason,
        extra={},
    )
    locus = project_unclassified_locus(row)
    assert locus is not None
    assert locus["resolution_kind"] == ""
    assert locus_is_addressable(locus)
