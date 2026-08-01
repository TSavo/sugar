#!/usr/bin/env python3
"""Criterion 5 inventory: every semantic family ships a lying twin.

CLASS
    SEMANTIC-FAMILY TWIN COVERAGE

DEFINITION
    Enrollment is existence: a semantic family is whatever the live catalog
    enumerates (factory-owned Sugar classes with ``witnesses()``, plus the
    ProofIR node-class registry). Each family must have a TRUTHFUL face and a
    LYING face. A family with only a truthful twin is untested for the thing
    that matters: a positive test proves the instrument fires; only a lying
    twin proves it can FAIL (AGENTS.md: only a flipping bad-twin can check the
    honest-arm clause).

AXES
    R_families_without_lying_twin
        Families that lack a discriminable lying face.
    R_families_without_truthful_twin
        Symmetric gap (reported; primary red is lying).
    R_families_without_either_twin
        No witnesses / empty enrollment surface.

Not the board. SCOREBOARD_AUTHORITY = False.

ENFORCEMENT LADDER
    Rung: **auditor** (static recognition over live catalog enrollment).

    Why not higher:
    1. Type system: cannot forbid a classmethod that returns only one face of a
       pair without a closed witness type that requires both constructors.
    2. One door: a sealed ``SugarWitnessPair`` / ``VerdictWitnessPair`` type
       that refuses construction without both faces would climb; today Python
       allows free-form ``witnesses()`` returns including partial shapes.
    3. Panic at contact: missing twins are absence of a test face, not a
       runtime contact path until the catalog test runs.

    Retirement path (name what would delete this auditor):
    - ``witnesses()`` return type is ``SugarWitnesses`` sealed at the type
      level: ``SugarWitnessPair`` (or lawful ``NotVerdictBearing`` opt-out)
      is the only constructible result; a single-face object cannot be built.
    - ProofIR ``verdict_witnesses()`` similarly sealed.
    When those doors refuse incomplete pairs, delete this inventory auditor.

This is MEASUREMENT only: it does not write missing twins. Exit 1 while R > 0.
"""

from __future__ import annotations

# Not the board.
SCOREBOARD_AUTHORITY = False

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Iterable


@dataclass(frozen=True, order=True)
class FamilyTwinStatus:
    catalog: str
    family: str
    path: str
    line: int
    has_truthful: bool
    has_lying: bool
    status: str  # both | truthful_only | lying_only | neither | opt_out
    plant: str

    @property
    def missing_lying(self) -> bool:
        return self.status in {"truthful_only", "neither"} and self.status != "opt_out"

    @property
    def missing_truthful(self) -> bool:
        return self.status in {"lying_only", "neither"} and self.status != "opt_out"


_OPT_OUT_MARKERS = frozenset(
    {
        "NotVerdictBearing",
        "not_verdict_bearing",
        "temporal_opt_out",
        "NON_FOL_OPT_OUT",
    }
)

_TRUTHFUL_MARKERS = frozenset(
    {
        "truthful",
        "SugarWitnessPair",
        "SugarUnwitnessedPair",
        "SugarRedEffectWitnessPair",
        "_call_pair",
        "_call_return_pair",
        "_boolop_wrapped_pair",
        "_unwitnessed_call_return_pair",
        "inert_statement_return_witness",
        "typed_red_effect_witness",
        "VerdictWitnessPair",
        "VerdictWitnessCase",
    }
)

_LYING_MARKERS = frozenset(
    {
        "lying",
        "SugarWitnessPair",
        "SugarUnwitnessedPair",
        "SugarRedEffectWitnessPair",
        "_call_pair",
        "_call_return_pair",
        "_boolop_wrapped_pair",
        "_unwitnessed_call_return_pair",
        "inert_statement_return_witness",
        "typed_red_effect_witness",
        "VerdictWitnessPair",
        "VerdictWitnessCase",
    }
)


def _method(class_node: ast.ClassDef, name: str) -> ast.FunctionDef | None:
    for item in class_node.body:
        if (
            isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            and item.name == name
        ):
            return item
    return None


