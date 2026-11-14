"""Collection displays: `[..]` list, `(..)` tuple, `{..}` set, `{k: v}` dict.

Each reduces its element sugars in source order and holds the reduced floor
values -- ListValue / TupleValue / SetValue / DictValue. The floor owns what the
collection then DOES (len, subscript, membership); this only constructs it. An
element that is itself an effect propagates -- a collection with an unresolvable
element is not a value. Star/double-star spreads (`*xs`, `**d`) stay loud until
their own sugar lands: a spread is not one element, and guessing would invent
membership the source never stated.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import (
    ConstructedTermSugar,
    require_constructed_term_sugar,
)
from sugar_lift_py_tests.sugar.witnesses import _call_return_pair


def _reduce_into(element_sugars, ctx, build):
    """Reduce elements in source order, then hand the tuple of values to ``build``.

    LAW: an element's outcome is not one unconditional value. ``and_then`` is the
    one door: an ``ExitSet`` threads every completed arm (a constructed raise
    keeps the control-flow value and evaluates no enclosing step) while halted
    arms bypass and never run the tail; a deferred native-operation carrier
    retains the tail until its caller discharges it.

    Reading ``.value`` off the outcome instead assumed exactly one arm, which is
    false the moment an element can halt: `[a, d[k] := f()]`, an element whose
    store partitions, a comparison chain that raises on one face. That assumption
    was the `'ExitSet' object has no attribute 'value'` defect.
    """
    from sugar_lift_py_tests.floor.named_expression_value import (
        consume_operands,
        reduce_operands,
    )

    # Each element is reduced after the ones before it, under the state after
    # them (``reduce_operands``): ``[(b := 2), b]`` reads ``b`` as 2.
    # An element that PARTITIONS enters the fold with at most one completed arm
    # (#6324). `and_then` is `ExitSet.sequence`, which distributes the tail
    # under every completed arm of the prefix, so an unfactored element makes
    # the accumulator grow multiplicatively: `test_arrow.py` measured 133,104
    # arms arriving at one `normalize` call through this loop. Factoring moves
    # the element's partition onto its VALUE (a `GuardedValue`, which a list
    # holds like any other floor value) and leaves its halted arms at the exit
    # level. The accumulator itself cannot be factored -- its completed value is
    # the growing tuple this fold is building.
    outcome = reduce_operands(element_sugars, ctx, factored=True)
    # The elements are operands of the display: a walrus in one (``[(x :=
    # 5)]``) binds once, through the one operand door, and the display holds
    # the values the elements present.

    if getattr(build, "returns_outcome", False):
        built = outcome.and_then(
            lambda values: consume_operands(lambda *held: build(held), *values)
        )
    else:
        built = outcome.and_then(
            lambda values: consume_operands(
                lambda *held: ExitSet.completed(build(held)), *values
            )
        )
    return built


@dataclass(frozen=True)
class ListSugar(ConstructedTermSugar):
    elements: tuple[ConstructedTermSugar, ...]
    site: object = dataclass_field(compare=False)

    def __post_init__(self) -> None:
        for element in self.elements:
            require_constructed_term_sugar(element, owner="ListSugar.elements")

    @classmethod
    def witnesses(cls):
        return _call_return_pair(
            name="list_len",
            owner_sugar="ListSugar",
            body="len([z, z, z])",
            truthful="3",
            lying="2",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        from sugar_lift_py_tests.floor import list_value
        from sugar_lift_py_tests.floor.object_identity import made_at

        # The display makes a new object here (``made_at``).
        allocation = made_at(self.site)

        def ListValue(held):  # noqa: N802 -- the owner name the fold reports
            return list_value.ListValue(held, allocation=allocation)

        return _reduce_into(self.elements, ctx, ListValue)

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor

        return ctor(
            "python:list-construction",
            (
                self.occurrence_term(owner=owner),
                ctor(
                    "python:list-elements",
                    tuple(element.to_term(owner=owner) for element in self.elements),
                ),
            ),
            symbol_kind="coordinate",
        )


@dataclass(frozen=True)
class TupleSugar(ConstructedTermSugar):
    elements: tuple[ConstructedTermSugar, ...]
    site: object = dataclass_field(compare=False)

    def __post_init__(self) -> None:
        for element in self.elements:
            require_constructed_term_sugar(element, owner="TupleSugar.elements")

    @classmethod
    def witnesses(cls):
        return _call_return_pair(
            name="tuple_len",
            owner_sugar="TupleSugar",
            body="len((z, z))",
            truthful="2",
            lying="3",
        )

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor

        return ctor(
            "python:tuple-construction",
            (
                self.occurrence_term(owner=owner),
                ctor(
                    "python:tuple-elements",
                    tuple(element.to_term(owner=owner) for element in self.elements),
                ),
            ),
            symbol_kind="coordinate",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        from sugar_lift_py_tests.floor.tuple_value import TupleValue

        return _reduce_into(self.elements, ctx, TupleValue)


@dataclass(frozen=True)
class SetSugar(ConstructedTermSugar):
    elements: tuple[ConstructedTermSugar, ...]
    site: object = dataclass_field(compare=False)

    def __post_init__(self) -> None:
        for element in self.elements:
            require_constructed_term_sugar(element, owner="SetSugar.elements")

    @classmethod
    def witnesses(cls):
        return _call_return_pair(
            name="set_len",
            owner_sugar="SetSugar",
            body="len({1, 2, 3})",
            truthful="3",
            lying="2",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        site = self.site

        def SetValue(values):  # noqa: N802 -- the owner name the fold reports
            return _built_set(values, site)

        SetValue.returns_outcome = True
        return _reduce_into(self.elements, ctx, SetValue)

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor

        return ctor(
            "python:set-construction",
            (
                self.occurrence_term(owner=owner),
                ctor(
                    "python:set-elements",
                    tuple(element.to_term(owner=owner) for element in self.elements),
                ),
            ),
            symbol_kind="coordinate",
        )


@dataclass(frozen=True)
class DictSugar(ConstructedTermSugar):
    keys: tuple[ConstructedTermSugar, ...]
    values: tuple[ConstructedTermSugar, ...]
    site: object = dataclass_field(compare=False)

    def __post_init__(self) -> None:
        if len(self.keys) != len(self.values):
            raise ValueError("DictSugar requires equal key/value arity")
        for key in self.keys:
            require_constructed_term_sugar(key, owner="DictSugar.keys")
        for value in self.values:
            require_constructed_term_sugar(value, owner="DictSugar.values")

    @classmethod
    def witnesses(cls):
        return _call_return_pair(
            name="dict_len",
            owner_sugar="DictSugar",
            body="len({1: z, 2: z})",
            truthful="2",
            lying="3",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        # Keys and values interleave in source order (`{k1: v1, k2: v2}`), so
        # they reduce as ONE element sequence and are re-paired afterwards. A
        # halt in `v1` must not be reported after `k2` was evaluated.
        interleaved = tuple(
            sugar for pair in zip(self.keys, self.values) for sugar in pair
        )

        site = self.site

        def DictValue(flat):  # noqa: N802 -- the owner name the fold reports
            return _built_dict(tuple(zip(flat[0::2], flat[1::2])), site)

        DictValue.returns_outcome = True
        return _reduce_into(interleaved, ctx, DictValue)

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor

        entries = tuple(
            ctor(
                "python:dict-entry",
                (key.to_term(owner=owner), value.to_term(owner=owner)),
            )
            for key, value in zip(self.keys, self.values, strict=True)
        )
        return ctor(
            "python:dict-construction",
            (
                self.occurrence_term(owner=owner),
                ctor("python:dict-entries", entries),
            ),
            symbol_kind="coordinate",
        )


def _built_set(values, site):
    """``{e1, e2, ...}``: CPython adds the members in order -- an unhashable
    one raises ``TypeError``, an equal one collapses into the first.  A member
    whose hash or equality the floor does not decide is kept as written; the
    set's length then stays undecided (``SetValue.length``), never a count."""
    from sugar_lift_py_tests.floor.builtin_container_method import (
        _hash_decided,
        _index_of,
    )
    from sugar_lift_py_tests.floor.membership import decided_unhashable
    from sugar_lift_py_tests.floor.set_value import SetValue

    kept: list = []
    for member in values:
        if decided_unhashable(member):
            return _display_refusal(site, "SetSugar")
        if _hash_decided(member) and _index_of(tuple(kept), member) not in (None, -1):
            continue
        kept.append(member)
    from sugar_lift_py_tests.floor.object_identity import made_at

    # The display makes a new object here (``made_at``).
    return ExitSet.completed(SetValue(tuple(kept), allocation=made_at(site)))


def _built_dict(pairs, site):
    """``{k1: v1, ...}``: an unhashable key raises ``TypeError``; a repeated
    key keeps its first position and takes the last value.  A key whose hash
    or equality the floor does not decide is kept as written; the dict's length
    and key traversal then stay undecided (``DictValue``), never a count."""
    from sugar_lift_py_tests.floor.builtin_container_method import (
        _hash_decided,
        _index_of,
    )
    from sugar_lift_py_tests.floor.dict_value import DictValue
    from sugar_lift_py_tests.floor.membership import decided_unhashable

    keys: list = []
    values: list = []
    for key, value in pairs:
        if decided_unhashable(key):
            return _display_refusal(site, "DictSugar")
        found = _index_of(tuple(keys), key) if _hash_decided(key) else None
        if found not in (None, -1):
            values[found] = value
            continue
        keys.append(key)
        values.append(value)
    from sugar_lift_py_tests.floor.object_identity import made_at

    # The display makes a new object here (``made_at``).
    return ExitSet.completed(
        DictValue(tuple(zip(keys, values)), allocation=made_at(site))
    )


def _display_refusal(site, owner):
    from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

    return ground_exceptional_exit(exception_name="TypeError", site=site, owner=owner)
