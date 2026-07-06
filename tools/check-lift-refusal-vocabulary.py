#!/usr/bin/env python3
"""Ratcheted census for lift-side `refus*` vocabulary.

REFUSE is the verifier's verb. Lift-side code may quote verifier verdicts,
but a lifter output, status, DTO, ProofIR node, or typed-effect boundary must
not name its own result as a refusal. This instrument pins the current surface
for the #3632 migration and makes new sites loud.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CENSUS = ROOT / "tools" / "lift_refusal_vocabulary_census.json"
REFUS_PATTERN = re.compile(r"refus", re.IGNORECASE)
SCAN_PATHS = (":(glob)implementations/python/*/src/**/*.py",)

LIFT_OUTPUT_SPEAKER = "lift-output-backlog"


@dataclass(frozen=True)
class Occurrence:
    key: str
    path: str
    line: int
    text: str
    speaker: str
    reason: str
    replacement: str

    def to_json(self) -> dict[str, object]:
        return {
            "key": self.key,
            "path": self.path,
            "line": self.line,
            "text": self.text,
            "speaker": self.speaker,
            "reason": self.reason,
            "replacement": self.replacement,
        }


@dataclass(frozen=True)
class Classified:
    speaker: str
    reason: str
    replacement: str


def normalize_text(line: str) -> str:
    return " ".join(line.strip().split())


def stable_digest(path: str, text: str) -> str:
    return hashlib.sha256(f"{path}\0{text}".encode("utf-8")).hexdigest()[:16]


def git_files() -> list[str]:
    output = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", *SCAN_PATHS],
        cwd=ROOT,
        text=True,
    )
    return sorted(line for line in output.splitlines() if line)


def classify(path: str, text: str) -> Classified:
    """Classify the speaker for an occurrence.

    The check is intentionally conservative: source/report/proof vocabulary
    that the lifter emits is backlog. Verifier/discharge callers may continue
    to quote the prove-side `refused` verdict.
    """

    if path.startswith("implementations/python/sugar-build-witness/src/"):
        return Classified(
            "verifier-verdict-quote",
            "witness builder reads or reports prove-side verifier verdicts",
            "keep verifier status vocabulary; do not use as lift output name",
        )
    if path.startswith("implementations/python/sugar-lift-py-pytest-witness/src/"):
        return Classified(
            "verifier-verdict-quote",
            "pytest witness kit reads or reports prove-side verifier verdicts",
            "keep verifier status vocabulary; do not use as lift output name",
        )
    if path.endswith("/witness_verify.py") or path.endswith("/verify_rpc.py"):
        return Classified(
            "verifier-verdict-quote",
            "witness or verify RPC boundary quotes verifier refusal verdicts",
            "keep verifier status vocabulary; do not use as lift output name",
        )
    if path.endswith("/verify_dialect.py"):
        return Classified(
            "verify-dialect-boundary",
            "verify-facing dialect describes what the verifier can discharge",
            "rename only with verify schema compatibility if the field crosses RPC",
        )
    if path.endswith("/witness_oracle.py") or path.endswith("/source_oracle.py"):
        return Classified(
            "provenance-oracle-guard",
            "source/witness oracle guards sealed evidence identity, not lifter output",
            "keep only as oracle guard vocabulary unless a future evidence-effect rename owns it",
        )
    if path.endswith("/grammar_ledger.py"):
        return Classified(
            "grammar-census-prose",
            "grammar census documentation and scoring prose, not an emitted lift result",
            "keep as doctrine prose unless future docs sweep narrows it",
        )
    if "/idd/" in path:
        return Classified(
            "instrument-prose",
            "IDD instrument code names an existing frontier or vocabulary row",
            "keep until the named frontier row is retired by its owning migration",
        )
    if path.startswith("implementations/python/sugar-emit-python-"):
        return Classified(
            "emitter-provenance-guard",
            "python emitter provenance guard or RPC quote, not the lifter's own output",
            "keep only while it quotes external/referee state",
        )

    if "verifier" in text.lower() or "prove-side" in text.lower():
        return Classified(
            "verifier-verdict-quote",
            "line explicitly talks about verifier/prove-side refusal vocabulary",
            "keep verifier status vocabulary; do not use as lift output name",
        )

    return Classified(
        LIFT_OUTPUT_SPEAKER,
        "lifter-side output/status/effect vocabulary still uses the verifier verb",
        "rename to typed effect/incomplete vocabulary with dual-read compatibility for wire strings",
    )


def collect() -> list[Occurrence]:
    raw: list[tuple[str, int, str, Classified]] = []
    for path in git_files():
        full = ROOT / path
        if not full.is_file():
            continue
        try:
            lines = full.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            continue
        for line_no, line in enumerate(lines, start=1):
            if not REFUS_PATTERN.search(line):
                continue
            text = normalize_text(line)
            raw.append((path, line_no, text, classify(path, text)))

    ordinals: collections.Counter[str] = collections.Counter()
    occurrences: list[Occurrence] = []
    for path, line_no, text, classified in raw:
        base = f"{path}:{stable_digest(path, text)}"
        ordinals[base] += 1
        key = f"{base}:{ordinals[base]}"
        occurrences.append(
            Occurrence(
                key=key,
                path=path,
                line=line_no,
                text=text,
                speaker=classified.speaker,
                reason=classified.reason,
                replacement=classified.replacement,
            )
        )
    return sorted(occurrences, key=lambda item: item.key)


def load_expected(path: Path) -> list[Occurrence]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [
        Occurrence(
            key=str(row["key"]),
            path=str(row["path"]),
            line=int(row["line"]),
            text=str(row["text"]),
            speaker=str(row["speaker"]),
            reason=str(row["reason"]),
            replacement=str(row["replacement"]),
        )
        for row in payload["occurrences"]
    ]


def census_payload(occurrences: list[Occurrence]) -> dict[str, object]:
    speaker_counts = collections.Counter(item.speaker for item in occurrences)
    return {
        "schema": 1,
        "issue": "#3632",
        "law": "REFUSE is the verifier verb; lift outputs are reduced meaning or typed effects.",
        "identity": "path + normalized text digest + duplicate ordinal; line is display only",
        "total_occurrences": len(occurrences),
        "lift_output_backlog": speaker_counts[LIFT_OUTPUT_SPEAKER],
        "speaker_counts": dict(sorted(speaker_counts.items())),
        "occurrences": [item.to_json() for item in occurrences],
    }


def write_current(path: Path) -> None:
    occurrences = collect()
    path.write_text(
        json.dumps(census_payload(occurrences), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print_summary(occurrences)
    print(f"WROTE: {path.relative_to(ROOT)}")


def print_summary(occurrences: Iterable[Occurrence]) -> None:
    items = list(occurrences)
    speaker_counts = collections.Counter(item.speaker for item in items)
    file_count = len({item.path for item in items})
    print(f"R(refus-vocabulary-total)={len(items)} across {file_count} files")
    print(f"R(lift-output-refusal-vocabulary)={speaker_counts[LIFT_OUTPUT_SPEAKER]}")
    for speaker, count in sorted(speaker_counts.items()):
        print(f"  {speaker}: {count}")


def compare(expected: list[Occurrence], observed: list[Occurrence]) -> int:
    expected_by_key = {item.key: item for item in expected}
    observed_by_key = {item.key: item for item in observed}
    stale = [
        item for key, item in expected_by_key.items() if key not in observed_by_key
    ]
    new = [item for key, item in observed_by_key.items() if key not in expected_by_key]
    changed_classification = [
        (expected_by_key[key], observed_by_key[key])
        for key in sorted(expected_by_key.keys() & observed_by_key.keys())
        if (
            expected_by_key[key].speaker,
            expected_by_key[key].reason,
            expected_by_key[key].replacement,
        )
        != (
            observed_by_key[key].speaker,
            observed_by_key[key].reason,
            observed_by_key[key].replacement,
        )
    ]

    print_summary(observed)

    if not stale and not new and not changed_classification:
        print("PASS: lift-side refusal vocabulary census matches the pinned multiset")
        return 0

    if new:
        print(
            "\nFAIL: new refus* vocabulary sites are not classified:", file=sys.stderr
        )
        for item in new[:50]:
            print(
                f"{item.path}:{item.line}: speaker={item.speaker}: {item.text}",
                file=sys.stderr,
            )
            print(f"  replacement={item.replacement}", file=sys.stderr)
        if len(new) > 50:
            print(f"  ... {len(new) - 50} more new rows", file=sys.stderr)

    if stale:
        print(
            "\nFAIL: pinned refus* vocabulary sites vanished; ratchet the census:",
            file=sys.stderr,
        )
        for item in stale[:50]:
            print(
                f"{item.path}: pinned-line={item.line}: speaker={item.speaker}: {item.text}",
                file=sys.stderr,
            )
        if len(stale) > 50:
            print(f"  ... {len(stale) - 50} more stale rows", file=sys.stderr)

    if changed_classification:
        print(
            "\nFAIL: pinned refus* vocabulary classifications drifted:", file=sys.stderr
        )
        for expected_item, observed_item in changed_classification[:50]:
            print(
                f"{observed_item.path}:{observed_item.line}: {observed_item.text}",
                file=sys.stderr,
            )
            print(f"  expected={expected_item.speaker}", file=sys.stderr)
            print(f"  observed={observed_item.speaker}", file=sys.stderr)
        if len(changed_classification) > 50:
            print(
                f"  ... {len(changed_classification) - 50} more classification changes",
                file=sys.stderr,
            )
    return 1


def self_test() -> int:
    planted = Occurrence(
        key="implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/planted_refusal_tooth.py:planted:1",
        path="implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/planted_refusal_tooth.py",
        line=1,
        text='reason = "lifter refused this shape"',
        speaker=LIFT_OUTPUT_SPEAKER,
        reason="lifter-side output/status/effect vocabulary still uses the verifier verb",
        replacement="rename to typed effect/incomplete vocabulary with dual-read compatibility for wire strings",
    )
    expected_by_key: dict[str, Occurrence] = {}
    observed_by_key = {planted.key: planted}
    new = [item for key, item in observed_by_key.items() if key not in expected_by_key]
    if not new:
        print(
            "FAIL: planted refus* output vocabulary did not trip the census",
            file=sys.stderr,
        )
        return 1
    if (
        new[0].speaker != LIFT_OUTPUT_SPEAKER
        or "planted_refusal_tooth.py" not in new[0].path
    ):
        print(
            "FAIL: planted refus* output vocabulary tripped the wrong row",
            file=sys.stderr,
        )
        return 1
    print("PASS: planted refus* output vocabulary trips the census")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--census", type=Path, default=DEFAULT_CENSUS)
    parser.add_argument("--write-current", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test()
    if args.write_current:
        write_current(args.census)
        return 0
    if not args.census.exists():
        print(f"FAIL: missing census file: {args.census}", file=sys.stderr)
        return 2
    return compare(load_expected(args.census), collect())


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