def _terminal_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _kw_present(tree: ast.AST, name: str) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == name:
            return True
        if isinstance(node, ast.Name) and node.id == name:
            return True
        if isinstance(node, ast.Attribute) and node.attr == name:
            return True
    return False


def _call_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            names.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            names.add(node.func.attr)
    return names


def _classify_witnesses_method(
    witnesses: ast.FunctionDef | None,
) -> tuple[bool, bool, bool]:
    """Return (has_truthful, has_lying, is_opt_out)."""
    if witnesses is None:
        return False, False, False
    body_text = ast.unparse(witnesses)
    if any(marker in body_text for marker in _OPT_OUT_MARKERS):
        return False, False, True
    calls = _call_names(witnesses)
    has_kw_truthful = _kw_present(witnesses, "truthful")
    has_kw_lying = _kw_present(witnesses, "lying")
    # Pair constructors that always carry both faces by API.
    pair_ctors = calls & {
        "SugarWitnessPair",
        "SugarUnwitnessedPair",
        "SugarRedEffectWitnessPair",
        "_call_pair",
        "_call_return_pair",
        "_boolop_wrapped_pair",
        "_unwitnessed_call_return_pair",
        "inert_statement_return_witness",
        "typed_red_effect_witness",
        "VerdictWitnessPair",
    }
    if pair_ctors:
        # These APIs require both faces; treat as both present.
        return True, True, False
    has_truthful = has_kw_truthful or bool(calls & _TRUTHFUL_MARKERS)
    has_lying = has_kw_lying or bool(calls & _LYING_MARKERS)
    # Bare return of something without markers → neither (unenrolled).
    return has_truthful, has_lying, False


def _status(has_truthful: bool, has_lying: bool, opt_out: bool) -> str:
    if opt_out:
        return "opt_out"
    if has_truthful and has_lying:
        return "both"
    if has_truthful and not has_lying:
        return "truthful_only"
    if has_lying and not has_truthful:
        return "lying_only"
    return "neither"


def _plant_for(status: str, family: str) -> str:
    if status == "opt_out":
        return (
            f"{family}: lawful NotVerdictBearing opt-out — no verdict twin owed; "
            "if this family becomes FOL-bearing, plant SugarWitnessPair(truthful=…, lying=…)"
        )
    if status == "both":
        return f"{family}: both faces enrolled"
    if status == "truthful_only":
        return (
            f"{family}: plant a LYING twin that flips the instrument red "
            f"(wrong assertion / wrong effect / construction-open) while the "
            f"truthful face stays SAT; register as SugarWitnessPair.lying or "
            f"VerdictWitnessPair.lying"
        )
    if status == "lying_only":
        return (
            f"{family}: plant a TRUTHFUL twin that proves the recognizer fires "
            f"(SAT / expected typed red) as SugarWitnessPair.truthful"
        )
    return (
        f"{family}: plant BOTH faces — SugarWitnessPair(name=…, owner_sugar={family!r}, "
        f"truthful=WitnessSource(…, expected='sat'), "
        f"lying=WitnessSource(…, expected='unsat')) "
        f"or lawful NotVerdictBearing opt-out with floor reason"
    )


def enumerate_sugar_families(sugar_root: Path) -> list[FamilyTwinStatus]:
    """Live catalog: concrete *Sugar classes that define witnesses()."""
    rows: list[FamilyTwinStatus] = []
    if not sugar_root.is_dir():
        return rows
    for path in sorted(sugar_root.rglob("*.py")):
        if path.name.startswith("_") and path.name != "__init__.py":
            continue
        try:
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source, filename=str(path))
        except (OSError, UnicodeError, SyntaxError):
            continue
        rel = f"sugar/{path.relative_to(sugar_root).as_posix()}"
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            if not node.name.endswith("Sugar"):
                continue
            if any(_terminal_name(base) in {"ABC", "Protocol"} for base in node.bases):
                continue
            witnesses = _method(node, "witnesses")
            if witnesses is None:
                # Not enrolled in the witness catalog — not a semantic family
                # for criterion 5 (enrollment is existence via witnesses).
                continue
            has_t, has_l, opt = _classify_witnesses_method(witnesses)
            status = _status(has_t, has_l, opt)
            rows.append(
                FamilyTwinStatus(
                    catalog="sugar",
                    family=node.name,
                    path=rel,
                    line=node.lineno,
                    has_truthful=has_t,
                    has_lying=has_l,
                    status=status,
                    plant=_plant_for(status, node.name),
                )
            )
    return rows


