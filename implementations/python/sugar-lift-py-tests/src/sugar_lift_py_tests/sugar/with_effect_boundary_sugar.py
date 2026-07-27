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
    observation_slot_id: str | None = None
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
            WarningEffectKindV1,
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

        semantics = self.semantics
        if (
            not isinstance(semantics, EffectBoundarySemanticsV1)
            or not isinstance(semantics.mode, (ExpectsModeV1, SuppressesModeV1))
            or not isinstance(
                semantics.effect_kind, (RaiseEffectKindV1, WarningEffectKindV1)
            )
        ):
            raise SugarNotWritten(
                owner="WithEffectBoundarySugar.desugar",
                observed="unsupported authenticated EffectBoundary mode/effect",
                requested="EffectBoundaryV1 Expects/Suppresses over Raise or Warning",
                fix="keep other effect-boundary variants loud until their typed router exists",
            )

        manager_es = sugar_outcome_to_exitset(self.manager.desugar(ctx))
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
            if isinstance(semantics.effect_kind, WarningEffectKindV1):
                if pattern is not None:
                    raise SugarNotWritten(
                        owner="WithEffectBoundarySugar.warning_observation",
                        observed="warning boundary carries an unprojected message pattern",
                        requested="authenticated warning message matcher",
                        fix="keep message-bearing warning assertions loud until their matcher is constructed",
                    )
                routed.append(
                    _route_completed_warning_boundary(
                        body=tuple(self.body),
                        ctx=ctx,
                        manager_exit=manager_exit,
                        expected=expected,
                        mode=semantics.mode,
                        site=self.site,
                    )
                )
                continue

            body_es = promote_raise_halts(
                reduce_block_to_exitset(self.body, ctx)
            ).guarded(manager_exit.guard)

            # One typed contract, both edges. ``unmet`` is what makes this an
            # assertion boundary rather than a resource ``__exit__``: under
            # Expects a body that completed is a failed expectation.
            disposition = EffectBoundaryDisposition(
                matcher=AuthenticatedRaiseMatcher(
                    expected=expected, message_pattern=pattern
                ),
                observation_slot_id=self.observation_slot_id,
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


def _unresolved_producer_coordinates(entries):
    """The MEMBERS of the "unresolved warning producers" bucket, by coordinate.

    Every call that survived to the completed face unreduced is a call this
    boundary could not rule out as the warning it is looking for -- including
    the three shapes the producer deliberately refuses (no explicit category, a
    category that is not a closed class coordinate, and a shadowed or parameter
    head).  Each is named ``file:line`` from its own pinned fragment, never from
    the spelling of its head.  A call whose fragment is absent still counts as a
    member and says so; dropping it would let the bucket under-report.
    """
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue

    members = []
    for entry in entries:
        if not isinstance(entry, CallSiteValue):
            continue
        fragment = entry.site
        filename = getattr(fragment, "filename", None)
        line = getattr(fragment, "line", None)
        if filename is None or line is None:
            members.append(f"<unlocated>:{entry.target_name}")
        else:
            members.append(f"{filename}:{line}")
    return tuple(members)


def _route_completed_warning_boundary(*, body, ctx, manager_exit, expected, mode, site):
    """Route authenticated warning testimony carried by a COMPLETED body face.

    Warnings never become halted exits.  Their producer contributes a
    ``WarningObservationValue`` to the completed block record.  The manager
    consumes a matching observation; an authenticated mismatch fails an
    Expects boundary; and missing identity/occurrence testimony stays a named
    refusal.  In particular, an empty record is not evidence that no warning
    occurred.
    """
    from sugar_lift_py_tests.context_manager_contract import ExpectsModeV1
    from sugar_lift_py_tests.effect import ExpectationNotMetEffect
    from dataclasses import replace

    from sugar_lift_py_tests.floor import CallSiteValue
    from sugar_lift_py_tests.floor.none_value import NoneValue
    from sugar_lift_py_tests.floor.warning_observation_value import (
        WarningObservationValue,
    )
    from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet, Halted
    from sugar_lift_py_tests.sugar.exit_set_routing import (
        promote_raise_halts,
    )
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        reduce_block_to_exitset,
    )
    from sugar_source_tree.panic import SugarNotWritten

    # Exact ``None`` is the manager's inverted contract: no warning may arrive.
    # NoneValue is the literal's floor type, not a placeholder warning class.
    if isinstance(expected, NoneValue):
        return _route_completed_no_warning_boundary(
            body=body,
            ctx=ctx,
            manager_exit=manager_exit,
            mode=mode,
            site=site,
        )

    # Python warning categories are exception classes.  The ordinary lexical
    # class authenticator therefore owns their identity too; no warning/vendor
    # name table is needed.
    identity_projection = getattr(expected, "exception_type_identity", None)
    if not callable(identity_projection):
        raise SugarNotWritten(
            owner="WithEffectBoundarySugar.warning_observation",
            observed="expected warning operand has no authenticated category identity",
            requested="source-authenticated warning category operand",
            fix="keep the completed observation undecided; never match category spelling",
        )
    expected_identity = identity_projection()
    body_es = promote_raise_halts(reduce_block_to_exitset(body, ctx)).guarded(
        manager_exit.guard
    )
    exits = []
    for face in body_es.exits:
        if isinstance(face, Halted):
            exits.append(face)
            continue
        entries = getattr(face.value, "entries", None)
        if not isinstance(entries, tuple):
            raise SugarNotWritten(
                owner="WithEffectBoundarySugar.warning_observation",
                observed=f"completed face carries {type(face.value).__name__}, not a reduced block record",
                requested="completed reduced block carrying authenticated warning observations",
                fix="preserve the completed face until its record is constructed",
            )
        observations = tuple(
            (index, entry)
            for index, entry in enumerate(entries)
            if isinstance(entry, WarningObservationValue)
        )
        unauthenticated = tuple(
            entry
            for _, entry in observations
            if entry.effect.category_identity is None or entry.guards
        )
        if unauthenticated or not observations:
            unresolved_members = _unresolved_producer_coordinates(entries)
            unresolved = bool(unresolved_members)
            if unresolved or not observations:
                observed = "completed face has unresolved warning producers"
            elif any(entry.guards for entry in unauthenticated):
                # The producer says the warning happens WHEN a branch guard
                # holds. Consuming it here would restate that as "the warning
                # happens", which is a strictly stronger claim than the source
                # makes. Undecided, not absent, and not present.
                observed = "warning occurrence is reached only under a branch guard"
            else:
                observed = "warning occurrence has no authenticated category identity"
            refusal = SugarNotWritten(
                owner="WithEffectBoundarySugar.warning_observation",
                observed=observed,
                requested="one source-authenticated WarningObservationValue on the completed face",
                fix="construct producer-owned warning testimony; never infer absence or category from spelling",
            )
            # The bucket ENUMERATES its members.  A refusal that only names a
            # bucket is indistinguishable from a producer that was never wired:
            # both leave the produced set empty, and a test can only assert
            # absence, which the never-wired case satisfies too.  A caller can
            # now require a specific coordinate to be PRESENT here.
            refusal.unresolved_warning_producers = unresolved_members
            raise refusal
        match = next(
            (
                pair
                for pair in observations
                if pair[1].effect.category_identity == expected_identity
            ),
            None,
        )
        if match is not None and len(observations) == 1:
            index, _ = match
            remaining = entries[:index] + entries[index + 1 :]
            exits.append(
                Completed(
                    face.guard,
                    replace(face.value, entries=remaining),
                    face.faces,
                    face.pending_contracts,
                )
            )
            continue
        if isinstance(mode, ExpectsModeV1):
            exits.append(
                Halted(
                    face.guard,
                    ExpectationNotMetEffect("warning", site),
                    face.value,
                    face.faces,
                    face.pending_contracts,
                )
            )
        else:
            exits.append(face)
    return ExitSet(tuple(exits)).normalize()


