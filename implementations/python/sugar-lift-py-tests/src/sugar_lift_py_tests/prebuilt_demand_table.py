"""Prebuilt provisional demand table: derive once per content, load in shards.

Law: ``provisional_contract_refs_from_demands`` walks every enrolled ``*.py``
(O(corpus)). Process memo (#7087) amortizes within one process; k=8 still
pays the walk eight times because each shard is a cold process and the cost
is invisible to LPT (per-process startup, not per-file).

Shape:
  - plan / first process DERIVES the table once and content-addresses it
  - every shard LOADS the artifact and installs it into the process memo
  - D2 ``sugar.enumerate level=functions`` then never re-derives

Corpus pin binding (blonde law): the artifact carries the corpus pin identity
it was built against. Load refuses a pin mismatch — a table for the wrong
pandas is not a table.

Walk counting is the unit-test instrument: a cold process given a prebuilt
table must perform ZERO corpus walks (count them; do not time them).
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping

from sugar_lift_python_source.canonical import (
    blake3_512_of,
    canonical_json_bytes,
    cid_of_json,
)
from sugar_lift_py_tests.authenticated_pytest import AuthenticatedPandasCorpus
from sugar_lift_py_tests.demand_table_identity import (
    DemandTableIdentityV1,
    demand_table_identity,
)
from sugar_lift_py_tests.repo_root import resolve_repo_root

SCHEMA = "python-provisional-demand-table/v1"


class DemandTablePinMismatch(ValueError):
    """Table was built for a different corpus pin than the one required."""


class DemandTableArtifactRefusal(ValueError):
    """Artifact is missing, malformed, or its contentCid does not recompute."""


class DemandTableSemanticIdentityMismatch(DemandTableArtifactRefusal):
    """Table meaning does not describe the authenticated current corpus."""


class PlanDemandTableRefusal(DemandTableArtifactRefusal):
    """A shard could not authenticate the exact table assigned by its plan."""

    def __init__(
        self,
        reason_name: str,
        detail: str,
        *,
        observed_table: "PrebuiltDemandTableV1 | None" = None,
    ) -> None:
        super().__init__(f"{reason_name}: {detail}")
        self.reason_name = reason_name
        self.observed_content_cid = (
            observed_table.content_cid if observed_table is not None else None
        )
        self.observed_semantic_identity = (
            observed_table.semantic_identity.as_dict()
            if observed_table is not None
            else None
        )


@dataclass(frozen=True)
class CorpusPinIdentityV1:
    """Minimal corpus pin fields the demand table authenticates against."""

    distribution: str
    version: str
    file_count: int
    aggregate_hash: str | None = None

    def as_dict(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "distribution": self.distribution,
            "version": self.version,
            "fileCount": self.file_count,
        }
        if self.aggregate_hash is not None:
            body["aggregateHash"] = self.aggregate_hash
        return body

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "CorpusPinIdentityV1":
        # Accept fileCount or file_count; aggregateHash optional.
        file_count = raw.get("fileCount", raw.get("file_count"))
        distribution = raw.get("distribution")
        version = raw.get("version")
        if distribution is None or version is None or file_count is None:
            raise DemandTableArtifactRefusal(
                f"corpus pin identity missing required fields "
                f"(need distribution, version, fileCount); got keys={sorted(raw)}"
            )
        agg = raw.get("aggregateHash", raw.get("aggregate_hash"))
        return cls(
            distribution=str(distribution),
            version=str(version),
            file_count=int(file_count),
            aggregate_hash=str(agg) if agg is not None else None,
        )

    def matches(self, other: "CorpusPinIdentityV1") -> bool:
        if (
            self.distribution != other.distribution
            or self.version != other.version
            or self.file_count != other.file_count
        ):
            return False
        # If either side carries aggregateHash, both must agree when both present.
        if (
            self.aggregate_hash is not None
            and other.aggregate_hash is not None
            and self.aggregate_hash != other.aggregate_hash
        ):
            return False
        return True


@dataclass(frozen=True)
class PrebuiltDemandTableV1:
    """Content-addressed provisional demand table for shard load."""

    content_cid: str
    corpus_pin: CorpusPinIdentityV1
    rows: tuple[dict[str, Any], ...]
    semantic_identity: DemandTableIdentityV1
    schema: str = SCHEMA

    def preimage(self) -> dict[str, Any]:
        """The value the artifact bytes encode. content_cid addresses it."""
        return {
            "schema": self.schema,
            "corpusPin": self.corpus_pin.as_dict(),
            "rows": list(self.rows),
            "semanticIdentity": self.semantic_identity.as_dict(),
        }

    def artifact_bytes(self) -> bytes:
        """THE bytes. Stored, hashed, and published are one spelling."""
        return serialize_prebuilt_demand_table(self.preimage())


def serialize_prebuilt_demand_table(preimage: Mapping[str, Any]) -> bytes:
    """The single artifact byte producer.

    A content address is h(content). There is exactly one serialization of a
    demand table: these bytes. Storage writes them, the content key hashes
    them, and CAS publication publishes them. A second spelling — a pretty
    dump, or a body carrying its own ``contentCid`` — makes the key address
    bytes that are not the bytes on disk, which is the publish-time CAS lie
    (``cas-publish-key-payload-mismatch``).
    """
    return canonical_json_bytes(dict(preimage))


def content_cid_for_preimage(preimage: Mapping[str, Any]) -> str:
    return blake3_512_of(serialize_prebuilt_demand_table(preimage))


def validate_prebuilt_demand_table(
    table: PrebuiltDemandTableV1,
    corpus: AuthenticatedPandasCorpus,
    *,
    source_root: Path | None = None,
    config: Mapping[str, object] | None = None,
) -> None:
    """Validate storage bytes and semantic meaning against current inputs.

    This is intentionally standalone: Slice 2 defines the shared door, while
    workers begin consuming it only in Slice 3.
    """
    payload_cid = content_cid_for_preimage(table.preimage())
    if payload_cid != table.content_cid:
        raise DemandTableArtifactRefusal(
            f"demand table payload contentCid mismatch: "
            f"presented={table.content_cid!r} recomputed={payload_cid!r}"
        )
    root = corpus.root
    expected_identity = demand_table_identity(
        root,
        sorted(root.rglob("*.py")),
        source_root=source_root or Path(__file__).resolve().parents[1],
        config=config,
    )
    if table.semantic_identity != expected_identity:
        raise DemandTableSemanticIdentityMismatch(
            "demand table semantic identity mismatch: "
            f"table={table.semantic_identity.as_dict()!r} "
            f"expected={expected_identity.as_dict()!r}; "
            "refuse table for a different corpus, producer, parser, or config"
        )


def mint_prebuilt_demand_table(
    corpus: AuthenticatedPandasCorpus,
) -> PrebuiltDemandTableV1:
    """Derive the provisional demand table once and content-address it.

    This is the only door that is allowed to walk the corpus for the table.
    """
    from sugar_lift_py_tests.lift_rpc import _preconstruction_demand_rows

    pin = CorpusPinIdentityV1(
        distribution=corpus.distribution,
        version=corpus.version,
        file_count=corpus.file_count,
        aggregate_hash=corpus.manifest_cid,
    )
    rows = tuple(_preconstruction_demand_rows(corpus.root))
    semantic_identity = demand_table_identity(
        corpus.root,
        sorted(corpus.root.rglob("*.py")),
        source_root=Path(__file__).resolve().parents[1],
    )
    table = PrebuiltDemandTableV1(
        content_cid="",
        corpus_pin=pin,
        rows=rows,
        semantic_identity=semantic_identity,
    )
    # Mint and validation must share one preimage door. A second authored
    # serialization silently diverges when fields are added to preimage().
    return replace(table, content_cid=content_cid_for_preimage(table.preimage()))


def write_prebuilt_demand_table(table: PrebuiltDemandTableV1, path: Path) -> Path:
    """Write the artifact bytes the content key addresses — and only those."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = table.artifact_bytes()
    written = blake3_512_of(payload)
    if written != table.content_cid:
        raise DemandTableArtifactRefusal(
            f"demand table storage key/payload mismatch: "
            f"claimed={table.content_cid!r} payload={written!r} "
            f"replacement=derive content_cid from serialize_prebuilt_demand_table "
            f"(a content address is h(content); one serialization, one place)"
        )
    path.write_bytes(payload)
    return path


