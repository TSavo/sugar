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
    boundary_faces: object | None = None
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
        from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet, Halted
        from sugar_lift_py_tests.sugar.exit_set_routing import (
            promote_raise_halts,
            sugar_outcome_to_exitset,
        )
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            reduce_block_to_exitset,
        )
        from sugar_source_tree.panic import SugarNotWritten

        semantics_faces = self._semantics_faces()
        for semantics in semantics_faces:
            if (
                not isinstance(semantics, EffectBoundarySemanticsV1)
                or not isinstance(semantics.mode, (ExpectsModeV1, SuppressesModeV1))
                or not isinstance(
                    semantics.effect_kind, (RaiseEffectKindV1, WarningEffectKindV1)
                )
            ):
                raise SugarNotWritten(
                    blame=self.site,
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
                    blame=self.site,
                    owner="WithEffectBoundarySugar.desugar",
                    observed="manager did not construct a call-site value",
                    requested="one real call occurrence with authenticated formal binding",
                    fix="keep computed or opaque managers loud",
                )
            fixed = _bind_real_actuals(
                self.contract_ref.import_signature,
                manager_value,
            )
            # Reduce the body suite ONCE per manager face. Factored message
            # faces are alternative guards over the same body occurrence —
            # re-reducing would re-enter nested resources and invent a second
            # evaluation of the same source suite under each message face.
            body_es_once = promote_raise_halts(
                reduce_block_to_exitset(self.body, ctx)
            )
            for face_guard, semantics in self._guarded_semantics():
                expected = project_formal_selector_v1(
                    semantics.expected_type_operand,
                    fixed_actuals=fixed,
                    variadic_positional_actuals={},
                    variadic_keyword_actuals={},
                )
                pattern = None
                if not isinstance(
                    semantics.message_pattern_operand, NoMessagePatternV1
                ):
                    pattern = project_formal_selector_v1(
                        semantics.message_pattern_operand,
                        fixed_actuals=fixed,
                        variadic_positional_actuals={},
                        variadic_keyword_actuals={},
                    )
                # Factored faces tighten the manager guard; single-face keeps
                # the manager exit as-is so true-guard identity is preserved.
                if face_guard is None:
                    face_manager = manager_exit
                else:
                    from sugar_lift_py_tests.ir import and_ as and_formulas

                    face_manager = replace_exit_guard(
                        manager_exit,
                        and_formulas([manager_exit.guard, face_guard]),
                    )
                if isinstance(semantics.effect_kind, WarningEffectKindV1):
                    routed.append(
                        _route_warning_boundary(
                            body=tuple(self.body),
                            ctx=ctx,
                            manager_exit=face_manager,
                            expected=expected,
                            pattern=pattern,
                            mode=semantics.mode,
                            site=self.site,
                        )
                    )
                    continue

                body_es = body_es_once.guarded(face_manager.guard)

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
                boundary_exit_es = ExitSet.completed(self.contract_ref)

                routed.append(
                    _route_raise_boundary(
                        body_es,
                        boundary_exit_es=boundary_exit_es,
                        disposition=disposition,
                    )
                )

        if not routed:
            raise SugarNotWritten(
                blame=self.site,
                owner="WithEffectBoundarySugar.desugar",
                observed="manager produced no execution face",
                requested="one completed or halted manager face",
                fix="keep empty manager outcomes loud",
            )
        result = routed[0]
        for part in routed[1:]:
            result = result.union(part)
        return result

    def _semantics_faces(self):
        from sugar_lift_py_tests.context_manager_contract import (
            EffectBoundarySemanticsV1,
        )
        from sugar_lift_py_tests.outcome.exit_set import Completed

        if self.boundary_faces is not None:
            return tuple(
                face.value
                for face in self.boundary_faces.exits
                if isinstance(face, Completed)
                and isinstance(face.value, EffectBoundarySemanticsV1)
            )
        return (self.semantics,)

    def _guarded_semantics(self):
        """(face_guard | None, EffectBoundarySemanticsV1) pairs.

        ``None`` face_guard means the single sealed summary path: do not re-and
        the manager exit. Factored faces carry their own guards.
        """
        from sugar_lift_py_tests.context_manager_contract import (
            EffectBoundarySemanticsV1,
        )
        from sugar_lift_py_tests.outcome.exit_set import Completed

        if self.boundary_faces is not None:
            return tuple(
                (face.guard, face.value)
                for face in self.boundary_faces.exits
                if isinstance(face, Completed)
                and isinstance(face.value, EffectBoundarySemanticsV1)
            )
        return ((None, self.semantics),)


