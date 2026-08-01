#!/usr/bin/env python3
"""Law-of-One parent R vector — live offender set, not a sin checklist.

CLASS NAME
    LAW-OF-ONE VIOLATION (parent)

DEFINITION
    The Law of One: there is exactly one way to produce a given kind of meaning
    in the system — AST tree shadows for temporal rewrite/tree mods, Sugar for
    meaning. Every other mechanism is a second door, a fabricated meaning, or a
    soft half-write.

    This instrument does NOT carry a curated list of sites. It structurally
    recognizes the live offender *classes* we keep rediscovering under new
    names, reports R per axis separately (AGENTS.md: keep axes separate), prints
    each offender with a replacement plan, and exits red while any axis R > 0.

AXES (separate R; never sum into a single "32 sins" threshold)

1. FABRICATED-MEANING
   Meaning minted outside its owner. Canonical plant: ``MatchDecided(False)``
   outside the authenticated matcher (deciding a settled miss without routing
   through identity/MRO testimony). Generalized: ``MatchDecided`` constructed
   with a constant False, or Incomplete/Complete(None) manufactured as a
   benign stand-in for an unwritten decision.

2. SPELLING-DISPATCH
   Semantic gate or route keyed by vendor/package *spelling* (string compare to
   ``pytest.raises``, ``pandas.*``, overload name tables) rather than an
   authenticated coordinate/CID/binding.

3. SWALLOWED-THROW
   ``except`` that soft-continues: pass, continue, return None/(), or empty
   body without re-raise — half-writing absence. Includes bare except and
   Exception/BaseException soft membranes in production sources.

4. NAMELESS-IDENTITY
   Authenticated exceptional identity promised but un-named: RaiseEffect
   construction without exception_type_coordinate, or keyword
   ``exception_type_coordinate=None`` / ``occurrence=None`` at a mint site.

5. TWO-PRODUCERS
   A second production door for a fact that already has an owner. Here:
   ``MatchDecided(...)`` mints outside the closed owner set (authenticated
   matcher + the one bare-except True path in try_sugar). Two doors for one
   match fact.

6. SELF-SEALING-INSTRUMENT
   Unfalsifiable teeth / checker-synthesized evidence. Owned by
   ``self_sealing_instrument_law.py`` (#6958). This parent vector *cites* that
   instrument as the axis owner and folds its live findings into the report
   without re-implementing the class.

ENFORCEMENT LADDER (per axis — every instrument should climb and retire)

| Axis | Current rung | Retirement hatch |
| --- | --- | --- |
| FABRICATED-MEANING | auditor | Seal MatchDecided construction to one module/type; False miss unwritable outside matcher |
| SPELLING-DISPATCH | auditor | All gates take authenticated coordinates; string vendor keys do not type-check |
| SWALLOWED-THROW | auditor | Typed effect membrane; bare soft-except unwritable; panic on ConstructionPanic outside audit |
| NAMELESS-IDENTITY | auditor | RaiseEffect requires non-Optional identity fields; None unconstructable |
| TWO-PRODUCERS | auditor | One public mint door (Factory/Visitor); second Call site is a visibility/type error |
| SELF-SEALING | auditor | See self_sealing_instrument_law retire_when |

Not the board. Sole Python corpus scoreboard: scripts/control_effect_recensus.py.
"""

from __future__ import annotations

# Not the board.
SCOREBOARD_AUTHORITY = False

import argparse
import ast
import importlib.util
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

# --- axis ids (stable names for R axes) --------------------------------------

FABRICATED = "FABRICATED-MEANING"
SPELLING = "SPELLING-DISPATCH"
SWALLOWED = "SWALLOWED-THROW"
NAMELESS = "NAMELESS-IDENTITY"
TWO_PRODUCERS = "TWO-PRODUCERS"
SELF_SEALING = "SELF-SEALING-INSTRUMENT"

AXES = (
    FABRICATED,
    SPELLING,
    SWALLOWED,
    NAMELESS,
    TWO_PRODUCERS,
    SELF_SEALING,
)

