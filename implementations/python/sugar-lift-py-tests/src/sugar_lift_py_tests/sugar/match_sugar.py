"""`match subject: case P [if g]: body ...` -- structural pattern matching.

A match is sequential, first-case-wins: case i runs exactly when the subject
matches P_i, matched no earlier *selected* case, and its guard (if any) is true.

Subject evaluates ONCE. Pattern captures bind the subject for that case's
guard and body only:

  - tentative bind for guard evaluation
  - false guard rolls the tentative bind back before the next case
  - true guard commits the bind for the body under the selection formula
  - guard halt bypasses later cases under the matched-and-reached-guard path,
    carrying the halt's pre-effect state (Halted.state preserved)

ExitSet law (advisor #6716 rework):

  - every pattern / guard / body face is restricted by ``not_prev`` (or a
    tighter selection); later-case outcomes never fire unguarded
  - Halted faces keep ``effect`` and ``state``; guards compose via ExitSet.guarded
  - multi-face guard ExitSets are fanned per face (no completed[0] collapse)
  - equality testimony routes through Floor ``equals`` + ``predicate_formula``
    (value.truth), never nested getattr formula probes
  - a completed pattern / equality / guard face feeds the selection formula
    AND what it owes: every arm past it is sequenced after it (``_after``),
    so its ``owed`` reaches the case body's result and every later arm (#7757)
  - a match with no catch-all case has a fall-through arm: completed under
    the negation of every case's selection, owing what every failed
    equality, pattern and guard owed (#7757)
  - each case's body arms and the fall-through arm are the match's routes
    (``route_site``, minted by ``Match.substitute`` when a binding after the
    match joins over them): every completed arm of a route confirms the
    match's route slots -- its own true, every other false -- and grounds
    them for the code after it, as a ``try``'s routed outcome does
    (``try_sugar._route_confirmation``, ``_ground_route_on_faces``)

Value patterns and catch-all / bare capture are value alternatives. Every
other pattern is structural (``match_pattern``): a selection over the subject
(its sequence / mapping / class test, its length, its keys, each
sub-pattern's test of the subject's projection) through the floor's own
operations, and the per-case capture keys (``Match.substitute``) bound to the
subject's projections.  A projection's halt (``__getitem__``, ``__len__``, an
attribute or ``__match_args__`` lookup on a source class) stays an arm; a
test the floor does not decide on an opaque subject is refused by name
(``undecided``), never guessed matched or not.  A case's guard is evaluated
after its captures bind and joins its selection.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_return_pair


@dataclass(frozen=True)
class MatchCaseSpec:
    """One case: value-pattern alternatives or a structural pattern, optional
    guard, body, capture.

    ``alternatives`` is the tuple of literal sugars the subject may equal --
    ``(1,)`` for `case 1:`, ``(1, 2)`` for `case 1 | 2:`, and the EMPTY tuple
    for a catch-all (`case _:` or bare capture `case x:`, which always match)
    and for a structural case.

    ``pattern`` is the structural pattern spec (``match_pattern``) for every
    other pattern (`case [a, *rest]:`, `case {"k": v}:`, `case Point(x=0):`,
    `case P as p:`); None for a value-alternatives case.

    ``guard`` is the optional `if <expr>` sugar (None when absent).

    ``capture_name`` is the bare capture name for `case x:` / `case x if g:`;
    None for wildcards and pure value patterns. The capture is the subject
    FloorValue at this match -- not a free-name spelling lookup.
    """

    alternatives: tuple  # literal sugars; empty = catch-all / bare capture
    body: tuple
    guard: object | None = None  # Sugar | None
    capture_name: str | None = None
    pattern: object | None = None  # structural pattern spec | None


# -- structural patterns ------------------------------------------------------


@dataclass(frozen=True)
class ValuePatternSpec:
    """A value pattern (`1`, `Color.RED`) nested in a structural one: the
    subject's projection equals the value (``equals``)."""

    value: Sugar


@dataclass(frozen=True)
class SingletonPatternSpec:
    """`None` / `True` / `False` nested in a structural pattern: the
    projection is the singleton (``is_identical``)."""

    value: Sugar


@dataclass(frozen=True)
class CapturePatternSpec:
    """`P as name`, a capture `name`, or the wildcard `_`: ``pattern`` (None
    for a capture or the wildcard) then the value bound under ``key`` (None
    for the wildcard)."""

    pattern: object | None
    key: str | None


@dataclass(frozen=True)
class OrPatternSpec:
    """`P1 | P2 | ...`: the first alternative that matches."""

    alternatives: tuple


@dataclass(frozen=True)
class SequencePatternSpec:
    """`[P1, ..., *rest, ..., Pn]`: ``before`` the star, the star (when
    ``has_star``; its capture ``star_key``, None for `*_`), ``after`` it."""

    before: tuple
    has_star: bool = False
    star_key: str | None = None
    after: tuple = ()


@dataclass(frozen=True)
class MappingPatternSpec:
    """`{K1: P1, ..., **rest}`: each key's value matches its pattern; the
    other items bind under ``rest_key`` (None without `**rest`)."""

    keys: tuple
    patterns: tuple
    rest_key: str | None = None


@dataclass(frozen=True)
class ClassPatternSpec:
    """`C(P1, ..., attr=P)`: the subject is an instance of ``cls``; each
    positional pattern matches the attribute ``__match_args__`` names at its
    position, each keyword pattern the attribute it names."""

    cls: Sugar
    positional: tuple
    keywords: tuple  # ((attr, spec), ...)