def _registry_names(init_path: Path, registry_name: str) -> list[str]:
    """Read class names from a module-level registry tuple assignment."""
    try:
        tree = ast.parse(init_path.read_text(encoding="utf-8"), filename=str(init_path))
    except (OSError, UnicodeError, SyntaxError):
        return []
    names: list[str] = []
    for node in tree.body:
        if not isinstance(node, ast.AnnAssign):
            if not isinstance(node, ast.Assign):
                continue
            targets = node.targets
            value = node.value
        else:
            targets = [node.target]
            value = node.value
        for target in targets:
            if not isinstance(target, ast.Name) or target.id != registry_name:
                continue
            if not isinstance(value, (ast.Tuple, ast.List)):
                continue
            for elt in value.elts:
                name = _terminal_name(elt)
                if name:
                    names.append(name)
    return names


def _find_class_def(
    package_root: Path, class_name: str
) -> tuple[Path, ast.ClassDef] | None:
    for path in sorted(package_root.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, UnicodeError, SyntaxError):
            continue
        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == class_name:
                return path, node
    return None


def enumerate_proofir_families(proofir_nodes_root: Path) -> list[FamilyTwinStatus]:
    """Live catalog: ProofIR node classes named in the registry tuples."""
    rows: list[FamilyTwinStatus] = []
    init_path = proofir_nodes_root / "__init__.py"
    if not init_path.is_file():
        return [
            FamilyTwinStatus(
                catalog="proofir",
                family="__catalog_missing__",
                path=str(init_path),
                line=0,
                has_truthful=False,
                has_lying=False,
                status="neither",
                plant=f"missing ProofIR nodes package at {proofir_nodes_root}",
            )
        ]
    names = _registry_names(init_path, "REGISTERED_PROOFIR_NODE_CLASSES")
    names += _registry_names(init_path, "_ADDITIONAL_PROOFIR_WITNESS_CLASSES")
    # Enrollment is existence: empty registry is itself a catalog failure.
    if not names:
        rows.append(
            FamilyTwinStatus(
                catalog="proofir",
                family="__catalog_empty__",
                path=f"proofir/nodes/{init_path.name}",
                line=0,
                has_truthful=False,
                has_lying=False,
                status="neither",
                plant="ProofIR registry tuples are empty — enroll node classes",
            )
        )
        return rows
    for class_name in names:
        found = _find_class_def(proofir_nodes_root, class_name)
        if found is None:
            rows.append(
                FamilyTwinStatus(
                    catalog="proofir",
                    family=class_name,
                    path="proofir/nodes/",
                    line=0,
                    has_truthful=False,
                    has_lying=False,
                    status="neither",
                    plant=(
                        f"{class_name}: registry names a class with no source "
                        "definition under proofir/nodes"
                    ),
                )
            )
            continue
        path, class_node = found
        witnesses = _method(class_node, "verdict_witnesses")
        has_t, has_l, opt = _classify_witnesses_method(witnesses)
        # ProofIR pairs always construct both faces when method exists; refine
        # with keyword detection for truthful=/lying= on VerdictWitnessPair.
        if witnesses is not None and not opt:
            has_t = has_t or _kw_present(witnesses, "truthful")
            has_l = has_l or _kw_present(witnesses, "lying")
            if _call_names(witnesses) & {"VerdictWitnessPair"}:
                has_t, has_l = True, True
        status = _status(has_t, has_l, opt)
        try:
            rel = f"proofir/nodes/{path.relative_to(proofir_nodes_root).as_posix()}"
        except ValueError:
            rel = path.as_posix()
        rows.append(
            FamilyTwinStatus(
                catalog="proofir",
                family=class_name,
                path=rel,
                line=class_node.lineno,
                has_truthful=has_t,
                has_lying=has_l,
                status=status,
                plant=_plant_for(status, class_name),
            )
        )
    return rows


