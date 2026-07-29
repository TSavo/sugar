"""A closed import-bound module member coordinate.

The lexical import pass authenticates the head; the static Attribute chain
names the export path.  This floor carries that joined coordinate without
re-asking an opaque module receiver for a member and without inventing
AttributeError.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .floor_value import FloorValue


_IMPORT_MEMBER_AUTHORITY = object()


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

    @classmethod
    def mint(cls, receipt):
        from sugar_lift_py_tests.import_binding import AuthenticatedImportUseV1

        if type(receipt) is not AuthenticatedImportUseV1:
            raise TypeError("ImportMemberValue requires exact authenticated receipt")
        receipt.revalidate()
        target = receipt.target_symbol
        path = tuple(receipt.use["exportedMemberPath"])
        if not target.startswith("python:") or not path:
            raise ValueError("ImportMemberValue receipt has no imported member path")
        return cls(
            target.removeprefix("python:"),
            receipt.source_cid,
            receipt.import_binding.cid,
            receipt.use["cid"],
            path,
            receipt,
            _IMPORT_MEMBER_AUTHORITY,
        )

    def __post_init__(self):
        from sugar_lift_py_tests.import_binding import AuthenticatedImportUseV1

        if self._authority is not _IMPORT_MEMBER_AUTHORITY:
            raise ValueError("ImportMemberValue is not producer-minted")
        if type(self.receipt) is not AuthenticatedImportUseV1:
            raise TypeError("ImportMemberValue requires exact authenticated receipt")
        self.receipt.revalidate()
        if (
            self.qualified_name
            != self.receipt.target_symbol.removeprefix("python:")
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
