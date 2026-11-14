from __future__ import annotations

from dataclasses import dataclass

from .guard_stable_value import GuardStableValue


@dataclass(frozen=True)
class NoneValue(GuardStableValue):
    """The floor for the `None` literal. No fields -- the None-ness IS the type."""

    def denotes_value(self) -> bool:
        """This floor value denotes ``None``."""
        return True

    def truth(self, site):
        # None's truth IS False -- the type again.
        from sugar_lift_py_tests.outcome import ExitSet
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )

        return ExitSet.completed(FalseBoolLiteralSugar(site=site))

    # Closed NoneType member inventory (CPython 3.12 ``dir(None)``).  Names
    # outside this set raise AttributeError at runtime; names inside it are
    # real members whose bodies the lift may still leave as coordinates.
    _NONETYPE_MEMBERS = frozenset(
        {
            "__bool__",
            "__class__",
            "__delattr__",
            "__dir__",
            "__doc__",
            "__eq__",
            "__format__",
            "__ge__",
            "__getattribute__",
            "__getstate__",
            "__gt__",
            "__hash__",
            "__init__",
            "__init_subclass__",
            "__le__",
            "__lt__",
            "__ne__",
            "__new__",
            "__reduce__",
            "__reduce_ex__",
            "__repr__",
            "__setattr__",
            "__sizeof__",
            "__str__",
            "__subclasshook__",
        }
    )

    def attribute(self, name, site, ctx):
        # NoneType's member set is closed and source-decided.  A name outside
        # that set is the authenticated AttributeError partition; a name inside
        # it stays the py.getattr coordinate until its body is constructed
        # (so ``None.__class__`` / ``None.__doc__`` are never mis-exited).
        del ctx
        if name not in self._NONETYPE_MEMBERS:
            from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

            return ground_exceptional_exit(
                exception_name="AttributeError",
                site=site,
                owner="NoneValue.attribute",
            )
        from sugar_lift_py_tests.floor.getattr_coordinate import getattr_coordinate

        return getattr_coordinate(self, name, owner="NoneValue.attribute")

    def setattr(self, name, value, site, ctx):
        """``None.name = value`` is always AttributeError — store, not read."""
        del name, value, ctx
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="AttributeError",
            site=site,
            owner="NoneValue.setattr",
        )

    def delattr(self, name, site, ctx):
        """``del None.name`` is always AttributeError — delete, not read."""
        del name, ctx
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="AttributeError",
            site=site,
            owner="NoneValue.delattr",
        )

    def subscript(self, index, site):
        """Construct Python's exact ground ``None[...]`` exceptional exit."""
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        del index
        return ground_exceptional_exit(
            exception_name="TypeError", site=site, owner="ground_type_error"
        )

    def setitem(self, index, value, site, ctx):
        """``None[index] = value`` is an exact ground TypeError."""
        del index, value, ctx
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError", site=site, owner="NoneValue.setitem"
        )

    def delitem(self, index, site, ctx):
        """``del None[index]`` is an exact ground TypeError."""
        del index, ctx
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError", site=site, owner="NoneValue.delitem"
        )

    def less_than(self, other, site, ctx):
        # None orders against nothing: any ground comparison is authenticated
        # TypeError. Undecided peers refuse named (no FOL invent).
        if self._unorderable_ground_peer(other):
            from sugar_lift_py_tests.floor.ground_exit import ground_type_error

            return ground_type_error(site=site, owner="NoneValue.less_than")
        return super().less_than(other, site, ctx)

    def less_than_from_left(self, left, site, ctx):
        """``left < None`` — TypeError when left is a decided ground peer."""
        if self._unorderable_ground_peer(left):
            from sugar_lift_py_tests.floor.ground_exit import ground_type_error

            return ground_type_error(site=site, owner="NoneValue.less_than_from_left")
        return super().less_than_from_left(left, site, ctx)

    def _unorderable_ground_peer(self, other) -> bool:
        from sugar_lift_py_tests.floor.list_value import ListValue
        from sugar_lift_py_tests.floor.set_value import SetValue
        from sugar_lift_py_tests.floor.string_value import StringValue
        from sugar_lift_py_tests.floor.term_value import TermValue
        from sugar_lift_py_tests.floor.tuple_value import TupleValue

        return type(other) in (
            NoneValue,
            TermValue,
            StringValue,
            ListValue,
            TupleValue,
            SetValue,
        )

    def less_equal(self, other, site, ctx):
        if self._unorderable_ground_peer(other):
            from sugar_lift_py_tests.floor.ground_exit import ground_type_error

            return ground_type_error(site=site, owner="NoneValue.less_equal")
        return super().less_equal(other, site, ctx)

    def greater_than(self, other, site, ctx):
        if self._unorderable_ground_peer(other):
            from sugar_lift_py_tests.floor.ground_exit import ground_type_error

            return ground_type_error(site=site, owner="NoneValue.greater_than")
        return super().greater_than(other, site, ctx)

    def greater_equal(self, other, site, ctx):
        if self._unorderable_ground_peer(other):
            from sugar_lift_py_tests.floor.ground_exit import ground_type_error

            return ground_type_error(site=site, owner="NoneValue.greater_equal")
        return super().greater_equal(other, site, ctx)

    def contains(self, item, site):
        """``x in None`` is exact TypeError — None is never a container."""
        del item
        from sugar_lift_py_tests.floor.ground_exit import ground_type_error

        return ground_type_error(site=site, owner="NoneValue.contains")

    def equals(self, other, site, ctx):
        # None stands on the equals floor only against itself. Cross-type is the
        # honest default gap until a ruling lands.
        if type(other) is NoneValue:
            from sugar_lift_py_tests.outcome import ExitSet
            from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
                TrueBoolLiteralSugar,
            )

            return ExitSet.completed(TrueBoolLiteralSugar(site=site))
        if decided_builtin_other_than_none(other):
            # Ground vs ground FOLDS -- an emitted py.eq(None, <ground>) atom has
            # no universe constraining it and would be vacuously SAT-able; Python
            # says None equals none of these, so the fold is False.
            from sugar_lift_py_tests.outcome import ExitSet
            from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
                FalseBoolLiteralSugar,
            )

            return ExitSet.completed(FalseBoolLiteralSugar(site=site))
        return super().equals(other, site, ctx)

    def _none_arithmetic_type_error(self, other, site, *, owner: str):
        """``None <op> x`` is TypeError when the right type is source-decided.

        An undecided right may still implement ``__r*__``, so that pair stays
        on the shared undecided-binary law rather than inventing an exit.
        """
        if other.denotes_value() and other.runtime_type_is_decided():
            from sugar_lift_py_tests.floor.ground_exit import ground_type_error

            return ground_type_error(site=site, owner=owner)
        return None

    def add(self, other, site, ctx):
        constructed = self._none_arithmetic_type_error(
            other, site, owner="NoneValue.add"
        )
        if constructed is not None:
            return constructed
        return super().add(other, site, ctx)

    def subtract(self, other, site, ctx):
        # None - x is TypeError when the right type is source-decided.  Undecided
        # rights stay on the shared binary-operation third-value law.
        constructed = self._none_arithmetic_type_error(
            other, site, owner="NoneValue.subtract"
        )
        if constructed is not None:
            return constructed
        return super().subtract(other, site, ctx)

    def multiply(self, other, site, ctx):
        constructed = self._none_arithmetic_type_error(
            other, site, owner="NoneValue.multiply"
        )
        if constructed is not None:
            return constructed
        return super().multiply(other, site, ctx)

    def divide(self, other, site, ctx):
        constructed = self._none_arithmetic_type_error(
            other, site, owner="NoneValue.divide"
        )
        if constructed is not None:
            return constructed
        return super().divide(other, site, ctx)

    def floor_divide(self, other, site, ctx):
        constructed = self._none_arithmetic_type_error(
            other, site, owner="NoneValue.floor_divide"
        )
        if constructed is not None:
            return constructed
        return super().floor_divide(other, site, ctx)

    def is_identical(self, other, site):
        # None is a singleton: None is None folds True. Against anything else,
        # emit identity -- the general case (e.g. z is None).
        if type(other) is NoneValue:
            from sugar_lift_py_tests.outcome import ExitSet
            from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
                TrueBoolLiteralSugar,
            )

            return ExitSet.completed(TrueBoolLiteralSugar(site=site))
        return super().is_identical(other, site)

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor

        return ctor("None", [])


def decided_builtin_other_than_none(value) -> bool:
    """A decided builtin value that is not ``None``: ``None == value`` is False.

    ``NoneType`` defines no ``__eq__`` and no builtin ``__eq__`` answers
    ``None``, so CPython falls back to identity, from either side.
    """
    from sugar_lift_py_tests.floor.bytes_value import BytesValue
    from sugar_lift_py_tests.floor.dict_value import DictValue
    from sugar_lift_py_tests.floor.list_value import ListValue
    from sugar_lift_py_tests.floor.set_value import SetValue
    from sugar_lift_py_tests.floor.string_value import StringValue
    from sugar_lift_py_tests.floor.term_value import TermValue
    from sugar_lift_py_tests.floor.tuple_value import TupleValue
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
        FalseBoolLiteralSugar,
    )
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    return type(value) in (
        TermValue,
        StringValue,
        BytesValue,
        ListValue,
        TupleValue,
        SetValue,
        DictValue,
        TrueBoolLiteralSugar,
        FalseBoolLiteralSugar,
    )
