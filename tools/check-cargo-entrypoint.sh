#!/bin/sh
# SPDX-License-Identifier: MIT OR Apache-2.0

set -eu

makefile="${1:-Makefile}"

if [ ! -f "$makefile" ]; then
  echo "FAIL: $makefile does not exist" >&2
  exit 2
fi

offenders="$(
  awk '
    /^[[:space:]]*#/ { next }
    /@echo/ { next }
    /(^|[[:space:];(&|])cargo[[:space:]]+(build|test|check|run|tree|clean)([[:space:]\\]|$)/ {
      print FILENAME ":" FNR ":" $0
    }
  ' "$makefile"
)"

if [ -n "$offenders" ]; then
  echo "FAIL: Makefile must route Rust Cargo work through \$(CARGO) or \$(CARGO_LOCAL), not raw cargo:" >&2
  echo "$offenders" >&2
  exit 1
fi

binary_offenders="$(
  python3 - <<'PY'
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path.cwd()

PATTERNS = [
    (
        re.compile(r"target/(?:debug|release)/sugar(?:$|[\"'\\s)])"),
        "direct target sugar path; replacement=bin/sugarbin",
    ),
    (
        re.compile(r"\bcargo\s+build\b.*(?:-p\s+sugar-cli|--bin\s+sugar(?:$|\s))"),
        "direct cargo build of sugar; replacement=bin/sugarbin",
    ),
    (
        re.compile(r"\bcargo\s+run\b.*(?:-p\s+sugar-cli|--bin\s+sugar(?:$|\s))"),
        "direct cargo run of sugar; replacement=bin/sugarbin",
    ),
    (
        re.compile(r"(?<![\"'])\bsugar\s+(?:lift|prove|verify|mint)\b"),
        "bare sugar invocation; replacement=bin/sugarbin-resolved path",
    ),
]

SCAN_SUFFIXES = {".sh", ".py", ".rs", ".yml", ".yaml", ".toml"}
SCAN_NAMES = {"Makefile"}
SKIP_PREFIXES = (
    "docs/",
    "protocol/",
    "conformance/",
    ".git/",
)
SELF_EXEMPT = {
    "bin/sugarbin": "the single binary acquisition entrypoint",
    "tools/check-cargo-entrypoint.sh": "the gate owns the forbidden-pattern strings",
    "implementations/python/sugar-lift-py-tests/tests/test_binary_handoff_policy.py": (
        "policy test plants forbidden strings to prove the gate"
    ),
}


def tracked_files() -> list[pathlib.Path]:
    out = subprocess.check_output(["git", "ls-files"], text=True)
    paths = [pathlib.Path(line) for line in out.splitlines() if line]
    extras = [pathlib.Path("bin/sugarbin")]
    for extra in extras:
        if extra.exists() and extra not in paths:
            paths.append(extra)
    return sorted(paths)


def is_comment(line: str, path: pathlib.Path) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if path.suffix in {".sh", ".py", ".yml", ".yaml", ".toml"}:
        return stripped.startswith("#")
    if path.suffix == ".rs":
        return stripped.startswith("//") or stripped.startswith("*")
    return False


def is_prose_or_label(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith(
        (
            "echo ",
            "printf ",
            "description:",
            "label:",
            "- label:",
            "usage:",
            "tools/",
            "///",
            "//!",
        )
    )


def exemption(path: str, line: str, reason: str) -> str | None:
    if path in SELF_EXEMPT:
        return SELF_EXEMPT[path]
    if path == "sugar-release.toml" and "target/release/sugar" in line:
        return "shipping manifest declares the release artifact being attested, not a consumer acquisition"
    if path == "examples/forall-vampire-showcase/run.sh" and "--example forall_vampire_fixture" in line:
        return "cargo run builds the fixture generator example, not the sugar CLI"
    if "--example synthetic_rss_fixture" in line:
        return "cargo run builds the RSS fixture generator example, not the sugar CLI"
    if path == ".github/workflows/ci.yml" and "subject-path: implementations/rust/target/release/sugar" in line:
        return "CI attestation names the release artifact subject, not a consumer acquisition"
    if path == "tests/bcargo_remote_root_cleanup.sh" and 'target/debug/sugar' in line:
        return "cleanup test asserts stale remote target removal, not binary acquisition"
    if path.startswith("implementations/rust/sugar-cli/tests/") and "CARGO_BIN_EXE_sugar" in line:
        return "Cargo integration tests exercise the test-built sugar subject binary"
    if path == "implementations/rust/sugar-cli/tests/perf_rss_floor.rs" and "dhat-heap" in line:
        return "test asserts perf documentation text, not an executable acquisition path"
    return None


offenders: list[str] = []
for path in tracked_files():
    path_str = path.as_posix()
    if path_str.startswith(SKIP_PREFIXES):
        continue
    if path.name not in SCAN_NAMES and path.suffix not in SCAN_SUFFIXES:
        continue
    full = ROOT / path
    if not full.is_file():
        continue
    try:
        lines = full.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        continue
    for lineno, line in enumerate(lines, start=1):
        if is_comment(line, path):
            continue
        for pattern, reason in PATTERNS:
            if reason.startswith("bare sugar") and (
                path.suffix not in {".sh", ".yml", ".yaml"} or is_prose_or_label(line)
            ):
                continue
            needle_line = line
            if reason.startswith("bare sugar"):
                needle_line = re.sub(r"\"[^\"]*\"|'[^']*'", "", line)
                before = needle_line.split("sugar", 1)[0]
                if ":" in before:
                    continue
            if not pattern.search(needle_line):
                continue
            if exemption(path_str, line, reason) is not None:
                continue
            offenders.append(f"{path_str}:{lineno}: {reason}: {line.strip()}")

if offenders:
    print("\n".join(offenders))
PY
)"

if [ -n "$binary_offenders" ]; then
  echo "FAIL: sugar binary acquisition must route through bin/sugarbin:" >&2
  echo "$binary_offenders" >&2
  exit 1
fi

echo "PASS: Makefile Cargo commands use the project cargo entrypoints"
echo "PASS: sugar binary acquisition routes through bin/sugarbin"
