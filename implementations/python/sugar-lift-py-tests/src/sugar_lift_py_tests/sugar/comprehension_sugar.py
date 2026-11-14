"""Symbolic comprehensions as nested guarded iterator recurrences."""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import (
    ConstructedTermSugar,
    require_constructed_term_sugar,
)
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class ComprehensionTargetSugar:
    """What one generator binds per symbolic element: a coordinate, or an
    ordered destructuring of coordinates.

    A leaf carries ``source_name`` and binds the whole element. A pattern
    carries ``coordinates`` and binds each position to a projection of the
    element -- the same binding problem a statement loop's tuple target
    solves, expressed against a SYMBOLIC element rather than a display.
    Exactly one of the two is ever set; a shape that is neither (a starred or
    attribute target) is never built here, so the source node stays loud.
    """

    source_name: str | None = None
    coordinates: "tuple[ComprehensionTargetSugar, ...] | None" = None

    def __post_init__(self):
        if (self.source_name is None) == (self.coordinates is None):
            raise ValueError(
                "comprehension target is exactly one of a name or a destructuring"
            )

    def to_term(self):
        from sugar_lift_py_tests.ir import ctor, str_const

        if self.source_name is not None:
            return ctor(
                "python:comprehension-name-target", (str_const(self.source_name),)
            )
        assert self.coordinates is not None
        return ctor(
            "python:comprehension-destructure-target",
            tuple(coordinate.to_term() for coordinate in self.coordinates),
        )


@dataclass(frozen=True)
class ComprehensionGeneratorSugar:
    target: ComprehensionTargetSugar
    binding_coordinate_cid: str
    iterable: ConstructedTermSugar
    filters: tuple[ConstructedTermSugar, ...]
    target_coordinates: tuple = dataclass_field(default=(), compare=False)
    target_pattern: object | None = dataclass_field(default=None, compare=False)
    target_pattern_enrollment: object = dataclass_field(kw_only=True, compare=False)
    """The PRODUCER's closed enrollment answer, minted by #7348's authority.

    This is `SourceUnit.target_pattern_enrollment(consumer)`:
    `TargetPatternEnrolledV1 | TargetPatternNotEnrolledV1`. It is the fact that
    separates "no pattern was ever owed" from "an owed pattern was lost"
    (#7347). Required, with no default -- a default would have re-created the
    very ambiguity this field exists to remove.

    It is the CONSUMER-level answer, and this sugar reads it as a per-slot one.
    That is sound in exactly this domain and nowhere else: `_finite_map`
    consults it only when `target.coordinates` is set, which
    `_comprehension_target` produces only for a Tuple/List of plain Names, and
    such a site always owns a binding leaf -- so an enrolled comprehension
    consumer necessarily owed a pattern for THIS slot. `covers()` is pinned by
    a tooth. This sugar mints no enrollment value of its own and adapts between
    no shapes; #7348 owns the type, the authority, and its reasons.
    """

    def __post_init__(self) -> None:
        require_constructed_term_sugar(
            self.iterable, owner="ComprehensionGeneratorSugar.iterable"
        )
        for filter_sugar in self.filters:
            require_constructed_term_sugar(
                filter_sugar, owner="ComprehensionGeneratorSugar.filters"
            )
        from sugar_source_tree.nodes import (
            TargetPatternEnrolledV1,
            TargetPatternEnrollmentV1,
        )

        if not isinstance(self.target_pattern_enrollment, TargetPatternEnrollmentV1):
            raise TypeError(
                "ComprehensionGeneratorSugar.target_pattern_enrollment requires the "
                "producer's TargetPatternEnrollmentV1; got "
                f"{type(self.target_pattern_enrollment).__name__}"
            )
        if self.target_pattern is not None and not isinstance(
            self.target_pattern_enrollment, TargetPatternEnrolledV1
        ):
            raise ValueError(
                "a target pattern cannot exist for an unenrolled consumer"
            )
        if self.target_pattern is not None:
            from sugar_source_tree.nodes import TargetPatternV1

            if type(self.target_pattern) is not TargetPatternV1:
                raise TypeError(
                    "destructured comprehension target requires its exact TargetPatternV1"
                )
            self.target_pattern.source_unit.require_target_pattern_coordinates(
                self.target_pattern, self.target_coordinates
            )

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:comprehension-generator-construction",
            (
                self.target.to_term(),
                str_const(self.binding_coordinate_cid),
                self.iterable.to_term(owner=owner),
                ctor(
                    "python:comprehension-filters",
                    tuple(value.to_term(owner=owner) for value in self.filters),
                ),
            ),
            symbol_kind="coordinate",
        )


