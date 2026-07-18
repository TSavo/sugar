from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import GetattrRuntimeEffect, runtime_effect_evidence
from sugar_lift_py_tests.floor import ImportAliasValue, ObjectValue, StringValue
from sugar_lift_py_tests.outcome import Incomplete, Outcome
from sugar_lift_py_tests.sugar.attribute_sugar import project_object_attribute
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class GetattrBuiltinSugar(Sugar, role=SugarRole.TERM, comes_before=("CallSugar",)):
    receiver: SugarBody
    static_name: str | None
    dynamic_name: SugarBody | None
    dynamic_observed: str | None
    site: object = field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return (
            site.observed == "Call"
            and site.call_receiver() is None
            and site.call_target_name() == "getattr"
            and site.call_arg_count() == 2
            and not site.call_has_keywords()
        )

    @classmethod
    def new(cls, site, ctx):
        receiver, name = site.call_args()
        literal = name.literal_value() if name.observed == "PrimitiveLiteral" else None
        return cls(
            ctx.build_body(receiver, SugarRole.TERM),
            literal if isinstance(literal, str) else None,
            None if isinstance(literal, str) else ctx.build_body(name, SugarRole.TERM),
            None if isinstance(literal, str) else name.observed,
            site,
        )

    @classmethod
    def witnesses(cls):
        prefix = "class Box:\n    def __init__(self):\n        self.x = 1\n\ndef A():\n    return getattr(Box(), 'x')\n\n"
        imported = (
            "import stat\n\n" "def A():\n" "    return getattr(stat, 'ST_MODE')\n\n"
        )
        return (
            _call_pair(
                name="getattr_builtin_return",
                owner_sugar=cls.__name__,
                truthful=prefix + "def test_a():\n    assert A() == 1\n",
                lying=prefix + "def test_a():\n    assert A() == 2\n",
            ),
            _call_pair(
                name="getattr_imported_source_function_return",
                owner_sugar=cls.__name__,
                truthful=imported + "def test_a():\n    assert A() == 0\n",
                lying=imported + "def test_a():\n    assert A() == 1\n",
            ),
        )

    def desugar(self, ctx=None) -> Outcome:
        return self.receiver.reduce(ctx).and_then(
            lambda receiver: self._finish(receiver, ctx)
        )

    def _finish(self, receiver, ctx):
        if self.static_name is None:
            assert self.dynamic_name is not None
            return self.dynamic_name.reduce(ctx).and_then(
                lambda name: self._finish_name(receiver, name, ctx)
            )
        return self._finish_static(receiver, self.static_name, ctx)

    def _finish_name(self, receiver, name, ctx):
        if isinstance(name, StringValue):
            return self._finish_static(receiver, name.value, ctx)

        # Ground single-face name terms (e.g. py.subscript(tuple(...), 0)) fold
        # to a static attribute name. Multi-face iter_elem coordinates stay
        # loud until a parent unfolds them face-by-face (#5156).
        static = _static_attribute_name(name)
        if static is not None:
            return self._finish_static(receiver, static, ctx)

        from sugar_lift_py_tests.effect.runtime_effect import is_lift_time_decidable

        name_term = name.to_term(owner="GetattrBuiltinSugar dynamic name")
        if is_lift_time_decidable(name_term):
            faces = _finite_attribute_name_faces(name_term)
            if faces is not None and len(faces) == 1:
                return self._finish_static(receiver, faces[0], ctx)
            if faces is not None and len(faces) > 1:
                from sugar_lift_py_tests.factory import factory_panic_gap

                factory_panic_gap(
                    owner=type(self).__name__,
                    blame=str(self.site),
                    observed=f"{type(name).__name__}({name_term!r})",
                    requested="statically enumerated attribute name",
                    fix=(
                        "enumerate the finite attribute-name faces and project each "
                        f"one ({faces!r}), or unfold the parent for/comprehension "
                        "so each face arrives as a static string"
                    ),
                )
            from sugar_lift_py_tests.factory import factory_panic_gap

            factory_panic_gap(
                owner=type(self).__name__,
                blame=str(self.site),
                observed=f"{type(name).__name__}({name_term!r})",
                requested="statically enumerated attribute name",
                fix=(
                    "enumerate the finite attribute-name faces and project each "
                    "one, or keep this missing construction loud"
                ),
            )
        return Incomplete(
            GetattrRuntimeEffect(
                f"getattr runtime boundary: attribute name expression `{self.dynamic_observed}` is runtime; blame={self.site}",
                **runtime_effect_evidence("py.getattr.dynamic_name", name, self.site),
            )
        )

    def _finish_static(self, receiver, name: str, ctx):
        if isinstance(receiver, ImportAliasValue):
            from sugar_lift_py_tests.sugar.install_source_dig import (
                resolve_install_source_value,
            )

            target = receiver.import_target or receiver.name
            resolved = resolve_install_source_value(f"{target}.{name}", ctx)
            if resolved is not None:
                from sugar_lift_py_tests.outcome import Complete

                return Complete(resolved)
            coordinate = receiver.qualified_attribute(name, self.site)
            if coordinate is not None:
                from sugar_lift_py_tests.outcome import Complete

                return Complete(coordinate)
            return receiver.getattr_static(name, self.site)
        if not isinstance(receiver, ObjectValue):
            return Incomplete(
                GetattrRuntimeEffect(
                    f"getattr runtime boundary: receiver reduced to {type(receiver).__name__}; Python resolves attributes at runtime; blame={self.site}",
                    **runtime_effect_evidence(
                        "py.getattr.receiver", receiver, self.site
                    ),
                )
            )
        return project_object_attribute(receiver, name, self.site, ctx)

    def walk_children(self):
        return (self.receiver,)


