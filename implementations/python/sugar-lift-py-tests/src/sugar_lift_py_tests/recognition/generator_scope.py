from __future__ import annotations

import ast


class GeneratorScopeRecognition:
    """Factory testimony that a Yield belongs to a function-body gateway."""

    @staticmethod
    def mark_function_body(nodes: list[ast.stmt]) -> list[ast.stmt]:
        class MarkOwnedYield(ast.NodeVisitor):
            def visit_Yield(self, node: ast.Yield) -> None:
                node._sugar_generator_context = True  # type: ignore[attr-defined]

            def stop_at_nested_owner(self, node: ast.AST) -> None:
                del node

            visit_FunctionDef = stop_at_nested_owner
            visit_AsyncFunctionDef = stop_at_nested_owner
            visit_Lambda = stop_at_nested_owner
            visit_ClassDef = stop_at_nested_owner

        marker = MarkOwnedYield()
        for node in nodes:
            marker.visit(node)
        return nodes

    @staticmethod
    def contains(site) -> bool:
        return (
            bool(getattr(site.node, "_sugar_generator_context", False))
            or site.has_enclosing_function()
        )
