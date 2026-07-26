#!/usr/bin/env python3
"""R_finite_unfold_compact_gaps — over-cap finite For/range must project compactly.

Illegal residual: ForSugar / CallSugar still leave decidable finite over-cap work as gaps
(or finite for + non-ground while) with ``finite_unfold_cap_panic`` instead of the
shared compact projection door.

Replacement architecture (one shared door, not file tickets):

* CallSugar range over-cap → fall through to CallSiteValue projection
  (no ListValue materialize, no force-curry, no opaque Complete on the cap arm)
* ForSugar finite over-cap or non-ground while body → recognition projection
  (``_project_compact_finite`` / ``_bind_and_body`` without ``force_curry=True``)
  instead of N-fold static unfold or force-curry opacity

Still lawful loud terminals (not residual):

* range / iterable length overflow past ``sys.maxsize``
* sequence repetition / join / comprehension over-cap arms that have not yet
  grown their own exact compact constructors

Floors preserved: ``R_finite_cap_opaque_completions = 0`` (no soft-complete,
no force-curry on finite arms, no bound raise, no RuntimeEffect laundry).

Baseline-free structural census. R > 0 exits red.
"""

from __future__ import annotations

# Not the board. This module measures its own named denominator; the sole
# authoritative Python corpus scoreboard is scripts/control_effect_recensus.py.
# See tests/test_one_authoritative_scoreboard.py.
SCOREBOARD_AUTHORITY = False

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import NamedTuple, Sequence


class FiniteUnfoldCompactGap(NamedTuple):
    path: str
    line: int
    kind: str
    expression: str
    note: str


# Residual drain family: these panic arms must be replaced by compact projection.
_RESIDUAL_CONSTRUCTION_PREFIXES = (
    "ForSugar finite iterable",
    "ForSugar finite for/while",
    "CallSugar range",
)

_OVERFLOW_MARKERS = (
    "overflow",
    "exceeds sys.maxsize",
    "length overflow",
)


def _name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _safe_unparse(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception as exc:  # noqa: BLE001 - auditor must stay structured
        return f"<unparse-failed:{type(exc).__name__}>"


def _const_str(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _call_keyword(node: ast.Call, name: str) -> ast.AST | None:
    for item in node.keywords:
        if item.arg == name:
            return item.value
    return None


def _is_overflow_observed(observed: str | None) -> bool:
    if not observed:
        return False
    lowered = observed.lower()
    return any(marker in lowered for marker in _OVERFLOW_MARKERS)


def _residual_kind(construction: str | None, observed: str | None) -> str | None:
    if not construction:
        return None
    if construction.startswith("ForSugar finite for/while"):
        return "for-nonground-while-panic"
    if construction.startswith("ForSugar finite iterable"):
        # Length overflow stays loud; cardinality over-cap is residual.
        if _is_overflow_observed(observed):
            return None
        return "for-over-cap-panic"
    if construction.startswith("CallSugar range"):
        if _is_overflow_observed(observed):
            return None
        return "range-over-cap-panic"
    return None


def scan_source(source: str, *, path: str) -> list[FiniteUnfoldCompactGap]:
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        return [
            FiniteUnfoldCompactGap(
                path,
                int(exc.lineno or 0),
                "auditor-parse-error",
                type(exc).__name__,
                f"ast.parse failed: {exc.msg}",
            )
        ]
    except Exception as exc:  # noqa: BLE001
        return [
            FiniteUnfoldCompactGap(
                path,
                0,
                "auditor-parse-error",
                type(exc).__name__,
                f"ast.parse failed: {exc}",
            )
        ]

    offenders: list[FiniteUnfoldCompactGap] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        called = _name(node.func).split(".")[-1]
        if called != "finite_unfold_cap_panic":
            continue
        construction = _const_str(_call_keyword(node, "construction"))
        observed = _const_str(_call_keyword(node, "observed"))
        # f-string observed values: treat as residual when construction matches
        # and the static observed keyword is absent or non-overflow.
        if observed is None:
            observed_node = _call_keyword(node, "observed")
            if isinstance(observed_node, ast.JoinedStr):
                observed = _safe_unparse(observed_node)
        kind = _residual_kind(construction, observed)
        if kind is None:
            continue
        offenders.append(
            FiniteUnfoldCompactGap(
                path,
                int(getattr(node, "lineno", 0) or 0),
                kind,
                _safe_unparse(node),
                (
                    "replace residual finite_unfold panic with shared compact "
                    "projection: CallSiteValue range fall-through or ForSugar "
                    "recognition projection (no force_curry, no opaque Complete)"
                ),
            )
        )
    return offenders


def scan_roots(roots: Sequence[Path]) -> list[FiniteUnfoldCompactGap]:
    offenders: list[FiniteUnfoldCompactGap] = []
    for root in roots:
        if not root.exists():
            offenders.append(
                FiniteUnfoldCompactGap(
                    root.as_posix(),
                    0,
                    "auditor-root-error",
                    "FileNotFoundError",
                    "scan root does not exist",
                )
            )
            continue
        paths = (root,) if root.is_file() else sorted(root.rglob("*.py"))
        for path in paths:
            try:
                source = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as exc:
                offenders.append(
                    FiniteUnfoldCompactGap(
                        path.as_posix(),
                        0,
                        "auditor-read-error",
                        type(exc).__name__,
                        f"could not read source: {exc}",
                    )
                )
                continue
            try:
                rel = path.resolve().relative_to(root.resolve()).as_posix()
            except ValueError:
                rel = path.as_posix()
            offenders.extend(scan_source(source, path=f"{root.name}/{rel}"))
    return sorted(offenders, key=lambda row: (row.path, row.line, row.kind))


def r_finite_unfold_compact_gaps(rows: Sequence[FiniteUnfoldCompactGap]) -> int:
    return sum(1 for row in rows if not row.kind.startswith("auditor-"))


def r_auditor_errors(rows: Sequence[FiniteUnfoldCompactGap]) -> int:
    return sum(1 for row in rows if row.kind.startswith("auditor-"))


def _default_root() -> Path:
    return Path(__file__).resolve().parents[1] / "src" / "sugar_lift_py_tests"


def main(argv: Sequence[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("roots", nargs="*", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    rows = scan_roots(tuple(args.roots) or (_default_root(),))
    risk = r_finite_unfold_compact_gaps(rows)
    errors = r_auditor_errors(rows)
    if args.json:
        print(
            json.dumps(
                {
                    "R_finite_unfold_compact_gaps": risk,
                    "R_auditor_errors": errors,
                    "rows": [row._asdict() for row in rows],
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        for row in rows:
            print(f"{row.path}:{row.line}: {row.kind}: {row.note}")
            print(f"  {row.expression}")
        print(f"R_finite_unfold_compact_gaps = {risk}")
        print(f"R_auditor_errors = {errors}")
        if risk == 0 and errors == 0:
            print(
                "replacement: CallSiteValue range projection + ForSugar "
                "recognition projection (no force_curry / opaque Complete)"
            )
    return 1 if risk or errors else 0


if __name__ == "__main__":
    sys.exit(main())
