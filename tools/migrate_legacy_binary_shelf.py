#!/usr/bin/env python3
"""Migrate verified stamp-keyed binary shelf cells into the current CAS layout.

The default is a read-only dry run. ``--apply`` copies existing compressed
payloads and manifests into ``cas/<h(payload)>/<binary>`` and creates the
``sourceStamp -> h(payload)`` reference. Legacy cells are never removed.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any


CONTENT_KEY = re.compile(r"blake3-512_[0-9a-f]{128}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
BINARY = re.compile(r"[A-Za-z0-9._-]+\Z")
CHUNK_SIZE = 1024 * 1024


class InstrumentFailure(RuntimeError):
    """The migration instrument could not render a trustworthy verdict."""


class MalformedManifest(ValueError):
    """A legacy cell's identity testimony is incomplete or contradictory."""


class ChecksumFailure(ValueError):
    """A legacy or current cell's payload does not match its testimony."""


@dataclass(frozen=True)
class LegacyCell:
    path: Path
    source_stamp: str
    build_identity: str
    binary: str
    legacy_name: str
    gzip_path: Path
    manifest_path: Path
    metadata_path: Path


@dataclass
class Row:
    legacyCell: str
    sourceStamp: str | None = None
    binary: str | None = None
    contentKey: str | None = None
    status: str = "malformed-manifest"
    detail: str = ""
    candidate: LegacyCell | None = None
    manifest: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None

    def render(self) -> dict[str, Any]:
        return {
            key: value
            for key, value in {
                "legacyCell": self.legacyCell,
                "sourceStamp": self.sourceStamp,
                "binary": self.binary,
                "contentKey": self.contentKey,
                "status": self.status,
                "detail": self.detail,
            }.items()
            if value is not None
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shelf-root", type=Path, required=True)
    parser.add_argument("--platform", default="linux-x86_64")
    parser.add_argument("--profile", default="release")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="atomically install eligible cells and refs (default: dry run)",
    )
    args = parser.parse_args()
    for label in ("platform", "profile"):
        value = getattr(args, label)
        if not BINARY.fullmatch(value):
            parser.error(f"--{label} must be path-safe")
    return args


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise MalformedManifest(f"{label} is not readable JSON: {error}") from error
    if not isinstance(value, dict):
        raise MalformedManifest(f"{label} root is not an object")
    return value


def require_equal(data: dict[str, Any], field: str, expected: Any, label: str) -> None:
    if data.get(field) != expected:
        raise MalformedManifest(
            f"{label}.{field}={data.get(field)!r}, expected {expected!r}"
        )


def require_nonempty_string(data: dict[str, Any], field: str, label: str) -> None:
    value = data.get(field)
    if not isinstance(value, str) or not value:
        raise MalformedManifest(f"{label}.{field} is not a non-empty string")


