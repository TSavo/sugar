from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.list_comp_sugar import _floor_as_term
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class DictCompSugar(Sugar, role=SugarRole.TERM):
    """A dict comprehension ``{<key>: <value> for <target> in <iter> (if <cond>)*}``.

    Single-generator, simple-Name target only. Multi-generator and
    tuple-unpack targets stay unowned (loud factory gap).

    LAW: do not enumerate the iterable. Reduce the iter to its coordinate,
    bind the target to ``py.iter_elem(iter)``, reduce key AND value (never
    drop either) plus conditions under that extended scope, and build
    ``py.dictcomp(key_term, value_term, iter_term, *cond_terms)``.
    """

    target_name: str
    iter_body: SugarBody
    key_body: SugarBody
    value_body: SugarBody
    condition_bodies: tuple[SugarBody, ...]
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "DictComp":
            return False
        generators = site.dictcomp_generators()
        if len(generators) != 1:
            return False
        gen = generators[0]
        if gen.comprehension_is_async():
            return False
        target = gen.comprehension_target()
        return target.observed == "Name"

    @classmethod
    def new(cls, site, ctx) -> "DictCompSugar":
        gen = site.dictcomp_generators()[0]
        return cls(
            target_name=gen.comprehension_target().name_id(),
            iter_body=ctx.build_body(gen.comprehension_iter(), SugarRole.TERM),
            key_body=ctx.build_body(site.dictcomp_key(), SugarRole.TERM),
            value_body=ctx.build_body(site.dictcomp_value(), SugarRole.TERM),
            condition_bodies=tuple(
                ctx.build_body(guard, SugarRole.TERM)
                for guard in gen.comprehension_ifs()
            ),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        prefix = (
            "def A(z):\n"
            "    y = {x: x for x in z}\n"
            "    return 1\n"
            "\n"
        )
        return _call_pair(
            name="dict_comp_return",
            owner_sugar="DictCompSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 1\n",
            lying=prefix + "def test_a():\n    assert A(5) == 0\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self.iter_body.reduce(ctx).and_then(
            lambda iterable: self._bind_and_collect(iterable, ctx)
        )

    def _bind_and_collect(self, iterable, ctx: object) -> Outcome:
        from sugar_lift_py_tests.floor import ListValue, TupleValue

        if not self.condition_bodies and isinstance(iterable, (ListValue, TupleValue)):
            return self._collect_finite(iterable.elements, (), ctx)
        from sugar_lift_py_tests.floor import ScopeRebind, SymbolicValue
        from sugar_lift_py_tests.ir import ctor

        owner = str(self.site)
        iter_term = iterable.to_term(owner=owner)
        element = SymbolicValue(ctor("py.iter_elem", [iter_term]))
        bound_ctx = ScopeRebind(self.target_name, element).extend_scope(ctx)
        # Key then value -- both ride; neither is dropped.
        return self.key_body.reduce(bound_ctx).and_then(
            lambda key: self.value_body.reduce(bound_ctx).and_then(
                lambda value: self._collect_conditions(
                    remaining=self.condition_bodies,
                    accumulated=(),
                    key=key,
                    value=value,
                    iterable=iterable,
                    bound_ctx=bound_ctx,
                )
            )
        )

    def _collect_finite(self, remaining, accumulated, ctx):
        from sugar_lift_py_tests.floor import DictValue, ScopeRebind

        if not remaining:
            return Complete(DictValue(accumulated))
        item, *rest = remaining
        item_ctx = ScopeRebind(self.target_name, item).extend_scope(ctx)
        return self.key_body.reduce(item_ctx).and_then(
            lambda key: self.value_body.reduce(item_ctx).and_then(
                lambda value: self._collect_finite(
                    tuple(rest),
                    self._dict_set(accumulated, key, value),
                    ctx,
                )
            )
        )

    @staticmethod
    def _dict_set(entries, key, value):
        updated = list(entries)
        for index, (existing_key, _existing_value) in enumerate(updated):
            if existing_key == key:
                updated[index] = (key, value)
                return tuple(updated)
        return (*entries, (key, value))

    def _collect_conditions(
        self,
        remaining: tuple,
        accumulated: tuple,
        key,
        value,
        iterable,
        bound_ctx: object,
    ) -> Outcome:
        if not remaining:
            from sugar_lift_py_tests.floor import ComprehensionValue
            from sugar_lift_py_tests.ir import ctor

            owner = str(self.site)
            return Complete(
                ComprehensionValue(
                    ctor(
                        "py.dictcomp",
                        [
                            _floor_as_term(key, owner=owner),
                            _floor_as_term(value, owner=owner),
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
                key=key,
                value=value,
                iterable=iterable,
                bound_ctx=bound_ctx,
            )
        )

    def walk_children(self):
        return (
            self.key_body,
            self.value_body,
            self.iter_body,
            *self.condition_bodies,
        )
