from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarCatalog, SugarRole


@dataclass(frozen=True)
class FactoryBuildContext:
    filename: str
    catalog: SugarCatalog

    def build_child(self, node, role: SugarRole):
        from .build import build_node

        return build_node(
            node,
            filename=self.filename,
            role=role,
            catalog=self.catalog,
        )
