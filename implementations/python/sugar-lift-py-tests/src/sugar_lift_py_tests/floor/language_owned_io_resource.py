"""Language-owned ``_io`` resource protocol (plan Cut 2).

``io.StringIO`` and ``io.BytesIO`` are reexported from the C module ``_io``,
which has no authenticated source in the stdlib artifact. The language law is
the documented IOBase protocol: ``__enter__`` returns self (total),
``__exit__`` calls ``close()`` and returns ``None`` (never suppresses).

Recognition keys on the export gap ``artifact-module-absent`` for module
``_io`` and a closed set of exported names, never on a use-site spelling.
``open`` and the other ``_io`` types are not in this increment.
"""

from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue
from .closed_operation_witness import PythonRuntimeIdentity


LANGUAGE_OWNED_IO_RESOURCES: frozenset[str] = frozenset({"StringIO", "BytesIO"})


def is_language_owned_io_resource_gap(resolved) -> bool:
    """True when export resolution named a language-owned ``_io`` resource."""
    return (
        getattr(resolved, "kind", None) == "artifact-module-absent"
        and getattr(resolved, "module_name", None) == "_io"
        and getattr(resolved, "exported_name", None) in LANGUAGE_OWNED_IO_RESOURCES
    )


@dataclass(frozen=True)
class LanguageOwnedIoResourceValue(FloorValue):
    """One constructed ``_io.StringIO`` or ``_io.BytesIO`` instance."""

    exported_name: str
    site: object = None

    def __post_init__(self) -> None:
        if self.exported_name not in LANGUAGE_OWNED_IO_RESOURCES:
            raise ValueError(
                f"{self.exported_name!r} is not a language-owned _io resource"
            )

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        del owner
        return ctor("python:_io.resource", (str_const(self.exported_name),))


@dataclass(frozen=True)
class LanguageOwnedIoResourceProtocol:
    """Enter returns self; exit is total and never suppresses."""

    exported_name: str
    runtime: PythonRuntimeIdentity

    def __post_init__(self) -> None:
        if self.exported_name not in LANGUAGE_OWNED_IO_RESOURCES:
            raise ValueError(
                f"{self.exported_name!r} is not a language-owned _io resource"
            )

    def enter_resource_outcome_for(self, receiver, ctx=None):
        del ctx
        from sugar_lift_py_tests.floor.entered_manager_state_value import (
            EnteredManagerStateValue,
        )
        from sugar_lift_py_tests.outcome import Complete

        resource = self._as_resource(receiver)
        return Complete(
            EnteredManagerStateValue(enter_value=resource, receiver_state=resource)
        )

    def exit_outcome_for(self, entered, ctx=None):
        """``IOBase.__exit__`` calls ``close()`` and returns ``None``."""
        del entered, ctx
        from sugar_lift_py_tests.floor.none_value import NoneValue
        from sugar_lift_py_tests.outcome import Complete

        return Complete(NoneValue())

    def _as_resource(self, receiver):
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_source_tree.panic import SugarNotWritten

        if (
            isinstance(receiver, LanguageOwnedIoResourceValue)
            and receiver.exported_name == self.exported_name
        ):
            return receiver
        if isinstance(receiver, CallSiteValue):
            return LanguageOwnedIoResourceValue(
                exported_name=self.exported_name,
                site=receiver.site,
            )
        raise SugarNotWritten(
            blame=getattr(receiver, "site", None),
            owner="LanguageOwnedIoResourceProtocol.enter_resource_outcome_for",
            observed=f"{type(receiver).__name__} is not a language-owned _io."
            f"{self.exported_name} receiver",
            requested=f"CallSiteValue or LanguageOwnedIoResourceValue({self.exported_name})",
            fix="floor the authenticated _io constructor; never invent a resource for an unmatched receiver",
        )
