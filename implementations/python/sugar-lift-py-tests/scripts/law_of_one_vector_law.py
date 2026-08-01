#!/usr/bin/env python3
"""Law-of-One parent R — Model A citing aggregator (no second recognition).

THIS IS NOT A MEGA-SCANNER. It must be impossible for this parent to report a
number its children did not produce. It never re-walks AST for classes that
child instruments already own.

## Class (product layer)

**Second mechanism for a fact** — deciding, minting, keying, or silencing
something that already has one lawful door, by a parallel path.

Fabricated meaning, unauth/spelling dispatch, soft membranes (swallowed
throws / soft skip / panic catch), dual doors, enrollment vanish faces — are
*tags under that class*, owned by specialized children. They are not six peer
parent axes with independent scanners.

## Two layers (never one success number)

1. **product** — second-mechanism children (construction/sugar/lift meaning)
2. **instrument** — self-sealing / measurement integrity (#6958 only)

Summing product R with instrument R into one "done" number is orientation mud.

## Climb, do not audit forever

| Face | Parent stance |
| --- | --- |
| Nameless authenticated identity (product faces) | **Climb** to constructor (non-Optional identity). Prefer type over auditor. |
| Dual producers of one fact | **Climb** to one door; delete second path; then delete any ratchet. |
| Spelling / unauth dispatch | Legitimate **membrane** (open grammar); child owns it. |
| Swallowed throws / soft panic catch | Legitimate **membrane** (open handlers); children own it. |
| Self-sealing instruments | **Meta** layer; cite #6958 only — not a product peer. |

## Model A rules

- Parent imports/calls child APIs only (black boxes).
- Axis map is 1:1 with child modules, not with a hand-curated sin list.
- Missing enrolled child file → parent RED (enrollment is existence for instruments).
- Child R is whatever the child reports; parent does not recompute offenders.
- When a child climbs to type and is deleted, drop the citation — never baseline 0.

## Shell this PR deletes

The dual-scan parent that reimplemented MatchDecided / spelling / swallow /
nameless / self-seal AST walks (merged as #6970 mega-scanner). That was two
producers of one R fact — a Law of One violation by the instrument built to
enforce it.

Not the board. Sole corpus scoreboard remains control_effect_recensus.py.
"""

from __future__ import annotations

SCOREBOARD_AUTHORITY = False

import argparse
import importlib.util
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

# ---------------------------------------------------------------------------
# Citation map: one row per child instrument. Parent never invents R.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChildSpec:
    """Enrolled child. Missing path → parent red. R only from ``collect``."""

    layer: str  # "product" | "instrument"
    axis: str  # stable citation key
    owner_relpath: str  # repo-relative path; enrollment is existence
    description: str
    # collect(repo_root) -> (R: int, detail: dict, errors: list[str])
    # bound at runtime after loaders exist


@dataclass
class Citation:
    layer: str
    axis: str
    owner: str
    R: int
    detail: dict
    errors: list[str] = field(default_factory=list)
    status: str = "ok"  # ok | missing_owner | collect_error

    def to_value(self) -> dict:
        return {
            "layer": self.layer,
            "axis": self.axis,
            "owner": self.owner,
            "R": self.R,
            "status": self.status,
            "detail": self.detail,
            "errors": self.errors,
        }


def _load_script(repo: Path, rel: str, mod_name: str):
    path = repo / rel
    if not path.is_file():
        return None, f"missing owner file: {rel}"
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        return None, f"cannot load: {rel}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception as exc:  # noqa: BLE001 — surface as citation error
        return None, f"{rel}: {type(exc).__name__}: {exc}"
    return mod, None


def _cite_self_sealing(repo: Path) -> Citation:
    rel = "implementations/python/sugar-lift-py-tests/scripts/self_sealing_instrument_law.py"
    mod, err = _load_script(repo, rel, "loo_cite_self_sealing")
    if err:
        return Citation("instrument", "self_sealing", rel, -1, {}, [err], "missing_owner" if "missing" in err else "collect_error")
    try:
        findings, errors = mod.scan_roots(repo=repo)
        by = {}
        for f in findings:
            by[f.violation_class] = by.get(f.violation_class, 0) + 1
        return Citation(
            "instrument",
            "self_sealing",
            rel,
            len(findings),
            {"by_subclass": by, "source": "self_sealing_instrument_law.scan_roots"},
            list(errors),
        )
    except Exception as exc:  # noqa: BLE001
        return Citation("instrument", "self_sealing", rel, -1, {}, [f"{type(exc).__name__}: {exc}"], "collect_error")


