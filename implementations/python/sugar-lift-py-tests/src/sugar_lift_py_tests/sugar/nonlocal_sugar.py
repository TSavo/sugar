from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field, replace

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.factory import factory_panic_gap
from sugar_lift_py_tests.floor import FloorValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


def reject_unconstructed_nonlocal_store(ctx: object, name: str) -> None:
    """Keep cross-frame stores loud until their caller rebind is constructed."""

    if name not in getattr(ctx, "nonlocal_names", frozenset()):
        return
    factory_panic_gap(
        owner="NonlocalRoute",
        blame=name,
        observed=name,
        requested="enclosing-frame mutation",
        fix=(
            "construct a caller-visible enclosing-frame rebind; never treat "
            "the store as function-local and never mint a RuntimeEffect"
        ),
    )


@dataclass(frozen=True)
class NonlocalRoute(FloorValue):
    """A read route to names already present in the captured lexical temporal."""

    names: tuple[str, ...]

    def contribution(self):  # pyright: ignore[reportIncompatibleMethodOverride]
        return ()

    def extend_scope(self, ctx):
        for name in self.names:
            if ctx.temporal.value_if_bound(name) is None:
                factory_panic_gap(
                    owner="NonlocalSugar",
                    blame=name,
                    observed=name,
                    requested="bound enclosing lexical name",
                    fix=(
                        "construct the function through a lexical context that "
                        "already binds every declared nonlocal name"
                    ),
                )
        return replace(
            ctx,
            nonlocal_names=ctx.nonlocal_names | frozenset(self.names),
        )


@dataclass(frozen=True)
class NonlocalSugar(Sugar, role=SugarRole.STATEMENT):
    """Route read-only declarations to the captured enclosing lexical frame."""

    names: tuple[str, ...]
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, fragment) -> bool:
        return fragment.observed == "Nonlocal"

    @classmethod
    def new(cls, site, ctx) -> "NonlocalSugar":
        del ctx
        names = tuple(site.node.names)
        source = site.source
        if not isinstance(source, str):
            factory_panic_gap(
                owner=cls.__name__,
                blame=site,
                observed=names[0] if len(names) == 1 else names,
                requested="bound enclosing lexical name",
                fix="construct NonlocalSugar from its complete lexical source",
            )
        try:
            compile(source, site.filename, "exec")
        except SyntaxError:
            factory_panic_gap(
                owner=cls.__name__,
                blame=site,
                observed=names[0] if len(names) == 1 else names,
                requested="bound enclosing lexical name",
                fix=(
                    "bind every declared name in an enclosing function scope; "
                    "an invalid nonlocal declaration cannot be lifted"
                ),
            )
        return cls(names=names, site=site)

    @classmethod
    def witnesses(cls):
        prefix = (
            "def A(z):\n"
            "    shared = z\n"
            "    def inner():\n"
            "        nonlocal shared\n"
            "        return shared\n"
            "    return inner()\n"
            "\n"
        )
        return _call_pair(
            name="nonlocal_enclosing_read",
            owner_sugar=cls.__name__,
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 6\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return Complete(NonlocalRoute(self.names))

    def walk_children(self):
        return ()
