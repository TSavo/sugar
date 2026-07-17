from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class NameSugar(Sugar, role=SugarRole.TERM):
    """A name is nothing: it asks the temporal context what stands there, and
    the binding answers. A concrete binding folds like any value; a symbolic
    binding (a parameter's SymbolicValue) carries its provenance as the term it
    projects. An unbound name panics -- the same way it would for Python."""

    name: str
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "Name"

    @classmethod
    def new(cls, site, ctx) -> "NameSugar":
        del ctx  # a name is a leaf: nothing to build, only to look up at reduce time
        return cls(name=site.name_id(), site=site)

    @classmethod
    def witnesses(cls):
        # A parameter flows through its name to the return: the truthful twin
        # rides the identity, the lying twin asserts a different value -- the
        # pair proves the lift discriminates on what the name is bound to.
        prefix = "def A(z):\n    return z\n\n"
        return _call_pair(
            name="name_return",
            owner_sugar="NameSugar",
            truthful=prefix + "def test_a():\n    assert A(5) == 5\n",
            lying=prefix + "def test_a():\n    assert A(5) == 6\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        # Ask the context what stands at this name; the binding answers.
        # A BoundVar recomposes its source against its definition scope; a
        # concrete or symbolic binding stands as itself.
        binding = ctx.temporal.value_for(
            self.name,
            blame=f"{self.site.filename}:{self.site.line}:{self.site.col}",
        )
        outcome = binding.answer(ctx)
        module_temporal = getattr(ctx, "module_temporal", None)
        if (
            module_temporal is None
            or module_temporal.value_if_bound(self.name) is not binding
        ):
            return outcome

        from sugar_lift_py_tests.floor import BoundVar, CallSiteValue, SymbolicValue
        from sugar_lift_py_tests.floor.call_site_value import force_floor
        from sugar_lift_py_tests.outcome import Complete

        if not isinstance(binding, BoundVar) or not isinstance(outcome, Complete):
            return outcome
        source_site = getattr(getattr(binding.source, "sugar", None), "site", None)
        replacement = source_site.unparse() if source_site is not None else self.name
        # #4203: never catch FactoryPanic. force_floor is process-terminal on a
        # construction gap; optional ground probes must not invent a silent
        # continue. Only demand ground when the caller explicitly opted in via
        # prefer_ground_module_bindings — then the panic is mandatory and loud.
        ground = None
        if isinstance(outcome.value, CallSiteValue) and getattr(
            ctx, "prefer_ground_module_bindings", False
        ):
            ground = force_floor(
                outcome.value,
                binding.scope,
                owner=f"module binding {self.name}",
                project_callsite=False,
            )
        ctx.module_rewrite_log.append(
            (
                self.name,
                replacement,
                getattr(source_site, "filename", self.site.filename),
                getattr(source_site, "line", 0),
                ground,
            )
        )
        if ground is not None and ctx.prefer_ground_module_bindings:
            return Complete(
                SymbolicValue(ground.to_term(owner=f"module binding {self.name}"))
            )
        return outcome
