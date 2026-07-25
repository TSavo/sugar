"""Authenticated EffectBoundary ``with`` over already-constructed call operands."""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar


@dataclass(frozen=True)
class WithEffectBoundarySugar(Sugar):
    manager: Sugar
    body: tuple
    semantics: object
    contract_ref: object
    context_manager_edge: object
    site: object = dataclass_field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        from sugar_lift_py_tests.sugar.witnesses import _call_pair

        return _call_pair(
            name="with_effect_boundary",
            owner_sugar="WithEffectBoundarySugar",
            truthful="def f():\n    with expect(ValueError):\n        raise ValueError()\n",
            lying="def f():\n    with expect(ValueError):\n        raise TypeError()\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        from sugar_lift_py_tests.context_manager_contract import (
            AuthenticatedRaiseMatcher,
            EffectBoundaryDisposition,
            EffectBoundarySemanticsV1,
            ExpectsModeV1,
            NoMessagePatternV1,
            RaiseEffectKindV1,
            SuppressesModeV1,
            project_formal_selector_v1,
        )
        from sugar_lift_py_tests.effect import ExpectationNotMetEffect
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.outcome.exit_set import ExitSet, Halted
        from sugar_lift_py_tests.sugar.exit_set_routing import (
            promote_raise_halts,
            sugar_outcome_to_exitset,
        )
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            reduce_block_to_exitset,
        )
        from sugar_source_tree.panic import SugarNotWritten

        del ctx
        semantics = self.semantics
        if (
            not isinstance(semantics, EffectBoundarySemanticsV1)
            or not isinstance(semantics.mode, (ExpectsModeV1, SuppressesModeV1))
            or not isinstance(semantics.effect_kind, RaiseEffectKindV1)
        ):
            raise SugarNotWritten(
                owner="WithEffectBoundarySugar.desugar",
                observed="unsupported authenticated EffectBoundary mode/effect",
                requested="EffectBoundaryV1 Expects/Raise",
                fix="keep other effect-boundary variants loud until their typed router exists",
            )

        manager_es = sugar_outcome_to_exitset(self.manager.desugar())
        routed = []
        for manager_exit in manager_es.exits:
            if isinstance(manager_exit, Halted):
                routed.append(ExitSet((manager_exit,)))
                continue
            manager_value = manager_exit.value
            if not isinstance(manager_value, CallSiteValue):
                raise SugarNotWritten(
                    owner="WithEffectBoundarySugar.desugar",
                    observed="manager did not construct a call-site value",
                    requested="one real call occurrence with authenticated formal binding",
                    fix="keep computed or opaque managers loud",
                )
            fixed = _bind_real_actuals(
                self.contract_ref.import_signature,
                manager_value,
            )
            expected = project_formal_selector_v1(
                semantics.expected_type_operand,
                fixed_actuals=fixed,
                variadic_positional_actuals={},
                variadic_keyword_actuals={},
            )
            pattern = None
            if not isinstance(semantics.message_pattern_operand, NoMessagePatternV1):
                pattern = project_formal_selector_v1(
                    semantics.message_pattern_operand,
                    fixed_actuals=fixed,
                    variadic_positional_actuals={},
                    variadic_keyword_actuals={},
                )

            body_es = promote_raise_halts(reduce_block_to_exitset(self.body)).guarded(
                manager_exit.guard
            )

            # One typed contract, both edges. ``unmet`` is what makes this an
            # assertion boundary rather than a resource ``__exit__``: under
            # Expects a body that completed is a failed expectation.
            disposition = EffectBoundaryDisposition(
                matcher=AuthenticatedRaiseMatcher(
                    expected=expected, message_pattern=pattern
                ),
                unmet=(
                    ExpectationNotMetEffect("raise", self.site)
                    if isinstance(semantics.mode, ExpectsModeV1)
                    else None
                ),
            )
            # The boundary's own exit completes, on the authority of the ref
            # that resolved it — so the exit face carries that ref rather than
            # a synthesized truth value. The algebra reads no value from a
            # completed exit face; the disposition decides both edges. Every
            # ref family (authenticated and source-derived) is spelled the
            # same way here, because the exit face is not ref-shaped data.
            boundary_exit_es = ExitSet.completed(self.contract_ref)

            routed.append(body_es.and_exit(boundary_exit_es, disposition=disposition))

        if not routed:
            raise SugarNotWritten(
                owner="WithEffectBoundarySugar.desugar",
                observed="manager produced no execution face",
                requested="one completed or halted manager face",
                fix="keep empty manager outcomes loud",
            )
        result = routed[0]
        for part in routed[1:]:
            result = result.union(part)
        return result


def _bind_real_actuals(signature, manager_value):
    from sugar_lift_py_tests.context_manager_contract import (
        ContextManagerContractError,
        KeywordOnlyV1,
        PositionalOnlyV1,
        PositionalOrKeywordV1,
    )

    keyword_count = len(manager_value.keyword_names)
    positional_count = len(manager_value.arg_values) - keyword_count
    positional = list(manager_value.arg_values[:positional_count])
    if manager_value.runtime_dispatch_receiver is not None:
        if (
            not positional
            or positional[0] is not manager_value.runtime_dispatch_receiver
        ):
            raise ContextManagerContractError(
                "constructed method receiver is absent from its call coordinate"
            )
        positional = positional[1:]
    keywords = dict(
        zip(
            manager_value.keyword_names,
            manager_value.arg_values[positional_count:],
            strict=True,
        )
    )
    if len(keywords) != keyword_count:
        raise ContextManagerContractError("duplicate keyword actual binding")
    fixed = {}
    for index, parameter in enumerate(signature.parameters):
        value = None
        present = False
        if positional and isinstance(
            parameter.passing, (PositionalOnlyV1, PositionalOrKeywordV1)
        ):
            value, present = positional.pop(0), True
            if parameter.name in keywords:
                raise ContextManagerContractError(
                    "formal receives positional and keyword actuals"
                )
        elif parameter.name in keywords and isinstance(
            parameter.passing, (PositionalOrKeywordV1, KeywordOnlyV1)
        ):
            value, present = keywords.pop(parameter.name), True
        if present:
            fixed[index] = value
        elif parameter.required:
            raise ContextManagerContractError("required formal actual is absent")
    if positional or keywords:
        raise ContextManagerContractError(
            "call actual does not fit authenticated signature"
        )
    return fixed
