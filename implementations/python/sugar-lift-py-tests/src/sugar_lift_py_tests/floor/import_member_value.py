"""A closed import-bound module member coordinate.

The lexical import pass authenticates the head; the static Attribute chain
names the export path.  This floor carries that joined coordinate without
re-asking an opaque module receiver for a member and without inventing
AttributeError.

Operations on this floor share one door: the export is source-authenticated
but its runtime type is not lift-time decided (``runtime_type_is_decided`` is
False). Lookups use the existing undecided_* named-refusal helpers. Call,
iteration, and method dispatch stay at the import-member runtime boundary —
never invent CallSite / MethodCall construction here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .floor_value import FloorValue
from sugar_source_tree.producer_authority import ProducerAuthorityV1

_IMPORT_MEMBER_AUTHORITY = ProducerAuthorityV1("sugar/floor/import-member")


@dataclass(frozen=True)
class ImportMemberValue(FloorValue):
    """Source-authenticated ``module.attr[.attr…]`` export coordinate."""

    qualified_name: str
    source_cid: str
    import_binding_cid: str
    use_cid: str
    exported_member_path: tuple[str, ...]
    receipt: object = field(compare=False, repr=False)
    _authority: object = field(default=None, compare=False, repr=False)

    def __post_init__(self):
        from sugar_lift_py_tests.import_binding import AuthenticatedImportUseV1

        if self._authority is not _IMPORT_MEMBER_AUTHORITY:
            raise ValueError("ImportMemberValue is not producer-minted")
        if type(self.receipt) is not AuthenticatedImportUseV1:
            raise TypeError("ImportMemberValue requires exact authenticated receipt")
        self.receipt.revalidate()
        if (
            self.qualified_name != self.receipt.target_symbol.removeprefix("python:")
            or self.source_cid != self.receipt.source_cid
            or self.import_binding_cid != self.receipt.import_binding.cid
            or self.use_cid != self.receipt.use["cid"]
            or self.exported_member_path
            != tuple(self.receipt.use["exportedMemberPath"])
        ):
            raise ValueError("ImportMemberValue receipt authority mismatch")

    def denotes_value(self) -> bool:
        """An import-bound export denotes a runtime value at the member path."""
        return True

    def runtime_type_is_decided(self) -> bool:
        """Module export runtime type is not lift-time decided from the path alone."""
        return False

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:import_member",
            [
                str_const(self.qualified_name),
                str_const(self.source_cid),
                str_const(self.import_binding_cid),
                str_const(self.use_cid),
                *[str_const(item) for item in self.exported_member_path],
            ],
        )

    def exception_type_identity(self):
        """The same import coordinate the exception authenticator mints."""
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:exception_type_identity",
            [str_const("import"), str_const(self.qualified_name)],
        )

    # ------------------------------------------------------------------
    # Import-member operations door (one surface; type undecided)
    # ------------------------------------------------------------------
    # Wiring: FloorValue already owns undecided_subscript / undecided_attribute /
    # undecided_contains. ImportMemberValue's only job is to enter those doors
    # instead of the default construction-panic "write more Floor" arm — which
    # would miscount an undecided runtime type as OUR missing floor method.

    def subscript(self, index, site):
        return self.undecided_subscript(
            index, site, owner="ImportMemberValue.subscript"
        )

    def attribute(self, name, site):
        return self.undecided_attribute(name, site, owner="ImportMemberValue.attribute")

    def contains(self, item, site):
        return self.undecided_contains(item, site, owner="ImportMemberValue.contains")

    def attribute_with(self, operation: Any, ctx: object):
        del ctx
        return self.attribute(operation.name, operation.site)

    def subscript_with(self, operation: Any, ctx: object):
        del ctx
        return self.subscript(operation.index, operation.site)

    def contains_with(self, operation: Any, ctx: object):
        del ctx
        return self.contains(operation.item, operation.site)

    def callable_application_with(self, operation: Any, ctx: object):
        """Call-through-import: boundary effect, not CallSite construction.

        Runtime type is undecided at lift; do not invent a CallSite sugar path
        here (that door is not this floor's). Name the import-member call
        boundary with the shared ImportedModuleRuntimeEffect incomplete.
        """
        del ctx
        return _import_member_runtime_effect(
            self,
            site=operation.site,
            shape=f"{self.qualified_name}(...)",
            replacement="ImportMemberCallEffect",
        )

    def call_method_with(self, operation: Any, ctx: object):
        del ctx
        return _import_member_runtime_effect(
            self,
            site=operation.site,
            shape=f"{self.qualified_name}.{operation.name}(...)",
            replacement="ImportMemberMethodCallEffect",
        )

    def iter_with(self, operation: Any, ctx: object):
        del ctx
        return _import_member_runtime_effect(
            self,
            site=operation.site,
            shape=f"iter({self.qualified_name})",
            replacement="ImportMemberIterEffect",
        )

    def binary_operator_with(self, operation: Any, ctx: object):
        del ctx
        return _import_member_runtime_effect(
            self,
            site=operation.site,
            shape=f"{self.qualified_name} {operation.operator} ...",
            replacement="ImportMemberBinaryEffect",
        )

    def equals(self, other, site):
        """Comparison constructs on the authenticated term, not runtime type.

        Equality uses content-addressed import-member terms already carried by
        ``to_term`` — no runtime-type decision required.
        """
        return super().equals(other, site)


def _import_member_runtime_effect(
    value: ImportMemberValue, *, site, shape: str, replacement: str
):
    """Shared incomplete for ops that would require evaluating the export."""
    from sugar_lift_py_tests.effect import (
        ImportedModuleRuntimeEffect,
        runtime_effect_evidence_from_terms,
    )
    from sugar_lift_py_tests.ir import ctor, str_const
    from sugar_lift_py_tests.outcome import Incomplete

    member = value.to_term(owner="ImportMemberRuntimeEffect")
    operand = ctor("call:import_member", [member])
    return Incomplete(
        ImportedModuleRuntimeEffect(
            "import-member runtime boundary: "
            f"`{shape}` requires evaluating authenticated export "
            f"`{value.qualified_name}` (path={value.exported_member_path!r}). "
            "Runtime type is not lift-time decided; source hunting is cut. "
            f"replacement={replacement}; blame={site}",
            **runtime_effect_evidence_from_terms(
                ctor(
                    "python:import_member_floor_operation",
                    [operand, str_const(replacement), str_const(shape)],
                ),
                operand,
                site,
            ),
        )
    )


def _mint_import_member_value(receipt):
    """Module-private producer door from exact lexical import testimony."""
    from sugar_lift_py_tests.import_binding import AuthenticatedImportUseV1

    if type(receipt) is not AuthenticatedImportUseV1:
        raise TypeError("ImportMemberValue requires exact authenticated receipt")
    receipt.revalidate()
    target = receipt.target_symbol
    path = tuple(receipt.use["exportedMemberPath"])
    if not target.startswith("python:") or not path:
        raise ValueError("ImportMemberValue receipt has no imported member path")
    return ImportMemberValue(
        target.removeprefix("python:"),
        receipt.source_cid,
        receipt.import_binding.cid,
        receipt.use["cid"],
        path,
        receipt,
        _IMPORT_MEMBER_AUTHORITY,
    )