@dataclass(frozen=True)
class ComprehensionSugar(ConstructedTermSugar):
    kind: str
    generators: tuple[ComprehensionGeneratorSugar, ...]
    element: ConstructedTermSugar
    key: ConstructedTermSugar | None = None
    site: object = dataclass_field(compare=False, default=None)
    # ``(name, evaluation key, prior read)`` for each walrus in the element,
    # key, value or a condition (``ListComp._carrying_walrus_priors``): where
    # no member writes the name, it keeps the binding the prior read answers.
    walrus_priors: tuple = dataclass_field(compare=False, default=())
    # ``(name, running coordinate, ordered)`` for each name a walrus in the
    # comprehension writes (``ListComp._walrus_recurrence``): a read of the
    # name inside the comprehension that no walrus of it writes before within
    # its element, key, value or condition reads the running coordinate,
    # which ``_recurrence_start`` binds to the prior binding and ``_written``
    # rebinds after every write; a read after one reads that walrus's key
    # (``nodes._scope_after``).  A name that is not ``ordered`` has
    # no running value: its reads are refused by name.
    walrus_recurrence: tuple = dataclass_field(compare=False, default=())
    # Whether the comprehension's final member is placed after it: what a
    # lambda made in it reads at a call outside every run of it
    # (``_final_member_ctx``, ``_symbolic_final_ctx``).  An eager
    # comprehension runs whole where it is made.  A generator expression
    # runs when it is consumed: only where it is consumed whole in place
    # (``GeneratorExp._consumed_whole_in_place``); anywhere else how far it
    # has been consumed at a later call is not decided, no final member is
    # placed, and that call is refused by name (``EvaluationRefSugar``).
    final_member: bool = True

    def __post_init__(self) -> None:
        if self.kind not in {
            "py.listcomp",
            "py.setcomp",
            "py.dictcomp",
            "py.generatorexp",
        }:
            raise ValueError(f"unknown comprehension kind {self.kind!r}")
        require_constructed_term_sugar(self.element, owner="ComprehensionSugar.element")
        if self.key is not None:
            require_constructed_term_sugar(self.key, owner="ComprehensionSugar.key")

    @classmethod
    def witnesses(cls):
        prefix = "def A(xs):\n    return [x for x in xs]\n\n"
        return _call_pair(
            name="symbolic_list_comprehension",
            owner_sugar="ComprehensionSugar",
            truthful=prefix + "def test_a():\n    assert A([1]) == [1]\n",
            lying=prefix + "def test_a():\n    assert A([1]) == [2]\n",
        )

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        key = (
            ctor("python:no-comprehension-key", ())
            if self.key is None
            else self.key.to_term(owner=owner)
        )
        return ctor(
            "python:comprehension-construction",
            (
                self.occurrence_term(owner=owner),
                str_const(self.kind),
                ctor(
                    "python:comprehension-generators",
                    tuple(
                        generator.to_term(owner=owner) for generator in self.generators
                    ),
                ),
                self.element.to_term(owner=owner),
                key,
            ),
            symbol_kind="coordinate",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        if not self.generators:
            raise ValueError("comprehension recurrence requires a generator")
        return self._desugar_generators(
            0, (), self._evaluation_ctx(ctx), writes=(), outer=ctx
        )

    def _evaluation_ctx(self, ctx):
        """``ctx`` with this evaluation of the comprehension bound, before any
        member, under each member coordinate's evaluation coordinate
        (``comprehension_evaluation_coordinate``): one value, made fresh for
        this evaluation, so two evaluations are never the same one.  Every
        member, condition and element reduces on it.

        A lambda made in the comprehension carries the evaluation
        it was made in (``LambdaSugar.evaluation_coordinates``); a call of it
        reads the member current at the call only while that same evaluation
        runs, the final member once none runs, and is refused by name while
        another evaluation runs (``EvaluationRefSugar``).  A context that
        carries no temporal is returned unchanged."""
        if ctx is None or not hasattr(ctx, "temporal"):
            return ctx
        from sugar_lift_py_tests.floor import SymbolicValue
        from sugar_lift_py_tests.ir import make_var
        from sugar_lift_py_tests.temporal.context_helpers import bind_temporal
        from sugar_source_tree.nodes import comprehension_evaluation_coordinate

        coordinates = tuple(
            comprehension_evaluation_coordinate(coordinate)
            for generator in self.generators
            for coordinate in _member_coordinates(generator)
        )
        # Compared by identity at the call: this object is this evaluation.
        evaluation = SymbolicValue(make_var(coordinates[0]))
        for coordinate in coordinates:
            ctx = bind_temporal(
                ctx,
                coordinate,
                evaluation,
                owner="ComprehensionSugar._evaluation_ctx",
                blame=str(self.site),
            )
        return ctx

    def _desugar_generators(self, index, resolved, ctx, *, writes, outer):
        """``writes``: each walrus write a condition made so far, as
        ``(bind, generator index, condition index)``.  ``outer``: the context
        the comprehension is evaluated in, which a walrus's prior read reads
        (``_walrus_prior``)."""
        from sugar_lift_py_tests.floor.named_expression_value import (
            peel_walrus_binds,
        )

        if index == len(self.generators):
            if self.key is not None:
                # Python evaluates the key before the value: the value reads
                # the key's walrus write.
                return self.key.desugar(ctx).and_then(
                    lambda key: self.element.desugar(
                        self._written(
                            peel_walrus_binds(key)[0], ctx, finite=False
                        )
                    ).and_then(
                        lambda element: self._complete(
                            resolved, element, key, writes=writes, outer=outer
                        )
                    )
                )
            return self.element.desugar(ctx).and_then(
                lambda element: self._complete(
                    resolved, element, writes=writes, outer=outer
                )
            )
        generator = self.generators[index]
        return generator.iterable.desugar(ctx).and_then(
            lambda iterable: self._after_iterable(
                generator, iterable, index, resolved, ctx, writes=writes, outer=outer
            )
        )

    def _after_iterable(
        self, generator, iterable, index, resolved, ctx, *, writes, outer
    ):
        """Project finite maps when the iterable is an exact container floor.

        ``tuple(self._parse_exc(e) for e in (expected,))`` is the RaisesExc
        field path: a one-element TupleValue iterable and a source-visible
        element body.  Projecting ``finite_elements`` here lets
        ``python.tuple.construct`` floor the outer ``tuple(...)`` call; without
        it the generator stays an opaque coordinate and ``not expected_exceptions``
        refuses at the UnaryOp producer.

        A comprehension of several generators is projected when a walrus in
        it writes a name it reads (``walrus_recurrence``): the running value
        threads through the members in nested loop order (each outer member,
        then every inner member under it), which one evaluation over symbolic
        members does not hold.  Without one it stays the symbolic fold.
        """
        if index == 0 and (
            len(self.generators) == 1 or self._running_coordinates(finite=True)
        ):
            from sugar_lift_py_tests.sugar.finite_projection import (
                FiniteProjectionNonSuccessV1,
                FiniteProjectionRefusalV1,
                NotProjected,
                Projected,
                require_finite_projection_decision,
            )

            decision = require_finite_projection_decision(
                self._finite_map(generator, iterable, ctx),
                owner="ComprehensionSugar._finite_map",
            )
            # EXHAUSTIVE. Only the two LAWFUL non-application reasons may fall
            # through to symbolic construction; the other two are construction
            # refusals and may never reach a completed arm (#7347).
            match decision:
                case Projected(outcome=outcome):
                    return outcome
                case NotProjected(
                    reason=FiniteProjectionNonSuccessV1.LAWFULLY_INAPPLICABLE
                ):
                    pass
                case NotProjected(
                    reason=(
                        FiniteProjectionNonSuccessV1.PROJECTION_UNAVAILABLE_IN_CONTEXT
                    )
                ):
                    pass
                case NotProjected(
                    reason=FiniteProjectionNonSuccessV1.AUTHENTICATED_LOOKUP_FAILED
                ):
                    raise FiniteProjectionRefusalV1(
                        FiniteProjectionNonSuccessV1.AUTHENTICATED_LOOKUP_FAILED,
                        construct=self.kind,
                        coordinate=generator.binding_coordinate_cid,
                        shape=_target_shape_name(generator.target),
                        site=self.site,
                    )
                case NotProjected(
                    reason=FiniteProjectionNonSuccessV1.REPLACEMENT_FAILED
                ):
                    raise FiniteProjectionRefusalV1(
                        FiniteProjectionNonSuccessV1.REPLACEMENT_FAILED,
                        construct=self.kind,
                        coordinate=generator.binding_coordinate_cid,
                        shape=_target_shape_name(generator.target),
                        site=self.site,
                    )
                case _:
                    raise TypeError(
                        "unhandled FiniteProjectionDecisionV1 variant "
                        f"{decision!r}: add a match arm, never a fallthrough"
                    )
        return self._desugar_filters(
            generator,
            0,
            (),
            iterable,
            index,
            resolved,
            self._symbolic_final_ctx(
                generator, iterable, self._symbolic_member_ctx(generator, ctx)
            ),
            writes=writes,
            outer=outer,
        )

    def _finite_map(self, generator, iterable, ctx):
        from sugar_lift_py_tests.floor.comprehension_value import ComprehensionValue
        from sugar_lift_py_tests.floor.dict_value import DictValue
        from sugar_lift_py_tests.ir import (
            PrimitiveSort,
            _Lambda,
            _intern_term,
            ctor,
        )
        from sugar_lift_py_tests.outcome import ExitSet
        from sugar_lift_py_tests.sugar.finite_projection import (
            FiniteProjectionNonSuccessV1,
            NotProjected,
            Projected,
        )
        from sugar_source_tree.nodes import TargetPatternEnrolledV1

        members = _finite_members(iterable)
        if members is None:
            return NotProjected(FiniteProjectionNonSuccessV1.LAWFULLY_INAPPLICABLE)
        # ``generator`` first, then each nested generator, outermost first.
        levels = (generator, *self.generators[1:])
        if any(level.filters for level in levels) and not hasattr(ctx, "temporal"):
            return NotProjected(
                FiniteProjectionNonSuccessV1.PROJECTION_UNAVAILABLE_IN_CONTEXT
            )
        for level in levels:
            if level.target.coordinates is not None and level.target_pattern is None:
                # The producer's OWN enrollment answer decides which fact this
                # is. ENROLLED + missing pattern is a stranded authenticated
                # lookup, not an absence, and it may not be spent as a symbolic
                # completion.
                if isinstance(level.target_pattern_enrollment, TargetPatternEnrolledV1):
                    return NotProjected(
                        FiniteProjectionNonSuccessV1.AUTHENTICATED_LOOKUP_FAILED
                    )
                return NotProjected(FiniteProjectionNonSuccessV1.LAWFULLY_INAPPLICABLE)
        if ctx is None or not hasattr(ctx, "temporal"):
            return NotProjected(
                FiniteProjectionNonSuccessV1.PROJECTION_UNAVAILABLE_IN_CONTEXT
            )
        from dataclasses import replace

        try:
            # Probe the sole context-replacement capability the projection
            # needs BEFORE entering the recursion. Inside ``project`` a failure
            # would have to travel back through ``ExitSet.and_then``, which is
            # exactly how this cause used to be laundered into a bare ``None``.
            replace(ctx, temporal=ctx.temporal)
        except TypeError:
            return NotProjected(FiniteProjectionNonSuccessV1.REPLACEMENT_FAILED)

        from sugar_lift_py_tests.floor.named_expression_value import (
            carry_walrus_binds,
            peel_walrus_binds,
        )
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            plain_completed_value,
        )

        owner = str(self.site)

        # A walrus in the element (``[(last := v) for v in xs]``) or a
        # condition binds the enclosing scope on every member that reaches
        # it: each member's conditions, then its element, write their keys,
        # the next member starts from those writes (``carried``), and the
        # comprehension's value carries each name's last write out to the
        # enclosing statement (``_carried_out``).  A read of the name inside
        # the comprehension reads its running value (``walrus_recurrence``):
        # the prior binding for the first member (``_recurrence_start``),
        # then every write before it, in evaluation order (``_written``).  A
        # name no member wrote (no member, or none that reached its walrus)
        # keeps its prior binding.  Each condition and element is evaluated
        # once per member, after the members before it, and its walrus value
        # is never evaluated again.  A generator expression writes nothing
        # here: its writes wait for it to be consumed.
        #
        # Several generators run as nested loops: under each outer member
        # that its conditions keep, the next generator's iterable is
        # evaluated (it reads the outer member and the writes so far), and
        # its members run in order before the next outer member.  The writes
        # thread through that order: ``carried`` passes from each member to
        # the next at every depth.
        def finish(projected, binds, _carried):
            binds = (
                () if self.kind == "py.generatorexp" else self._carried_out(binds, ctx)
            )
            if self.key is not None:
                return ExitSet.completed(
                    carry_walrus_binds(binds, DictValue(tuple(projected)))
                )
            if projected:
                element_term = projected[0].to_term(owner=owner)
            else:
                element_term = ctor("python:loop.latch", [], symbol_kind="coordinate")
            term = ctor(
                self.kind,
                [
                    iterable.to_term(owner=owner),
                    _intern_term(
                        _Lambda(
                            generator.binding_coordinate_cid,
                            PrimitiveSort("Value"),
                            element_term,
                        )
                    ),
                    ctor("python:loop.exhaustion", [], symbol_kind="coordinate"),
                ],
                symbol_kind="coordinate",
            )
            return ExitSet.completed(
                carry_walrus_binds(
                    binds,
                    ComprehensionValue(term, finite_elements=tuple(projected)),
                )
            )

        def project(depth, members, index, projected, binds, carried, done):
            """Member ``index`` of ``members`` (generator ``depth``'s) and
            every member after it, then ``done``."""
            level = levels[depth]
            if index == len(members):
                return done(projected, binds, carried)

            def after(projected, binds, carried):
                return project(
                    depth, members, index + 1, projected, binds, carried, done
                )

            unpacked, enter = self._member_unpack(level, members[index], carried)
            if unpacked.completed_value() is None and level.filters:
                # The member does not destructure on every arm: its
                # conditions are not decided here.
                raise _UndecidedMember

            # The member runs beneath each completed arm of its unpack; the
            # unpack's halt is an arm of the comprehension as it is.
            def member(roster):
                return run_member(
                    depth, enter(roster), projected, binds, carried, after
                )

            if len(unpacked.exits) == 1:
                return unpacked.and_then(member)
            return unpacked.sequence(member)

        def run_member(depth, inner_ctx, projected, binds, carried, after):
            """One member of generator ``depth`` whose target is bound in
            ``inner_ctx``: its conditions, then its element (or the next
            generator's members), then ``after`` (every member after it)."""
            level = levels[depth]
            # The member's conditions run before its element, after every
            # earlier member: their writes come first.
            keep, condition_writes, inner_ctx = self._sifted(level, inner_ctx)
            binds = _last_binds((*binds, *condition_writes))
            carried = self._written(condition_writes, carried, finite=True)
            if not keep:
                return after(projected, binds, carried)
            if depth + 1 < len(levels):
                # The next generator's members, under this member: its
                # iterable reads this member and every write before it.
                inner = levels[depth + 1]
                inner_members = _finite_members(
                    plain_completed_value(inner.iterable.desugar(inner_ctx))
                )
                if inner_members is None:
                    # Not a finite container: the nested members are not
                    # fixed here, and the comprehension stays symbolic.
                    raise _UndecidedMember
                return project(
                    depth + 1, inner_members, 0, projected, binds, inner_ctx, after
                )

            def written(wrote):
                """The member's walrus writes: on the next member's context
                and on what the comprehension carries out."""
                return (
                    _last_binds((*binds, *wrote)),
                    self._written(wrote, carried, finite=True),
                )

            if self.key is not None:

                def after_key(key_value):
                    key_binds, key = peel_walrus_binds(key_value)
                    # Python evaluates the key before the value: the value
                    # reads the key's walrus write.
                    value_ctx = self._written(key_binds, inner_ctx, finite=True)
                    return self.element.desugar(value_ctx).and_then(
                        lambda value_value: after_value(key_binds, key, value_value)
                    )

                def after_value(key_binds, key, value_value):
                    value_binds, value = peel_walrus_binds(value_value)
                    return after(
                        (*projected, (key, value)),
                        *written((*key_binds, *value_binds)),
                    )

                return self.key.desugar(inner_ctx).and_then(after_key)

            def after_element(element_value):
                element_binds, element = peel_walrus_binds(element_value)
                return after(
                    (
                        *projected,
                        element.project_operation_receiver(
                            inner_ctx,
                            owner="ComprehensionSugar finite constructed element",
                        ),
                    ),
                    *written(element_binds),
                )

            return self.element.desugar(inner_ctx).and_then(after_element)

        # The cell holds the last member iterated once the comprehension is
        # done, whichever members the filters keep: a stored closure's read.
        final_ctx = (
            self._final_member_ctx(generator, members[-1], ctx) if members else ctx
        )
        try:
            projected = project(
                0,
                members,
                0,
                (),
                (),
                self._recurrence_start(final_ctx, ctx),
                finish,
            )
        except _UndecidedMember:
            # A condition's verdict is not one decided bool for some member,
            # or a nested generator's iterable is not a finite container:
            # which members run is not fixed, and the comprehension stays
            # symbolic.
            return NotProjected(FiniteProjectionNonSuccessV1.LAWFULLY_INAPPLICABLE)
        # ExitSet.and_then owns terminal/guarded propagation. Every constructed
        # outcome propagates unchanged through its own continuation law and is
        # TRANSPORTED by ``Projected`` -- which is not a non-success cause.
        return Projected(projected)

    def _member_unpack(self, generator, member, ctx):
        """``(unpacked, enter)``: one finite member's unpack into the
        generator's target.  ``unpacked`` is an ``ExitSet`` whose completed
        arms hold the target's roster (``()`` for a name target) and whose
        halted arms are the unpack's halt (the member does not destructure
        into the target's leaves); a member with no authenticated cardinality
        answers both, its leaves' projections under the unpack's completes
        atom and the halt under its complement.  ``enter(roster)`` is ``ctx``
        with the member and a completed arm's leaves bound.

        A read of a target name in the element or a condition is a member
        ``EvaluationRef`` to the coordinate bound here (temporal choice 1,
        #7661): the generator's coordinate for a name target, each leaf's
        coordinate for a destructuring one. The reference reads only the
        coordinate. The source name is still bound, for a read substitution
        did not rewrite.
        """
        from dataclasses import replace

        from sugar_lift_py_tests.operations.positional_unpack_operation import (
            PositionalUnpackOperation,
            UnpackMemberRoster,
        )
        from sugar_lift_py_tests.outcome import ExitSet

        target = generator.target
        member = member.project_operation_receiver(
            ctx, owner="ComprehensionSugar finite iterable member"
        )
        temporal = ctx.temporal
        if target.source_name is not None:
            temporal = temporal.bind_value(target.source_name, member)
        temporal = temporal.bind_value(generator.binding_coordinate_cid, member)
        if target.coordinates is None:
            return ExitSet.completed(()), lambda _roster: replace(
                ctx, temporal=temporal
            )
        leaves = _target_leaves(target)

        def enter(roster):
            if not isinstance(roster, UnpackMemberRoster):
                raise TypeError(
                    "comprehension target unpack omitted its authenticated roster"
                )
            leaf_temporal = temporal
            for leaf, coordinate, value in zip(
                leaves,
                generator.target_coordinates,
                roster.members,
                strict=True,
            ):
                leaf_temporal = leaf_temporal.bind_value(leaf.source_name, value)
                leaf_temporal = leaf_temporal.bind_value(coordinate.cid, value)
            return replace(ctx, temporal=leaf_temporal)

        unpacked = PositionalUnpackOperation(
            fixed_prefix=len(leaves),
            fixed_suffix=0,
            has_star=False,
            owner="ComprehensionSugar._finite_map.target",
            blame=self.site,
        ).submit(member, ctx)
        return unpacked, enter

    def _symbolic_member_ctx(self, generator, ctx):
        """``ctx`` with the generator's symbolic member bound before any read
        of it: the variable the recurrence's lambda binds (``_complete``)
        under the generator's coordinate, and, for a destructuring target,
        each leaf's projection of it under the leaf's coordinate. These are
        the coordinates a member ``EvaluationRef`` reads, bound as
        ``_member_unpack`` binds a finite member, so the element, the
        conditions and every later generator read the member and never a
        name an enclosing statement bound. A context that carries no
        temporal is returned unchanged: a member read in it panics.
        """
        from sugar_lift_py_tests.floor import SymbolicValue
        from sugar_lift_py_tests.ir import make_var
        from sugar_lift_py_tests.temporal.context_helpers import bind_temporal

        if ctx is not None and not hasattr(ctx, "temporal"):
            return ctx
        element = make_var(generator.binding_coordinate_cid)
        bindings = [(generator.binding_coordinate_cid, element)]
        if generator.target.coordinates is not None:
            bindings.extend(
                zip(
                    (coordinate.cid for coordinate in generator.target_coordinates),
                    _leaf_projections(generator.target, element),
                    strict=True,
                )
            )
        for coordinate, term in bindings:
            ctx = bind_temporal(
                ctx,
                coordinate,
                SymbolicValue(term),
                owner="ComprehensionSugar._symbolic_member_ctx",
                blame=str(self.site),
            )
        return ctx

    def _final_member_ctx(self, generator, last, ctx):
        """``ctx`` with the generator's final member bound: what the
        comprehension's cell holds once it is done, the ``last`` finite
        member, under each member coordinate's final coordinate
        (``final_member_coordinate``) -- the generator's, and each leaf's
        projection of it for a destructuring target. Every lambda in the
        comprehension reads these at a call after it
        (``Lambda._cells_read_at_the_call``), and so does every lambda in an
        inner comprehension in the element: they are bound on the context
        every member's element, and so every inner comprehension, reduces
        in. The lambda value carries each binding it reads
        (``LambdaCallable.closure``), so its body reduces after the
        comprehension is done. ``ctx`` unchanged when ``last`` does not
        destructure into the target on any arm: the comprehension halts on
        it, and no lambda made in it outlives it.  ``ctx`` unchanged, too,
        where the final member is not placed (``final_member``: a generator
        expression not consumed whole in place).
        """
        from dataclasses import replace

        from sugar_source_tree.nodes import final_member_coordinate

        if not self.final_member:
            return ctx
        from sugar_lift_py_tests.outcome import Completed

        unpacked, enter = self._member_unpack(generator, last, ctx)
        # The comprehension is done only on the unpack's completed arm: its
        # roster (each leaf's projection, for a member with no authenticated
        # cardinality) is what the cell holds there.
        completed = [arm for arm in unpacked.exits if isinstance(arm, Completed)]
        if len(completed) != 1:
            return ctx
        member_ctx = enter(completed[0].value)
        temporal = ctx.temporal
        for coordinate in _member_coordinates(generator):
            temporal = temporal.bind_value(
                final_member_coordinate(coordinate),
                member_ctx.temporal.value_if_bound(coordinate),
            )
        return replace(ctx, temporal=temporal)

    def _symbolic_final_ctx(self, generator, iterable, ctx):
        """``ctx`` with the generator's symbolic final member bound under each
        member coordinate's final coordinate (``final_member_coordinate``),
        as ``_final_member_ctx`` binds a finite one: the final member of
        ``iterable`` (the member's final evaluation), and, for a destructuring
        target, each leaf's projection of it. A context that carries no
        temporal is returned unchanged, as is one where the final member is
        not placed (``final_member``).
        """
        from sugar_lift_py_tests.floor import SymbolicValue
        from sugar_lift_py_tests.ir import ctor, str_const
        from sugar_lift_py_tests.temporal.context_helpers import bind_temporal
        from sugar_source_tree.nodes import final_member_coordinate

        if not self.final_member:
            return ctx
        if ctx is not None and not hasattr(ctx, "temporal"):
            return ctx
        final = ctor(
            "python:comprehension.final_member",
            [
                iterable.to_term(owner=str(self.site)),
                str_const(generator.binding_coordinate_cid),
            ],
            symbol_kind="coordinate",
        )
        terms = (final,)
        if generator.target.coordinates is not None:
            terms = (final, *_leaf_projections(generator.target, final))
        coordinates = _member_coordinates(generator)
        for coordinate, term in zip(coordinates, terms, strict=True):
            ctx = bind_temporal(
                ctx,
                final_member_coordinate(coordinate),
                SymbolicValue(term),
                owner="ComprehensionSugar._symbolic_final_ctx",
                blame=str(self.site),
            )
        return ctx

    def _sifted(self, generator, inner_ctx):
        """Whether every ``if`` condition keeps the member ``inner_ctx``
        binds, the walrus writes its conditions made, and ``inner_ctx`` with
        those writes applied.

        Python evaluates a member's conditions in order, stopping at the
        first false one, and keeps the member only if all are true.  A
        walrus in a condition writes whether or not the member is kept: the
        write reaches the next condition of the member, its element and
        every later member.  The member's conditions read what every earlier
        member wrote, so they run here, member by member.  When every
        condition reached reduces to a plain decided bool (no effect, no
        halt, no symbolic guard), whether the member survives is fixed.  Any
        other verdict raises ``_UndecidedMember`` and the comprehension stays
        symbolic, as before.  Without conditions the member is kept and
        nothing is evaluated here.
        """
        from sugar_lift_py_tests.floor.named_expression_value import (
            peel_walrus_binds,
        )
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            plain_completed_value,
        )

        wrote = ()
        for guard in generator.filters:
            value = plain_completed_value(guard.desugar(inner_ctx))
            if value is None:
                raise _UndecidedMember
            binds, verdict_value = peel_walrus_binds(value)
            verdict = _decided_verdict(verdict_value)
            if verdict is None:
                raise _UndecidedMember
            wrote = (*wrote, *binds)
            inner_ctx = self._written(binds, inner_ctx, finite=True)
            if not verdict:
                return False, wrote, inner_ctx
        return True, wrote, inner_ctx

    def _running_coordinates(self, *, finite: bool) -> dict:
        """Each ``ordered`` name of ``walrus_recurrence``, to the coordinate
        its running value is bound under.

        Empty over symbolic members of several generators: a member of an
        inner generator reads the writes of the inner members before it,
        which one evaluation over symbolic members does not hold, so no
        running value is bound and the reads are refused by name.  The
        ``finite`` projection runs the members of every generator in nested
        loop order, and threads the running value through them."""
        if not finite and len(self.generators) != 1:
            return {}
        return {
            name: coordinate
            for name, coordinate, ordered in self.walrus_recurrence
            if ordered
        }

    def _written(self, binds, ctx, *, finite: bool):
        """``ctx`` with the walrus writes ``binds`` applied in evaluation
        order, for the element, key, value or condition evaluated after them:
        the running value of each ``ordered`` name (``_running_coordinates``),
        so a later read of the name in the comprehension reads the last write
        before it; for any other name, each walrus's key
        (``bind_walrus_binds``).

        The key of an ``ordered`` name's walrus is never bound here: a read
        after the walrus within one element, key, value or condition reads
        it (``nodes._scope_after``), and only the consumer that
        evaluates that read after the walrus binds it, with this member's
        write (``named_expression_value.written_by``).  Where that bind did
        not reach the read, the key is unbound and the read is refused by
        name, never an earlier member's write.  ``ctx`` itself when there
        are none or it carries no temporal."""
        if not binds or ctx is None or not hasattr(ctx, "temporal"):
            return ctx
        from dataclasses import replace

        from sugar_lift_py_tests.floor.named_expression_value import (
            bind_walrus_binds,
        )

        ordered = {
            name
            for name, _coordinate, is_ordered in self.walrus_recurrence
            if is_ordered
        }
        ctx = bind_walrus_binds(
            tuple(bind for bind in binds if bind.name not in ordered), ctx
        )
        running = self._running_coordinates(finite=finite)
        temporal = ctx.temporal
        for bind in binds:
            coordinate = running.get(bind.name)
            if coordinate is not None:
                temporal = temporal.bind_value(coordinate, bind.assigned_value)
        return replace(ctx, temporal=temporal)

    def _recurrence_start(self, ctx, outer):
        """``ctx`` with each running value (``_running_coordinates``) bound to
        the name's binding before the comprehension, read in ``outer``
        (``_walrus_prior``): what the first member's read of it reads.  A
        name with no one plain prior binding gets none: a read of it before
        any write is refused by name.  Only a finite projection starts the
        recurrence: over a symbolic iterable each member's read needs the
        write of the member before it, which one evaluation over the
        symbolic member does not have, so a read before the member's own
        write is refused by name."""
        running = self._running_coordinates(finite=True)
        if not running:
            return ctx
        from dataclasses import replace

        temporal = ctx.temporal
        for name, coordinate in running.items():
            prior = self._walrus_prior(name, outer)
            if prior is not None:
                temporal = temporal.bind_value(coordinate, prior)
        return replace(ctx, temporal=temporal)

    def _carried_out(self, binds, ctx) -> tuple:
        """The walrus writes the comprehension carries out to the enclosing
        statement, from ``binds`` (the last write of each walrus, in the
        order of those writes, ``_last_binds``).

        Every walrus of one name writes the same variable, so after the
        comprehension each walrus's key holds the name's last write in
        evaluation order, whichever walrus made it: a read after the
        comprehension refers to one of the keys (the last walrus
        substitution met).  A name no member wrote (no member, or none that
        reached a walrus of it) holds what it held before, read in ``ctx``
        (``_walrus_prior``).  A name whose prior read is not one plain value
        (it was unbound, or its read partitions) gets none: a read of it
        after the comprehension is refused by name, as an unwritten walrus
        is (``EvaluationRefSugar``).  A write of a name the roster does not
        hold is carried as it was made."""
        from sugar_lift_py_tests.floor.named_expression_value import (
            NamedExpressionValue,
        )

        last = {}
        for bind in binds:
            last.pop(bind.name, None)
            last[bind.name] = bind
        rostered = {name for name, _evaluation, _read in self.walrus_priors}
        carried = [bind for bind in binds if bind.name not in rostered]
        for name, evaluation, _read in self.walrus_priors:
            if name in last:
                value = last[name].assigned_value
            else:
                value = self._walrus_prior(name, ctx)
                if value is None:
                    continue
            carried.append(NamedExpressionValue(name, value, evaluation=evaluation))
        return tuple(carried)

    def _walrus_prior(self, name, ctx):
        """The one plain value ``name`` held before the comprehension, read
        in ``ctx`` through the read substitution made of it there
        (``walrus_priors``; every walrus of the name has the same read),
        else ``None``.  A read of an enclosing comprehension's running value
        that is not bound there has none (``unwritten_recurrence``)."""
        from sugar_lift_py_tests.sugar.evaluation_ref_sugar import (
            EvaluationRefSugar,
        )
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            plain_completed_value,
        )

        for prior_name, _evaluation, read in self.walrus_priors:
            if prior_name != name:
                continue
            if isinstance(read, EvaluationRefSugar) and read.unwritten_recurrence(
                ctx
            ):
                return None
            return plain_completed_value(read.desugar(ctx))
        return None

    def _desugar_filters(
        self,
        generator,
        filter_index,
        filters,
        iterable,
        index,
        resolved,
        ctx,
        *,
        writes,
        outer,
    ):
        from sugar_lift_py_tests.floor.named_expression_value import (
            peel_walrus_binds,
        )

        if filter_index == len(generator.filters):
            return self._desugar_generators(
                index + 1,
                (
                    *resolved,
                    (
                        generator.target,
                        generator.binding_coordinate_cid,
                        iterable,
                        filters,
                    ),
                ),
                ctx,
                writes=writes,
                outer=outer,
            )

        def after_guard(guard_value):
            # A walrus in the condition writes for every member reaching it;
            # the guard is the value it presents.
            binds, guard = peel_walrus_binds(guard_value)
            return self._desugar_filters(
                generator,
                filter_index + 1,
                (*filters, guard),
                iterable,
                index,
                resolved,
                self._written(binds, ctx, finite=False),
                writes=(*writes, *((bind, index, filter_index) for bind in binds)),
                outer=outer,
            )

        return generator.filters[filter_index].desugar(ctx).and_then(after_guard)

    def _complete(self, resolved, element, key=None, *, writes, outer) -> ExitSet:
        from sugar_lift_py_tests.floor.comprehension_value import ComprehensionValue
        from sugar_lift_py_tests.floor.named_expression_value import (
            carry_walrus_binds,
            peel_walrus_binds,
        )
        from sugar_lift_py_tests.ir import ctor
        from sugar_lift_py_tests.outcome import ExitSet

        # Over a symbolic iterable the element (and a condition) is evaluated
        # once, over the symbolic member: a walrus there presents its value
        # to the fold and its write is carried out as the last member's
        # write, guarded by some member writing (``_symbolic_writes``).
        key_binds = ()
        if key is not None:
            key_binds, key = peel_walrus_binds(key)
        element_binds, element = peel_walrus_binds(element)
        writes = (
            *writes,
            *(
                (bind, len(resolved) - 1, None)
                for bind in (*key_binds, *element_binds)
            ),
        )
        owner = str(self.site)
        element_term = (
            ctor(
                "python:dict_entry",
                [key.to_term(owner=owner), element.to_term(owner=owner)],
                symbol_kind="coordinate",
            )
            if key is not None
            else element.to_term(owner=owner)
        )
        value = ComprehensionValue(
            self._fold_term(self.kind, resolved, element_term, owner=owner)
        )
        if self.kind == "py.generatorexp":
            # A generator's writes wait for it to be consumed.
            return ExitSet.completed(value)
        return ExitSet.completed(
            carry_walrus_binds(
                self._symbolic_writes(resolved, writes, outer, owner=owner), value
            )
        )

    def _symbolic_writes(self, resolved, writes, ctx, *, owner) -> tuple:
        """The walrus writes a comprehension over a symbolic iterable carries
        out: for each name a walrus writes, the name after the comprehension,
        under the key of every walrus of the name (``walrus_priors``).

        A walrus writes for every member that reaches it.  The members that
        reach it are those of every generator up to its own, past every
        condition before it (``rows``); its ``written`` sequence is its
        writes over them.  ``writes`` holds the walruses of a member in
        evaluation order (conditions in order, then the key, then the value
        or element), so the writes of all the walruses of a name, member by
        member in that order, are the name's writes in evaluation order:
        the name holds the last of them when there is one, and its prior
        binding (``_walrus_prior``, read in ``ctx``) when there is none.
        ``python:comprehension.last_write`` and ``python.comprehension.wrote``
        take the ``written`` sequences of every walrus of the name, in that
        order; with one walrus they take its sequence alone.

        No write is carried (a read after the comprehension is refused by
        name) for a name whose prior is not one plain value.
        """
        from sugar_lift_py_tests.floor import SymbolicValue
        from sugar_lift_py_tests.floor.guarded_value import GuardedValue
        from sugar_lift_py_tests.floor.named_expression_value import (
            NamedExpressionValue,
        )
        from sugar_lift_py_tests.ir import atomic, ctor

        by_name: dict = {}
        for bind, generator_index, condition_index in writes:
            by_name.setdefault(bind.name, []).append(
                (bind, generator_index, condition_index)
            )
        carried = []
        for name, named in by_name.items():
            prior = self._walrus_prior(name, ctx)
            if prior is None:
                continue
            sequences = []
            for bind, generator_index, condition_index in named:
                rows = tuple(resolved[: generator_index + 1])
                if condition_index is not None:
                    target, coordinate, iterable, filters = rows[-1]
                    rows = (
                        *rows[:-1],
                        (target, coordinate, iterable, filters[:condition_index]),
                    )
                sequences.append(
                    self._fold_term(
                        "py.listcomp",
                        rows,
                        bind.assigned_value.to_term(owner=owner),
                        owner=owner,
                    )
                )
            last = SymbolicValue(
                ctor(
                    "python:comprehension.last_write",
                    list(sequences),
                    symbol_kind="coordinate",
                )
            )
            value = GuardedValue(
                atomic("python.comprehension.wrote", list(sequences)), last, prior
            )
            for prior_name, evaluation, _read in self.walrus_priors:
                if prior_name == name:
                    carried.append(
                        NamedExpressionValue(name, value, evaluation=evaluation)
                    )
        return tuple(carried)

    def _fold_term(self, kind, resolved, element_term, *, owner):
        """The ``kind`` fold of ``element_term`` over the generator rows
        ``resolved`` (outermost first): each row binds its target, guards
        its destructuring and its conditions, and flat-maps the rows inside
        it."""
        from sugar_lift_py_tests.ir import (
            PrimitiveSort,
            _Lambda,
            _intern_term,
            ctor,
            make_var,
        )

        body = element_term
        recurrence_rows = []
        for target, binding_coordinate_cid, iterable, filters in reversed(resolved):
            coordinate_var = make_var(binding_coordinate_cid)
            body = _bind_target(target, coordinate_var, body)
            for guard in reversed(filters):
                guard_term = _bind_target(
                    target, coordinate_var, guard.to_term(owner=owner)
                )
                body = ctor(
                    "python:loop.filter_guard",
                    [
                        guard_term,
                        body,
                        ctor("python:loop.latch", [], symbol_kind="coordinate"),
                    ],
                    symbol_kind="coordinate",
                )
            body = _guard_destructure(target, coordinate_var, body)
            recurrence_rows.append((binding_coordinate_cid, iterable, body))
            body = ctor(
                "python:loop.flat_map",
                [
                    iterable.to_term(owner=owner),
                    _intern_term(
                        _Lambda(
                            binding_coordinate_cid,
                            PrimitiveSort("Value"),
                            body,
                        )
                    ),
                    ctor("python:loop.exhaustion", [], symbol_kind="coordinate"),
                ],
                symbol_kind="coordinate",
            )
        outer_coordinate, outer_iterable, outer_body = recurrence_rows[-1]
        return ctor(
            kind,
            [
                outer_iterable.to_term(owner=owner),
                _intern_term(
                    _Lambda(outer_coordinate, PrimitiveSort("Value"), outer_body)
                ),
                ctor("python:loop.exhaustion", [], symbol_kind="coordinate"),
            ],
            symbol_kind="coordinate",
        )