@dataclass(frozen=True)
class _Matched:
    """One completed face of a pattern test: whether the subject matched
    there, and what its captures bound (``((key, value), ...)``)."""

    matched: bool
    binds: tuple = ()


def _outcome(matched: bool, binds=()):
    return ExitSet.completed(_Matched(matched, tuple(binds) if matched else ()))


def _decide(formula, site):
    """A test's truth as matched / not-matched faces: one face when the floor
    decided it, the two faces of its split (minted here, the test owning it)
    when the formula is symbolic."""
    from sugar_lift_py_tests.ir import not_
    from sugar_lift_py_tests.outcome.exit_set import _is_false, _is_true, partition

    if _is_true(formula):
        return _outcome(True)
    if _is_false(formula):
        return _outcome(False)
    yes, no = partition(("MatchPattern", site, formula))
    return _outcome(True).guarded(formula, yes).union(
        _outcome(False).guarded(not_(formula), no)
    )


def _tested(outcome, site):
    """A floor test's outcome (``equals``, ``contains``, a type test): each
    completed truth value decided as matched / not matched; a halt stays."""
    from sugar_lift_py_tests.outcome.exit_set import _require_exit_set

    return _require_exit_set(outcome, owner="MatchSugar.pattern").sequence(
        lambda value: _decide(_formula_from_floor_value(value, site), site)
    )


def _projected(outcome):
    from sugar_lift_py_tests.outcome.exit_set import _require_exit_set

    return _require_exit_set(outcome, owner="MatchSugar.pattern")


def _each(outcome, step):
    """``step`` on each completed arm of ``outcome``.  A projection that waits
    on its caller's actual (a ``subscript`` carrier) enrolls ``step`` to run
    once it discharges; an ``ExitSet`` sequences it (its halts stand)."""
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )

    if isinstance(outcome, NativeOperationExitCarrierV1):
        return outcome.and_then(step)
    return _projected(outcome).sequence(step)


def _then_match(outcome, step):
    """``outcome``'s matched faces continue into ``step()`` (its binds
    prefixed to what that binds); a face that did not match stands."""

    def go(matched):
        if not matched.matched:
            return ExitSet.completed(matched)
        return _each(step(), lambda following: _joined(matched, following))

    return _each(outcome, go)


def _joined(first, following):
    """``following`` after the matched ``first``: both their binds when it
    matched too, else the miss."""
    if not following.matched:
        return ExitSet.completed(following)
    return ExitSet.completed(_Matched(True, (*first.binds, *following.binds)))


def _undecided(site, observed: str):
    """A pattern test the floor does not decide on this subject: refused by
    name, never guessed matched or not."""
    from sugar_source_tree.panic import SugarNotWritten

    raise SugarNotWritten(
        owner="MatchSugar.pattern",
        blame=site,
        observed=f"undecided {observed}",
        requested="source testimony deciding the pattern test on this subject",
        fix=(
            "decide the subject's runtime type and protocol before the "
            "pattern tests it; never guess a match or a miss"
        ),
    )


def match_pattern(spec, value, site, ctx):
    """Test ``value`` against the structural pattern ``spec``: an ``ExitSet``
    whose completed faces are ``_Matched`` (the selection is their guards'
    join where they matched) and whose halts are the projections' halts."""
    if isinstance(spec, ValuePatternSpec):
        return _projected(spec.value.desugar(ctx)).sequence(
            lambda literal: _tested(value.equals(literal, site, ctx), site)
        )
    if isinstance(spec, SingletonPatternSpec):
        return _projected(spec.value.desugar(ctx)).sequence(
            lambda singleton: _tested(value.is_identical(singleton, site), site)
        )
    if isinstance(spec, CapturePatternSpec):
        inner = (
            _outcome(True)
            if spec.pattern is None
            else match_pattern(spec.pattern, value, site, ctx)
        )
        if spec.key is None:
            return inner
        return _then_match(inner, lambda: _outcome(True, ((spec.key, value),)))
    if isinstance(spec, OrPatternSpec):
        return _first_match(spec.alternatives, value, site, ctx)
    if isinstance(spec, SequencePatternSpec):
        return _match_sequence(spec, value, site, ctx)
    if isinstance(spec, MappingPatternSpec):
        return _match_mapping(spec, value, site, ctx)
    if isinstance(spec, ClassPatternSpec):
        return _match_class(spec, value, site, ctx)
    raise TypeError(f"match pattern spec not lifted: {type(spec).__name__}")


def _first_match(alternatives, value, site, ctx):
    first = match_pattern(alternatives[0], value, site, ctx)
    if len(alternatives) == 1:
        return first

    def otherwise(matched):
        if matched.matched:
            return ExitSet.completed(matched)
        return _first_match(alternatives[1:], value, site, ctx)

    return _each(first, otherwise)


def _decided_kind(value, yes: tuple, no: tuple, what: str, site) -> bool:
    """Whether the floor decides ``value`` is a ``what`` (a sequence, a
    mapping, for a pattern): exactly its decided floor types answer."""
    if type(value) in yes:
        return True
    if type(value) in no:
        return False
    _undecided(site, f"whether {type(value).__name__} is a {what}")


def _scalar_floors() -> tuple:
    from sugar_lift_py_tests.floor import (
        BytesValue,
        NoneValue,
        SetValue,
        StringValue,
        TermValue,
    )

    return (BytesValue, NoneValue, SetValue, StringValue, TermValue)