def normalize_content_key(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise MalformedManifest(f"{label} is not a string")
    normalized = value.replace("blake3-512:", "blake3-512_", 1)
    if not CONTENT_KEY.fullmatch(normalized):
        raise MalformedManifest(f"{label} is not a blake3-512 key: {value!r}")
    return normalized


def parse_legacy_cell(
    path: Path, *, platform: str, profile: str
) -> tuple[LegacyCell, dict[str, Any], dict[str, Any]]:
    source_stamp = normalize_content_key(
        path.parent.name, "source-stamp directory"
    )
    identity_separator = f"-{platform}-{profile}-"
    binary, separator, identity_text = path.name.rpartition(identity_separator)
    if not separator:
        raise MalformedManifest(
            f"legacy leaf {path.name!r} does not contain {identity_separator!r}"
        )
    if not BINARY.fullmatch(binary):
        raise MalformedManifest(f"legacy binary name is not path-safe: {binary!r}")
    build_identity = normalize_content_key(identity_text, "legacy leaf build identity")
    candidate = LegacyCell(
        path=path,
        source_stamp=source_stamp,
        build_identity=build_identity,
        binary=binary,
        legacy_name=path.name,
        gzip_path=path / f"{path.name}.gz",
        manifest_path=path / f"{path.name}.sugarbin.json",
        metadata_path=path / f"{path.name}.metadata.json",
    )
    for artifact in (
        candidate.gzip_path,
        candidate.manifest_path,
        candidate.metadata_path,
    ):
        if not artifact.is_file():
            raise MalformedManifest(f"legacy cell is missing {artifact.name}")

    manifest = load_json(candidate.manifest_path, "manifest")
    metadata = load_json(candidate.metadata_path, "metadata")
    expected_manifest = {
        "schema": 1,
        "binary": binary,
        "platform": platform,
        "profile": profile,
        "features": [],
        "built": True,
        "executed": False,
    }
    for field, expected in expected_manifest.items():
        require_equal(manifest, field, expected, "manifest")
    if normalize_content_key(manifest.get("sourceStamp"), "manifest.sourceStamp") != source_stamp:
        raise MalformedManifest("manifest.sourceStamp does not equal the parent stamp")
    if normalize_content_key(
        manifest.get("buildIdentity"), "manifest.buildIdentity"
    ) != build_identity:
        raise MalformedManifest("manifest.buildIdentity does not equal the leaf identity")
    for field in ("package", "targetTriple", "rustc", "cargo"):
        require_nonempty_string(manifest, field, "manifest")
    expected_metadata = {
        "platform": platform,
        "profile": profile,
        "transport": "filesystem-cas-v2",
    }
    for field, expected in expected_metadata.items():
        require_equal(metadata, field, expected, "metadata")
    if normalize_content_key(metadata.get("buildStamp"), "metadata.buildStamp") != source_stamp:
        raise MalformedManifest("metadata.buildStamp does not equal the parent stamp")
    for field in ("actor", "publishedAt", "source"):
        require_nonempty_string(metadata, field, "metadata")
    manifest_sha = manifest.get("sha256")
    metadata_sha = metadata.get("sha256")
    if not isinstance(manifest_sha, str) or not SHA256.fullmatch(manifest_sha):
        raise MalformedManifest("manifest.sha256 is not a SHA-256 digest")
    if metadata_sha != manifest_sha:
        raise MalformedManifest(
            "metadata.sha256 does not equal the manifest payload checksum"
        )
    return candidate, manifest, metadata


def hash_gzip_payload(path: Path, expected_sha256: str) -> tuple[str, str]:
    """Validate SHA-256, then derive BLAKE3 from the verified payload."""
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix="sugarbin-legacy-payload.", delete=False
        ) as temporary:
            temporary_path = Path(temporary.name)
            sha256 = hashlib.sha256()
            with gzip.open(path, "rb") as source:
                while chunk := source.read(CHUNK_SIZE):
                    sha256.update(chunk)
                    temporary.write(chunk)
    except (OSError, EOFError) as error:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise ChecksumFailure(f"payload gzip cannot be decompressed: {error}") from error
    actual_sha256 = sha256.hexdigest()
    if actual_sha256 != expected_sha256:
        assert temporary_path is not None
        temporary_path.unlink(missing_ok=True)
        raise ChecksumFailure(
            f"decompressed payload sha256={actual_sha256}, manifest={expected_sha256}"
        )
    assert temporary_path is not None
    try:
        result = subprocess.run(
            ["b3sum", "-l", "64", "--no-names", str(temporary_path)],
            check=False,
            capture_output=True,
        )
    except OSError as error:
        raise InstrumentFailure(f"cannot execute b3sum: {error}") from error
    finally:
        temporary_path.unlink(missing_ok=True)
    if result.returncode != 0:
        raise InstrumentFailure(
            f"b3sum exited {result.returncode}: "
            f"{result.stderr.decode(errors='replace').strip()}"
        )
    digest = result.stdout.decode("ascii", errors="strict").strip()
    if not re.fullmatch(r"[0-9a-f]{128}", digest):
        raise InstrumentFailure(f"b3sum emitted a malformed digest: {digest!r}")
    return actual_sha256, f"blake3-512_{digest}"


def discover_legacy_cells(root: Path, platform: str, profile: str) -> list[Path]:
    population = root / platform / profile
    if not population.is_dir():
        raise InstrumentFailure(f"legacy shelf population does not exist: {population}")
    cells: list[Path] = []
    for stamp_dir in sorted(population.iterdir()):
        if not stamp_dir.is_dir() or stamp_dir.name == "by-stamp":
            continue
        for cell in sorted(stamp_dir.iterdir()):
            if cell.is_dir() and cell.name != ".incoming":
                cells.append(cell)
    return cells


def current_paths(
    root: Path, platform: str, profile: str, source_stamp: str, binary: str, key: str
) -> tuple[Path, Path]:
    cell = root / "cas" / key / binary
    ref = root / platform / profile / "by-stamp" / source_stamp / f"{binary}.ref"
    return cell, ref


def read_ref(ref: Path) -> str | None:
    if not ref.exists():
        return None
    try:
        key = "".join(ref.read_text(encoding="utf-8").split())
    except (OSError, UnicodeError) as error:
        raise MalformedManifest(f"current ref is unreadable: {error}") from error
    if not CONTENT_KEY.fullmatch(key):
        raise MalformedManifest(f"current ref is not a blake3-512 key: {key!r}")
    return key


def current_cell_complete(cell: Path, binary: str) -> bool:
    return all(
        (cell / f"{binary}{suffix}").is_file()
        for suffix in (".gz", ".sugarbin.json", ".metadata.json")
    )


