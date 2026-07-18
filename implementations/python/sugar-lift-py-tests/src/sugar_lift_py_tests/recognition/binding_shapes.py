from __future__ import annotations

import ast


class BindingShapeRecognition:
    """Binding testimony owned by Assign/For/With/constructor Sugars."""

    @staticmethod
    def named_expr_target_name(site) -> str:
        target = site.node.target
        if not isinstance(target, ast.Name):
            raise TypeError(
                "NamedExpr target must be an ast.Name; malformed AST cannot "
                "enter NamedExprSugar"
            )
        return target.id

    @staticmethod
    def assign_target_name(site) -> str | None:
        targets = site.node.targets
        if len(targets) == 1 and isinstance(targets[0], ast.Name):
            return targets[0].id
        return None

    @staticmethod
    def assign_attribute_receiver_name(site) -> str | None:
        targets = site.node.targets
        if (
            len(targets) == 1
            and isinstance(targets[0], ast.Attribute)
            and isinstance(targets[0].value, ast.Name)
        ):
            return targets[0].value.id
        return None

    @staticmethod
    def assign_attribute_name(site) -> str | None:
        targets = site.node.targets
        if len(targets) == 1 and isinstance(targets[0], ast.Attribute):
            return targets[0].attr
        return None

    @staticmethod
    def assign_dotted_path(site) -> tuple[str, ...] | None:
        from sugar_lift_py_tests.recognition.call_identity import (
            CallIdentityRecognition,
        )
        from sugar_lift_py_tests.source_fragment import SourceFragment

        targets = site.node.targets
        if len(targets) != 1 or not isinstance(targets[0], ast.Attribute):
            return None
        target = SourceFragment.from_node(targets[0], site.filename, source=site.source)
        dotted = CallIdentityRecognition.qualified_name(target)
        return None if dotted is None else tuple(dotted.split("."))

    @staticmethod
    def annassign_target_id(site) -> str:
        target = site.node.target
        if not isinstance(target, ast.Name):
            raise TypeError(
                "annassign_target_id requires a Name target, got "
                f"{type(target).__name__} at {site.blame}"
            )
        return target.id

    @staticmethod
    def with_optional_vars_name(site, index: int = 0) -> str | None:
        target = site.node.items[index].optional_vars
        return target.id if isinstance(target, ast.Name) else None

    @staticmethod
    def for_target_name(site) -> str | None:
        target = site.node.target
        return target.id if isinstance(target, ast.Name) else None

    @staticmethod
    def for_flat_tuple_target_names(site) -> tuple[str, ...] | None:
        target = site.node.target
        if not isinstance(target, ast.Tuple) or not target.elts:
            return None
        if not all(isinstance(element, ast.Name) for element in target.elts):
            return None
        return tuple(element.id for element in target.elts)

    @staticmethod
    def for_nested_tuple_target_paths(
        site,
    ) -> tuple[tuple[tuple[int, ...], str], ...] | None:
        target = site.node.target
        if not isinstance(target, ast.Tuple):
            return None
        paths: list[tuple[tuple[int, ...], str]] = []
        nested = False

        def visit(node, path: tuple[int, ...]) -> bool:
            nonlocal nested
            if isinstance(node, ast.Name):
                paths.append((path, node.id))
                return True
            if not isinstance(node, ast.Tuple) or not node.elts:
                return False
            if path:
                nested = True
            return all(
                visit(item, (*path, index)) for index, item in enumerate(node.elts)
            )

        if not visit(target, ()) or not nested:
            return None
        return tuple(paths)

    @staticmethod
    def binds_name_anywhere(site, name: str) -> bool:
        for descendant in ast.walk(site.node):
            if (
                isinstance(
                    descendant,
                    (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
                )
                and descendant.name == name
            ):
                return True
            if (
                isinstance(descendant, ast.Name)
                and isinstance(descendant.ctx, ast.Store)
                and descendant.id == name
            ):
                return True
            if isinstance(descendant, (ast.Import, ast.ImportFrom)) and any(
                (alias.asname or alias.name.split(".", 1)[0]) == name
                for alias in descendant.names
            ):
                return True
        return False

    @staticmethod
    def loaded_names(site) -> frozenset[str]:
        return frozenset(
            node.id
            for node in ast.walk(site.node)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
        )

    @staticmethod
    def stored_or_deleted_names(site) -> frozenset[str]:
        return frozenset(
            node.id
            for node in ast.walk(site.node)
            if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del))
        )
