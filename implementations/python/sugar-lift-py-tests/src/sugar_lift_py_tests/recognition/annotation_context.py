from __future__ import annotations

import ast

from sugar_lift_python_source.source_tables import parsed_parents


class AnnotationContextRecognition:
    """Raw structural recognition owned by AnnotationUnionSugar."""

    @staticmethod
    def mark_subtree(node: ast.AST) -> ast.AST:
        for descendant in ast.walk(node):
            descendant._sugar_annotation_context = True  # type: ignore[attr-defined]
        return node

    @staticmethod
    def is_pep613_type_alias(node: ast.AST) -> bool:
        if not isinstance(node, ast.AnnAssign) or node.value is None:
            return False
        annotation = node.annotation
        return (
            isinstance(annotation, ast.Name)
            and annotation.id == "TypeAlias"
            or isinstance(annotation, ast.Attribute)
            and annotation.attr == "TypeAlias"
        )

    @classmethod
    def roots(cls, node: ast.AST) -> list[ast.AST]:
        roots: list[ast.AST] = []
        for descendant in ast.walk(node):
            if isinstance(descendant, ast.arg) and descendant.annotation is not None:
                roots.append(descendant.annotation)
            if (
                isinstance(descendant, (ast.FunctionDef, ast.AsyncFunctionDef))
                and descendant.returns is not None
            ):
                roots.append(descendant.returns)
            if isinstance(descendant, ast.AnnAssign):
                roots.append(descendant.annotation)
                if cls.is_pep613_type_alias(descendant):
                    roots.append(descendant.value)
            type_alias = getattr(ast, "TypeAlias", ())
            if type_alias and isinstance(descendant, type_alias):
                roots.append(descendant.value)
        return roots

    @classmethod
    def mark_runtime_statement(cls, node: ast.stmt) -> ast.stmt:
        if getattr(node, "_sugar_runtime_marked", False):
            return node
        node._sugar_runtime_marked = True  # type: ignore[attr-defined]
        annotation_nodes = {
            descendant for root in cls.roots(node) for descendant in ast.walk(root)
        }
        for descendant in ast.walk(node):
            if descendant in annotation_nodes:
                descendant._sugar_annotation_context = True  # type: ignore[attr-defined]
            elif isinstance(descendant, ast.expr):
                descendant._sugar_runtime_expression_context = True  # type: ignore[attr-defined]
        return node

    @classmethod
    def contains(cls, fragment) -> bool:
        node = fragment.node
        if getattr(node, "_sugar_annotation_context", False):
            return True
        if fragment.source is None:
            return False
        parsed = parsed_parents(fragment.source)
        if parsed is None:
            return False
        _tree, parents = parsed
        target = next(
            (
                candidate
                for candidate in parents
                if type(candidate) is type(node)
                and getattr(candidate, "lineno", None) == fragment.line
                and getattr(candidate, "col_offset", None) == fragment.col
                and getattr(candidate, "end_lineno", None)
                == getattr(node, "end_lineno", None)
                and getattr(candidate, "end_col_offset", None)
                == getattr(node, "end_col_offset", None)
            ),
            None,
        )
        if target is None:
            return False
        current = target
        while current in parents:
            parent = parents[current]
            if isinstance(parent, ast.arg) and parent.annotation is current:
                return True
            if (
                isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef))
                and parent.returns is current
            ):
                return True
            if isinstance(parent, ast.AnnAssign) and parent.annotation is current:
                return True
            if (
                cls.is_pep613_type_alias(parent)
                and isinstance(parent, ast.AnnAssign)
                and parent.value is current
            ):
                return True
            type_alias = getattr(ast, "TypeAlias", ())
            if (
                type_alias
                and isinstance(parent, type_alias)
                and parent.value is current
            ):
                return True
            current = parent
        return False
