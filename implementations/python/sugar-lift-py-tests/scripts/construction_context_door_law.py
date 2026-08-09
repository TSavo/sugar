#!/usr/bin/env python3
"""R_bare_construction_door — construction never enters through the bare door.

``SourceFile.from_path`` builds a tree with **no construction context**. That is
a legitimate door: a roll-call discharge and a parse-only corpus emit use it
correctly.

**CORRECTION — this file used to claim "a demand-table scan ... because none of
them construct". The demand-table scan CONSTRUCTS.**

    mint_prebuilt_demand_table
      -> _preconstruction_demand_rows        lift_rpc.py
      -> _call_contract_demand_rows          lift_rpc.py
      -> authenticated_import_uses           import_binding.py
      -> _run_lexical_import_pass            import_binding.py
      -> SourceFile.__new__ -> materialize_module -> _materialize_module_body
      -> Constant.sugar()

The demand table is what MINTS the construction context, and minting it runs a
lexical import pass that materializes modules, which constructs. **The context
is a PRODUCT of construction, so a TOTAL law is self-contradictory at
bootstrap** -- armed as a total rule it killed the census before seat 1. The
rule below is narrowed accordingly, and the bootstrap's permission is pinned by
its own teeth in ``sugar-source-tree/tests/
test_bootstrap_construction_permission.py`` rather than left to the predicate
happening to exclude ``Constant``.

Constructing through the bare door is a different act, and it fails in **TWO
DISTINCT MODES**. This file used to name only the first, and the word "LIES"
collapsed them:

1. **LOUD OVER-COUNT.** Without a context every ``with`` paints
   ``RuntimeSelectedContextManager`` regardless of resolvability. With a
   testimony reporter seated this is a *named refusal*, not silence -- but it
   is one refusal per ``with``, so the tree answers with a plausible wrong
   NUMBER: false frontier rows, halting at the first ``with``. The phantom is
   in the COUNT, not in the quiet.

2. **SILENT CONSTRUCTION.** With a non-testimony reporter seated there is no
   refusal at all: bare door plus a plain ``CollectingReporter`` constructs
   happily with ``call_occurrence=None``. The production bootstrap is worse
   still -- it seats ``NULL_REPORTER``, which retains nothing, so there is not
   even a registered-without-discharge trace an auditor could find later.

They have different detection stories and different severities, and a law that
names only the first will be read as covering both. The runtime guard
(``Node._require_construction_context``) closes both, because it keys on
**whether a context exists**, never on which reporter happens to be seated.

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

# ---------------------------------------------------------------------------
# DELIBERATE OFFENDERS -- an authenticated predicate, written down
# ---------------------------------------------------------------------------
# A measurement that must EXHIBIT the forbidden door's output has no other way
# to do it: there is no way to show what the bare door produces except to drive
# it. Such a file is an offender on purpose.
#
# This is an allowlist and allowlists are how laws die, so it carries two
# conditions that the rest of this instrument enforces rather than requests:
#
#   * the reason is stated HERE, per entry, in the entry itself -- never a bare
#     path, never "known issue";
#   * a stale entry is LOUD. If an allowlisted file stops existing, or stops
#     being an offender, ``--self-test`` fails. The danger is not the exception;
#     it is the exception outliving its reason and quietly covering a NEW
#     offender that happens to land at the same path.
#
# The failure mode this exists to prevent is someone "fixing" the probe to make
# the law pass. THE FIX DELETES THE EVIDENCE. If one of these files is genuinely
# obsolete, delete the file AND its entry together.
#
# An entry is ``(reason, pending_branch)``. ``pending_branch`` is None for a
# file that is in this tree now. It names a branch when the file is NOT here
# yet, which is a genuinely different fact from "the file is gone" -- one is a
# merge that has not happened, the other is rot. Collapsing them into "missing"
# is the same absence-vs-lookup-failure conflation this whole issue is about,
# committed by the instrument that polices it.
#
# A pending entry reports loudly and does not fail. It cannot rot silently,
# because the moment the branch lands the file EXISTS and the pending marker
# becomes a lie -- which ``stale_allowlist_entries`` then fails on, forcing
# whoever merges to confirm the reason rather than inherit it.
DELIBERATE_OFFENDERS: dict[str, tuple[str, str | None]] = {
    "implementations/python/sugar-lift-py-tests/scripts/"
    "probe_runtime_selected_provenance.py": (
        "Discriminator for #7394: drives .sugar() over a bare from_path tree "
        "BESIDE the production door, because exhibiting the forbidden door's "
        "output is the measurement. Fixing this to satisfy the law would "
        "delete the evidence the law was bought with.",
        "gh/frontier-rts-provenance",
    ),
    "implementations/python/sugar-source-tree/tests/"
    "test_bootstrap_construction_permission.py": (
        "Pins the bootstrap's construction permission (#7396). It drives a bare "
        "tree at a BAIT source containing a With and a Call, to demonstrate that "
        "a consulting kind reaching backend.py:931 would be REFUSED -- the "
        "safety property that makes the isinstance(node.value, Constant) filter "
        "load-bearing for a law stated in another file. Exhibiting the bare "
        "door's behaviour is the measurement; opening through the production "
        "door here would prove nothing, because the whole claim is about what "
        "happens when there is no context.",
        None,
    ),
}


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


def _allowlisted(path: Path, repo_root: Path) -> bool:
    """True when this exact file is a stated deliberate offender."""
    try:
        rel = path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return False
    return rel in DELIBERATE_OFFENDERS


def stale_allowlist_entries(repo_root: Path) -> list[dict]:
    """Entries that no longer name a real offender. A stale exception is LOUD.

    Two ways an entry rots, and both are reported rather than tolerated:

    * the file is GONE -- the exception now covers nothing, and will silently
      cover whatever lands at that path next;
    * the file is CLEAN -- it stopped driving the bare door, so the reason
      recorded here is no longer true of it.

    Neither is fatal to the corpus; both are fatal to the exception.
    """
    stale: list[dict] = []
    for rel, (reason, pending_branch) in sorted(DELIBERATE_OFFENDERS.items()):
        path = repo_root / rel
        if not path.is_file():
            if pending_branch is not None:
                # Expected: the file arrives with its branch. Loud, not fatal.
                print(
                    f"  PENDING {rel}: not in this tree yet, expected from "
                    f"{pending_branch}. Confirm the reason when it merges."
                )
                continue
            stale.append(
                {
                    "path": rel,
                    "reason": reason,
                    "rot": "file does not exist -- delete the entry with it, or "
                    "correct the path. An entry pointing nowhere will cover the "
                    "next file to land there.",
                }
            )
            continue
        if pending_branch is not None:
            stale.append(
                {
                    "path": rel,
                    "reason": reason,
                    "rot": f"marked pending on {pending_branch}, but the file is "
                    f"HERE -- the branch landed. Drop the pending marker and "
                    f"confirm the reason still describes this file, rather than "
                    f"inheriting an exception nobody rechecked.",
                }
            )
            continue
        try:
            found = offenders_in_source(
                path.read_text(encoding="utf-8"), path=str(path)
            )
        except (OSError, UnicodeError, SyntaxError) as error:
            stale.append({"path": rel, "reason": reason, "rot": f"unreadable: {error}"})
            continue
        if not found:
            stale.append(
                {
                    "path": rel,
                    "reason": reason,
                    "rot": "no longer drives the bare door -- the stated reason "
                    "is no longer true of this file, so the exception should go.",
                }
            )
    return stale


def scan_roots(
    roots: Iterable[Path], *, repo_root: Path | None = None
) -> tuple[list[Offender], list[dict]]:
    offenders: list[Offender] = []
    unreadable: list[dict] = []
    root_for_allowlist = repo_root if repo_root is not None else resolve_repo_root()
    for root in roots:
        for path in sorted(root.rglob("*.py")):
            if _allowlisted(path, root_for_allowlist):
                continue
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

    # The allowlist is part of the law, so it is proved like the rest of it.
    for row in stale_allowlist_entries(resolve_repo_root()):
        failures.append(f"stale allowlist entry {row['path']}: {row['rot']}")

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
