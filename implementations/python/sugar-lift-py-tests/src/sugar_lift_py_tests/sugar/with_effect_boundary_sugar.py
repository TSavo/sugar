"""Authenticated EffectBoundary ``with`` over already-constructed call operands."""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import ExitSet
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

    def desugar(self, ctx: object = None) -> ExitSet:
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
        from sugar_lift_py_tests.outcome.exit_set import Completed, Halted
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

        from sugar_lift_py_tests.outcome.exit_set import _require_exit_set

        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            halt_record,
            halts_recorded,
        )

        # The manager is routed face by face: a deferred native-operation
        # carrier is refused by name. A manager or constructor halt is at the
        # head of the ``with``: it carries the record of where it halted
        # (``halts_recorded``).
        manager_es = halts_recorded(
            _require_exit_set(
                self.manager.desugar(ctx), owner="WithEffectBoundarySugar.manager"
            ),
            halt_record(ctx),
        )
        construction_halts, construction_guard = self._construction_faces()
        routed = []
        for manager_exit in manager_es.exits:
            if isinstance(manager_exit, Halted):
                routed.append(ExitSet((manager_exit,)))
                continue
            # Python evaluates the context expression first. A constructor
            # halt leaves the With as itself: nothing was entered, so neither
            # the body nor __exit__ runs and the boundary never sees it. It
            # runs beneath the manager face (``ExitSet.sequence``), so it
            # keeps the face's guard, faces and ``owed`` beside its own.
            for halt in construction_halts:
                routed.append(
                    ExitSet((manager_exit,)).sequence(
                        lambda _manager, halt=halt: halts_recorded(
                            ExitSet((halt,)), halt_record(ctx)
                        )
                    )
                )
            if construction_guard is not None:
                manager_exit = replace_exit_guard(
                    manager_exit, _and_guard(manager_exit.guard, construction_guard)
                )
            manager_value = manager_exit.value
            if not isinstance(manager_value, CallSiteValue):
                raise SugarNotWritten(
                    blame=self.site,
                    owner="WithEffectBoundarySugar.desugar",
                    observed="manager did not construct a call-site value",
                    requested="one real call occurrence with authenticated formal binding",
                    fix="keep computed or opaque managers loud",
                )
            fixed, keyword_actuals = _bind_real_actuals(
                self.contract_ref.import_signature,
                manager_value,
            )
            # Reduce the body suite ONCE per manager face. Factored message
            # faces are alternative guards over the same body occurrence —
            # re-reducing would re-enter nested resources and invent a second
            # evaluation of the same source suite under each message face.
            body_es_once = reduce_block_to_exitset(self.body, ctx)
            for face_guard, semantics in self._guarded_semantics():
                expected = project_formal_selector_v1(
                    semantics.expected_type_operand,
                    fixed_actuals=fixed,
                    variadic_positional_actuals={},
                    variadic_keyword_actuals=keyword_actuals,
                )
                pattern = None
                if not isinstance(
                    semantics.message_pattern_operand, NoMessagePatternV1
                ):
                    pattern = project_formal_selector_v1(
                        semantics.message_pattern_operand,
                        fixed_actuals=fixed,
                        variadic_positional_actuals={},
                        variadic_keyword_actuals=keyword_actuals,
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

                # The body runs beneath the manager face: its guard, faces
                # and ``owed`` ride onto every body arm.
                body_es = ExitSet((face_manager,)).sequence(
                    lambda _manager: body_es_once
                )

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
        return routed[0].union(*routed[1:])

    def _construction_faces(self):
        """``(halts, completed_guard)`` of the manager's own construction.

        Factored faces already carry each completed construction guard; their
        construction halts ride as Halted boundary faces. A sealed boundary
        names them by ``SourceConstructorFacesCompletionV1`` and they are read
        from the source-derived protocol's receiver partition, the same
        testimony the boundary was sealed over. ``completed_guard`` is ``None``
        when construction is total.
        """
        from sugar_lift_py_tests.context_manager_contract import (
            SourceConstructorFacesCompletionV1,
        )
        from sugar_lift_py_tests.floor import ReceiverStatePartitionValue
        from sugar_lift_py_tests.outcome.exit_set import Halted, _or_guards
        from sugar_source_tree.panic import SugarNotWritten

        if self.boundary_faces is not None:
            halts = tuple(
                face for face in self.boundary_faces.exits if isinstance(face, Halted)
            )
            if any(face.effect is None for face in halts):
                raise SugarNotWritten(
                    blame=self.site,
                    owner="WithEffectBoundarySugar.construction",
                    observed="factored construction halt without a typed effect",
                    requested="every constructor halt as its own typed effect",
                    fix="keep untyped construction halts loud; never drop them",
                )
            return halts, None
        if not isinstance(
            getattr(self.semantics, "construction", None),
            SourceConstructorFacesCompletionV1,
        ):
            return (), None
        state = getattr(getattr(self.contract_ref, "protocol", None), "receiver_state", None)
        faces = (
            state.constructor_faces()
            if isinstance(state, ReceiverStatePartitionValue)
            else None
        )
        if faces is None or not faces[0] or not faces[1]:
            raise SugarNotWritten(
                blame=self.site,
                owner="WithEffectBoundarySugar.construction",
                observed="constructor-faces boundary without typed construction faces",
                requested="the source-derived receiver partition the boundary sealed",
                fix="seal constructor-faces only over a typed receiver partition",
            )
        halts, completed = faces
        guard = completed[0].guard
        for face in completed[1:]:
            guard = _or_guards(guard, face.guard)
        return halts, guard

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


@dataclass(frozen=True)
class _KeywordValueEntry:
    """An already-constructed keyword actual, not a source Sugar occurrence."""

    keyword: str
    value: object


@dataclass(frozen=True)
class _KeywordValuePack:
    """Pack leftover keywords under a unique ``**kwargs`` formal."""

    formal_index: int
    entries: tuple[_KeywordValueEntry, ...]


def _bind_real_actuals(signature, manager_value):
    from sugar_lift_py_tests.context_manager_contract import (
        ContextManagerContractError,
        KeywordOnlyV1,
        PositionalOnlyV1,
        PositionalOrKeywordV1,
        VariadicKeywordV1,
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
    keyword_formal = None
    for index, parameter in enumerate(signature.parameters):
        if isinstance(parameter.passing, VariadicKeywordV1):
            if keyword_formal is not None:
                raise ContextManagerContractError(
                    "at most one variadic keyword parameter"
                )
            keyword_formal = index
            continue
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
    keyword_actuals = {}
    if keyword_formal is not None:
        keyword_actuals[keyword_formal] = _KeywordValuePack(
            keyword_formal,
            tuple(
                _KeywordValueEntry(name, value) for name, value in keywords.items()
            ),
        )
        keywords.clear()
    if positional or keywords:
        raise ContextManagerContractError(
            "call actual does not fit authenticated signature"
        )
    return fixed, keyword_actuals


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
    from sugar_lift_py_tests.outcome.exit_set import (
        Completed,
        ExitSet,
        complement_guard,
        partition,
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

    # The body runs beneath the manager face: its guard, faces and ``owed``
    # ride onto every body arm.
    body_es = ExitSet((manager_exit,)).sequence(
        lambda _manager: reduce_block_to_exitset(body, ctx)
    )
    # Every face continues beneath itself (``ExitSet.sequence``): what the
    # boundary makes of it keeps the face's guard, faces and ``owed``, and the
    # routed faces join through ``ExitSet.union``.
    parts = []
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
            # LAW OF ONE: match/miss meaning is only warning_effect_message_verdict
            # (the one matcher) after sugar produced one authenticated observation.
            # pytest.warns is EXISTENTIAL — one written surface. Cardinality ≠ 1
            # is not a settled miss: deciding MatchDecided(False) here would be a
            # second mechanism (ad-hoc count → fabricated ExpectationNotMet).
            # Sugar not written for multi-obs yet; throw, do not decide.
            raise SugarNotWritten(
                blame=site,
                owner="WithEffectBoundarySugar.warning_observation",
                observed=(f"{len(observations)} authenticated warning observations"),
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
        # ONE matcher: identity + optional message. No local MatchDecided mint.
        verdict = warning_effect_message_verdict(observation.effect, expected, pattern)

        def restored(carried, face=face):
            # The face goes on as itself -- its completion, or its halt --
            # over ``carried``.
            if isinstance(face, Completed):
                return ExitSet.completed(carried)
            return ExitSet.halted(face.effect, state=carried)

        def successful():
            assert index is not None
            remaining = entries[:index] + entries[index + 1 :]
            return restored(replace(record, entries=remaining))

        def failed():
            if isinstance(mode, ExpectsModeV1):
                return ExitSet.halted(
                    ExpectationNotMetEffect("warning", site), state=record
                )
            return restored(record)

        if isinstance(verdict, MatchDecided):
            following = successful() if verdict.value else failed()
            parts.append(
                ExitSet((face,)).sequence(
                    lambda _value, f=following: f, consume=lambda _halt, f=following: f
                )
            )
            continue
        if isinstance(verdict, MatchRetained):
            held, rejected = partition(
                ("warning-boundary-message", verdict.obligation, face.guard)
            )
            following = (
                successful()
                .guarded(verdict.obligation, held)
                .union(
                    failed().guarded(complement_guard(verdict.obligation), rejected)
                )
            )
            parts.append(
                ExitSet((face,)).sequence(
                    lambda _value, f=following: f, consume=lambda _halt, f=following: f
                )
            )
            continue
        from sugar_lift_py_tests.gap.panic import construction_panic_gap

        construction_panic_gap(
            owner="WithEffectBoundarySugar.warning_message",
            blame=getattr(self, "site", "with-effect-boundary"),
            observed=f"warning message verdict species {type(verdict).__name__} has no arm",
            requested="a written warning-message verdict class",
            fix=f"write warning-message arm for {type(verdict).__name__}",
        )
    return ExitSet(()).union(*parts)


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
    from sugar_lift_py_tests.outcome.exit_set import ExitSet
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        reduce_block_to_exitset,
    )
    from sugar_source_tree.panic import SugarNotWritten

    # The body runs beneath the manager face: its guard, faces and ``owed``
    # ride onto every body arm.
    body_es = ExitSet((manager_exit,)).sequence(
        lambda _manager: reduce_block_to_exitset(body, ctx)
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

    def unmet(record, *, halted):
        """What follows one face whose record is ``record`` (its value, or
        its pre-halt state when ``halted``): the assertion's unmet halt, or
        ``None`` when the face goes on as itself.

        Matching-category routing already reads both faces the same way:
        Completed carries the reduced block as its value; Halted carries the
        pre-halt record as its state."""
        entries = getattr(record, "entries", None)
        if not isinstance(entries, tuple):
            if halted:
                # Exception edge without a temporal record: do not invent a
                # warning verdict. Restore the halt as the body left it.
                return None
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
                return ExitSet.halted(
                    ExpectationNotMetEffect("warning", site), state=record
                )
            return None
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
        return None

    def after_completion(value):
        following = unmet(value, halted=False)
        return ExitSet.completed(value) if following is None else following

    # Each face's verdict runs beneath it (``ExitSet.sequence``; ``consume=``
    # for the halts the boundary decides), so it keeps the face's guard,
    # faces and ``owed``.
    return body_es.sequence(
        after_completion, consume=lambda halt: unmet(halt.state, halted=True)
    )


def _and_guard(left, right):
    from sugar_lift_py_tests.outcome.exit_set import _and_guards

    return _and_guards(left, right)
