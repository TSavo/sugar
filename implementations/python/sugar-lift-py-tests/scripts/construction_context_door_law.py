#!/usr/bin/env python3
"""R_bare_construction_door — construction never enters through the bare door.

``SourceFile.from_path`` builds a tree with **no construction context**. That is
a legitimate door: a demand-table scan, a roll-call discharge, a parse-only
corpus emit all use it correctly, because none of them construct sugar.

Constructing through it is a different act, and it does not fail — it LIES.
Without a context every ``with`` paints ``RuntimeSelectedContextManager``
regardless of resolvability, so the tree answers every question with a plausible
wrong number instead of a refusal.

That door has manufactured a false frontier three times:

1. The old census used it and reported ``With 4125 assertion / 811 resource``
   sites. Measured through the production door, whole-corpus construction R is
   **4**. Two owners worked against the phantom for hours.
2. A scoreboard repair found ``census.py`` still on it -- and the backend-defect
   tooth written to catch that was itself patching ``SourceFile.from_path``, a
   door that code path no longer called, so the tooth would have gone green
   measuring nothing.
3. ``panic_probe.py`` (this instrument's own author, tonight) reported eleven
   residual floor pairs. Five were artifacts of the door: three ``ground_*``
   rows it manufactured outright, and two ``attribute`` rows wrongly declared
   blocked behind them.

Three phantoms, one door, and the defence was a comment reading
``# Production door: never a bare SourceFile.from_path``. Prose is the bottom
rung of the enforcement ladder. This is the next rung up.

**THE LAW.** Within one scope, obtaining a ``SourceFile`` from the bare door and
then driving ``.sugar()`` is an offender. Both halves are required:

* ``SourceFile.from_path`` alone is fine -- that is the door working.
* ``.sugar()`` alone is fine -- the file came from somewhere else.
* Together in one scope, construction is being driven over a tree that has no
  context to construct against.

Scope granularity is the FUNCTION, never the module. A module-level rule reads
one layer too shallow and produces a false population: ``lift_rpc`` calls the
bare door in a demand scan and in a roll-call discharge, and calls ``.sugar()``
in unrelated functions elsewhere. Those are correct uses, and a law that named
them would be allowlisted within a week -- which is how a law dies.

The replacement is ``open_source_file_for_construction(path, root=...)``, which
threads the construction context and the locus root together.

No baseline, no threshold, no allowlist. Exit 1 while R > 0.

    python scripts/construction_context_door_law.py [ROOT ...]
    python scripts/construction_context_door_law.py --self-test
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


from sugar_lift_py_tests.repo_root import resolve_repo_root

BARE_DOOR = "from_path"
BARE_DOOR_OWNER = "SourceFile"
CONSTRUCTION_DRIVER = "sugar"


@dataclass(frozen=True)
class Offender:
    path: str
    scope: str
    door_lines: tuple[int, ...]
    construction_lines: tuple[int, ...]

    def to_json(self) -> dict:
        return {
            "path": self.path,
            "scope": self.scope,
            "doorLines": list(self.door_lines),
            "constructionLines": list(self.construction_lines),
            "law": "construction never enters through the bare door",
            "fix": (
                "open_source_file_for_construction(path, root=<corpus root>) --"
                " it threads the construction context and the locus root"
            ),
        }


def _own_statements(scope: ast.AST) -> Iterable[ast.AST]:
    """Nodes belonging to this scope, excluding nested function bodies.

    A nested function is its own scope and is judged separately, so an outer
    function is never blamed for what an inner one does (or credited with it).
    """
    nested: set[int] = set()
    for node in ast.walk(scope):
        if node is scope:
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            nested.update(id(inner) for inner in ast.walk(node))
    for node in ast.walk(scope):
        if node is not scope and id(node) not in nested:
            yield node


def offenders_in_source(text: str, *, path: str) -> list[Offender]:
    """Every scope that reaches the bare door and then constructs."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        # A file this instrument cannot parse is not silently clean. The caller
        # reports it as its own row; it is never counted as R=0.
        raise
    found: list[Offender] = []
    scopes: list[ast.AST] = [tree]
    scopes.extend(
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    )
    for scope in scopes:
        door: list[int] = []
        construction: list[int] = []
        for node in _own_statements(scope):
            if not isinstance(node, ast.Call) or not isinstance(
                node.func, ast.Attribute
            ):
                continue
            attribute = node.func
            if (
                attribute.attr == BARE_DOOR
                and isinstance(attribute.value, ast.Name)
                and attribute.value.id == BARE_DOOR_OWNER
            ):
                door.append(node.lineno)
            elif attribute.attr == CONSTRUCTION_DRIVER:
                construction.append(node.lineno)
        if door and construction:
            found.append(
                Offender(
                    path=path,
                    scope=getattr(scope, "name", "<module>"),
                    door_lines=tuple(sorted(door)),
                    construction_lines=tuple(sorted(construction)),
                )
            )
    return found


