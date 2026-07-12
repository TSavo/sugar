from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody
from sugar_lift_py_tests.sugar.while_sugar import (
    _carried_names,
    _has_loop_control,
    _has_unclassified_mutation,
)


@dataclass(frozen=True)
class ForSugar(Sugar, role=SugarRole.STATEMENT):
    """`for <name> in <iter>: <body>` -- thread the body over the iter element.

    Recognition + scope threading, not loop unrolling: reduce the iterable to
    its coordinate, bind the simple-Name target to an element coordinate
    ctor("py.iter_elem", [iter_term]), then reduce the body under that extended
    scope. The For is a scope+sequence construct: its outcome is the body's
    BlockValue, which splices into the enclosing record.

    Owns only simple-Name targets with empty orelse. Tuple/starred targets and
    non-empty `else:` clauses stay unowned (loud factory gap) -- never silently
    drop the iterable, body, or orelse. AsyncFor is a different observed kind
    and is not owned here.
    """

    target_name: str
    iterable: SugarBody
    body: SugarBody
    carried: tuple[str, ...]
    curried: bool
    unclassified_mutation: bool
    static_elements: tuple[SugarBody, ...] | None
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "For":
            return False
        # Simple Name target only; tuple/starred stays a loud gap.
        if site.for_target_name() is None:
            return False
        # Non-empty else: is not threaded this arm -- require empty orelse.
        if site.for_orelse_count() != 0:
            return False
        return True

    @classmethod
    def new(cls, site, ctx) -> "ForSugar":
        # Iterable (TERM), target name, body block (STATEMENT). Never reduce here.
        static_elements = _static_iterable_elements(site.for_iter(), ctx, site)
        return cls(
            target_name=site.for_target_name(),
            iterable=ctx.build_body(site.for_iter(), SugarRole.TERM),
            body=ctx.build_body(site.for_body_block(), SugarRole.STATEMENT),
            carried=tuple(
                name for name in _carried_names(site) if name != site.for_target_name()
            ),
            curried=_has_loop_control(site),
            unclassified_mutation=_has_unclassified_mutation(site),
            static_elements=static_elements,
            site=site,
        )

    @classmethod
    def witnesses(cls):
        # Loop body return face: truthful rides 1, lying asserts 0.
        prefix = (
            "def A(z):\n"
            "    for x in z:\n"
            "        return 1\n"
            "    return 0\n"
            "\n"
        )
        return _call_pair(
            name="for_return",
            owner_sugar="ForSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 1\n",
            lying=prefix + "def test_a():\n    assert A(5) == 0\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        if self.static_elements is not None:
            return self._unfold_static(self.static_elements, ctx)
        # Reduce the iterable; bind target to the element coordinate; thread body.
        return self.iterable.reduce(ctx).and_then(
            lambda iterable: self._bind_and_body(iterable, ctx)
        )

    def _unfold_static(self, remaining, ctx, entries=()):
        from sugar_lift_py_tests.floor import BlockValue, ScopeRebind

        if not remaining:
            bindings = tuple(
                ScopeRebind(name, value)
                for name in self.carried
                if (value := ctx.temporal.value_if_bound(name)) is not None
            )
            return Complete(BlockValue((*entries, *bindings)))
        head, *rest = remaining
        return head.reduce(ctx).and_then(
            lambda element: self._unfold_iteration(
                element, tuple(rest), ctx, entries
            )
        )

    def _unfold_iteration(self, element, remaining, ctx, entries):
        from sugar_lift_py_tests.floor import ScopeRebind

        iteration_ctx = ScopeRebind(self.target_name, element).extend_scope(ctx)
        record, next_ctx = self.body.sugar.reduce_with_scope(iteration_ctx)
        return self._unfold_static(
            remaining,
            next_ctx,
            (*entries, *record.contribution()),
        )

    def _bind_and_body(self, iterable, ctx: object) -> Outcome:
        from sugar_lift_py_tests.floor import CallSiteValue, ScopeRebind
        from sugar_lift_py_tests.ir import ctor

        # Element of the iterable -- recognition coordinate, not unrolled history.
        elem = CallSiteValue(
            target_name="iter_elem",
            arg_values=(iterable,),
            parameters=(),
            term=ctor(
                "py.iter_elem",
                [iterable.to_term(owner=str(self.site))],
            ),
            body=None,
            site=self.site,
        )
        body_ctx = ScopeRebind(self.target_name, elem).extend_scope(ctx)
        if self.curried:
            from sugar_lift_py_tests.floor import CurriedLoopBody, CurriedLoopScope, FunctionCallable
            from sugar_lift_py_tests.sugar.install_source_dig import _contextualized_dig_body

            if self.unclassified_mutation:
                from sugar_lift_py_tests.factory import factory_panic_gap

                factory_panic_gap(
                    owner="ForSugar", blame=str(self.site), observed="nonlocal mutation",
                    requested="classifiable loop-carried local state",
                    fix="rewrite attribute or subscript mutation as explicit carried locals",
                )

            values = tuple(body_ctx.temporal.value_if_bound(name) for name in self.carried)
            if all(value is not None for value in values):
                name = f"loop:{self.site}"
                body = _contextualized_dig_body(
                    SugarBody(
                        sugar=CurriedLoopBody(self.body, self.carried),
                        role=SugarRole.TERM,
                    ),
                    body_ctx,
                )
                callable_value = FunctionCallable(
                    name=name, parameters=self.carried,
                    parameter_kinds=("positional",) * len(self.carried), body=body,
                )
                callsite = callable_value.callsite(values, (), self.site).value
                return Complete(CurriedLoopScope(callsite, self.carried))
            from sugar_lift_py_tests.factory import factory_panic_gap

            factory_panic_gap(
                owner="ForSugar",
                blame=str(self.site),
                observed=self.carried,
                requested="statically bound loop-carried locals",
                fix="bind every carried local before currying the loop",
            )
        # Body is a BlockSugar; its BlockValue contribution splices outward.
        return self.body.reduce(body_ctx)

    def walk_children(self):
        return (
            self.iterable,
            self.body,
            *(self.static_elements or ()),
        )


def _static_iterable_elements(iterable_site, ctx, loop_site):
    import ast

    node = iterable_site.node
    values = None
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "range":
        if node.keywords or not 1 <= len(node.args) <= 3:
            return None
        if not all(isinstance(arg, ast.Constant) and type(arg.value) is int for arg in node.args):
            return None
        values = tuple(range(*(arg.value for arg in node.args)))
    elif isinstance(node, (ast.Tuple, ast.List)):
        values = tuple(element for element in node.elts)
    else:
        return None

    if len(values) > 64:
        from sugar_lift_py_tests.factory import factory_panic_gap

        factory_panic_gap(
            owner="ForSugar.static_unfold",
            blame=str(loop_site),
            observed=f"statically finite iterable with {len(values)} elements",
            requested="at most 64 concrete loop self-applications",
            fix="reduce the literal iterable size or raise the reviewed unfold cap",
        )
    return tuple(
        ctx.build_body(
            ast.copy_location(ast.Constant(value=value), node)
            if not isinstance(value, ast.AST)
            else value,
            SugarRole.TERM,
        )
        for value in values
    )
