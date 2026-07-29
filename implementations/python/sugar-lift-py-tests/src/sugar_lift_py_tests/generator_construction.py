"""Typed suspended-generator construction and transition algebra."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from sugar_lift_python_source.canonical import cid_of_json

from .effect import Effect, require_effect
from .outcome import ExitSet
from .sugar.sugar_base import ConstructedTermSugar


def _require_constructed_term(value: object, *, owner: str) -> None:
    if not isinstance(value, ConstructedTermSugar):
        raise TypeError(
            f"{owner} requires ConstructedTermSugar, got {type(value).__name__}"
        )


class FormalFloorBindingGap(ValueError):
    """Formal floor roster cannot enter GeneratorConstructionV1.allocate."""


@dataclass(frozen=True)
class FormalFloorBindingV1:
    """One formal coordinate paired with its binder-produced Floor actual.

    Minted at the SourceCallFrame.bind_actuals boundary: the Floor is the exact
    object bind_actuals returned, never a consumer-side Node/Sugar rebuild.
    ``coordinate_cid`` must be an authenticated binding-coordinate CID;
    ``floor_value`` must be a FloorValue.
    """

    coordinate_cid: str
    floor_value: object = field(compare=False, repr=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.coordinate_cid, str)
            or not self.coordinate_cid.startswith("blake3-512:")
        ):
            raise FormalFloorBindingGap(
                "FormalFloorBindingV1.coordinate_cid must be an authenticated "
                f"blake3-512 CID, got {self.coordinate_cid!r}"
            )
        from sugar_lift_py_tests.floor.floor_value import FloorValue

        if not isinstance(self.floor_value, FloorValue):
            raise FormalFloorBindingGap(
                "FormalFloorBindingV1.floor_value must be a FloorValue, "
                f"got {type(self.floor_value).__name__}"
            )


@dataclass(frozen=True)
class _BinderOnlyReduceCtx:
    """Context-free test shell: temporal is the only field that exists.

    Used only when allocate is invoked with ``reduction_context=None``
    (focused machine twins).  Production CallSiteSugar always passes the
    authenticated caller context, which must expose ``with_temporal``.
    """

    temporal: object


@dataclass(frozen=True)
class YieldStepV1:
    value: ConstructedTermSugar | None

    def __post_init__(self) -> None:
        if self.value is not None:
            _require_constructed_term(self.value, owner="YieldStepV1.value")


@dataclass(frozen=True)
class YieldFromStepV1:
    """Authenticated delegated-iteration suspension.

    The iterable remains constructed testimony until transition.  The source
    occurrence authenticates both iterator acquisition and exhaustion; neither
    operation is inferred from the iterable's spelling.
    """

    iterable: ConstructedTermSugar
    occurrence: object = field(compare=False, repr=False)
    occurrence_cid: str

    def __post_init__(self) -> None:
        _require_constructed_term(self.iterable, owner="YieldFromStepV1.iterable")
        if self.occurrence.seal().cid != self.occurrence_cid:
            raise TypeError(
                "YieldFromStepV1 occurrence must match its authenticated CID"
            )


@dataclass(frozen=True)
class ReturnStepV1:
    value: ConstructedTermSugar | None = None

    def __post_init__(self) -> None:
        if self.value is not None:
            _require_constructed_term(self.value, owner="ReturnStepV1.value")


@dataclass(frozen=True)
class OpaqueStepV1:
    """A body statement the step vocabulary cannot yet name.

    ``carries_suspension`` is the discrimination that makes this row
    dispatchable. Without it, ``x = 1`` and ``x = yield 1`` are the SAME row --
    ``OpaqueStepV1("Assign")`` -- and they are not the same obligation:

    * an opaque statement that owns NO suspension owes ordinary statement
      execution inside a generator frame;
    * an opaque statement that OWNS one owes a generator-protocol law (the
      resumed value's binding, a branched suspension's partition).

    Bucketing them together is why the two suspension owners read as one
    undifferentiated mass. The flag is read from ``_owns_yield``, the same
    authenticated predicate the step builder already uses to decide whether a
    body is a generator at all -- never from the statement's spelling.
    """

    observed: str
    carries_suspension: bool = False

    def gap_observed(self) -> str:
        """What the transition gap should NAME as unconsumed.

        The statement kind alone (``Assign``, ``If``, ``Expr``) names the
        shape of the container, not the thing that could not be consumed, so a
        board keyed on it cannot tell generator-protocol work from ordinary
        unsupported statements.
        """
        if not self.carries_suspension:
            return self.observed
        return f"{self.observed} carrying a suspension"


@dataclass(frozen=True)
class InertStepV1:
    """A body statement that owes NOTHING and is therefore stepped past.

    The discriminating property is not the statement's spelling but what it
    owes: no effect, no binding, no suspension. A bare ``Constant`` expression
    -- a docstring, or any evaluated-and-discarded literal -- is the only shape
    admitted today, because evaluating a literal and discarding it is
    observationally nothing.

    This is deliberately NARROWER than ``OpaqueStepV1``. An opaque step names a
    real obligation the vocabulary cannot yet perform; an inert step names the
    absence of one. Widening this row to any statement that merely *looks*
    harmless would make the machine skip work it cannot do and report the wrong
    blocker -- the failure this row must never cause. ``observed`` is retained
    so a stepped-past statement is still nameable in testimony rather than
    vanishing.
    """

    observed: str


@dataclass(frozen=True)
class AssignStepV1:
    """Simple name assignment executed on the live generator machine.

    Pre-yield setup (``prior = None``, ``filters = [action]``, ``saved = state``)
    must run before the first yield — not gap as opaque. No suspension: the RHS
    is reduced and the name is bound into ``binding_state``, then the machine
    advances. Multi-target / non-Name stores stay OpaqueStepV1 until named.
    """

    name: str
    value: ConstructedTermSugar
    fragment_cid: str

    def __post_init__(self) -> None:
        _require_constructed_term(self.value, owner="AssignStepV1.value")


@dataclass(frozen=True)
class FinallyStepV1:
    """Cleanup suite as ConstructedTermSugar payloads only.

    Never carries ExprStatementSugar or other non-term statement wrappers —
    the producer projects each cleanup statement to its term sugar (e.g.
    CallSiteSugar for a bare call expression).
    """

    statements: tuple[ConstructedTermSugar, ...]
    cleanup_steps: tuple = ()

    def __post_init__(self) -> None:
        for statement in self.statements:
            _require_constructed_term(statement, owner="FinallyStepV1.statements")


@dataclass(frozen=True)
class ForStepV1:
    """Authenticated source construction for one generator ``for`` step.

    Transition remains a separate loud gap until the generator machine owns
    iterator advancement and authenticated StopIteration routing.
    """

    iterable: ConstructedTermSugar
    target_coordinates: tuple
    body_steps: tuple
    module_cid: str
    fragment_cid: str
    occurrence: object = field(compare=False, repr=False)

    def __post_init__(self) -> None:
        _require_constructed_term(self.iterable, owner="ForStepV1.iterable")
        if not self.target_coordinates:
            raise TypeError("ForStepV1 requires authenticated target coordinates")
        from sugar_source_tree.binding_provenance import BindingCoordinateV1

        coordinate_cids = []
        for coordinate in self.target_coordinates:
            if not isinstance(coordinate, BindingCoordinateV1):
                raise TypeError(
                    "ForStepV1 target coordinates must be authenticated "
                    "BindingCoordinateV1 values"
                )
            coordinate_cids.append(coordinate.cid)
        if len(coordinate_cids) != len(set(coordinate_cids)):
            raise TypeError("ForStepV1 target coordinates must be distinct")
        if any(
            coordinate.scope_owner_cid != self.module_cid
            for coordinate in self.target_coordinates
        ):
            from sugar_lift_py_tests.gap.panic import construction_panic_gap

            construction_panic_gap(
                owner="ForStepV1.__post_init__",
                blame=self.occurrence,
                observed="target coordinate outside authenticated module",
                requested="all target coordinates owned by ForStepV1.module_cid",
                fix="retain the producer-minted module coordinate without substitution",
            )
        occurrence_cid = self.occurrence.seal().cid
        if occurrence_cid != self.fragment_cid:
            from sugar_lift_py_tests.gap.panic import construction_panic_gap

            construction_panic_gap(
                owner="ForStepV1.__post_init__",
                blame=self.occurrence,
                observed="For occurrence and fragment CID disagree",
                requested="the producer-authenticated For source occurrence",
                fix="retain the occurrence paired with its own fragment CID",
            )
        for field_name, value in (
            ("module_cid", self.module_cid),
            ("fragment_cid", self.fragment_cid),
        ):
            if not isinstance(value, str) or not value.startswith("blake3-512:"):
                raise TypeError(f"ForStepV1.{field_name} must be authenticated")


@dataclass(frozen=True)
class RaiseStepV1:
    """Authenticated ``raise`` as a generator-step vocabulary row.

    Validation arms (``if bad: raise ValueError(...)``) and cleanup raises are
    named here so suspension-owning ``IfStepV1`` branches stay fully
    constructed. Transition desugars the RaiseSugar and halts with the effect.
    """

    raise_sugar: object = field(compare=False, repr=False)
    fragment_cid: str


@dataclass(frozen=True)
class TermStepV1:
    """One ConstructedTermSugar performed as a generator body statement.

    Admits pre-yield / cleanup expression calls (``set_option(pat, val)``) by
    the value's term sugar — never ExprStatementSugar.
    """

    term: ConstructedTermSugar
    fragment_cid: str

    def __post_init__(self) -> None:
        _require_constructed_term(self.term, owner="TermStepV1.term")


@dataclass(frozen=True)
class _ForIteratorStepV1:
    iterator: object = field(compare=False, repr=False)
    target_coordinates: tuple
    body_steps: tuple
    module_cid: str
    fragment_cid: str
    occurrence: object = field(compare=False, repr=False)


@dataclass(frozen=True)
class _YieldFromIteratorStepV1:
    iterator: object = field(compare=False, repr=False)
    occurrence: object = field(compare=False, repr=False)
    occurrence_cid: str


@dataclass(frozen=True)
class IfStepV1:
    """A branch inside a generator body, with each side's own step sequence.

    Carries SOURCE data only -- the guard's sugar, both branches' steps, and the
    `If` statement's own fragment CID. It deliberately does NOT carry a
    partition: the composite key needs the machine's `instance_coordinate`, and
    `allocate` mints that AFTER the producer has built the steps. Minting at
    TRANSITION time instead keeps the step tuple instance-agnostic, so one
    generator's steps can be shared by every instance over it while each mints
    its own partition. That is the property the key exists for.

    Admitted by the producer only when EVERY step in both branches is one the
    vocabulary can already execute — including pre-yield guarded setup
    (``if cond: x = …`` before yield) and suspension-owning branches
    (``if c: yield 1``). A branch holding a shape we cannot resume or perform
    -- ``x = yield v``, ``raise``, ``for``, etc. -- keeps the whole `If` an
    `OpaqueStepV1` and loud. Naming a step we cannot perform is worse than an
    honest opaque one.
    """

    guard: ConstructedTermSugar
    then_steps: tuple
    else_steps: tuple
    fragment_cid: str

    def __post_init__(self) -> None:
        _require_constructed_term(self.guard, owner="IfStepV1.guard")


@dataclass(frozen=True)
class NestedManagerStepV1:
    """Nested source-defined manager enter wrapping a body step sequence.

    Real shape: ``with inner(): yield outer_resource`` (and peers with
    Assign/If setup inside the With). Enter runs the nested protocol once,
    records :class:`NestedEnteredBindingV1`, splices ``body_steps`` plus an
    exit step, then continues. Unhandled nested shapes stay Opaque and loud.
    """

    nested_protocol: object = field(compare=False, repr=False)
    body_steps: tuple
    fragment_cid: str
    occurrence_cid: str


@dataclass(frozen=True)
class NestedManagerExitStepV1:
    """Exit the nested manager entered by the matching NestedManagerStepV1.

    Sits after the With body (after the yield suspension for the classic
    nested form). On resume *and* on throw, nested cleanup runs before the
    outer machine continues — inner cleanup before outer yield-resume.
    """

    occurrence_cid: str


GeneratorStepV1 = (
    YieldStepV1
    | YieldFromStepV1
    | ReturnStepV1
    | OpaqueStepV1
    | InertStepV1
    | AssignStepV1
    | FinallyStepV1
    | ForStepV1
    | RaiseStepV1
    | TermStepV1
    | _ForIteratorStepV1
    | _YieldFromIteratorStepV1
    | IfStepV1
    | NestedManagerStepV1
    | NestedManagerExitStepV1
)


def _generator_value_testimony(value: object, *, owner: str) -> dict:
    """Content-addressed testimony for one binding-state or step payload value."""
    if value is None:
        return {"kind": "null"}
    if isinstance(value, ResumeBindingV1):
        return {
            "kind": "resume-binding",
            "resumeCoordinate": value.resume_coordinate,
            "value": _generator_value_testimony(value.resume_value, owner=owner),
        }
    if isinstance(value, GeneratorAssignBindingV1):
        return {
            "kind": "assign-binding",
            "name": value.name,
            "fragmentCid": value.fragment_cid,
            "value": _generator_value_testimony(value.value, owner=owner),
        }
    if isinstance(value, GeneratorLoopBindingV1):
        return {
            "kind": "loop-binding",
            "coordinateCid": value.coordinate.cid,
            "demandCid": value.demand_cid,
            "value": _generator_value_testimony(value.value, owner=owner),
        }
    if isinstance(value, NestedEnteredBindingV1):
        return {
            "kind": "nested-entered-binding",
            "occurrenceCid": value.occurrence_cid,
            "nestedProtocolConstructionCid": value.nested_protocol_construction_cid,
            "nestedEntryCid": value.nested_entry_cid,
        }
    # Sealed BindingEntryV1: require producer-minted ConstructedValueTestimonyV1.
    # Consumer never fabricates testimony; unsealed entries refuse here.
    from sugar_source_tree.binding_state import BindingEntryV1

    if isinstance(value, BindingEntryV1):
        testimony = value.require_constructed_value_testimony()
        return {
            "kind": "sealed-bound-binding",
            "coordinateCid": value.coordinate.cid,
            "constructedValueTestimonyCid": testimony.cid,
            "entry": value.wire(),
        }
    if isinstance(value, ConstructedTermSugar):
        from sugar_lift_py_tests.ir import _term_content_cid

        return {
            "kind": "term-cid",
            "contentCid": _term_content_cid(value.to_term(owner=owner)),
        }
    # IR Terms are already content-addressable without a FloorValue wrapper.
    from sugar_lift_py_tests.ir import (
        _ConstBool,
        _ConstInt,
        _ConstReal,
        _ConstStr,
        _Ctor,
        _Lambda,
        _Var,
        _term_content_cid,
    )

    if isinstance(
        value, (_Ctor, _ConstInt, _ConstStr, _ConstBool, _ConstReal, _Var, _Lambda)
    ):
        return {"kind": "term-cid", "contentCid": _term_content_cid(value)}
    fragment = getattr(value, "fragment", None)
    if fragment is not None:
        seal = getattr(fragment, "seal", None)
        if callable(seal):
            return {"kind": "fragment-cid", "contentCid": seal().cid}
    wire = getattr(value, "wire", None)
    if callable(wire):
        return {"kind": "wire", "payload": wire()}
    if isinstance(value, (str, int, bool)):
        return {"kind": "primitive", "value": value}
    raise TypeError(
        f"{owner} cannot content-address value of type {type(value).__name__}; "
        "project authenticated construction testimony, never object identity"
    )


def _generator_step_testimony(step: object, *, owner: str) -> dict:
    """Content-addressed testimony for one generator step."""
    if isinstance(step, YieldStepV1):
        return {
            "kind": "yield",
            "value": _generator_value_testimony(step.value, owner=owner),
        }
    if isinstance(step, YieldFromStepV1):
        return {
            "kind": "yield-from",
            "occurrenceCid": step.occurrence_cid,
            "iterable": _generator_value_testimony(step.iterable, owner=owner),
        }
    if isinstance(step, ReturnStepV1):
        return {
            "kind": "return",
            "value": _generator_value_testimony(step.value, owner=owner),
        }
    if isinstance(step, OpaqueStepV1):
        return {
            "kind": "opaque",
            "observed": step.observed,
            "carriesSuspension": step.carries_suspension,
        }
    if isinstance(step, InertStepV1):
        return {"kind": "inert", "observed": step.observed}
    if isinstance(step, AssignStepV1):
        return {
            "kind": "assign",
            "name": step.name,
            "fragmentCid": step.fragment_cid,
            "value": _generator_value_testimony(step.value, owner=owner),
        }
    if isinstance(step, FinallyStepV1):
        return {
            "kind": "finally",
            "statements": [
                _generator_value_testimony(item, owner=owner)
                for item in step.statements
            ],
            "cleanupSteps": [
                _generator_step_testimony(item, owner=owner)
                for item in step.cleanup_steps
            ],
        }
    if isinstance(step, ForStepV1):
        return {
            "kind": "for",
            "moduleCid": step.module_cid,
            "fragmentCid": step.fragment_cid,
            "iterable": _generator_value_testimony(step.iterable, owner=owner),
            "targetCoordinateCids": [
                coordinate.cid for coordinate in step.target_coordinates
            ],
            "bodySteps": [
                _generator_step_testimony(item, owner=owner) for item in step.body_steps
            ],
        }
    if isinstance(step, RaiseStepV1):
        return {
            "kind": "raise",
            "fragmentCid": step.fragment_cid,
            "raiseSugar": _generator_value_testimony(step.raise_sugar, owner=owner),
        }
    if isinstance(step, TermStepV1):
        return {
            "kind": "term",
            "fragmentCid": step.fragment_cid,
            "term": _generator_value_testimony(step.term, owner=owner),
        }
    if isinstance(step, _ForIteratorStepV1):
        return {
            "kind": "for-iterator",
            "moduleCid": step.module_cid,
            "fragmentCid": step.fragment_cid,
            "targetCoordinateCids": [c.cid for c in step.target_coordinates],
            "bodySteps": [
                _generator_step_testimony(item, owner=owner) for item in step.body_steps
            ],
        }
    if isinstance(step, _YieldFromIteratorStepV1):
        return {
            "kind": "yield-from-iterator",
            "occurrenceCid": step.occurrence_cid,
        }
    if isinstance(step, IfStepV1):
        return {
            "kind": "if",
            "fragmentCid": step.fragment_cid,
            "guard": _generator_value_testimony(step.guard, owner=owner),
            "thenSteps": [
                _generator_step_testimony(item, owner=owner) for item in step.then_steps
            ],
            "elseSteps": [
                _generator_step_testimony(item, owner=owner) for item in step.else_steps
            ],
        }
    if isinstance(step, NestedManagerStepV1):
        nested_cid = getattr(
            step.nested_protocol, "protocol_construction_cid", None
        )
        return {
            "kind": "nested-manager",
            "fragmentCid": step.fragment_cid,
            "occurrenceCid": step.occurrence_cid,
            "nestedProtocolConstructionCid": nested_cid,
            "bodySteps": [
                _generator_step_testimony(item, owner=owner) for item in step.body_steps
            ],
        }
    if isinstance(step, NestedManagerExitStepV1):
        return {
            "kind": "nested-manager-exit",
            "occurrenceCid": step.occurrence_cid,
        }
    raise TypeError(
        f"{owner} cannot content-address step of type {type(step).__name__}"
    )


@dataclass(frozen=True)
class ResumeBindingV1:
    resume_coordinate: str
    resume_value: object


@dataclass(frozen=True)
class GeneratorAssignBindingV1:
    """One name bound by an executed AssignStepV1 on the live machine."""

    name: str
    value: object
    fragment_cid: str


@dataclass(frozen=True)
class GeneratorLoopBindingV1:
    coordinate: object
    value: object = field(compare=False, repr=False)
    occurrence: object = field(compare=False, repr=False)
    demand_cid: str


@dataclass(frozen=True)
class NestedEnteredBindingV1:
    """Nested manager entered while executing NestedManagerStepV1.

    Carries enough to exit the nested layer exactly once (occurrence + nested
    protocol construction CID + nested entry CID + the entered state handle).
    """

    occurrence_cid: str
    nested_protocol_construction_cid: str
    nested_entry_cid: str
    nested_protocol: object = field(compare=False, repr=False)
    nested_entered: object = field(compare=False, repr=False)


@dataclass(frozen=True)
class GeneratorTerminationV1:
    return_value: object | None
    binding_state: tuple[object, ...]


@dataclass(frozen=True)
class GeneratorTransitionGapV1:
    owner: str
    observed: str
    requested: str
    fix: str = "construct the transition in GeneratorConstructionV1"


@dataclass(frozen=True)
class YieldEffect:
    value: object
    resume_coordinate: str
    machine: "GeneratorConstructionV1"


@dataclass(frozen=True)
class GeneratorConstructionV1:
    """One allocated generator instance and its suspended frame state."""

    allocation_coordinate: str
    frame_coordinate: str
    binding_state: tuple[object, ...]
    steps: tuple[GeneratorStepV1, ...]
    instance_coordinate: str
    cursor: int = 0
    suspended_resume_coordinate: str | None = None
    # Binder-produced formal Floors (coordinate.cid → FloorValue identity).
    # Guard temporal installs these directly — never Node.sugar()/desugar().
    formal_floor_bindings: tuple[FormalFloorBindingV1, ...] = field(
        default=(), compare=False, repr=False
    )
    # Caller reduction context preserved from CallSiteSugar.desugar; guard
    # evaluation extends its temporal rather than fabricating a temporal-only
    # substitute context.
    reduction_context: object | None = field(default=None, compare=False, repr=False)

    @classmethod
    def allocate(
        cls,
        *,
        allocation_coordinate: str,
        frame_coordinate: str,
        binding_state: tuple[object, ...],
        steps: tuple[GeneratorStepV1, ...],
        formal_floor_bindings: tuple[FormalFloorBindingV1, ...] = (),
        reduction_context: object | None = None,
    ) -> "GeneratorConstructionV1":
        from sugar_source_tree.binding_state import (
            BindingEntryV1,
            seal_generator_binding_state_v1,
        )

        # Producer seal: every BindingEntryV1 carries ConstructedValueTestimonyV1
        # before the instance exists. Unavailable testimony gaps here, never as
        # a delayed BindingStateWireGap on a "successfully" sealed state.
        binding_state = seal_generator_binding_state_v1(binding_state)
        formal_floor_bindings = tuple(formal_floor_bindings)
        # Roster law: every sealed formal BindingEntryV1 has exactly one
        # FormalFloorBindingV1 at the same coordinate CID, and no foreign
        # coordinates are admitted.  Unrelated coordinate + arbitrary object
        # cannot resolve a guard.
        sealed_formal_cids = tuple(
            entry.coordinate.cid
            for entry in binding_state
            if isinstance(entry, BindingEntryV1)
        )
        floor_cids = tuple(item.coordinate_cid for item in formal_floor_bindings)
        if len(floor_cids) != len(set(floor_cids)):
            raise FormalFloorBindingGap(
                "formal floor bindings must not duplicate a formal coordinate"
            )
        if set(floor_cids) != set(sealed_formal_cids):
            raise FormalFloorBindingGap(
                "formal floor coordinate roster must equal sealed BindingEntryV1 "
                f"formal roster; floors={sorted(floor_cids)!r} "
                f"sealed={sorted(sealed_formal_cids)!r}"
            )
        if reduction_context is not None and not callable(
            getattr(reduction_context, "with_temporal", None)
        ):
            raise TypeError(
                "reduction_context must expose with_temporal(temporal) when "
                f"provided; got {type(reduction_context).__name__}"
            )
        instance_coordinate = cid_of_json(
            {
                "kind": "python-generator-instance",
                "schemaVersion": "1",
                "allocationCoordinate": allocation_coordinate,
                "frameCoordinate": frame_coordinate,
                "bindingState": [repr(item) for item in binding_state],
                "formalFloorCoordinateCids": [
                    item.coordinate_cid for item in formal_floor_bindings
                ],
            }
        )
        return cls(
            allocation_coordinate=allocation_coordinate,
            frame_coordinate=frame_coordinate,
            binding_state=binding_state,
            steps=tuple(steps),
            instance_coordinate=instance_coordinate,
            formal_floor_bindings=formal_floor_bindings,
            reduction_context=reduction_context,
        )

    def construction_term_preimage(self) -> dict:
        """Authenticated construction + lifecycle content for term projection.

        Derives solely from construction coordinates (allocation/frame/instance),
        step testimony, binding-state testimony, and lifecycle (cursor /
        suspended resume). Never object identity, class spelling, or a
        fabricated generic manager DTO disconnected from this preimage.
        """
        return {
            "kind": "python-generator-construction-term",
            "schemaVersion": "1",
            "allocationCoordinate": self.allocation_coordinate,
            "frameCoordinate": self.frame_coordinate,
            "instanceCoordinate": self.instance_coordinate,
            "cursor": self.cursor,
            "suspendedResumeCoordinate": self.suspended_resume_coordinate,
            "bindingState": [
                _generator_value_testimony(item, owner="GeneratorConstructionV1")
                for item in self.binding_state
            ],
            "steps": [
                _generator_step_testimony(step, owner="GeneratorConstructionV1")
                for step in self.steps
            ],
        }

    def construction_term_cid(self) -> str:
        return cid_of_json(self.construction_term_preimage())

    def to_term(self, *, owner: str):
        """Canonical term for ManagerBinding and other record testimony.

        Content-addressed over :meth:`construction_term_preimage`. Identical
        construction and lifecycle yield identical terms; any change to
        generator/frame/state testimony changes the term.
        """
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:generator-construction",
            [str_const(self.construction_term_cid())],
            symbol_kind="coordinate",
        )

    def resume(self):
        return self._transition("resume")

    def send(self, value: object):
        if self.suspended_resume_coordinate is None:
            return self._gap("send", "generator is not suspended at a yield")
        machine = replace(
            self,
            binding_state=(
                *self.binding_state,
                ResumeBindingV1(self.suspended_resume_coordinate, value),
            ),
            suspended_resume_coordinate=None,
        )
        return machine._transition("send")

    def throw(self, effect: Effect) -> ExitSet:
        require_effect(effect)
        incoming = ExitSet.halted(effect, state=self)
        if self.cursor < len(self.steps) and isinstance(
            self.steps[self.cursor], NestedManagerExitStepV1
        ):
            # Halted edge: nested cleanup BEFORE outer yield-resume / halt.
            step = self.steps[self.cursor]
            after = self._exit_nested_manager(step, requested="throw")
            if isinstance(after, GeneratorTransitionGapV1):
                return ExitSet.halted(effect, state=self)
            if isinstance(after, GeneratorConstructionV1):
                return ExitSet.halted(effect, state=after)
            return incoming
        if self.cursor < len(self.steps) and isinstance(
            self.steps[self.cursor], FinallyStepV1
        ):
            step = self.steps[self.cursor]
            return incoming.and_finally(lambda: self._reduce_finally(step))
        return incoming

    def close(self):
        if self.cursor < len(self.steps) and isinstance(
            self.steps[self.cursor], NestedManagerExitStepV1
        ):
            step = self.steps[self.cursor]
            after = self._exit_nested_manager(step, requested="close")
            if isinstance(after, GeneratorConstructionV1):
                return after.close()
            if isinstance(after, GeneratorTransitionGapV1):
                return after
        if self.cursor < len(self.steps) and isinstance(
            self.steps[self.cursor], FinallyStepV1
        ):
            cleanup = self._reduce_finally(self.steps[self.cursor])
            return cleanup.sequence(
                lambda state: ExitSet.completed(
                    GeneratorTerminationV1(None, self.binding_state)
                )
            )
        return GeneratorTerminationV1(None, self.binding_state)

    def _transition(self, requested: str):
        if self.cursor >= len(self.steps):
            return GeneratorTerminationV1(None, self.binding_state)
        step = self.steps[self.cursor]
        if isinstance(step, OpaqueStepV1):
            return self._gap(requested, step.gap_observed())
        if isinstance(step, InertStepV1):
            # Owes nothing, so there is nothing to perform and nothing to
            # refuse: advance and let the NEXT step answer. This is what makes
            # the machine report its first real blocker instead of the first
            # statement it happens to meet.
            machine = replace(self, cursor=self.cursor + 1)
            return machine._transition(requested)
        if isinstance(step, AssignStepV1):
            # Pre-yield (and peer) simple name assignment on the live machine.
            value = self._reduce_value(step.value, requested)
            if isinstance(value, GeneratorTransitionGapV1):
                return value
            binding = GeneratorAssignBindingV1(step.name, value, step.fragment_cid)
            machine = replace(
                self,
                cursor=self.cursor + 1,
                binding_state=(*self.binding_state, binding),
            )
            return machine._transition(requested)
        if isinstance(step, RaiseStepV1):
            from sugar_lift_py_tests.outcome import Incomplete

            outcome = step.raise_sugar.desugar(self._guard_evaluation_context())
            if isinstance(outcome, Incomplete):
                return ExitSet.halted(outcome.effect, state=self)
            return self._gap(requested, f"raise did not halt ({type(outcome).__name__})")
        if isinstance(step, TermStepV1):
            outcome = step.term.desugar(self._guard_evaluation_context())
            from sugar_lift_py_tests.outcome import Complete, Incomplete

            if isinstance(outcome, Incomplete):
                return ExitSet.halted(outcome.effect, state=self)
            if not isinstance(outcome, Complete):
                return self._gap(requested, type(outcome).__name__)
            machine = replace(self, cursor=self.cursor + 1)
            return machine._transition(requested)
        if isinstance(step, ForStepV1):
            return self._transition_for(step, requested)
        if isinstance(step, _ForIteratorStepV1):
            return self._transition_for_iterator(step, requested)
        if isinstance(step, YieldFromStepV1):
            return self._transition_yield_from(step, requested)
        if isinstance(step, _YieldFromIteratorStepV1):
            return self._transition_yield_from_iterator(step, requested)
        if isinstance(step, NestedManagerStepV1):
            return self._transition_nested_manager(step, requested)
        if isinstance(step, NestedManagerExitStepV1):
            after = self._exit_nested_manager(step, requested=requested)
            if isinstance(after, GeneratorTransitionGapV1):
                return after
            return after._transition(requested)
        if isinstance(step, FinallyStepV1):
            if step.cleanup_steps:
                return self._gap(
                    requested,
                    "FinallyStepV1 structured cleanup steps require generator "
                    "cleanup transition composition",
                )
            cleanup = self._reduce_finally(step)
            from sugar_lift_py_tests.outcome import Completed, Halted

            if any(isinstance(exit_, Halted) for exit_ in cleanup.exits):
                return cleanup
            completed = tuple(
                exit_ for exit_ in cleanup.exits if isinstance(exit_, Completed)
            )
            binding_state = self.binding_state
            if len(completed) == 1 and isinstance(
                completed[0].value, GeneratorTerminationV1
            ):
                binding_state = completed[0].value.binding_state
            machine = replace(
                self,
                cursor=self.cursor + 1,
                binding_state=binding_state,
            )
            return machine._transition(requested)
        if isinstance(step, IfStepV1):
            return self._transition_branch(step, requested)
        if isinstance(step, ForStepV1):
            return self._gap(
                requested,
                "ForStepV1 requires iter_with/next_with transition and "
                "authenticated StopIteration routing",
            )
        if isinstance(step, ReturnStepV1):
            value = self._reduce_value(step.value, requested)
            if isinstance(value, GeneratorTransitionGapV1):
                return value
            return GeneratorTerminationV1(value, self.binding_state)
        value = self._reduce_value(step.value, requested)
        if isinstance(value, GeneratorTransitionGapV1):
            return value
        resume_coordinate = f"{self.instance_coordinate}:resume:{self.cursor + 1}"
        machine = replace(
            self,
            cursor=self.cursor + 1,
            suspended_resume_coordinate=resume_coordinate,
        )
        return YieldEffect(value, resume_coordinate, machine)

    def _transition_for(self, step: ForStepV1, requested: str):
        from sugar_lift_py_tests.operations import IteratorOperation
        from sugar_lift_py_tests.outcome import Complete, Incomplete

        iterable = step.iterable.desugar(self._guard_evaluation_context())
        if isinstance(iterable, Incomplete):
            return ExitSet.halted(iterable.effect, state=self)
        if not isinstance(iterable, Complete):
            return self._gap(requested, type(iterable).__name__)
        iterator = IteratorOperation(
            owner="GeneratorConstructionV1.ForStepV1.iter",
            blame=step.occurrence,
        ).submit(iterable.value, self._guard_evaluation_context())
        if isinstance(iterator, Incomplete):
            return ExitSet.halted(iterator.effect, state=self)
        if not isinstance(iterator, Complete):
            return self._gap(requested, type(iterator).__name__)
        runtime = _ForIteratorStepV1(
            iterator.value,
            step.target_coordinates,
            step.body_steps,
            step.module_cid,
            step.fragment_cid,
            step.occurrence,
        )
        machine = replace(self, steps=(*self.steps[: self.cursor], runtime, *self.steps[self.cursor + 1 :]))
        return machine._transition(requested)

    def _transition_yield_from(self, step: YieldFromStepV1, requested: str):
        from sugar_lift_py_tests.operations import IteratorOperation
        from sugar_lift_py_tests.outcome import Complete, Incomplete

        iterable = step.iterable.desugar(self._guard_evaluation_context())
        if isinstance(iterable, Incomplete):
            return ExitSet.halted(iterable.effect, state=self)
        if not isinstance(iterable, Complete):
            return self._gap(requested, type(iterable).__name__)
        iterator = IteratorOperation(
            owner="GeneratorConstructionV1.YieldFromStepV1.iter",
            blame=step.occurrence,
        ).submit(iterable.value, self._guard_evaluation_context())
        if isinstance(iterator, Incomplete):
            return ExitSet.halted(iterator.effect, state=self)
        if not isinstance(iterator, Complete):
            return self._gap(requested, type(iterator).__name__)
        runtime = _YieldFromIteratorStepV1(
            iterator.value, step.occurrence, step.occurrence_cid
        )
        machine = replace(
            self,
            steps=(
                *self.steps[: self.cursor],
                runtime,
                *self.steps[self.cursor + 1 :],
            ),
        )
        return machine._transition(requested)

    def _transition_yield_from_iterator(
        self, step: _YieldFromIteratorStepV1, requested: str
    ):
        from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
        from sugar_lift_py_tests.floor.ground_exit import ground_raise_effect
        from sugar_lift_py_tests.floor.iterator_value import NextResult
        from sugar_lift_py_tests.operations import NextOperation
        from sugar_lift_py_tests.outcome import Complete, Incomplete

        outcome = NextOperation(
            owner="GeneratorConstructionV1.YieldFromStepV1.next",
            blame=step.occurrence,
        ).submit(step.iterator, self._guard_evaluation_context())
        if isinstance(outcome, Incomplete):
            effect = outcome.effect
            stop_identity = ground_raise_effect(
                exception_name="StopIteration",
                site=step.occurrence,
                owner="GeneratorConstructionV1.YieldFromStepV1.next",
            ).exception_type_coordinate
            if (
                isinstance(effect, RaiseEffect)
                and effect.exception_type_coordinate == stop_identity
                and effect.occurrence == str(step.occurrence)
            ):
                machine = replace(self, cursor=self.cursor + 1)
                return machine._transition(requested)
            return ExitSet.halted(effect, state=self)
        if not isinstance(outcome, Complete) or not isinstance(
            outcome.value, NextResult
        ):
            return self._gap(requested, f"next_with returned {type(outcome).__name__}")

        runtime = replace(step, iterator=outcome.value.advanced)
        machine = replace(
            self,
            steps=(
                *self.steps[: self.cursor],
                runtime,
                *self.steps[self.cursor + 1 :],
            ),
        )
        resume_coordinate = f"{self.instance_coordinate}:resume:{self.cursor + 1}"
        machine = replace(machine, suspended_resume_coordinate=resume_coordinate)
        return YieldEffect(outcome.value.value, resume_coordinate, machine)

    def _transition_for_iterator(self, step: _ForIteratorStepV1, requested: str):
        from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
        from sugar_lift_py_tests.floor.ground_exit import ground_raise_effect
        from sugar_lift_py_tests.floor.iterator_value import NextResult
        from sugar_lift_py_tests.operations import NextOperation
        from sugar_lift_py_tests.operations.positional_unpack_operation import (
            PositionalUnpackOperation,
            UnpackMemberRoster,
        )
        from sugar_lift_py_tests.outcome import Complete, Incomplete

        outcome = NextOperation(
            owner="GeneratorConstructionV1.ForStepV1.next",
            blame=step.occurrence,
        ).submit(step.iterator, self._guard_evaluation_context())
        if isinstance(outcome, Incomplete):
            effect = outcome.effect
            stop_identity = ground_raise_effect(
                exception_name="StopIteration",
                site=step.occurrence,
                owner="GeneratorConstructionV1.ForStepV1.next",
            ).exception_type_coordinate
            if (
                isinstance(effect, RaiseEffect)
                and effect.exception_type_coordinate == stop_identity
                and effect.occurrence == str(step.occurrence)
            ):
                machine = replace(self, cursor=self.cursor + 1)
                return machine._transition(requested)
            return ExitSet.halted(effect, state=self)
        if not isinstance(outcome, Complete) or not isinstance(outcome.value, NextResult):
            return self._gap(requested, f"next_with returned {type(outcome).__name__}")

        unpack = PositionalUnpackOperation(
            fixed_prefix=len(step.target_coordinates),
            fixed_suffix=0,
            has_star=False,
            owner="GeneratorConstructionV1.ForStepV1.target",
            blame=step.occurrence,
        ).submit(outcome.value.value, self._guard_evaluation_context())
        if isinstance(unpack, Incomplete):
            return ExitSet.halted(unpack.effect, state=self)
        if not isinstance(unpack, Complete) or not isinstance(unpack.value, UnpackMemberRoster):
            return self._gap(requested, f"target unpack returned {type(unpack).__name__}")
        bindings = tuple(
            GeneratorLoopBindingV1(coordinate, member, unpack.value.occurrence, unpack.value.demand_cid)
            for coordinate, member in zip(
                step.target_coordinates, unpack.value.members, strict=True
            )
        )
        recurrence = replace(step, iterator=outcome.value.advanced)
        steps = (
            *self.steps[: self.cursor],
            *step.body_steps,
            recurrence,
            *self.steps[self.cursor + 1 :],
        )
        machine = replace(self, steps=steps, binding_state=(*self.binding_state, *bindings))
        return machine._transition(requested)

    def _transition_nested_manager(self, step: NestedManagerStepV1, requested: str):
        """Enter nested protocol, bind entered state, splice body + exit step."""
        from sugar_lift_py_tests.outcome import Complete, Incomplete

        enter = getattr(step.nested_protocol, "enter_resource_outcome", None)
        if not callable(enter):
            return self._gap(requested, "nested manager without enter_resource_outcome")
        outcome = enter()
        if isinstance(outcome, Incomplete):
            return outcome
        if not isinstance(outcome, Complete):
            return self._gap(
                requested, f"nested enter observed {type(outcome).__name__}"
            )
        nested_entered = outcome.value
        nested_cid = getattr(
            step.nested_protocol, "protocol_construction_cid", ""
        ) or getattr(nested_entered, "protocol_construction_cid", "")
        entry_cid = getattr(nested_entered, "entry_cid", "")
        binding = NestedEnteredBindingV1(
            occurrence_cid=step.occurrence_cid,
            nested_protocol_construction_cid=nested_cid,
            nested_entry_cid=entry_cid,
            nested_protocol=step.nested_protocol,
            nested_entered=nested_entered,
        )
        steps = (
            *self.steps[: self.cursor],
            *step.body_steps,
            NestedManagerExitStepV1(step.occurrence_cid),
            *self.steps[self.cursor + 1 :],
        )
        machine = replace(
            self,
            steps=steps,
            binding_state=(*self.binding_state, binding),
            # cursor stays at first body step (same index as NestedManagerStep)
        )
        return machine._transition(requested)

    def _exit_nested_manager(self, step: NestedManagerExitStepV1, *, requested: str):
        """Exit the nested layer for this occurrence; advance past the exit step."""
        binding = None
        for item in reversed(self.binding_state):
            if (
                isinstance(item, NestedEnteredBindingV1)
                and item.occurrence_cid == step.occurrence_cid
            ):
                binding = item
                break
        if binding is None:
            return self._gap(
                requested, f"nested exit without enter ({step.occurrence_cid})"
            )
        exit_for = getattr(binding.nested_protocol, "exit_outcome_for", None)
        if not callable(exit_for):
            return self._gap(requested, "nested manager without exit_outcome_for")
        exit_for(binding.nested_entered)
        return replace(self, cursor=self.cursor + 1)

    def _transition_branch(self, step: "IfStepV1", requested: str):
        """A branch is a two-face partition, or a splice when the guard decides.

        A DECIDED guard is not a partition: exactly one side runs, so its steps
        are spliced into this machine's sequence and nothing is minted. Minting
        a family over a route the producer does not actually decide would assert
        an exhaustiveness that is not true.

        An UNDECIDED guard is a genuine two-face split. Each face is a distinct
        successor machine with its own cursor -- the partition lives in the
        `ExitSet`, never in the machine, which is why no `faces` field is needed
        here. `factor_completed` then moves the partition from the exit level
        (where `sequence` multiplies it, m ** k over k steps) to the value level
        (one arm carrying a `GuardedValue` chain, which composes).

        THE KEY IS COMPOSITE. `("generator.branch", instance_coordinate,
        fragment_cid)`: the fragment gives reproducibility -- two reads of one
        instance's branch mint the same partition -- and the instance
        coordinate keeps two live generators over one source branch from
        looking like two sides of ONE split. `_faces_exclusive` never reads the
        arms' guards, so a source-only key would let the algebra declare two
        unrelated executions exclusive and re-attribute one's value to the
        negation of the other's guard. Same shape as the loop carrier's
        `targetCid` occurrence (see
        `test_two_occurrences_with_identical_faces_are_different_states`).
        """
        from dataclasses import replace as _replace

        from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet, partition

        from sugar_lift_py_tests.outcome import Complete, Halted, Incomplete

        guard_outcome = self._guard_truth(step.guard)
        if isinstance(guard_outcome, ExitSet):
            if guard_outcome.exits and all(
                isinstance(face, Halted) for face in guard_outcome.exits
            ):
                return ExitSet(
                    tuple(
                        Halted(
                            face.guard,
                            face.effect,
                            self,
                            face.faces,
                            face.pending_contracts,
                        )
                        for face in guard_outcome.exits
                    )
                )
            return self._gap(requested, "If guard has mixed completed/halted faces")
        if isinstance(guard_outcome, Incomplete):
            return ExitSet.halted(guard_outcome.effect, state=self)
        if not isinstance(guard_outcome, Complete):
            return self._gap(requested, "If carrying a suspension")

        truth = guard_outcome.value
        decided = self._decide_guard(truth)
        if decided is True:
            return self._spliced(step.then_steps)._transition(requested)
        if decided is False:
            return self._spliced(step.else_steps)._transition(requested)

        guard_formula = self._guard_formula(truth)
        if guard_formula is None:
            return self._gap(requested, "If carrying a suspension")

        then_face, else_face = partition(
            ("generator.branch", self.instance_coordinate, step.fragment_cid)
        )
        from sugar_lift_py_tests.ir import not_

        return ExitSet(
            (
                Completed(
                    guard_formula,
                    self._spliced(step.then_steps),
                    frozenset({then_face}),
                    (),
                ),
                Completed(
                    not_(guard_formula),
                    self._spliced(step.else_steps),
                    frozenset({else_face}),
                    (),
                ),
            )
        ).factor_completed()

    def _spliced(self, branch_steps: tuple) -> "GeneratorConstructionV1":
        """This machine with the branch's steps in place of the `If`."""
        from dataclasses import replace as _replace

        steps = (
            *self.steps[: self.cursor],
            *branch_steps,
            *self.steps[self.cursor + 1 :],
        )
        return _replace(self, steps=steps)

    def _guard_evaluation_context(self):
        """Caller reduction context extended with binder-produced formal Floors.

        Installs each :class:`FormalFloorBindingV1` by coordinate CID into the
        temporal table (object identity of the binder Floor).  Also installs
        post-assign names already reduced on this machine.

        When a caller ``reduction_context`` was carried into allocate it **must**
        expose ``with_temporal`` through ``ReduceContext``; the
        typed surface is required — no hasattr/dataclass probe ladder.  The
        binder-only shell is only for explicitly context-free test allocate
        (``reduction_context=None``).  BindingCoordinateRefSugar.desugar remains
        the sole consumer door.
        """
        from sugar_lift_py_tests.temporal.temporal_context import TemporalContext

        base = self.reduction_context
        if base is None:
            temporal = TemporalContext()
        else:
            temporal = base.temporal

        for binding in self.formal_floor_bindings:
            temporal = temporal.bind_value(
                binding.coordinate_cid, binding.floor_value
            )
        for item in self.binding_state:
            if isinstance(item, GeneratorAssignBindingV1) and item.value is not None:
                temporal = temporal.bind_value(item.name, item.value)
            if isinstance(item, GeneratorLoopBindingV1):
                temporal = temporal.bind_value(item.coordinate.cid, item.value)

        if base is None:
            return _BinderOnlyReduceCtx(temporal)
        return base.with_temporal(temporal)

    def _guard_truth(self, guard: object):
        """The guard's typed truth outcome, or None if it cannot stand.

        A branch guard is not the operand -- it is the operand's truth, which
        is exactly what `FloorValue.truth` already states for every value that
        can answer it. Reading the operand's type directly would be a second,
        weaker copy of that law: `NoneValue.truth` is False, a container's is
        its non-emptiness, and a symbolic value's is a predicate. Routing
        through `truth` keeps one owner for the question.

        Guard Sugar is reduced under :meth:`_guard_evaluation_context` so
        BindingCoordinateRefSugar resolves binder Floors at the exact
        coordinate CID (and only there).
        """
        from sugar_lift_py_tests.outcome import Complete, ExitSet, Incomplete
        from sugar_lift_py_tests.sugar.sugar_base import Sugar
        from sugar_source_tree.panic import SugarNotWritten

        value = guard
        if isinstance(guard, Sugar):
            ctx = self._guard_evaluation_context()
            try:
                outcome = guard.desugar(ctx)
            except SugarNotWritten:
                # Unspecialized / wrong-coordinate formal: not a ground truth.
                # Surface as undecided (None) so the branch stays a loud gap or
                # partition path rather than inventing a default.
                return None
            if isinstance(outcome, Incomplete):
                return outcome
            if isinstance(outcome, ExitSet):
                return outcome
            if not isinstance(outcome, Complete):
                return None
            value = outcome.value
        truth = getattr(value, "truth", None)
        if truth is None:
            return None
        # ConstructionPanic is BaseException by design so ordinary Exception
        # handlers cannot silence it. Do not catch BaseException here — that
        # would reclassify incomplete floors as undecided suspension gaps.
        outcome = truth(self.instance_coordinate)
        if isinstance(outcome, (Complete, Incomplete)):
            return outcome
        return None

    def _decide_guard(self, truth: object):
        """True/False when the guard's truth is ground, None when it is not."""
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        if isinstance(truth, TrueBoolLiteralSugar):
            return True
        if isinstance(truth, FalseBoolLiteralSugar):
            return False
        return None

    def _guard_formula(self, truth: object):
        """The guard's truth as a Formula, or None when it cannot stand."""
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue

        if isinstance(truth, PredicateValue):
            return truth.formula
        to_formula = getattr(truth, "to_formula", None)
        if to_formula is not None:
            # Same law as _guard_truth: never catch BaseException / ConstructionPanic.
            return to_formula()
        return None

    def _reduce_value(self, value: object, requested: str):
        if value is None:
            return None
        from sugar_lift_py_tests.outcome import Complete
        from sugar_lift_py_tests.sugar.sugar_base import Sugar
        from sugar_source_tree.panic import SugarNotWritten

        if not isinstance(value, Sugar):
            return value
        ctx = self._guard_evaluation_context()
        try:
            outcome = value.desugar(ctx)
        except SugarNotWritten as exc:
            observed = getattr(exc, "observed", type(exc).__name__)
            return self._gap(requested, str(observed))
        if isinstance(outcome, Complete):
            return outcome.value
        return self._gap(requested, type(outcome).__name__)

    def _reduce_finally(self, step: FinallyStepV1) -> ExitSet:
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            reduce_block_to_exitset,
        )

        if step.cleanup_steps:
            cleanup_machine = replace(
                self,
                steps=(*step.cleanup_steps, ReturnStepV1()),
                cursor=0,
                suspended_resume_coordinate=None,
            )
            result = cleanup_machine._transition("finally cleanup")
            if isinstance(result, GeneratorTerminationV1):
                return ExitSet.completed(result)
            if isinstance(result, ExitSet):
                return result
            from sugar_lift_py_tests.gap.panic import construction_panic_gap

            construction_panic_gap(
                owner="GeneratorConstructionV1._reduce_finally",
                blame=step,
                observed=f"cleanup transitioned to {type(result).__name__}",
                requested="completed or halted cleanup",
                fix="keep suspension and unresolved steps out of a finally cleanup suite",
            )
        return reduce_block_to_exitset(step.statements)

    @staticmethod
    def _gap(requested: str, observed: str) -> GeneratorTransitionGapV1:
        return GeneratorTransitionGapV1(
            owner="GeneratorConstructionV1.transition",
            observed=observed,
            requested=requested,
        )
