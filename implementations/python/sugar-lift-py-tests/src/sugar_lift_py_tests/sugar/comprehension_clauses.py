from __future__ import annotations

import ast
from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class ComprehensionClause:
    bindings: tuple[tuple[str, tuple[int, ...]], ...]
    iterable: SugarBody
    conditions: tuple[SugarBody, ...]


def supports_clauses(generators) -> bool:
    return bool(generators) and all(
        not generator.comprehension_is_async()
        and _target_bindings(generator.comprehension_target()) is not None
        for generator in generators
    )


def build_clauses(generators, ctx) -> tuple[ComprehensionClause, ...]:
    return tuple(
        ComprehensionClause(
            bindings=_target_bindings(generator.comprehension_target()),
            iterable=ctx.build_body(generator.comprehension_iter(), SugarRole.TERM),
            conditions=tuple(
                ctx.build_body(condition, SugarRole.TERM)
                for condition in generator.comprehension_ifs()
            ),
        )
        for generator in generators
    )


def reduce_clauses(clauses, ctx, finish, *, first_iterable=None):
    return _reduce_clause(clauses, 0, ctx, (), finish, first_iterable)


def _reduce_clause(clauses, index, ctx, accumulated, finish, first_iterable):
    if index == len(clauses):
        from sugar_lift_py_tests.ir import ctor

        args = (
            accumulated[0].args
            if len(accumulated) == 1
            else (ctor("py.generators", accumulated),)
        )
        return finish(ctx, args)

    clause = clauses[index]
    from sugar_lift_py_tests.outcome import Complete

    iterable_outcome = (
        Complete(first_iterable)
        if index == 0 and first_iterable is not None
        else clause.iterable.reduce(ctx)
    )
    return iterable_outcome.and_then(
        lambda iterable: _bind_and_filter(
            clauses,
            index,
            clause,
            iterable,
            ctx,
            accumulated,
            finish,
            first_iterable,
        )
    )


def _bind_and_filter(
    clauses, index, clause, iterable, ctx, accumulated, finish, first_iterable
):
    from sugar_lift_py_tests.floor import ScopeRebind, SymbolicValue
    from sugar_lift_py_tests.ir import ctor, num

    iterable_term = iterable.to_term(owner="comprehension iterable")
    element = SymbolicValue(ctor("py.iter_elem", [iterable_term]))
    bound_ctx = ctx
    for name, path in clause.bindings:
        value = element
        for position in path:
            value = SymbolicValue(
                ctor("py.subscript", [value.to_term(owner=name), num(position)])
            )
        bound_ctx = ScopeRebind(name, value).extend_scope(bound_ctx)
    return _reduce_conditions(
        clause.conditions,
        0,
        bound_ctx,
        (),
        lambda conditions: _reduce_clause(
            clauses,
            index + 1,
            bound_ctx,
            (
                *accumulated,
                ctor("py.comprehension_clause", [iterable_term, *conditions]),
            ),
            finish,
            first_iterable,
        ),
    )


def _reduce_conditions(conditions, index, ctx, accumulated, finish):
    if index == len(conditions):
        return finish(accumulated)
    return conditions[index].reduce(ctx).and_then(
        lambda value: _reduce_conditions(
            conditions,
            index + 1,
            ctx,
            (*accumulated, value.to_term(owner="comprehension condition")),
            finish,
        )
    )


def _target_bindings(target):
    def walk(node, path):
        if isinstance(node, ast.Name):
            return ((node.id, path),)
        if isinstance(node, (ast.Tuple, ast.List)):
            bindings = []
            for index, element in enumerate(node.elts):
                nested = walk(element, (*path, index))
                if nested is None:
                    return None
                bindings.extend(nested)
            return tuple(bindings)
        return None

    return walk(target.node, ())


def clause_children(clauses):
    return tuple(
        child
        for clause in clauses
        for child in (clause.iterable, *clause.conditions)
    )
