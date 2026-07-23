"""ConstructionGap testimony must not depend on audit projection."""

from __future__ import annotations

import ast
from pathlib import Path

from sugar_lift_py_tests.gap.audit_row import (
    ConstructionAuditStatus,
    gap_kind_status,
)
from sugar_lift_py_tests.gap.info import ConstructionGap, GapKind

_GAP = Path(__file__).resolve().parents[1] / "src" / "sugar_lift_py_tests" / "gap"


def test_info_module_does_not_import_audit_row() -> None:
    source = (_GAP / "info.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if "audit_row" in node.module or node.module.endswith("audit_row"):
                offenders.append(f"ImportFrom {node.module}")
        if isinstance(node, ast.Import):
            for alias in node.names:
                if "audit_row" in alias.name:
                    offenders.append(f"Import {alias.name}")
    assert (
        offenders == []
    ), "gap/info.py must not import audit projection:\n" + "\n".join(offenders)


def test_gap_kind_status_lives_on_audit_boundary() -> None:
    assert gap_kind_status(GapKind.FLOOR) is ConstructionAuditStatus.FLOOR_GAP
    assert gap_kind_status(GapKind.SUGAR) is ConstructionAuditStatus.SUGAR_GAP
    assert (
        gap_kind_status(GapKind.CONSTRUCTOR) is ConstructionAuditStatus.CONSTRUCTOR_GAP
    )
    # Pure testimony constructs without touching audit status.
    gap = ConstructionGap(
        owner="test",
        blame="t.py:1:0",
        observed="x",
        requested="y",
        fix="z",
        gap_kind=GapKind.OPERATION,
    )
    assert gap.gap_kind is GapKind.OPERATION
    assert gap_kind_status(gap.gap_kind) is ConstructionAuditStatus.OPERATION_GAP
