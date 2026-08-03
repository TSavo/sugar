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
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from sugar_lift_python_source.canonical import cid_of_json
from sugar_lift_py_tests.authenticated_pytest import AuthenticatedPandasCorpus
from sugar_lift_py_tests.demand_table_identity import DemandTableIdentityV1, demand_table_identity

SCHEMA = "python-provisional-demand-table/v1"


class DemandTablePinMismatch(ValueError):
    """Table was built for a different corpus pin than the one required."""


class DemandTableArtifactRefusal(ValueError):
    """Artifact is missing, malformed, or its contentCid does not recompute."""


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
        """Bytes that content_cid addresses (no contentCid field)."""
        return {
            "schema": self.schema,
            "corpusPin": self.corpus_pin.as_dict(),
            "rows": list(self.rows),
        }

    def to_json_dict(self) -> dict[str, Any]:
        body = self.preimage()
        body["contentCid"] = self.content_cid
        body["semanticIdentity"] = self.semantic_identity.as_dict()
        return body


def content_cid_for_preimage(preimage: Mapping[str, Any]) -> str:
    return cid_of_json(dict(preimage))


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
    preimage = {
        "schema": SCHEMA,
        "corpusPin": pin.as_dict(),
        "rows": list(rows),
    }
    return PrebuiltDemandTableV1(
        content_cid=content_cid_for_preimage(preimage),
        corpus_pin=pin,
        rows=rows,
        semantic_identity=semantic_identity,
    )


def write_prebuilt_demand_table(table: PrebuiltDemandTableV1, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(table.to_json_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def load_prebuilt_demand_table(
    path: Path,
    *,
    expected_corpus_pin: Mapping[str, Any] | CorpusPinIdentityV1,
    expected_content_cid: str | None = None,
) -> PrebuiltDemandTableV1:
    """Load and authenticate a prebuilt table.

    Refuses:
      - missing / malformed artifact
      - contentCid that does not recompute from preimage
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
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
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
        semantic_identity = DemandTableIdentityV1.from_mapping(raw.get("semanticIdentity") or {})
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
    preimage = {
        "schema": SCHEMA,
        "corpusPin": pin.as_dict(),
        "rows": list(raw["rows"]),
    }
    recomputed = content_cid_for_preimage(preimage)
    presented = raw.get("contentCid")
    if presented != recomputed:
        raise DemandTableArtifactRefusal(
            f"prebuilt demand table contentCid mismatch: "
            f"presented={presented!r} recomputed={recomputed!r}"
        )
    if expected_content_cid is not None and presented != expected_content_cid:
        raise DemandTableArtifactRefusal(
            f"prebuilt demand table contentCid != plan demandTableCid: "
            f"artifact={presented!r} plan={expected_content_cid!r}"
        )
    return PrebuiltDemandTableV1(
        content_cid=str(presented),
        corpus_pin=pin,
        rows=tuple(raw["rows"]),
        semantic_identity=semantic_identity,
    )


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
