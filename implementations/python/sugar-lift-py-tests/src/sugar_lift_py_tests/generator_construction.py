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
    coordinate: object | None = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(
            self.coordinate_cid, str
        ) or not self.coordinate_cid.startswith("blake3-512:"):
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
        if self.coordinate is not None:
            from sugar_source_tree.binding_provenance import BindingCoordinateV1

            if (
                type(self.coordinate) is not BindingCoordinateV1
                or self.coordinate.cid != self.coordinate_cid
                or cid_of_json(self.coordinate.preimage) != self.coordinate.cid
                or BindingCoordinateV1.decode(self.coordinate.wire()) != self.coordinate
            ):
                raise FormalFloorBindingGap(
                    "projected formal floor binding has foreign coordinate testimony"
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
class YieldAssignUnpackV1:
    """The unpacking a yield assignment's targets spell (``a, b = yield v``,
    ``a, *b = yield v``, ``(a, (b, c)) = yield v``): Name leaves, flat with at
    most one ``*Name``, or a nested Name-only tree (``pattern``).

    It is the demand an ordinary unpack makes of its one evaluation
    (``DynamicUnpackAssignSugar``; ``NestedDynamicUnpackAssignSugar`` for a
    nested tree): ``SequenceProjectionOperation`` asks the value what it
    unpacks to, level by level.  For a nested tree ``prefix_names`` holds
    every leaf, in source order.
    """

    prefix_names: tuple[str, ...]
    star_name: str | None = None
    suffix_names: tuple[str, ...] = ()
    pattern: tuple | None = None

    def project(self, value: object, ctx: object, *, owner: str, blame: object):
        """The unpack of ``value``: an ExitSet whose completed face is the
        ``ScopeRebinds`` of every leaf, or the unpack's halt."""
        if self.pattern is not None:
            from sugar_lift_py_tests.sugar.nested_dynamic_unpack_assign_sugar import (
                project_nested_pattern,
            )

            return project_nested_pattern(value, self.pattern, ctx, site=blame)
        from sugar_lift_py_tests.operations import SequenceProjectionOperation

        if self.star_name is None:
            operation = SequenceProjectionOperation(
                target_names=self.prefix_names, owner=owner, blame=blame
            )
        else:
            operation = SequenceProjectionOperation(
                target_names=(*self.prefix_names, *self.suffix_names),
                owner=owner,
                blame=blame,
                star_name=self.star_name,
                prefix_names=self.prefix_names,
                suffix_names=self.suffix_names,
            )
        return operation.submit(value, ctx)


@dataclass(frozen=True)
class YieldAssignStepV1:
    """``<targets> = yield v`` and ``<targets> = yield from xs``: a suspension
    whose resumed value is assigned to the statement's targets.

    ``yield_step`` suspends: a ``YieldStepV1`` yields ``v`` (recording any
    walrus bind the value carries, as every yield does); a ``YieldFromStepV1``
    delegates to the sub-iterator.  The assignment is the step it resumes at
    (``_ResumeAssignStepV1``).  After a yield it binds the value the resume
    sent (``send``'s argument; ``None`` on a plain ``next``) to every target
    the way an ordinary assignment of those targets binds its one evaluation:

    * ``y = ...``, ``y: T = ...`` and ``a = b = ...`` bind the value to each
      Name, in source order;
    * ``a, b = ...`` / ``a, *b = ...`` / ``(a, (b, c)) = ...`` (``unpack``)
      unpack the value through ``SequenceProjectionOperation`` and bind each
      member to its Name;
    * ``o.x = ...`` / ``d[k] = ...`` (``store``) store the value through the
      store the statement's own sugar is: ``store`` is that store with its
      value read through ``store_evaluation``, the statement's evaluation key
      (``KeyedStoreSugar`` for a keyed place), which the resume binds the
      value under first.

    ``targets`` is ``(name, evaluation)`` per bound Name: ``evaluation`` is the
    key the assignment's evaluation binds that Name under (``Assign
    .target_evaluations``; a projection of the statement's evaluation for an
    unpack), None only for a body that was never substituted, whose reads are
    name reads.  ``occurrence`` is the statement's fragment (the unpack's
    blame).

    After a delegation the value is the delegate's return value
    (``StopIteration.value``): the yield-from step completes with it as the
    value the frame resumes with (``ResumeBindingV1``), as a yield completes
    with the value a ``send`` brings.
    """

    yield_step: YieldStepV1 | YieldFromStepV1
    targets: tuple[tuple[str, str | None], ...]
    fragment_cid: str
    unpack: YieldAssignUnpackV1 | None = None
    occurrence: object = field(default=None, compare=False, repr=False)
    store: object = field(default=None, compare=False, repr=False)
    store_evaluation: str | None = None

    def resume_step(self) -> "_ResumeAssignStepV1":
        return _ResumeAssignStepV1(
            self.targets,
            self.fragment_cid,
            self.unpack,
            self.occurrence,
            store=self.store,
            store_evaluation=self.store_evaluation,
        )


@dataclass(frozen=True)
class _ResumeAssignStepV1:
    """Where a ``YieldAssignStepV1`` suspends: the assignment of the resumed
    value (the sent value after a yield; the delegation's return value after a
    ``yield from``)."""

    targets: tuple[tuple[str, str | None], ...]
    fragment_cid: str
    unpack: YieldAssignUnpackV1 | None = None
    occurrence: object = field(default=None, compare=False, repr=False)
    store: object = field(default=None, compare=False, repr=False)
    store_evaluation: str | None = None


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
class AttributeAssignStepV1:
    """Authenticated generator assignment to one source Attribute target."""

    receiver: ConstructedTermSugar
    attr: str
    value: ConstructedTermSugar
    fragment_cid: str
    target_cid: str
    occurrence: object = field(compare=False, repr=False)

    def __post_init__(self) -> None:
        _require_constructed_term(self.receiver, owner="AttributeAssignStepV1.receiver")
        _require_constructed_term(self.value, owner="AttributeAssignStepV1.value")
        try:
            observed_target_cid = self.occurrence.seal().cid
        except (AttributeError, TypeError) as exc:
            raise TypeError(
                "AttributeAssignStepV1 requires an authenticated target occurrence"
            ) from exc
        if observed_target_cid != self.target_cid:
            raise TypeError(
                "AttributeAssignStepV1 target occurrence does not match its "
                "authenticated target CID"
            )


@dataclass(frozen=True)
class AssertStepV1:
    """One authenticated source Assert executed by the generator machine."""

    assert_sugar: object
    assert_cid: str
    assert_coordinate: object
    occurrence: object = field(compare=False, repr=False)

    def __post_init__(self) -> None:
        from sugar_lift_py_tests.sugar.assert_sugar import AssertSugar

        if not isinstance(self.assert_sugar, AssertSugar):
            raise TypeError("AssertStepV1 requires AssertSugar")
        from sugar_lift_py_tests.context_manager_resolution import (
            SourceFragmentCoordinateV1,
        )

        try:
            span = self.occurrence.line_col_span
            observed_coordinate = SourceFragmentCoordinateV1(
                self.occurrence.source_cid,
                span.start_line,
                span.start_col,
                span.end_line,
                span.end_col,
            )
        except (AttributeError, TypeError) as exc:
            raise TypeError(
                "AssertStepV1 requires an authenticated occurrence"
            ) from exc
        if observed_coordinate != self.assert_coordinate:
            raise TypeError(
                "AssertStepV1 assert occurrence does not match its authenticated coordinate"
            )


@dataclass(frozen=True)
class ImportFromStepV1:
    """Authenticated source import-from statement with inert meaning."""

    import_sugar: object
    coordinate: object
    occurrence: object = field(compare=False, repr=False)

    def __post_init__(self) -> None:
        from sugar_lift_py_tests.context_manager_resolution import (
            SourceFragmentCoordinateV1,
        )
        from sugar_lift_py_tests.sugar.inert_sugar import InertSugar

        if not isinstance(self.import_sugar, InertSugar):
            raise TypeError("ImportFromStepV1 requires InertSugar")
        try:
            span = self.occurrence.line_col_span
            observed = SourceFragmentCoordinateV1(
                self.occurrence.source_cid,
                span.start_line,
                span.start_col,
                span.end_line,
                span.end_col,
            )
        except (AttributeError, TypeError) as exc:
            raise TypeError(
                "ImportFromStepV1 requires an authenticated import occurrence"
            ) from exc
        if observed != self.coordinate:
            raise TypeError(
                "ImportFromStepV1 import occurrence does not match its "
                "authenticated coordinate"
            )


@dataclass(frozen=True)
class ImportStepV1:
    """Authenticated source import statement with inert meaning."""

    import_sugar: object
    coordinate: object
    occurrence: object = field(compare=False, repr=False)

    def __post_init__(self) -> None:
        from sugar_lift_py_tests.context_manager_resolution import (
            SourceFragmentCoordinateV1,
        )
        from sugar_lift_py_tests.sugar.inert_sugar import InertSugar

        if not isinstance(self.import_sugar, InertSugar):
            raise TypeError("ImportStepV1 requires InertSugar")
        try:
            span = self.occurrence.line_col_span
            observed = SourceFragmentCoordinateV1(
                self.occurrence.source_cid,
                span.start_line,
                span.start_col,
                span.end_line,
                span.end_col,
            )
        except (AttributeError, TypeError) as exc:
            raise TypeError(
                "ImportStepV1 requires an authenticated import occurrence"
            ) from exc
        if observed != self.coordinate:
            raise TypeError(
                "ImportStepV1 import occurrence does not match its "
                "authenticated coordinate"
            )


@dataclass(frozen=True)
class WhileStepV1:
    """Authenticated generator while with a nameable body and no else."""

    guard: ConstructedTermSugar
    body_steps: tuple
    fragment_cid: str
    coordinate: object
    occurrence: object = field(compare=False, repr=False)

    def __post_init__(self) -> None:
        from sugar_lift_py_tests.context_manager_resolution import (
            SourceFragmentCoordinateV1,
        )

        _require_constructed_term(self.guard, owner="WhileStepV1.guard")
        try:
            span = self.occurrence.line_col_span
            observed = SourceFragmentCoordinateV1(
                self.occurrence.source_cid,
                span.start_line,
                span.start_col,
                span.end_line,
                span.end_col,
            )
        except (AttributeError, TypeError) as exc:
            raise TypeError(
                "WhileStepV1 requires an authenticated while occurrence"
            ) from exc
        if observed != self.coordinate:
            raise TypeError(
                "WhileStepV1 while occurrence does not match its "
                "authenticated coordinate"
            )


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

    Transition uses IteratorOperation / NextOperation and accepts only
    authenticated StopIteration at this occurrence; it does not invent
    iterator items.
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
    """A delegation in progress: the sub-iterator, or the delegate source
    generator's machine (``GeneratorConstructionV1``) the frame drives.
    ``started`` says the delegate has already suspended once here, so a
    resume of the frame resumes it (forwarding a ``send``)."""

    iterator: object = field(compare=False, repr=False)
    occurrence: object = field(compare=False, repr=False)
    occurrence_cid: str
    started: bool = False


@dataclass(frozen=True)
class YieldExceptStepV1:
    """``try: yield v`` with ``except`` arms and nothing else in the suite.

    ``contextlib`` throws a body exception in at the yield, so these arms are
    where a generator manager decides suppression. Admitted by the producer
    only when the try body is exactly that one yield, the arms own no
    suspension and bind no name the rest of the frame could read, and every
    arm type is an authenticated exception coordinate (the ``TrySugar``
    handler roster). Anything wider stays an honest ``OpaqueStepV1``.
    """

    yield_step: YieldStepV1
    handlers: tuple = field(compare=False, repr=False)
    fragment_cid: str
    site: object = field(compare=False, repr=False)


@dataclass(frozen=True)
class ExceptArmsStepV1:
    """Where a ``YieldExceptStepV1`` suspends: its arms, right after the yield.

    Resuming steps past it (the try body completed); a throw is routed through
    its arms with ``TrySugar``'s one matcher before anything after the try.
    """

    handlers: tuple = field(compare=False, repr=False)
    fragment_cid: str
    site: object = field(compare=False, repr=False)


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
    (``if c: yield 1``, ``if c: x = yield 1``). A branch holding a shape we
    cannot resume or perform -- ``x = (yield 1) + 1``, etc. -- keeps the
    whole `If` an `OpaqueStepV1` and loud. Naming a step we cannot perform is worse than an
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


@dataclass(frozen=True)
class NestedCitedOpaqueManagerStepV1:
    """Nested ``with`` over a cited-opaque manager, not a source-defined generator.

    Python's ``with`` law holds: enter is attempted; the body runs only if
    enter completed; exit runs over every outgoing body edge. The manager's
    own enter and exit stay open per-occurrence coordinates — the same law
    as ``WithOpaqueCitedManagerSugar``. This step does not invent that
    ``__enter__`` completed, and does not invent what it projected.
    """

    manager: ConstructedTermSugar
    contract_ref: object = field(compare=False, repr=False)
    body_steps: tuple
    fragment_cid: str
    occurrence_cid: str
    site: object = field(compare=False)
    as_name: str | None = None

    def __post_init__(self) -> None:
        _require_constructed_term(
            self.manager, owner="NestedCitedOpaqueManagerStepV1.manager"
        )
        from sugar_lift_py_tests.context_manager_resolution import (
            OpaqueCitedContextManagerRefV1,
            PartitionedOpaqueCitedContextManagerRefV1,
        )

        if type(self.contract_ref) not in (
            OpaqueCitedContextManagerRefV1,
            PartitionedOpaqueCitedContextManagerRefV1,
        ):
            raise ValueError(
                "NestedCitedOpaqueManagerStepV1 requires an authenticated "
                "OpaqueCitedContextManagerRefV1; a cited manager is never "
                "inferred from the absence of a contract"
            )


@dataclass(frozen=True)
class NestedCitedOpaqueExitStepV1:
    """Exit the cited-opaque manager entered by NestedCitedOpaqueManagerStepV1."""

    occurrence_cid: str
    contract_ref: object = field(compare=False, repr=False)
    manager_value: object = field(compare=False, repr=False)
    site: object = field(compare=False)


# Statements that may follow a halting statement inside a flattened nested
# with body and are skipped by that halt. Handler and other-manager exit steps
# are deliberately absent: a halt does not skip past them to a later exit.
_BODY_REMAINDER_STEPS = (
    YieldStepV1,
    YieldAssignStepV1,
    _ResumeAssignStepV1,
    YieldFromStepV1,
    TermStepV1,
    AssignStepV1,
    AttributeAssignStepV1,
    AssertStepV1,
    ImportStepV1,
    ImportFromStepV1,
    IfStepV1,
    ForStepV1,
    WhileStepV1,
    ReturnStepV1,
    RaiseStepV1,
    OpaqueStepV1,
)


GeneratorStepV1 = (
    YieldStepV1
    | YieldAssignStepV1
    | _ResumeAssignStepV1
    | YieldFromStepV1
    | ReturnStepV1
    | OpaqueStepV1
    | InertStepV1
    | AssignStepV1
    | AttributeAssignStepV1
    | AssertStepV1
    | ImportFromStepV1
    | ImportStepV1
    | WhileStepV1
    | FinallyStepV1
    | ForStepV1
    | RaiseStepV1
    | TermStepV1
    | _ForIteratorStepV1
    | _YieldFromIteratorStepV1
    | IfStepV1
    | NestedManagerStepV1
    | NestedManagerExitStepV1
    | NestedCitedOpaqueManagerStepV1
    | NestedCitedOpaqueExitStepV1
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
        payload = {
            "kind": "assign-binding",
            "name": value.name,
            "fragmentCid": value.fragment_cid,
            "value": _generator_value_testimony(value.value, owner=owner),
        }
        if value.evaluation is not None:
            payload["evaluation"] = value.evaluation
        return payload
    if isinstance(value, GeneratorWalrusBindingV1):
        return {
            "kind": "walrus-binding",
            "name": value.name,
            "evaluation": value.evaluation,
            "value": _generator_value_testimony(
                value.bind.assigned_value, owner=owner
            ),
        }
    if isinstance(value, GeneratorLoopBindingV1):
        payload = {
            "kind": "loop-binding",
            "coordinateCid": value.coordinate.cid,
            "value": _generator_value_testimony(value.value, owner=owner),
        }
        if value.demand_cid:
            payload["demandCid"] = value.demand_cid
        else:
            payload["fragmentCid"] = value.fragment_cid
        return payload
    if isinstance(value, NestedEnteredBindingV1):
        return {
            "kind": "nested-entered-binding",
            "occurrenceCid": value.occurrence_cid,
            "nestedProtocolConstructionCid": value.nested_protocol_construction_cid,
            "nestedEntryCid": value.nested_entry_cid,
        }
    if isinstance(value, NestedCitedOpaqueEnteredBindingV1):
        return {
            "kind": "nested-cited-opaque-entered-binding",
            "occurrenceCid": value.occurrence_cid,
            "targetName": getattr(value.contract_ref, "target_name", ""),
            "asName": value.as_name,
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


def _yield_assign_targets_testimony(targets) -> list:
    """Each bound Name of a yield assignment, with its evaluation key."""
    rows = []
    for name, evaluation in targets:
        row = {"name": name}
        if evaluation is not None:
            row["evaluation"] = evaluation
        rows.append(row)
    return rows


def _yield_assign_unpack_testimony(unpack) -> dict | None:
    """The unpacking a yield assignment's targets spell, or None."""
    if unpack is None:
        return None
    row = {
        "prefixNames": list(unpack.prefix_names),
        "starName": unpack.star_name,
        "suffixNames": list(unpack.suffix_names),
    }
    if unpack.pattern is not None:
        from sugar_lift_py_tests.sugar.nested_dynamic_unpack_assign_sugar import (
            pattern_desc,
        )

        row["pattern"] = pattern_desc(unpack.pattern)
    return row


def _generator_step_testimony(step: object, *, owner: str) -> dict:
    """Content-addressed testimony for one generator step."""
    if isinstance(step, YieldStepV1):
        return {
            "kind": "yield",
            "value": _generator_value_testimony(step.value, owner=owner),
        }
    if isinstance(step, YieldAssignStepV1):
        row = {
            "kind": "yield-assign",
            "fragmentCid": step.fragment_cid,
            "targets": _yield_assign_targets_testimony(step.targets),
            "unpack": _yield_assign_unpack_testimony(step.unpack),
            "yield": _generator_step_testimony(step.yield_step, owner=owner),
        }
        if step.store_evaluation is not None:
            row["storeEvaluation"] = step.store_evaluation
        return row
    if isinstance(step, _ResumeAssignStepV1):
        row = {
            "kind": "resume-assign",
            "fragmentCid": step.fragment_cid,
            "targets": _yield_assign_targets_testimony(step.targets),
            "unpack": _yield_assign_unpack_testimony(step.unpack),
        }
        if step.store_evaluation is not None:
            row["storeEvaluation"] = step.store_evaluation
        return row
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
    if isinstance(step, AttributeAssignStepV1):
        return {
            "kind": "attribute-assign",
            "attr": step.attr,
            "fragmentCid": step.fragment_cid,
            "targetCid": step.target_cid,
            "receiver": _generator_value_testimony(step.receiver, owner=owner),
            "value": _generator_value_testimony(step.value, owner=owner),
        }
    if isinstance(step, AssertStepV1):
        return {
            "kind": "assert",
            "assertCid": step.assert_cid,
            "assertCoordinate": step.assert_coordinate.wire(),
            "test": _generator_value_testimony(step.assert_sugar.test, owner=owner),
        }
    if isinstance(step, ImportFromStepV1):
        return {
            "kind": "import-from",
            "coordinate": step.coordinate.wire(),
        }
    if isinstance(step, ImportStepV1):
        return {
            "kind": "import",
            "coordinate": step.coordinate.wire(),
        }
    if isinstance(step, WhileStepV1):
        return {
            "kind": "while",
            "fragmentCid": step.fragment_cid,
            "coordinate": step.coordinate.wire(),
            "guard": _generator_value_testimony(step.guard, owner=owner),
            "bodySteps": [
                _generator_step_testimony(item, owner=owner) for item in step.body_steps
            ],
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
        from sugar_lift_py_tests.sugar.raise_sugar import RaiseSugar

        if not isinstance(step.raise_sugar, RaiseSugar):
            raise TypeError(
                f"{owner} requires RaiseSugar for RaiseStepV1, got "
                f"{type(step.raise_sugar).__name__}"
            )
        return {
            "kind": "raise",
            "fragmentCid": step.fragment_cid,
            "exception": _generator_value_testimony(
                step.raise_sugar.exception, owner=owner
            ),
            "cause": _generator_value_testimony(step.raise_sugar.cause, owner=owner),
            "inFlightSlot": step.raise_sugar.in_flight_slot,
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
    if isinstance(step, YieldExceptStepV1):
        return {
            "kind": "yield-except",
            "fragmentCid": step.fragment_cid,
            "yield": _generator_step_testimony(step.yield_step, owner=owner),
            "handlerCount": len(step.handlers),
        }
    if isinstance(step, ExceptArmsStepV1):
        return {"kind": "except-arms", "fragmentCid": step.fragment_cid}
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
        nested_cid = getattr(step.nested_protocol, "protocol_construction_cid", None)
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
    if isinstance(step, NestedCitedOpaqueManagerStepV1):
        return {
            "kind": "nested-cited-opaque-manager",
            "fragmentCid": step.fragment_cid,
            "occurrenceCid": step.occurrence_cid,
            "targetName": getattr(step.contract_ref, "target_name", ""),
            "asName": step.as_name,
            "manager": _generator_value_testimony(step.manager, owner=owner),
            "bodySteps": [
                _generator_step_testimony(item, owner=owner) for item in step.body_steps
            ],
        }
    if isinstance(step, NestedCitedOpaqueExitStepV1):
        return {
            "kind": "nested-cited-opaque-exit",
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
    """One name bound by an executed AssignStepV1 on the live machine.

    ``name`` is None for the value a yield assignment's store target stored
    (``o.x = yield v``): it binds no name, only the statement's evaluation
    key, which a later read of the keyed place reads (``KeyedStoreSugar``).
    """

    name: str | None
    value: object
    fragment_cid: str
    # The RHS occurrence (``assigned_value.assigned_key``) this binding is the
    # completed value of: a later step whose substituted sugar inlines that
    # RHS answers with this value instead of evaluating the call again.
    rhs_key: object = field(default=None, compare=False, repr=False)
    # The key the assignment's evaluation binds the value under, as any
    # assignment's sugar binds it (``Assign.target_evaluations``,
    # ``_bind_evaluations``): ``y = yield v`` binds the sent value here, so a
    # later read of ``y`` (an ``EvaluationRef`` to the key) reads it.
    evaluation: str | None = None


@dataclass(frozen=True)
class GeneratorWalrusBindingV1:
    """One walrus bind a step's value carried out of its step.

    ``yield (x := v)``, ``y = (x := v)`` and a bare ``(x := v)`` statement:
    the walrus completes inside the step's operand and its bind rides the
    value (``NamedExpressionValue``).  The step peels it
    (``peel_walrus_binds``, ``_recording_walrus_binds``) and records it
    here, in evaluation order among the frame's other writes; ``_guard_evaluation_context`` applies it with
    ``NamedExpressionValue.bind``, the one place a walrus writes the temporal,
    so a later step's read of ``x`` (an ``EvaluationRef`` to the walrus's key)
    resolves to ``v``.
    """

    bind: object

    @property
    def name(self) -> str:
        return self.bind.name

    @property
    def evaluation(self) -> str | None:
        return self.bind.evaluation


@dataclass(frozen=True)
class GeneratorLoopBindingV1:
    """One name bound by a ForStepV1 iteration.

    An unpack target carries the unpack operation's ``demand_cid``. A bare
    name target (projection path ``("target",)``) carries the for
    fragment, not an invented unpack demand. Exactly one of those
    authorities is present.
    """

    coordinate: object
    value: object = field(compare=False, repr=False)
    occurrence: object = field(compare=False, repr=False)
    demand_cid: str = ""
    fragment_cid: str = ""

    def __post_init__(self) -> None:
        if bool(self.demand_cid) == bool(self.fragment_cid):
            raise TypeError(
                "GeneratorLoopBindingV1 requires exactly one of "
                "demand_cid or fragment_cid"
            )


@dataclass(frozen=True)
class NestedCitedOpaqueEnteredBindingV1:
    """Cited-opaque manager entered while executing NestedCitedOpaqueManagerStepV1."""

    occurrence_cid: str
    as_name: str | None
    contract_ref: object = field(compare=False, repr=False)
    manager_value: object = field(compare=False, repr=False)
    site: object = field(compare=False)


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
    # The source-visible frame this instance was allocated from: the one
    # object that carries this generator's lexical owner, so a reader of the
    # machine (a factory returning it, say) can name its function without
    # re-resolving a spelling.  Not identity: frame_coordinate is.
    source_frame: object | None = field(default=None, compare=False, repr=False)

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
        source_frame: object | None = None,
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
        root_floor_bindings = tuple(
            item for item in formal_floor_bindings if item.coordinate is None
        )
        projected_floor_bindings = tuple(
            item for item in formal_floor_bindings if item.coordinate is not None
        )
        projected_cids = tuple(item.coordinate_cid for item in projected_floor_bindings)
        if len(projected_cids) != len(set(projected_cids)):
            raise FormalFloorBindingGap(
                "projected formal floor bindings must not duplicate a coordinate"
            )
        floor_cids = tuple(item.coordinate_cid for item in root_floor_bindings)
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
        sealed_coordinates = tuple(
            entry.coordinate
            for entry in binding_state
            if isinstance(entry, BindingEntryV1)
        )
        for binding in projected_floor_bindings:
            coordinate = binding.coordinate
            parents = tuple(
                root
                for root in sealed_coordinates
                if coordinate.scope_owner_cid == root.scope_owner_cid
                and coordinate.binding_site == root.binding_site
                and coordinate.projection_path[: len(root.projection_path)]
                == root.projection_path
            )
            suffix = (
                coordinate.projection_path[len(parents[0].projection_path) :]
                if len(parents) == 1
                else ()
            )
            if (
                len(parents) != 1
                or len(suffix) != 2
                # ``*args`` elements and ``**kwargs`` entries are the two
                # collected-formal projections ``bind_actuals`` seats.
                or suffix[0] not in ("variadic", "variadic-keyword")
                or not isinstance(suffix[1], int)
                or isinstance(suffix[1], bool)
                or coordinate != parents[0].project(*suffix)
            ):
                raise FormalFloorBindingGap(
                    "projected formal floor coordinate is foreign to sealed formal roster"
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
            source_frame=source_frame,
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
            self.steps[self.cursor], ExceptArmsStepV1
        ):
            return self._throw_into_except_arms(self.steps[self.cursor], effect)
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
            self.steps[self.cursor], NestedCitedOpaqueExitStepV1
        ):
            step = self.steps[self.cursor]
            incoming = ExitSet.halted(effect, state=replace(self, cursor=self.cursor + 1))
            return self._exit_nested_cited_opaque(
                step, requested="throw", incoming=incoming
            )
        if self.cursor < len(self.steps) and isinstance(
            self.steps[self.cursor], FinallyStepV1
        ):
            step = self.steps[self.cursor]
            return incoming.and_finally(lambda: self._reduce_finally(step))
        return incoming

    def close(self):
        if self.cursor < len(self.steps) and isinstance(
            self.steps[self.cursor], ExceptArmsStepV1
        ):
            # close() throws GeneratorExit at the yield. Step past the arms
            # only when every arm is a settled miss for it; an arm that may
            # catch GeneratorExit owes "generator ignored GeneratorExit" or a
            # second close law, which is not written.
            if not self._arms_decided_miss(
                self.steps[self.cursor], "GeneratorExit"
            ):
                return self._gap("close", "except arm may catch GeneratorExit")
            return replace(self, cursor=self.cursor + 1).close()
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
            self.steps[self.cursor], NestedCitedOpaqueExitStepV1
        ):
            return self._exit_nested_cited_opaque(
                self.steps[self.cursor], requested="close"
            )
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

    def _arms_decided_miss(self, step: "ExceptArmsStepV1", exception_name: str):
        from sugar_lift_py_tests.authenticated_exception_matching import (
            MatchDecided,
        )
        from sugar_lift_py_tests.effect import RaiseEffect
        from sugar_lift_py_tests.sugar.try_sugar import _effect_match_verdict

        probe = RaiseEffect.for_builtin(
            exception_name,
            occurrence=f"generator-close:{step.fragment_cid}",
            blame=step.fragment_cid,
        )
        for matcher, _body, _slot in step.handlers:
            verdict = _effect_match_verdict(
                probe, matcher, self._guard_evaluation_context(), site=step.site
            )
            if not (isinstance(verdict, MatchDecided) and verdict.value is False):
                return False
        return True

    def _throw_into_except_arms(self, step: "ExceptArmsStepV1", effect) -> ExitSet:
        """``gen.throw(e)`` at ``try: yield ... except ...``.

        The arms are ``TrySugar``'s: the one matcher decides, splits
        (``MatchRetained``, e.g. an undetermined exception), or misses. A halt
        out of the arms (unmatched, or raised by an arm) is thrown on at the
        step after the try, so an enclosing ``finally`` still runs. An arm that
        completes resumes the frame after the try; an arm that returns ends it.
        """
        from sugar_lift_py_tests.floor import ReturnValue
        from sugar_lift_py_tests.outcome.exit_set import (
            Completed,
            Halted,
            true_guard,
        )
        from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock
        from sugar_lift_py_tests.sugar.try_sugar import _route_one_halt
        from sugar_source_tree.panic import SugarNotWritten

        after_try = replace(
            self, cursor=self.cursor + 1, suspended_resume_coordinate=None
        )
        parts = _route_one_halt(
            Halted(true_guard(), effect, self),
            step.handlers,
            site=step.site,
            ctx=self._guard_evaluation_context(),
        )
        routed = []
        for part in parts:
            for face in part.exits:
                if isinstance(face, Halted):
                    onward = after_try.throw(face.effect)
                    routed.append(_guard_exits(onward, face))
                    continue
                block = face.value
                returned = (
                    tuple(
                        entry
                        for entry in getattr(block, "entries", ())
                        if isinstance(entry, ReturnValue)
                    )
                    if isinstance(block, _ReducedBlock)
                    else ()
                )
                if isinstance(block, _ReducedBlock) and block.can_fall_through:
                    resumed = after_try._transition("throw")
                    if isinstance(resumed, GeneratorTransitionGapV1):
                        raise SugarNotWritten(
                            owner="GeneratorConstructionV1.throw",
                            blame=step.site,
                            observed=resumed.observed,
                            requested=resumed.requested,
                            fix="construct the transition after the except arm",
                        )
                    resumed_es = (
                        resumed
                        if isinstance(resumed, ExitSet)
                        else ExitSet.completed(resumed)
                    )
                    routed.append(_guard_exits(resumed_es, face))
                    continue
                cleanup_ahead = any(
                    isinstance(
                        later,
                        (
                            FinallyStepV1,
                            NestedManagerExitStepV1,
                            NestedCitedOpaqueExitStepV1,
                        ),
                    )
                    for later in self.steps[self.cursor + 1 :]
                )
                if len(returned) == 1 and not cleanup_ahead:
                    routed.append(
                        _guard_exits(
                            ExitSet.completed(
                                GeneratorTerminationV1(
                                    returned[0].value, self.binding_state
                                )
                            ),
                            face,
                        )
                    )
                    continue
                raise SugarNotWritten(
                    owner="GeneratorConstructionV1.throw",
                    blame=step.site,
                    observed=(
                        "except arm leaves by return under a pending cleanup"
                        if cleanup_ahead
                        else f"except arm completed as {type(block).__name__}"
                    ),
                    requested="an arm that falls through, raises, or returns",
                    fix="construct the arm's exit or keep the throw loud",
                )
        if not routed:
            return ExitSet(())
        result = routed[0]
        for part in routed[1:]:
            result = result.union(part)
        return result.normalize()

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

            def transition_assign(resolved_value):
                from sugar_lift_py_tests.sugar.assigned_value import assigned_key

                # ``y = (x := v)``: the walrus wrote before the assignment
                # does.  Its bind is recorded first and ``y`` is bound to the
                # value the walrus presents.
                recorded, presented = self._recording_walrus_binds(resolved_value)
                binding = GeneratorAssignBindingV1(
                    step.name,
                    presented,
                    step.fragment_cid,
                    assigned_key(step.value),
                )
                machine = replace(
                    recorded,
                    cursor=self.cursor + 1,
                    binding_state=(*recorded.binding_state, binding),
                )
                return machine._transition(requested)

            def continue_assign(resolved_value):
                from sugar_lift_py_tests.caller_parameter_contract import (
                    NativeOperationExitCarrierV1,
                )
                from sugar_source_tree.panic import SugarNotWritten

                result = transition_assign(resolved_value)
                if isinstance(result, GeneratorTransitionGapV1):
                    raise SugarNotWritten(
                        owner="GeneratorConstructionV1.transition",
                        blame=step,
                        observed=result.observed,
                        requested=result.requested,
                        fix=(
                            "implement that next transition before deferred "
                            "normalization"
                        ),
                    )
                if isinstance(result, (ExitSet, NativeOperationExitCarrierV1)):
                    return result
                return ExitSet.completed(result)

            from sugar_lift_py_tests.caller_parameter_contract import (
                NativeOperationExitCarrierV1,
            )

            if _halts_with_a_raise(value):
                # The value raised: the step halts with the machine's state and
                # still runs any already-written cited exit (as the attribute
                # store, assert and term steps do for their halts).
                return self._fold_pending_cited_opaque_exits(
                    ExitSet(tuple(replace(h, state=self) for h in value.halts()))
                )
            if isinstance(value, (ExitSet, NativeOperationExitCarrierV1)):
                return value.and_then(continue_assign)
            return transition_assign(value)
        if isinstance(step, AttributeAssignStepV1):
            from sugar_lift_py_tests.sugar.store_effect_sugar import (
                AttributeStoreEffectSugar,
            )

            outcome = AttributeStoreEffectSugar(
                receiver=step.receiver,
                value=step.value,
                attr=step.attr,
                site=step.occurrence,
            ).desugar(self._guard_evaluation_context())
            if not isinstance(outcome, ExitSet):
                return self._gap(
                    requested, f"attribute store returned {type(outcome).__name__}"
                )
            if outcome.completed_value() is None or outcome.owed_items():
                # A halt, or an undecided receiver's store answering its two
                # faces (``store_faces``): the halted face leaves the machine
                # here, the completed face resumes past the store (#7827
                # item 4).
                return self._transition_term_exitset(step, outcome, requested)
            machine = replace(self, cursor=self.cursor + 1)
            return machine._transition(requested)
        if isinstance(step, AssertStepV1):
            outcome = step.assert_sugar.desugar(self._guard_evaluation_context())
            if not isinstance(outcome, ExitSet):
                return self._gap(requested, f"assert returned {type(outcome).__name__}")
            if outcome.exits and outcome.halts() == outcome.exits:
                return self._fold_pending_cited_opaque_exits(
                    ExitSet(tuple(replace(h, state=self) for h in outcome.halts()))
                )
            if outcome.completed_value() is None or outcome.owed_items():
                return self._gap(requested, f"assert returned {type(outcome).__name__}")
            machine = replace(self, cursor=self.cursor + 1)
            return machine._transition(requested)
        if isinstance(step, ImportFromStepV1):
            outcome = step.import_sugar.desugar(self._guard_evaluation_context())
            if (
                not isinstance(outcome, ExitSet)
                or outcome.completed_value() is None
                or outcome.owed_items()
            ):
                return self._gap(
                    requested, f"import-from returned {type(outcome).__name__}"
                )
            machine = replace(self, cursor=self.cursor + 1)
            return machine._transition(requested)
        if isinstance(step, ImportStepV1):
            outcome = step.import_sugar.desugar(self._guard_evaluation_context())
            if (
                not isinstance(outcome, ExitSet)
                or outcome.completed_value() is None
                or outcome.owed_items()
            ):
                return self._gap(requested, f"import returned {type(outcome).__name__}")
            machine = replace(self, cursor=self.cursor + 1)
            return machine._transition(requested)
        if isinstance(step, WhileStepV1):
            guard_outcome = self._guard_truth(step.guard)
            if not isinstance(guard_outcome, ExitSet):
                return self._gap(requested, "While guard is not ground")
            if guard_outcome.exits and guard_outcome.halts() == guard_outcome.exits:
                return self._fold_pending_cited_opaque_exits(
                    ExitSet(
                        tuple(replace(h, state=self) for h in guard_outcome.halts())
                    )
                )
            if guard_outcome.completed_value() is None or guard_outcome.owed_items():
                return self._gap(requested, "While guard is not ground")
            decided = self._decide_guard(guard_outcome.completed_value())
            if decided is False:
                machine = replace(self, cursor=self.cursor + 1)
                return machine._transition(requested)
            if decided is True:
                return self._spliced((*step.body_steps, step))._transition(requested)
            return self._gap(requested, "While guard is not ground")
        if isinstance(step, RaiseStepV1):
            outcome = step.raise_sugar.desugar(self._guard_evaluation_context())
            if (
                isinstance(outcome, ExitSet)
                and outcome.exits
                and outcome.halts() == outcome.exits
            ):
                return self._fold_pending_cited_opaque_exits(
                    ExitSet(tuple(replace(h, state=self) for h in outcome.halts()))
                )
            return self._gap(
                requested, f"raise did not halt ({type(outcome).__name__})"
            )
        if isinstance(step, TermStepV1):
            from sugar_source_tree.panic import SugarNotWritten

            # A ConstructionPanic from the term is its own named refusal: it
            # propagates with its owner, requested, and observed intact. It is
            # never rewritten into a transition gap.
            try:
                outcome = step.term.desugar(self._guard_evaluation_context())
            except SugarNotWritten as exc:
                return self._gap(requested, str(exc.observed))
            if not isinstance(outcome, ExitSet):
                return self._gap(requested, type(outcome).__name__)
            if outcome.completed_value() is None or outcome.owed_items():
                # A halt leaves the machine here (with any written cited
                # exit folded over it); a two-faced value splits it.
                return self._transition_term_exitset(step, outcome, requested)
            # The value is discarded; a walrus it carries (``(x := v)``) wrote.
            recorded, _presented = self._recording_walrus_binds(
                outcome.completed_value()
            )
            machine = replace(recorded, cursor=self.cursor + 1)
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
        if isinstance(step, NestedCitedOpaqueManagerStepV1):
            return self._transition_nested_cited_opaque(step, requested)
        if isinstance(step, NestedCitedOpaqueExitStepV1):
            return self._exit_nested_cited_opaque(step, requested=requested)
        if isinstance(step, FinallyStepV1):
            # Structured cleanup_steps already reduce through a sub-machine in
            # _reduce_finally; do not leave a gap that hides that composition.
            cleanup = self._reduce_finally(step)
            from sugar_lift_py_tests.outcome import Completed, Halted

            if any(isinstance(exit_, Halted) for exit_ in cleanup.exits):
                return self._continue_after_two_faced_cleanup(cleanup, requested)
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
        if isinstance(step, ExceptArmsStepV1):
            # The try body (one yield) completed: no arm runs.
            machine = replace(self, cursor=self.cursor + 1)
            return machine._transition(requested)
        if isinstance(step, YieldExceptStepV1):
            # The yielded value is evaluated INSIDE the try. A value whose
            # evaluation may halt would need its halt routed through the arms;
            # that routing is not written, so it stays loud rather than escape.
            value = self._reduce_value(step.yield_step.value, requested)
            if isinstance(value, GeneratorTransitionGapV1):
                return value
            from sugar_lift_py_tests.caller_parameter_contract import (
                NativeOperationExitCarrierV1,
            )
            if isinstance(value, (ExitSet, NativeOperationExitCarrierV1)):
                return self._gap(
                    requested, "yield value inside try/except may raise"
                )
            arms = ExceptArmsStepV1(step.handlers, step.fragment_cid, step.site)
            return self._spliced((step.yield_step, arms))._transition(requested)
        if isinstance(step, YieldAssignStepV1):
            # ``<targets> = yield v`` / ``= yield from xs``: the suspension
            # happens here; the assignment of the resumed value is the step
            # it resumes at.
            return self._spliced(
                (step.yield_step, step.resume_step())
            )._transition(requested)
        if isinstance(step, _ResumeAssignStepV1):
            return self._transition_resume_assign(step, requested)
        if isinstance(step, IfStepV1):
            return self._transition_branch(step, requested)
        if isinstance(step, ReturnStepV1):
            value = self._reduce_value(step.value, requested)
            if isinstance(value, GeneratorTransitionGapV1):
                return value

            def transition_return(resolved_value):
                return self._fold_pending_cited_opaque_exits(
                    GeneratorTerminationV1(resolved_value, self.binding_state)
                )

            def continue_return(resolved_value):
                from sugar_source_tree.panic import SugarNotWritten

                result = transition_return(resolved_value)
                if isinstance(result, GeneratorTransitionGapV1):
                    raise SugarNotWritten(
                        owner="GeneratorConstructionV1.transition",
                        blame=step,
                        observed=result.observed,
                        requested=result.requested,
                        fix=(
                            "implement that next transition before deferred "
                            "normalization"
                        ),
                    )
                if isinstance(result, ExitSet):
                    return result
                return ExitSet.completed(result)

            from sugar_lift_py_tests.caller_parameter_contract import (
                NativeOperationExitCarrierV1,
            )

            if _halts_with_a_raise(value):
                # The value raised: the step halts with the machine's state and
                # still runs any already-written cited exit (as the attribute
                # store, assert and term steps do for their halts).
                return self._fold_pending_cited_opaque_exits(
                    ExitSet(tuple(replace(h, state=self) for h in value.halts()))
                )
            if isinstance(value, (ExitSet, NativeOperationExitCarrierV1)):
                return value.and_then(continue_return)
            return transition_return(value)
        value = self._reduce_value(step.value, requested)
        if isinstance(value, GeneratorTransitionGapV1):
            return value
        resume_coordinate = f"{self.instance_coordinate}:resume:{self.cursor + 1}"
        machine = replace(
            self,
            cursor=self.cursor + 1,
            suspended_resume_coordinate=resume_coordinate,
        )

        def transition_yield(resolved_value):
            # The yielded value is an operand: a walrus in it (``yield (x :=
            # v)``) ran before the suspension.  Its binds come off the value
            # (the one operand door's peel), the yield hands out the value
            # they present, and the suspended frame records them, so a step
            # after the resume reads ``x`` from its own state.  Each arm of a
            # split value carries only its own binds.
            bound, presented = machine._recording_walrus_binds(resolved_value)
            return YieldEffect(presented, resume_coordinate, bound)

        def continue_yield(resolved_value):
            from sugar_source_tree.panic import SugarNotWritten

            result = transition_yield(resolved_value)
            if isinstance(result, GeneratorTransitionGapV1):
                raise SugarNotWritten(
                    owner="GeneratorConstructionV1.transition",
                    blame=step,
                    observed=result.observed,
                    requested=result.requested,
                    fix=(
                        "implement that next transition before deferred "
                        "normalization"
                    ),
                )
            if isinstance(result, ExitSet):
                return result
            return ExitSet.completed(result)

        from sugar_lift_py_tests.caller_parameter_contract import (
            NativeOperationExitCarrierV1,
        )

        if _halts_with_a_raise(value):
            # The value raised: the step halts with the machine's state and
            # still runs any already-written cited exit (as the attribute
            # store, assert and term steps do for their halts).
            return self._fold_pending_cited_opaque_exits(
                ExitSet(tuple(replace(h, state=self) for h in value.halts()))
            )
        if isinstance(value, (ExitSet, NativeOperationExitCarrierV1)):
            return value.and_then(continue_yield)
        return transition_yield(value)

    def _transition_for(self, step: ForStepV1, requested: str):
        from sugar_lift_py_tests.operations import IteratorOperation

        iterable = step.iterable.desugar(self._guard_evaluation_context())
        if not isinstance(iterable, ExitSet):
            return self._gap(requested, type(iterable).__name__)
        if iterable.exits and iterable.halts() == iterable.exits:
            return self._fold_pending_cited_opaque_exits(
                ExitSet(tuple(replace(h, state=self) for h in iterable.halts()))
            )
        if iterable.completed_value() is None or iterable.owed_items():
            return self._gap(requested, type(iterable).__name__)
        iterator = IteratorOperation(
            owner="GeneratorConstructionV1.ForStepV1.iter",
            blame=step.occurrence,
        ).submit(iterable.completed_value(), self._guard_evaluation_context())
        if not isinstance(iterator, ExitSet):
            return self._gap(requested, type(iterator).__name__)
        if iterator.exits and iterator.halts() == iterator.exits:
            return self._fold_pending_cited_opaque_exits(
                ExitSet(tuple(replace(h, state=self) for h in iterator.halts()))
            )
        if iterator.completed_value() is None or iterator.owed_items():
            return self._gap(requested, type(iterator).__name__)
        runtime = _ForIteratorStepV1(
            iterator.completed_value(),
            step.target_coordinates,
            step.body_steps,
            step.module_cid,
            step.fragment_cid,
            step.occurrence,
        )
        machine = replace(
            self,
            steps=(*self.steps[: self.cursor], runtime, *self.steps[self.cursor + 1 :]),
        )
        return machine._transition(requested)

    def _transition_resume_assign(self, step: _ResumeAssignStepV1, requested: str):
        """Bind the resumed value to a yield assignment's targets.

        After a yield the value is the one the resume sent
        (``_sent_value``).  Each Name of a plain or chained target binds it;
        an unpacking target asks the value what it unpacks to, as an ordinary
        ``a, b = e`` asks its one evaluation (``YieldAssignUnpackV1``; level by
        level for a nested tree): a halted unpack (too few members, runtime
        cardinality) halts here and binds nothing.  Each bound Name is keyed
        like any assignment of it (``GeneratorAssignBindingV1.evaluation``).

        A store target (``o.x = yield v``, ``d[k] = yield v``) binds the value
        under the statement's evaluation key and runs the statement's store,
        which reads it there (``YieldAssignStepV1.store``): a keyed place's
        later read reads that key; the store's halt halts here.

        After a ``yield from`` the value is the delegate's return value, which
        the yield-from step completed with as the frame's resume value
        (``_delegation_returned``); ``_sent_value`` reads both the same way.
        """
        from sugar_lift_py_tests.floor.scope_rebind import ScopeRebinds
        from sugar_source_tree.panic import SugarNotWritten

        names = ", ".join(name for name, _evaluation in step.targets)
        sent = self._sent_value(requested)
        if isinstance(sent, GeneratorTransitionGapV1):
            return sent
        if step.store is not None:
            stored = GeneratorAssignBindingV1(
                None, sent, step.fragment_cid, evaluation=step.store_evaluation
            )
            bound = replace(self, binding_state=(*self.binding_state, stored))
            try:
                outcome = step.store.desugar(bound._guard_evaluation_context())
            except SugarNotWritten as exc:
                return self._gap(requested, str(exc.observed))
            if not isinstance(outcome, ExitSet):
                return self._gap(
                    requested,
                    f"store = yield: store returned {type(outcome).__name__}",
                )
            if outcome.completed_value() is None or outcome.owed_items():
                # A halt, or an undecided receiver's two store faces: the
                # halted face leaves the machine here, the completed face
                # resumes past the statement.
                return bound._transition_term_exitset(step, outcome, requested)
            return replace(bound, cursor=self.cursor + 1)._transition(requested)
        if step.unpack is None:
            members = tuple((name, sent) for name, _evaluation in step.targets)
        else:
            unpacked = step.unpack.project(
                sent,
                self._guard_evaluation_context(),
                owner="GeneratorConstructionV1.YieldAssignStepV1.unpack",
                blame=step.occurrence,
            )
            if not isinstance(unpacked, ExitSet):
                return self._gap(
                    requested,
                    f"{names} = yield: unpack returned {type(unpacked).__name__}",
                )
            if unpacked.exits and unpacked.halts() == unpacked.exits:
                return self._fold_pending_cited_opaque_exits(
                    ExitSet(tuple(replace(h, state=self) for h in unpacked.halts()))
                )
            if (
                unpacked.completed_value() is None
                or unpacked.owed_items()
                or not isinstance(unpacked.completed_value(), ScopeRebinds)
            ):
                return self._gap(
                    requested,
                    f"{names} = yield: unpack returned {type(unpacked).__name__}",
                )
            members = unpacked.completed_value().bindings
        keys = dict(step.targets)
        bindings = tuple(
            GeneratorAssignBindingV1(
                name, value, step.fragment_cid, evaluation=keys.get(name)
            )
            for name, value in members
        )
        machine = replace(
            self,
            cursor=self.cursor + 1,
            binding_state=(*self.binding_state, *bindings),
        )
        return machine._transition(requested)

    def _transition_yield_from(self, step: YieldFromStepV1, requested: str):
        from sugar_lift_py_tests.operations import IteratorOperation

        iterable = step.iterable.desugar(self._guard_evaluation_context())
        if not isinstance(iterable, ExitSet):
            return self._gap(requested, type(iterable).__name__)
        if iterable.exits and iterable.halts() == iterable.exits:
            return self._fold_pending_cited_opaque_exits(
                ExitSet(tuple(replace(h, state=self) for h in iterable.halts()))
            )
        if iterable.completed_value() is None or iterable.owed_items():
            return self._gap(requested, type(iterable).__name__)
        if isinstance(iterable.completed_value(), GeneratorConstructionV1):
            # ``yield from g()`` over a source generator: ``iter(g)`` is ``g``
            # itself, and the frame drives the delegate's machine, so its
            # ``return r`` is the value the delegation completes with.
            runtime = _YieldFromIteratorStepV1(
                iterable.completed_value(), step.occurrence, step.occurrence_cid
            )
            return self._spliced((runtime,))._transition(requested)
        iterator = IteratorOperation(
            owner="GeneratorConstructionV1.YieldFromStepV1.iter",
            blame=step.occurrence,
        ).submit(iterable.completed_value(), self._guard_evaluation_context())
        if not isinstance(iterator, ExitSet):
            return self._gap(requested, type(iterator).__name__)
        if iterator.exits and iterator.halts() == iterator.exits:
            return self._fold_pending_cited_opaque_exits(
                ExitSet(tuple(replace(h, state=self) for h in iterator.halts()))
            )
        if iterator.completed_value() is None or iterator.owed_items():
            return self._gap(requested, type(iterator).__name__)
        runtime = _YieldFromIteratorStepV1(
            iterator.completed_value(), step.occurrence, step.occurrence_cid
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
        from sugar_lift_py_tests.floor.iterator_value import (
            ListIteratorValue,
            NextResult,
            TupleIteratorValue,
        )
        from sugar_lift_py_tests.operations import NextOperation

        if isinstance(step.iterator, GeneratorConstructionV1):
            return self._transition_yield_from_generator(step, requested)
        outcome = NextOperation(
            owner="GeneratorConstructionV1.YieldFromStepV1.next",
            blame=step.occurrence,
        ).submit(step.iterator, self._guard_evaluation_context())
        if not isinstance(outcome, ExitSet):
            return self._gap(requested, f"next_with returned {type(outcome).__name__}")
        if outcome.exits and outcome.halts() == outcome.exits:
            halts = outcome.halts()
            effect = halts[0].effect
            stop_identity = ground_raise_effect(
                exception_name="StopIteration",
                site=step.occurrence,
                owner="GeneratorConstructionV1.YieldFromStepV1.next",
            ).exception_type_coordinate
            if (
                len(halts) == 1
                and isinstance(effect, RaiseEffect)
                and effect.exception_type_coordinate == stop_identity
                and effect.occurrence_id == str(step.occurrence)
            ):
                # The sub-iterator is exhausted: the delegation completes with
                # its ``StopIteration.value``.  A list's or tuple's iterator
                # returns None; any other iterator's return is not known
                # here, so the value is named, undecided: the delegate's
                # ``StopIteration.value`` coordinate.
                if isinstance(step.iterator, (ListIteratorValue, TupleIteratorValue)):
                    from sugar_lift_py_tests.floor.none_value import NoneValue

                    returned = NoneValue()
                else:
                    from sugar_lift_py_tests.floor.opaque_op_callsite import (
                        OpaqueOpCallsite,
                    )

                    returned = OpaqueOpCallsite(
                        callee="StopIteration.value", arg=step.iterator
                    )
                return self._delegation_returned(returned, requested)
            return ExitSet(tuple(replace(h, state=self) for h in halts))
        if outcome.owed_items() or not isinstance(
            outcome.completed_value(), NextResult
        ):
            return self._gap(requested, f"next_with returned {type(outcome).__name__}")
        next_result = outcome.completed_value()

        runtime = replace(step, iterator=next_result.advanced)
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
        return YieldEffect(next_result.value, resume_coordinate, machine)

    def _transition_yield_from_generator(
        self, step: _YieldFromIteratorStepV1, requested: str
    ):
        """``yield from g()`` over a source generator: drive its machine.

        The first entry resumes the delegate (``next``).  After the delegate
        suspended here, a plain resume of this frame resumes it, and a
        ``send(v)`` of this frame (``ResumeBindingV1`` at this delegation's
        resume coordinate) is sent into it, as Python forwards it.  Each yield
        of the delegate is this frame's yield; its halt is this frame's halt;
        its ``return r`` is the value the delegation completes with
        (``_delegation_returned``), None when it returns nothing.
        """
        from sugar_lift_py_tests.floor.none_value import NoneValue

        delegate = step.iterator
        resume_coordinate = f"{self.instance_coordinate}:resume:{self.cursor + 1}"
        last = self.binding_state[-1] if self.binding_state else None
        if (
            step.started
            and self.suspended_resume_coordinate is None
            and isinstance(last, ResumeBindingV1)
            and last.resume_coordinate == resume_coordinate
            and last.resume_value is not None
        ):
            outcome = delegate.send(last.resume_value)
        else:
            outcome = delegate.resume()
        if isinstance(outcome, ExitSet):
            if outcome.exits and outcome.halts() == outcome.exits:
                return self._fold_pending_cited_opaque_exits(
                    ExitSet(tuple(replace(h, state=self) for h in outcome.halts()))
                )
            if outcome.completed_value() is None or outcome.owed_items():
                return self._gap(
                    requested,
                    "yield from: the delegate generator's transition is two-faced",
                )
            outcome = outcome.completed_value()
        if isinstance(outcome, GeneratorTransitionGapV1):
            return outcome
        if isinstance(outcome, YieldEffect):
            runtime = replace(step, iterator=outcome.machine, started=True)
            machine = replace(
                self._spliced((runtime,)),
                suspended_resume_coordinate=resume_coordinate,
            )
            return YieldEffect(outcome.value, resume_coordinate, machine)
        if isinstance(outcome, GeneratorTerminationV1):
            returned = outcome.return_value
            return self._delegation_returned(
                NoneValue() if returned is None else returned, requested
            )
        return self._gap(
            requested,
            "yield from: the delegate generator transitioned to "
            f"{type(outcome).__name__}",
        )

    def _delegation_returned(self, returned: object, requested: str):
        """A ``yield from`` whose delegate is exhausted completes with
        ``returned`` (``StopIteration.value``): the value of the ``yield
        from`` expression.  It is the value this frame resumes with past the
        delegation, recorded as a resume records a sent value
        (``ResumeBindingV1`` at the delegation's resume coordinate, the frame
        no longer suspended), so ``x = yield from xs`` binds it through the
        one resume read (``_sent_value``); a bare ``yield from`` discards
        it."""
        coordinate = f"{self.instance_coordinate}:resume:{self.cursor + 1}"
        machine = replace(
            self,
            cursor=self.cursor + 1,
            suspended_resume_coordinate=None,
            binding_state=(
                *self.binding_state,
                ResumeBindingV1(coordinate, returned),
            ),
        )
        return machine._transition(requested)

    def _transition_for_iterator(self, step: _ForIteratorStepV1, requested: str):
        from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
        from sugar_lift_py_tests.floor.ground_exit import ground_raise_effect
        from sugar_lift_py_tests.floor.iterator_value import NextResult
        from sugar_lift_py_tests.operations import NextOperation
        from sugar_lift_py_tests.operations.positional_unpack_operation import (
            PositionalUnpackOperation,
            UnpackMemberRoster,
        )
        outcome = NextOperation(
            owner="GeneratorConstructionV1.ForStepV1.next",
            blame=step.occurrence,
        ).submit(step.iterator, self._guard_evaluation_context())
        if not isinstance(outcome, ExitSet):
            return self._gap(requested, f"next_with returned {type(outcome).__name__}")
        if outcome.exits and outcome.halts() == outcome.exits:
            halts = outcome.halts()
            effect = halts[0].effect
            stop_identity = ground_raise_effect(
                exception_name="StopIteration",
                site=step.occurrence,
                owner="GeneratorConstructionV1.ForStepV1.next",
            ).exception_type_coordinate
            if (
                len(halts) == 1
                and isinstance(effect, RaiseEffect)
                and effect.exception_type_coordinate == stop_identity
                and effect.occurrence_id == str(step.occurrence)
            ):
                machine = replace(self, cursor=self.cursor + 1)
                return machine._transition(requested)
            return ExitSet(tuple(replace(h, state=self) for h in halts))
        if outcome.owed_items() or not isinstance(
            outcome.completed_value(), NextResult
        ):
            return self._gap(requested, f"next_with returned {type(outcome).__name__}")
        next_result = outcome.completed_value()

        if (
            len(step.target_coordinates) == 1
            and tuple(step.target_coordinates[0].projection_path) == ("target",)
        ):
            # Bare name: bind the iterated item, as LoopRecurrence already does.
            # A 1-tuple target is ``("target", 0)`` and still unpacks.
            bindings = (
                GeneratorLoopBindingV1(
                    step.target_coordinates[0],
                    next_result.value,
                    step.occurrence,
                    fragment_cid=step.fragment_cid,
                ),
            )
        else:
            unpack = PositionalUnpackOperation(
                fixed_prefix=len(step.target_coordinates),
                fixed_suffix=0,
                has_star=False,
                owner="GeneratorConstructionV1.ForStepV1.target",
                blame=step.occurrence,
            ).submit(next_result.value, self._guard_evaluation_context())
            if not isinstance(unpack, ExitSet):
                return self._gap(
                    requested, f"target unpack returned {type(unpack).__name__}"
                )
            if unpack.exits and unpack.halts() == unpack.exits:
                return ExitSet(tuple(replace(h, state=self) for h in unpack.halts()))
            if unpack.owed_items() or not isinstance(
                unpack.completed_value(), UnpackMemberRoster
            ):
                return self._gap(
                    requested, f"target unpack returned {type(unpack).__name__}"
                )
            roster = unpack.completed_value()
            bindings = tuple(
                GeneratorLoopBindingV1(
                    coordinate, member, roster.occurrence, roster.demand_cid
                )
                for coordinate, member in zip(
                    step.target_coordinates, roster.members, strict=True
                )
            )
        recurrence = replace(step, iterator=next_result.advanced)
        steps = (
            *self.steps[: self.cursor],
            *step.body_steps,
            recurrence,
            *self.steps[self.cursor + 1 :],
        )
        machine = replace(
            self, steps=steps, binding_state=(*self.binding_state, *bindings)
        )
        return machine._transition(requested)

    def _transition_nested_manager(self, step: NestedManagerStepV1, requested: str):
        """Enter nested protocol, bind entered state, splice body + exit step."""
        enter = getattr(step.nested_protocol, "enter_resource_outcome", None)
        if not callable(enter):
            return self._gap(requested, "nested manager without enter_resource_outcome")
        outcome = enter()
        if (
            isinstance(outcome, ExitSet)
            and outcome.exits
            and outcome.halts() == outcome.exits
        ):
            return outcome
        if (
            not isinstance(outcome, ExitSet)
            or outcome.completed_value() is None
            or outcome.owed_items()
        ):
            return self._gap(
                requested, f"nested enter observed {type(outcome).__name__}"
            )
        nested_entered = outcome.completed_value()
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

    def _transition_nested_cited_opaque(
        self, step: NestedCitedOpaqueManagerStepV1, requested: str
    ):
        """Enter a cited-opaque nested with: both enter faces stay open."""
        from sugar_lift_py_tests.caller_parameter_contract import (
            NativeOperationExitCarrierV1,
        )
        from sugar_lift_py_tests.sugar.with_opaque_cited_manager_sugar import (
            WithOpaqueCitedManagerSugar,
        )
        from sugar_source_tree.panic import SugarNotWritten

        manager_value = self._reduce_value(step.manager, requested)
        if isinstance(manager_value, GeneratorTransitionGapV1):
            return manager_value

        def continue_with_manager(resolved_manager):
            law = WithOpaqueCitedManagerSugar(
                manager=step.manager,
                body=(),
                contract_ref=step.contract_ref,
                site=step.site,
            )
            enter_es = law._enter_exitset(resolved_manager)

            def continue_enter(enter_value):
                binding = NestedCitedOpaqueEnteredBindingV1(
                    occurrence_cid=step.occurrence_cid,
                    as_name=step.as_name,
                    contract_ref=step.contract_ref,
                    manager_value=resolved_manager,
                    site=step.site,
                )
                bindings = [binding]
                if step.as_name is not None:
                    bindings.append(
                        GeneratorAssignBindingV1(
                            step.as_name, enter_value, step.fragment_cid
                        )
                    )
                steps = (
                    *self.steps[: self.cursor],
                    *step.body_steps,
                    NestedCitedOpaqueExitStepV1(
                        occurrence_cid=step.occurrence_cid,
                        contract_ref=step.contract_ref,
                        manager_value=resolved_manager,
                        site=step.site,
                    ),
                    *self.steps[self.cursor + 1 :],
                )
                machine = replace(
                    self,
                    steps=steps,
                    binding_state=(*self.binding_state, *bindings),
                )
                result = machine._transition(requested)
                if isinstance(result, GeneratorTransitionGapV1):
                    raise SugarNotWritten(
                        owner="GeneratorConstructionV1.transition",
                        blame=step,
                        observed=result.observed,
                        requested=result.requested,
                        fix=(
                            "implement that next transition before deferred "
                            "normalization"
                        ),
                    )
                if isinstance(result, (ExitSet, NativeOperationExitCarrierV1)):
                    return result
                return ExitSet.completed(result)

            return enter_es.and_then(continue_enter)

        if isinstance(manager_value, (ExitSet, NativeOperationExitCarrierV1)):
            return manager_value.and_then(continue_with_manager)
        return continue_with_manager(manager_value)

    def _exit_nested_cited_opaque(
        self,
        step: NestedCitedOpaqueExitStepV1,
        *,
        requested: str,
        incoming: ExitSet | None = None,
    ):
        """Apply open cited-opaque exit over the continuation or a thrown effect."""
        from sugar_lift_py_tests.sugar.with_opaque_cited_manager_sugar import (
            WithOpaqueCitedManagerSugar,
        )
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        law = WithOpaqueCitedManagerSugar(
            manager=TrueBoolLiteralSugar(site=step.site),
            body=(),
            contract_ref=step.contract_ref,
            site=step.site,
        )
        exit_es = law._exit_exitset(step.manager_value)
        if incoming is not None:
            return incoming.and_exit_truthiness(exit_es, site=step.site)
        # The body reached the end of this ``with``: its exit runs on that
        # completion NOW, and only a completed exit continues to the steps
        # after it. Applying this exit over the continuation instead would
        # wrap every later step -- an enclosing ``with``'s exit, a later
        # raise -- inside this one, letting it "suppress" what runs after it.
        from sugar_lift_py_tests.outcome.exit_set import Completed

        advanced = replace(self, cursor=self.cursor + 1)
        exited = ExitSet.completed(advanced).and_exit_truthiness(
            exit_es, site=step.site
        )
        parts = []
        for face in exited.exits:
            if not isinstance(face, Completed):
                parts.append(ExitSet((face,)))
                continue
            if requested == "close":
                continued = face.value.close()
            else:
                continued = face.value._transition(requested)
            if isinstance(continued, GeneratorTransitionGapV1):
                return continued
            if not isinstance(continued, ExitSet):
                continued = ExitSet.completed(continued)
            parts.append(_guard_exits(continued, face))
        result = parts[0]
        for part in parts[1:]:
            result = result.union(part)
        return result.normalize()


    def _transition_term_exitset(self, step, outcome, requested: str):
        """An expression statement whose value is two-faced (may complete or raise).

        A halted face leaves the machine HERE: its pre-halt state is this
        machine, and an already-written cited-opaque exit folds over it. A
        completed face discards the value and the machine advances past the
        statement under that face's guard. Returning the call's own ExitSet
        would hand its value (a call result) to the consumer as if it were the
        machine's next transition.
        """
        from sugar_lift_py_tests.caller_parameter_contract import (
            NativeOperationExitCarrierV1,
        )
        from sugar_lift_py_tests.outcome.exit_set import Halted
        from sugar_source_tree.panic import SugarNotWritten

        completed = tuple(face for face in outcome.exits if not isinstance(face, Halted))
        parts = []
        if outcome.halts():
            parts.append(
                self._fold_pending_cited_opaque_exits(
                    ExitSet(tuple(replace(h, state=self) for h in outcome.halts()))
                )
            )
        if completed:
            machine = replace(self, cursor=self.cursor + 1)

            def continue_term(value):
                # Each completed arm records only the walrus binds it carries.
                recorded, _presented = machine._recording_walrus_binds(value)
                result = recorded._transition(requested)
                if isinstance(result, GeneratorTransitionGapV1):
                    raise SugarNotWritten(
                        owner="GeneratorConstructionV1.transition",
                        blame=step,
                        observed=result.observed,
                        requested=result.requested,
                        fix=(
                            "implement that next transition before deferred "
                            "normalization"
                        ),
                    )
                if isinstance(result, (ExitSet, NativeOperationExitCarrierV1)):
                    return result
                return ExitSet.completed(result)

            parts.append(ExitSet(completed).and_then(continue_term))
        if not parts:
            return ExitSet(())
        result = parts[0]
        for part in parts[1:]:
            result = result.union(part)
        return result

    def _continue_after_two_faced_cleanup(self, cleanup, requested: str):
        """A ``finally`` cleanup that may complete or raise.

        A halted face leaves the generator with the cleanup's raise.  A
        completed face is the cleanup suite finishing: the frame continues past
        the ``finally`` under that face's guard, exactly as a one-faced cleanup
        does.  Handing the completed face's reduced block to the consumer would
        present the cleanup's statement record as the generator's next
        transition.
        """
        from sugar_lift_py_tests.caller_parameter_contract import (
            NativeOperationExitCarrierV1,
        )
        from sugar_lift_py_tests.outcome.exit_set import Halted
        from sugar_source_tree.panic import SugarNotWritten

        halted = tuple(face for face in cleanup.exits if isinstance(face, Halted))
        completed = tuple(
            face for face in cleanup.exits if not isinstance(face, Halted)
        )
        result = ExitSet(halted)
        if completed:

            def continue_after(value):
                binding_state = (
                    value.binding_state
                    if isinstance(value, GeneratorTerminationV1)
                    else self.binding_state
                )
                machine = replace(
                    self, cursor=self.cursor + 1, binding_state=binding_state
                )
                after = machine._transition(requested)
                if isinstance(after, GeneratorTransitionGapV1):
                    raise SugarNotWritten(
                        owner="GeneratorConstructionV1.transition",
                        blame=self.steps[self.cursor],
                        observed=after.observed,
                        requested=after.requested,
                        fix="implement the transition after the finally cleanup",
                    )
                if isinstance(after, (ExitSet, NativeOperationExitCarrierV1)):
                    return after
                return ExitSet.completed(after)

            result = result.union(ExitSet(completed).and_then(continue_after))
        return result

    def _fold_pending_cited_opaque_exits(self, outgoing):
        """Apply already-written cited-opaque exit over an outgoing body edge.

        Python's with law runs ``__exit__`` on every outgoing body edge,
        including a return, a raise, or a body halt such as a failed
        attribute store.
        The step producer's ``compose_finally`` seats cleanup before a return
        or raise and also on fall-through, so the remaining steps after
        that terminal include a finally copy and then
        ``NestedCitedOpaqueExitStepV1``. A return or raise must not skip
        that exit. This reuses ``_exit_nested_cited_opaque(..., incoming=)``,
        the same fold ``throw`` already applies when the cursor is already
        on the exit step. It does not invent that exit swallowed the
        termination. Cleanup that itself halts still returns before this
        fold, so a finally raise keeps the still-open enter face.
        """
        from sugar_lift_py_tests.outcome import ExitSet

        from sugar_lift_py_tests.outcome.exit_set import Completed, Halted

        pending = []
        last = None
        for index, step in enumerate(
            self.steps[self.cursor + 1 :], start=self.cursor + 1
        ):
            if isinstance(step, (FinallyStepV1, InertStepV1)):
                continue
            if isinstance(step, NestedCitedOpaqueExitStepV1):
                pending.append(step)
                last = index
                continue
            if not pending and isinstance(step, _BODY_REMAINDER_STEPS):
                # The rest of the flattened with body (a later statement, a
                # yield not yet reached): a halt leaves the body, so it never
                # runs, and the enclosing exit still does. Only a flattened
                # body is spliced before its exit step, so that exit encloses
                # this cursor.
                continue
            break
        if not pending:
            return outgoing
        if isinstance(outgoing, ExitSet):
            # A halted edge leaves THIS machine at this cursor: whatever
            # internal state a reduced helper carried, the generator's
            # pre-halt state is the machine itself.
            incoming = ExitSet(
                tuple(
                    replace(face, state=self) if isinstance(face, Halted) else face
                    for face in outgoing.exits
                )
            )
        else:
            incoming = ExitSet.completed(outgoing)
        result = incoming
        for step in pending:
            result = self._exit_nested_cited_opaque(
                step,
                requested="pending cited-opaque exit",
                incoming=result,
            )
        # A face the exit SUPPRESSED completes carrying the pre-halt state --
        # this machine, still poised on the raise. Python continues after the
        # ``with`` statement, so that face's successor is the machine past the
        # last exit step, never the raise again.
        after_with = replace(self, cursor=last + 1)
        return ExitSet(
            tuple(
                # The suppressed face keeps its guard, faces and owed.
                replace(face, value=after_with)
                if isinstance(face, Completed) and face.value is self
                else face
                for face in result.exits
            )
        )

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

        from sugar_lift_py_tests.caller_parameter_contract import (
            NativeOperationExitCarrierV1,
        )
        from sugar_source_tree.panic import SugarNotWritten

        def _refuse_transition(result):
            if isinstance(result, GeneratorTransitionGapV1):
                observed = result.observed
                requested_result = result.requested
            else:
                observed = "If carrying a suspension"
                requested_result = requested
            raise SugarNotWritten(
                owner="GeneratorConstructionV1.transition",
                blame=step,
                observed=observed,
                requested=requested_result,
                fix=(
                    "implement that next branch transition before deferred "
                    "normalization"
                ),
            )

        def _transition_truth(truth):
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

            branches = ExitSet(
                (
                    Completed(
                        guard_formula,
                        self._spliced(step.then_steps),
                        frozenset({then_face}),
                    ),
                    Completed(
                        not_(guard_formula),
                        self._spliced(step.else_steps),
                        frozenset({else_face}),
                    ),
                )
            )

            def _transition_branch_machine(machine):
                transitioned = machine._transition(requested)
                if isinstance(transitioned, GeneratorTransitionGapV1):
                    _refuse_transition(transitioned)
                if isinstance(
                    transitioned, (ExitSet, NativeOperationExitCarrierV1)
                ):
                    return transitioned
                return ExitSet.completed(transitioned)

            transitioned = branches.sequence(_transition_branch_machine)
            if isinstance(transitioned, ExitSet):
                factored = transitioned.factor_completed()
                branch_faces = frozenset({then_face, else_face})
                return ExitSet(
                    tuple(
                        (
                            # Guard, value and owed stay; the branch faces join.
                            _replace(exit_, faces=exit_.faces | branch_faces)
                            if isinstance(exit_, Completed)
                            else exit_
                        )
                        for exit_ in factored.exits
                    )
                )
            return transitioned

        def _project_guard_operand(value):
            projected = self._guard_truth(value)
            if projected is None or isinstance(projected, GeneratorTransitionGapV1):
                _refuse_transition(projected)
            return projected

        def _transition_projected_truth(truth):
            transitioned = _transition_truth(truth)
            if transitioned is None or isinstance(
                transitioned, GeneratorTransitionGapV1
            ):
                _refuse_transition(transitioned)
            if isinstance(transitioned, (ExitSet, NativeOperationExitCarrierV1)):
                return transitioned
            return ExitSet.completed(transitioned)

        guard_outcome = self._guard_truth(step.guard)
        if (
            isinstance(guard_outcome, ExitSet)
            and guard_outcome.exits
            and guard_outcome.halts() == guard_outcome.exits
        ):
            return self._fold_pending_cited_opaque_exits(
                ExitSet(tuple(replace(h, state=self) for h in guard_outcome.halts()))
            )
        if (
            isinstance(guard_outcome, ExitSet)
            and guard_outcome.completed_value() is not None
            and not guard_outcome.owed_items()
        ):
            return _transition_truth(guard_outcome.completed_value())
        if isinstance(guard_outcome, ExitSet):
            projected = guard_outcome.sequence(_project_guard_operand)
        elif isinstance(guard_outcome, NativeOperationExitCarrierV1):
            projected = guard_outcome.and_then(_project_guard_operand)
        else:
            return self._gap(requested, "If carrying a suspension")
        if isinstance(projected, ExitSet):
            return projected.sequence(_transition_projected_truth)
        if isinstance(projected, NativeOperationExitCarrierV1):
            return projected.and_then(_transition_projected_truth)
        return self._gap(requested, "If carrying a suspension")

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
        (``reduction_context=None``).  That shell still starts from
        ``TemporalContext.empty()``, the language-owned builtin name floor,
        so a guard like ``isinstance(expected, tuple)`` can use the already
        written ClassValue law rather than treating ``isinstance`` and
        ``tuple`` as free names.  Formal floors overlay those builtins and
        win on a shadowed spelling.  The binder-only shell is a
        ``ReduceContext.root`` with that temporal, so a cleanup term can
        reduce already-written prefix rather than stalling as a temporal-only
        shell.  BindingCoordinateRefSugar.desugar remains the sole consumer
        door for formals.
        """
        from sugar_lift_py_tests.context.reduce_context import ReduceContext
        from sugar_lift_py_tests.temporal.temporal_context import TemporalContext

        base = self.reduction_context
        if base is None:
            temporal = TemporalContext.empty()
        else:
            temporal = base.temporal

        for binding in self.formal_floor_bindings:
            temporal = temporal.bind_value(binding.coordinate_cid, binding.floor_value)

        if base is None:
            ctx = ReduceContext.root(
                owner="GeneratorConstructionV1.guard"
            ).with_temporal(temporal)
        else:
            ctx = base.with_temporal(temporal)
        # The frame's writes, in the order the steps made them.  A walrus a
        # yielded value carried writes through ``NamedExpressionValue.bind``
        # (its name and its evaluation key), the same write a statement
        # applies.
        from sugar_lift_py_tests.sugar.assigned_value import _bind_evaluations

        for item in self.binding_state:
            if isinstance(item, GeneratorAssignBindingV1) and item.value is not None:
                if item.name is not None:
                    ctx = ctx.with_temporal(
                        ctx.temporal.bind_value(item.name, item.value)
                    )
                if item.evaluation is not None:
                    # Keyed as any assignment's sugar keys it.
                    ctx = _bind_evaluations(
                        ctx, ((item.evaluation, 0),), 0, item.value
                    )
            if isinstance(item, GeneratorLoopBindingV1):
                ctx = ctx.with_temporal(
                    ctx.temporal.bind_value(item.coordinate.cid, item.value)
                )
            if isinstance(item, GeneratorWalrusBindingV1):
                ctx = item.bind.bind(ctx)
        # An assignment step evaluated its RHS once, at the step (#7600): a
        # later step's substituted read of that RHS answers with the value the
        # step completed with, never a second evaluation.
        for item in self.binding_state:
            if (
                isinstance(item, GeneratorAssignBindingV1)
                and item.value is not None
                and item.rhs_key is not None
            ):
                ctx = ctx.with_assigned_value(item.rhs_key, item.value)
        return ctx

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
        from sugar_lift_py_tests.caller_parameter_contract import (
            NativeOperationExitCarrierV1,
        )
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
            if isinstance(outcome, NativeOperationExitCarrierV1):
                return outcome
            if not isinstance(outcome, ExitSet):
                return None
            if outcome.completed_value() is None or outcome.owed_items():
                # A halt, a split, or an owing arm: the caller reads the arms.
                return outcome
            value = outcome.completed_value()
        truth = getattr(value, "truth", None)
        if truth is None:
            return None
        # ConstructionPanic is BaseException by design so ordinary Exception
        # handlers cannot silence it. Do not catch BaseException here — that
        # would reclassify incomplete floors as undecided suspension gaps.
        outcome = truth(self.instance_coordinate)
        if isinstance(outcome, (ExitSet, NativeOperationExitCarrierV1)):
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
        from sugar_lift_py_tests.caller_parameter_contract import (
            NativeOperationExitCarrierV1,
        )
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
        if (
            isinstance(outcome, ExitSet)
            and outcome.completed_value() is not None
            and not outcome.owed_items()
        ):
            return outcome.completed_value()
        if isinstance(outcome, (ExitSet, NativeOperationExitCarrierV1)):
            # A halt, a split, or an owing arm: the step sequences the arms
            # (``and_then`` carries each arm's ``owed``).
            return outcome
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
            if isinstance(result, GeneratorTransitionGapV1):
                # A cleanup step that cannot transition stays a typed leftover,
                # not a construction panic that hides the inner observed gap.
                from sugar_source_tree.panic import SugarNotWritten

                raise SugarNotWritten(
                    owner=result.owner,
                    blame=step,
                    observed=result.observed,
                    requested=result.requested,
                    fix=result.fix,
                )
            from sugar_lift_py_tests.gap.panic import construction_panic_gap

            construction_panic_gap(
                owner="GeneratorConstructionV1._reduce_finally",
                blame=step,
                observed=f"cleanup transitioned to {type(result).__name__}",
                requested="completed or halted cleanup",
                fix="keep suspension and unresolved steps out of a finally cleanup suite",
            )
        return reduce_block_to_exitset(
            step.statements, self._guard_evaluation_context()
        )

    def _recording_walrus_binds(self, value):
        """``(machine, presented)``: this machine with every walrus bind
        ``value`` carries recorded in its binding state
        (``GeneratorWalrusBindingV1``, in evaluation order), and the value the
        binds present.  A value with no bind is itself, on this machine.

        The one place a generator step records the walrus binds its value
        carried out of the operand: a yield, an assignment and an expression
        statement each peel through here."""
        from sugar_lift_py_tests.floor.named_expression_value import (
            peel_walrus_binds,
        )

        binds, presented = peel_walrus_binds(value)
        if not binds:
            return self, value
        recorded = replace(
            self,
            binding_state=(
                *self.binding_state,
                *(GeneratorWalrusBindingV1(bind) for bind in binds),
            ),
        )
        return recorded, presented

    def _sent_value(self, requested: str):
        """The value the resume at this cursor sent into the yield before it.

        The yield suspended with ``<instance>:resume:<this cursor>``.  A plain
        resume (``next``) leaves that coordinate suspended and sends ``None``.
        ``send`` clears it and records ``ResumeBindingV1`` at that coordinate
        as the frame's last write; ``send(None)`` is ``next``.  Any other
        arrival at this step has no authenticated sent value and is refused.
        """
        from sugar_lift_py_tests.floor.none_value import NoneValue

        coordinate = f"{self.instance_coordinate}:resume:{self.cursor}"
        if self.suspended_resume_coordinate == coordinate:
            return NoneValue()
        last = self.binding_state[-1] if self.binding_state else None
        if (
            self.suspended_resume_coordinate is None
            and isinstance(last, ResumeBindingV1)
            and last.resume_coordinate == coordinate
        ):
            return NoneValue() if last.resume_value is None else last.resume_value
        return self._gap(
            requested, "yield assignment resumed without its yield's resume"
        )

    @staticmethod
    def _gap(requested: str, observed: str) -> GeneratorTransitionGapV1:
        return GeneratorTransitionGapV1(
            owner="GeneratorConstructionV1.transition",
            observed=observed,
            requested=requested,
        )


def _guard_exits(exit_set: ExitSet, face) -> ExitSet:
    """``exit_set`` continuing beneath one routing face, completed or halted.

    Composed through ``ExitSet.sequence`` (``consume=`` for a halted face the
    routing owns): the face's guard is conjoined onto every exit, both sets of
    partition testimony ride, and the face's debts ride onto every exit under
    it.
    """
    return ExitSet((face,)).sequence(
        lambda _value: exit_set, consume=lambda _halt: exit_set
    )


def _halts_with_a_raise(value) -> bool:
    """A step's value that raised: one unconditional halt with a ``RaiseEffect``.

    This is the halt ``ground_exceptional_exit`` returns (``1 // 0``).  It
    carries no branch condition, so the step's own
    halted face, with the machine's state, is the whole outcome.
    """
    from sugar_lift_py_tests.effect import RaiseEffect
    from sugar_lift_py_tests.outcome.exit_set import _is_true

    return (
        isinstance(value, ExitSet)
        and len(value.exits) == 1
        and value.halts() == value.exits
        and isinstance(value.exits[0].effect, RaiseEffect)
        and _is_true(value.exits[0].guard)
    )
