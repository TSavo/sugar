from __future__ import annotations

import ast
from dataclasses import dataclass

from sugar_lift_py_tests.sugar.loop_control_scope_sugar import (
    LoopControlScopeSugar,
)
from sugar_lift_py_tests.source_fragment import SourceFragment


@dataclass(frozen=True)
class SetCompRecognition:
    """Construction-closed target bindings for one native set comprehension."""

    clause_bindings: tuple[tuple[tuple[str, tuple[int, ...]], ...], ...]

    @classmethod
    def classify(cls, site) -> "SetCompRecognition | None":
        if site.observed != "SetComp":
            return None
        generators = site.setcomp_generators()
        if not generators:
            return None
        loaded_names = frozenset(
            node.id
            for node in ast.walk(site.node)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
        )
        clauses: list[tuple[tuple[str, tuple[int, ...]], ...]] = []
        for generator in generators:
            if generator.comprehension_is_async():
                return None
            target = generator.comprehension_target()
            bindings = LoopControlScopeSugar.classify(target).target_bindings
            if bindings is None:
                bindings = cls._discarded_starred_bindings(target, loaded_names)
            if bindings is None:
                return None
            clauses.append(bindings)
        return cls(clause_bindings=tuple(clauses))

    @classmethod
    def owns(cls, site) -> bool:
        return cls.classify(site) is not None

    @staticmethod
    def _discarded_starred_bindings(
        target,
        loaded_names: frozenset[str],
    ) -> tuple[tuple[str, tuple[int, ...]], ...] | None:
        node = target.node
        if not isinstance(node, (ast.Tuple, ast.List)):
            return None
        starred = [
            (index, element)
            for index, element in enumerate(node.elts)
            if isinstance(element, ast.Starred)
        ]
        if len(starred) != 1:
            return None
        star_index, star = starred[0]
        if not isinstance(star.value, ast.Name) or star.value.id in loaded_names:
            return None

        bindings: list[tuple[str, tuple[int, ...]]] = []
        for index, element in enumerate(node.elts):
            if index == star_index:
                continue
            fragment = SourceFragment.from_node(
                element,
                target.filename,
                source=target.source,
            )
            nested = LoopControlScopeSugar.classify(fragment).target_bindings
            if nested is None:
                return None
            root_index = index if index < star_index else index - len(node.elts)
            bindings.extend((name, (root_index, *path)) for name, path in nested)
        return tuple(bindings)


__all__ = ["SetCompRecognition"]
