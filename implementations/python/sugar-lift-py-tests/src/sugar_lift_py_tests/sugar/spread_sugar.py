"""Reference-shaped construction for Python starred/spread expressions."""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field, replace as _replace

from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import (
    ConstructedTermSugar,
    Sugar,
    require_constructed_term_sugar,
)
from sugar_lift_py_tests.sugar.witnesses import _call_return_pair


def _collect(sugars: tuple, ctx, done: tuple, finish):
    """Sequence spread operands by COMPOSING factors, never distributing them.

    #6309. The previous body chained ``and_then`` once per operand, and
    ``ExitSet.sequence`` appends every exit of the tail under every completed
    exit of the prefix. With k operands of m arms each that is m ** k
    materialized arms — and it is the arm POPULATION, not the per-merge cost,
    that walled ``pandas/core/generic.py``: an observed 1,317-wide arm set with
    a heavy tail (63% of normalize calls at one arm, three above 256), at guard
    nesting depth only 4.

    Each operand keeps its complete ExitSet as a FACTOR:

    - its completed face is factored to one arm carrying a guarded value
      (``ExitSet.factor_completed``), so k operands contribute k guarded values
      to ONE arm instead of one arm per tuple in the product;
    - its halted arms are lifted to the exit level under the prefix's completed
      guard, where one arm per operand per effect is already linear;
    - ``finish`` runs ONCE, on the factored value tuple, under the conjunction of
      the operands' completed guards.

    Both faces are retained in full. Nothing is pruned, no arm is capped, and
    success is never assumed: an operand whose every path halts ends the fold
    with only halted arms, which is exactly what the product said.

    ``finish`` is also invoked once rather than once per completed tuple. The old
    chain re-``desugar``ed each tail operand once per prefix arm; the fold walks
    the operands in the same source order, once each.
    """
    from sugar_lift_py_tests.outcome.exit_set import (
        ExitSet,
        Halted,
        _and_guards,
        _is_true,
        outcome_to_exitset,
        true_guard,
    )

    from sugar_lift_py_tests.caller_parameter_contract import merge_demands
    from sugar_lift_py_tests.floor.single_outcome_law import (
        pending_demand,
        rewrap_pending,
    )

    prefix_guard = true_guard()
    values = list(done)
    halted: list = []
    pending = None

    for sugar in sugars:
        # An operand that owes a parameter contract (`[*p[0]]`, `[*xs, p[0]]`
        # for a formal `p`) WRAPS its value rather than being one, and the exit
        # algebra has no arm for a value carried together with an undischarged
        # obligation. Hoisting is the same door `collection_sugar._reduce_into`
        # uses; without it this reached `outcome_to_exitset` and stopped on a
        # bare `TypeError` that named no owner and no fix (#6352).
        #
        # The operand hoists at `true_guard`: a spread display has no guard of
        # its own, and the prefix guard already rides on the arms below.
        entry, operand = pending_demand(sugar.desugar(ctx), true_guard())
        if entry is not None:
            pending = (
                entry
                if pending is None
                else _replace(
                    pending,
                    demands=merge_demands(pending.demands, entry.demands),
                )
            )
        factors = outcome_to_exitset(operand).factor_completed()
        completed = None
        for exit_ in factors.exits:
            if isinstance(exit_, Halted):
                halted.append(
                    Halted(
                        _and_guards(prefix_guard, exit_.guard),
                        exit_.effect,
                        exit_.state,
                    )
                )
            else:
                completed = exit_
        if completed is None:
            # Every path through this operand halts: there is no completed
            # continuation to hand to ``finish``, and the halted face is the
            # whole meaning. Any obligation already incurred rides on the halted
            # arms, which `outcome_to_exitset` conserved across the conversion.
            return rewrap_pending(
                pending,
                ExitSet(tuple(halted)).normalize().collapse(),
                owner="spread operand",
                blame=str(getattr(sugar, "site", sugar)),
            )
        prefix_guard = _and_guards(prefix_guard, completed.guard)
        values.append(completed.value)

    tail = outcome_to_exitset(finish(tuple(values)))
    if not _is_true(prefix_guard):
        tail = tail.guarded(prefix_guard)
    # ``collapse`` restores the linear ``Outcome`` for the unconditional case, so
    # a spread with no guarded operand desugars to exactly what it did before.
    built = ExitSet((*halted, *tail.exits)).normalize().collapse()
    # Re-attach every hoisted obligation to the finished display, or be loud.
    return rewrap_pending(pending, built, owner="spread display", blame=str(finish))


