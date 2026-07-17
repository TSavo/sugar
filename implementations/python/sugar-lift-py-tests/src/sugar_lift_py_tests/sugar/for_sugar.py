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

STATIC_UNFOLD_LIMIT = 1024


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
            carried=_loop_carried_names(site),
            curried=_has_loop_control(site),
            unclassified_mutation=_has_unclassified_mutation(site),
            static_elements=static_elements,
            site=site,
        )

    @classmethod
    def witnesses(cls):
        # The iteration-local assignment is not a carried input.  The continue
        # makes the loop curried; the post-loop return is still verdict-bearing.
        prefix = (
            "def A(z):\n"
            "    for x in z:\n"
            "        if x == 0:\n"
            "            continue\n"
            "        local = 1\n"
            "    return 0\n"
            "\n"
        )
        large_static_prefix = (
            "def B():\n"
            "    for x in range(65):\n"
            "        pass\n"
            "    return 0\n"
            "\n"
        )
        return (
            _call_pair(
                name="for_return",
                owner_sugar="ForSugar",
                truthful=prefix + "def test_a():\n    assert A(5) == 0\n",
                lying=prefix + "def test_a():\n    assert A(5) == 1\n",
            ),
            _call_pair(
                name="for_large_static_unfold",
                owner_sugar="ForSugar",
                truthful=large_static_prefix + "def test_b():\n    assert B() == 0\n",
                lying=large_static_prefix + "def test_b():\n    assert B() == 1\n",
            ),
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
        from sugar_lift_py_tests.outcome import Incomplete

        accumulated = list(entries)
        current_ctx = ctx
        for element_body in remaining:
            outcome = element_body.reduce(current_ctx)
            if isinstance(outcome, Incomplete):
                return outcome
            iteration_ctx = ScopeRebind(self.target_name, outcome.value).extend_scope(
                current_ctx
            )
            record, current_ctx = self.body.sugar.reduce_with_scope(iteration_ctx)
            accumulated.extend(record.contribution())
        bindings = tuple(
            ScopeRebind(name, value)
            for name in self.carried
            if (value := current_ctx.temporal.value_if_bound(name)) is not None
        )
        return Complete(BlockValue((*accumulated, *bindings)))

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
            from sugar_lift_py_tests.floor import (
                CurriedLoopBody,
                CurriedLoopScope,
                FunctionCallable,
            )
            from sugar_lift_py_tests.sugar.install_source_dig import (
                _contextualized_dig_body,
            )

            if self.unclassified_mutation:
                from sugar_lift_py_tests.factory import factory_panic_gap

                factory_panic_gap(
                    owner="ForSugar",
                    blame=self.site,
                    observed="nonlocal mutation",
                    requested="classifiable loop-carried local state",
                    fix="rewrite attribute or subscript mutation as explicit carried locals",
                )

            values = tuple(
                body_ctx.temporal.value_if_bound(name) for name in self.carried
            )
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
                    name=name,
                    parameters=self.carried,
                    parameter_kinds=("positional",) * len(self.carried),
                    body=body,
                )
                callsite = callable_value.callsite(values, (), self.site).value
                return Complete(CurriedLoopScope(callsite, self.carried))
            from sugar_lift_py_tests.factory import factory_panic_gap

            factory_panic_gap(
                owner="ForSugar",
                blame=self.site,
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
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "range"
    ):
        if node.keywords or not 1 <= len(node.args) <= 3:
            return None
        if not all(
            isinstance(arg, ast.Constant) and type(arg.value) is int
            for arg in node.args
        ):
            return None
        values = tuple(range(*(arg.value for arg in node.args)))
    elif isinstance(node, (ast.Tuple, ast.List)):
        values = tuple(element for element in node.elts)
    else:
        return None

    if len(values) > STATIC_UNFOLD_LIMIT:
        from sugar_lift_py_tests.factory import factory_panic_gap

        factory_panic_gap(
            owner="ForSugar.static_unfold",
            blame=loop_site,
            observed=f"statically finite iterable with {len(values)} elements",
            requested=(
                f"at most {STATIC_UNFOLD_LIMIT} concrete loop self-applications"
            ),
            fix="reduce the literal iterable size or raise the reviewed unfold cap",
        )
    return tuple(
        ctx.build_body(
            (
                ast.copy_location(ast.Constant(value=value), node)
                if not isinstance(value, ast.AST)
                else value
            ),
            SugarRole.TERM,
        )
        for value in values
    )


