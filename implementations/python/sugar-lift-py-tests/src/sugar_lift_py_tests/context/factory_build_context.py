from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sugar_lift_py_tests.claim import SugarCatalog, SugarRole
from sugar_lift_py_tests.temporal import TemporalContext


@dataclass(frozen=True)
class FactoryBuildContext:
    filename: str
    catalog: SugarCatalog
    temporal: TemporalContext = field(default_factory=TemporalContext.empty)
    source_oracle: Any = None
    expected_role: SugarRole | None = None
    name_resolver: Any = None
    audit_sink: Any = None

    def build_child(self, node, role: SugarRole):
        from sugar_lift_py_tests.factory.build import build_node

        return build_node(
            node,
            filename=self.filename,
            role=role,
            catalog=self.catalog,
            ctx=self,
        )

    def build_body(self, node, role: SugarRole):
        from sugar_lift_py_tests.sugar_body import SugarBody

        result = self.build_child(node, role)
        return SugarBody(sugar=result.sugar, role=role, audit_row=result.audit_row)
