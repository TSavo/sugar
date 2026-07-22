from __future__ import annotations

from pathlib import Path


_SEMANTIC_ROOTS = ("floor", "temporal", "proofir", "audit_only")
_FACTORY_AUDIT_NAMES = ("FactoryAuditStatus", "FactoryAuditRow")


def test_construction_semantics_do_not_import_or_reconstruct_factory_audit_objects():
    """R_semantic_factory_audit_authority stays red until the clean slice is zero."""
    package = Path(__file__).parents[1] / "src" / "sugar_lift_py_tests"
    offenders: list[str] = []
    for root_name in _SEMANTIC_ROOTS:
        for path in sorted((package / root_name).rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            for name in _FACTORY_AUDIT_NAMES:
                if name in source:
                    offenders.append(f"{path.relative_to(package)}: {name}")

    assert not offenders, (
        f"R_semantic_factory_audit_authority={len(offenders)}:\n"
        + "\n".join(offenders)
        + "\nreplacement=floor construction outcome or specific loud panic role"
    )
