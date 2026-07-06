from __future__ import annotations

import importlib.util
import os
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from .source_fragment import SourceFragment

_LEDGER_KEYS = (
    "source_loci",
    "source_warranted",
    "source_inactive",
    "source_support",
    "source_refused",
    "source_unresolved",
    "unclassified_source",
)


def package_source_audits_for_source(
    *, source: str, filename: str
) -> list[dict[str, Any]]:
    if _package_accounting_mode() != "structural":
        return []
    try:
        root_fragment = SourceFragment.from_source(source, filename)
    except SyntaxError:
        return []
    audits: list[dict[str, Any]] = []
    for package in _imported_top_level_packages(root_fragment):
        root = _package_root(package)
        if root is None:
            continue
        accounting = _package_accounting_summary(root)
        totals = accounting["totals"]
        if totals["source_loci"] <= 0:
            continue
        audit = {
            "kind": "source-audit",
            "language": "python",
            "contract": {"name": f"{package}#source-accounting"},
            "role": "python.package-source",
            "universe_kind": "package-accounting",
            "accounting_mode": "structural",
            "package": package,
            "package_root": str(root),
            "totals": totals,
            **accounting,
        }
        if _package_accounting_elide_loci():
            audit["loci_elided"] = True
        audits.append(audit)
    return audits


def source_ledger_for_source_audits(
    source_audits: Iterable[Mapping[str, Any]],
) -> dict[str, int]:
    ledger = _empty_source_ledger()
    for audit in source_audits:
        totals = audit.get("totals")
        if isinstance(totals, Mapping):
            for key in _LEDGER_KEYS:
                ledger[key] += int(totals.get(key, 0) or 0)
            continue
        ledger["source_loci"] += 1
        ledger["source_warranted"] += 1
    return ledger


def _imported_top_level_packages(root_fragment: SourceFragment) -> tuple[str, ...]:
    packages: set[str] = set()
    for fragment in root_fragment.walk():
        if fragment.observed == "Import":
            for name, _asname in fragment.import_names():
                package = name.split(".", 1)[0]
                if package and package != "__future__":
                    packages.add(package)
        elif fragment.observed == "ImportFrom":
            if fragment.importfrom_level() != 0:
                continue
            module = fragment.importfrom_module()
            if not module:
                continue
            package = module.split(".", 1)[0]
            if package and package != "__future__":
                packages.add(package)
    return tuple(sorted(packages))


def _package_root(package: str) -> Path | None:
    try:
        spec = importlib.util.find_spec(package)
    except (ImportError, AttributeError, ValueError):
        return None
    if spec is None or spec.submodule_search_locations is None:
        return None
    for raw in spec.submodule_search_locations:
        root = Path(raw).resolve()
        if root.is_dir():
            return root
    return None


def _package_accounting_summary(root: Path) -> dict[str, Any]:
    totals = _empty_source_ledger()
    ast_type_counts: dict[str, dict[str, int]] = {}
    samples: list[dict[str, Any]] = []
    sample_limit = _package_accounting_sample_limit()
    file_count = 0
    include_loci = not _package_accounting_elide_loci()
    loci: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        file_count += 1
        try:
            source = path.read_text(encoding="utf-8")
            root_fragment = SourceFragment.from_source(source, str(path))
        except (OSError, SyntaxError) as exc:
            locus = _source_locus(
                path,
                line=0,
                col=0,
                status="unclassified",
                ast_kind="Parse",
                reason=f"package source could not be parsed for accounting: {exc}",
            )
            _account_locus(totals, ast_type_counts, locus)
            if include_loci:
                loci.append(locus)
            elif len(samples) < sample_limit:
                samples.append(locus)
            continue
        for fragment in root_fragment.walk():
            if not fragment.has_position():
                continue
            status, reason = _structural_status(fragment)
            locus = _source_locus(
                path,
                line=fragment.line,
                col=fragment.col,
                status=status,
                ast_kind=fragment.observed,
                reason=reason,
                end_line=fragment.end_line,
                end_col=fragment.end_col,
            )
            _account_locus(totals, ast_type_counts, locus)
            if include_loci:
                loci.append(locus)
            elif len(samples) < sample_limit:
                samples.append(locus)
    result: dict[str, Any] = {
        "totals": totals,
        "ast_type_counts": ast_type_counts,
        "package_file_count": file_count,
    }
    if include_loci:
        result["loci"] = loci
    else:
        result["sample_loci"] = samples
    return result


