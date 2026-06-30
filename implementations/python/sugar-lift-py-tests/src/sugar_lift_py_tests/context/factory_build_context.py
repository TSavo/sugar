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
    # The set of callee names whose body is CURRENTLY being built, up the build stack.
    # CallSugar.build refuses a callee already in this set: eagerly building a recursive
    # universe never terminates, and an infinite recursion is not finitely constructible ->
    # the bridge stays the vendor's axiom rather than hanging the lifter.
    building: frozenset = field(default_factory=frozenset)

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
        from sugar_lift_py_tests.factory.build import build_node
        from sugar_lift_py_tests.factory.source_fragment import SourceFragment
        from sugar_lift_py_tests.sugar_body import SugarBody

        # Accept a SourceFragment directly (idempotent) or an ast node.
        if isinstance(node, SourceFragment):
            site = node
            result = build_node(
                site,
                filename=self.filename,
                role=role,
                catalog=self.catalog,
                ctx=self,
            )
        else:
            result = self.build_child(node, role)
        return SugarBody(sugar=result.sugar, role=role, audit_row=result.audit_row)