class _UndecidedMember(Exception):
    """A finite member whose conditions are not decided here
    (``ComprehensionSugar._sifted``): the finite projection does not apply and
    the comprehension stays symbolic (``_finite_map``)."""


def _finite_members(iterable):
    """The members ``iterable`` yields when it is an exact finite container
    (a list or tuple, an iterator over one from its position, a projected
    comprehension), else ``None`` -- as for a list whose contents are not
    current (``object_identity.contents_stale``)."""
    from sugar_lift_py_tests.floor.comprehension_value import ComprehensionValue
    from sugar_lift_py_tests.floor.iterator_value import (
        ListIteratorValue,
        TupleIteratorValue,
    )
    from sugar_lift_py_tests.floor.list_value import ListValue
    from sugar_lift_py_tests.floor.object_identity import contents_stale
    from sugar_lift_py_tests.floor.tuple_value import TupleValue

    if contents_stale(iterable):
        return None
    if isinstance(iterable, (TupleValue, ListValue)):
        return iterable.elements
    if isinstance(iterable, (ListIteratorValue, TupleIteratorValue)):
        return iterable.elements[iterable.index :]
    if isinstance(iterable, ComprehensionValue) and iterable.finite_elements is not None:
        return iterable.finite_elements
    return None


def _last_binds(binds) -> tuple:
    """The last write of each walrus in ``binds``, in the order of those last
    writes: what the comprehension's value carries out after its final
    member."""
    last: dict = {}
    for bind in binds:
        identity = (bind.name, bind.evaluation)
        last.pop(identity, None)
        last[identity] = bind
    return tuple(last.values())


