"""Compose authenticated binary, demand-table, and launcher testimony.

This module owns no artifact identity.  It compares the coordinates already
owned by the three producers and emits a hit only when their testimony agrees
with one request.  In particular, runtime remains absent from the Rust binary
cell: Python runtime authority is testified by the demand cell and launcher.
"""

from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.demand_table_identity import DemandTableIdentityV1


class ConsumerResolutionMiss(RuntimeError):
    """A composite lookup failed at one named coordinate."""

    def __init__(self, coordinate: str, detail: str):
        self.coordinate = coordinate
        self.detail = detail
        super().__init__(f"consumer resolution MISS: {coordinate} differs: {detail}")


@dataclass(frozen=True)
class ConsumerResolutionRequest:
    source_stamp: str
    runtime: str
    platform: str
    profile: str
    corpus_manifest_cid: str
    corpus_files: int


@dataclass(frozen=True)
class BinaryCellTestimony:
    source_stamp: str
    platform: str
    profile: str
    binary_name: str
    artifact_verified: bool


@dataclass(frozen=True)
class DemandTableCellTestimony:
    identity: DemandTableIdentityV1
    runtime: str
    platform: str
    profile: str
    artifact_verified: bool


@dataclass(frozen=True)
class LauncherSelectionTestimony:
    runtime: str
    corpus_manifest_cid: str
    corpus_files: int
    selected_binary_source_stamp: str
    selected_binary_platform: str
    selected_binary_profile: str
    selected_demand_content_key: str
    selected_demand_runtime: str
    selected_demand_platform: str
    selected_demand_profile: str
    artifact_verification_succeeded: bool


@dataclass(frozen=True)
class ConsumerHitReport:
    source_stamp: str
    runtime: str
    corpus_files: int
    corpus_manifest_cid: str

    def lines(self) -> tuple[str, ...]:
        return (
            f"sourceStamp {self.source_stamp}",
            f"runtime {self.runtime}",
            f"corpusFiles {self.corpus_files}",
            f"corpusManifest {self.corpus_manifest_cid}",
            "artifactVerification success",
        )

    def render(self) -> str:
        return "\n".join(self.lines())


def _miss(coordinate: str, requested: object, observed: object) -> None:
    raise ConsumerResolutionMiss(
        coordinate, f"requested={requested!r} observed={observed!r}"
    )


def _runtime_parser_identity(runtime: str) -> str:
    implementation, separator, version = runtime.rpartition("-")
    components = version.split(".")
    if not separator or len(components) < 2:
        _miss("runtime", "<implementation-major.minor.patch>", runtime)
    return f"{implementation}-{components[0]}.{components[1]}"


def resolve_consumer_hit(
    request: ConsumerResolutionRequest,
    binary: BinaryCellTestimony,
    demand: DemandTableCellTestimony,
    launcher: LauncherSelectionTestimony,
) -> ConsumerHitReport:
    """Resolve one composite hit or refuse at its first differing coordinate."""
    source_stamps = (
        binary.source_stamp,
        launcher.selected_binary_source_stamp,
    )
    if any(stamp != request.source_stamp for stamp in source_stamps):
        _miss("source stamp", request.source_stamp, source_stamps)

    runtimes = (demand.runtime, launcher.runtime, launcher.selected_demand_runtime)
    parser_identities = (
        demand.identity.parser_identity,
        _runtime_parser_identity(request.runtime),
    )
    if any(runtime != request.runtime for runtime in runtimes) or len(
        set(parser_identities)
    ) != 1:
        _miss("runtime", request.runtime, (runtimes, parser_identities))

    cell_coordinates = (
        (binary.platform, binary.profile),
        (demand.platform, demand.profile),
        (launcher.selected_binary_platform, launcher.selected_binary_profile),
        (launcher.selected_demand_platform, launcher.selected_demand_profile),
    )
    requested_cell = (request.platform, request.profile)
    if any(coordinate != requested_cell for coordinate in cell_coordinates):
        _miss("profile/platform", requested_cell, cell_coordinates)

    corpus_coordinates = (
        (demand.identity.corpus_manifest_cid, demand.identity.file_count),
        (launcher.corpus_manifest_cid, launcher.corpus_files),
    )
    requested_corpus = (request.corpus_manifest_cid, request.corpus_files)
    if any(coordinate != requested_corpus for coordinate in corpus_coordinates):
        _miss("corpus identity", requested_corpus, corpus_coordinates)

    if launcher.selected_demand_content_key != demand.identity.content_key:
        _miss(
            "artifact verification",
            demand.identity.content_key,
            launcher.selected_demand_content_key,
        )
    verification = (
        binary.artifact_verified,
        demand.artifact_verified,
        launcher.artifact_verification_succeeded,
    )
    if not all(verification):
        _miss("artifact verification", True, verification)

    return ConsumerHitReport(
        source_stamp=request.source_stamp,
        runtime=request.runtime,
        corpus_files=request.corpus_files,
        corpus_manifest_cid=request.corpus_manifest_cid,
    )


def print_consumer_hit(
    request: ConsumerResolutionRequest,
    binary: BinaryCellTestimony,
    demand: DemandTableCellTestimony,
    launcher: LauncherSelectionTestimony,
) -> ConsumerHitReport:
    """Resolve and print the composed testimony at the consumer edge."""
    report = resolve_consumer_hit(request, binary, demand, launcher)
    print(report.render(), flush=True)
    return report
