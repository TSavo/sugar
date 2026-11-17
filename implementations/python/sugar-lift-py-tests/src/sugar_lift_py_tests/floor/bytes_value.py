from __future__ import annotations

from dataclasses import dataclass

from .guard_stable_value import GuardStableValue


@dataclass(frozen=True)
class BytesValue(GuardStableValue):
    """The floor for a Python `bytes` literal. Carries the raw bytes; stands as
    the vendor-canonical ``python:bytes(<hex String const>)`` ctor already
    consumed by the SMT emitter (``literal_encoding.rs``: "python:bytes(<String
    const>) is the Python kit's ASCII-gated bytes literal"), the verifier's
    structural ground-ctor whitelist (``consistency.rs``), and the isinstance
    fold table (``symbolic_value.py``: ``"python:bytes": "bytes"``). This is
    the ONE representation -- never a second bytes encoding."""

    value: bytes

    def denotes_value(self) -> bool:
        """This floor value denotes a ``bytes``."""
        return True

    def python_isinstance(self, type_name: str, type_term, site):
        """A ``bytes`` is an instance of every class of ``bytes``'s real
        order (``object`` included) and of no other builtin class; any other
        classinfo is the undecided type test, its halt kept
        (``python_type_coordinate.builtin_order_isinstance``, #7757)."""
        from sugar_lift_py_tests.floor.python_type_coordinate import (
            builtin_order_isinstance,
        )

        decided = builtin_order_isinstance(
            "bytes", type_term, site, owner="BytesValue.python_isinstance"
        )
        if decided is not None:
            return decided
        return super().python_isinstance(type_name, type_term, site)

    def equals(self, other, site, ctx):
        if type(other) is BytesValue:
            from sugar_lift_py_tests.outcome import ExitSet
            from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
                FalseBoolLiteralSugar,
            )
            from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
                TrueBoolLiteralSugar,
            )

            return ExitSet.completed(
                TrueBoolLiteralSugar(site=site)
                if self.value == other.value
                else FalseBoolLiteralSugar(site=site)
            )
        return super().equals(other, site, ctx)

    def contains(self, item, site):
        """``item in b"..."``: CPython's ``_Py_bytes_contains``
        (Objects/bytes_methods.c), decided where the needle is ground, as a
        ``str`` haystack's is (``StringValue.contains``).

        - An ``int`` needle (a ``bool`` is one) is a byte value: membership
          where it is in ``range(0, 256)``, ``ValueError`` where it is not.
        - A ``bytes`` needle is a substring test.
        - Any other ground needle (a ``str``, ``None``, a ``float``, a list,
          a tuple, a set) has neither ``__index__`` nor the buffer
          protocol: ``TypeError``.
        - A needle whose type is not decided (a formal, a call's result, an
          instance: its ``__index__`` or buffer may run code or raise) is
          the floor's one undecided membership: two faces, the halt kept,
          owed (``FloorValue.undecided_contains``, #7757 H17).
        """
        from sugar_lift_py_tests.floor.guarded_operand import (
            distribute_guarded_membership,
        )

        distributed = distribute_guarded_membership(self, item, site)
        if distributed is not None:
            return distributed
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit
        from sugar_lift_py_tests.floor.list_value import ListValue
        from sugar_lift_py_tests.floor.none_value import NoneValue
        from sugar_lift_py_tests.floor.set_value import SetValue
        from sugar_lift_py_tests.floor.string_value import StringValue
        from sugar_lift_py_tests.floor.term_value import TermValue
        from sugar_lift_py_tests.floor.tuple_value import TupleValue
        from sugar_lift_py_tests.outcome import ExitSet
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        def decided(answer: bool):
            return ExitSet.completed(
                TrueBoolLiteralSugar(site=site)
                if answer
                else FalseBoolLiteralSugar(site=site)
            )

        if type(item) is BytesValue:
            return decided(item.value in self.value)
        bools = {TrueBoolLiteralSugar: 1, FalseBoolLiteralSugar: 0}
        byte = bools.get(type(item))
        if type(item) is TermValue and isinstance(item.value, int):
            byte = item.value
        if byte is not None:
            if not 0 <= byte < 256:
                return ground_exceptional_exit(
                    exception_name="ValueError",
                    site=site,
                    owner="BytesValue.contains",
                )
            return decided(byte in self.value)
        if type(item) in (
            StringValue,
            NoneValue,
            TermValue,
            ListValue,
            TupleValue,
            SetValue,
        ):
            return ground_exceptional_exit(
                exception_name="TypeError", site=site, owner="BytesValue.contains"
            )
        return self.undecided_contains(item, site, owner="BytesValue.contains")

    def subscript(self, index, site):
        """``b"..."[i]``: CPython's ``bytes_subscript``
        (Objects/bytesobject.c), decided where the index is ground, as a
        ``str``'s is (``StringValue.subscript``): an ``int`` index is the
        byte's ``int`` value, or ``IndexError`` out of range; a slice of
        ``int``/``None`` bounds is the sliced ``bytes`` (``ValueError`` for a
        zero step); an index decided to have no ``__index__`` is
        ``TypeError``; any other is the floor's one undecided subscript."""
        from typing import cast

        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit
        from sugar_lift_py_tests.floor.slice_value import SliceValue
        from sugar_lift_py_tests.floor.term_value import TermValue
        from sugar_lift_py_tests.outcome import ExitSet

        if type(index) is SliceValue:
            bounds = (index.lower, index.upper, index.step)
            if all(
                bound is None or (type(bound) is TermValue and type(bound.value) is int)
                for bound in bounds
            ):
                lower, upper, step = (
                    cast(int, bound.value) if type(bound) is TermValue else None
                    for bound in bounds
                )
                if step == 0:
                    return ground_exceptional_exit(
                        exception_name="ValueError",
                        site=site,
                        owner="BytesValue.subscript",
                    )
                return ExitSet.completed(
                    BytesValue(self.value[slice(lower, upper, step)])
                )
        if type(index) is TermValue and isinstance(index.value, int):
            i = index.value
            n = len(self.value)
            if -n <= i < n:
                return ExitSet.completed(TermValue(self.value[i]))
            from sugar_lift_py_tests.floor.ground_index_error import (
                ground_index_error,
            )

            return ground_index_error(
                owner="BytesValue.subscript",
                operation="bytes subscript",
                index=i,
                length=n,
                site=site,
            )
        if index.python_index_protocol() is False:
            return ground_exceptional_exit(
                exception_name="TypeError", site=site, owner="BytesValue.subscript"
            )
        return self.undecided_subscript(index, site, owner="BytesValue.subscript")

    def slice_assign_iterable_with(self, operation, ctx):
        """Project the bytes object's authenticated integer members."""
        del operation, ctx
        from sugar_lift_py_tests.floor.term_value import TermValue
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(tuple(TermValue(byte) for byte in self.value))

    def setitem(self, index, value, site, ctx):
        """Bytes are immutable: every subscript store is exact TypeError."""
        del index, value, ctx
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError", site=site, owner="BytesValue.setitem"
        )

    def delitem(self, index, site, ctx):
        """Bytes are immutable: every subscript delete is exact TypeError."""
        del index, ctx
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError", site=site, owner="BytesValue.delitem"
        )

    def setattr(self, name, value, site, ctx):
        del value, ctx
        from sugar_lift_py_tests.floor.ground_exit import builtin_attribute_store_exit

        return builtin_attribute_store_exit(name, site=site, owner="BytesValue.setattr")

    def delattr(self, name, site, ctx):
        del ctx
        from sugar_lift_py_tests.floor.ground_exit import builtin_attribute_store_exit

        return builtin_attribute_store_exit(name, site=site, owner="BytesValue.delattr")

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor("python:bytes", [str_const(self.value.hex())])
