"""Compose authenticated binary, demand-table, and launcher testimony.

This module owns no artifact identity.  It compares the coordinates already
owned by the three producers and emits a hit only when their testimony agrees
with one request.  In particular, runtime remains absent from the Rust binary
cell: Python runtime authority is testified by the demand cell and launcher.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sugar_lift_py_tests.demand_table_identity import DemandTableIdentityV1
from sugar_lift_py_tests.no_call_body_attribution import AttributionOutcome


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
class CallerAttribution:
    """Caller-owned surviving gap testimony using #6511's closed outcomes."""

    outcome: AttributionOutcome
    detail: str

    def __post_init__(self) -> None:
        if self.outcome not in (
            AttributionOutcome.NAMED_REFUSAL,
            AttributionOutcome.CONSTRUCTION_PANIC,
        ):
            raise ValueError(
                "surviving testimony must be a named refusal or construction panic"
            )
        if not self.detail:
            raise ValueError("surviving testimony requires caller detail")


@dataclass(frozen=True)
class CallerReportTestimony:
    """Reported observations; never promoted to artifact verification."""

    concrete_source_site: str
    before_outcome: str
    after_outcome: str
    surviving: tuple[CallerAttribution, ...]

    def __post_init__(self) -> None:
        fields = (
            self.concrete_source_site,
            self.before_outcome,
            self.after_outcome,
        )
        if any(not value for value in fields):
            raise ValueError("caller testimony cannot contain an absent observation")


@dataclass(frozen=True)
class ConsumerHitReport:
    source_stamp: str
    runtime: str
    corpus_manifest_cid: str
    demand_table_content_key: str
    caller: CallerReportTestimony

    def lines(self) -> tuple[str, ...]:
        surviving = ",".join(
            f"{item.outcome.value}:{item.detail}" for item in self.caller.surviving
        )
        return (
            f"sourceStamp {self.source_stamp}",
            f"runtime {self.runtime}",
            f"corpusManifest {self.corpus_manifest_cid}",
            f"demandTableIdentity {self.demand_table_content_key}",
            f"concreteSourceSite reported {self.caller.concrete_source_site}",
            f"beforeOutcome reported {self.caller.before_outcome}",
            f"afterOutcome reported {self.caller.after_outcome}",
            "survivingTypedGapsOrReattributions reported "
            f"[{surviving}]",
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


def _is_primary_corpus_coordinate(value: str) -> bool:
    """The demand identity owns one primary CID; SHA-256 is only an alias.

    ``demand_table_identity.corpus_manifest_cid`` returns the BLAKE3-512
    coordinate.  Artifact transport may authenticate the SHA-256 alias over
    the same canonical bytes, but that alias does not replace the primary
    coordinate consumed by the demand table and launcher.
    """
    return re.fullmatch(r"blake3-512:[0-9a-f]{128}", value) is not None


def resolve_consumer_hit(
    request: ConsumerResolutionRequest,
    binary: BinaryCellTestimony,
    demand: DemandTableCellTestimony,
    launcher: LauncherSelectionTestimony,
    caller: CallerReportTestimony,
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
    if not _is_primary_corpus_coordinate(request.corpus_manifest_cid) or any(
        coordinate != requested_corpus for coordinate in corpus_coordinates
    ):
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
        corpus_manifest_cid=request.corpus_manifest_cid,
        demand_table_content_key=demand.identity.content_key,
        caller=caller,
    )


def print_consumer_hit(
    request: ConsumerResolutionRequest,
    binary: BinaryCellTestimony,
    demand: DemandTableCellTestimony,
    launcher: LauncherSelectionTestimony,
    caller: CallerReportTestimony,
) -> ConsumerHitReport:
    """Resolve and print the composed testimony at the consumer edge."""
    report = resolve_consumer_hit(request, binary, demand, launcher, caller)
    print(report.render(), flush=True)
    return report