def _decided_verdict(value):
    """``True``/``False`` when ``value`` (a condition's plain completed value,
    its walrus writes peeled off) is a decided bool, else ``None``."""
    from sugar_lift_py_tests.outcome.exit_set import false_guard, true_guard
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
        FalseBoolLiteralSugar,
    )
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    if isinstance(value, TrueBoolLiteralSugar):
        return True
    if isinstance(value, FalseBoolLiteralSugar):
        return False
    formula = getattr(value, "formula", None)
    if formula is not None and formula == true_guard():
        return True
    if formula is not None and formula == false_guard():
        return False
    return None


def _target_shape_name(target: ComprehensionTargetSugar) -> str:
    """The SHAPE a refusal names: a bound name, or a destructuring arity."""
    if target.source_name is not None:
        return f"name:{target.source_name}"
    assert target.coordinates is not None
    return f"destructure:{len(target.coordinates)}"


def _projection(element, index: int, arity: int):
    """The coordinate the ``index``th position of an ``arity``-wide
    destructuring reads out of a symbolic ``element``.

    Python unpacking is iterable unpacking, not subscription, so this is its
    own coordinate: it carries the arity the source demanded, which is what
    makes the accompanying obligation checkable.
    """
    from sugar_lift_py_tests.ir import ctor, num

    return ctor(
        "python:unpack.project",
        [element, num(index), num(arity)],
        symbol_kind="coordinate",
    )


