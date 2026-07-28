from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class NoneValue(FloorValue):
    """The floor for the `None` literal. No fields -- the None-ness IS the type."""

    def denotes_value(self) -> bool:
        """This floor value denotes ``None``."""
        return True

    def truth(self, site):
        # None's truth IS False -- the type again.
        from sugar_lift_py_tests.outcome import Complete
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )

        return Complete(FalseBoolLiteralSugar(site=site))

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

    def attribute(self, name, site):
        # NoneType's member set is closed and source-decided.  A name outside
        # that set is the authenticated AttributeError partition; a name inside
        # it stays the py.getattr coordinate until its body is constructed
        # (so ``None.__class__`` / ``None.__doc__`` are never mis-exited).
        if name not in self._NONETYPE_MEMBERS:
            from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

            return ground_exceptional_exit(
                exception_name="AttributeError",
                site=site,
                owner="NoneValue.attribute",
            )
        from sugar_lift_py_tests.floor.getattr_coordinate import getattr_coordinate

        return getattr_coordinate(self, name, owner="NoneValue.attribute")

    def subscript(self, index, site):
        """Construct Python's exact ground ``None[...]`` exceptional exit."""
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        del index
        return ground_exceptional_exit(
            exception_name="TypeError", site=site, owner="ground_type_error"
        )

    def less_than(self, other, site):
        # None orders against nothing: any ground comparison is authenticated
        # TypeError. Symbolic falls to super() emit.
        if self._unorderable_ground_peer(other):
            from sugar_lift_py_tests.floor.ground_exit import ground_type_error

            return ground_type_error(site=site, owner="NoneValue.less_than")
        return super().less_than(other, site)

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

    def less_equal(self, other, site):
        if self._unorderable_ground_peer(other):
            from sugar_lift_py_tests.floor.ground_exit import ground_type_error

            return ground_type_error(site=site, owner="NoneValue.less_equal")
        return super().less_equal(other, site)

    def greater_than(self, other, site):
        if self._unorderable_ground_peer(other):
            from sugar_lift_py_tests.floor.ground_exit import ground_type_error

            return ground_type_error(site=site, owner="NoneValue.greater_than")
        return super().greater_than(other, site)

    def greater_equal(self, other, site):
        if self._unorderable_ground_peer(other):
            from sugar_lift_py_tests.floor.ground_exit import ground_type_error

            return ground_type_error(site=site, owner="NoneValue.greater_equal")
        return super().greater_equal(other, site)

    def contains(self, item, site):
        """``x in None`` is exact TypeError — None is never a container."""
        del item
        from sugar_lift_py_tests.floor.ground_exit import ground_type_error

        return ground_type_error(site=site, owner="NoneValue.contains")

    def equals(self, other, site):
        # None stands on the equals floor only against itself. Cross-type is the
        # honest default gap until a ruling lands.
        if type(other) is NoneValue:
            from sugar_lift_py_tests.outcome import Complete
            from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
                TrueBoolLiteralSugar,
            )

            return Complete(TrueBoolLiteralSugar(site=site))
        from sugar_lift_py_tests.floor.list_value import ListValue
        from sugar_lift_py_tests.floor.set_value import SetValue
        from sugar_lift_py_tests.floor.string_value import StringValue
        from sugar_lift_py_tests.floor.term_value import TermValue
        from sugar_lift_py_tests.floor.tuple_value import TupleValue

        if type(other) in (TermValue, StringValue, ListValue, TupleValue, SetValue):
            # Ground vs ground FOLDS -- an emitted py.eq(None, <ground>) atom has
            # no universe constraining it and would be vacuously SAT-able; Python
            # says None equals none of these, so the fold is False.
            from sugar_lift_py_tests.outcome import Complete
            from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
                FalseBoolLiteralSugar,
            )

            return Complete(FalseBoolLiteralSugar(site=site))
        return super().equals(other, site)

    def _none_arithmetic_type_error(self, other, site, *, owner: str):
        """``None <op> x`` is TypeError when the right type is source-decided.

        An undecided right may still implement ``__r*__``, so that pair stays
        on the shared undecided-binary law rather than inventing an exit.
        """
        if other.denotes_value() and other.runtime_type_is_decided():
            from sugar_lift_py_tests.floor.ground_exit import ground_type_error

            return ground_type_error(site=site, owner=owner)
        return None

    def add(self, other, site):
        constructed = self._none_arithmetic_type_error(
            other, site, owner="NoneValue.add"
        )
        if constructed is not None:
            return constructed
        return super().add(other, site)

    def subtract(self, other, site):
        # None - x is TypeError when the right type is source-decided.  Undecided
        # rights stay on the shared binary-operation third-value law.
        constructed = self._none_arithmetic_type_error(
            other, site, owner="NoneValue.subtract"
        )
        if constructed is not None:
            return constructed
        return super().subtract(other, site)

    def multiply(self, other, site):
        constructed = self._none_arithmetic_type_error(
            other, site, owner="NoneValue.multiply"
        )
        if constructed is not None:
            return constructed
        return super().multiply(other, site)

    def divide(self, other, site):
        constructed = self._none_arithmetic_type_error(
            other, site, owner="NoneValue.divide"
        )
        if constructed is not None:
            return constructed
        return super().divide(other, site)

    def floor_divide(self, other, site):
        constructed = self._none_arithmetic_type_error(
            other, site, owner="NoneValue.floor_divide"
        )
        if constructed is not None:
            return constructed
        return super().floor_divide(other, site)

    def is_identical(self, other, site):
        # None is a singleton: None is None folds True. Against anything else,
        # emit identity -- the general case (e.g. z is None).
        if type(other) is NoneValue:
            from sugar_lift_py_tests.outcome import Complete
            from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
                TrueBoolLiteralSugar,
            )

            return Complete(TrueBoolLiteralSugar(site=site))
        return super().is_identical(other, site)

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor

        return ctor("None", [])