def _cite_swallowed_throw(repo: Path) -> Citation:
    rel = "implementations/python/sugar-lift-py-tests/scripts/swallowed_throw_second_mechanism_law.py"
    mod, err = _load_script(repo, rel, "loo_cite_swallowed")
    if err:
        return Citation("product", "swallowed_throw_second_mechanism", rel, -1, {}, [err], "missing_owner" if "missing" in err else "collect_error")
    try:
        python_root = repo / "implementations/python"
        offenders = mod.scan_python_root(python_root)
        counts = mod.axis_counts(offenders)
        return Citation(
            "product",
            "swallowed_throw_second_mechanism",
            rel,
            sum(counts.values()),
            {"by_axis": counts, "source": "swallowed_throw_second_mechanism_law.scan_python_root"},
        )
    except Exception as exc:  # noqa: BLE001
        return Citation("product", "swallowed_throw_second_mechanism", rel, -1, {}, [f"{type(exc).__name__}: {exc}"], "collect_error")


def _cite_construction_panic_catch(repo: Path) -> Citation:
    rel = "implementations/python/sugar-lift-py-tests/scripts/construction_panic_catch_law.py"
    mod, err = _load_script(repo, rel, "loo_cite_panic_catch")
    if err:
        return Citation("product", "construction_panic_catch", rel, -1, {}, [err], "missing_owner" if "missing" in err else "collect_error")
    try:
        kit = repo / "implementations/python/sugar-lift-py-tests"
        offenders = mod.scan_repository(kit)
        panic = [o for o in offenders if getattr(o, "kind", "") != "auditor-error"]
        return Citation(
            "product",
            "construction_panic_catch",
            rel,
            len(panic),
            {"source": "construction_panic_catch_law.scan_repository", "raw_rows": len(offenders)},
        )
    except Exception as exc:  # noqa: BLE001
        return Citation("product", "construction_panic_catch", rel, -1, {}, [f"{type(exc).__name__}: {exc}"], "collect_error")


def _cite_enumeration_soft_skip(repo: Path) -> Citation:
    rel = "implementations/python/sugar-lift-py-tests/scripts/enumeration_binding_soft_skip_law.py"
    mod, err = _load_script(repo, rel, "loo_cite_enum_soft")
    if err:
        return Citation("product", "enumeration_binding_soft_skip", rel, -1, {}, [err], "missing_owner" if "missing" in err else "collect_error")
    try:
        kit = repo / "implementations/python/sugar-lift-py-tests"
        paths = mod.production_scan_roots(kit)
        offenders = mod.scan_sources(paths, root=kit)
        return Citation(
            "product",
            "enumeration_binding_soft_skip",
            rel,
            len(offenders),
            {"source": "enumeration_binding_soft_skip_law.scan_sources"},
        )
    except Exception as exc:  # noqa: BLE001
        return Citation("product", "enumeration_binding_soft_skip", rel, -1, {}, [f"{type(exc).__name__}: {exc}"], "collect_error")


def _cite_source_audit_presence(repo: Path) -> Citation:
    rel = "implementations/python/sugar-lift-py-tests/scripts/source_audit_presence_identity_law.py"
    mod, err = _load_script(repo, rel, "loo_cite_presence")
    if err:
        return Citation("product", "source_audit_presence_identity", rel, -1, {}, [err], "missing_owner" if "missing" in err else "collect_error")
    try:
        roots = [
            repo / "implementations/python/sugar-lift-py-tests/src",
            repo / "implementations/python/sugar-source-tree/src",
            repo / "implementations/python/sugar-lift-python-source/src",
        ]
        offenders, unreadable = mod.scan_roots(roots)
        return Citation(
            "product",
            "source_audit_presence_identity",
            rel,
            len(offenders),
            {
                "source": "source_audit_presence_identity_law.scan_roots",
                "unreadable": len(unreadable),
            },
            [str(u) for u in unreadable[:20]],
        )
    except Exception as exp:  # noqa: BLE001
        return Citation("product", "source_audit_presence_identity", rel, -1, {}, [f"{type(exp).__name__}: {exp}"], "collect_error")