def replace_exit_guard(exit_, guard):
    """Copy a manager exit under a tighter face guard without dropping value."""
    from dataclasses import replace

    from sugar_lift_py_tests.outcome.exit_set import Completed, Halted

    if isinstance(exit_, Completed):
        return replace(exit_, guard=guard)
    if isinstance(exit_, Halted):
        return replace(exit_, guard=guard)
    return exit_


def _route_raise_boundary(body_es, *, boundary_exit_es, disposition):
    """Route only halts that carry a possible exception-type subject.

    A wholly nameless ``RaiseEffect`` -- no name, authenticated type identity,
    or raised value -- has no operand on which the boundary can state its type
    predicate.  It therefore stays outside this boundary unchanged.  The
    expected type verifies producer testimony; it cannot manufacture the
    missing raised value or identity merely because a matcher is present.

    Effects with a value term but no closed identity still reach the shared
    matcher and retain its three-valued runtime type obligation.  Every other
    face continues through ``ExitSet.and_exit`` unchanged, so this partition
    neither duplicates the matcher nor locates a raising expression.
    """
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
    from sugar_lift_py_tests.outcome.exit_set import ExitSet, Halted

    outside = []
    candidates = []
    for face in body_es.exits:
        effect = face.effect if isinstance(face, Halted) else None
        if (
            isinstance(effect, RaiseEffect)
            and effect.exception_name is None
            and effect.exception_type_coordinate is None
            and effect.raised_value is None
        ):
            outside.append(face)
        else:
            candidates.append(face)

    routed = ExitSet(tuple(candidates)).and_exit(
        boundary_exit_es, disposition=disposition
    )
    if not outside:
        return routed
    return routed.union(ExitSet(tuple(outside)))


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


