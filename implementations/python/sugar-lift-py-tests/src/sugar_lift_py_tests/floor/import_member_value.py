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


@dataclass(frozen=True, init=False)
class ImportMemberValue(FloorValue):
    """Source-authenticated ``module.attr[.attr…]`` export coordinate."""

    source_cid: str
    import_binding_cid: str
    value_use_cid: str
    target_symbol: str
    exported_member_path: tuple[str, ...]
    use_site: tuple[int, int, int, int]
    _authority: object = field(repr=False, compare=False)

    def __init__(self, *args, **kwargs):
        del args, kwargs
        from sugar_source_tree.panic import BackendDefect

        raise BackendDefect(
            owner="ImportMemberValue",
            blame="public constructor",
            observed="caller attempted to forge imported member authority",
            requested="private authenticated import-use producer mint",
            fix="construct through ImportMemberSugar with the exact receipt",
        )

    @classmethod
    def _from_authenticated_use(cls, receipt):
        from sugar_lift_py_tests.import_binding import AuthenticatedImportUseV1
        from sugar_source_tree.panic import BackendDefect

        if type(receipt) is not AuthenticatedImportUseV1:
            raise BackendDefect(
                owner="ImportMemberValue._from_authenticated_use",
                blame=receipt,
                observed=type(receipt).__name__,
                requested="exact AuthenticatedImportUseV1",
                fix="mint imported members only from the lexical value-use receipt",
            )
        receipt.revalidate()
        site = receipt.use["useSite"]
        path = tuple(receipt.use["exportedMemberPath"])
        if not receipt.target_symbol.startswith("python:") or not path:
            raise BackendDefect(
                owner="ImportMemberValue._from_authenticated_use",
                blame=site,
                observed="receipt lacks an authenticated python member path",
                requested="python: targetSymbol with nonempty exportedMemberPath",
                fix="preserve the import-value receipt testimony unchanged",
            )
        value = object.__new__(cls)
        object.__setattr__(value, "source_cid", receipt.source_cid)
        object.__setattr__(value, "import_binding_cid", receipt.import_binding.cid)
        object.__setattr__(value, "value_use_cid", receipt.use["cid"])
        object.__setattr__(value, "target_symbol", receipt.target_symbol)
        object.__setattr__(value, "exported_member_path", path)
        object.__setattr__(value, "use_site", (
            site["startLine"], site["startCol"], site["endLine"], site["endCol"]
        ))
        object.__setattr__(value, "_authority", _IMPORT_MEMBER_AUTHORITY)
        return value

    @property
    def qualified_name(self) -> str:
        return self.target_symbol.removeprefix("python:")

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
                str_const(self.target_symbol),
                str_const(self.source_cid),
                str_const(self.import_binding_cid),
                str_const(self.value_use_cid),
                *(str_const(item) for item in self.exported_member_path),
                *(str_const(str(item)) for item in self.use_site),
            ],
            symbol_kind="coordinate",
        )

    def exception_type_identity(self):
        """The same import coordinate the exception authenticator mints."""
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:exception_type_identity",
            [str_const("import"), str_const(self.qualified_name)],
        )
