#!/usr/bin/env python3
"""R_compatibility_door — Criterion 4 recognition for the unowned shape.

## Definition (this instrument's claim — attack it, do not adopt by habit)

A **compatibility door** is a *second public entry into meaning production*
kept so unmigrated callers still succeed when the sole construction door would
refuse them or redirect them.

It is a shim / legacy accepting branch / second entry point. It is **not**
merely old vocabulary in a comment, and it is **not** every soft path.

### What it is not (owned by other instruments)

| Shape | Owner |
| --- | --- |
| Bare ``SourceFile.from_path`` + ``.sugar()`` without context | ``construction_context_door_law`` |
| Manifest membrane / foreign AST / dual-old-lifter | ``construction_side_door_law`` |
| Private AST evaluator manufacturing floors | ``construction_invariant_law`` SECOND-CONSTRUCTION-PATH |
| Vendor logo dispatch | ``vendor_special_case_law`` |
| Spelling tables / ``func.id`` gates | ``builtin_closed_operation_instrument`` |
| Catch-and-continue / soft Sugar | ``swallowed_throw_second_mechanism_law`` |

Nearest neighbour is the bare construction door. That class is *wrong context
on the one door*. A compatibility door is a *second door* kept for callers who
have not migrated.

### Predicate (both halves required)

An offender is a function definition (or module-level callable alias) that has:

1. **Second-entry marker** — at least one of:
   - a leading comment block immediately above the def (only blanks/comments
     between) matching the marker regexes below;
   - a function name matching ``legacy_`` / ``compat_`` / ``deprecated_``
     prefix or ``_legacy`` / ``_compat`` / ``_deprecated`` suffix;
   - a docstring whose first 400 characters match the marker regexes.

2. **Meaning production** — at least one of:
   - **thin re-export**: body is only pass-through ``return Other(...)`` /
     ``return Other`` / assignments that alias another name (no independent
     construction logic beyond the call);
   - **construction-class call**: body walks to a call of ``sugar``,
     ``from_path``, ``open_source_file_for_construction``, ``force_floor``,
     ``construct_*``, ``build_proof_envelope``, ``reduce_source_outcome``,
     ``to_term``, or attribute tails in ``_MEANING_CALL_TAILS``.

Marker alone is prose. Construction alone is the sole door doing its job.
Both together are the second door.

### Enforcement ladder

Auditor (static AST). Type system cannot forbid "second public entry kept for
unmigrated callers" in open Python. One-door construction helps retire
instances but cannot close the open class of new shims. Retirement: delete the
second entry; migrate callers to the sole door; then this shell sleeps at
stable zero (or is deleted when every production package forbids dual public
entries by construction).

No baseline. Exit 1 while R > 0 or auditor_errors > 0. Zero offenders is a
legitimate green — do not manufacture hits.

Usage::

    python scripts/compatibility_door_law.py
    python scripts/compatibility_door_law.py --python-root PATH
    python scripts/compatibility_door_law.py --self-test
"""

from __future__ import annotations

# Not the board.
SCOREBOARD_AUTHORITY = False

import argparse
import ast
import re
import sys
import tempfile
from pathlib import Path
from typing import NamedTuple, Sequence


class CompatibilityDoorOffender(NamedTuple):
    path: str
    line: int
    axis: str
    kind: str
    name: str
    note: str
    fix: str


_AXES = (
    "R_compat_comment_marked_entry",
    "R_compat_name_marked_entry",
    "R_compat_docstring_marked_entry",
)

_MARKER_RES = (
    re.compile(r"legacy\s+helper", re.I),
    re.compile(r"kept\s+for\s+(backward|backwards)\s+compat", re.I),
    re.compile(r"backward[s]?\s+compatibility\s+with\s+existing", re.I),
    re.compile(r"compatibility\s+(shim|wrapper|adapter|hatch|door)", re.I),
    re.compile(r"deprecated\s*:\s*use\s+\w+\s+instead", re.I),
    re.compile(r"back-?compat\s+alias", re.I),
    re.compile(r"for\s+backward[s]?\s+compatibility\s+with\s+existing\s+callers", re.I),
)

_NAME_PREFIX = re.compile(r"^(legacy_|compat_|deprecated_)", re.I)
_NAME_SUFFIX = re.compile(r"_(legacy|compat|deprecated)$", re.I)

