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
    CELL PATH     platform, interpreter identity, anything situational
    EXCLUDED      checkout path, package spelling, monorepo HEAD, docs

RELATIVE PATHS ARE THE WHOLE POINT. Two byte-identical corpora at different
filesystem locations must resolve to the SAME key, or the fixture is a
per-checkout cache wearing a CID. That is the discriminating face, and it is
the one that proves the key was taken over the preimage rather than the
location.

RUNTIME IS NOT IN THE KEY, AND THAT IS MEASURED. The demand table is a pure
function of source bytes: `_context_manager_demand_rows` walks
`SourceTree(root).paths()` and reads source without constructing any Sugar,
`_call_contract_demand_rows` reads `authenticated_import_uses` over source
text, and neither they nor the join import, execute, or interrogate the
interpreter -- `importlib`, `__import__`, `exec(`, `eval(`, `sys.modules` and
`pkgutil` appear in none of them. `test_demand_table_identity.py` pins that as
a law, because the moment a producer starts observing the runtime this key is
wrong and must say so loudly rather than silently share a table across
incompatible interpreters.

It is also what makes the fixture worth building: the offload host runs Python
3.12 and the workstations run 3.14. Had runtime entered the key, the artifact
would have been unshareable across exactly the machines that need it.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass
from typing import Iterable, Mapping

from sugar_lift_python_source.canonical import blake3_512_of, cid_of_json

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
    file_count: int

    def preimage(self) -> Mapping[str, object]:
        return {
            "kind": "python-demand-table-identity",
            "schemaVersion": self.schema_version,
            "corpusManifestCid": self.corpus_manifest_cid,
            "producerSourceCid": self.producer_source_cid,
            "resolutionConfigCid": self.resolution_config_cid,
            "fileCount": self.file_count,
        }


def corpus_manifest_cid(
    root: pathlib.Path, paths: Iterable[pathlib.Path]
) -> tuple[str, int]:
    """Content-address a corpus by its RELATIVE paths and file bytes.

    Sorted by relative path so enumeration order cannot enter the address, and
    relative so the same corpus at a different location is the same corpus.
    """
    rows = []
    for path in sorted(paths, key=lambda item: item.relative_to(root).as_posix()):
        rows.append(
            {
                "path": path.relative_to(root).as_posix(),
                "contentCid": blake3_512_of(path.read_bytes()),
            }
        )
    return cid_of_json({"kind": "corpus-manifest", "files": rows}), len(rows)


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
        file_count=file_count,
    )
    return DemandTableIdentityV1(
        content_key=cid_of_json(dict(identity.preimage())),
        corpus_manifest_cid=identity.corpus_manifest_cid,
        schema_version=identity.schema_version,
        producer_source_cid=identity.producer_source_cid,
        resolution_config_cid=identity.resolution_config_cid,
        file_count=identity.file_count,
    )