def _match_sequence(spec, value, site, ctx):
    """A sequence pattern: the subject is a sequence (never ``str`` /
    ``bytes``), of the length the pattern takes, and each sub-pattern
    matches the item at its position; the star binds the items between as a
    ``list``."""
    from sugar_lift_py_tests.floor import DictValue, ListValue, TupleValue

    if not _decided_kind(
        value,
        (TupleValue, ListValue),
        (DictValue, *_scalar_floors()),
        "sequence",
        site,
    ):
        return _outcome(False)
    return _projected(value.length(site)).sequence(
        lambda length: _sequence_of_length(spec, value, length, site, ctx)
    )


def _sequence_of_length(spec, value, length, site, ctx):
    """The pattern over the subject's ``length``: a ground count decides
    it; any other length is the ``call:len`` coordinate (a list whose
    contents are not current, ``object_identity.contents_current``), split
    on like any undecided length -- the pattern's length test is the split's
    formula (``_decide``), and each arm runs under its guard."""
    from sugar_lift_py_tests.floor import TermValue

    if type(length) is TermValue and type(length.value) is int:
        return _sequence_of_ground_length(spec, value, length.value, site, ctx)
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue

    if not (type(length) is CallSiteValue and length.target_name == "len"):
        _undecided(site, f"sequence length {type(length).__name__}")
    from sugar_lift_py_tests.ir import eq, gte

    owner = "MatchSugar.pattern"
    fixed = len(spec.before) + len(spec.after)
    test = gte if spec.has_star else eq
    formula = test(
        length.to_term(owner=owner), TermValue(fixed).to_term(owner=owner)
    )
    return _then_match(
        _decide(formula, site),
        lambda: _sequence_of_undecided_length(spec, value, site, ctx),
    )


def _sequence_of_undecided_length(spec, value, site, ctx):
    """The items of a subject of a length the pattern takes but the floor
    does not count: each before the star at its index, each after it at
    its index from the end, and the star's capture the slice between."""
    after = len(spec.after)
    positions = (
        *((index, sub) for index, sub in enumerate(spec.before)),
        *((index - after, sub) for index, sub in enumerate(spec.after)),
    )
    matched = _match_items(value, positions, site, ctx)
    if not spec.has_star or spec.star_key is None:
        return matched
    from sugar_lift_py_tests.floor import TermValue
    from sugar_lift_py_tests.floor.slice_value import SliceValue

    between = SliceValue(
        TermValue(len(spec.before)), TermValue(-after) if after else None, None
    )
    return _then_match(
        matched,
        lambda: _each(
            _read(value, between, site, ctx),
            lambda items: _outcome(True, ((spec.star_key, items),)),
        ),
    )


def _sequence_of_ground_length(spec, value, length, site, ctx):
    fixed = len(spec.before) + len(spec.after)
    if (length < fixed) if spec.has_star else (length != fixed):
        return _outcome(False)
    start = len(spec.before)
    stop = length - len(spec.after)
    positions = (
        *((index, sub) for index, sub in enumerate(spec.before)),
        *((stop + index, sub) for index, sub in enumerate(spec.after)),
    )
    matched = _match_items(value, positions, site, ctx)
    if not spec.has_star or spec.star_key is None:
        return matched
    return _then_match(
        matched, lambda: _star_items(value, spec.star_key, start, stop, site, ctx)
    )


def _read(value, key, site, ctx):
    """``value[key]`` as the pattern reads it: through the one subscript door
    a source ``value[key]`` takes (``discharge_subscript``), so a parameter in
    either operand defers to the caller as it does there (the ``subscript``
    carrier, consumed through ``_each``)."""
    from sugar_lift_py_tests.operations.subscript_operation import (
        discharge_subscript,
    )

    return discharge_subscript(value, key, site, ctx, owner="MatchSugar.pattern")


def _item(value, index, site, ctx):
    from sugar_lift_py_tests.floor import TermValue

    return _read(value, TermValue(index), site, ctx)


def _match_items(value, positions, site, ctx):
    """Each ``(index, spec)``: the item at ``index`` matches ``spec``, in
    order, stopping at the first that does not."""
    if not positions:
        return _outcome(True)
    (index, sub), rest = positions[0], positions[1:]
    first = _each(
        _item(value, index, site, ctx),
        lambda item: match_pattern(sub, item, site, ctx),
    )
    return _then_match(first, lambda: _match_items(value, rest, site, ctx))


def _star_items(value, key, start, stop, site, ctx, collected=()):
    """The items ``start`` to ``stop`` of the subject, bound under ``key`` as
    a ``list`` (what a star captures from any sequence): a new list made
    here, current only when the subject's contents are, else named by its
    derivation (``object_identity.made_from``)."""
    from sugar_lift_py_tests.floor import ListValue
    from sugar_lift_py_tests.floor.object_identity import made_from

    if start >= stop:
        captured = ListValue(tuple(collected), **made_from("[*]", site, value))
        return _outcome(True, ((key, captured),))
    return _each(
        _item(value, start, site, ctx),
        lambda item: _star_items(
            value, key, start + 1, stop, site, ctx, (*collected, item)
        ),
    )


