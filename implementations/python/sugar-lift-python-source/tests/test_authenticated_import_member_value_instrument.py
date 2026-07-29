"""Honest-red instrument for a closed imported-module member value producer.

Only the missing typed producer door is red.  Active fixture preflights consume
existing authenticated lexical and dependency-artifact products.  Every axis
that requires the absent producer's typed closed result remains dormant and is
not counted as a semantic red.
"""

from __future__ import annotations

import csv
import importlib.metadata
import importlib.util
from pathlib import Path

import pytest

from sugar_lift_py_tests.import_binding import (
    AuthenticatedImportUseV1,
    authenticated_import_value_use_receipts,
)
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.dependency_artifact import DependencyArtifactGraph


PRODUCTION_MODULE = "sugar_lift_python_source.authenticated_import_member_value"


def _distribution(root: Path) -> importlib.metadata.Distribution:
    package = root / "provider_pkg"
    package.mkdir()
    (package / "__init__.py").write_text("member = 7\n", encoding="utf-8")
    metadata = root / "provider_pkg_dist-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: provider-pkg-dist\nVersion: 1.0\n",
        encoding="utf-8",
    )
    (metadata / "top_level.txt").write_text("provider_pkg\n", encoding="utf-8")
    recorded = (
        "provider_pkg/__init__.py",
        "provider_pkg_dist-1.0.dist-info/METADATA",
        "provider_pkg_dist-1.0.dist-info/top_level.txt",
        "provider_pkg_dist-1.0.dist-info/RECORD",
    )
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for seat in recorded:
            writer.writerow((seat, "", ""))
    return importlib.metadata.Distribution.at(metadata)


def _receipt(root: Path, *, scoped: bool = False) -> AuthenticatedImportUseV1:
    if scoped:
        source = (
            "def scope():\n"
            "    from provider_pkg import member\n"
            "    observed = member\n"
        )
    else:
        source = "from provider_pkg import member\nobserved = member\n"
    path = root / "consumer.py"
    path.write_text(source, encoding="utf-8")
    receipts, outcomes = authenticated_import_value_use_receipts(
        root,
        path,
        source,
        blake3_512_of(source.encode("utf-8")),
        module_identities={},
    )
    assert set(outcomes.values()) == {"authenticated-import-value-use"}
    # ImportFrom binds the member directly, so the lexical producer emits one
    # value-use receipt.  No caller coordinate or spelling selection exists.
    (receipt,) = receipts
    return receipt


def test_fixture_preflight_constructs_sole_occurrence_and_scope(tmp_path: Path) -> None:
    """Active fixture: exact occurrence/scope come from the lexical producer."""
    _distribution(tmp_path)
    receipt = _receipt(tmp_path)

    assert receipt.use["useSite"] == {
        "sourceCid": receipt.source_cid,
        "startLine": 2,
        "startCol": 11,
        "endLine": 2,
        "endCol": 17,
    }
    assert receipt.import_binding.to_value()["scope"] == {
        "sourceCid": receipt.source_cid,
        "startLine": 1,
        "startCol": 0,
        "endLine": 2,
        "endCol": 17,
    }


def test_fixture_preflight_constructs_independent_typed_dependency_graph(
    tmp_path: Path,
) -> None:
    """Active fixture: graph intake is typed; no receipt relationship is claimed."""
    graph = DependencyArtifactGraph.authenticate(_distribution(tmp_path))

    assert type(graph) is DependencyArtifactGraph
    assert graph.distribution_artifact_cid.startswith("blake3-512:")


def test_scoped_fixture_preflight_proves_real_indentation_and_scope(
    tmp_path: Path,
) -> None:
    """Active fixture: the scoped receipt is independently authenticated."""
    receipt = _receipt(tmp_path, scoped=True)

    assert receipt.use["useSite"] == {
        "sourceCid": receipt.source_cid,
        "startLine": 3,
        "startCol": 15,
        "endLine": 3,
        "endCol": 21,
    }
    scope = receipt.import_binding.to_value()["scope"]
    assert scope["sourceCid"] == receipt.source_cid
    assert (scope["startLine"], scope["startCol"]) == (1, 0)
    assert (scope["endLine"], scope["endCol"]) == (3, 21)


def test_missing_closed_producer_door_is_one_red() -> None:
    """R_missing_door=1: the typed producer module does not exist yet."""
    assert importlib.util.find_spec(PRODUCTION_MODULE) is not None, (
        "missing typed closed imported-module member producer door"
    )


_DORMANT_SEMANTIC_TEETH = (
    "TermValue(31400)-recomputed-hash-and-fully-matching-tuple-refuse",
    "dataclass-replace-refuses",
    "deserialize-refuses",
    "wrong-import-use-occurrence-refuses",
    "wrong-member-coordinate-refuses",
    "wrong-module-capability-refuses",
    "wrong-module-source-cid-refuses",
    "wrong-dependency-artifact-cid-refuses",
    "wrong-lexical-scope-identity-refuses",
    "wrong-value-sort-refuses",
    "cross-wired-construction-result-refuses",
    "missing-source-construction-testimony-refuses-before-consumer",
    "same-spelling-foreign-member-refuses-and-pure-resolver-preserves-identity",
)


@pytest.mark.skip(reason="dormant until one truthful typed closed result exists")
@pytest.mark.parametrize("tooth", _DORMANT_SEMANTIC_TEETH)
def test_semantic_constructor_refusal_tooth_is_dormant(tooth: str) -> None:
    """Thirteen semantic teeth are named but explicitly unmeasured."""
    raise AssertionError(f"semantic tooth must be activated: {tooth}")


@pytest.mark.skip(
    reason=(
        "dormant until a semantic cross-file provenance/dataflow auditor "
        "discovers and audits the full public alias/reexport/caller closure"
    )
)
def test_future_producer_side_door_closure_is_dormant() -> None:
    """Unmeasured future tooth; a spelling/leaf checklist is not evidence.

    The eventual live instrument must discover the repository closure and
    require discovered == audited for producer inputs, graph selection,
    traversal, occurrence sealing, introspection, fallback flow, and public
    aliases/reexports/wrappers.  Until that semantic instrument exists this
    tooth stays skipped rather than claiming a plausible green.
    """
    from sugar_lift_python_source.import_member_authority_audit import (
        audit_import_member_authority_closure,
    )

    report = audit_import_member_authority_closure(
        repository_root=Path(__file__).parents[4]
    )
    assert report.discovered == report.audited
    assert report.unaudited == ()
    assert report.caller_semantic_authority == ()
    assert report.alternate_construction_doors == ()
    assert report.unproven_graph_selections == ()
    assert report.ast_or_body_reconstructions == ()
    assert report.occurrence_reseals == ()
    assert report.runtime_introspection == ()
    assert report.fallback_flows == ()
    assert report.public_aliases_without_closed_provenance == ()