def _loop_carried_names(site) -> tuple[str, ...]:
    """Return stored locals whose prior value can be read in an iteration.

    A store alone does not make a local loop-carried.  Iteration temporaries and
    nested-loop targets are parameters only when some reachable path reads their
    old value before definitely assigning the new one.
    """

    import ast

    target_name = site.for_target_name()
    candidates_list: list[str] = []

    class CandidateStores(ast.NodeVisitor):
        def add(self, name):
            if name != target_name and name not in candidates_list:
                candidates_list.append(name)

        def visit_Name(self, node):
            if isinstance(node.ctx, ast.Store):
                self.add(node.id)

        def visit_Subscript(self, node):
            if isinstance(node.ctx, ast.Store) and isinstance(node.value, ast.Name):
                self.add(node.value.id)
            self.generic_visit(node)

        # These bodies introduce their own local binding scope.
        def visit_Lambda(self, node):
            return None

        def visit_FunctionDef(self, node):
            return None

        def visit_AsyncFunctionDef(self, node):
            return None

        def visit_ClassDef(self, node):
            return None

        def visit_ListComp(self, node):
            return None

        def visit_SetComp(self, node):
            return None

        def visit_DictComp(self, node):
            return None

        def visit_GeneratorExp(self, node):
            return None

    for statement in site.node.body:
        CandidateStores().visit(statement)
    candidates = tuple(candidates_list)
    candidate_set = set(candidates)
    carried: set[str] = set()

    def note_loads(node, assigned):
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

    def stored_names(node):
        names: set[str] = set()
        for child in ast.walk(node):
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                names.add(child.id)
        return names

    def scan_block(statements, assigned):
        current = set(assigned)
        for statement in statements:
            result = scan_statement(statement, current)
            if result is None:
                return None
            current = result
        return current

    def merge_fallthrough(*arms):
        live = [arm for arm in arms if arm is not None]
        if not live:
            return None
        merged = set(live[0])
        for arm in live[1:]:
            merged.intersection_update(arm)
        return merged

    def scan_statement(statement, assigned):
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
            if isinstance(statement.target, ast.Name):
                if (
                    statement.target.id in candidate_set
                    and statement.target.id not in current
                ):
                    carried.add(statement.target.id)
            note_loads(statement.value, current)
            current.update(stored_names(statement.target))
            return current
        if isinstance(statement, ast.If):
            note_loads(statement.test, current)
            body = scan_block(statement.body, current)
            orelse = scan_block(statement.orelse, current)
            return merge_fallthrough(body, orelse)
        if isinstance(statement, (ast.For, ast.AsyncFor)):
            note_loads(statement.iter, current)
            nested = set(current)
            nested.update(stored_names(statement.target))
            scan_block(statement.body, nested)
            scan_block(statement.orelse, current)
            # A nested iterable can be empty, so its stores are not definite.
            return current
        if isinstance(statement, ast.While):
            note_loads(statement.test, current)
            scan_block(statement.body, current)
            scan_block(statement.orelse, current)
            return current
        if isinstance(statement, ast.Try):
            body = scan_block(statement.body, current)
            normal = scan_block(statement.orelse, body) if body is not None else None
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
            # No case is guaranteed to match.
            return merge_fallthrough(current, *arms)
        if isinstance(statement, (ast.Break, ast.Continue, ast.Return, ast.Raise)):
            note_loads(getattr(statement, "value", None), current)
            note_loads(getattr(statement, "exc", None), current)
            note_loads(getattr(statement, "cause", None), current)
            return None

        note_loads(statement, current)
        current.update(stored_names(statement))
        return current

    scan_block(site.node.body, {target_name})
    return tuple(name for name in candidates if name in carried)
