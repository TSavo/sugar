#!/usr/bin/env python3
"""R_source_audit_cid_alone_presence — source-audit status never keys by CID alone.

SIN CLUSTER 7: two producers of the source-audit product keyed presence by
CID alone while ``MinorityReport`` partitions by
``(file, line, col, kind, cid)``. Equal source text seals to one CID at
distinct loci; those seats are distinct obligations. CID-alone status promotes
every seat that shares a present CID to Blue while ``report.R`` still counts
the absent seat — ``warranted + R`` can exceed ``source_loci``, and Yellow
silently becomes Blue.

**THE LAW.** Production code that derives source-audit ``warranted`` /
``unresolved`` status from a set of present CIDs (or from ``entry.cid in
present_*`` without the full roll-call coordinate) is an offender. The one
door is ``source_audit_from_report`` (full-tuple presence).

Rung: **auditor** — the domain is open Python that can re-derive the product
inline; the type system cannot close free dict construction of wire rows.
Retirement path: if source-audit totals become fields of a single typed
partition value whose constructors only accept full-tuple present keys, this
auditor deletes itself.

No baseline, no threshold, no allowlist. Exit 1 while R > 0.

    python scripts/source_audit_presence_identity_law.py [ROOT ...]
    python scripts/source_audit_presence_identity_law.py --self-test
"""

from __future__ import annotations

# Not the board. This module measures its own named denominator.
SCOREBOARD_AUTHORITY = False

import argparse
import ast
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class Offender:
    path: str
    line: int
    kind: str
    expression: str

    def to_json(self) -> dict:
        return {
            "path": self.path,
            "line": self.line,
            "kind": self.kind,
            "expression": self.expression,
            "law": "source-audit presence never keys by CID alone",
            "fix": (
                "route through source_audit_from_report(report, file_rel); "
                "key presence by (file, line, col, kind, cid) — the same "
                "tuple MinorityReport uses"
            ),
            "retirement": (
                "typed partition value whose constructors only accept "
                "full-tuple present keys makes this auditor deletable"
            ),
        }


def _expr_text(node: ast.AST, source: str) -> str:
    try:
        return ast.get_source_segment(source, node) or ast.dump(node)
    except Exception:
        return ast.dump(node)


def _is_cid_attr(node: ast.AST) -> bool:
    return isinstance(node, ast.Attribute) and node.attr == "cid"


def _comp_targets_cid_from_present(node: ast.AST) -> bool:
    """``{e.cid for e in report.present}`` / ``{entry.cid for entry in ...present}``."""
    if not isinstance(node, (ast.SetComp, ast.ListComp, ast.GeneratorExp)):
        return False
    if not _is_cid_attr(node.elt):
        return False
    for gen in node.generators:
        # iter ends with .present (Name.present or Attribute.present)
        it = gen.iter
        if isinstance(it, ast.Attribute) and it.attr == "present":
            return True
        if isinstance(it, ast.Name) and it.id in {"present", "present_nodes"}:
            return True
    return False


def _assigns_present_cids(node: ast.AST) -> bool:
    if not isinstance(node, ast.Assign):
        return False
    for target in node.targets:
        if isinstance(target, ast.Name) and (
            target.id == "present_cids"
            or target.id.endswith("_cids")
            and "present" in target.id
        ):
            if _comp_targets_cid_from_present(node.value):
                return True
            # set([...]) wrapping a gen
            if (
                isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Name)
                and node.value.func.id == "set"
                and node.value.args
                and _comp_targets_cid_from_present(node.value.args[0])
            ):
                return True
    return False


def _status_by_cid_membership(node: ast.AST) -> bool:
    """``"warranted" if entry.cid in present_cids else "unresolved"`` shapes."""
    if not isinstance(node, ast.IfExp):
        return False
    # body/orelse string constants warranted/unresolved
    strings: set[str] = set()
    for arm in (node.body, node.orelse):
        if isinstance(arm, ast.Constant) and isinstance(arm.value, str):
            strings.add(arm.value)
    if not {"warranted", "unresolved"}.issubset(strings):
        return False
    test = node.test
    # entry.cid in something
    if isinstance(test, ast.Compare) and len(test.ops) == 1 and isinstance(
        test.ops[0], ast.In
    ):
        left = test.left
        if _is_cid_attr(left):
            return True
        # negated: entry.cid not in ...
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        inner = test.operand
        if (
            isinstance(inner, ast.Compare)
            and len(inner.ops) == 1
            and isinstance(inner.ops[0], ast.In)
            and _is_cid_attr(inner.left)
        ):
            return True
    return False


