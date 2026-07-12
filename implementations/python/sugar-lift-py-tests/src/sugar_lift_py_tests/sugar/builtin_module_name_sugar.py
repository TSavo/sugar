from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.floor.floor_value import FloorValue
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_return_pair

# Well-known top-level modules often referenced in tests without a local binding
# surviving into the function temporal (or when import stmt is not yet staged).
# Closed set — not a soft map for arbitrary names. Unbound user modules still panic.
_BUILTIN_MODULE_NAMES = frozenset(
    {
        "pytest",
        "unittest",
        "mock",
        "typing",
        "types",
        "sys",
        "os",
        "re",
        "json",
        "math",
        "abc",
        "functools",
        "itertools",
        "collections",
        "dataclasses",
        "pathlib",
        "io",
        "copy",
        "struct",
        "base64",
        "hashlib",
        "hmac",
        "binascii",
        "zlib",
        "uuid",
        "datetime",
        "time",
        "random",
        "string",
        "warnings",
        "contextlib",
        "inspect",
        "operator",
        "enum",
        "numpy",
        "pandas",
        "itsdangerous",
        "requests",
        "freezegun",
        "hashlib",
        "secrets",
        "urllib",
        "http",
        "email",
        "logging",
        "pickle",
        "base64",
    }
)


@dataclass(frozen=True)
class BuiltinModuleNameSugar(
    Sugar, role=SugarRole.TERM, comes_before=("NameSugar", "BuiltinTypeNameSugar")
):
    """A Name that is a known top-level module (``pytest``, ``sys``, …).

    Deeper floors: unlocks ``pytest.raises`` / ``sys.version`` coordinates by
    giving the Name a ``python:module`` floor term instead of TemporalContext
    unbound panic. Disjoint from BuiltinTypeNameSugar (types vs modules).

    Module-level ``import`` seeding (lift_rpc) is the preferred path when an
    Import statement exists; this sugar covers bare references and residual
    cases where import stmt is not in the reduced scope.
    """

    name: str
    bound_value: FloorValue | None
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "Name" and site.name_id() in _BUILTIN_MODULE_NAMES

    @classmethod
    def new(cls, site, ctx) -> "BuiltinModuleNameSugar":
        name = site.name_id()
        return cls(
            name=name,
            bound_value=ctx.temporal.value_if_bound(name),
            site=site,
        )

    @classmethod
    def witnesses(cls):
        return _call_return_pair(
            name="builtin_module_name_truthy",
            owner_sugar="BuiltinModuleNameSugar",
            body="pytest",
            truthful="pytest",
            lying="None",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx
        if self.bound_value is not None:
            return Complete(self.bound_value)
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
        from sugar_lift_py_tests.ir import ctor, str_const

        return Complete(SymbolicValue(ctor("python:module", [str_const(self.name)])))