def _static_attribute_name(name) -> str | None:
    """Fold a already-reduced name value to one static attribute string."""
    if isinstance(name, StringValue):
        return name.value
    term = getattr(name, "term", None)
    if term is None and hasattr(name, "to_term"):
        term = name.to_term(owner="GetattrBuiltinSugar dynamic name")
    if term is None:
        return None
    faces = _finite_attribute_name_faces(term)
    if faces is not None and len(faces) == 1:
        return faces[0]
    return None


def _finite_attribute_name_faces(term) -> tuple[str, ...] | None:
    """Return ground string faces of a lift-time-decidable attribute-name term.

    Single-face ground subscripts fold. ``py.iter_elem`` over a ground array
    enumerates every element (and every fixed index of those elements). Unknown
    shapes return None so the caller stays loud.
    """
    from sugar_lift_py_tests.ir import _ConstInt, _ConstStr, _Ctor

    if isinstance(term, _ConstStr):
        return (term.value,)
    if not isinstance(term, _Ctor):
        return None
    if term.name in {"tuple", "array"}:
        faces: list[str] = []
        for arg in term.args:
            nested = _finite_attribute_name_faces(arg)
            if nested is None or len(nested) != 1:
                return None
            faces.append(nested[0])
        return tuple(faces)
    if term.name == "py.iter_elem" and len(term.args) == 1:
        return _finite_attribute_name_faces(term.args[0])
    if term.name == "py.subscript" and len(term.args) == 2:
        base, index = term.args
        if not isinstance(index, _ConstInt):
            return None
        if (
            isinstance(base, _Ctor)
            and base.name == "py.iter_elem"
            and len(base.args) == 1
        ):
            container = base.args[0]
            if not isinstance(container, _Ctor) or container.name not in {
                "tuple",
                "array",
            }:
                return None
            faces = []
            for element in container.args:
                projected = _project_ground_index(element, index.value)
                if projected is None:
                    return None
                faces.append(projected)
            return tuple(faces)
        projected = _project_ground_index(base, index.value)
        if projected is None:
            return None
        return (projected,)
    return None


def _project_ground_index(term, index: int) -> str | None:
    from sugar_lift_py_tests.ir import _ConstStr, _Ctor

    if isinstance(term, _ConstStr) and index == 0:
        return term.value
    if isinstance(term, _Ctor) and term.name in {"tuple", "array"}:
        if 0 <= index < len(term.args):
            faces = _finite_attribute_name_faces(term.args[index])
            if faces is not None and len(faces) == 1:
                return faces[0]
    return None