def inventory(
    *,
    sugar_root: Path,
    proofir_nodes_root: Path | None = None,
    include_proofir: bool = True,
) -> list[FamilyTwinStatus]:
    rows = enumerate_sugar_families(sugar_root)
    if include_proofir:
        if proofir_nodes_root is None:
            proofir_nodes_root = (
                sugar_root.parent / "proofir" / "nodes"
            )
        rows.extend(enumerate_proofir_families(proofir_nodes_root))
    return sorted(rows, key=lambda r: (r.catalog, r.family, r.path, r.line))


def format_report(rows: Iterable[FamilyTwinStatus]) -> str:
    rows = list(rows)
    missing_lying = [r for r in rows if r.missing_lying]
    missing_truthful = [r for r in rows if r.missing_truthful]
    opt_out = [r for r in rows if r.status == "opt_out"]
    both = [r for r in rows if r.status == "both"]
    lines = [
        "SEMANTIC-FAMILY TWIN INVENTORY (criterion 5)",
        f"catalog_families = {len(rows)}",
        f"R_families_without_lying_twin = {len(missing_lying)}",
        f"R_families_without_truthful_twin = {len(missing_truthful)}",
        f"families_with_both = {len(both)}",
        f"families_opt_out_not_verdict_bearing = {len(opt_out)}",
        "",
        "Law: enrollment is existence. Every catalog family must ship a lying "
        "twin that can flip red. Positive-only coverage is unfalsifiable.",
        "Retirement: seal witnesses() / verdict_witnesses() so incomplete pairs "
        "are unconstructable; then delete this auditor.",
        "",
    ]
    if missing_lying:
        lines.append("OFFENDERS (missing lying twin):")
        for row in missing_lying:
            lines.append(
                f"  {row.catalog}:{row.family} @ {row.path}:{row.line} "
                f"status={row.status}"
            )
            lines.append(f"    plant: {row.plant}")
        lines.append("")
    if missing_truthful:
        lines.append("OFFENDERS (missing truthful twin):")
        for row in missing_truthful:
            lines.append(
                f"  {row.catalog}:{row.family} @ {row.path}:{row.line} "
                f"status={row.status}"
            )
            lines.append(f"    plant: {row.plant}")
        lines.append("")
    lines.append("FULL INVENTORY:")
    for row in rows:
        lines.append(
            f"  {row.catalog}:{row.family} status={row.status} "
            f"truthful={int(row.has_truthful)} lying={int(row.has_lying)} "
            f"@ {row.path}:{row.line}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="backslashreplace")
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sugar-root",
        type=Path,
        default=(
            Path(__file__).resolve().parents[1]
            / "src"
            / "sugar_lift_py_tests"
            / "sugar"
        ),
    )
    parser.add_argument(
        "--proofir-nodes-root",
        type=Path,
        default=(
            Path(__file__).resolve().parents[1]
            / "src"
            / "sugar_lift_py_tests"
            / "proofir"
            / "nodes"
        ),
    )
    parser.add_argument(
        "--no-proofir",
        action="store_true",
        help="skip ProofIR registry (sugar catalog only)",
    )
    args = parser.parse_args(argv)
    rows = inventory(
        sugar_root=args.sugar_root,
        proofir_nodes_root=args.proofir_nodes_root,
        include_proofir=not args.no_proofir,
    )
    report = format_report(rows)
    print(report)
    r_lying = sum(1 for r in rows if r.missing_lying)
    return 1 if r_lying > 0 or not rows else 0


if __name__ == "__main__":
    raise SystemExit(main())