def _target_leaves(
    target: ComprehensionTargetSugar,
) -> tuple[ComprehensionTargetSugar, ...]:
    if target.source_name is not None:
        return (target,)
    assert target.coordinates is not None
    return tuple(leaf for child in target.coordinates for leaf in _target_leaves(child))


def _member_coordinates(generator: ComprehensionGeneratorSugar) -> tuple[str, ...]:
    """Every coordinate a member binds: the generator's, then, for a
    destructuring target, each leaf's in ``_target_leaves`` order."""
    return (
        generator.binding_coordinate_cid,
        *(coordinate.cid for coordinate in generator.target_coordinates),
    )


def _leaf_projections(target: ComprehensionTargetSugar, element) -> tuple:
    """What each leaf of ``target`` reads out of the symbolic ``element``, in
    ``_target_leaves`` order.

    A leaf reads the element whole. A pattern reads each position's
    projection, recursively -- so a nested pattern reads a projection of a
    projection, exactly as the source nests.
    """
    if target.source_name is not None:
        return (element,)
    coordinates = target.coordinates
    assert coordinates is not None
    arity = len(coordinates)
    return tuple(
        projection
        for index, child in enumerate(coordinates)
        for projection in _leaf_projections(child, _projection(element, index, arity))
    )


def _bind_target(target: ComprehensionTargetSugar, element, body):
    """``body`` with every name this target binds replaced by what the
    symbolic ``element`` binds to it (``_leaf_projections``): a read
    substitution did not rewrite to a member reference.
    """
    from sugar_lift_py_tests.ir import subst_var_in_term

    for leaf, projection in zip(
        _target_leaves(target), _leaf_projections(target, element), strict=True
    ):
        body = subst_var_in_term(body, leaf.source_name, projection)
    return body


def _guard_destructure(target: ComprehensionTargetSugar, element, body):
    """``body`` under the arity obligation every destructuring in this target
    carries.

    A leaf destructures nothing and adds no obligation. A pattern demands the
    element unpack to exactly its arity: when it does, the continuation is
    ``body``; when it does not, Python raises, so the exit is the halt
    coordinate -- NEVER a silently skipped element and never an assumed
    success. Outer obligations wrap inner ones, because the outer element must
    unpack before any inner position exists to be read.
    """
    from sugar_lift_py_tests.ir import ctor, num

    if target.source_name is not None:
        return body
    coordinates = target.coordinates
    assert coordinates is not None
    arity = len(coordinates)
    for index in reversed(range(arity)):
        body = _guard_destructure(
            coordinates[index], _projection(element, index, arity), body
        )
    return ctor(
        "python:unpack.destructure",
        [
            element,
            num(arity),
            body,
            ctor("python:unpack.halt", [], symbol_kind="coordinate"),
        ],
        symbol_kind="coordinate",
    )