def _match_mapping(spec, value, site, ctx):
    """A mapping pattern: the subject is a mapping, holds each key, and the
    value at each key matches its pattern; ``**rest`` binds a ``dict`` of
    the other items."""
    from sugar_lift_py_tests.floor import DictValue, ListValue, TupleValue

    if not _decided_kind(
        value,
        (DictValue,),
        (TupleValue, ListValue, *_scalar_floors()),
        "mapping",
        site,
    ):
        return _outcome(False)
    return _keys(spec.keys, ctx).sequence(
        lambda keys: _then_match(
            _match_entries(value, tuple(zip(keys, spec.patterns)), site, ctx),
            lambda: _mapping_rest(value, keys, spec.rest_key, site),
        )
    )


def _keys(sugars, ctx, collected=()):
    """Each key sugar's value, in order."""
    if not sugars:
        return ExitSet.completed(tuple(collected))
    return _projected(sugars[0].desugar(ctx)).sequence(
        lambda key: _keys(sugars[1:], ctx, (*collected, key))
    )


def _match_entries(value, entries, site, ctx):
    if not entries:
        return _outcome(True)
    (key, sub), rest = entries[0], entries[1:]
    held = _tested(value.contains(key, site), site)
    first = _then_match(
        held,
        lambda: _each(
            _read(value, key, site, ctx),
            lambda item: match_pattern(sub, item, site, ctx),
        ),
    )
    return _then_match(first, lambda: _match_entries(value, rest, site, ctx))


def _mapping_rest(value, keys, rest_key, site):
    """``**rest``: a ``dict`` of the subject's items whose key is none of the
    pattern's keys -- each decided distinct from them, or refused.  It is a
    new dict made at the match, current only when the subject's entries are
    (``object_identity.made_from``): from entries that are not, its
    contents are not its contents either, no read takes them, and its
    derivation names it."""
    from sugar_lift_py_tests.floor import DictValue
    from sugar_lift_py_tests.floor.dict_value import _key_position
    from sugar_lift_py_tests.floor.object_identity import made_from

    if rest_key is None:
        return _outcome(True)
    taken = tuple((key, None) for key in keys)
    kept = []
    for key, item in value.entries:
        found = _key_position(taken, key)
        if found is None:
            _undecided(site, f"whether {type(key).__name__} key is a pattern key")
        if found < 0:
            kept.append((key, item))
    rest = DictValue(tuple(kept), **made_from("{**}", site, value))
    return _outcome(True, ((rest_key, rest),))


def _match_class(spec, value, site, ctx):
    """A class pattern: the subject is an instance of the class, and each
    sub-pattern matches the attribute it names (``__match_args__`` names
    the positional ones)."""
    return _projected(spec.cls.desugar(ctx)).sequence(
        lambda cls: _then_match(
            _instance_of(cls, value, site),
            lambda: _class_members(spec, cls, value, site, ctx),
        )
    )


def _instance_of(cls, value, site):
    """``isinstance(value, cls)``: a source class decides an instance it
    defined (CPython's exact-type test); every other class answers through
    its own type test (``test_python_type``)."""
    from sugar_lift_py_tests.floor.class_definition_value import (
        ClassDefinitionValue,
    )
    from sugar_lift_py_tests.floor.object_value import ObjectValue

    if isinstance(cls, ClassDefinitionValue):
        defining = (
            getattr(value, "defining_class", None)
            if isinstance(value, ObjectValue)
            else None
        )
        if getattr(defining, "class_definition_cid", None) == cls.class_definition_cid:
            return _outcome(True)
        _undecided(site, f"isinstance({type(value).__name__}, {cls.class_name})")
    return _tested(cls.test_python_type(value, site), site)


def _class_members(spec, cls, value, site, ctx):
    if not spec.positional:
        return _match_attributes(value, spec.keywords, site, ctx)
    return _projected(cls.attribute("__match_args__", site, ctx)).sequence(
        lambda names: _positional_members(spec, names, value, site, ctx)
    )


def _positional_members(spec, names, value, site, ctx):
    """``__match_args__`` names the attribute of each positional pattern: a
    ``tuple`` of ``str`` long enough, naming no attribute twice; else
    ``TypeError``, as CPython raises."""
    from sugar_lift_py_tests.floor import StringValue, TupleValue
    from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

    if type(names) is not TupleValue or not all(
        type(name) is StringValue for name in names.elements
    ):
        _undecided(site, f"__match_args__ {type(names).__name__}")
    attrs = tuple(name.value for name in names.elements[: len(spec.positional)])
    taken = (*attrs, *(attr for attr, _sub in spec.keywords))
    if len(spec.positional) > len(names.elements) or len(set(taken)) != len(taken):
        return ground_exceptional_exit(
            exception_name="TypeError", site=site, owner="MatchSugar.pattern"
        )
    return _match_attributes(
        value, (*zip(attrs, spec.positional), *spec.keywords), site, ctx
    )


def _match_attributes(value, members, site, ctx):
    if not members:
        return _outcome(True)
    (attr, sub), rest = members[0], members[1:]
    first = _projected(value.attribute(attr, site, ctx)).sequence(
        lambda member: match_pattern(sub, member, site, ctx),
        consume=lambda halt: _missing_attribute(halt, attr, site),
    )
    return _then_match(first, lambda: _match_attributes(value, rest, site, ctx))