def publish_prebuilt_demand_table(
    table: PrebuiltDemandTableV1,
    path: Path,
    *,
    runtime: str = "cpython-3.12.13",
) -> None:
    """Publish one already-written table through the authenticated CAS door."""
    repo_root = resolve_repo_root()
    completed = subprocess.run(
        [
            str(repo_root / "bin" / "sugarbin"),
            "artifact",
            "publish",
            "--kind",
            "python-demand-table",
            "--content-key",
            table.content_cid,
            "--input",
            str(path),
            "--runtime",
            runtime,
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout).strip()[:800]
        raise DemandTableArtifactRefusal(
            "python-demand-table CAS publication refused: "
            f"contentCid={table.content_cid} exit={completed.returncode} "
            f"detail={detail}"
        )


def load_prebuilt_demand_table(
    path: Path,
    *,
    expected_corpus_pin: Mapping[str, Any] | CorpusPinIdentityV1,
    expected_content_cid: str | None = None,
) -> PrebuiltDemandTableV1:
    """Load and authenticate a prebuilt table.

    The content CID is h(artifact bytes) — read, never presented. Refuses:
      - missing / malformed artifact
      - bytes that are not the one serialization (a re-dump is a different
        artifact, and its address is not the plan's address)
      - corpus pin mismatch (wrong pandas / fileCount / aggregate)
      - expected_content_cid mismatch when the plan pin requires a specific CID
    """
    path = Path(path)
    if not path.is_file():
        raise DemandTableArtifactRefusal(
            f"prebuilt demand table missing path={path} "
            f"replacement=mint at plan time and pass the path to every shard"
        )
    try:
        data = path.read_bytes()
        raw = json.loads(data.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DemandTableArtifactRefusal(
            f"prebuilt demand table unreadable path={path} detail={exc}"
        ) from exc
    if not isinstance(raw, dict):
        raise DemandTableArtifactRefusal("prebuilt demand table root must be an object")
    if raw.get("schema") != SCHEMA:
        raise DemandTableArtifactRefusal(
            f"prebuilt demand table schema mismatch got={raw.get('schema')!r} "
            f"want={SCHEMA!r}"
        )
    try:
        semantic_identity = DemandTableIdentityV1.from_mapping(
            raw.get("semanticIdentity") or {}
        )
    except (TypeError, ValueError) as exc:
        raise DemandTableArtifactRefusal(
            f"prebuilt demand table semantic identity invalid: {exc}"
        ) from exc
    if not isinstance(raw.get("rows"), list):
        raise DemandTableArtifactRefusal("prebuilt demand table carries no rows list")
    pin = CorpusPinIdentityV1.from_mapping(raw.get("corpusPin") or {})
    expected = (
        expected_corpus_pin
        if isinstance(expected_corpus_pin, CorpusPinIdentityV1)
        else CorpusPinIdentityV1.from_mapping(expected_corpus_pin)
    )
    if not pin.matches(expected):
        raise DemandTablePinMismatch(
            f"prebuilt demand table corpus pin mismatch: "
            f"table={pin.as_dict()!r} expected={expected.as_dict()!r} "
            f"replacement=rebuild the table against the authenticated pin "
            f"(blonde law: wrong corpus is not a measurement)"
        )
    if "contentCid" in raw:
        raise DemandTableArtifactRefusal(
            "prebuilt demand table body carries its own contentCid: "
            "the address is h(artifact bytes), so a self-describing key would "
            "address bytes that are not these bytes "
            "replacement=rebuild the table; the artifact is the preimage only"
        )
    # The address is h(bytes) — read from the file, never taken on the file's
    # word. Reconstruct through the one serialization door and require the
    # bytes on disk to BE that serialization.
    table = PrebuiltDemandTableV1(
        content_cid=blake3_512_of(data),
        corpus_pin=pin,
        rows=tuple(raw["rows"]),
        semantic_identity=semantic_identity,
    )
    if table.artifact_bytes() != data:
        raise DemandTableArtifactRefusal(
            f"prebuilt demand table bytes are not the canonical serialization: "
            f"path={path} storedCid={table.content_cid!r} "
            f"canonicalCid={content_cid_for_preimage(table.preimage())!r} "
            f"replacement=write through write_prebuilt_demand_table "
            f"(one serialization, one place)"
        )
    if expected_content_cid is not None and table.content_cid != expected_content_cid:
        raise DemandTableArtifactRefusal(
            f"prebuilt demand table contentCid != plan demandTableCid: "
            f"artifact={table.content_cid!r} plan={expected_content_cid!r}"
        )
    return table


def load_plan_bound_demand_table(
    path: Path,
    *,
    corpus: AuthenticatedPandasCorpus,
    expected_content_cid: str,
    expected_semantic_identity: Mapping[str, Any],
) -> PrebuiltDemandTableV1:
    """Load exactly the plan-assigned table; never derive a replacement.

    Storage identity and semantic meaning are independent agreement axes.  A
    missing artifact is absence testimony; a different CID or meaning is a
    mismatch.  Neither condition has a minting arm.
    """
    try:
        table = load_prebuilt_demand_table(
            path,
            expected_corpus_pin={
                "distribution": corpus.distribution,
                "version": corpus.version,
                "fileCount": corpus.file_count,
                "aggregateHash": corpus.manifest_cid,
            },
        )
    except DemandTableArtifactRefusal as error:
        reason = str(error)
        if "missing path=" in reason or "unreadable path=" in reason:
            name = "plan-demand-table-artifact-unavailable"
        else:
            name = "plan-demand-table-artifact-refusal"
        raise PlanDemandTableRefusal(name, reason) from error

    if table.content_cid != expected_content_cid:
        raise PlanDemandTableRefusal(
            "plan-demand-table-cid-mismatch",
            f"artifact={table.content_cid!r} plan={expected_content_cid!r}",
            observed_table=table,
        )

    try:
        expected_identity = DemandTableIdentityV1.from_mapping(
            expected_semantic_identity
        )
    except (TypeError, ValueError) as error:
        raise PlanDemandTableRefusal(
            "plan-demand-table-semantic-identity-malformed", str(error)
        ) from error
    expected_key = cid_of_json(dict(expected_identity.preimage()))
    if expected_identity.content_key != expected_key:
        raise PlanDemandTableRefusal(
            "plan-demand-table-semantic-identity-malformed",
            f"presented contentKey={expected_identity.content_key!r} "
            f"recomputed={expected_key!r}",
        )
    if table.semantic_identity != expected_identity:
        raise PlanDemandTableRefusal(
            "plan-demand-table-semantic-mismatch",
            f"artifact={table.semantic_identity.as_dict()!r} "
            f"plan={expected_identity.as_dict()!r}",
            observed_table=table,
        )
    try:
        validate_prebuilt_demand_table(table, corpus)
    except DemandTableSemanticIdentityMismatch as error:
        raise PlanDemandTableRefusal(
            "plan-demand-table-semantic-mismatch",
            str(error),
            observed_table=table,
        ) from error
    return table


def refs_from_prebuilt_table(table: PrebuiltDemandTableV1):
    """Project authenticated rows into construction refs (no corpus walk)."""
    from sugar_lift_py_tests.lift_rpc import provisional_contract_refs_from_demand_rows

    return provisional_contract_refs_from_demand_rows(
        list(table.rows),
        table_cid=table.content_cid,
        catalog_cid=table.content_cid,
    )


def install_prebuilt_demand_table(
    table: PrebuiltDemandTableV1,
    *,
    root: Path,
):
    """Install table into the process memo so D2 never re-derives.

    Zero corpus walks. Returns the installed ResolvedContractRefsV1.
    """
    from sugar_lift_py_tests.lift_rpc import install_provisional_contract_refs

    refs = refs_from_prebuilt_table(table)
    install_provisional_contract_refs(Path(root), refs)
    return refs