def _cite_one_matcher(repo: Path) -> Citation:
    """MatchDecided(False) sole owner — recognition lives in the test module."""
    rel = "implementations/python/sugar-lift-py-tests/tests/test_match_decided_one_matcher_law.py"
    mod, err = _load_script(repo, rel, "loo_cite_one_matcher")
    if err:
        return Citation("product", "one_matcher_match_decided_false", rel, -1, {}, [err], "missing_owner" if "missing" in err else "collect_error")
    try:
        # Child's structural scan over production packages
        files = mod._production_py_files()
        sites: list = []
        for path in files:
            sites.extend(mod._fabricated_decided_miss_sites(path))
        return Citation(
            "product",
            "one_matcher_match_decided_false",
            rel,
            len(sites),
            {
                "source": "test_match_decided_one_matcher_law._fabricated_decided_miss_sites",
                "sites": [
                    {"path": str(p), "line": ln, "snippet": sn[:120]}
                    for p, ln, sn in sites[:50]
                ],
            },
        )
    except Exception as exc:  # noqa: BLE001
        return Citation("product", "one_matcher_match_decided_false", rel, -1, {}, [f"{type(exc).__name__}: {exc}"], "collect_error")


def _cite_builtin_name_vendor_gates(repo: Path) -> Citation:
    rel = (
        "implementations/python/sugar-lift-py-tests/src/"
        "sugar_lift_py_tests/idd/builtin_closed_operation_instrument.py"
    )
    path = repo / rel
    if not path.is_file():
        return Citation("product", "builtin_name_or_vendor_gates", rel, -1, {}, [f"missing owner file: {rel}"], "missing_owner")
    try:
        # Import as package if possible; else load file and call collect with roots
        sys.path.insert(0, str(repo / "implementations/python/sugar-lift-py-tests/src"))
        from sugar_lift_py_tests.idd.builtin_closed_operation_instrument import (  # type: ignore
            collect_builtin_closed_operation_report,
            production_python_scan_roots,
        )

        roots = production_python_scan_roots(repo)
        report = collect_builtin_closed_operation_report(roots)
        by: dict[str, int] = {}
        by_kind: dict[str, int] = {}
        for o in report.offenders:
            ax = getattr(o, "axis", "unknown")
            by[ax] = by.get(ax, 0) + 1
            k = getattr(o, "kind", "unclassified")
            by_kind[k] = by_kind.get(k, 0) + 1
        # Climb residual only — permanent membranes are separate axes (partition doc).
        r = int(by.get("name_or_vendor_gates", 0))
        detail = {
            "by_axis": by,
            "by_kind": by_kind,
            "source": "builtin_closed_operation_instrument.collect multi-root",
            "partition": "docs/spelling-dispatch-partition.md",
            "membrane_open_lexical_ast_id": by.get("open_lexical_ast_id", 0),
            "membrane_open_lexical_attr_name": by.get("open_lexical_attr_name", 0),
            "fabrication_denylist_axis": by.get("exception_name_fabrication_denylist", 0),
        }
        return Citation("product", "builtin_name_or_vendor_gates", rel, r, detail)
    except Exception as exc:  # noqa: BLE001
        return Citation("product", "builtin_name_or_vendor_gates", rel, -1, {}, [f"{type(exc).__name__}: {exc}"], "collect_error")


# Climb notes — parent does NOT audit these; names the required hatch.
CLIMB_NOT_AUDIT = (
    {
        "face": "nameless_authenticated_identity_product",
        "stance": "climb",
        "why": (
            "Codomain climb: RaiseEffect / Halted faces must require authenticated "
            "type coordinate (non-Optional). Auditor forever is ceremony if None still constructs."
        ),
        "related_children": ["self_sealing PRESENCE-ONLY (tests only)", "RaiseEffect constructor work"],
    },
    {
        "face": "dual_producers_one_fact",
        "stance": "climb",
        "why": (
            "One door: delete the second path so dual production is unrepresentable; "
            "then delete any ratchet that watched it. Parent must not keep a permanent axis."
        ),
        "related_children": ["one_matcher_match_decided_false", "source_audit_presence_identity"],
    },
)

MEMBRANE_HONEST = (
    {
        "face": "spelling_unauth_dispatch",
        "stance": "membrane",
        "owner_axis": (
            "builtin_name_or_vendor_gates (climb residual) + "
            "open_lexical_ast_id + open_lexical_attr_name (permanent) + "
            "enumeration_binding_soft_skip; see docs/spelling-dispatch-partition.md"
        ),
        "why": (
            "Open grammar/vendor Name.id and attr.name projection; type cannot close "
            "ast.Compare on display text. Climb residual is vendor-CM / type-identity "
            "only; lexical membranes are permanent under current ontology."
        ),
    },
    {
        "face": "swallowed_throws_soft_handlers",
        "stance": "membrane",
        "owner_axis": "swallowed_throw_second_mechanism + construction_panic_catch",
        "why": "Open except surface; sanctioned membranes only; not ceremony if child-owned.",
    },
    {
        "face": "self_sealing_instruments",
        "stance": "membrane_meta",
        "owner_axis": "self_sealing",
        "why": "Open test Python; #6958 sole owner; parent cites only.",
    },
)