def _missing_attribute(halt, attr, site):
    """A class pattern's attribute lookup that raised ``AttributeError``
    does not match (CPython); any other raise leaves the match.  A raise
    whose type is not decided against ``AttributeError`` is refused by name."""
    from sugar_lift_py_tests.effect.raise_effect import (
        RaiseEffect,
        UndeterminedRaiseEffect,
    )
    from sugar_lift_py_tests.floor.ground_exit import _builtin_exception_identity

    effect = halt.effect
    if isinstance(effect, RaiseEffect):
        attribute_error, _ = _builtin_exception_identity("AttributeError")
        lineage = (
            effect.exception_type_coordinate,
            *(effect.exception_type_mro or ()),
        )
        if attribute_error in lineage:
            return _outcome(False)
        if effect.exception_type_mro is not None:
            return None
        _undecided(site, f"whether the raise reading .{attr} is an AttributeError")
    if isinstance(effect, UndeterminedRaiseEffect):
        _undecided(site, f"whether the raise reading .{attr} is an AttributeError")
    return None


def _bind_captures(ctx, binds):
    """The case's context with each capture's value bound under its key,
    qualified where the match runs (``evaluation_here``)."""
    if not binds:
        return ctx
    from sugar_lift_py_tests.context.reduce_context import ReduceContext
    from sugar_lift_py_tests.sugar.evaluation_ref_sugar import evaluation_here
    from sugar_lift_py_tests.temporal.context_helpers import bind_temporal

    bound = ctx if ctx is not None else ReduceContext.root(owner="MatchSugar.capture")
    for key, value in binds:
        bound = bind_temporal(
            bound,
            evaluation_here(key),
            value,
            owner="MatchSugar.capture",
            blame=f"match capture {key}",
        )
    return bound


def _not_earlier(earlier: list):
    from sugar_lift_py_tests.ir import and_, not_
    from sugar_lift_py_tests.outcome.exit_set import true_guard

    if not earlier:
        return true_guard()
    parts = tuple(not_(f) for f in earlier)
    return and_(parts) if len(parts) > 1 else parts[0]


def _and_parts(*parts):
    from sugar_lift_py_tests.ir import and_
    from sugar_lift_py_tests.outcome.exit_set import true_guard

    flat = [p for p in parts if p is not None and p != true_guard()]
    if not flat:
        return true_guard()
    if len(flat) == 1:
        return flat[0]
    return and_(tuple(flat))


def _tentative_capture_ctx(ctx, capture_name: str | None, subject):
    """Bind capture_name → subject for this case only; caller discards after."""
    if capture_name is None:
        return ctx
    from sugar_lift_py_tests.context.reduce_context import ReduceContext
    from sugar_lift_py_tests.temporal.context_helpers import bind_temporal

    base = ctx if ctx is not None else ReduceContext.root(owner="MatchSugar.capture")
    return bind_temporal(
        base,
        capture_name,
        subject,
        owner="MatchSugar.tentative_capture",
        blame=f"match capture {capture_name!r}",
    )


def _debt(owed=()):
    """One completed match step under truth owing ``owed``.

    The match's PATH is one such arm: what the patterns, equalities and
    guards run so far incurred. It grows only by composition --
    ``path.sequence(lambda _: step)`` for a step that ran after it, and
    ``ExitSet.union`` for sibling faces of one step, which merges them into
    one arm owing every sibling's debt -- never by unioning debts by hand.
    """
    return ExitSet.completed(None, owed=owed)


def _then(path, step):
    """``path`` followed by ``step``: one arm owing both, in that order."""
    return path.sequence(lambda _reached: step)


def _after(guard, path, exits):
    """``exits`` sequenced after the match ``path`` that reached them (#7757).

    ``path`` is the one-arm match step (``_debt``) owing what the patterns,
    equalities and guards on the path into these arms incurred, restricted
    here to ``guard``. ``ExitSet.sequence`` conjoins ``guard`` onto every arm
    and carries the debt onto every arm, completed and halted alike, so
    nothing a completed equality or guard face owed is dropped by being read
    as a formula only. Halted.state and partition faces ride through
    unchanged.
    """
    reached = path if guard is None else path.guarded(guard)
    return reached.sequence(lambda _reached: exits)


def _halted_face(face, prefix_guard):
    """Preserve a Halted face (effect, state, faces, owed) under an outer
    prefix: the arm restricted to ``prefix_guard`` (``ExitSet.guarded``)."""
    return ExitSet((face,)).guarded(prefix_guard)


def _formula_from_floor_value(value, site):
    """Equality / guard truth via Floor surface (value.truth), not getattr probes."""
    from sugar_lift_py_tests.sugar.if_sugar import predicate_formula

    return predicate_formula(value, site)


def _exceptional_faces_only(exits, prefix_guard):
    """Propagate only non-Completed control faces under ``prefix_guard``.

    Completed faces feed matching / guard truth; they must not also escape as
    completed Match outcomes by wholesale ExitSet union.
    """
    return ExitSet(exits.halts()).guarded(prefix_guard)