_MEANING_CALL_TAILS = frozenset(
    {
        "sugar",
        "from_path",
        "open_source_file_for_construction",
        "force_floor",
        "build_proof_envelope",
        "reduce_source_outcome",
        "to_term",
        "lift_source",
        "lift_paths",
    }
)

_MEANING_CALL_PREFIXES = (
    "construct_",
    "build_proof",
    "open_source_file",
)

_PRODUCTION_PACKAGE_SRC = (
    "sugar-lift-python-source/src",
    "sugar-source-tree/src",
    "sugar-lift-py-tests/src",
)

_SKIP_DIR_NAMES = frozenset({"__pycache__", ".git", "tests", "vendor"})


def _marker_text_hits(text: str) -> bool:
    return any(rx.search(text) for rx in _MARKER_RES)


def _name_marked(name: str) -> bool:
    return bool(_NAME_PREFIX.search(name) or _NAME_SUFFIX.search(name))


def _call_tail(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _is_meaning_call(node: ast.Call) -> bool:
    tail = _call_tail(node.func)
    if tail in _MEANING_CALL_TAILS:
        return True
    if any(tail.startswith(p) for p in _MEANING_CALL_PREFIXES):
        return True
    # Name form: construct_manager_behavior
    if isinstance(node.func, ast.Name):
        if any(node.func.id.startswith(p) for p in _MEANING_CALL_PREFIXES):
            return True
        if node.func.id in _MEANING_CALL_TAILS:
            return True
    return False


def _body_has_meaning_production(function: ast.AST) -> bool:
    for child in ast.walk(function):
        if isinstance(child, ast.Call) and _is_meaning_call(child):
            return True
    return False


def _is_thin_reexport(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Body only returns another name/call — no independent logic."""
    body = [
        stmt
        for stmt in function.body
        if not (
            isinstance(stmt, ast.Expr)
            and isinstance(stmt.value, ast.Constant)
            and isinstance(stmt.value.value, str)
        )
    ]
    if not body:
        return False
    if len(body) > 2:
        return False
    # allow single import then return
    core = [s for s in body if not isinstance(s, (ast.Import, ast.ImportFrom))]
    if len(core) != 1:
        return False
    stmt = core[0]
    if not isinstance(stmt, ast.Return) or stmt.value is None:
        return False
    value = stmt.value
    if isinstance(value, ast.Name):
        return True
    if isinstance(value, ast.Call):
        # return Other(...) or return Other.method(...)
        return isinstance(value.func, (ast.Name, ast.Attribute))
    return False


_NORMATIVE_PEER = re.compile(
    r"\b(?:use|prefer|call)\s+[`']?([A-Za-z_][A-Za-z0-9_]*)[`']?"
    r".{0,80}\b(?:normative|instead|sole|canonical)\b"
    r"|\b(?:normative|sole|canonical)\b.{0,80}"
    r"\b(?:use|prefer|call)\s+[`']?([A-Za-z_][A-Za-z0-9_]*)[`']?",
    re.I | re.S,
)


def _comment_names_normative_peer(lead: str) -> bool:
    """Comment both marks legacy and points at the sole/normative peer."""
    if not _marker_text_hits(lead):
        return False
    return bool(_NORMATIVE_PEER.search(lead)) or (
        "normative" in lead.lower() and "use " in lead.lower()
    )


def _produces_meaning(
    function: ast.FunctionDef | ast.AsyncFunctionDef, *, lead: str = ""
) -> bool:
    if _is_thin_reexport(function) or _body_has_meaning_production(function):
        return True
    # Declared second to a named normative peer: body may reimplement rather
    # than thin-wrap, but the comment itself admits the dual entry.
    return _comment_names_normative_peer(lead)


def _leading_comment_block(source: str, def_lineno: int) -> str:
    """Comments immediately above ``def`` (1-indexed), stopping at code."""
    lines = source.splitlines()
    idx = def_lineno - 2  # line above def
    collected: list[str] = []
    while idx >= 0:
        raw = lines[idx]
        stripped = raw.strip()
        if stripped == "":
            idx -= 1
            continue
        if stripped.startswith("#"):
            collected.append(stripped.lstrip("#").strip())
            idx -= 1
            continue
        break
    collected.reverse()
    return "\n".join(collected)


def _module_alias_offenders(
    tree: ast.Module, *, path: str, source: str
) -> list[CompatibilityDoorOffender]:
    """Module-level ``legacy_x = real_x`` style second entries."""
    offenders: list[CompatibilityDoorOffender] = []
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        if not _name_marked(target.id):
            # comment above assignment?
            lead = _leading_comment_block(source, node.lineno)
            if not _marker_text_hits(lead):
                continue
            axis = "R_compat_comment_marked_entry"
            kind = "comment-marked-alias"
        else:
            axis = "R_compat_name_marked_entry"
            kind = "name-marked-alias"
        if not isinstance(node.value, (ast.Name, ast.Attribute)):
            continue
        offenders.append(
            CompatibilityDoorOffender(
                path=path,
                line=node.lineno,
                axis=axis,
                kind=kind,
                name=target.id,
                note=(
                    f"module-level alias {target.id!r} is a second public entry "
                    "kept under a compatibility/legacy marker"
                ),
                fix=(
                    "delete the alias; migrate callers to the sole name; "
                    "a second entry is a compatibility door"
                ),
            )
        )
    return offenders


def scan_source(source: str, *, path: str) -> list[CompatibilityDoorOffender]:
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as error:
        return [
            CompatibilityDoorOffender(
                path=path,
                line=int(error.lineno or 0),
                axis="auditor_errors",
                kind="auditor-parse-error",
                name="",
                note=f"ast.parse failed: {error.msg}",
                fix="fix the production source so the auditor can read it",
            )
        ]

    offenders: list[CompatibilityDoorOffender] = []
    offenders.extend(_module_alias_offenders(tree, path=path, source=source))

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        lead = _leading_comment_block(source, node.lineno)
        doc = (ast.get_docstring(node) or "")[:400]
        if not _produces_meaning(node, lead=lead):
            continue

        name_hit = _name_marked(node.name)
        comment_hit = _marker_text_hits(lead)
        doc_hit = _marker_text_hits(doc)

        if not (name_hit or comment_hit or doc_hit):
            continue
        if comment_hit:
            axis = "R_compat_comment_marked_entry"
            kind = "comment-marked-second-entry"
            marker = "leading comment"
        elif name_hit:
            axis = "R_compat_name_marked_entry"
            kind = "name-marked-second-entry"
            marker = f"name {node.name!r}"
        else:
            axis = "R_compat_docstring_marked_entry"
            kind = "docstring-marked-second-entry"
            marker = "docstring"

        thin = _is_thin_reexport(node)
        meaning = "thin re-export" if thin else "meaning-production body"
        offenders.append(
            CompatibilityDoorOffender(
                path=path,
                line=node.lineno,
                axis=axis,
                kind=kind,
                name=node.name,
                note=(
                    f"{marker} marks a second entry ({meaning}) — unmigrated "
                    "callers still obtain meaning the sole door would own alone"
                ),
                fix=(
                    "delete the second entry; migrate callers to the sole door "
                    f"(normative peer of {node.name!r}); never keep a shim"
                ),
            )
        )
    return offenders


def scan_file(path: Path, *, rel: str) -> list[CompatibilityDoorOffender]:
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        return [
            CompatibilityDoorOffender(
                path=rel,
                line=0,
                axis="auditor_errors",
                kind="auditor-read-error",
                name="",
                note=f"could not read source: {error}",
                fix="make the production source readable to the auditor",
            )
        ]
    return scan_source(source, path=rel)


def production_roots(python_root: Path) -> list[tuple[str, Path]]:
    return [(rel, python_root / rel) for rel in _PRODUCTION_PACKAGE_SRC]


def scan_python_root(python_root: Path) -> list[CompatibilityDoorOffender]:
    offenders: list[CompatibilityDoorOffender] = []
    for prefix, root in production_roots(python_root):
        if not root.is_dir():
            offenders.append(
                CompatibilityDoorOffender(
                    path=prefix,
                    line=0,
                    axis="auditor_errors",
                    kind="auditor-root-error",
                    name="",
                    note="scan root is not a directory",
                    fix="restore the production package src tree",
                )
            )
            continue
        try:
            paths = sorted(root.rglob("*.py"))
        except OSError as error:
            offenders.append(
                CompatibilityDoorOffender(
                    path=prefix,
                    line=0,
                    axis="auditor_errors",
                    kind="auditor-root-error",
                    name="",
                    note=f"could not enumerate scan root: {error}",
                    fix="restore the production package src tree",
                )
            )
            continue
        for path in paths:
            if any(part in _SKIP_DIR_NAMES for part in path.parts):
                continue
            if "__pycache__" in path.parts:
                continue
            rel = f"{prefix}/{path.relative_to(root).as_posix()}"
            # Prefer package-relative path for reports
            try:
                rel = path.relative_to(python_root).as_posix()
            except ValueError:
                pass
            offenders.extend(scan_file(path, rel=rel))
    return sorted(offenders, key=lambda o: (o.path, o.line, o.kind, o.name))


def axis_counts(offenders: Sequence[CompatibilityDoorOffender]) -> dict[str, int]:
    counts = {axis: 0 for axis in _AXES}
    counts["auditor_errors"] = 0
    for row in offenders:
        if row.axis == "auditor_errors" or row.kind.startswith("auditor-"):
            counts["auditor_errors"] += 1
        elif row.axis in counts:
            counts[row.axis] += 1
    return counts


def format_report(offenders: Sequence[CompatibilityDoorOffender]) -> str:
    counts = axis_counts(offenders)
    lines = [
        "compatibility_door_law",
        *(f"{axis} = {counts[axis]}" for axis in _AXES),
        f"auditor_errors = {counts['auditor_errors']}",
        "",
        "Replacement: delete the second entry; migrate callers to the sole door.",
        "Marker alone is prose. Construction alone is the sole door. Both = compat door.",
        "",
        "Loci:",
    ]
    if not offenders:
        lines.append("(none)")
    for row in offenders:
        lines.append(
            f"{row.path}:{row.line}:{row.kind} [{row.axis}] name={row.name!r} — "
            f"{row.note} | FIX: {row.fix}"
        )
    return "\n".join(lines)


def discrimination_self_test() -> bool:
    """Planted twins: second entry reds; sole door and prose stay quiet."""
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp) / "python"
        for pkg in _PRODUCTION_PACKAGE_SRC:
            (root / pkg).mkdir(parents=True)
        # Package leaf so the planted module is on the production scan path.
        (root / "sugar-lift-py-tests/src/sugar_lift_py_tests").mkdir(
            parents=True, exist_ok=True
        )

        dirty = root / "sugar-lift-py-tests/src/sugar_lift_py_tests/compat_plant.py"
        dirty.write_text(
            '''
# Legacy helper -- kept for backward compatibility with existing callers.
# Use open_source_file_for_construction for the normative path.
def load_tree(path):
    return open_source_file_for_construction(path)


def legacy_construct(path):
    return SourceFile.from_path(path).sugar()


def only_constructs(path):
    """Normative door — no second-entry marker."""
    return open_source_file_for_construction(path)


# Historical note: the legacy wire field was renamed.
# This is prose, not a second entry.
def project_wire(row):
    return row["exitPartitionArity"]
''',
            encoding="utf-8",
        )

        offenders = scan_python_root(root)
        kinds = {o.kind for o in offenders}
        names = {o.name for o in offenders}
        if "comment-marked-second-entry" not in kinds:
            return False
        if "name-marked-second-entry" not in kinds:
            return False
        if "load_tree" not in names or "legacy_construct" not in names:
            return False
        # Prose + sole door must not red
        if "only_constructs" in names or "project_wire" in names:
            return False
        return True


def default_python_root() -> Path:
    # scripts/ → sugar-lift-py-tests → python/
    return Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--python-root",
        type=Path,
        default=default_python_root(),
        help="implementations/python root",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="planted twins only; exit 0 on discrimination green",
    )
    args = parser.parse_args(argv)
    if args.self_test:
        ok = discrimination_self_test()
        print(
            "compatibility_door_law self-test:",
            "GREEN" if ok else "RED",
            file=sys.stderr,
        )
        return 0 if ok else 1

    offenders = scan_python_root(args.python_root)
    counts = axis_counts(offenders)
    r_total = sum(counts[axis] for axis in _AXES)
    auditor_errors = counts["auditor_errors"]
    print(format_report(offenders))
    if r_total or auditor_errors:
        print(
            f"COMPATIBILITY-DOOR LAW RED: R_total={r_total} "
            f"(axes={ {a: counts[a] for a in _AXES} }) "
            f"auditor_errors={auditor_errors}",
            file=sys.stderr,
        )
        return 1
    print("COMPATIBILITY-DOOR LAW GREEN: all axes 0", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