def _route_completed_no_warning_boundary(*, body, ctx, manager_exit, mode, site):
    """Accept a completed face only when warning absence is decidable."""
    from sugar_lift_py_tests.context_manager_contract import ExpectsModeV1
    from sugar_lift_py_tests.effect import ExpectationNotMetEffect
    from sugar_lift_py_tests.floor import CallSiteValue
    from sugar_lift_py_tests.floor.warning_observation_value import (
        WarningObservationValue,
    )
    from sugar_lift_py_tests.outcome.exit_set import ExitSet, Halted
    from sugar_lift_py_tests.sugar.exit_set_routing import promote_raise_halts
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        reduce_block_to_exitset,
    )
    from sugar_source_tree.panic import SugarNotWritten

    body_es = promote_raise_halts(reduce_block_to_exitset(body, ctx)).guarded(
        manager_exit.guard
    )
    exits = []
    for face in body_es.exits:
        if isinstance(face, Halted):
            exits.append(face)
            continue
        entries = getattr(face.value, "entries", None)
        if not isinstance(entries, tuple):
            raise SugarNotWritten(
                owner="WithEffectBoundarySugar.warning_observation",
                observed=(
                    f"completed face carries {type(face.value).__name__}, "
                    "not a reduced block record"
                ),
                requested=(
                    "completed reduced block carrying authenticated warning observations"
                ),
                fix="preserve the completed face until its record is constructed",
            )
        if any(isinstance(entry, WarningObservationValue) for entry in entries):
            if isinstance(mode, ExpectsModeV1):
                exits.append(
                    Halted(
                        face.guard,
                        ExpectationNotMetEffect("warning", site),
                        face.value,
                        face.faces,
                        face.pending_contracts,
                    )
                )
            else:
                exits.append(face)
            continue
        if any(isinstance(entry, CallSiteValue) for entry in entries):
            raise SugarNotWritten(
                owner="WithEffectBoundarySugar.warning_observation",
                observed="completed face has unresolved warning producers",
                requested="authenticated absence of warning observations",
                fix=(
                    "construct every producer on the completed face; never infer "
                    "absence from an empty observation set"
                ),
            )
        exits.append(face)
    return ExitSet(tuple(exits)).normalize()
