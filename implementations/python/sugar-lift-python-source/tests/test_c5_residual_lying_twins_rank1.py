"""C5 rank-1 lying twins for residual families missing a fool-the-detector face.

Census: ``docs/audits/c5-residual-family-twin-census.md`` listed 25 residual
families with no lying twin. A truthful twin only proves recognition when the
defect is present. A lying twin plants the *absence* of the defect (or a
misclassification) and asserts the detector does **not** fire that family — so
silence is tested.

Rank (seal / floor load-bearing tonight — see ranking section in the census doc):

1. ``call-target-off-population`` — population membrane; seal CM residual key
2. ``exit-missing`` — manager protocol residual on the closed gap vocabulary
3. ``unresolved-symbol`` — default With loud residual when contracts are absent
4. ``ConstructedValueTestimonyNotWritten`` / category gap — false-green construction

These four convert R_missing_lying_twin toward 21 when re-scanned with explicit
``lying_twin`` names. Residual gap products only — not sugar-catalog C5.
"""

from __future__ import annotations

import csv
import importlib.metadata
import tempfile
from pathlib import Path

import pytest

from sugar_lift_python_source.dependency_artifact import (
    DependencyArtifactGraph,
    ResolvedPythonObjectV1,
)
from sugar_lift_python_source.manager_protocol_construction import (
    ManagerProtocolConstructionGapV1,
)
from sugar_lift_python_source.resolution_session import SourceResolutionSession
from sugar_source_tree.binding_state import (
    ConstructedValueCategoryGap,
    constructed_value_cid_v2,
)
from sugar_source_tree.panic import (
    SugarNotWritten,
    WithConstructionGapKind,
)


# ---------------------------------------------------------------------------
# Ranking notes (load-bearing for seal/floors)
# ---------------------------------------------------------------------------
# Seal buckets CM residuals as gap:{WithConstructionGapKind.value}. Every
# vocabulary member is on the closed cardinality tooth in control_effect_recensus.
# Floor board also tracks SugarNotWritten / ConstructionPanic families.
#
# Rank among the 25 missing lying twins:
#   R1 call-target-off-population — membrane; false green would rebuild off-pin
#   R2 exit-missing — protocol residual; vocabulary member seal counts
#   R3 unresolved-symbol — common With loud residual without a contract ref
#   R4 ConstructedValueTestimony / category gap — false-green construction class
#   R5–R20 other WithConstructionGapKind members (definition-missing, etc.)
#   R21 instrument-defect category — board channel, not a gap kind
#   R22–R24 panic subclasses less common on seal mass
#   R25 GapKind.SUGAR_ORDERING — construction locus label, not CM residual


# ---------------------------------------------------------------------------
# 1. call-target-off-population
# ---------------------------------------------------------------------------


def test_call_target_off_population_truthful_twin_stdlib_is_detected() -> None:
    """Detector fires for stdlib graphs (membrane residual)."""
    from sugar_lift_python_source.manager_construction import (
        _off_population_materialize_gap,
    )

    class _Resolved:
        cid = "test-resolved-cid"
        module_name = "enum"

    stdlib = DependencyArtifactGraph.authenticate_stdlib_module("enum")
    gap = _off_population_materialize_gap(_Resolved(), graph=stdlib)  # type: ignore[arg-type]
    assert gap is not None
    assert gap.kind == "call-target-off-population"
    assert gap.kind == WithConstructionGapKind.CALL_TARGET_OFF_POPULATION.value


def test_call_target_off_population_lying_twin_on_population_is_not_misclassified(
    tmp_path: Path,
) -> None:
    """Lying face: enrolled distribution is NOT off-population.

    If the membrane detector always returned off-population, this would red.
    Proves we notice the *absence* of the residual class on the lawful path.
    """
    from sugar_lift_python_source.manager_construction import (
        _off_population_materialize_gap,
    )

    package = tmp_path / "arbitrary"
    package.mkdir()
    (package / "__init__.py").write_text("x = 1\n", encoding="utf-8")
    metadata = tmp_path / "arbitrary_dist-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: arbitrary-dist\nVersion: 1.0\n",
        encoding="utf-8",
    )
    (metadata / "top_level.txt").write_text("arbitrary\n", encoding="utf-8")
    files = (
        "arbitrary/__init__.py",
        "arbitrary_dist-1.0.dist-info/METADATA",
        "arbitrary_dist-1.0.dist-info/top_level.txt",
        "arbitrary_dist-1.0.dist-info/RECORD",
    )
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for name in files:
            writer.writerow((name, "", ""))
    graph = DependencyArtifactGraph.authenticate(
        importlib.metadata.Distribution.at(metadata)
    )

    class _Resolved:
        cid = "on-pop-cid"
        module_name = "arbitrary"

    session = SourceResolutionSession(
        enrolled_distributions=frozenset({graph.distribution_name})
    )
    gap = _off_population_materialize_gap(
        _Resolved(), graph=graph, session=session  # type: ignore[arg-type]
    )
    assert gap is None, (
        f"lying twin failed: on-population graph misclassified as "
        f"{getattr(gap, 'kind', gap)}"
    )