COLLECTORS: list[tuple[str, str, str, Callable[[Path], Citation]]] = [
    ("product", "one_matcher_match_decided_false", "test_match_decided_one_matcher_law", _cite_one_matcher),
    ("product", "swallowed_throw_second_mechanism", "swallowed_throw_second_mechanism_law", _cite_swallowed_throw),
    ("product", "construction_panic_catch", "construction_panic_catch_law", _cite_construction_panic_catch),
    ("product", "enumeration_binding_soft_skip", "enumeration_binding_soft_skip_law", _cite_enumeration_soft_skip),
    ("product", "source_audit_presence_identity", "source_audit_presence_identity_law", _cite_source_audit_presence),
    ("product", "builtin_name_or_vendor_gates", "builtin_closed_operation_instrument", _cite_builtin_name_vendor_gates),
    ("instrument", "self_sealing", "self_sealing_instrument_law", _cite_self_sealing),
]


def collect_citations(repo: Path) -> list[Citation]:
    return [fn(repo) for _layer, _axis, _name, fn in COLLECTORS]


def format_report(citations: list[Citation]) -> str:
    lines = [
        "LAW-OF-ONE PARENT R VECTOR (Model A — cite only)",
        "class=SECOND MECHANISM (product) + SELF-SEALING (instrument meta)",
        "recognition=children only; parent never re-scans owned classes",
        "",
        "=== climb (no parent auditor) ===",
    ]
    for row in CLIMB_NOT_AUDIT:
        lines.append(f"climb:{row['face']}: {row['why']}")
    lines.append("")
    lines.append("=== honest membranes (child-owned) ===")
    for row in MEMBRANE_HONEST:
        lines.append(f"membrane:{row['face']}: owner={row['owner_axis']}; {row['why']}")
    lines.append("")
    lines.append("=== citations ===")
    product_r = 0
    instrument_r = 0
    missing = 0
    errors = 0
    for c in citations:
        if c.status != "ok":
            missing += 1 if c.status == "missing_owner" else 0
            errors += 1 if c.status == "collect_error" else 0
            lines.append(
                f"CITATION {c.status} layer={c.layer} axis={c.axis} owner={c.owner} "
                f"errors={c.errors}"
            )
            continue
        if c.layer == "product":
            product_r += c.R
        else:
            instrument_r += c.R
        lines.append(
            f"cite layer={c.layer} axis={c.axis} owner={c.owner} "
            f"R={c.R} detail={json.dumps(c.detail, sort_keys=True)[:200]}"
        )
        for e in c.errors:
            lines.append(f"  child_error: {e}")

    lines.append("")
    lines.append(f"R_product_second_mechanism_cited = {product_r}")
    lines.append(f"R_instrument_self_sealing_cited = {instrument_r}")
    lines.append(f"R_citation_missing_owners = {missing}")
    lines.append(f"R_citation_collect_errors = {errors}")
    lines.append(
        "stable_zero_requires: every product citation R==0 AND instrument citation R==0 "
        "AND no missing owners AND no collect errors "
        "(layers reported separately; never one blended 'done' number)"
    )
    lines.append(
        "retirement: when a child climbs to type/door and is deleted, drop its citation; "
        "do not baseline"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)
    repo = args.repo.resolve()
    citations = collect_citations(repo)
    print(format_report(citations))
    product_r = sum(c.R for c in citations if c.layer == "product" and c.status == "ok")
    instrument_r = sum(c.R for c in citations if c.layer == "instrument" and c.status == "ok")
    bad = [c for c in citations if c.status != "ok" or c.R != 0]
    if args.json is not None:
        args.json.write_text(
            json.dumps(
                {
                    "kind": "law-of-one-parent-vector-model-a",
                    "model": "A_cite_only",
                    "class": "SECOND MECHANISM + instrument meta",
                    "R_product_second_mechanism_cited": product_r,
                    "R_instrument_self_sealing_cited": instrument_r,
                    "climb_not_audit": list(CLIMB_NOT_AUDIT),
                    "membrane_honest": list(MEMBRANE_HONEST),
                    "citations": [c.to_value() for c in citations],
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