def _pattern_match_formula_and_side_exits(subject, alternatives, site, not_prev, ctx):
    """Build match formula; exceptional alt/equality faces ride under not_prev.

    Returns ``(match_formula | None, side_exits: ExitSet, pattern_path)``.
    Completed faces of alternative/equality ExitSets feed matching as
    formulas, and what they OWE is returned as ``pattern_path`` (one
    ``_debt`` arm) for the caller to sequence every arm past this pattern
    after (#7757). They are never unioned wholesale into the Match outcome.
    An equality halt is sequenced after the alternative that completed into
    it, so it owes what that alternative (and every alternative tried before
    it) owed.
    """
    from sugar_lift_py_tests.ir import or_
    from sugar_lift_py_tests.outcome import Completed
    from sugar_lift_py_tests.outcome.exit_set import true_guard
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        halt_record,
        halts_recorded,
    )

    if not alternatives:
        return true_guard(), ExitSet(()), _debt()

    # An alternative's or an equality's halt is before any case body ran:
    # nothing of the match bound before it, so it carries the record where
    # it halted (``halt_record``), onto which the block composition splices
    # what ran before the ``match``.
    record = halt_record(ctx)
    alts = []
    side = ExitSet(())
    path = _debt()
    for alt in alternatives:
        alt_out = alt.desugar(ctx)
        if not isinstance(alt_out, ExitSet):
            raise NotImplementedError(
                f"match alternative outcome not lifted: {type(alt_out).__name__}"
            )
        alt_out = halts_recorded(alt_out, record)
        # What the alternatives tried before this one incurred.
        before = path
        # Exceptional/control faces only — not Completed outcomes.
        side = side.union(
            _after(None, before, _exceptional_faces_only(alt_out, not_prev))
        )
        for face in alt_out.exits:
            if not isinstance(face, Completed):
                continue
            # Matching under not_prev ∧ alt-face polarity (an unguarded face
            # adds nothing to either).
            eq_prefix = _and_parts(not_prev, face.guard)
            eq_out = subject.equals(face.value, site, ctx)
            eq_side, formula, eq_path = _equality_outcome_under(
                eq_out, eq_prefix, site, record
            )
            # The equality ran after this alternative's face completed.
            reached_eq = _then(before, _debt(face.owed))
            side = side.union(_after(None, reached_eq, eq_side))
            path = _then(_then(path, _debt(face.owed)), eq_path)
            if formula is not None:
                # When multi-face equality, formula is OR of (face.guard ∧ truth).
                alts.append(_and_parts(face.guard, formula))

    if not alts:
        return None, side, path
    match_formula = or_(tuple(alts)) if len(alts) > 1 else alts[0]
    return match_formula, side, path


def _equality_outcome_under(eq_out, not_prev, site, record):
    """Process subject.equals under not_prev; return (side, formula|None, path).

    ExitSet Completed faces contribute ``face.guard ∧ truth(face.value)`` to
    the match formula, and their ``owed`` to the returned ``path`` (#7757):
    the equality ran on every path past it, so the caller sequences every
    such arm after it. The completed faces are siblings of one comparison,
    so ``path`` is their join (``ExitSet.union`` of one ``_debt`` arm each):
    one arm owing every face's debt. Non-completed faces propagate
    separately (owed preserved), each carrying ``record``, the record where
    the equality halted, when it offers none of its own
    (``halts_recorded``). Never wholesale-unions Completed equality faces
    into side.
    """
    from sugar_lift_py_tests.ir import or_
    from sugar_lift_py_tests.outcome import Completed, Halted
    from sugar_lift_py_tests.sugar.function_universe_sugar import halts_recorded

    if not isinstance(eq_out, ExitSet):
        raise NotImplementedError(
            f"match equality outcome not lifted: {type(eq_out).__name__}"
        )
    eq_out = halts_recorded(eq_out, record)
    side = ExitSet(())
    formulas = []
    path = _debt()
    for face in eq_out.exits:
        if isinstance(face, Halted):
            side = side.union(_halted_face(face, not_prev))
            continue
        if isinstance(face, Completed):
            truth = _formula_from_floor_value(face.value, site)
            formulas.append(_and_parts(face.guard, truth))
            path = path.union(_debt(face.owed))
            continue
        raise NotImplementedError(
            f"match equality face not lifted: {type(face).__name__}"
        )
    if not formulas:
        return side, None, path
    formula = or_(tuple(formulas)) if len(formulas) > 1 else formulas[0]
    return side, formula, path


def _guard_faces_under(
    guard_out, reached, site, body, body_ctx, match_formula, path, routed
):
    """Fan a guard outcome into ExitSets under ``reached``.

    Returns ``(parts, earlier_bits, guard_path)``.  ``routed`` turns the
    body's exits into the case's route (``MatchSugar._routed``).

    ``path`` is the match step owing what the path into this guard incurred
    (patterns and equalities of this and every earlier case); every part is
    sequenced after it. Per Completed face: body sequenced under ``reached ∧
    face.guard ∧ truth``, after ``path`` and then the face. Per Halted face:
    preserve Halted under ``reached ∧ face.guard``; mark only ``match_formula
    ∧ face.guard`` consumed (not the whole match path). ``guard_path`` is the
    join of every completed face's debt (``ExitSet.union``), which the paths
    past a false guard carry too (#7757).
    """
    from sugar_lift_py_tests.outcome import Completed, Halted
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        halt_record,
        halts_recorded,
        reduce_block_to_exitset,
    )

    parts: list = []
    earlier_bits: list = []
    guard_path = _debt()

    if not isinstance(guard_out, ExitSet):
        raise NotImplementedError(
            f"match guard outcome not lifted: {type(guard_out).__name__}"
        )
    # The guard runs where the case's captures are bound (``body_ctx`` binds
    # what the guard's context bound): a guard halt carries the record of
    # that context, before the case body ran (``halt_record``).
    guard_out = halts_recorded(guard_out, halt_record(body_ctx))
    for face in guard_out.exits:
        if isinstance(face, Halted):
            parts.append(_after(None, path, _halted_face(face, reached)))
            # Only this polarity of the match is consumed by the halt.
            earlier_bits.append(_and_parts(match_formula, face.guard))
            continue
        if isinstance(face, Completed):
            truth = _formula_from_floor_value(face.value, site)
            body_exits = routed(reduce_block_to_exitset(body, body_ctx))
            # The body runs after ``path`` and then the guard face itself: its
            # guard, its partition testimony and what it owes ride onto every
            # body arm.
            parts.append(
                _after(
                    _and_parts(reached, truth),
                    _then(path, ExitSet((face,))),
                    body_exits,
                )
            )
            earlier_bits.append(_and_parts(match_formula, face.guard, truth))
            guard_path = guard_path.union(_debt(face.owed))
            continue
        raise NotImplementedError(
            f"match guard ExitSet face not lifted: {type(face).__name__}"
        )
    return parts, earlier_bits, guard_path