def current_cell_resolves(
    cell: Path,
    *,
    binary: str,
    source_stamp: str,
    content_key: str,
    platform: str,
    profile: str,
) -> bool:
    if not current_cell_complete(cell, binary):
        return False
    manifest_path = cell / f"{binary}.sugarbin.json"
    try:
        manifest = load_json(manifest_path, "current manifest")
        for field, expected in {
            "schema": 1,
            "binary": binary,
            "sourceStamp": source_stamp,
            "buildIdentity": source_stamp,
            "platform": platform,
            "profile": profile,
            "built": True,
            "executed": False,
        }.items():
            require_equal(manifest, field, expected, "current manifest")
        manifest_sha = manifest.get("sha256")
        if not isinstance(manifest_sha, str) or not SHA256.fullmatch(manifest_sha):
            return False
        actual_sha, actual_key = hash_gzip_payload(
            cell / f"{binary}.gz", manifest_sha
        )
    except (MalformedManifest, ChecksumFailure):
        return False
    return actual_key == content_key and manifest.get("sha256") == actual_sha


def classify_cell(
    path: Path, *, root: Path, platform: str, profile: str
) -> Row:
    row = Row(legacyCell=str(path))
    try:
        candidate, manifest, metadata = parse_legacy_cell(
            path, platform=platform, profile=profile
        )
        row.sourceStamp = candidate.source_stamp
        row.binary = candidate.binary
        actual_sha, content_key = hash_gzip_payload(
            candidate.gzip_path, manifest["sha256"]
        )
        row.contentKey = content_key
        row.candidate = candidate
        row.manifest = manifest
        row.metadata = metadata
        if candidate.build_identity != candidate.source_stamp:
            row.status = "conflict"
            row.detail = (
                f"legacy buildIdentity={candidate.build_identity} differs from "
                f"sourceStamp={candidate.source_stamp}; current build_identity(sourceStamp) "
                "requires equality, and migration cannot fabricate it"
            )
            return row
        current_cell, ref = current_paths(
            root,
            platform,
            profile,
            candidate.source_stamp,
            candidate.binary,
            content_key,
        )
        try:
            ref_key = read_ref(ref)
        except MalformedManifest as error:
            row.status = "conflict"
            row.detail = str(error)
            return row
        if ref_key is not None:
            referred_cell = root / "cas" / ref_key / candidate.binary
            if current_cell_resolves(
                referred_cell,
                binary=candidate.binary,
                source_stamp=candidate.source_stamp,
                content_key=ref_key,
                platform=platform,
                profile=profile,
            ):
                row.status = "already-present"
                row.detail = "existing ref already resolves to a verified current cell"
                return row
            if ref_key != content_key:
                row.status = "conflict"
                row.detail = (
                    f"existing unresolved ref names {ref_key}; migration will not overwrite it"
                )
                return row
        if current_cell.exists() and not current_cell_resolves(
            current_cell,
            binary=candidate.binary,
            source_stamp=candidate.source_stamp,
            content_key=content_key,
            platform=platform,
            profile=profile,
        ):
            row.status = "conflict"
            row.detail = (
                "target CAS leaf exists but is incomplete or carries different identity testimony"
            )
            return row
        row.status = "candidate"
        row.detail = "verified legacy bytes can populate current CAS and stamp ref"
        return row
    except ChecksumFailure as error:
        row.status = "checksum-failed"
        row.detail = str(error)
        return row
    except MalformedManifest as error:
        row.status = "malformed-manifest"
        row.detail = str(error)
        return row


def reject_unrepresentable_collisions(rows: list[Row]) -> None:
    groups: dict[tuple[str, str], list[Row]] = {}
    for row in rows:
        if row.status == "candidate" and row.contentKey and row.binary:
            groups.setdefault((row.contentKey, row.binary), []).append(row)
    for (content_key, binary), group in groups.items():
        stamps = {row.sourceStamp for row in group}
        if len(stamps) <= 1:
            continue
        detail = (
            f"{len(stamps)} source stamps share CAS payload {content_key} for {binary}, "
            "but the current leaf carries one source-specific manifest"
        )
        for row in group:
            row.status = "conflict"
            row.detail = detail


