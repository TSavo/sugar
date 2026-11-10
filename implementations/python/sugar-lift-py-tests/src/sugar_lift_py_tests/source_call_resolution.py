"""Closed exact-use outcomes for authenticated source-call preconstruction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sugar_lift_python_source.canonical import cid_of_json

from .context_manager_resolution import SourceFragmentCoordinateV1


@dataclass(frozen=True)
class SourceCallPreconstructionRefV1:
    use_site: SourceFragmentCoordinateV1
    resolved_object_cid: str
    distribution_artifact_cid: str
    source_call_frame_cid: str
    dispatch_kind: Literal["function", "constructor", "method"] = "function"
    resolution_cid: str = ""

    def __post_init__(self) -> None:
        expected = cid_of_json(self.preimage)
        if self.resolution_cid and self.resolution_cid != expected:
            raise ValueError("source-call resolution CID does not match its preimage")
        object.__setattr__(self, "resolution_cid", expected)

    @property
    def preimage(self):
        return {
            "kind": "source-call-preconstruction-ref",
            "schemaVersion": "1",
            "useSite": self.use_site.wire(),
            "resolvedObjectCid": self.resolved_object_cid,
            "distributionArtifactCid": self.distribution_artifact_cid,
            "sourceCallFrameCid": self.source_call_frame_cid,
            "dispatchKind": self.dispatch_kind,
        }


@dataclass(frozen=True)
class SourceCallPreconstructionGapV1:
    kind: Literal[
        "no-distribution",
        "ambiguous-distribution",
        "artifact-resolution",
        "artifact-mismatch",
        "definition-missing",
        "source-body-gap",
        # The four conditions `opaque-call-target` used to fuse; these ride
        # straight off `ManagerConstructionGapV1.kind`, which owns their
        # definitions.
        "call-graph-cycle",
        "value-call-target",
        "call-target-source-absent",
        "call-target-export-unresolved",
        "call-target-off-population",
        "non-manager-result",
        "call-binding",
        "call-closure-over-bound",
        "dynamic-call-target",
    ]
    use_site: SourceFragmentCoordinateV1
    detail: str


SourceCallPreconstructionV1 = (
    SourceCallPreconstructionRefV1 | SourceCallPreconstructionGapV1
)


__all__ = [
    "SourceCallPreconstructionGapV1",
    "SourceCallPreconstructionRefV1",
    "SourceCallPreconstructionV1",
]


def _occurrence_result(callsite, key):
    """The value ONE evaluation of a bodiless call returned.

    ``call:<target>(<args>)`` names the callee applied to its arguments; as a
    value it would claim that every evaluation of that application returns the
    same object (two iterations of ``r.append(textwrap.dedent(s))``, or two
    sites calling it with equal arguments). Nothing testified to that, so the
    completed result is ``python:call_result(<call term>, <occurrence>)``: the
    application is kept, and the occurrence key makes each evaluation its own
    unknown.
    """
    from dataclasses import replace

    from .floor.call_site_value import CallSiteValue
    from .ir import ctor, str_const

    if not isinstance(callsite, CallSiteValue) or key is None:
        return callsite
    return replace(
        callsite,
        term=ctor("python:call_result", (callsite.term, str_const(key))),
    )


@dataclass(frozen=True)
class UnprojectedSourceCallV1:
    """An authenticated source-defined callee whose body was not projected here.

    Seated at an exact consumer call site after the import receipt resolved to
    a Python ``def``/``class`` in an authenticated dependency artifact. The
    body is real source but was not projected at this site, so the call may
    raise anything: it completes only under the opaque partition atom
    ``python:source_call.completes(module, name, site)`` and halts with an
    ``UndeterminedRaiseEffect`` under its complement. It never names what the
    callee does.

    A ``class`` callee is a construction: ``type.__call__`` runs the class's
    own (or an inherited) ``__new__``/``__init__``, none of which is projected
    here, so it is the same two-faced law under its own atom
    ``python:source_construction.completes(module, name, site)`` and owner
    ``UnprojectedSourceConstruction:<module>.<name>``. Exception classes are no
    exception: constructing one runs its ``__init__`` before any ``raise``.
    """

    module_name: str
    definition_name: str
    definition_kind: Literal["function", "class"]
    resolved_object_cid: str

    def faces(self, callsite, site):
        """Two faces for one bodiless call: opaque completion or a raise."""
        from .effect.raise_effect import UndeterminedRaiseEffect
        from .ir import atomic, ctor, str_const
        from .occurrence import occurrence_key
        from .outcome.exit_set import Completed, ExitSet, Halted, complement_guard

        noun = "source_construction" if self.definition_kind == "class" else "source_call"
        key = occurrence_key(site)
        call = ctor(
            f"python:{noun}",
            (
                str_const(self.module_name),
                str_const(self.definition_name),
                str_const(key),
            ),
        )
        completes = atomic(f"python:{noun}.completes", [call])
        owner = (
            "UnprojectedSourceConstruction"
            if self.definition_kind == "class"
            else "UnprojectedSourceCall"
        )
        return ExitSet(
            (
                Completed(completes, _occurrence_result(callsite, key)),
                Halted(
                    complement_guard(completes),
                    UndeterminedRaiseEffect(
                        blame=str(site) if site is not None else None,
                        occurrence=key if site is not None else None,
                        producer_node_owner=(
                            f"{owner}:{self.module_name}.{self.definition_name}"
                        ),
                    ),
                    None,
                ),
            )
        ).normalize()


@dataclass(frozen=True)
class OffPopulationSourceCallV1:
    """An authenticated callee cited off the enrolled population, called here.

    ``call-target-off-population`` means the export door authenticated the
    callee's defining source (stdlib or an unenrolled distribution) and the
    population membrane declined to project it. Its body is real Python that
    was not looked at, so the call may raise anything: it completes only under
    ``python:off_population_call.completes(python:off_population_call(target,
    site))`` and halts with an ``UndeterminedRaiseEffect`` (owner
    ``OffPopulationCall:<target>``) under the complement -- the #7585 law for a
    consumer's unprojected call, applied where the call sits inside an
    enrolled dependency body. Completing it totally would claim the callee
    never raises. It never names what the callee does.
    """

    target_name: str

    def faces(self, callsite, site):
        from .effect.raise_effect import UndeterminedRaiseEffect
        from .ir import atomic, ctor, str_const
        from .occurrence import occurrence_key
        from .outcome.exit_set import Completed, ExitSet, Halted, complement_guard

        key = occurrence_key(site)
        call = ctor(
            "python:off_population_call",
            (str_const(self.target_name), str_const(key)),
        )
        completes = atomic("python:off_population_call.completes", [call])
        return ExitSet(
            (
                Completed(completes, _occurrence_result(callsite, key)),
                Halted(
                    complement_guard(completes),
                    UndeterminedRaiseEffect(
                        blame=str(site) if site is not None else None,
                        occurrence=key if site is not None else None,
                        producer_node_owner=f"OffPopulationCall:{self.target_name}",
                    ),
                    None,
                ),
            )
        ).normalize()


@dataclass(frozen=True)
class BuiltinDunderCallV1:
    """A builtin that invokes an operand's dunder, on an operand whose type is
    not a decided builtin.

    ``str(c)`` runs ``type(c).__str__``, ``len(c)`` its ``__len__``,
    ``sum([c])`` its ``__radd__``, ``print(c)`` its ``__str__``, ``sorted(c)``
    its ``__iter__`` and the items' ``__lt__``. When an operand is not a
    decided builtin all the way down, that dunder is not CPython's own: it may
    be user code, or missing (``TypeError``), and may raise anything. So the
    call completes only under ``python:builtin_dunder_call.completes(
    python:builtin_dunder_call(name, site))`` and halts with an
    ``UndeterminedRaiseEffect`` (owner ``BuiltinDunderCall:<name>``) under the
    complement -- the #7585 law for a body that was not looked at. It never
    names what the dunder does.
    """

    builtin_name: str

    def faces(self, callsite, site):
        from .effect.raise_effect import UndeterminedRaiseEffect
        from .ir import atomic, ctor, str_const
        from .occurrence import occurrence_key
        from .outcome.exit_set import Completed, ExitSet, Halted, complement_guard

        key = occurrence_key(site)
        call = ctor(
            "python:builtin_dunder_call",
            (str_const(self.builtin_name), str_const(key)),
        )
        completes = atomic("python:builtin_dunder_call.completes", [call])
        return ExitSet(
            (
                Completed(completes, _occurrence_result(callsite, key)),
                Halted(
                    complement_guard(completes),
                    UndeterminedRaiseEffect(
                        blame=str(site) if site is not None else None,
                        occurrence=key if site is not None else None,
                        producer_node_owner=f"BuiltinDunderCall:{self.builtin_name}",
                    ),
                    None,
                ),
            )
        ).normalize()


# Cited pure builtins that invoke a dunder of (or iterate) their operands.
DUNDER_BUILTINS = frozenset(
    {
        "abs",
        "all",
        "any",
        "bool",
        "chr",
        "dict",
        "divmod",
        "enumerate",
        "float",
        "format",
        "frozenset",
        "hash",
        "int",
        "iter",
        "len",
        "list",
        "max",
        "min",
        "ord",
        "print",
        "range",
        "repr",
        "reversed",
        "round",
        "set",
        "sorted",
        "str",
        "sum",
        "tuple",
        "zip",
    }
)


# Of those, the builtins that invoke only the operand's OWN iteration/length
# (``list.__iter__``, ``len``): the items are handed on, never asked anything.
SHALLOW_DUNDER_BUILTINS = frozenset(
    {"enumerate", "iter", "len", "list", "reversed", "tuple", "zip"}
)


def _builtin_container(value) -> bool:
    """A value whose own type is a decided builtin container or scalar."""
    from .floor.comprehension_value import ComprehensionValue
    from .ir import _Ctor

    if builtin_typed_value(value, shallow=True):
        return True
    if type(value) is ComprehensionValue and type(value.term) is _Ctor:
        # A list/set/dict comprehension is an evaluated builtin container; a
        # generator's iteration runs its element expressions.
        return value.term.name in ("py.listcomp", "py.setcomp", "py.dictcomp")
    return False


def builtin_typed_value(value, depth=0, *, shallow=False) -> bool:
    """Whether a floor value is a decided builtin all the way down (or, with
    ``shallow``, whose own type is), so every dunder a builtin invokes on it
    is CPython's own."""
    from .floor.bytes_value import BytesValue
    from .floor.dict_value import DictValue
    from .floor.list_value import ListValue
    from .floor.none_value import NoneValue
    from .floor.set_value import SetValue
    from .floor.string_value import StringValue
    from .floor.term_value import TermValue
    from .floor.tuple_value import TupleValue
    from .sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
    from .sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    if depth > 32:
        return False
    if type(value) in (
        TermValue,
        StringValue,
        BytesValue,
        NoneValue,
        TrueBoolLiteralSugar,
        FalseBoolLiteralSugar,
    ):
        return True
    if shallow and type(value) in (ListValue, TupleValue, SetValue, DictValue):
        return True
    if type(value) in (ListValue, TupleValue, SetValue):
        return all(builtin_typed_value(e, depth + 1) for e in value.elements)
    if type(value) is DictValue:
        return all(
            builtin_typed_value(k, depth + 1) and builtin_typed_value(v, depth + 1)
            for k, v in value.entries
        )
    return False


def _is_the_builtin(target_name, ctx) -> bool:
    """Whether ``target_name`` at this call is bound to Python's own builtin:
    its temporal binding is the very one the builtin floor seats (a lexical
    rebinding, ``tuple = 7``, replaces it)."""
    temporal = getattr(ctx, "temporal", None)
    if temporal is None:
        return False
    from .temporal.builtin_name_bindings import builtin_name_temporal

    seated = builtin_name_temporal().value_if_bound(target_name)
    return seated is not None and temporal.value_if_bound(target_name) is seated


def builtin_dunder_call(target_name, arg_values, ctx=None):
    """The may-raise testimony for a dunder-invoking builtin over an operand
    whose type is not a decided builtin, or None."""
    if target_name not in DUNDER_BUILTINS or not _is_the_builtin(target_name, ctx):
        return None
    if target_name in SHALLOW_DUNDER_BUILTINS:
        decided = all(_builtin_container(value) for value in arg_values)
    else:
        decided = all(builtin_typed_value(value) for value in arg_values)
    if decided:
        return None
    return BuiltinDunderCallV1(target_name)