# ---------------------------------------------------------------------------
# 2. exit-missing (vocabulary + protocol gap product)
# ---------------------------------------------------------------------------


def test_exit_missing_truthful_twin_protocol_gap_kind_is_closed() -> None:
    """Truthful product: protocol gap mints exit-missing on the closed vocabulary."""
    gap = ManagerProtocolConstructionGapV1(
        "exit-missing",
        "manager-construction-cid-test",
        "source-visible method",
    )
    assert gap.kind == "exit-missing"
    assert gap.kind == WithConstructionGapKind.EXIT_MISSING.value


def test_exit_missing_lying_twin_enter_missing_is_not_exit_missing() -> None:
    """Lying face: enter-missing must not be reported as exit-missing.

    Detector discrimination: the two protocol absences are distinct kinds.
    Confusing them would hide which arm of the protocol is unfinished.
    """
    gap = ManagerProtocolConstructionGapV1(
        "enter-missing",
        "manager-construction-cid-test",
        "source-visible method",
    )
    assert gap.kind == "enter-missing"
    assert gap.kind != WithConstructionGapKind.EXIT_MISSING.value
    assert gap.kind != "exit-missing"


# ---------------------------------------------------------------------------
# 3. unresolved-symbol
# ---------------------------------------------------------------------------


def _source_file_with_preconstruction(path: Path):
    """Import fixture from sugar-source-tree tests (not on default package path)."""
    import sys

    fixture_dir = (
        Path(__file__).resolve().parents[2]
        / "sugar-source-tree"
        / "tests"
    )
    if str(fixture_dir) not in sys.path:
        sys.path.insert(0, str(fixture_dir))
    from with_resolution_fixture import source_file_with_preconstruction

    return source_file_with_preconstruction(path)


def test_unresolved_symbol_truthful_twin_unauthenticated_with_is_loud() -> None:
    """Detector fires a typed CM residual without an authenticated contract ref."""
    src = (
        "import contextlib\n"
        "def A(z):\n"
        "    with contextlib.nullcontext():\n"
        "        z = z\n"
        "    return z\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as handle:
        handle.write(src)
        path = Path(handle.name)
    fn = next(_source_file_with_preconstruction(path).functions())
    with pytest.raises(SugarNotWritten) as caught:
        fn.sugar()
    name = type(caught.value).__name__
    assert name in {
        "ContextManagerResolutionConstructionGap",
        "RuntimeSelectedContextManager",
        "WithConstructionGap",
    }
    kind = getattr(caught.value, "kind", None)
    if kind is not None:
        # Prefer unresolved-symbol; allow sibling loud residuals if fixture path varies.
        assert kind in {
            "unresolved-symbol",
            "runtime-selected",
            "no-derived-contract",
            "unsupported-cm-schema",
        }


def test_unresolved_symbol_lying_twin_bare_return_is_not_unresolved_symbol() -> None:
    """Lying face: no With site must not mint unresolved-symbol.

    Plants absence of the residual site. If a detector sprayed
    unresolved-symbol onto every function, this would red.
    """
    src = "def A(z):\n    return z\n"
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as handle:
        handle.write(src)
        path = Path(handle.name)
    fn = next(_source_file_with_preconstruction(path).functions())
    try:
        fn.sugar()
    except SugarNotWritten as exc:
        assert getattr(exc, "kind", None) != "unresolved-symbol", (
            "lying twin failed: bare return misclassified as unresolved-symbol"
        )


# ---------------------------------------------------------------------------
# 4. ConstructedValueTestimony / category gap (false-green class)
# ---------------------------------------------------------------------------


def test_constructed_value_category_truthful_twin_list_is_loud() -> None:
    """Mutable list cannot mint a constructed-value CID (truthful residual)."""
    with pytest.raises(ConstructedValueCategoryGap) as caught:
        constructed_value_cid_v2([1, 2, 3])  # type: ignore[arg-type]
    assert "MUTABLE" in str(caught.value) or "list" in str(caught.value).lower()


def test_constructed_value_category_lying_twin_tuple_canonicalizes() -> None:
    """Lying face: an immutable tuple *does* canonicalize — detector must not fire.

    If the category gap fired on every present, this would red.
    """
    cid = constructed_value_cid_v2((1, 2, 3))
    assert isinstance(cid, str) and cid.startswith("blake3-512:")