REQUIRED_FIX = {
    FABRICATED: (
        "route the decision through the single owner (authenticated matcher / "
        "Sugar recognition); never mint MatchDecided(False) or a benign "
        "Complete(None) as a stand-in for an unwritten decision. Replacement: "
        "MatchRetained / typed effect / write the Sugar arm."
    ),
    SPELLING: (
        "resolve via authenticated binding/contract coordinate (CID, definition "
        "memento, typed identity); delete string compares and spelling tables "
        "that grant semantic membership."
    ),
    SWALLOWED: (
        "re-raise, panic, or emit a named typed gap row; never pass/continue/"
        "return None after except. Soft absence is a second mechanism for 'no fact'."
    ),
    NAMELESS: (
        "require exception_type_coordinate and occurrence at RaiseEffect mint; "
        "pin the authenticated identity term. None is not an authenticated exit."
    ),
    TWO_PRODUCERS: (
        "delete the second mint door; all MatchDecided production routes through "
        "the closed owner set (authenticated_exception_matching + the one "
        "sanctioned bare-except True path). One fact, one producer."
    ),
    SELF_SEALING: (
        "see self_sealing_instrument_law: delete checker-synthesized evidence, "
        "tautological asserts, and presence-only identity teeth; pin Eq values."
    ),
}

RUNG = {axis: "auditor" for axis in AXES}

RETIRE_WHEN = {
    FABRICATED: (
        "MatchDecided is constructible only inside authenticated_exception_matching "
        "(visibility or factory door); constant-False miss unwritable elsewhere"
    ),
    SPELLING: (
        "gate APIs accept only authenticated coordinates; str vendor keys rejected "
        "at the type/constructor boundary"
    ),
    SWALLOWED: (
        "soft except→continue/None is a type error or linter-panic; ConstructionPanic "
        "catch closed to audit membranes by type"
    ),
    NAMELESS: (
        "RaiseEffect.exception_type_coordinate: Term (non-Optional); None does not parse"
    ),
    TWO_PRODUCERS: (
        "single module-private constructor for MatchDecided; other packages cannot import mint"
    ),
    SELF_SEALING: (
        "sealed evidence mints + typed assert_identity(Eq) + tautology-rejecting assert macro"
    ),
}

# MatchDecided owners (path suffix). True/False both counted for TWO_PRODUCERS;
# constant False outside authenticated matcher is also FABRICATED-MEANING.
_MATCH_DECIDED_OWNERS = frozenset(
    {
        "authenticated_exception_matching.py",
        # bare-except over a real RaiseEffect may return MatchDecided(True) only
        "try_sugar.py",
    }
)
_MATCH_FALSE_OWNERS = frozenset({"authenticated_exception_matching.py"})

_FORBIDDEN_SPELLING = re.compile(
    r"(^|[.:/_-])(pytest|pandas|numpy|pyarrow|matplotlib|contextlib)([.:/_-]|$)",
    re.IGNORECASE,
)
_FORBIDDEN_API_NAMES = frozenset(
    {
        "row_for_spelling",
        "default_community_manifest",
        "manifest_membrane",
        "community_context_managers",
        "overload_name",
        "by_name",
    }
)

_SOFT_HANDLER_MARKERS = frozenset({"pass", "continue", "None", "Ellipsis"})


@dataclass(frozen=True, order=True)
class Finding:
    path: str
    line: int
    column: int
    axis: str
    observed: str

    @property
    def required_fix(self) -> str:
        return REQUIRED_FIX[self.axis]

    @property
    def rung(self) -> str:
        return RUNG[self.axis]

    @property
    def retire_when(self) -> str:
        return RETIRE_WHEN[self.axis]

    def to_value(self) -> dict[str, object]:
        return {
            "path": self.path,
            "line": self.line,
            "column": self.column,
            "axis": self.axis,
            "observed": self.observed,
            "requiredFix": self.required_fix,
            "rung": self.rung,
            "retireWhen": self.retire_when,
        }


