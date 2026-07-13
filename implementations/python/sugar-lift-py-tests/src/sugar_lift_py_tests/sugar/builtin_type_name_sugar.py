from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_return_pair

# Names that stand as types / builtins without a local binding. Not a soft
# fallback for every Name — only this closed set. Unbound user names still panic
# (TemporalContext) — that is correct instrument behaviour.
_BUILTIN_TYPE_NAMES = frozenset(
    {
        "bytes",
        "bytearray",
        "int",
        "str",
        "float",
        "bool",
        "list",
        "dict",
        "tuple",
        "set",
        "frozenset",
        "type",
        "object",
        "complex",
        "memoryview",
        "range",
        "slice",
    }
)


@dataclass(frozen=True)
class BuiltinTypeNameSugar(Sugar, role=SugarRole.TERM, comes_before=("NameSugar",)):
    """A Name that is a known builtin/type (``bytes``, ``int``, …).

    Interface-first: owns the Name fragment before NameSugar so
    ``isinstance(x, bytes)`` does not hit TemporalContext unbound-panic.
    Reduces to ``python:type("<name>")`` — a floor term the call can stand on.

    Deeper floors (#4106 / deeper-floors track): unlocks isinstance asserts and
    other type-name positions without inventing local bindings.
    """

    name: str
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "Name" and site.name_id() in _BUILTIN_TYPE_NAMES

    @classmethod
    def new(cls, site, ctx) -> "BuiltinTypeNameSugar":
        del ctx
        return cls(name=site.name_id(), site=site)

    @classmethod
    def witnesses(cls):
        # Discriminate on the isinstance face (builtin type name is the left
        # of the type arg — truthful bytes vs lying str).
        return _call_return_pair(
            name="builtin_type_name_isinstance",
            owner_sugar="BuiltinTypeNameSugar",
            body="isinstance(b'ab', bytes)",
            truthful="True",
            lying="False",
            # lying twin uses str so the type-name binding is still the sugar under test
            # (both twins need the name to resolve; discrimination is on the bool face).
        )

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
        from sugar_lift_py_tests.ir import ctor, str_const

        return Complete(SymbolicValue(ctor("python:type", [str_const(self.name)])))
