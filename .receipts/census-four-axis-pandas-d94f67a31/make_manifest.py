#!/usr/bin/env python3
"""Build the reconstruction manifest for the pinned census receipt.

The tooling's own identity is known-broken at this commit (`sourceStamp:
unavailable`, `testExtraInputHash: None`, `suite-report.json` carrying no
commit, and the lease receipt emitting `"measuredCommit": "unknown"` -- I
observed all of these directly). So the manifest states identity itself, in
the artifact, rather than trusting what the tooling emitted.

Everything needed to ATTEMPT exact reconstruction is recorded here: the
measured commit, the corpus identity and per-file hashes summary, the
interpreter, the dependency versions, the lease receipts, and a hash of every
artifact and every script that produced it. Dropping an input now would decide
the rerun; nothing is dropped.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

R = Path("/Users/tsavo/census-pin-d94f67a31/.receipts/census-four-axis-pandas-d94f67a31")
PIN = "d94f67a3149ea2aceee4f9a8cff0397b6f6d374a"
HEAD_REPLAY = "c11767c5e48f2e6799d0d4a0d58823ea84486ac6"


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    import pandas

    corpus = Path(os.path.dirname(pandas.__file__))
    files = sorted(corpus.rglob("*.py"))
    # One hash over the whole corpus, in sorted-rglob order.
    #
    # THE CONVENTION IS PART OF THE RECEIPT. A bare digest is not checkable by
    # anyone who hashed the same bytes a different way -- timeout-bisect and I
    # produced different digests over a provably IDENTICAL corpus purely from
    # convention drift, and chased it until both were computed side by side.
    # Both are recorded so either can be reproduced without guessing.
    #
    #   pathBound  : for each file, sha256(relpath_utf8 || hex_digest_ascii)
    #                Binds paths, so a pure rename changes the digest.
    #   contentOnly: for each file, raw bytes concatenated.
    #                Path-blind; a rename is invisible to it.
    agg = hashlib.sha256()
    content_only = hashlib.sha256()
    for f in files:
        agg.update(str(f.relative_to(corpus)).encode())
        agg.update(sha256(f).encode())
        content_only.update(f.read_bytes())

    def pipfreeze() -> dict:
        out = {}
        for mod in ("pandas", "numpy", "blake3", "cbor2", "nacl", "tqdm", "pyarrow"):
            try:
                m = __import__(mod)
                out[mod] = getattr(m, "__version__", "unknown")
            except Exception:  # noqa: BLE001
                out[mod] = "absent"
        return out

    artifacts = {
        p.name: {"sha256": sha256(p), "bytes": p.stat().st_size}
        for p in sorted(R.iterdir())
        if p.is_file() and p.name != "MANIFEST.json"
    }

    manifest = {
        "receiptSchema": "sugar.census.four-axis.receipt.v1",
        "evidenceStatus": "completed, commit-pinned evidence - NOT authoritative",
        "evidenceNote": (
            "Predates #6290 identity authority. Becomes bankable authoritative "
            "evidence only through exact reconstruction or an authenticated "
            "rerun. Valid steering evidence now."
        ),
        "measuredCommit": PIN,
        "measuredCommitStatedBy": (
            "this manifest, NOT the tooling: lease-record.json emitted "
            "\"measuredCommit\": \"unknown\" at this commit"
        ),
        "knownInstrumentIdentityGaps": {
            "environment-identity.sourceStamp": "unavailable",
            "environment-identity.testExtraInputHash": None,
            "suite-report.json.commit": "absent",
            "lease-record.measuredCommit": "unknown (observed directly)",
        },
        "boundedReplayCommit": HEAD_REPLAY,
        "corpus": {
            "package": "pandas",
            "version": pandas.__version__,
            "root": str(corpus),
            "pyFiles": len(files),
            "aggregateSha256": agg.hexdigest(),
            "aggregateSha256Convention": (
                "pathBound: sorted(rglob('*.py')); per file "
                "sha256(relpath_utf8 || sha256_hex_ascii)"
            ),
            "aggregateSha256ContentOnly": content_only.hexdigest(),
            "aggregateSha256ContentOnlyConvention": (
                "contentOnly: sorted(rglob('*.py')); raw file bytes "
                "concatenated. Path-blind."
            ),
            "crossAgentCorpusAgreement": (
                "timeout-bisect independently reported "
                "a1155ae27c10a1828ac6a02b890a8b1ee23881a5f78c3d6265f02a63065ca77d, "
                "which equals aggregateSha256ContentOnly here. Same 1421 files, "
                "byte-identical; the digests differed only by convention."
            ),
            "fileIndexBase": (
                "1-based. The census prints [i+1/N] over sorted(rglob('*.py')), "
                "so census index 100 is timeout-bisect's 0-based index 99."
            ),
        },
        "environment": {
            "python": sys.version,
            "pythonExecutable": sys.executable,
            "platform": platform.platform(),
            "machine": platform.machine(),
            "hostname": platform.node(),
            "cpuCount": os.cpu_count(),
            "dependencies": pipfreeze(),
        },
        "contention": {
            "note": (
                "The BX lease excludes other sugar heavy measurements on this "
                "host only. It does NOT exclude concurrent rustc/agent load, "
                "which was present throughout. Absolute timings are upper "
                "bounds; see rank-stability.json (Spearman rho 0.6552)."
            ),
            "leasePath": "/var/tmp/sugar-heavy-measurement.lease",
            "leasePathIsOverride": True,
            "leasePathOverrideReason": (
                "DEFAULT_LEASE_PATH /home/runner/... does not exist on this "
                "macOS host. /var/tmp is a single real inode here (not "
                "per-container as on battleaxe runners), so flock(2) on it "
                "genuinely serializes local takers. Scope: machine-local."
            ),
        },
        "voidedRuns": {
            "run1": {
                "startedUtc": "2026-07-25T21:50:03Z",
                "verdict": "VOID - not a slow census, not a census",
                "cause": (
                    "The agent worktree supplying the instrument "
                    "(agent-a9758440c99edca00) was deleted by the harness "
                    "mid-sweep. Lazily-imported sugar modules "
                    "(sugar_lift_py_tests.sugar.named_expr_sugar, "
                    "yield_from_sugar) began raising ModuleNotFoundError at "
                    "file ~125/1421, producing 9 CRASH rows that would have "
                    "been misreported as product red."
                ),
                "discriminator": (
                    "run 2 on a durable tree at the same commit produced 0 "
                    "CRASH rows over all 1421 files"
                ),
                "secondaryDefect": (
                    "my wrapper's unconditional `exit 0` wrote "
                    "completed/zero-findings for a killed run - the one status "
                    "permitted to support a zero claim. Fixed in run 2."
                ),
            }
        },
        "artifacts": artifacts,
        "reconstruction": {
            "tree": "git worktree add <path> " + PIN,
            "pythonpath": "implementations/python/*/src",
            "command": "python3 -m sugar_lift_py_tests.census $(python3 -c 'import pandas,os;print(os.path.dirname(pandas.__file__))')",
            "underLease": "tools/heavy_measurement_lease.py --class pandas-four-axis-census",
        },
    }
    (R / "MANIFEST.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps({k: v for k, v in manifest.items() if k != "artifacts"}, indent=2))
    print(f"\nartifacts hashed: {len(artifacts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
