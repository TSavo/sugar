#!/usr/bin/env python3
"""Resident process-lifetime ownership census (Lane B instrument).

Law: every process-lifetime owner in the resident Python kit is finite by
construction. Unbounded `lru_cache(maxsize=None)` and `functools.cache`
decorators retain every distinct key for the life of the process; the pandas
wall dies when those maps accumulate.

This instrument names the residue *class*, not one death site. R is the
offender count. Exit 1 while R > 0. The next memory PR's success is ΔR here,
not "the wall got further."

See docs/analysis/ci-whack-a-mole-course-2026-07-15.md.
"""

from __future__ import annotations

import argparse
import ast
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Resident kit surfaces that hold process-lifetime state across RPC generations.
SCAN_ROOTS = (
    ROOT / "implementations/python/sugar-lift-py-tests/src",
    ROOT / "implementations/python/sugar-lift-python-source/src",
)

REPLACEMENT = (
    "bounded LRU (maxsize=N or generation-local), caller-owned tables, "
    "or spill outside the process; never maxsize=None / functools.cache "
    "on process-lifetime keys"
)


@dataclass(frozen=True)
class Offender:
    path: str
    line: int
    name: str
    shape: str

    @property
    def key(self) -> str:
        return f"{self.path}:{self.line}:{self.name}"

    def render(self) -> str:
        return (
            f"  {self.path}:{self.line} {self.name}\n"
            f"    shape: {self.shape}\n"
            f"    replacement: {REPLACEMENT}"
        )


def _repo_relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def _decorator_call(node: ast.AST) -> ast.Call | None:
    if isinstance(node, ast.Call):
        return node
    return None


def _is_lru_cache_func(func: ast.AST) -> bool:
    if isinstance(func, ast.Name) and func.id == "lru_cache":
        return True
    if isinstance(func, ast.Attribute) and func.attr == "lru_cache":
        return True
    return False


def _is_cache_func(func: ast.AST) -> bool:
    if isinstance(func, ast.Name) and func.id == "cache":
        return True
    if isinstance(func, ast.Attribute) and func.attr == "cache":
        # functools.cache, not arbitrary .cache attributes used as non-decorator
        if isinstance(func.value, ast.Name) and func.value.id == "functools":
            return True
        return False
    return False


def _maxsize_is_none(call: ast.Call) -> bool:
    for kw in call.keywords:
        if kw.arg != "maxsize":
            continue
        val = kw.value
        if isinstance(val, ast.Constant) and val.value is None:
            return True
        # Python 3.7 style: NameConstant (not present on 3.12+, still cheap)
        if getattr(val, "value", object()) is None and type(val).__name__ in {
            "NameConstant",
            "Constant",
        }:
            return True
    return False


def _classify_decorator(dec: ast.AST) -> str | None:
    """Return illegal shape string, or None if decorator is not an offender."""
    # Bare @cache / @functools.cache (no call) — functools.cache is unbounded.
    if isinstance(dec, ast.Name) and dec.id == "cache":
        return "functools.cache (unbounded)"
    if isinstance(dec, ast.Attribute) and dec.attr == "cache":
        if isinstance(dec.value, ast.Name) and dec.value.id == "functools":
            return "functools.cache (unbounded)"
        return None

    call = _decorator_call(dec)
    if call is None:
        return None

    if _is_cache_func(call.func):
        return "functools.cache() (unbounded)"

    if _is_lru_cache_func(call.func) and _maxsize_is_none(call):
        return "lru_cache(maxsize=None)"

    return None


def _function_name(node: ast.AST) -> str:
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return node.name
    if isinstance(node, ast.ClassDef):
        return node.name
    return "<unknown>"


def collect_from_source(source: str, path: str) -> list[Offender]:
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return []
    offenders: list[Offender] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        for dec in node.decorator_list:
            shape = _classify_decorator(dec)
            if shape is None:
                continue
            line = getattr(dec, "lineno", node.lineno)
            offenders.append(
                Offender(
                    path=path,
                    line=line,
                    name=_function_name(node),
                    shape=shape,
                )
            )
    return offenders


def collect(scan_roots: tuple[Path, ...] = SCAN_ROOTS) -> list[Offender]:
    offenders: list[Offender] = []
    for root in scan_roots:
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.py")):
            if path.name == "__pycache__":
                continue
            rel = _repo_relative(path)
            text = path.read_text(encoding="utf-8")
            offenders.extend(collect_from_source(text, rel))
    offenders.sort(key=lambda o: (o.path, o.line, o.name))
    return offenders


def report(offenders: list[Offender]) -> int:
    r = len(offenders)
    print("RESIDENT OWNERSHIP CENSUS")
    print(f"R={r} unbounded process-lifetime owners")
    print(
        "class: lru_cache(maxsize=None) | functools.cache on resident kit surfaces"
    )
    print(f"scan: {', '.join(_repo_relative(p) for p in SCAN_ROOTS)}")
    if offenders:
        print("offenders:")
        for item in offenders:
            print(item.render())
        print(
            "FAIL: R must be 0 "
            "(every process-lifetime owner is finite by construction)"
        )
        return 1
    print("PASS: R=0 — no unbounded cache decorators on resident kit surfaces")
    return 0


def self_test() -> int:
    planted = '''
import functools

@functools.lru_cache(maxsize=None)
def planted_unbounded(x):
    return x

@functools.cache
def planted_cache(x):
    return x

@functools.lru_cache(maxsize=64)
def planted_bounded(x):
    return x
'''
    found = collect_from_source(planted, "planted://resident_ownership_tooth.py")
    shapes = {item.shape for item in found}
    names = {item.name for item in found}
    if "planted_unbounded" not in names or "planted_cache" not in names:
        print(
            "FAIL: planted unbounded caches did not trip the census",
            file=sys.stderr,
        )
        return 1
    if "planted_bounded" in names:
        print(
            "FAIL: bounded lru_cache(maxsize=64) was misclassified as unbounded",
            file=sys.stderr,
        )
        return 1
    if not any("maxsize=None" in s for s in shapes):
        print("FAIL: maxsize=None shape missing from planted hit", file=sys.stderr)
        return 1
    if not any("cache" in s for s in shapes):
        print("FAIL: functools.cache shape missing from planted hit", file=sys.stderr)
        return 1

    # Bounded capacity constant must not trip (live tree regression).
    bounded_live = '''
import functools
CAPACITY = 64
@functools.lru_cache(maxsize=CAPACITY)
def ok(x):
    return x
'''
    if collect_from_source(bounded_live, "planted://bounded.py"):
        print(
            "FAIL: maxsize=CAPACITY constant was misclassified as unbounded",
            file=sys.stderr,
        )
        return 1

    # Empty temp tree: R=0 green path.
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "src"
        root.mkdir()
        (root / "ok.py").write_text("def f():\n    return 1\n", encoding="utf-8")
        empty = collect(scan_roots=(root,))
        if empty:
            print("FAIL: empty tree produced offenders", file=sys.stderr)
            return 1

    print("PASS: planted unbounded owners trip the census; bounded sites stay quiet")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit machine-readable offender list on stdout (still exit 1 if R>0)",
    )
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test()

    offenders = collect()
    if args.json:
        import json

        payload = {
            "R": len(offenders),
            "class": "unbounded-resident-cache-decorator",
            "offenders": [
                {
                    "key": o.key,
                    "path": o.path,
                    "line": o.line,
                    "name": o.name,
                    "shape": o.shape,
                    "replacement": REPLACEMENT,
                }
                for o in offenders
            ],
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 1 if offenders else 0
    return report(offenders)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
