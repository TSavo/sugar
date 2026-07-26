"""The corpus pin: a scoreboard number means nothing without a named corpus.

Two measurements are comparable only when they ran over *the same files*. The
pandas board learned this the hard way: a 1,415-file ledger and a 1,421-file
ledger were quoted against each other for weeks as if the delta were signal. It
was a different pandas.

So the authoritative recensus pins its corpus and records the pin in its
result:

* the **distribution and version** (``pandas 3.0.3``), read from the
  installed ``*.dist-info`` beside the package root — never guessed;
* the **file manifest** — every enrolled file with its content hash and size;
* the **aggregate hash** — one sha256 over the whole manifest, so two runs can
  be declared comparable (or not) by comparing a single string.

The manifest is enumerated with ``SourceTree(root).paths()`` — the *same*
enumerator the census uses. A pin built from a different walk (``rglob``, a
filter, an installer's RECORD file) would pin a denominator the run never had,
which is the failure this module exists to make impossible.

Paths in the pin are relative to the corpus root, so the same corpus pins
identically on the Mac and on the measurement box. The absolute root is carried
for testimony only and is deliberately NOT part of the aggregate hash.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

PIN_KIND = "sugar-corpus-pin/v1"


class CorpusPinDefect(Exception):
    """The pin could not be established — instrument/environment defect.

    Never a measurement result. A run that cannot pin its corpus has no
    denominator, and a number without a denominator is not a scoreboard entry.
    """

    def __init__(self, *, owner: str, observed: str, requested: str, fix: str) -> None:
        super().__init__(
            f"CORPUS PIN DEFECT [{owner}]\n"
            f"  observed:  {observed}\n"
            f"  requested: {requested}\n"
            f"  fix:       {fix}"
        )
        self.owner = owner
        self.observed = observed
        self.requested = requested
        self.fix = fix


@dataclass(frozen=True)
class CorpusFile:
    """One enrolled file: identity is (path, content), never path alone."""

    path: str
    sha256: str
    size_bytes: int

    def row(self) -> dict[str, Any]:
        return {"path": self.path, "sha256": self.sha256, "sizeBytes": self.size_bytes}


@dataclass(frozen=True)
class CorpusPin:
    """A named, content-addressed corpus. Comparable iff aggregate hashes match."""

    distribution: str
    version: str
    file_count: int
    aggregate_hash: str
    files: tuple[CorpusFile, ...]
    # The two circulating conventions, computed from the same bytes at pin
    # time. Empty only for pins decoded from an older file that lacked them.
    content_only_hash: str = ""
    path_bound_hash: str = ""
    root: str = ""

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": PIN_KIND,
            "distribution": self.distribution,
            "version": self.version,
            "fileCount": self.file_count,
            "aggregateHash": self.aggregate_hash,
            "contentOnlyHash": self.content_only_hash,
            "pathBoundHash": self.path_bound_hash,
            # Testimony only — deliberately outside the aggregate hash so the
            # same corpus pins identically on every box.
            "root": self.root,
            "files": [f.row() for f in self.files],
        }

    def summary(self) -> dict[str, Any]:
        """The pin without the 1,400-row manifest — for embedding in a result."""
        return {
            "kind": PIN_KIND,
            "distribution": self.distribution,
            "version": self.version,
            "fileCount": self.file_count,
            "aggregateHash": self.aggregate_hash,
            # WHICH CONVENTION. A bare digest is not checkable across agents:
            # two are already in circulation for this corpus and boards failed
            # to reconcile on that alone, for reasons that had nothing to do
            # with the code. Always say how the number was computed.
            "aggregateHashConvention": (
                "sha256 over: pin kind, distribution, version, then one "
                "'<relpath> <sha256> <sizeBytes>' line per file, sorted by "
                "relpath. Root path excluded so the same corpus pins "
                "identically on every box."
            ),
            "interoperableDigests": self.interoperable_digests(),
            "root": self.root,
        }

    def interoperable_digests(self) -> dict[str, str]:
        """The two conventions already in circulation, emitted alongside ours.

        Neither matches our aggregate, because ours also binds distribution and
        version. Both are carried so a board reconciles against existing
        receipts without anyone re-deriving a digest by hand -- that
        convention drift already cost a round-trip and was mistaken for a
        corpus difference.

        ``contentOnly`` -- raw file bytes concatenated in sorted-relpath order,
        path-blind. Independently agreed by two agents for this corpus.
        ``pathBound`` -- per file ``sha256(relpath_utf8 || sha256_hex_ascii)``,
        concatenated in sorted-relpath order.
        """
        return {
            "contentOnly": self.content_only_hash,
            "pathBound": self.path_bound_hash,
            "enumerator": "SourceTree(root).paths()",
        }

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(f.path for f in self.files)

    @classmethod
    def from_json(cls, payload: Mapping[str, Any]) -> "CorpusPin":
        kind = payload.get("kind")
        if kind != PIN_KIND:
            raise CorpusPinDefect(
                owner="corpus pin decode",
                observed=f"pin kind {kind!r}",
                requested=f"pin kind {PIN_KIND!r}",
                fix="re-pin the corpus with the current instrument",
            )
        files = tuple(
            CorpusFile(
                path=str(row["path"]),
                sha256=str(row["sha256"]),
                size_bytes=int(row["sizeBytes"]),
            )
            for row in payload.get("files") or ()
        )
        pin = cls(
            distribution=str(payload["distribution"]),
            version=str(payload["version"]),
            file_count=int(payload["fileCount"]),
            aggregate_hash=str(payload["aggregateHash"]),
            files=files,
            content_only_hash=str(payload.get("contentOnlyHash") or ""),
            path_bound_hash=str(payload.get("pathBoundHash") or ""),
            root=str(payload.get("root") or ""),
        )
        # A pin whose own aggregate disagrees with its own manifest is a
        # corrupted pin, not a corpus mismatch. Say which one it is.
        recomputed = aggregate_hash(pin.distribution, pin.version, files)
        if recomputed != pin.aggregate_hash:
            raise CorpusPinDefect(
                owner="corpus pin decode",
                observed=(
                    f"pin file claims aggregate {pin.aggregate_hash}, "
                    f"its own manifest hashes to {recomputed}"
                ),
                requested="a pin whose aggregate hash covers its own manifest",
                fix="re-pin the corpus; do not hand-edit pin files",
            )
        if len(files) != pin.file_count:
            raise CorpusPinDefect(
                owner="corpus pin decode",
                observed=f"fileCount {pin.file_count} with {len(files)} manifest rows",
                requested="fileCount equal to the manifest length",
                fix="re-pin the corpus",
            )
        return pin


def aggregate_hash(
    distribution: str, version: str, files: Iterable[CorpusFile]
) -> str:
    """One sha256 over (distribution, version, sorted path→content manifest).

    The distribution and version are inside the hash on purpose: the identical
    file set claimed as two different pandas versions must not compare equal.
    """
    digest = hashlib.sha256()
    digest.update(f"{PIN_KIND}\n{distribution}\n{version}\n".encode("utf-8"))
    for entry in sorted(files, key=lambda f: f.path):
        digest.update(f"{entry.path} {entry.sha256} {entry.size_bytes}\n".encode())
    return digest.hexdigest()


def _sha256_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1 << 20)
            if not chunk:
                break
            size += len(chunk)
            digest.update(chunk)
    return digest.hexdigest(), size


def distribution_version(root: Path, distribution: str) -> str:
    """Read the installed version from the ``*.dist-info`` beside the package.

    No guessing and no fallback. If the metadata is not there, the caller must
    state the version explicitly — an unpinned version silently turns two
    different corpora into one scoreboard.
    """
    candidates = sorted(root.parent.glob(f"{distribution}-*.dist-info"))
    if len(candidates) == 1:
        name = candidates[0].name
        return name[len(distribution) + 1 : -len(".dist-info")]
    if not candidates:
        raise CorpusPinDefect(
            owner="corpus pin version",
            observed=f"no {distribution}-*.dist-info beside {root}",
            requested=f"exactly one installed {distribution} distribution",
            fix=f"pass --corpus-version explicitly, or install {distribution}",
        )
    raise CorpusPinDefect(
        owner="corpus pin version",
        observed=f"{len(candidates)} dist-info dirs beside {root}: "
        + ", ".join(c.name for c in candidates),
        requested=f"exactly one installed {distribution} distribution",
        fix="clean the environment, or pass --corpus-version explicitly",
    )


def pin_corpus(
    root: Path,
    *,
    distribution: str | None = None,
    version: str | None = None,
) -> CorpusPin:
    """Pin the corpus the census will actually walk.

    Enumeration goes through ``SourceTree(root).paths()`` — the census's own
    enumerator. Pinning a different walk would pin a denominator no run ever
    had, which defeats the entire purpose.
    """
    from sugar_source_tree.tree import SourceTree

    root = root.resolve()
    if not root.is_dir():
        raise CorpusPinDefect(
            owner="corpus pin",
            observed=f"corpus root {root} is not a directory",
            requested="a package root directory to pin",
            fix="point --corpus-root at the installed package directory",
        )
    dist = distribution or root.name
    resolved_version = version or distribution_version(root, dist)

    files: list[CorpusFile] = []
    by_path: dict[str, Path] = {}
    for path in SourceTree(root).paths():
        sha, size = _sha256_file(path)
        relative = path.resolve().relative_to(root).as_posix()
        by_path[relative] = path
        files.append(CorpusFile(path=relative, sha256=sha, size_bytes=size))
    if not files:
        raise CorpusPinDefect(
            owner="corpus pin",
            observed=f"SourceTree({root}).paths() enumerated no files",
            requested="a non-empty corpus",
            fix="check the corpus root",
        )
    ordered = tuple(sorted(files, key=lambda f: f.path))
    seen: set[str] = set()
    for entry in ordered:
        if entry.path in seen:
            raise CorpusPinDefect(
                owner="corpus pin",
                observed=f"duplicate enrolled path {entry.path}",
                requested="one manifest row per enrolled file",
                fix="the enumerator yielded a path twice — fix SourceTree.paths()",
            )
        seen.add(entry.path)
    # The two circulating conventions, over the SAME bytes and the SAME
    # enumeration, so a reader never has to guess which walk produced them.
    content = hashlib.sha256()
    path_bound = hashlib.sha256()
    for entry in ordered:
        content.update(by_path[entry.path].read_bytes())
        path_bound.update(entry.path.encode("utf-8"))
        path_bound.update(entry.sha256.encode("ascii"))
    return CorpusPin(
        distribution=dist,
        version=resolved_version,
        file_count=len(ordered),
        aggregate_hash=aggregate_hash(dist, resolved_version, ordered),
        files=ordered,
        content_only_hash=content.hexdigest(),
        path_bound_hash=path_bound.hexdigest(),
        root=str(root),
    )


def compare(expected: CorpusPin, observed: CorpusPin) -> dict[str, Any]:
    """Name every way two corpora differ — never a bare boolean.

    "Not comparable" is useless testimony. Which files appeared, which vanished,
    which changed content, whether the version moved: that is what tells the
    reader whether a delta is signal or a different pandas.
    """
    expected_by_path = {f.path: f for f in expected.files}
    observed_by_path = {f.path: f for f in observed.files}
    added = sorted(set(observed_by_path) - set(expected_by_path))
    removed = sorted(set(expected_by_path) - set(observed_by_path))
    changed = sorted(
        path
        for path in set(expected_by_path) & set(observed_by_path)
        if expected_by_path[path].sha256 != observed_by_path[path].sha256
    )
    return {
        "identical": expected.aggregate_hash == observed.aggregate_hash,
        "expectedAggregateHash": expected.aggregate_hash,
        "observedAggregateHash": observed.aggregate_hash,
        "expectedVersion": f"{expected.distribution} {expected.version}",
        "observedVersion": f"{observed.distribution} {observed.version}",
        "versionMoved": (expected.distribution, expected.version)
        != (observed.distribution, observed.version),
        "addedFiles": added,
        "removedFiles": removed,
        "changedFiles": changed,
    }


def require_pin(expected: CorpusPin, observed: CorpusPin) -> None:
    """Refuse to measure against a corpus that is not the pinned one."""
    report = compare(expected, observed)
    if report["identical"]:
        return
    raise CorpusPinDefect(
        owner="corpus pin check",
        observed=json.dumps(
            {
                key: report[key]
                for key in (
                    "expectedVersion",
                    "observedVersion",
                    "expectedAggregateHash",
                    "observedAggregateHash",
                )
            }
        )
        + f" added={len(report['addedFiles'])}"
        + f" removed={len(report['removedFiles'])}"
        + f" changed={len(report['changedFiles'])}",
        requested="the pinned corpus",
        fix=(
            "install the pinned distribution version, or re-pin deliberately "
            "and archive the old board as non-comparable"
        ),
    )


def load_pin(path: Path) -> CorpusPin:
    return CorpusPin.from_json(json.loads(path.read_text(encoding="utf-8")))


def write_pin(pin: CorpusPin, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(pin.to_json(), indent=2) + "\n", encoding="utf-8")
