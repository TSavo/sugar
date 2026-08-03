"""The content key for a shared demand table.

Building the With demand table costs >600s on the pinned corpus and timed out
at 240s on a single subpackage, and every owner driving a with-shape needs it
before they can answer a single question. Paying it per owner is the defect;
publishing one authenticated artifact is the fix.

THE KEY IS THE PREIMAGE, NOT THE LOCATION. Mirrors `bin/sugarbin`'s existing
`build_identity()` rule for the Rust binary -- *"Shelf / artifact identity is
ONLY the authenticated source matter... Platform / profile / binary name live
in the cell path, not in this content key -- so a docs-only commit cannot bust
the shelf."* Same discipline, second artifact kind:

    CONTENT KEY   corpus manifest CID   ordered (RELATIVE path, content CID)
                + demand-table schema version
                + producer source CID
                + resolution-affecting configuration
    CELL PATH     platform, exact interpreter patch, anything situational
    EXCLUDED      checkout path, package spelling, monorepo HEAD, docs

RELATIVE PATHS ARE THE WHOLE POINT. Two byte-identical corpora at different
filesystem locations must resolve to the SAME key, or the fixture is a
per-checkout cache wearing a CID. That is the discriminating face, and it is
the one that proves the key was taken over the preimage rather than the
location.

PARSER IDENTITY IS IN THE CONTENT KEY.

An earlier version of this module excluded runtime identity, on two
independently-traced verdicts that demand production never CALLS anything
observing the interpreter. Both verdicts were correct and both answered the
wrong question. The right question is whether production's OUTPUT can differ
across interpreters, and it can with no such call at all, because the parse
itself is version-dependent. `CPythonAstBackend.fingerprint`, in this same
tree, says so:

    "CPython's `ast` produces a version-dependent node stream (e.g. the empty
     Constant("") it staples into a nested f-string format spec on 3.12 but
     not 3.14), so the interpreter IS this backend's version-of-record."

`fingerprint()` exists precisely because this codebase already pins goldens
per interpreter for that reason, and it names 3.12 and 3.14 -- which is the
offload host versus the workstations exactly.

The managed runtime authority is CPython 3.12.13. A workstation measurement
under 3.14.4 cannot relax this identity: it is testimony from an undeclared
runtime, not a second supported cell. The parser's major/minor fingerprint
therefore remains in the content preimage, while the exact patch identity is
authenticated at execution and artifact boundaries.
"""

from __future__ import annotations

import hashlib
import pathlib
from dataclasses import dataclass
from typing import Iterable, Mapping

from sugar_lift_python_source.canonical import (
    blake3_512_of,
    canonical_json_bytes,
    cid_of_json,
)

# Bump when the demand table's SHAPE changes -- a new row kind, a changed
# field, a different join. A consumer holding an artifact built under an older
# schema must MISS rather than decode a table it does not understand.
DEMAND_TABLE_SCHEMA_VERSION = "python-demand-table/v1"

# The producer modules whose source decides what the table contains. A change
# to any of them changes the table, so their bytes are part of the key -- the
# same reason `build_identity` stamps the dependency closure rather than a
# version string.
_PRODUCER_MODULES = (
    "sugar_lift_py_tests/lift_rpc.py",
    "sugar_lift_py_tests/context_manager_resolution.py",
    "sugar_lift_py_tests/import_binding.py",
)


@dataclass(frozen=True)
class DemandTableIdentityV1:
    """A demand table's content key and the complete preimage that made it.

    The preimage travels with the key so any machine can recompute the CID
    without this process. An identity whose preimage cannot be re-derived is
    an assertion, not an address.
    """

    content_key: str
    corpus_manifest_cid: str
    schema_version: str
    producer_source_cid: str
    resolution_config_cid: str
    parser_identity: str
    file_count: int

    def preimage(self) -> Mapping[str, object]:
        return {
            "kind": "python-demand-table-identity",
            "schemaVersion": self.schema_version,
            "corpusManifestCid": self.corpus_manifest_cid,
            "producerSourceCid": self.producer_source_cid,
            "resolutionConfigCid": self.resolution_config_cid,
            "parserIdentity": self.parser_identity,
            "fileCount": self.file_count,
        }

    def as_dict(self) -> dict[str, object]:
        body = dict(self.preimage())
        body["contentKey"] = self.content_key
        return body

    @classmethod
    def from_mapping(cls, raw: Mapping[str, object]) -> "DemandTableIdentityV1":
        required = ("contentKey", "corpusManifestCid", "schemaVersion",
                    "producerSourceCid", "resolutionConfigCid",
                    "parserIdentity", "fileCount")
        missing = [key for key in required if key not in raw]
        if missing:
            raise ValueError(f"demand table semantic identity missing fields: {missing}")
        return cls(
            content_key=str(raw["contentKey"]),
            corpus_manifest_cid=str(raw["corpusManifestCid"]),
            schema_version=str(raw["schemaVersion"]),
            producer_source_cid=str(raw["producerSourceCid"]),
            resolution_config_cid=str(raw["resolutionConfigCid"]),
            parser_identity=str(raw["parserIdentity"]),
            file_count=int(raw["fileCount"]),
        )