def _unparse(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:  # noqa: BLE001
        return type(node).__name__


def _call_tail(node: ast.AST) -> str:
    if not isinstance(node, ast.Call):
        return ""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _path_basename(path: str) -> str:
    return Path(path).name


def _is_false_constant(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value is False


def _is_none_constant(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _handler_is_soft(handler: ast.ExceptHandler) -> bool:
    """Soft if body only continues/pass/returns None/() without raise."""
    body = handler.body
    if not body:
        return True
    # pure re-raise is hard (honorable)
    if len(body) == 1 and isinstance(body[0], ast.Raise):
        return False
    soft_only = True
    saw_raise = False
    for stmt in body:
        if isinstance(stmt, ast.Raise):
            saw_raise = True
            soft_only = False
            continue
        if isinstance(stmt, ast.Pass):
            continue
        if isinstance(stmt, ast.Continue):
            continue
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            # docstring / ellipsis
            if stmt.value.value is Ellipsis or isinstance(stmt.value.value, str):
                continue
        if isinstance(stmt, ast.Return):
            if stmt.value is None or _is_none_constant(stmt.value):
                continue
            if isinstance(stmt.value, (ast.Tuple, ast.List)) and not stmt.value.elts:
                continue
            # return of something else — may be recovery object (still soft)
            continue
        if isinstance(stmt, ast.Assign):
            # fn = None soft assign
            if _is_none_constant(stmt.value):
                continue
            soft_only = False
            break
        # anything else (append gap, log, call) — treat as possibly loud membrane
        soft_only = False
        break
    if saw_raise and not soft_only:
        # mixed: has raise somewhere — not pure soft
        return False
    return soft_only


def _except_type_is_broad(handler: ast.ExceptHandler) -> bool:
    if handler.type is None:
        return True
    names: set[str] = set()

    def walk(node: ast.AST) -> None:
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Tuple):
            for elt in node.elts:
                walk(elt)

    walk(handler.type)
    return bool(names & {"Exception", "BaseException", "OSError", "ValueError", "ExceptionGroup"}) or handler.type is None


def scan_python_source(source: str, path: str) -> list[Finding]:
    """Structural recognition of Law-of-One axes in one module (no curated sites)."""
    tree = ast.parse(source, filename=path)
    findings: list[Finding] = []
    base = _path_basename(path)

    # Skip this parent instrument and the self-sealing shell (they document shapes).
    if base in {
        "law_of_one_vector_law.py",
        "self_sealing_instrument_law.py",
        "construction_invariant_law.py",
        "construction_panic_catch_law.py",
        "enumeration_binding_soft_skip_law.py",
    }:
        return []

    for node in ast.walk(tree):
        # --- FABRICATED-MEANING + TWO-PRODUCERS via MatchDecided -------------
        if isinstance(node, ast.Call) and _call_tail(node) == "MatchDecided":
            arg0 = node.args[0] if node.args else None
            is_false = arg0 is not None and _is_false_constant(arg0)
            if is_false and base not in _MATCH_FALSE_OWNERS:
                findings.append(
                    Finding(
                        path,
                        node.lineno,
                        node.col_offset,
                        FABRICATED,
                        f"MatchDecided(False) outside authenticated matcher "
                        f"({base}); settled miss must not be minted here",
                    )
                )
            if base not in _MATCH_DECIDED_OWNERS:
                findings.append(
                    Finding(
                        path,
                        node.lineno,
                        node.col_offset,
                        TWO_PRODUCERS,
                        f"MatchDecided mint in {base}; owners are "
                        f"{sorted(_MATCH_DECIDED_OWNERS)}",
                    )
                )

        # Complete(None) / return Complete(None) as fabricated completion
        if isinstance(node, ast.Call) and _call_tail(node) == "Complete":
            if node.args and _is_none_constant(node.args[0]):
                findings.append(
                    Finding(
                        path,
                        node.lineno,
                        node.col_offset,
                        FABRICATED,
                        "Complete(None) manufactures a completed value for absence",
                    )
                )

        # --- SPELLING-DISPATCH -----------------------------------------------
        if isinstance(node, ast.Name) and node.id in _FORBIDDEN_API_NAMES:
            findings.append(
                Finding(
                    path,
                    node.lineno,
                    node.col_offset,
                    SPELLING,
                    f"spelling-authority name `{node.id}`",
                )
            )
        if isinstance(node, ast.Attribute) and node.attr in _FORBIDDEN_API_NAMES:
            findings.append(
                Finding(
                    path,
                    node.lineno,
                    node.col_offset,
                    SPELLING,
                    f"spelling-authority attribute `{node.attr}`",
                )
            )
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _FORBIDDEN_SPELLING.search(node.value) and _in_compare_or_key(node, tree):
                findings.append(
                    Finding(
                        path,
                        node.lineno,
                        node.col_offset,
                        SPELLING,
                        f"semantic gate / key literal {node.value!r}",
                    )
                )

        # --- SWALLOWED-THROW -------------------------------------------------
        if isinstance(node, ast.ExceptHandler) and _handler_is_soft(node):
            # Restrict to production-ish modules: under src/, not tests/
            if "/tests/" in path.replace("\\", "/") or path.startswith("tests/"):
                pass  # tests may soft-catch for harness; still count production
            else:
                if _except_type_is_broad(node) or handler_catches_named_gap(node):
                    findings.append(
                        Finding(
                            path,
                            node.lineno,
                            node.col_offset,
                            SWALLOWED,
                            f"soft except ({_unparse(node.type) if node.type else 'bare'}) "
                            f"→ pass/continue/return-None without re-raise",
                        )
                    )

        # --- NAMELESS-IDENTITY -----------------------------------------------
        if isinstance(node, ast.Call) and _call_tail(node) == "RaiseEffect":
            kw = {k.arg: k.value for k in node.keywords if k.arg}
            # no exception_type_coordinate keyword and no positional story
            if "exception_type_coordinate" not in kw:
                # empty RaiseEffect() or only partial fields
                if not node.args:
                    findings.append(
                        Finding(
                            path,
                            node.lineno,
                            node.col_offset,
                            NAMELESS,
                            "RaiseEffect(...) without exception_type_coordinate",
                        )
                    )
            else:
                if _is_none_constant(kw["exception_type_coordinate"]):
                    findings.append(
                        Finding(
                            path,
                            node.lineno,
                            node.col_offset,
                            NAMELESS,
                            "RaiseEffect(exception_type_coordinate=None)",
                        )
                    )
            if "occurrence" in kw and _is_none_constant(kw["occurrence"]):
                findings.append(
                    Finding(
                        path,
                        node.lineno,
                        node.col_offset,
                        NAMELESS,
                        "RaiseEffect(occurrence=None)",
                    )
                )

    return sorted(set(findings))


def handler_catches_named_gap(handler: ast.ExceptHandler) -> bool:
    names: set[str] = set()
    if handler.type is None:
        return False

    def walk(node: ast.AST) -> None:
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Tuple):
            for elt in node.elts:
                walk(elt)

    walk(handler.type)
    return bool(
        names
        & {
            "ConstructionPanic",
            "FunctionBindingMiss",
            "SourceCallBindingGap",
            "SugarNotWritten",
            "AttributionInvariantError",
        }
    )


def _in_compare_or_key(const: ast.Constant, tree: ast.AST) -> bool:
    """True when the string constant is used as a compare operand or subscript key."""
    parents: dict[int, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[id(child)] = parent
    node: ast.AST | None = const
    depth = 0
    while node is not None and depth < 6:
        parent = parents.get(id(node))
        if parent is None:
            break
        if isinstance(parent, (ast.Compare, ast.Subscript, ast.keyword)):
            return True
        if isinstance(parent, ast.Call):
            # dict key or equality helper
            return True
        node = parent
        depth += 1
    return False


def _production_roots(repo: Path) -> tuple[Path, ...]:
    return (
        repo / "implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests",
        repo / "implementations/python/sugar-source-tree/src",
        repo / "implementations/python/sugar-lift-python-source/src",
    )


def _source_files(roots: Iterable[Path]) -> list[Path]:
    files: set[Path] = set()
    for root in roots:
        if root.is_file() and root.suffix == ".py":
            files.add(root)
        elif root.is_dir():
            for path in root.rglob("*.py"):
                if "__pycache__" in path.parts:
                    continue
                files.add(path)
    return sorted(files)


def _load_self_sealing():
    here = Path(__file__).resolve().parent
    path = here / "self_sealing_instrument_law.py"
    spec = importlib.util.spec_from_file_location("self_sealing_instrument_law", path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    # dataclasses needs the module present in sys.modules during class body exec
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def scan_roots(
    roots: Iterable[Path] | None = None,
    *,
    repo: Path | None = None,
    include_self_sealing: bool = True,
) -> tuple[list[Finding], list[str]]:
    base = (repo or Path.cwd()).resolve()
    findings: list[Finding] = []
    errors: list[str] = []
    scan_roots_list = tuple(roots) if roots is not None else _production_roots(base)
    for path in _source_files(scan_roots_list):
        label = (
            str(path.resolve().relative_to(base))
            if path.resolve().is_relative_to(base)
            else str(path)
        )
        try:
            source = path.read_text(encoding="utf-8")
            findings.extend(scan_python_source(source, label))
        except (OSError, UnicodeError, SyntaxError) as exc:
            errors.append(f"{label}: {type(exc).__name__}: {exc}")

    if include_self_sealing:
        mod = _load_self_sealing()
        if mod is None:
            errors.append("self_sealing_instrument_law.py: load failed")
        else:
            ss_findings, ss_errors = mod.scan_roots(mod._default_roots(base), repo=base)
            errors.extend(ss_errors)
            for row in ss_findings:
                findings.append(
                    Finding(
                        path=row.path,
                        line=row.line,
                        column=row.column,
                        axis=SELF_SEALING,
                        observed=f"[{row.violation_class}] {row.observed}",
                    )
                )
    return sorted(set(findings)), sorted(errors)


def format_report(findings: Iterable[Finding], errors: Iterable[str] = ()) -> str:
    rows = list(findings)
    error_rows = list(errors)
    lines = [
        "LAW-OF-ONE PARENT R VECTOR",
        "class=LAW-OF-ONE VIOLATION",
        "shape=live-scan (no curated site list; no hand threshold)",
        "",
    ]
    for axis in AXES:
        lines.append(
            f"axis={axis} rung={RUNG[axis]} retire_when={RETIRE_WHEN[axis]}"
        )
    lines.append("")
    for finding in rows:
        lines.append(
            f"{finding.path}:{finding.line}:{finding.column}: {finding.axis}: "
            f"{finding.observed}; required fix: {finding.required_fix}"
        )
    lines.extend(f"AUDITOR-ERROR: {error}" for error in error_rows)
    by_axis = {axis: sum(r.axis == axis for r in rows) for axis in AXES}
    lines.append(f"R_law_of_one_total = {len(rows)}")
    for axis, count in by_axis.items():
        key = axis.lower().replace("-", "_")
        lines.append(f"R_{key} = {count}")
    lines.append(f"R_auditor_errors = {len(error_rows)}")
    # Zeros are measurements that must be preserved — print them explicitly.
    lines.append(
        "stable_zero_requires: all R_* == 0 and R_auditor_errors == 0 "
        "(zeros are load-bearing; do not baseline remaining debt)"
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roots", nargs="*", type=Path)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--json", type=Path)
    parser.add_argument(
        "--no-self-sealing",
        action="store_true",
        help="skip folding self_sealing_instrument_law (axis still reported as 0)",
    )
    args = parser.parse_args()
    repo = args.repo.resolve()
    roots = tuple(p.resolve() for p in args.roots) if args.roots else None
    findings, errors = scan_roots(
        roots, repo=repo, include_self_sealing=not args.no_self_sealing
    )
    print(format_report(findings, errors))
    if args.json is not None:
        by_axis = {axis: sum(f.axis == axis for f in findings) for axis in AXES}
        args.json.write_text(
            json.dumps(
                {
                    "kind": "law-of-one-parent-vector",
                    "class": "LAW-OF-ONE VIOLATION",
                    "R": len(findings),
                    "byAxis": by_axis,
                    "auditorErrors": errors,
                    "findings": [f.to_value() for f in findings],
                    "rung": RUNG,
                    "retireWhen": RETIRE_WHEN,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    return 1 if findings or errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