def offenders_in_source(text: str, *, path: str) -> list[Offender]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        raise
    found: list[Offender] = []
    for node in ast.walk(tree):
        if _assigns_present_cids(node):
            found.append(
                Offender(
                    path=path,
                    line=getattr(node, "lineno", 0),
                    kind="present-cids-set",
                    expression=_expr_text(node, text),
                )
            )
        if _status_by_cid_membership(node):
            found.append(
                Offender(
                    path=path,
                    line=getattr(node, "lineno", 0),
                    kind="status-by-cid-membership",
                    expression=_expr_text(node, text),
                )
            )
        # bare setcomp of .cid from present not only in assign (e.g. inline)
        if _comp_targets_cid_from_present(node) and not isinstance(
            getattr(node, "parent", None), ast.Assign
        ):
            # avoid double-counting when parent assign already caught
            parent_is_assign_value = False
            # walk doesn't give parent; re-check: if this node is value of an
            # Assign we already emit present-cids-set. Detect via enclosing:
            # skip if any Assign in walk has this as value — done below by
            # only emitting setcomp when not under Assign we already flag.
            pass
    # Second pass: standalone setcomps of present CIDs used anywhere
    for node in ast.walk(tree):
        if not _comp_targets_cid_from_present(node):
            continue
        # Skip if this exact node is the value of an Assign we already flagged
        already = any(
            o.line == getattr(node, "lineno", 0) and o.kind == "present-cids-set"
            for o in found
        )
        if already:
            continue
        # Only flag if this appears as a set() arg or bare setcomp assigned
        # — covered by assign. For bare setcomp as RHS of Assign of other
        # names, _assigns_present_cids may miss; catch generic present.cid set:
        found.append(
            Offender(
                path=path,
                line=getattr(node, "lineno", 0),
                kind="present-cid-setcomp",
                expression=_expr_text(node, text),
            )
        )
    # Dedup by (line, kind)
    uniq: dict[tuple[int, str], Offender] = {}
    for o in found:
        uniq[(o.line, o.kind)] = o
    return sorted(uniq.values(), key=lambda o: (o.line, o.kind))


def scan_roots(roots: Iterable[Path]) -> tuple[list[Offender], list[dict]]:
    """Scan production packages only (src trees), not tests/scripts/docs."""
    offenders: list[Offender] = []
    unreadable: list[dict] = []
    skip_parts = {
        "tests",
        "scripts",
        "measurements",
        ".git",
        "__pycache__",
        "vendor",
        "site-packages",
    }
    for root in roots:
        root = root.resolve()
        for path in sorted(root.rglob("*.py")):
            parts = set(path.parts)
            if parts & skip_parts:
                continue
            # production src only when under a package src/
            if "src" not in path.parts:
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
# Historical twins — the shapes SIN CLUSTER 7 actually shipped
# ---------------------------------------------------------------------------

HISTORICAL_LIFT_RPC_CID_ALONE = '''
def _roll_call_audit_leaf(full_path, file_rel):
    report = discharge(source_file)
    present_cids = {entry.cid for entry in report.present}
    loci = [
        {
            "status": "warranted" if entry.cid in present_cids else "unresolved",
            "kind": entry.kind,
            "source_cid": entry.cid,
        }
        for entry in report.roster
    ]
    warranted = sum(row["status"] == "warranted" for row in loci)
    source_audit = {
        "totals": {
            "source_loci": len(loci),
            "source_warranted": warranted,
            "source_unresolved": report.R,
        },
    }
    return source_audit
'''

HISTORICAL_TREE_ENUMERATE_CID_ALONE = '''
def source_audit_from_roll_call(full_path, file_rel):
    report = discharge(sf)
    present_cids = {e.cid for e in report.present}
    loci = []
    for entry in report.roster:
        status = "warranted" if entry.cid in present_cids else "unresolved"
        loci.append({"status": status, "source_cid": entry.cid})
    warranted = sum(1 for locus in loci if locus["status"] == "warranted")
    unresolved = len(loci) - warranted
    return {"loci": loci, "totals": {"source_warranted": warranted, "source_unresolved": unresolved}}
'''

PRODUCTION_ONE_DOOR = '''
def source_audit_from_report(report, file_rel):
    present_keys = {_roll_call_identity(entry) for entry in report.present}
    loci = []
    for entry in report.roster:
        status = (
            "warranted" if _roll_call_identity(entry) in present_keys else "unresolved"
        )
        loci.append({"status": status})
    return {"loci": loci}

def _roll_call_audit_leaf(full_path, file_rel):
    report = discharge(source_file)
    source_audit = source_audit_from_report(report, file_rel)
    return source_audit
'''


def self_test() -> int:
    failures: list[str] = []

    def expect(label: str, source: str, *, min_offenders: int) -> None:
        found = offenders_in_source(source, path=f"<{label}>")
        if len(found) < min_offenders:
            failures.append(
                f"{label}: expected >= {min_offenders} offenders, got "
                f"{[(o.kind, o.line) for o in found]}"
            )

    def expect_clean(label: str, source: str) -> None:
        found = offenders_in_source(source, path=f"<{label}>")
        if found:
            failures.append(
                f"{label}: expected clean, got {[(o.kind, o.line) for o in found]}"
            )

    expect("historical lift_rpc CID-alone", HISTORICAL_LIFT_RPC_CID_ALONE, min_offenders=2)
    expect(
        "historical tree_enumerate CID-alone",
        HISTORICAL_TREE_ENUMERATE_CID_ALONE,
        min_offenders=2,
    )
    expect_clean("production one door", PRODUCTION_ONE_DOOR)

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

    default_root = Path(__file__).resolve().parents[1]  # sugar-lift-py-tests
    roots = args.roots or [default_root]
    offenders, unreadable = scan_roots(roots)
    report = {
        "law": "R_source_audit_cid_alone_presence",
        "R": len(offenders),
        "offenders": [o.to_json() for o in offenders],
        "unreadable": unreadable,
        "retirement": (
            "typed partition value whose constructors only accept full-tuple "
            "present keys"
        ),
    }
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"R_source_audit_cid_alone_presence = {len(offenders)}")
        for o in offenders:
            print(f"  {o.path}:{o.line} [{o.kind}] {o.expression!r:.120}")
        for row in unreadable:
            print(f"  UNREADABLE {row['path']}: {row['reason']}")
    return 1 if offenders or unreadable else 0


if __name__ == "__main__":
    raise SystemExit(main())