def scan_roots(roots: Iterable[Path]) -> tuple[list[Offender], list[dict]]:
    offenders: list[Offender] = []
    unreadable: list[dict] = []
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as error:
                unreadable.append({"path": str(path), "reason": str(error)})
                continue
            try:
                offenders.extend(offenders_in_source(text, path=str(path)))
            except SyntaxError as error:
                unreadable.append({"path": str(path), "reason": f"syntax: {error}"})
    return offenders, unreadable


# ---------------------------------------------------------------------------
# self-test: the law proved on the incident it exists to prevent
# ---------------------------------------------------------------------------

HISTORICAL_PROBE = """
def main() -> int:
    path = Path(sys.argv[1])
    root = Path(sys.argv[2])
    from sugar_lift_py_tests.desugar_axis import DesugarAxis
    from sugar_source_tree.tree import SourceFile
    rel = str(path.relative_to(root))
    desugar = DesugarAxis()
    reporter = CollectingReporter()
    sf = SourceFile.from_path(str(path), reporter=reporter)
    for fn in sf.functions():
        try:
            sugar = fn.sugar()
        except SugarNotWritten:
            sugar = None
        if sugar is not None:
            desugar.measure(sugar, where=rel)
    return 0
"""

PRODUCTION_DOOR = """
def main() -> int:
    sf = open_source_file_for_construction(path, root=root, reporter=reporter)
    for fn in sf.functions():
        fn.sugar()
    return 0
"""

DEMAND_SCAN_ONLY = """
def demand_rows(root):
    for path in SourceTree(root).paths():
        source_file = SourceFile.from_path(path)
        for node in source_file.nodes():
            rows.append(node)
    return rows
"""

CONSTRUCTION_ONLY = """
def measure(source_file):
    for fn in source_file.functions():
        fn.sugar()
"""

NESTED_SCOPES = """
def outer(path):
    source_file = SourceFile.from_path(path)
    def inner(other):
        other.sugar()
    return source_file, inner
"""


def self_test() -> int:
    """Prove the law fires on the real incident and stays quiet on correct use."""
    failures: list[str] = []

    def expect(label: str, source: str, *, offends: bool) -> None:
        found = offenders_in_source(source, path=f"<{label}>")
        if bool(found) is not offends:
            failures.append(
                f"{label}: expected {'an offender' if offends else 'clean'}, "
                f"got {[o.scope for o in found]}"
            )

    # THE incident. Not a synthetic stand-in: this is the shape of the probe
    # that produced five withdrawn residual pairs.
    expect("historical panic_probe", HISTORICAL_PROBE, offends=True)
    expect("production door", PRODUCTION_DOOR, offends=False)
    expect("demand scan, no construction", DEMAND_SCAN_ONLY, offends=False)
    expect("construction, no bare door", CONSTRUCTION_ONLY, offends=False)
    # The outer scope opens the door; only the INNER scope constructs. Blaming
    # the outer one would be the module-level granularity error in miniature.
    expect("nested scopes", NESTED_SCOPES, offends=False)

    for line in failures:
        print(f"SELF-TEST FAIL {line}")
    print(f"self-test: {'FAIL' if failures else 'PASS'} ({len(failures)} failures)")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roots", nargs="*", type=Path)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test()

    roots = args.roots or [(resolve_repo_root() / "implementations")]
    offenders, unreadable = scan_roots(roots)
    report = {
        "law": "R_bare_construction_door",
        "R": len(offenders),
        "offenders": [offender.to_json() for offender in offenders],
        "unreadable": unreadable,
    }
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"R_bare_construction_door = {len(offenders)}")
        for offender in offenders:
            print(
                f"  {offender.path}:{offender.door_lines[0]} "
                f"{offender.scope}() constructs at {offender.construction_lines}"
            )
        for row in unreadable:
            print(f"  UNREADABLE {row['path']}: {row['reason']}")
    return 1 if offenders or unreadable else 0


if __name__ == "__main__":
    raise SystemExit(main())
