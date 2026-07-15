#!/usr/bin/env python3
"""Census: lift launches of the Python kit must wire both packages + --rpc.

Law:
1. Any command that launches `sugar_lift_py_tests.lift_rpc` (or sibling -m
   sugar_lift_py_tests.*) must put `sugar-lift-python-source` on PYTHONPATH.
   `factory/source_fragment.py` imports it at module load; py-tests-only
   PYTHONPATH dies before handshake and cascades into A2 refuse noise.
2. Any `bind_rpc` launch must pass `--rpc` (else usage text breaks the
   declaration handshake JSON).

R = offender count. Exit 1 while R > 0.

See docs/analysis/ci-whack-a-mole-course-2026-07-15.md.
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"

SOURCE_MARK = "sugar-lift-python-source"
LIFT_RPC_MARK = re.compile(
    r"sugar_lift_py_tests\.lift_rpc|sugar_lift_py_tests\.|-\s*m[,\s]+sugar_lift_py_tests"
)
# PYTHONPATH=value, PYTHONPATH="value", PYTHONPATH=$VAR, export PYTHONPATH=...
PYTHONPATH_ASSIGN = re.compile(
    r"""(?:export\s+)?PYTHONPATH=(?:
        "(?P<dquote>[^"]*)"
        |'(?P<squote>[^']*)'
        |(?P<bare>[^\s]+)
    )""",
    re.VERBOSE,
)
# Shell assignment NAME="...sugar-lift-..." (for $PP style indirection)
VAR_ASSIGN = re.compile(
    r'^([A-Za-z_][A-Za-z0-9_]*)=(?P<q>["\'])(?P<body>.*?)(?P=q)\s*$',
    re.MULTILINE,
)
BIND_RPC = re.compile(r"sugar_lift_python_source\.bind_rpc|bind_rpc")
RPC_FLAG = re.compile(r"(?:^|[\s,\"'])--rpc(?:$|[\s,\"'])")


@dataclass(frozen=True)
class Offender:
    path: str
    line: int
    shape: str
    detail: str
    replacement: str

    def render(self) -> str:
        return (
            f"  {self.path}:{self.line} [{self.shape}]\n"
            f"    {self.detail}\n"
            f"    replacement: {self.replacement}"
        )


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def _var_map(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in VAR_ASSIGN.finditer(text):
        out[m.group(1)] = m.group("body")
    return out


def _expand_shell_vars(value: str, vars_: dict[str, str]) -> str:
    """Best-effort expand $NAME / ${NAME} from same-file assignments."""

    def repl(m: re.Match[str]) -> str:
        name = m.group(1) or m.group(2)
        return vars_.get(name, m.group(0))

    return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)", repl, value)


def _pythonpath_covers_source(text: str) -> tuple[bool, int]:
    """Return (ok, locus_line) for PYTHONPATH coverage of sugar-lift-python-source."""
    vars_ = _var_map(text)
    locus = 1
    any_path = False
    for i, line in enumerate(text.splitlines(), start=1):
        for m in PYTHONPATH_ASSIGN.finditer(line):
            any_path = True
            locus = i
            raw = m.group("dquote") or m.group("squote") or m.group("bare") or ""
            expanded = _expand_shell_vars(raw, vars_)
            if SOURCE_MARK in raw or SOURCE_MARK in expanded:
                return True, i
            # Format-string templates like {py_source} used by consumer demos.
            if "py_source" in raw or "python-source" in raw:
                return True, i
    if not any_path:
        return False, locus
    return False, locus


def scan_file(path: Path) -> list[Offender]:
    text = path.read_text(encoding="utf-8", errors="replace")
    offenders: list[Offender] = []

    # 1) lift_rpc launch without source on PYTHONPATH
    if LIFT_RPC_MARK.search(text) and "PYTHONPATH" in text:
        ok, locus = _pythonpath_covers_source(text)
        if not ok:
            offenders.append(
                Offender(
                    path=_rel(path),
                    line=locus,
                    shape="A1/manifest-pythonpath-missing-source",
                    detail=(
                        "launches sugar_lift_py_tests but no PYTHONPATH in this "
                        "file includes sugar-lift-python-source"
                    ),
                    replacement=(
                        "add sugar-lift-python-source/src to every PYTHONPATH "
                        "that runs sugar_lift_py_tests.*"
                    ),
                )
            )

    # 2) bind_rpc without --rpc
    if BIND_RPC.search(text) and "bind_rpc" in text:
        if not RPC_FLAG.search(text):
            locus = 1
            for i, line in enumerate(text.splitlines(), start=1):
                if "bind_rpc" in line:
                    locus = i
                    break
            offenders.append(
                Offender(
                    path=_rel(path),
                    line=locus,
                    shape="A1/bind-rpc-missing-rpc-flag",
                    detail="launches bind_rpc without --rpc (handshake gets usage text)",
                    replacement="append --rpc to the bind_rpc command argv",
                )
            )
    return offenders


def collect() -> list[Offender]:
    offenders: list[Offender] = []
    if not EXAMPLES.is_dir():
        return offenders
    names = {"manifest.toml", "run.sh", "run-logo-receipt.sh", "lift-shim.sh"}
    for path in sorted(EXAMPLES.rglob("*")):
        if not path.is_file() or path.name not in names:
            continue
        offenders.extend(scan_file(path))
    seen: set[tuple[str, str]] = set()
    unique: list[Offender] = []
    for o in offenders:
        key = (o.path, o.shape)
        if key in seen:
            continue
        seen.add(key)
        unique.append(o)
    unique.sort(key=lambda o: (o.path, o.line, o.shape))
    return unique


def report(offenders: list[Offender]) -> int:
    r = len(offenders)
    print("LIFT MANIFEST PYTHONPATH CENSUS")
    print(f"R={r} incomplete kit launch surfaces")
    print(
        "class: sugar_lift_py_tests without sugar-lift-python-source | "
        "bind_rpc without --rpc"
    )
    if offenders:
        print("offenders:")
        for o in offenders:
            print(o.render())
        print(
            "FAIL: R must be 0 "
            "(every Python kit launch can import sugar_lift_python_source "
            "and every bind_rpc speaks --rpc)"
        )
        return 1
    print("PASS: R=0 — Python kit PYTHONPATH and bind_rpc --rpc are complete")
    return 0


def self_test() -> int:
    planted_miss = '''
command = [
    "/usr/bin/env",
    "PYTHONPATH=../../implementations/python/sugar-lift-py-tests/src",
    "python",
    "-m",
    "sugar_lift_py_tests.lift_rpc",
    "--rpc",
]
'''
    planted_ok = '''
command = [
    "/usr/bin/env",
    "PYTHONPATH=../../implementations/python/sugar-lift-py-tests/src:../../implementations/python/sugar-lift-python-source/src",
    "python",
    "-m",
    "sugar_lift_py_tests.lift_rpc",
    "--rpc",
]
'''
    planted_var_ok = '''
PP="$REPO/implementations/python/sugar-lift-python-source/src:$REPO/implementations/python/sugar-lift-py-tests/src"
command = ["env", "PYTHONPATH=$PP", "python", "-m", "sugar_lift_py_tests.lift_rpc", "--rpc"]
'''
    planted_bind = '''
command = ["/usr/bin/env", "python", "-m", "sugar_lift_python_source.bind_rpc"]
'''
    planted_bind_ok = '''
command = ["/usr/bin/env", "python", "-m", "sugar_lift_python_source.bind_rpc", "--rpc"]
'''
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        cases = {
            "miss.toml": (planted_miss, True, False),
            "ok.toml": (planted_ok, False, False),
            "var.sh": (planted_var_ok, False, False),
            "bind.sh": (planted_bind, False, True),
            "bindok.sh": (planted_bind_ok, False, False),
        }
        for name, (body, expect_src, expect_rpc) in cases.items():
            path = root / name
            path.write_text(body, encoding="utf-8")
            found = scan_file(path)
            has_src = any(o.shape.endswith("missing-source") for o in found)
            has_rpc = any(o.shape.endswith("missing-rpc-flag") for o in found)
            if has_src != expect_src or has_rpc != expect_rpc:
                print(
                    f"FAIL: {name}: found={found} expect_src={expect_src} "
                    f"expect_rpc={expect_rpc}",
                    file=sys.stderr,
                )
                return 1
    print("PASS: manifest PYTHONPATH / bind_rpc --rpc census self-test")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        return self_test()
    return report(collect())


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
