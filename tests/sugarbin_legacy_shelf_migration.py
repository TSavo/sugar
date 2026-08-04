#!/usr/bin/env python3
"""Behavioral teeth for the legacy binary-shelf migration."""

from __future__ import annotations

import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from sugar_lift_py_tests.repo_root import resolve_repo_root

REPO = resolve_repo_root()
TOOL = REPO / "tools" / "migrate_legacy_binary_shelf.py"
PLATFORM = "linux-x86_64"
PROFILE = "release"


def stamp(digit: str) -> str:
    return f"blake3-512_{digit * 128}"


def content_key(payload: bytes) -> str:
    result = subprocess.run(
        ["b3sum", "-l", "64", "--no-names"],
        input=payload,
        check=True,
        capture_output=True,
    )
    return f"blake3-512_{result.stdout.decode().strip()}"


def legacy_cell(
    shelf: Path,
    *,
    source_stamp: str,
    payload: bytes,
    binary: str = "sugar",
    build_identity: str | None = None,
    legacy_colon_keys: bool = False,
    malformed_manifest: bool = False,
    corrupt_payload: bool = False,
) -> Path:
    build_identity = build_identity or source_stamp
    name = f"{binary}-{PLATFORM}-{PROFILE}-{build_identity}"
    cell = shelf / PLATFORM / PROFILE / source_stamp / name
    cell.mkdir(parents=True)
    declared_payload = payload
    stored_payload = payload + b"-corrupt" if corrupt_payload else payload
    with gzip.GzipFile(
        filename=str(cell / f"{name}.gz"), mode="wb", mtime=0
    ) as target:
        target.write(stored_payload)
    sha256 = hashlib.sha256(declared_payload).hexdigest()
    manifest_source_stamp = source_stamp
    manifest_build_identity = build_identity
    if legacy_colon_keys:
        manifest_source_stamp = source_stamp.replace("blake3-512_", "blake3-512:")
        manifest_build_identity = build_identity.replace(
            "blake3-512_", "blake3-512:"
        )
    metadata = {
        "actor": "fixture",
        "buildStamp": manifest_source_stamp,
        "platform": PLATFORM,
        "profile": PROFILE,
        "publishedAt": "2026-08-03T00:00:00+00:00",
        "sha256": sha256,
        "source": f"/fixture/{binary}",
        "transport": "filesystem-cas-v2",
    }
    manifest = {
        "binary": binary,
        "buildIdentity": manifest_build_identity,
        "built": True,
        "cargo": "cargo fixture",
        "executed": False,
        "features": [],
        "package": f"{binary}-package",
        "platform": PLATFORM,
        "profile": PROFILE,
        "rustc": "rustc fixture",
        "schema": 1,
        "sha256": sha256,
        "sourceStamp": manifest_source_stamp,
        "targetTriple": "x86_64-unknown-linux-gnu",
    }
    (cell / f"{name}.metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    manifest_path = cell / f"{name}.sugarbin.json"
    if malformed_manifest:
        manifest_path.write_text('{"schema": 1}{"second": true}\n', encoding="utf-8")
    else:
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
    return cell


def plant_current_cell(
    shelf: Path,
    *,
    source_stamp: str,
    payload: bytes,
    binary: str = "sugar",
) -> tuple[str, Path, Path]:
    key = content_key(payload)
    cell = shelf / "cas" / key / binary
    cell.mkdir(parents=True)
    sha256 = hashlib.sha256(payload).hexdigest()
    with gzip.GzipFile(
        filename=str(cell / f"{binary}.gz"), mode="wb", mtime=0
    ) as target:
        target.write(payload)
    manifest = {
        "binary": binary,
        "buildIdentity": source_stamp,
        "built": True,
        "cargo": "cargo fixture",
        "executed": False,
        "features": [],
        "package": f"{binary}-package",
        "platform": PLATFORM,
        "profile": PROFILE,
        "rustc": "rustc fixture",
        "schema": 1,
        "sha256": sha256,
        "sourceStamp": source_stamp,
        "targetTriple": "x86_64-unknown-linux-gnu",
    }
    metadata = {
        "actor": "fixture",
        "buildStamp": source_stamp,
        "contentKey": key,
        "platform": PLATFORM,
        "profile": PROFILE,
        "sha256": sha256,
        "source": f"/fixture/{binary}",
        "transport": "filesystem-cas-v3",
    }
    (cell / f"{binary}.sugarbin.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (cell / f"{binary}.metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    ref = shelf / PLATFORM / PROFILE / "by-stamp" / source_stamp / f"{binary}.ref"
    ref.parent.mkdir(parents=True, exist_ok=True)
    ref.write_text(key + "\n", encoding="utf-8")
    return key, cell, ref


def tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        digest.update(str(path.relative_to(root)).encode())
        if path.is_file():
            digest.update(path.read_bytes())
    return digest.hexdigest()


class LegacyShelfMigrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="legacy-shelf-migration.")
        self.shelf = Path(self.temporary.name) / "shelf"
        self.shelf.mkdir()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_tool(
        self, *extra: str, env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(TOOL),
                "--shelf-root",
                str(self.shelf),
                "--platform",
                PLATFORM,
                "--profile",
                PROFILE,
                *extra,
            ],
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )

    def test_dry_run_reports_every_outcome_without_writing(self) -> None:
        legacy_cell(self.shelf, source_stamp=stamp("1"), payload=b"eligible")
        legacy_cell(
            self.shelf,
            source_stamp=stamp("2"),
            payload=b"checksum",
            corrupt_payload=True,
        )
        legacy_cell(
            self.shelf,
            source_stamp=stamp("3"),
            payload=b"malformed",
            malformed_manifest=True,
        )
        legacy_cell(self.shelf, source_stamp=stamp("4"), payload=b"current")
        plant_current_cell(
            self.shelf, source_stamp=stamp("4"), payload=b"current"
        )
        evidence = self.shelf / "cas" / "evidence" / ".incoming" / "survives"
        evidence.mkdir(parents=True)
        (evidence / "raw.txt").write_text("do-not-touch\n", encoding="utf-8")
        before = tree_digest(self.shelf)

        result = self.run_tool()

        self.assertEqual(result.returncode, 3, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["mode"], "dry-run")
        self.assertEqual(
            report["counts"],
            {
                "alreadyPresent": 1,
                "checksumFailed": 1,
                "conflict": 0,
                "discovered": 4,
                "malformedManifest": 1,
                "wouldMigrate": 1,
                "writesPerformed": 0,
            },
        )
        self.assertEqual(tree_digest(self.shelf), before)
        self.assertFalse(
            (self.shelf / PLATFORM / PROFILE / "by-stamp" / stamp("1")).exists()
        )

    def test_apply_is_idempotent_and_preserves_legacy_and_incoming(self) -> None:
        source_stamp = stamp("5")
        legacy = legacy_cell(
            self.shelf, source_stamp=source_stamp, payload=b"migrate-me"
        )
        legacy_before = tree_digest(legacy)
        evidence = self.shelf / "cas" / "evidence" / ".incoming" / "survives"
        evidence.mkdir(parents=True)
        (evidence / "raw.txt").write_text("do-not-touch\n", encoding="utf-8")
        incoming_before = tree_digest(self.shelf / "cas" / "evidence")

        first = self.run_tool("--apply")

        self.assertEqual(first.returncode, 0, first.stderr)
        first_report = json.loads(first.stdout)
        self.assertEqual(first_report["counts"]["migrated"], 1)
        self.assertEqual(first_report["counts"]["writesPerformed"], 1)
        key = content_key(b"migrate-me")
        current = self.shelf / "cas" / key / "sugar"
        ref = (
            self.shelf
            / PLATFORM
            / PROFILE
            / "by-stamp"
            / source_stamp
            / "sugar.ref"
        )
        self.assertEqual(ref.read_text(encoding="utf-8"), key + "\n")
        self.assertEqual(
            gzip.decompress((current / "sugar.gz").read_bytes()), b"migrate-me"
        )
        current_metadata = json.loads(
            (current / "sugar.metadata.json").read_text(encoding="utf-8")
        )
        self.assertEqual(current_metadata["contentKey"], key)
        self.assertEqual(current_metadata["transport"], "filesystem-cas-v3")
        self.assertEqual(current_metadata["buildStamp"], source_stamp)
        self.assertEqual(tree_digest(legacy), legacy_before)
        self.assertEqual(
            tree_digest(self.shelf / "cas" / "evidence"), incoming_before
        )
        current_before = tree_digest(current)
        ref_before = ref.read_bytes()

        second = self.run_tool("--apply")

        self.assertEqual(second.returncode, 0, second.stderr)
        second_report = json.loads(second.stdout)
        self.assertEqual(second_report["counts"]["migrated"], 0)
        self.assertEqual(second_report["counts"]["alreadyPresent"], 1)
        self.assertEqual(second_report["counts"]["writesPerformed"], 0)
        self.assertEqual(tree_digest(current), current_before)
        self.assertEqual(ref.read_bytes(), ref_before)

    def test_apply_never_overwrites_a_resolving_ref(self) -> None:
        source_stamp = stamp("6")
        legacy_cell(self.shelf, source_stamp=source_stamp, payload=b"old-build")
        key, current, ref = plant_current_cell(
            self.shelf, source_stamp=source_stamp, payload=b"newer-build"
        )
        current_before = tree_digest(current)
        ref_before = ref.read_bytes()

        result = self.run_tool("--apply")

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["counts"]["alreadyPresent"], 1)
        self.assertEqual(report["counts"]["writesPerformed"], 0)
        self.assertEqual(ref.read_text(encoding="utf-8"), key + "\n")
        self.assertEqual(ref.read_bytes(), ref_before)
        self.assertEqual(tree_digest(current), current_before)

    def test_apply_heals_a_matching_dangling_ref_without_rewriting_it(self) -> None:
        source_stamp = stamp("7")
        payload = b"restore-cas-cell"
        legacy_cell(self.shelf, source_stamp=source_stamp, payload=payload)
        key = content_key(payload)
        ref = (
            self.shelf
            / PLATFORM
            / PROFILE
            / "by-stamp"
            / source_stamp
            / "sugar.ref"
        )
        ref.parent.mkdir(parents=True)
        ref.write_text(key + "\n", encoding="utf-8")
        ref_before = ref.read_bytes()

        result = self.run_tool("--apply")

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["counts"]["migrated"], 1)
        self.assertEqual(ref.read_bytes(), ref_before)
        self.assertTrue((self.shelf / "cas" / key / "sugar" / "sugar.gz").is_file())

    def test_same_payload_at_two_source_stamps_is_refused_before_writing(self) -> None:
        payload = b"identical-build-output"
        legacy_cell(self.shelf, source_stamp=stamp("8"), payload=payload)
        legacy_cell(self.shelf, source_stamp=stamp("9"), payload=payload)
        before = tree_digest(self.shelf)

        result = self.run_tool("--apply")

        self.assertEqual(result.returncode, 3, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["counts"]["conflict"], 2)
        self.assertEqual(report["counts"]["migrated"], 0)
        self.assertEqual(report["counts"]["writesPerformed"], 0)
        self.assertEqual(tree_digest(self.shelf), before)

    def test_checksum_failure_is_refused_before_blake3_addressing(self) -> None:
        legacy_cell(
            self.shelf,
            source_stamp=stamp("a"),
            payload=b"declared-payload",
            corrupt_payload=True,
        )
        fake_bin = Path(self.temporary.name) / "fake-bin"
        fake_bin.mkdir()
        marker = Path(self.temporary.name) / "b3sum-was-called"
        fake_b3sum = fake_bin / "b3sum"
        fake_b3sum.write_text(
            f"#!/usr/bin/env bash\n: >{marker!s}\nexit 99\n", encoding="utf-8"
        )
        fake_b3sum.chmod(0o755)
        env = dict(os.environ)
        env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"

        result = self.run_tool(env=env)

        self.assertEqual(result.returncode, 3, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["counts"]["checksumFailed"], 1)
        self.assertFalse(marker.exists(), "BLAKE3 ran before SHA-256 validation")

    def test_legacy_split_identity_is_named_as_a_conflict_not_skipped(self) -> None:
        source_stamp = stamp("b")
        build_identity = stamp("c")
        legacy_cell(
            self.shelf,
            source_stamp=source_stamp,
            build_identity=build_identity,
            legacy_colon_keys=True,
            binary="coretests_sweep",
            payload=b"pre-identity-collapse",
        )

        result = self.run_tool()

        self.assertEqual(result.returncode, 3, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["counts"]["conflict"], 1)
        self.assertEqual(report["counts"]["malformedManifest"], 0)
        row = report["rows"][0]
        self.assertEqual(row["binary"], "coretests_sweep")
        self.assertEqual(row["sourceStamp"], source_stamp)
        self.assertIn("buildIdentity", row["detail"])

    def test_apply_normalizes_equal_legacy_key_spelling_for_current_pull(self) -> None:
        source_stamp = stamp("d")
        legacy_cell(
            self.shelf,
            source_stamp=source_stamp,
            legacy_colon_keys=True,
            payload=b"same-identity-legacy-spelling",
        )

        result = self.run_tool("--apply")

        self.assertEqual(result.returncode, 0, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["counts"]["migrated"], 1)
        key = content_key(b"same-identity-legacy-spelling")
        current_manifest = json.loads(
            (
                self.shelf
                / "cas"
                / key
                / "sugar"
                / "sugar.sugarbin.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(current_manifest["sourceStamp"], source_stamp)
        self.assertEqual(current_manifest["buildIdentity"], source_stamp)


if __name__ == "__main__":
    unittest.main()