def copy_verified_cell(row: Row, *, root: Path, platform: str, profile: str) -> str:
    assert row.candidate is not None
    assert row.contentKey is not None
    candidate = row.candidate
    target, ref = current_paths(
        root,
        platform,
        profile,
        candidate.source_stamp,
        candidate.binary,
        row.contentKey,
    )

    # Re-evaluate both protected destinations immediately before writing. A
    # concurrent publisher may have completed either after the dry scan.
    existing_ref = read_ref(ref)
    if existing_ref is not None:
        referred_cell = root / "cas" / existing_ref / candidate.binary
        if current_cell_resolves(
            referred_cell,
            binary=candidate.binary,
            source_stamp=candidate.source_stamp,
            content_key=existing_ref,
            platform=platform,
            profile=profile,
        ):
            return "already-present"
        if existing_ref != row.contentKey:
            raise MalformedManifest(
                f"existing unresolved ref names {existing_ref}; refusing overwrite"
            )

    if target.exists():
        if not current_cell_resolves(
            target,
            binary=candidate.binary,
            source_stamp=candidate.source_stamp,
            content_key=row.contentKey,
            platform=platform,
            profile=profile,
        ):
            raise MalformedManifest(
                "target CAS leaf appeared with incomplete or different testimony"
            )
    else:
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o777)
        stage = Path(
            tempfile.mkdtemp(
                prefix=f".{candidate.binary}.legacy-migration.", dir=target.parent
            )
        )
        try:
            shutil.copyfile(candidate.gzip_path, stage / f"{candidate.binary}.gz")
            current_manifest = dict(row.manifest or {})
            current_manifest["sourceStamp"] = candidate.source_stamp
            current_manifest["buildIdentity"] = candidate.source_stamp
            (stage / f"{candidate.binary}.sugarbin.json").write_text(
                json.dumps(current_manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            current_metadata = dict(row.metadata or {})
            current_metadata["contentKey"] = row.contentKey
            current_metadata["transport"] = "filesystem-cas-v3"
            (stage / f"{candidate.binary}.metadata.json").write_text(
                json.dumps(current_metadata, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            os.chmod(stage, 0o777)
            for child in stage.iterdir():
                os.chmod(child, 0o644)
            try:
                os.rename(stage, target)
            except OSError:
                if not current_cell_resolves(
                    target,
                    binary=candidate.binary,
                    source_stamp=candidate.source_stamp,
                    content_key=row.contentKey,
                    platform=platform,
                    profile=profile,
                ):
                    raise
        finally:
            if stage.exists():
                shutil.rmtree(stage)

    if existing_ref is None:
        ref.parent.mkdir(parents=True, exist_ok=True, mode=0o777)
        fd, temporary_name = tempfile.mkstemp(prefix=f".{candidate.binary}.ref.", dir=ref.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                output.write(row.contentKey + "\n")
                output.flush()
                os.fsync(output.fileno())
            os.chmod(temporary, 0o644)
            try:
                os.link(temporary, ref)
            except FileExistsError:
                raced_key = read_ref(ref)
                if raced_key != row.contentKey:
                    raise MalformedManifest(
                        f"stamp ref appeared concurrently with {raced_key}; refusing overwrite"
                    )
        finally:
            temporary.unlink(missing_ok=True)
    return "migrated"


def make_report(
    rows: list[Row], *, root: Path, platform: str, profile: str, apply: bool
) -> dict[str, Any]:
    counts: dict[str, int] = {
        "alreadyPresent": sum(row.status == "already-present" for row in rows),
        "checksumFailed": sum(row.status == "checksum-failed" for row in rows),
        "conflict": sum(row.status == "conflict" for row in rows),
        "discovered": len(rows),
        "malformedManifest": sum(row.status == "malformed-manifest" for row in rows),
    }
    if apply:
        counts["migrated"] = sum(row.status == "migrated" for row in rows)
        counts["writesPerformed"] = counts["migrated"]
    else:
        counts["wouldMigrate"] = sum(row.status == "candidate" for row in rows)
        counts["writesPerformed"] = 0
    return {
        "schema": 1,
        "mode": "apply" if apply else "dry-run",
        "shelfRoot": str(root),
        "platform": platform,
        "profile": profile,
        "counts": counts,
        "rows": [row.render() for row in rows],
    }


def main() -> int:
    args = parse_args()
    root = args.shelf_root.resolve()
    try:
        paths = discover_legacy_cells(root, args.platform, args.profile)
        rows = [
            classify_cell(
                path, root=root, platform=args.platform, profile=args.profile
            )
            for path in paths
        ]
        reject_unrepresentable_collisions(rows)
        if args.apply:
            for row in rows:
                if row.status != "candidate":
                    continue
                try:
                    row.status = copy_verified_cell(
                        row, root=root, platform=args.platform, profile=args.profile
                    )
                    row.detail = (
                        "legacy bytes installed without rebuild"
                        if row.status == "migrated"
                        else "concurrent publisher completed an existing resolution"
                    )
                except MalformedManifest as error:
                    row.status = "conflict"
                    row.detail = str(error)
        report = make_report(
            rows,
            root=root,
            platform=args.platform,
            profile=args.profile,
            apply=args.apply,
        )
    except InstrumentFailure as error:
        print(f"legacy shelf migration unmeasured: {error}", file=sys.stderr)
        return 2
    json.dump(report, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    counts = report["counts"]
    refusal_counts = ("checksumFailed", "malformedManifest", "conflict")
    return 3 if any(counts[name] for name in refusal_counts) else 0


if __name__ == "__main__":
    raise SystemExit(main())
