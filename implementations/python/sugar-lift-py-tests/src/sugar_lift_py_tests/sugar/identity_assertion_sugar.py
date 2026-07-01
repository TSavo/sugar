from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.ir import Formula, Term, identity
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.not_sugar import NotSugar
from sugar_lift_py_tests.sugar.symbolic_term import can_symbolic_term, symbolic_term


@dataclass(frozen=True)
class IdentityAssertionSugar(Sugar, role=SugarRole.ASSERTION):
    source_role = "python.identity-assertion-sugar"

    left: Term
    right: Term
    polarity: NotSugar | None = None

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Assert":
            return False
        test = site.assert_test()
        if test.observed != "Compare":
            return False
        if test.compare_ops() not in (["Is"], ["IsNot"]):
            return False
        if len(test.compare_comparators()) != 1:
            return False
        return can_symbolic_term(test.compare_left()) and can_symbolic_term(
            test.compare_comparators()[0]
        )

    @classmethod
    def build(cls, site, ctx) -> "IdentityAssertionSugar":
        test = site.assert_test()
        import_aliases = getattr(ctx, "import_aliases", {}) or {}
        from_imports = getattr(ctx, "from_imports", {}) or {}
        name_resolver = getattr(ctx, "name_resolver", {}) or {}
        external_bridge_sink = getattr(ctx, "external_bridge_sink", None)
        return cls(
            left=symbolic_term(
                test.compare_left(),
                owner="identity assertion left",
                import_aliases=import_aliases,
                from_imports=from_imports,
                name_resolver=name_resolver,
                external_bridge_sink=external_bridge_sink,
            ),
            right=symbolic_term(
                test.compare_comparators()[0],
                owner="identity assertion right",
                import_aliases=import_aliases,
                from_imports=from_imports,
                name_resolver=name_resolver,
                external_bridge_sink=external_bridge_sink,
            ),
            polarity=NotSugar() if test.compare_ops() == ["IsNot"] else None,
        )

    def assertion_formula(self) -> Formula:
        formula = identity(self.left, self.right)
        if self.polarity is None:
            return formula
        return self.polarity.apply(formula)

    def desugar(self, ctx):
        del ctx
        return self.assertion_formula()
