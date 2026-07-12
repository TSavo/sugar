from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


def _floor_as_term(value, *, owner: str):
    """Project a reduced floor value to a Term for the listcomp coordinate.

    PredicateValue owns its formula reification at the floor membrane, so
    comprehension coordinates use the same projection as every other caller.
    """
    return value.to_term(owner=owner)


@dataclass(frozen=True)
class ListCompSugar(Sugar, role=SugarRole.TERM):
    """A list comprehension ``[<elt> for <target> in <iter> (if <cond>)*]``.

    Single-generator, simple-Name target only. Multi-generator and
    tuple-unpack targets stay unowned (loud factory gap).

    LAW: do not enumerate the iterable. Reduce the iter to its coordinate,
    bind the target to ``py.iter_elem(iter)`` (element coordinate), reduce
    elt and conditions under that extended scope, and build
    ``py.listcomp(elt_term, iter_term, *cond_terms)``. Keyword / starred
    shapes are not in this arm.
    """

    target_name: str
    iter_body: SugarBody
    elt_body: SugarBody
    condition_bodies: tuple[SugarBody, ...]
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "ListComp":
            return False
        generators = site.listcomp_generators()
        # One generator first; multi-generator is a harder shape -- loud gap.
        if len(generators) != 1:
            return False
        gen = generators[0]
        if gen.comprehension_is_async():
            return False
        target = gen.comprehension_target()
        # Simple Name only; tuple-unpack target stays unowned.
        return target.observed == "Name"

    @classmethod
    def new(cls, site, ctx) -> "ListCompSugar":
        # Factory-build iter / elt / conditions (audited), never reduce here.
        # elt and conditions reference the target; they reduce under the
        # extended scope at desugar time (same pattern as With's body).
        gen = site.listcomp_generators()[0]
        return cls(
            target_name=gen.comprehension_target().name_id(),
            iter_body=ctx.build_body(gen.comprehension_iter(), SugarRole.TERM),
            elt_body=ctx.build_body(site.listcomp_element(), SugarRole.TERM),
            condition_bodies=tuple(
                ctx.build_body(guard, SugarRole.TERM)
                for guard in gen.comprehension_ifs()
            ),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        # Comprehension coordinate rides in the body; the pair discriminates
        # on the enclosing return face (coordinates stay symbolic).
        prefix = (
            "def A(z):\n"
            "    y = [x for x in z]\n"
            "    return 1\n"
            "\n"
        )
        return _call_pair(
            name="list_comp_return",
            owner_sugar="ListCompSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 1\n",
            lying=prefix + "def test_a():\n    assert A(5) == 0\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        # Reduce iter, bind target to the element coordinate, reduce elt +
        # conditions under that scope, build the comprehension coordinate.
        return self.iter_body.reduce(ctx).and_then(
            lambda iterable: self._bind_and_collect(iterable, ctx)
        )

    def _bind_and_collect(self, iterable, ctx: object) -> Outcome:
        from sugar_lift_py_tests.floor import ScopeRebind, SymbolicValue
        from sugar_lift_py_tests.ir import ctor

        owner = str(self.site)
        iter_term = iterable.to_term(owner=owner)
        # Element coordinate of the iter -- same family ForSugar would use.
        element = SymbolicValue(ctor("py.iter_elem", [iter_term]))
        bound_ctx = ScopeRebind(self.target_name, element).extend_scope(ctx)
        return self.elt_body.reduce(bound_ctx).and_then(
            lambda elt: self._collect_conditions(
                remaining=self.condition_bodies,
                accumulated=(),
                elt=elt,
                iterable=iterable,
                bound_ctx=bound_ctx,
            )
        )

    def _collect_conditions(
        self,
        remaining: tuple,
        accumulated: tuple,
        elt,
        iterable,
        bound_ctx: object,
    ) -> Outcome:
        if not remaining:
            from sugar_lift_py_tests.floor import SymbolicValue
            from sugar_lift_py_tests.ir import ctor

            owner = str(self.site)
            return Complete(
                SymbolicValue(
                    ctor(
                        "py.listcomp",
                        [
                            _floor_as_term(elt, owner=owner),
                            iterable.to_term(owner=owner),
                            *accumulated,
                        ],
                    )
                )
            )
        head, *rest = remaining
        return head.reduce(bound_ctx).and_then(
            lambda cond: self._collect_conditions(
                remaining=tuple(rest),
                accumulated=(
                    *accumulated,
                    _floor_as_term(cond, owner=str(self.site)),
                ),
                elt=elt,
                iterable=iterable,
                bound_ctx=bound_ctx,
            )
        )

    def walk_children(self):
        return (self.elt_body, self.iter_body, *self.condition_bodies)
