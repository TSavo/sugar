"""Symbolic comprehensions as nested guarded iterator recurrences."""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
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


@dataclass(frozen=True)
class ComprehensionGeneratorSugar:
    target: ComprehensionTargetSugar
    binding_coordinate_cid: str
    iterable: Sugar
    filters: tuple[Sugar, ...]


@dataclass(frozen=True)
class ComprehensionSugar(Sugar):
    kind: str
    generators: tuple[ComprehensionGeneratorSugar, ...]
    element: Sugar
    key: Sugar | None = None
    site: object = dataclass_field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        prefix = "def A(xs):\n    return [x for x in xs]\n\n"
        return _call_pair(
            name="symbolic_list_comprehension",
            owner_sugar="ComprehensionSugar",
            truthful=prefix + "def test_a():\n    assert A([1]) == [1]\n",
            lying=prefix + "def test_a():\n    assert A([1]) == [2]\n",
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
        if (
            index == 0
            and len(self.generators) == 1
            and not generator.filters
            and self.key is None
        ):
            finite = self._finite_map(generator, iterable, ctx)
            if finite is not None:
                return finite
        return self._desugar_filters(
            generator, 0, (), iterable, index, resolved, ctx
        )

    def _finite_map(self, generator, iterable, ctx):
        from sugar_lift_py_tests.floor.comprehension_value import ComprehensionValue
        from sugar_lift_py_tests.floor.list_value import ListValue
        from sugar_lift_py_tests.floor.tuple_value import TupleValue
        from sugar_lift_py_tests.ir import (
            PrimitiveSort,
            _Lambda,
            _intern_term,
            ctor,
        )
        from sugar_lift_py_tests.outcome import Complete

        members = None
        if isinstance(iterable, (TupleValue, ListValue)):
            members = iterable.elements
        elif isinstance(iterable, ComprehensionValue) and iterable.finite_elements is not None:
            members = iterable.finite_elements
        if members is None:
            return None
        target = generator.target
        if target.source_name is None or target.coordinates is not None:
            # Destructured targets need unpack projection; stay symbolic.
            return None
        if ctx is None or not hasattr(ctx, "temporal"):
            return None
        from dataclasses import replace

        projected = []
        owner = str(self.site)
        for member in members:
            temporal = ctx.temporal.bind_value(
                generator.binding_coordinate_cid, member
            )
            if target.source_name is not None:
                temporal = temporal.bind_value(target.source_name, member)
            try:
                inner_ctx = replace(ctx, temporal=temporal)
            except TypeError:
                return None
            try:
                outcome = self.element.desugar(inner_ctx)
            except Exception:
                return None
            if not isinstance(outcome, Complete):
                return None
            projected.append(outcome.value)
        # Term carries iterable + projected-element coordinate; finite_elements
        # is the exact member testimony consumers (tuple construct) demand.
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
        return Complete(ComprehensionValue(term, finite_elements=tuple(projected)))

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
