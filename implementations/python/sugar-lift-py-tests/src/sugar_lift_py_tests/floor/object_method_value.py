from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, ClassVar

from sugar_lift_py_tests.sugar_body import SugarBody

if TYPE_CHECKING:
    from sugar_lift_py_tests.sugar.sugar_base import Sugar

from .floor_value import FloorValue
from .object_field import ObjectField


@dataclass(frozen=True)
class ObjectMethodValue(FloorValue):
    _INTRINSIC_MEMBERS: ClassVar[frozenset[str]] = frozenset(
        {
            "__annotations__",
            "__builtins__",
            "__call__",
            "__class__",
            "__closure__",
            "__code__",
            "__defaults__",
            "__delattr__",
            "__dict__",
            "__dir__",
            "__doc__",
            "__eq__",
            "__format__",
            "__ge__",
            "__get__",
            "__getattribute__",
            "__getstate__",
            "__globals__",
            "__gt__",
            "__hash__",
            "__init__",
            "__init_subclass__",
            "__kwdefaults__",
            "__le__",
            "__lt__",
            "__module__",
            "__name__",
            "__ne__",
            "__new__",
            "__qualname__",
            "__reduce__",
            "__reduce_ex__",
            "__repr__",
            "__setattr__",
            "__sizeof__",
            "__str__",
            "__subclasshook__",
            "__type_params__",
        }
    )
    name: str
    parameters: tuple[str, ...]
    # build_body returns SugarBody[Any]; Any
    # is the open membrane here, matching FactoryBuildResult.sugar, since a
    # method body's reduction shape varies with the SugarRole it was built
    # under and is not known at this seam.
    body: SugarBody[Any] | Sugar
    source_call_frame_cid: str | None = None
    formal_coordinate_cids: tuple[str, ...] = ()
    source_call_frame: object | None = field(default=None, compare=False, repr=False)
    descriptor_kind: str | None = None
    # Exact lexical owner of this method body.  Inherited methods retain their
    # defining class rather than being rebound to the runtime receiver class;
    # this is the authenticated ``__class__`` cell used by zero-arg super().
    defining_class: object | None = field(default=None, compare=False, repr=False)
    dynamic_attributes: tuple[ObjectField, ...] = ()

    def __post_init__(self) -> None:
        from sugar_lift_py_tests.sugar.sugar_base import Sugar

        if not isinstance(self.body, (SugarBody, Sugar)):
            raise TypeError("ObjectMethodValue body must be constructor-built")
        if any(type(item) is not ObjectField for item in self.dynamic_attributes):
            raise TypeError("ObjectMethodValue dynamic state requires ObjectField records")
        names = tuple(item.name for item in self.dynamic_attributes)
        if len(set(names)) != len(names):
            raise ValueError("ObjectMethodValue dynamic state has duplicate names")

    def to_term(self, *, owner: str):
        """Project the authenticated source-frame identity of this function."""
        del owner
        if not self.source_call_frame_cid:
            from sugar_lift_py_tests.gap.panic import construction_panic_gap

            construction_panic_gap(
                owner="ObjectMethodValue.to_term",
                blame=self.name,
                observed="method without source call frame CID",
                requested="one authenticated source method coordinate",
                fix="retain the defining source frame or keep the method loud",
            )
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:source-method-value",
            (str_const(self.source_call_frame_cid),),
            symbol_kind="coordinate",
        )

    def _require_source_identity(self, site, *, owner: str) -> None:
        if self.source_call_frame_cid:
            return
        from sugar_lift_py_tests.gap.panic import construction_panic_gap

        construction_panic_gap(
            owner=owner,
            blame=site,
            observed="source method without source call frame CID",
            requested="authenticated source-function identity",
            fix="retain the defining source frame or keep member access loud",
        )

    def attribute(self, name, site):
        """Read receiver-owned function attributes or prove their absence."""
        self._require_source_identity(site, owner="ObjectMethodValue.attribute")
        for item in reversed(self.dynamic_attributes):
            if item.name == name:
                from sugar_lift_py_tests.outcome import Complete

                return Complete(item.value)
        if name in self._INTRINSIC_MEMBERS:
            return super().attribute(name, site)
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="AttributeError",
            site=site,
            owner="ObjectMethodValue.attribute",
        )

    def with_field_store(self, name: str, value: FloorValue) -> "ObjectMethodValue":
        """Return the same function occurrence with one updated dynamic field."""
        remaining = tuple(item for item in self.dynamic_attributes if item.name != name)
        return replace(self, dynamic_attributes=(*remaining, ObjectField(name, value)))

    def python_isinstance(self, type_name: str, type_term, site):
        """Decide that an authenticated source function object is not a class.

        ``ObjectMethodValue`` is produced by a source ``FunctionDef`` and its
        source-call-frame CID authenticates that value category.  It is an
        ordinary ``object`` but not an instance of the builtin metaclass
        ``type``.
        Leaving this undecided creates an impossible ``isinstance(method,
        type)`` face; CPython's ``enum._EnumDict.__setitem__`` then treats an
        ordinary method as a class and eventually attempts ``method.value``.

        This is deliberately narrower than claiming the full builtin object
        MRO.  Other classinfo values retain the ordinary Floor refusal until
        their own authenticated law exists.
        """
        if type_name not in {"type", "object"}:
            return super().python_isinstance(type_name, type_term, site)
        if not self.source_call_frame_cid:
            from sugar_lift_py_tests.gap.panic import construction_panic_gap

            construction_panic_gap(
                owner="ObjectMethodValue.python_isinstance",
                blame=site,
                observed="source method without source call frame CID",
                requested="authenticated source-function identity",
                fix="retain the defining source frame or keep isinstance loud",
            )
        from sugar_lift_py_tests.outcome import Complete
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        return Complete(
            FalseBoolLiteralSugar(site=site)
            if type_name == "type"
            else TrueBoolLiteralSugar(site=site)
        )

    def attribute_presence(self, name: str, site):
        """Decide descriptor members owned by this authenticated function object."""
        self._require_source_identity(
            site, owner="ObjectMethodValue.attribute_presence"
        )
        if any(item.name == name for item in self.dynamic_attributes):
            from sugar_lift_py_tests.outcome import Complete
            from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
                TrueBoolLiteralSugar,
            )

            return Complete(TrueBoolLiteralSugar(site=site))
        descriptor_names = {"__get__", "__set__", "__delete__"}
        if name not in descriptor_names:
            if name in self._INTRINSIC_MEMBERS:
                from sugar_lift_py_tests.outcome import Complete
                from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
                    TrueBoolLiteralSugar,
                )

                return Complete(TrueBoolLiteralSugar(site=site))
            return super().attribute_presence(name, site)

        present = name == "__get__" or self.descriptor_kind == "property"
        from sugar_lift_py_tests.outcome import Complete
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        return Complete(
            TrueBoolLiteralSugar(site=site)
            if present
            else FalseBoolLiteralSugar(site=site)
        )

    def setitem(self, index, value, site):
        del index, value
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError",
            site=site,
            owner="ObjectMethodValue.setitem",
        )

    def delitem(self, index, site):
        del index
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError",
            site=site,
            owner="ObjectMethodValue.delitem",
        )

    def setattr(self, name, value, site):
        self._require_source_identity(site, owner="ObjectMethodValue.setattr")
        from sugar_lift_py_tests.outcome import Complete

        return Complete(self.with_field_store(name, value))

    def delattr(self, name, site):
        self._require_source_identity(site, owner="ObjectMethodValue.delattr")
        from sugar_lift_py_tests.gap.panic import construction_panic_gap

        construction_panic_gap(
            owner="ObjectMethodValue.delattr",
            blame=site,
            observed=f"source function dynamic attribute delete: {name}",
            requested="receiver-owned delete post-state transition",
            fix=(
                "thread deletion through the shared shadow receiver-state door; "
                "do not claim a post-state that no transition publishes"
            ),
        )
