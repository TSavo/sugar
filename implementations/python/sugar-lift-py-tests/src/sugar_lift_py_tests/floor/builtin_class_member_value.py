from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.ir import _term_content_cid, ctor, num, str_const

from .closed_operation_witness import PythonRuntimeIdentity
from .floor_value import FloorValue


_BUILTIN_CLASS_MEMBER_AUTHORITY = object()


def _member_term(runtime: PythonRuntimeIdentity, owner_name: str, member_name: str):
    return ctor(
        "python:builtin-class-member",
        (
            str_const(runtime.implementation),
            num(runtime.major),
            num(runtime.minor),
            str_const(owner_name),
            str_const(member_name),
        ),
        symbol_kind="coordinate",
    )


@dataclass(frozen=True)
class BuiltinClassMemberValue(FloorValue):
    """Runtime-sealed member coordinate from the builtin namespace producer."""

    runtime: PythonRuntimeIdentity
    owner_name: str
    member_name: str
    coordinate_cid: str
    _authority: object = field(
        init=False, default=None, compare=False, repr=False
    )

    def __post_init__(self) -> None:
        if self._authority is not _BUILTIN_CLASS_MEMBER_AUTHORITY:
            raise ValueError("builtin class member is not producer-minted")
        if type(self.runtime) is not PythonRuntimeIdentity:
            raise ValueError("builtin class member runtime identity is malformed")
        if self.runtime != PythonRuntimeIdentity.current():
            raise ValueError("builtin class member runtime identity is foreign")
        expected = _term_content_cid(
            _member_term(self.runtime, self.owner_name, self.member_name)
        )
        if self.coordinate_cid != expected:
            raise ValueError("builtin class member coordinate CID mismatch")

    def to_term(self, *, owner: str):
        del owner
        return _member_term(self.runtime, self.owner_name, self.member_name)


def _mint_builtin_class_member(
    owner_name: str, member_name: str
) -> BuiltinClassMemberValue:
    runtime = PythonRuntimeIdentity.current()
    term = _member_term(runtime, owner_name, member_name)
    value = object.__new__(BuiltinClassMemberValue)
    object.__setattr__(value, "runtime", runtime)
    object.__setattr__(value, "owner_name", owner_name)
    object.__setattr__(value, "member_name", member_name)
    object.__setattr__(value, "coordinate_cid", _term_content_cid(term))
    object.__setattr__(value, "_authority", _BUILTIN_CLASS_MEMBER_AUTHORITY)
    value.__post_init__()
    return value
