from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1

from .class_value import ClassValue
from .closed_operation_witness import PythonRuntimeIdentity
from .floor_value import FloorValue


_BUILTIN_CLASS_MEMBER_AUTHORITY = object()


@dataclass(frozen=True, init=False)
class BuiltinClassMemberValue(FloorValue):
    """Callable coordinate published by the closed builtin class registry."""

    receiver: "BuiltinObjectClassValue"
    member_name: str
    runtime: PythonRuntimeIdentity
    occurrence: SourceFragmentCoordinateV1
    use_site: object = field(compare=False, repr=False)
    _authority: object = field(init=False, compare=False, repr=False, default=None)

    def __post_init__(self) -> None:
        from sugar_source_tree.fragment import SourceFragment

        if self._authority is not _BUILTIN_CLASS_MEMBER_AUTHORITY:
            raise ValueError("builtin class member lacks producer authority")
        if type(self.receiver) is not BuiltinObjectClassValue:
            raise ValueError("builtin class member receiver is not the registry object")
        if self.runtime != self.receiver.runtime_identity:
            raise ValueError("builtin class member runtime identity mismatch")
        if self.member_name != "__str__":
            raise ValueError("builtin object member is outside the closed roster")
        if type(self.use_site) is not SourceFragment:
            raise ValueError("builtin class member requires an exact source use")
        span = self.use_site.line_col_span
        expected = SourceFragmentCoordinateV1(
            self.use_site.unit.source_cid,
            span.start_line,
            span.start_col,
            span.end_line,
            span.end_col,
        )
        if self.occurrence != expected:
            raise ValueError("builtin class member occurrence mismatch")

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:builtin_class_member",
            [
                self.receiver.to_term(owner="builtin class member"),
                str_const(self.member_name),
                str_const(self.runtime.implementation),
                str_const(f"{self.runtime.major}.{self.runtime.minor}"),
                str_const(self.occurrence.cid),
            ],
            symbol_kind="builtin",
        )


@dataclass(frozen=True)
class BuiltinObjectClassValue(ClassValue):
    """The exact ``object`` class published by the builtin registry."""

    runtime_identity: PythonRuntimeIdentity = field(
        default_factory=PythonRuntimeIdentity.current
    )

    def attribute(self, name, site):
        if name == "__str__":
            return _mint_builtin_object_str_member(self, site)
        return super().attribute(name, site)


def _mint_builtin_object_str_member(receiver, site):
    from sugar_lift_py_tests.outcome import Complete
    from sugar_source_tree.fragment import SourceFragment

    if type(receiver) is not BuiltinObjectClassValue:
        raise ValueError("builtin object member requires the registry receiver")
    if type(site) is not SourceFragment:
        return super(BuiltinObjectClassValue, receiver).attribute("__str__", site)
    span = site.line_col_span
    value = object.__new__(BuiltinClassMemberValue)
    object.__setattr__(value, "receiver", receiver)
    object.__setattr__(value, "member_name", "__str__")
    object.__setattr__(value, "runtime", receiver.runtime_identity)
    object.__setattr__(
        value,
        "occurrence",
        SourceFragmentCoordinateV1(
            site.unit.source_cid,
            span.start_line,
            span.start_col,
            span.end_line,
            span.end_col,
        ),
    )
    object.__setattr__(value, "use_site", site)
    object.__setattr__(value, "_authority", _BUILTIN_CLASS_MEMBER_AUTHORITY)
    value.__post_init__()
    return Complete(value)