@dataclass(frozen=True)
class SpreadCollectionSugar(ConstructedTermSugar):
    """A display containing spread operands, as encoded by the reference lifter.

    ``elements`` is ``(wrapper-or-None, child-sugar)`` in source order.

    ConstructedTermSugar: a list/tuple/set display with ``*`` IS nested
    construction testimony — the same meaning ListSugar/TupleSugar/SetSugar
    admit without stars. Parent slots that require ConstructedTermSugar are
    truthful; this class was missing the base and ``to_term``. Promoting is
    not a convenience widen of the slot.
    """

    kind: str
    elements: tuple
    site: object = dataclass_field(compare=False)

    def __post_init__(self) -> None:
        for _wrapper, sugar in self.elements:
            require_constructed_term_sugar(
                sugar, owner="SpreadCollectionSugar.elements"
            )

    @classmethod
    def witnesses(cls):
        return _call_return_pair(
            name="spread_collection_len",
            owner_sugar="SpreadCollectionSugar",
            body="len([*z])",
            truthful="len(z)",
            lying="len(z) + 1",
        )

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor

        element_terms = []
        for wrapper, sugar in self.elements:
            term = require_constructed_term_sugar(
                sugar, owner="SpreadCollectionSugar.elements"
            ).to_term(owner=owner)
            if wrapper is not None:
                term = ctor(wrapper, [term])
            element_terms.append(term)
        return ctor(
            f"python:{self.kind}-construction",
            (
                self.occurrence_term(owner=owner),
                ctor(f"python:{self.kind}-elements", tuple(element_terms)),
            ),
            symbol_kind="coordinate",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        sugars = tuple(sugar for _, sugar in self.elements)

        def finish(values):
            from sugar_lift_py_tests.floor import SymbolicValue
            from sugar_lift_py_tests.ir import ctor

            owner = str(self.site)
            terms = []
            for (wrapper, _), value in zip(self.elements, values):
                term = value.to_term(owner=owner)
                terms.append(ctor(wrapper, [term]) if wrapper is not None else term)
            return Complete(SymbolicValue(ctor(f"python:{self.kind}", terms)))

        return _collect(sugars, ctx, (), finish)


@dataclass(frozen=True)
class SpreadDictSugar(ConstructedTermSugar):
    """A dict display whose entries include reference ``None``-key spreads.

    ConstructedTermSugar for the same reason as SpreadCollectionSugar: ``{**d}``
    is a constructed dict term, not an over-wide slot.
    """

    entries: tuple  # (key-sugar-or-None, value-sugar), source order
    site: object = dataclass_field(compare=False)

    def __post_init__(self) -> None:
        for key, value in self.entries:
            if key is not None:
                require_constructed_term_sugar(key, owner="SpreadDictSugar.entries.key")
            require_constructed_term_sugar(value, owner="SpreadDictSugar.entries.value")

    @classmethod
    def witnesses(cls):
        return _call_return_pair(
            name="spread_dict_len",
            owner_sugar="SpreadDictSugar",
            body="len({**z})",
            truthful="len(z)",
            lying="len(z) + 1",
        )

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor

        entry_terms = []
        for key, value in self.entries:
            value_term = require_constructed_term_sugar(
                value, owner="SpreadDictSugar.entries.value"
            ).to_term(owner=owner)
            if key is None:
                key_term = ctor("None", [])
            else:
                key_term = require_constructed_term_sugar(
                    key, owner="SpreadDictSugar.entries.key"
                ).to_term(owner=owner)
            entry_terms.append(ctor("python:dict-entry", (key_term, value_term)))
        return ctor(
            "python:dict-construction",
            (
                self.occurrence_term(owner=owner),
                ctor("python:dict-entries", tuple(entry_terms)),
            ),
            symbol_kind="coordinate",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        flattened = tuple(
            sugar
            for key, value in self.entries
            for sugar in ((value,) if key is None else (key, value))
        )

        def finish(values):
            from sugar_lift_py_tests.floor import SymbolicValue
            from sugar_lift_py_tests.ir import ctor

            owner = str(self.site)
            value_iter = iter(values)
            terms = []
            for key, _ in self.entries:
                if key is None:
                    key_term = ctor("None", [])
                    value_term = next(value_iter).to_term(owner=owner)
                else:
                    key_term = next(value_iter).to_term(owner=owner)
                    value_term = next(value_iter).to_term(owner=owner)
                terms.append(ctor("python:dict_entry", [key_term, value_term]))
            return Complete(SymbolicValue(ctor("python:dict", terms)))

        return _collect(flattened, ctx, (), finish)


@dataclass(frozen=True)
class SpreadCallSugar(ConstructedTermSugar):
    """A call containing ``*``/``**``, using the reference call vocabulary.

    When an authenticated source-visible callee frame is enrolled (class
    constructor / function body), typed ``**`` expansions project through that
    frame so the CallSiteValue carries the factory-built body. Opaque spreads
    without a frame keep the reference bodyless coordinate.
    """

    callee_name: str | None
    callee: Sugar | None
    arguments: tuple  # (role, optional-name, sugar), source order
    site: object = dataclass_field(compare=False)
    source_call_frame: object | None = dataclass_field(default=None, compare=False)

    @classmethod
    def witnesses(cls):
        return _call_return_pair(
            name="spread_call",
            owner_sugar="SpreadCallSugar",
            body="tuple((*z,))",
            truthful="tuple(z)",
            lying="tuple((*z, 0))",
        )

    def to_term(self, *, owner: str):
        """Project the same call coordinate used by completed spread reduction."""
        from sugar_lift_py_tests.ir import ctor, str_const

        if self.callee_name is not None:
            callee_term = str_const(self.callee_name)
        else:
            callee = require_constructed_term_sugar(
                self.callee, owner="SpreadCallSugar.callee"
            )
            callee_term = callee.to_term(owner=owner)
        arg_terms = []
        for role, name, sugar in self.arguments:
            term = require_constructed_term_sugar(
                sugar, owner="SpreadCallSugar.arguments"
            ).to_term(owner=owner)
            if role == "star":
                term = ctor("python:starred_arg", [term])
            elif role == "double-star":
                term = ctor("python:double_starred_kwarg", [term])
            elif role == "keyword":
                term = ctor("python:kwarg", [str_const(name), term])
            arg_terms.append(term)
        return ctor("python:call", [callee_term, *arg_terms])

    def desugar(self, ctx: object = None) -> Outcome:
        def after_callee(callee_value):
            sugars = tuple(sugar for _, _, sugar in self.arguments)
            return _collect(
                sugars,
                ctx,
                (),
                lambda values: self._finish(callee_value, values, ctx),
            )

        if self.callee is None:
            return after_callee(None)
        return self.callee.desugar(ctx).and_then(after_callee)

    def _finish(self, callee_value, values, ctx=None) -> Outcome:
        from sugar_lift_py_tests.floor import BuiltinSuperMethodValue

        if isinstance(callee_value, BuiltinSuperMethodValue):
            if any(role == "star" for role, _, _ in self.arguments):
                from sugar_source_tree.panic import SugarNotWritten

                raise SugarNotWritten(
                    owner="SpreadCallSugar._finish",
                    blame=self.site,
                    observed="starred positional actual to selected super method",
                    requested="an exact positional roster",
                    fix="project the starred operand exactly or keep the call loud",
                )
            positional = tuple(
                value
                for (role, _name, _), value in zip(self.arguments, values)
                if role == "positional"
            )
            keywords = tuple(
                (("**" if role == "double-star" else name), value)
                for (role, name, _), value in zip(self.arguments, values)
                if role in {"keyword", "double-star"}
            )
            return callee_value.receiver.call_method_value(
                callee_value.name,
                positional,
                owner="SpreadCallSugar._finish",
                blame=self.site,
                ctx=ctx,
                keywords=keywords,
            )
        from sugar_lift_py_tests.floor import CallSiteValue
        from sugar_lift_py_tests.ir import ctor, str_const

        owner = str(self.site)
        callee_term = (
            str_const(self.callee_name)
            if self.callee_name is not None
            else callee_value.to_term(owner=owner)
        )
        arg_terms = []
        for (role, name, _), value in zip(self.arguments, values):
            term = value.to_term(owner=owner)
            if role == "star":
                term = ctor("python:starred_arg", [term])
            elif role == "double-star":
                term = ctor("python:double_starred_kwarg", [term])
            elif role == "keyword":
                term = ctor("python:kwarg", [str_const(name), term])
            arg_terms.append(term)
        term = ctor("python:call", [callee_term, *arg_terms])

        framed = self._body_bearing_callsite(values, term, ctx)
        if framed is not None:
            return Complete(framed)

        return Complete(
            CallSiteValue(
                target_name=self.callee_name or "python:call",
                arg_values=tuple(values),
                parameters=(),
                term=term,
                body=None,
                site=self.site,
            )
        )

    def _body_bearing_callsite(self, values, term, ctx) -> object | None:
        """Project ``*``/``**`` actuals onto an enrolled source frame when lawful.

        Star operands stay bodyless (no typed vararg projection here). A
        double-star must be a constructed DictValue so bind_actuals can merge
        keys onto formals — the same law FunctionCallable uses for ``**``.
        """
        frame = self.source_call_frame
        if frame is None:
            return None
        if any(role == "star" for role, _, _ in self.arguments):
            return None
        from sugar_lift_py_tests.floor import CallSiteValue
        from sugar_lift_py_tests.source_call_frame import (
            SourceCallBindingGap,
            SourceVisibleCallFrameV1,
        )

        if not isinstance(frame, SourceVisibleCallFrameV1):
            return None
        positional: list = []
        keywords: list = []
        for (role, name, _), value in zip(self.arguments, values):
            if role == "positional":
                positional.append(value)
            elif role == "keyword":
                keywords.append((name, value))
            elif role == "double-star":
                keywords.append(("**", value))
            else:
                return None
        try:
            bound = frame.bind_actuals(tuple(positional), tuple(keywords), ctx)
        except SourceCallBindingGap:
            return None
        source_body = frame.body
        owner = getattr(frame, "owner", None)
        if owner is not None and hasattr(owner, "source_visible_constructor_frame"):
            source_body = owner.source_visible_constructor_frame().body
        return CallSiteValue(
            target_name=self.callee_name or "python:call",
            arg_values=bound.actuals,
            parameters=frame.parameters,
            term=term,
            body=source_body,
            site=self.site,
            source_call_frame_cid=frame.frame_cid,
            formal_coordinate_cids=tuple(item.cid for item in frame.formal_coordinates),
            bound_source_actuals=bound,
        )