def _structural_status(fragment: SourceFragment) -> tuple[str, str]:
    if fragment.observed in {"Import", "ImportFrom", "alias"}:
        return (
            "unclassified",
            "import metadata is not classified by any emitted Python source warrant",
        )
    if fragment.observed in {"FunctionDef", "AsyncFunctionDef"}:
        return (
            "unclassified",
            "function declaration is not classified by any emitted Python source warrant",
        )
    if fragment.observed == "ClassDef":
        return (
            "unclassified",
            "class declaration is not classified by any emitted Python source warrant",
        )
    if fragment.observed == "arg":
        return (
            "unclassified",
            "function parameter metadata is not classified by any emitted Python source warrant",
        )
    if fragment.observed == "Pass":
        return (
            "unclassified",
            "pass no-op scaffolding is not classified by any emitted Python source warrant",
        )
    if fragment.observed == "Expr":
        value = fragment.expr_value()
        if value.observed == "PrimitiveLiteral" and isinstance(
            value.literal_value(), str
        ):
            return "inactive", "docstring metadata is inactive at runtime"
    return "unclassified", "not classified by any emitted Python source warrant"


def _source_locus(
    path: Path,
    *,
    line: int,
    col: int,
    status: str,
    ast_kind: str,
    reason: str,
    end_line: Any = None,
    end_col: Any = None,
) -> dict[str, Any]:
    locus = {
        "file": str(path),
        "line": line,
        "col": col,
        "status": status,
        "role": "python.package-source",
        "contract": "package-accounting",
        "ast_kind": ast_kind,
        "reason": reason,
    }
    if isinstance(end_line, int) and isinstance(end_col, int):
        locus["span"] = {
            "start_line": line,
            "start_col": col,
            "end_line": end_line,
            "end_col": end_col,
        }
    return locus


def _account_locus(
    totals: dict[str, int],
    ast_type_counts: dict[str, dict[str, int]],
    locus: Mapping[str, Any],
) -> None:
    status = _normalized_source_status(locus.get("status"))
    totals["source_loci"] += 1
    if status == "warranted":
        totals["source_warranted"] += 1
    elif status == "inactive":
        totals["source_inactive"] += 1
    elif status == "support":
        totals["source_support"] += 1
    elif status == "unresolved":
        totals["source_unresolved"] += 1
    elif status == "refused":
        totals["source_refused"] += 1
    else:
        totals["unclassified_source"] += 1
    ast_kind = str(locus.get("ast_kind") or "?")
    ast_type_counts.setdefault(status, {}).setdefault(ast_kind, 0)
    ast_type_counts[status][ast_kind] += 1


def _normalized_source_status(status: Any) -> str:
    if status in {"warranted", "support", "inactive", "unresolved", "refused"}:
        return str(status)
    return "unclassified"


def _empty_source_ledger() -> dict[str, int]:
    return {key: 0 for key in _LEDGER_KEYS}


def _package_accounting_mode() -> str:
    return os.environ.get("SUGAR_PY_PACKAGE_ACCOUNTING_MODE", "").strip().lower()


def _package_accounting_elide_loci() -> bool:
    mode = os.environ.get("SUGAR_PY_PACKAGE_ACCOUNTING_LOCI", "").strip().lower()
    return mode in {"summary", "elide", "counts"}


def _package_accounting_sample_limit() -> int:
    raw = os.environ.get("SUGAR_PY_PACKAGE_ACCOUNTING_SAMPLE_LIMIT", "").strip()
    if not raw:
        return 200
    try:
        return max(0, int(raw))
    except ValueError:
        return 200