@dataclass(frozen=True)
class CorpusManifestDigestAliasesV1:
    """Digest aliases over one canonical path-plus-content manifest."""

    sha256: str
    blake3_512: str
    file_count: int

    def accepts(self, digest: str) -> bool:
        return digest in (self.sha256, self.blake3_512)


class CorpusManifestIdentityMismatch(ValueError):
    """A presented digest is not an alias of the canonical corpus manifest."""


def corpus_manifest_digest_aliases(
    root: pathlib.Path, paths: Iterable[pathlib.Path]
) -> CorpusManifestDigestAliasesV1:
    """Hash one ordered relative-path/content-CID manifest two ways.

    Algorithm choice does not create a second corpus identity. Both aliases
    cover the exact same canonical bytes; ordering, path membership, file
    count, or file bytes therefore move both together.
    """
    rows = []
    for path in sorted(paths, key=lambda item: item.relative_to(root).as_posix()):
        rows.append(
            {
                "path": path.relative_to(root).as_posix(),
                "contentCid": blake3_512_of(path.read_bytes()),
            }
        )
    manifest = canonical_json_bytes({"kind": "corpus-manifest", "files": rows})
    return CorpusManifestDigestAliasesV1(
        sha256="sha256:" + hashlib.sha256(manifest).hexdigest(),
        blake3_512=blake3_512_of(manifest),
        file_count=len(rows),
    )


def require_corpus_manifest_alias(
    aliases: CorpusManifestDigestAliasesV1, presented: str
) -> None:
    """Refuse artifact consumption under a digest from another preimage."""
    if aliases.accepts(presented):
        return
    raise CorpusManifestIdentityMismatch(
        f"{presented} is not an alias of canonical corpus manifest "
        f"({aliases.sha256}, {aliases.blake3_512}); stop artifact consumption"
    )


def corpus_manifest_cid(
    root: pathlib.Path, paths: Iterable[pathlib.Path]
) -> tuple[str, int]:
    """Content-address a corpus by its RELATIVE paths and file bytes.

    Sorted by relative path so enumeration order cannot enter the address, and
    relative so the same corpus at a different location is the same corpus.
    """
    aliases = corpus_manifest_digest_aliases(root, paths)
    return aliases.blake3_512, aliases.file_count


def producer_source_cid(source_root: pathlib.Path) -> str:
    """Content-address the code that produces the table.

    Absent modules are recorded as absent rather than skipped: a producer that
    disappears changes the table and must change the key.
    """
    rows = []
    for relative in _PRODUCER_MODULES:
        module = source_root / relative
        rows.append(
            {
                "module": relative,
                "contentCid": (
                    blake3_512_of(module.read_bytes()) if module.is_file() else None
                ),
            }
        )
    return cid_of_json({"kind": "demand-table-producer", "modules": rows})


def resolution_config_cid(config: Mapping[str, object] | None = None) -> str:
    """Content-address configuration that changes what the table resolves.

    Empty is a legitimate configuration and is addressed as such -- not as a
    missing input, which would let two different configurations share a key.
    """
    return cid_of_json(
        {"kind": "demand-table-resolution-config", "config": dict(config or {})}
    )


def parser_identity() -> str:
    """The interpreter, as the parser's version-of-record.

    Same shape `CPythonAstBackend.fingerprint` already uses to pin goldens --
    implementation plus major.minor -- because that is the granularity at
    which the node stream is documented to change. Patch level is excluded
    deliberately: the documented differences are minor-version differences,
    and keying on patch would force a rebuild for changes that provably
    cannot move the table.
    """
    import sys

    version = sys.version_info
    return f"{sys.implementation.name}-{version.major}.{version.minor}"


def demand_table_identity(
    root: pathlib.Path,
    paths: Iterable[pathlib.Path],
    *,
    source_root: pathlib.Path,
    config: Mapping[str, object] | None = None,
) -> DemandTableIdentityV1:
    """The content key for the table this corpus and producer would build."""
    manifest_cid, file_count = corpus_manifest_cid(root, paths)
    identity = DemandTableIdentityV1(
        content_key="",
        corpus_manifest_cid=manifest_cid,
        schema_version=DEMAND_TABLE_SCHEMA_VERSION,
        producer_source_cid=producer_source_cid(source_root),
        resolution_config_cid=resolution_config_cid(config),
        parser_identity=parser_identity(),
        file_count=file_count,
    )
    return DemandTableIdentityV1(
        content_key=cid_of_json(dict(identity.preimage())),
        corpus_manifest_cid=identity.corpus_manifest_cid,
        schema_version=identity.schema_version,
        producer_source_cid=identity.producer_source_cid,
        resolution_config_cid=identity.resolution_config_cid,
        parser_identity=identity.parser_identity,
        file_count=identity.file_count,
    )
