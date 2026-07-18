from __future__ import annotations

import ast
from dataclasses import dataclass

from sugar_lift_py_tests.factory.block import Block
@dataclass(frozen=True)
class LoopControlScopeClassification:
    """Sugar-owned testimony about one loop/control-flow source scope."""

    carried_names: tuple[str, ...]
    stored_names: tuple[str, ...]
    has_loop_control: bool
    has_owned_break: bool
    has_unclassified_mutation: bool
    definite_break_output_names: tuple[str, ...]
    contains_terminal_control: bool
    target_bindings: tuple[tuple[str, tuple[int, ...]], ...] | None


class LoopControlScopeRecognition:
    """Structural recognition for loop, control-block, and target-pattern scopes."""

    _OWNED_KINDS = frozenset(
        {
            "For",
            "While",
            "Block",
            "Name",
            "Tuple",
            "List",
            "Starred",
            "Attribute",
            "Subscript",
        }
    )

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed in cls._OWNED_KINDS

    @classmethod
    def own_scope_stored_names(cls, site) -> tuple[str, ...]:
        names: list[str] = []

        class OwnScopeStores(ast.NodeVisitor):
            def visit_Name(self, node: ast.Name) -> None:
                if isinstance(node.ctx, ast.Store) and node.id not in names:
                    names.append(node.id)

            def stop_at_nested_owner(self, node: ast.AST) -> None:
                del node

            visit_Lambda = stop_at_nested_owner
            visit_FunctionDef = stop_at_nested_owner
            visit_AsyncFunctionDef = stop_at_nested_owner
            visit_ClassDef = stop_at_nested_owner
            visit_ListComp = stop_at_nested_owner
            visit_SetComp = stop_at_nested_owner
            visit_DictComp = stop_at_nested_owner
            visit_GeneratorExp = stop_at_nested_owner

        roots = site.node.body if isinstance(site.node, Block) else (site.node,)
        visitor = OwnScopeStores()
        for root in roots:
            visitor.visit(root)
        return tuple(names)

    @classmethod
    def loop_stored_names(cls, site) -> tuple[str, ...]:
        names: list[str] = []
        for node in ast.walk(site.node):
            if (
                isinstance(node, ast.Name)
                and isinstance(node.ctx, ast.Store)
                and node.id not in names
            ):
                names.append(node.id)
            if (
                isinstance(node, ast.Subscript)
                and isinstance(node.ctx, ast.Store)
                and isinstance(node.value, ast.Name)
                and node.value.id not in names
            ):
                names.append(node.value.id)
        return tuple(names)

    @classmethod
    def has_unclassified_loop_mutation(cls, site) -> bool:
        for node in ast.walk(site.node):
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                targets = (
                    node.targets if isinstance(node, ast.Assign) else (node.target,)
                )
                for target in targets:
                    if isinstance(target, (ast.Name, ast.Tuple)):
                        continue
                    if isinstance(target, ast.Subscript) and isinstance(
                        target.value, ast.Name
                    ):
                        continue
                    return True
        return False

    @classmethod
    def loop_carried_names(
        cls,
        site,
        *,
        target_name: str | None = None,
        entry_reads: tuple = (),
    ) -> tuple[str, ...]:
        if target_name is None and isinstance(site.node, ast.For):
            target_name = site.for_target_name()
        candidates_list: list[str] = []

        class CandidateStores(ast.NodeVisitor):
            def add(self, name: str) -> None:
                if name != target_name and name not in candidates_list:
                    candidates_list.append(name)

            def visit_Name(self, node: ast.Name) -> None:
                if isinstance(node.ctx, ast.Store):
                    self.add(node.id)

            def visit_Subscript(self, node: ast.Subscript) -> None:
                if isinstance(node.ctx, ast.Store) and isinstance(node.value, ast.Name):
                    self.add(node.value.id)
                self.generic_visit(node)

            def stop_at_nested_owner(self, node: ast.AST) -> None:
                del node

            visit_Lambda = stop_at_nested_owner
            visit_FunctionDef = stop_at_nested_owner
            visit_AsyncFunctionDef = stop_at_nested_owner
            visit_ClassDef = stop_at_nested_owner
            visit_ListComp = stop_at_nested_owner
            visit_SetComp = stop_at_nested_owner
            visit_DictComp = stop_at_nested_owner
            visit_GeneratorExp = stop_at_nested_owner

        for statement in site.node.body:
            CandidateStores().visit(statement)
        candidates = tuple(candidates_list)
        candidate_set = set(candidates)
        carried: set[str] = set()

        def note_loads(node: ast.AST | None, assigned: set[str]) -> None:
            if node is None:
                return
            for child in ast.walk(node):
                if (
                    isinstance(child, ast.Name)
                    and isinstance(child.ctx, ast.Load)
                    and child.id in candidate_set
                    and child.id not in assigned
                ):
                    carried.add(child.id)

        def stored_names(node: ast.AST) -> set[str]:
            return {
                child.id
                for child in ast.walk(node)
                if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store)
            }

        def scan_block(statements, assigned: set[str]) -> set[str] | None:
            current = set(assigned)
            for statement in statements:
                result = scan_statement(statement, current)
                if result is None:
                    return None
                current = result
            return current

        def merge_fallthrough(*arms: set[str] | None) -> set[str] | None:
            live = [arm for arm in arms if arm is not None]
            if not live:
                return None
            merged = set(live[0])
            for arm in live[1:]:
                merged.intersection_update(arm)
            return merged

        def scan_statement(statement: ast.stmt, assigned: set[str]):
            current = set(assigned)
            if isinstance(statement, ast.Assign):
                note_loads(statement.value, current)
                for target in statement.targets:
                    if not isinstance(target, (ast.Name, ast.Tuple, ast.List)):
                        note_loads(target, current)
                    current.update(stored_names(target))
                return current
            if isinstance(statement, ast.AnnAssign):
                note_loads(statement.annotation, current)
                note_loads(statement.value, current)
                if not isinstance(statement.target, (ast.Name, ast.Tuple, ast.List)):
                    note_loads(statement.target, current)
                current.update(stored_names(statement.target))
                return current
            if isinstance(statement, ast.AugAssign):
                note_loads(statement.target, current)
                if (
                    isinstance(statement.target, ast.Name)
                    and statement.target.id in candidate_set
                    and statement.target.id not in current
                ):
                    carried.add(statement.target.id)
                note_loads(statement.value, current)
                current.update(stored_names(statement.target))
                return current
            if isinstance(statement, ast.If):
                note_loads(statement.test, current)
                return merge_fallthrough(
                    scan_block(statement.body, current),
                    scan_block(statement.orelse, current),
                )
            if isinstance(statement, (ast.For, ast.AsyncFor)):
                note_loads(statement.iter, current)
                nested = set(current)
                nested.update(stored_names(statement.target))
                scan_block(statement.body, nested)
                scan_block(statement.orelse, current)
                return current
            if isinstance(statement, ast.While):
                note_loads(statement.test, current)
                scan_block(statement.body, current)
                scan_block(statement.orelse, current)
                return current
            if isinstance(statement, ast.Try):
                body = scan_block(statement.body, current)
                normal = (
                    scan_block(statement.orelse, body) if body is not None else None
                )
                handlers = [
                    scan_block(handler.body, current) for handler in statement.handlers
                ]
                merged = merge_fallthrough(normal, *handlers)
                if statement.finalbody:
                    return (
                        scan_block(statement.finalbody, merged)
                        if merged is not None
                        else None
                    )
                return merged
            if isinstance(statement, (ast.With, ast.AsyncWith)):
                for item in statement.items:
                    note_loads(item.context_expr, current)
                    if item.optional_vars is not None:
                        current.update(stored_names(item.optional_vars))
                return scan_block(statement.body, current)
            if isinstance(statement, ast.Match):
                note_loads(statement.subject, current)
                arms = []
                for case in statement.cases:
                    arm = set(current)
                    arm.update(stored_names(case.pattern))
                    note_loads(case.guard, arm)
                    arms.append(scan_block(case.body, arm))
                return merge_fallthrough(current, *arms)
            if isinstance(statement, (ast.Break, ast.Continue, ast.Return, ast.Raise)):
                note_loads(getattr(statement, "value", None), current)
                note_loads(getattr(statement, "exc", None), current)
                note_loads(getattr(statement, "cause", None), current)
                return None

            note_loads(statement, current)
            current.update(stored_names(statement))
            return current

        for entry_read in entry_reads:
            note_loads(entry_read.node, set())
        scan_block(
            site.node.body,
            {target_name} if target_name is not None else set(),
        )
        return tuple(name for name in candidates if name in carried)

    @classmethod
    def while_definite_break_output_names(cls, site) -> tuple[str, ...]:
        if not (
            isinstance(site.node.test, ast.Constant) and site.node.test.value is True
        ):
            return ()

        break_bindings: list[set[str]] = []
        outer_break_count = 0

        class OuterBreakCounter(ast.NodeVisitor):
            def visit_Break(self, node: ast.Break) -> None:
                nonlocal outer_break_count
                outer_break_count += 1

            def stop_at_nested_owner(self, node: ast.AST) -> None:
                del node

            visit_For = stop_at_nested_owner
            visit_AsyncFor = stop_at_nested_owner
            visit_While = stop_at_nested_owner
            visit_Lambda = stop_at_nested_owner
            visit_FunctionDef = stop_at_nested_owner
            visit_AsyncFunctionDef = stop_at_nested_owner
            visit_ClassDef = stop_at_nested_owner

        break_counter = OuterBreakCounter()
        for statement in site.node.body:
            break_counter.visit(statement)

        def stored_names(node: ast.AST) -> set[str]:
            return {
                child.id
                for child in ast.walk(node)
                if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store)
            }

        def merge_fallthrough(*arms: set[str] | None) -> set[str] | None:
            live = [arm for arm in arms if arm is not None]
            if not live:
                return None
            merged = set(live[0])
            for arm in live[1:]:
                merged.intersection_update(arm)
            return merged

        def scan_block(
            statements: list[ast.stmt], assigned: set[str]
        ) -> set[str] | None:
            current = set(assigned)
            for statement in statements:
                result = scan_statement(statement, current)
                if result is None:
                    return None
                current = result
            return current

        def scan_statement(statement: ast.stmt, assigned: set[str]) -> set[str] | None:
            current = set(assigned)
            if isinstance(statement, ast.Assign):
                for target in statement.targets:
                    current.update(stored_names(target))
                return current
            if isinstance(statement, ast.AnnAssign):
                if statement.value is not None:
                    current.update(stored_names(statement.target))
                return current
            if isinstance(statement, ast.AugAssign):
                return current
            if isinstance(statement, ast.If):
                return merge_fallthrough(
                    scan_block(statement.body, current),
                    scan_block(statement.orelse, current),
                )
            if isinstance(statement, ast.Break):
                break_bindings.append(current)
                return None
            if isinstance(statement, (ast.Continue, ast.Return, ast.Raise)):
                return None
            if isinstance(statement, (ast.For, ast.AsyncFor, ast.While)):
                return current
            if isinstance(statement, ast.Try):
                body = scan_block(statement.body, current)
                normal = (
                    scan_block(statement.orelse, body) if body is not None else None
                )
                handlers = [
                    scan_block(handler.body, current) for handler in statement.handlers
                ]
                merged = merge_fallthrough(normal, *handlers)
                if statement.finalbody:
                    return (
                        scan_block(statement.finalbody, merged)
                        if merged is not None
                        else None
                    )
                return merged
            if isinstance(statement, (ast.With, ast.AsyncWith)):
                return scan_block(statement.body, current)
            return current

        scan_block(site.node.body, set())
        if not break_bindings or len(break_bindings) != outer_break_count:
            return ()
        definite = set(break_bindings[0])
        for binding_set in break_bindings[1:]:
            definite.intersection_update(binding_set)
        ordered = cls.own_scope_stored_names(site.while_body_block())
        return tuple(name for name in ordered if name in definite)

    @classmethod
    def classify(
        cls,
        site,
        *,
        target_name: str | None = None,
        entry_reads: tuple = (),
    ) -> LoopControlScopeClassification:
        is_loop = isinstance(site.node, (ast.For, ast.While))
        carried_names = (
            cls.loop_carried_names(
                site,
                target_name=target_name,
                entry_reads=entry_reads,
            )
            if is_loop
            else ()
        )
        stored_names = (
            cls.loop_stored_names(site)
            if is_loop
            else cls.own_scope_stored_names(site)
        )

        class OwnedLoopControl(ast.NodeVisitor):
            has_break = False
            has_continue = False

            def visit_Break(self, node: ast.Break) -> None:
                del node
                self.has_break = True

            def visit_Continue(self, node: ast.Continue) -> None:
                del node
                self.has_continue = True

            def stop_at_nested_owner(self, node: ast.AST) -> None:
                del node

            visit_For = stop_at_nested_owner
            visit_AsyncFor = stop_at_nested_owner
            visit_While = stop_at_nested_owner
            visit_FunctionDef = stop_at_nested_owner
            visit_AsyncFunctionDef = stop_at_nested_owner
            visit_Lambda = stop_at_nested_owner
            visit_ClassDef = stop_at_nested_owner

        control = OwnedLoopControl()
        roots = (
            site.node.body
            if is_loop or isinstance(site.node, Block)
            else (site.node,)
        )
        for root in roots:
            control.visit(root)

        terminal_types = (ast.Return, ast.Raise, ast.Break, ast.Continue)
        contains_terminal_control = any(
            isinstance(descendant, terminal_types)
            for root in roots
            for descendant in ast.walk(root)
        )

        def target_bindings(
            node: ast.AST, path: tuple[int, ...]
        ) -> tuple[tuple[str, tuple[int, ...]], ...] | None:
            if isinstance(node, ast.Name):
                return ((node.id, path),)
            if isinstance(node, (ast.Tuple, ast.List)):
                bindings: list[tuple[str, tuple[int, ...]]] = []
                for index, element in enumerate(node.elts):
                    nested = target_bindings(element, (*path, index))
                    if nested is None:
                        return None
                    bindings.extend(nested)
                return tuple(bindings)
            return None

        return LoopControlScopeClassification(
            carried_names=carried_names,
            stored_names=stored_names,
            has_loop_control=control.has_break or control.has_continue,
            has_owned_break=control.has_break,
            has_unclassified_mutation=(
                cls.has_unclassified_loop_mutation(site) if is_loop else False
            ),
            definite_break_output_names=(
                cls.while_definite_break_output_names(site)
                if isinstance(site.node, ast.While)
                else ()
            ),
            contains_terminal_control=contains_terminal_control,
            target_bindings=target_bindings(site.node, ()),
        )