@dataclass(frozen=True)
class MatchSugar(Sugar):
    subject: Sugar
    cases: tuple  # MatchCaseSpec, in source order
    site: object = dataclass_field(compare=False)
    # The address of the match's route slots (``match_route_site``), when a
    # binding after the match joins over them (``Match.substitute``); None
    # when nothing reads them.
    route_site: object = dataclass_field(compare=False, default=None)

    @classmethod
    def witnesses(cls):
        return _call_return_pair(
            name="match_value_return",
            owner_sugar="MatchSugar",
            body="1 if z == 1 else 0",
            truthful="1",
            lying="2",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        from sugar_lift_py_tests.ir import or_
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            halt_record,
            halts_recorded,
            plain_completed_value,
            reduce_block_to_exitset,
        )

        subject_out = self.subject.desugar(ctx)
        if not isinstance(subject_out, ExitSet):
            raise NotImplementedError(
                f"match subject outcome not lifted: {type(subject_out).__name__}"
            )
        # A halt of the subject is at the head of the ``match``, before any
        # case: it carries the record of where it halted (``halts_recorded``).
        subject_out = halts_recorded(subject_out, halt_record(ctx))
        if subject_out.exits and subject_out.halts() == subject_out.exits:
            # Subject halt is before any case; no later case can run.
            return subject_out
        subject = plain_completed_value(subject_out)
        if subject is None:
            # Multi-face subject: the whole match runs beneath each completed
            # face, over a one-shot sugar presenting that face's value; its
            # guard, its partition testimony and what it owes ride onto every
            # nested arm. A halted subject face stands.
            parts = subject_out.sequence(
                lambda value: MatchSugar(
                    _CompleteValueSugar(value, self.site),
                    self.cases,
                    self.site,
                    self.route_site,
                ).desugar(ctx)
            )
            if parts.exits:
                return parts
            from sugar_lift_py_tests.floor.block_value import BlockValue

            return ExitSet.completed(BlockValue((), can_fall_through=True))

        accumulated = ExitSet(())
        earlier: list = []  # selection formulas of prior *selected* cases
        # The match step every path past the cases so far took: it owes what
        # the completed faces of their patterns, equalities and guards owed
        # (#7757). A case is reached only after every earlier case's pattern
        # ran, so its arms are sequenced after this.
        running = _debt()

        for arm, case in enumerate(self.cases):
            if not isinstance(case, MatchCaseSpec):
                raise TypeError(
                    f"MatchSugar.cases requires MatchCaseSpec, got {type(case).__name__}"
                )

            not_prev = _not_earlier(earlier)

            if case.pattern is not None:
                parts, running, selection = self._structural_case(
                    arm, case, subject, not_prev, running, ctx
                )
                accumulated = accumulated.union(parts)
                if selection is not None:
                    earlier.append(selection)
                continue

            # --- pattern match (all exceptional faces restricted by not_prev) ---
            match_formula, pattern_side, pattern_path = (
                _pattern_match_formula_and_side_exits(
                    subject, case.alternatives, self.site, not_prev, ctx
                )
            )
            accumulated = accumulated.union(_after(None, running, pattern_side))
            running = _then(running, pattern_path)

            if match_formula is None:
                # No completed match formula: only exceptional pattern faces.
                # Do not claim this case selected; later cases still compete
                # under not_prev (already on those exceptional faces).
                continue

            reached = _and_parts(not_prev, match_formula)

            # --- tentative capture for guard; rolled back after this case ---
            guard_ctx = _tentative_capture_ctx(ctx, case.capture_name, subject)
            body_ctx = _tentative_capture_ctx(ctx, case.capture_name, subject)

            if case.guard is None:
                body_exits = self._routed(
                    arm, reduce_block_to_exitset(case.body, body_ctx)
                )
                accumulated = accumulated.union(_after(reached, running, body_exits))
                earlier.append(match_formula)
                continue

            guard_out = case.guard.desugar(guard_ctx)
            parts, earlier_bits, guard_path = _guard_faces_under(
                guard_out,
                reached,
                self.site,
                case.body,
                body_ctx,
                match_formula,
                running,
                lambda exits, arm=arm: self._routed(arm, exits),
            )
            for part in parts:
                accumulated = accumulated.union(part)
            running = _then(running, guard_path)
            # Collapse earlier_bits: any selection of this case for first-case-wins.
            if earlier_bits:
                # Distinct polarities: later cases see not(OR of selections).
                if len(earlier_bits) == 1:
                    earlier.append(earlier_bits[0])
                else:
                    earlier.append(or_(tuple(earlier_bits)))
            # body_ctx / guard_ctx discarded here — rollback for next case.

        from sugar_lift_py_tests.outcome.exit_set import _is_true

        if not any(_is_true(selection) for selection in earlier):
            # No case is a catch-all: the path where no case matched is real
            # Python behaviour (execution continues after the match), so it
            # is an arm (#7757). It is completed under the negation of every
            # case's selection and owes what every failed equality, pattern
            # and guard on that path owed.
            from sugar_lift_py_tests.floor.block_value import BlockValue

            # The fall-through route: every case slot is false on it.
            accumulated = accumulated.union(
                _after(
                    _not_earlier(earlier),
                    running,
                    ExitSet.completed(
                        BlockValue(self._route_facts(None), can_fall_through=True)
                    ),
                )
            )
        # Shared ExitSet projection — no output-kind membrane on value shape.
        return accumulated.normalize()

    def _structural_case(self, arm, case, subject, not_prev, running, ctx):
        """Case ``arm`` with a structural pattern: ``(parts, running,
        selection)``.

        The pattern is tested against the subject (``match_pattern``): each
        halted face (a projection's halt) is an arm under ``not_prev``,
        after ``running``; each face that matched selects the case under its
        guard, with its captures bound under their keys (``_bind_captures``)
        for the guard and the body.  A guard is evaluated there, after the
        captures, and joins the selection (``_guard_faces_under``).  The
        returned ``running`` owes what every completed face of the pattern
        and every guard owed; ``selection`` is the case's selection (None
        when no face can match)."""
        from sugar_lift_py_tests.ir import or_
        from sugar_lift_py_tests.outcome import Completed, Halted
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            halt_record,
            halts_recorded,
            reduce_block_to_exitset,
        )

        # The case reads the pattern's faces one by one: a pattern still
        # waiting on its caller's actual (a projection's carrier) is refused
        # here by name, never read as no face. A projection's halt is before
        # any case body ran: it carries the record where it halted.
        tested = halts_recorded(
            _projected(match_pattern(case.pattern, subject, self.site, ctx)),
            halt_record(ctx),
        )
        parts = ExitSet(())
        selections: list = []
        pattern_path = _debt()
        guard_paths = _debt()
        for face in tested.exits:
            if isinstance(face, Halted):
                parts = parts.union(_after(None, running, _halted_face(face, not_prev)))
                continue
            if not isinstance(face, Completed):
                raise NotImplementedError(
                    f"match pattern face not lifted: {type(face).__name__}"
                )
            pattern_path = pattern_path.union(_debt(face.owed))
            if not face.value.matched:
                continue
            # Every arm of this selection runs after ``running`` and then the
            # matched face itself: its guard, its partition testimony and what
            # it owes ride onto every arm.
            path = _then(running, ExitSet((face,)))
            body_ctx = _bind_captures(ctx, face.value.binds)
            if case.guard is None:
                body_exits = self._routed(
                    arm, reduce_block_to_exitset(case.body, body_ctx)
                )
                parts = parts.union(_after(not_prev, path, body_exits))
                selections.append(face.guard)
                continue
            guard_parts, bits, guard_path = _guard_faces_under(
                case.guard.desugar(body_ctx),
                not_prev,
                self.site,
                case.body,
                body_ctx,
                face.guard,
                path,
                lambda exits, arm=arm: self._routed(arm, exits),
            )
            for part in guard_parts:
                parts = parts.union(part)
            guard_paths = guard_paths.union(guard_path)
            selections.extend(bits)
        running = _then(_then(running, pattern_path), guard_paths)
        if not selections:
            return parts, running, None
        selection = selections[0] if len(selections) == 1 else or_(tuple(selections))
        return parts, running, selection

    def _route_facts(self, arm) -> tuple:
        """What a completed arm of route ``arm`` (case ``arm``, or the
        fall-through for ``None``) states about the match's route slots
        (``try_sugar._route_confirmation``); nothing without a route site."""
        from sugar_lift_py_tests.sugar.try_sugar import _route_confirmation

        return _route_confirmation(self.route_site, len(self.cases), arm, self.site)

    def _routed(self, arm, exits):
        """Case ``arm``'s body ``exits`` as the match's route ``arm``: every
        completed arm confirms the route slots (``_route_facts``) and decides
        them for the code after it (``try_sugar._ground_route_on_faces``), so
        a phi after the match (``Match.substitute``) reads that case's
        binding there.  A body still waiting on its caller's actuals is
        routed once they discharge it."""
        if self.route_site is None:
            return exits
        from sugar_lift_py_tests.caller_parameter_contract import (
            NativeOperationExitCarrierV1,
        )
        from sugar_lift_py_tests.sugar.try_sugar import (
            _ground_route_on_faces,
            _prepend_facts,
        )

        if isinstance(exits, NativeOperationExitCarrierV1):
            return exits.after_discharge(
                lambda discharged: self._routed(arm, discharged)
            )
        return _ground_route_on_faces(
            _prepend_facts(exits, self._route_facts(arm)),
            self.route_site,
            len(self.cases),
            arm,
            self.site,
        )


@dataclass(frozen=True)
class _CompleteValueSugar(Sugar):
    """One-shot sugar that desugars to an already-reduced FloorValue."""

    value: object
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None) -> ExitSet:
        del ctx
        return ExitSet.completed(self.value)