def _route_warning_boundary(*, body, ctx, manager_exit, expected, pattern, mode, site):
    """Route warning testimony on every face while preserving body control.

    A warning observation can precede a later halt, so consuming the warning
    must preserve that halt for an enclosing boundary.  Message predicates
    keep their three-valued result: ground matches decide, symbolic matches
    partition, and missing producer testimony remains a named refusal.
    """
    from sugar_lift_py_tests.context_manager_contract import ExpectsModeV1
    from sugar_lift_py_tests.effect import ExpectationNotMetEffect
    from dataclasses import replace

    from sugar_lift_py_tests.floor import CallSiteValue
    from sugar_lift_py_tests.floor.none_value import NoneValue
    from sugar_lift_py_tests.floor.warning_observation_value import (
        WarningObservationValue,
    )
    from sugar_lift_py_tests.authenticated_exception_matching import (
        MatchDecided,
        MatchRetained,
        warning_effect_message_verdict,
    )
    from sugar_lift_py_tests.ir import and_
    from sugar_lift_py_tests.outcome.exit_set import (
        Completed,
        ExitSet,
        Halted,
        complement_guard,
        partition,
    )
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
        return _route_no_warning_boundary(
            body=body,
            ctx=ctx,
            manager_exit=manager_exit,
            mode=mode,
            site=site,
        )

    body_es = promote_raise_halts(reduce_block_to_exitset(body, ctx)).guarded(
        manager_exit.guard
    )
    exits = []
    for face in body_es.exits:
        record = face.value if isinstance(face, Completed) else face.state
        entries = getattr(record, "entries", None)
        if not isinstance(entries, tuple):
            raise SugarNotWritten(
                blame=site,
                owner="WithEffectBoundarySugar.warning_observation",
                observed=f"body face carries {type(record).__name__}, not a reduced block record",
                requested="reduced block carrying authenticated warning observations",
                fix="preserve the body face until its temporal record is constructed",
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
                blame=site,
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
        if len(observations) != 1:
            # pytest.warns is EXISTENTIAL: one authenticated observation is the
            # written surface. Cardinality ≠ 1 is not a decided miss — deciding
            # False here fabricates ExpectationNotMet without asking the
            # three-valued matcher. Sugar not written for multi-obs (yet).
            raise SugarNotWritten(
                blame=site,
                owner="WithEffectBoundarySugar.warning_observation",
                observed=(
                    f"{len(observations)} authenticated warning observations"
                ),
                requested=(
                    "exactly one source-authenticated WarningObservationValue "
                    "on the completed face"
                ),
                fix=(
                    "write multi-observation warning-boundary sugar; never "
                    "decide miss by cardinality alone"
                ),
            )
        index, observation = observations[0]
        verdict = warning_effect_message_verdict(
            observation.effect, expected, pattern
        )

        def successful(guard, faces):
            assert index is not None
            remaining = entries[:index] + entries[index + 1 :]
            carried = replace(record, entries=remaining)
            if isinstance(face, Completed):
                return Completed(guard, carried, faces, face.pending_contracts)
            return Halted(
                guard,
                face.effect,
                carried,
                faces,
                face.pending_contracts,
            )

        def failed(guard, faces):
            if isinstance(mode, ExpectsModeV1):
                return Halted(
                    guard,
                    ExpectationNotMetEffect("warning", site),
                    record,
                    faces,
                    face.pending_contracts,
                )
            return replace(face, guard=guard, faces=faces)

        if isinstance(verdict, MatchDecided):
            exits.append(
                successful(face.guard, face.faces)
                if verdict.value
                else failed(face.guard, face.faces)
            )
            continue
        if isinstance(verdict, MatchRetained):
            held, rejected = partition(
                ("warning-boundary-message", verdict.obligation, face.guard)
            )
            exits.extend(
                (
                    successful(
                        and_([face.guard, verdict.obligation]),
                        face.faces | {held},
                    ),
                    failed(
                        and_([face.guard, complement_guard(verdict.obligation)]),
                        face.faces | {rejected},
                    ),
                )
            )
            continue
        raise TypeError(f"unknown warning message verdict {type(verdict).__name__}")
    return ExitSet(tuple(exits)).normalize()


def _route_no_warning_boundary(*, body, ctx, manager_exit, mode, site):
    """Invert Expects/Warning for literal ``None`` on both body edges.

    ``assert_produces_warning(None)`` is not an empty category. Exact
    ``NoneValue`` means no warning may arrive:

    - completed edge: absence is success; an unguarded observation is
      ``ExpectationNotMetEffect`` (never a fabricated ``WarningEffect``)
    - exception edge: the same observation law applies to the pre-halt
      record. Clean absence restores the original halt; an unguarded
      observation still fails the assertion. A halt with no temporal
      record is not a warning decision surface and is restored unchanged

    Guarded occurrences and unresolved producers remain undecided on either
    edge — the same refusals the matching-category router already names.
    """
    from sugar_lift_py_tests.context_manager_contract import ExpectsModeV1
    from sugar_lift_py_tests.effect import ExpectationNotMetEffect
    from sugar_lift_py_tests.floor.warning_observation_value import (
        WarningObservationValue,
    )
    from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet, Halted
    from sugar_lift_py_tests.sugar.exit_set_routing import promote_raise_halts
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        reduce_block_to_exitset,
    )
    from sugar_source_tree.panic import SugarNotWritten

    body_es = promote_raise_halts(reduce_block_to_exitset(body, ctx)).guarded(
        manager_exit.guard
    )
    # The inverted contract is proved by a POSITIVE completed edge whose
    # temporal record contains no matching warning observation.  An empty
    # ExitSet says the body never resolved; it is not a vacuous proof of
    # absence. Producer-family enrollment carries the same distinction as
    # AuthenticatedCompletedOwnership versus UndecidedOwnership; keep that
    # population predicate in its single owner rather than restating it here.
    if not body_es.exits:
        raise SugarNotWritten(
            blame=site,
            owner="WithEffectBoundarySugar.warning_observation",
            observed="body has no authenticated exit edge",
            requested="a resolved ExitSet containing a Completed edge",
            fix=(
                "construct and resolve the body before deciding warning absence; "
                "absence of a halt is not completion testimony"
            ),
        )
    exits = []
    for face in body_es.exits:
        # Matching-category routing already reads both faces the same way:
        # Completed carries the reduced block as its value; Halted carries
        # the pre-halt record as its state.
        record = face.value if isinstance(face, Completed) else face.state
        entries = getattr(record, "entries", None)
        if not isinstance(entries, tuple):
            if isinstance(face, Halted):
                # Exception edge without a temporal record: do not invent a
                # warning verdict. Restore the halt as the body left it.
                exits.append(face)
                continue
            raise SugarNotWritten(
                blame=site,
                owner="WithEffectBoundarySugar.warning_observation",
                observed=(
                    f"completed face carries {type(record).__name__}, "
                    "not a reduced block record"
                ),
                requested=(
                    "completed reduced block carrying authenticated warning observations"
                ),
                fix="preserve the completed face until its record is constructed",
            )
        observations = tuple(
            entry for entry in entries if isinstance(entry, WarningObservationValue)
        )
        # A conditional occurrence decides NEITHER side of a no-warning
        # contract. The producer says the warning happens WHEN a branch guard
        # holds; reading that as a met assertion drops the warning, and reading
        # it as a failed one -- which is what an unguarded `any(...)` does --
        # asserts a violation the source never states. Both directions are the
        # same defect, and the matching-category router above already refuses
        # this shape by name. Undecided, not present and not absent.
        if any(entry.guards for entry in observations):
            raise SugarNotWritten(
                blame=site,
                owner="WithEffectBoundarySugar.warning_observation",
                observed="warning occurrence is reached only under a branch guard",
                requested="a decidable warning surface on the completed face",
                fix=(
                    "keep the conditional occurrence undecided; never settle a "
                    "no-warning contract from a guarded occurrence"
                ),
            )
        if observations:
            if isinstance(mode, ExpectsModeV1):
                # Fail the inverted contract with the assertion effect only.
                # Never mint a WarningEffect here — observations arrive only
                # from the producer, and unmet is ExpectationNotMetEffect.
                exits.append(
                    Halted(
                        face.guard,
                        ExpectationNotMetEffect("warning", site),
                        record,
                        face.faces,
                        face.pending_contracts,
                    )
                )
            else:
                exits.append(face)
            continue
        unresolved_members = _unresolved_producer_coordinates(entries)
        if unresolved_members:
            refusal = SugarNotWritten(
                blame=site,
                owner="WithEffectBoundarySugar.warning_observation",
                observed="completed face has unresolved warning producers",
                requested="authenticated absence of warning observations",
                fix=(
                    "construct every producer on the completed face; never infer "
                    "absence from an empty observation set"
                ),
            )
            # Same enumeration the matching-category router carries: a bucket
            # that only names itself cannot be told apart from one nothing was
            # ever routed into.
            refusal.unresolved_warning_producers = unresolved_members
            raise refusal
        # Decidable absence: completed stays completed; exception edge restores
        # the original halt without inventing any warning effect.
        exits.append(face)
    return ExitSet(tuple(exits)).normalize()
