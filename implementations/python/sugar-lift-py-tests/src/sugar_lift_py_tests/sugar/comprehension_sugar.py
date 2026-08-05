"""Symbolic comprehensions as nested guarded iterator recurrences."""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Outcome
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

    def desugar(self, ctx: object = None) -> Outcome:
        if not self.generators:
            raise ValueError("comprehension recurrence requires a generator")
        return self._desugar_generators(0, (), ctx)

    def _desugar_generators(self, index, resolved, ctx):
        if index == len(self.generators):
            if self.key is not None:
                return self.key.desugar(ctx).and_then(
                    lambda key: self.element.desugar(ctx).and_then(
                        lambda element: self._complete(resolved, element, key)
                    )
                )
            return self.element.desugar(ctx).and_then(
                lambda element: self._complete(resolved, element)
            )
        generator = self.generators[index]
        return generator.iterable.desugar(ctx).and_then(
            lambda iterable: self._after_iterable(
                generator, iterable, index, resolved, ctx
            )
        )

    def _after_iterable(self, generator, iterable, index, resolved, ctx):
        """Project finite maps when the iterable is an exact container floor.

        ``tuple(self._parse_exc(e) for e in (expected,))`` is the RaisesExc
        field path: a one-element TupleValue iterable and a source-visible
        element body.  Projecting ``finite_elements`` here lets
        ``python.tuple.construct`` floor the outer ``tuple(...)`` call; without
        it the generator stays an opaque coordinate and ``not expected_exceptions``
        refuses at the UnaryOp producer.
        """
        if index == 0 and len(self.generators) == 1 and not generator.filters:
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
            # refusals and may never reach ``Complete`` (#7347).
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
        return self._desugar_filters(generator, 0, (), iterable, index, resolved, ctx)

    def _finite_map(self, generator, iterable, ctx):
        from sugar_lift_py_tests.floor.comprehension_value import ComprehensionValue
        from sugar_lift_py_tests.floor.dict_value import DictValue
        from sugar_lift_py_tests.floor.list_value import ListValue
        from sugar_lift_py_tests.floor.iterator_value import (
            ListIteratorValue,
            TupleIteratorValue,
        )
        from sugar_lift_py_tests.floor.tuple_value import TupleValue
        from sugar_lift_py_tests.ir import (
            PrimitiveSort,
            _Lambda,
            _intern_term,
            ctor,
        )
        from sugar_lift_py_tests.outcome import Complete
        from sugar_lift_py_tests.sugar.finite_projection import (
            FiniteProjectionNonSuccessV1,
            NotProjected,
            Projected,
        )
        from sugar_source_tree.nodes import TargetPatternEnrolledV1

        members = None
        if isinstance(iterable, (TupleValue, ListValue)):
            members = iterable.elements
        elif isinstance(iterable, (ListIteratorValue, TupleIteratorValue)):
            members = iterable.elements[iterable.index :]
        elif (
            isinstance(iterable, ComprehensionValue)
            and iterable.finite_elements is not None
        ):
            members = iterable.finite_elements
        if members is None:
            return NotProjected(FiniteProjectionNonSuccessV1.LAWFULLY_INAPPLICABLE)
        target = generator.target
        if target.coordinates is not None and generator.target_pattern is None:
            # The producer's OWN enrollment answer decides which fact this is.
            # ENROLLED + missing pattern is a stranded authenticated lookup, not
            # an absence, and it may not be spent as a symbolic Complete.
            if isinstance(
                generator.target_pattern_enrollment, TargetPatternEnrolledV1
            ):
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
            # would have to travel back through ``Outcome.and_then``, which is
            # exactly how this cause used to be laundered into a bare ``None``.
            replace(ctx, temporal=ctx.temporal)
        except TypeError:
            return NotProjected(FiniteProjectionNonSuccessV1.REPLACEMENT_FAILED)

        owner = str(self.site)

        def project(index, projected):
            if index == len(members):
                if self.key is not None:
                    return Complete(DictValue(tuple(projected)))
                if projected:
                    element_term = projected[0].to_term(owner=owner)
                else:
                    element_term = ctor(
                        "python:loop.latch", [], symbol_kind="coordinate"
                    )
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
                return Complete(
                    ComprehensionValue(term, finite_elements=tuple(projected))
                )

            member = members[index].project_operation_receiver(
                ctx, owner="ComprehensionSugar finite iterable member"
            )
            temporal = ctx.temporal.bind_value(generator.binding_coordinate_cid, member)
            if target.coordinates is not None:
                from sugar_lift_py_tests.operations.positional_unpack_operation import (
                    PositionalUnpackOperation,
                    UnpackMemberRoster,
                )

                leaves = _target_leaves(target)
                unpacked = PositionalUnpackOperation(
                    fixed_prefix=len(leaves),
                    fixed_suffix=0,
                    has_star=False,
                    owner="ComprehensionSugar._finite_map.target",
                    blame=self.site,
                ).submit(member, ctx)
                if not isinstance(unpacked, Complete) or not isinstance(
                    unpacked.value, UnpackMemberRoster
                ):
                    return unpacked
                for leaf, coordinate, value in zip(
                    leaves,
                    generator.target_coordinates,
                    unpacked.value.members,
                    strict=True,
                ):
                    temporal = temporal.bind_value(coordinate.cid, value)
                    temporal = temporal.bind_value(leaf.source_name, value)
            elif target.source_name is not None:
                temporal = temporal.bind_value(target.source_name, member)
            inner_ctx = replace(ctx, temporal=temporal)
            if self.key is not None:
                return self.key.desugar(inner_ctx).and_then(
                    lambda key: self.element.desugar(inner_ctx).and_then(
                        lambda value: project(index + 1, (*projected, (key, value)))
                    )
                )
            return self.element.desugar(inner_ctx).and_then(
                lambda value: project(
                    index + 1,
                    (
                        *projected,
                        value.project_operation_receiver(
                            inner_ctx,
                            owner="ComprehensionSugar finite constructed element",
                        ),
                    ),
                )
            )

        # Outcome.and_then owns terminal/guarded propagation. Every constructed
        # outcome propagates unchanged through its own continuation law and is
        # TRANSPORTED by ``Projected`` -- which is not a non-success cause.
        return Projected(project(0, ()))

    def _desugar_filters(
        self, generator, filter_index, filters, iterable, index, resolved, ctx
    ):
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
            )
        return (
            generator.filters[filter_index]
            .desugar(ctx)
            .and_then(
                lambda guard: self._desugar_filters(
                    generator,
                    filter_index + 1,
                    (*filters, guard),
                    iterable,
                    index,
                    resolved,
                    ctx,
                )
            )
        )

    def _complete(self, resolved, element, key=None) -> Outcome:
        from sugar_lift_py_tests.floor.comprehension_value import ComprehensionValue
        from sugar_lift_py_tests.ir import (
            PrimitiveSort,
            _Lambda,
            _intern_term,
            ctor,
            make_var,
            subst_var_in_term,
        )
        from sugar_lift_py_tests.outcome import Complete

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
        term = ctor(
            self.kind,
            [
                outer_iterable.to_term(owner=owner),
                _intern_term(
                    _Lambda(outer_coordinate, PrimitiveSort("Value"), outer_body)
                ),
                ctor("python:loop.exhaustion", [], symbol_kind="coordinate"),
            ],
            symbol_kind="coordinate",
        )
        return Complete(ComprehensionValue(term))


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


def _bind_target(target: ComprehensionTargetSugar, element, body):
    """``body`` with every coordinate this target names replaced by what the
    symbolic ``element`` binds to it.

    A leaf binds the element whole. A pattern binds each position to its
    projection, recursively -- so a nested pattern reads a projection of a
    projection, exactly as the source nests.
    """
    from sugar_lift_py_tests.ir import subst_var_in_term

    if target.source_name is not None:
        return subst_var_in_term(body, target.source_name, element)
    coordinates = target.coordinates
    assert coordinates is not None
    arity = len(coordinates)
    for index, child in enumerate(coordinates):
        body = _bind_target(child, _projection(element, index, arity), body)
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
