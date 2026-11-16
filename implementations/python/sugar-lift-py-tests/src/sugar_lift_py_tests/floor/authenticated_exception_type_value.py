from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.ir import Term

from .floor_value import FloorValue


@dataclass(frozen=True)
class AuthenticatedExceptionTypeValue(FloorValue):
    """A type operand plus its source-authenticated exception-class identity."""

    value: FloorValue
    identity: Term
    mro: tuple[Term, ...] | None = None
    class_value: FloorValue | None = None

    def to_term(self, *, owner: str):
        return self.value.to_term(owner=owner)

    def setitem(self, index, value, site, ctx):
        """The carried type operand stores through the one item mutation
        (``store_effect_sugar.item_mutation``), never its own ``setitem``
        past the door: an operand whose type is not decided keeps the
        undecided mutation's halt (#7757 step 7)."""
        from sugar_lift_py_tests.sugar.store_effect_sugar import item_mutation

        return item_mutation(
            "__setitem__",
            self.value,
            (index, value),
            site,
            ctx,
            unit=getattr(site, "unit", None),
        )

    def delitem(self, index, site, ctx):
        """The carried type operand deletes through the one item mutation."""
        from sugar_lift_py_tests.sugar.store_effect_sugar import item_mutation

        return item_mutation(
            "__delitem__",
            self.value,
            (index,),
            site,
            ctx,
            unit=getattr(site, "unit", None),
        )

    def setattr(self, name, value, site, ctx):
        return self.value.setattr(name, value, site, ctx)

    def delattr(self, name, site, ctx):
        return self.value.delattr(name, site, ctx)

    def exception_type_identity(self) -> Term:
        return self.identity

    def exception_type_mro(self) -> tuple[Term, ...] | None:
        return self.mro

    def test_python_subtype(self, supertype, site):
        from sugar_lift_py_tests.floor.authenticated_exception_type_value import (
            AuthenticatedExceptionTypeValue,
        )
        from sugar_lift_py_tests.floor.class_value import ClassValue
        from sugar_source_tree.panic import SugarNotWritten

        if not isinstance(supertype, AuthenticatedExceptionTypeValue):
            raise SugarNotWritten(
                blame=site,
                owner="AuthenticatedExceptionTypeValue.test_python_subtype",
                observed=type(supertype).__name__,
                requested="authenticated exception type operand",
                fix="construct the handler type through its lexical coordinate",
            )
        leaf_class = self.class_value if self.class_value is not None else self.value
        handler_class = (
            supertype.class_value
            if supertype.class_value is not None
            else supertype.value
        )
        if not isinstance(leaf_class, ClassValue):
            raise SugarNotWritten(
                blame=site,
                owner="AuthenticatedExceptionTypeValue.test_python_subtype",
                observed=type(leaf_class).__name__,
                requested="authenticated ClassValue leaf",
                fix="construct the raised exception through its lexical class graph",
            )
        return leaf_class.test_python_subtype(handler_class, site)
