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


def _constant_str(value):
    from .floor.string_value import StringValue
    from .floor.term_value import TermValue

    if type(value) is StringValue and type(value.value) is str:
        return value.value
    if type(value) is TermValue and type(value.value) is str:
        return value.value
    return None


def pinned_absent_top_level_module(name) -> bool:
    """True iff the pinned interpreter's import system finds no ``name``.

    Only a top-level absolute name is asked: ``importlib.util.find_spec`` on
    a name with no dot imports nothing (no parent package runs) -- it reads
    ``sys.modules`` and asks each ``sys.meta_path`` finder for a spec.  A
    ``None`` answer is exactly the condition under which
    ``importlib.import_module(name)`` raises ``ModuleNotFoundError``
    (Lib/importlib/_bootstrap.py ``_find_and_load_unlocked``).
    """
    import importlib.util
    import sys

    if not isinstance(name, str) or not name.isidentifier():
        return False
    if name in sys.modules:
        return sys.modules[name] is None
    try:
        return importlib.util.find_spec(name) is None
    except (ImportError, ValueError):
        return False


def pinned_present_top_level_module(name) -> bool:
    """True iff the pinned interpreter's import system finds ``name``.

    The positive twin of :func:`pinned_absent_top_level_module`, asked the same
    way (``sys.modules`` then ``importlib.util.find_spec`` on a top-level
    absolute name: nothing is imported).  A failed question is neither answer.
    """
    import importlib.util
    import sys

    if not isinstance(name, str) or not name.isidentifier():
        return False
    if name in sys.modules:
        return sys.modules[name] is not None
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def imported_module_value(name: str):
    """The value an import of the top-level module ``name`` evaluates to.

    ``import name`` binds, and ``importlib.import_module(name)`` returns, the
    same object: ``sys.modules[name]`` once ``_bootstrap._gcd_import`` has
    loaded it.  That object is named by its structural module coordinate
    ``python:module(<name>)`` (the coordinate an ``import a.b`` occurrence reads
    as, #7726); nothing about its members is claimed.
    """
    from .floor.symbolic_value import SymbolicValue
    from .ir import ctor, str_const

    return SymbolicValue(ctor("python:module", (str_const(name),)))


def module_value_name(value):
    """``<name>`` when ``value`` is exactly ``python:module(<name>)``, else None.

    Only that structural coordinate is a module here: any other value (an
    opaque call result, a string, ``None``) is not read as one.
    """
    from .floor.symbolic_value import SymbolicValue
    from .ir import _ConstStr, _Ctor

    if type(value) is not SymbolicValue:
        return None
    term = value.term
    if (
        type(term) is not _Ctor
        or term.name != "python:module"
        or len(term.args) != 1
        or type(term.args[0]) is not _ConstStr
    ):
        return None
    return term.args[0].value


def cpython_cited_fold(unprojected, arg_values, keyword_names, site=None):
    """A stdlib call with no projected body whose result CPython's source decides.

    ``unprojected`` is the call's may-raise testimony: an off-population
    citation (``python:operator.index``) or an unprojected source function
    (``operator`` / ``index``).  Either names the same stdlib callee.

    ``operator.index(a)`` is ``_operator.index`` (Modules/_operator.c,
    ``_operator_index``: ``return PyNumber_Index(a);``).  In
    Objects/abstract.c, ``_PyNumber_Index`` returns ``Py_NewRef(item)`` when
    ``PyLong_Check(item)``, and ``PyNumber_Index`` copies the result only when
    it is not ``PyLong_CheckExact``: an exact ``int`` passes through unchanged
    and nothing is raised.  Only that
    case is decided here: an exact int (never ``bool``, whose index is a copy),
    one positional, no keywords.  Every other operand keeps the off-population
    call two-faced.
    """
    from .floor.term_value import TermValue
    from .outcome import Complete

    if isinstance(unprojected, OffPopulationSourceCallV1):
        qualified = unprojected.target_name.removeprefix("python:")
    elif (
        isinstance(unprojected, UnprojectedSourceCallV1)
        and unprojected.definition_kind == "function"
    ):
        qualified = f"{unprojected.module_name}.{unprojected.definition_name}"
    else:
        return None
    if qualified == "importlib.import_module":
        # ``importlib.import_module(name)`` (Lib/importlib/__init__.py) with
        # a constant top-level absolute name and no ``package``: the pinned
        # environment decides whether that module exists.  When no finder
        # has it, CPython raises ``ModuleNotFoundError`` and nothing else
        # runs; ``pandas.compat._optional.import_optional_dependency`` reads
        # that as "not installed" and returns ``None`` (#7665: zstandard).
        # A module that IS present keeps the two-faced call -- importing it
        # runs its body, which was not looked at, so it may raise anything --
        # but its completed face returns that module: ``sys.modules[name]``,
        # the very object ``import name`` binds (#7742).
        if keyword_names or len(arg_values) != 1 or site is None:
            return None
        name = _constant_str(arg_values[0])
        if name is None:
            return None
        if pinned_present_top_level_module(name):
            return unprojected.faces(imported_module_value(name), site)
        if not pinned_absent_top_level_module(name):
            return None
        from .floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="ModuleNotFoundError",
            site=site,
            owner="cpython_cited_fold:importlib.import_module",
        )
    if qualified != "operator.index" or keyword_names:
        return None
    if len(arg_values) != 1:
        return None
    (operand,) = arg_values
    if type(operand) is TermValue and type(operand.value) is int:
        return Complete(operand)
    return None


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
        from dataclasses import replace

        from .effect.raise_effect import UndeterminedRaiseEffect
        from .floor.call_site_value import CallSiteValue
        from .ir import atomic, ctor, str_const
        from .occurrence import occurrence_key
        from .outcome.exit_set import Completed, ExitSet, Halted, complement_guard

        key = occurrence_key(site)
        call = ctor(
            "python:off_population_call",
            (str_const(self.target_name), str_const(key)),
        )
        completes = atomic("python:off_population_call.completes", [call])
        result = _occurrence_result(callsite, key)
        if isinstance(result, CallSiteValue):
            result = replace(result, off_population_target=self.target_name)
        return ExitSet(
            (
                Completed(completes, result),
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
class UnknownCalleeCallV1:
    """A call whose callee nothing here resolved: an undefined name, a formal,
    or a module member the import door did not cite.

    ``h()`` with ``h`` unbound, ``y()`` with ``y`` a formal, or
    ``random.random()`` whose module was not enrolled: no body, contract or
    floor testified to what runs, so the call may raise anything
    (``NameError`` when the name is unbound, ``TypeError`` when the value is
    not callable, or whatever the callee raises).  It completes only under
    ``python:unknown_callee_call.completes(python:unknown_callee_call(callee,
    site))`` with the value ``python:call_result(<call term>, <occurrence>)``,
    and halts with an ``UndeterminedRaiseEffect`` (owner
    ``UnknownCallee:<callee>``) under the complement -- the #7585 law.  It
    never names what the callee does.
    """

    callee_name: str

    def faces(self, callsite, site):
        from .effect.raise_effect import UndeterminedRaiseEffect
        from .ir import atomic, ctor, str_const
        from .occurrence import occurrence_key
        from .outcome.exit_set import Completed, ExitSet, Halted, complement_guard

        key = occurrence_key(site)
        call = ctor(
            "python:unknown_callee_call",
            (str_const(self.callee_name), str_const(key)),
        )
        completes = atomic("python:unknown_callee_call.completes", [call])
        return ExitSet(
            (
                Completed(completes, _occurrence_result(callsite, key)),
                Halted(
                    complement_guard(completes),
                    UndeterminedRaiseEffect(
                        blame=str(site) if site is not None else None,
                        occurrence=key if site is not None else None,
                        producer_node_owner=f"UnknownCallee:{self.callee_name}",
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


@dataclass(frozen=True)
class BuiltinValueCallV1:
    """A builtin over decided builtin operands that CPython may still refuse.

    ``int('x')`` raises ``ValueError``, ``chr(-1)`` ``ValueError``,
    ``max([])`` ``ValueError``, ``len(5)`` ``TypeError``, ``divmod(1, 0)``
    ``ZeroDivisionError`` -- every dunder is CPython's own, yet whether the
    call completes depends on the operands' values, which this call does not
    evaluate.  So it completes only under ``python:builtin_call.completes(
    python:builtin_call(name, site))`` and halts with an
    ``UndeterminedRaiseEffect`` (owner ``BuiltinCall:<name>``) under the
    complement -- the #7585 law.  Only the shapes ``builtin_call_total``
    lists, which CPython documents as never raising, complete outright.
    """

    builtin_name: str

    def faces(self, callsite, site):
        from .effect.raise_effect import UndeterminedRaiseEffect
        from .ir import atomic, ctor, str_const
        from .occurrence import occurrence_key
        from .outcome.exit_set import Completed, ExitSet, Halted, complement_guard

        key = occurrence_key(site)
        call = ctor(
            "python:builtin_call",
            (str_const(self.builtin_name), str_const(key)),
        )
        completes = atomic("python:builtin_call.completes", [call])
        return ExitSet(
            (
                Completed(completes, _occurrence_result(callsite, key)),
                Halted(
                    complement_guard(completes),
                    UndeterminedRaiseEffect(
                        blame=str(site) if site is not None else None,
                        occurrence=key if site is not None else None,
                        producer_node_owner=f"BuiltinCall:{self.builtin_name}",
                    ),
                    None,
                ),
            )
        ).normalize()


def _scalar(value) -> bool:
    """A decided hashable builtin scalar: int/float/str/bytes/None/bool."""
    from .floor.bytes_value import BytesValue
    from .floor.none_value import NoneValue
    from .floor.string_value import StringValue
    from .floor.term_value import TermValue
    from .sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
    from .sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    return type(value) in (
        TermValue,
        StringValue,
        BytesValue,
        NoneValue,
        TrueBoolLiteralSugar,
        FalseBoolLiteralSugar,
    )


def _ground_number(value, kinds=(int, float)) -> bool:
    import math

    from .floor.term_value import TermValue

    if type(value) is not TermValue:
        return False
    raw = value.value
    if isinstance(raw, bool) or not isinstance(raw, kinds):
        return False
    return not isinstance(raw, float) or math.isfinite(raw)


def _iterable(value) -> bool:
    """A decided builtin value whose iteration is CPython's and cannot raise."""
    from .floor.bytes_value import BytesValue
    from .floor.dict_value import DictValue
    from .floor.list_value import ListValue
    from .floor.set_value import SetValue
    from .floor.string_value import StringValue
    from .floor.tuple_value import TupleValue

    return type(value) in (
        StringValue,
        BytesValue,
        ListValue,
        TupleValue,
        SetValue,
        DictValue,
    ) or (_builtin_container(value) and not _scalar(value))


def _hashable_members(value) -> bool:
    """Iterating ``value`` yields only hashable members (``set(value)``)."""
    from .floor.bytes_value import BytesValue
    from .floor.dict_value import DictValue
    from .floor.list_value import ListValue
    from .floor.set_value import SetValue
    from .floor.string_value import StringValue
    from .floor.tuple_value import TupleValue

    if type(value) in (StringValue, BytesValue, SetValue, DictValue):
        return True
    if type(value) in (ListValue, TupleValue):
        return all(_scalar(element) for element in value.elements)
    return False


def _finite_members(value):
    """The decided members a list/tuple/set display iterates, or None."""
    from .floor.list_value import ListValue
    from .floor.set_value import SetValue
    from .floor.tuple_value import TupleValue

    if type(value) in (ListValue, TupleValue, SetValue):
        return tuple(value.elements)
    return None


def _comparable(members) -> bool:
    """All ground numbers, or all strings: ``<`` and ``+`` between them are
    CPython's own and never raise."""
    from .floor.string_value import StringValue

    return all(_ground_number(v) for v in members) or all(
        type(v) is StringValue for v in members
    )


def builtin_call_total(target_name, arg_values, keyword_names=()) -> bool:
    """Whether CPython documents ``target_name(*arg_values)`` over decided
    builtin operands as never raising.  Anything not listed may raise."""
    from .floor.dict_value import DictValue

    if keyword_names:
        return False
    args = tuple(arg_values)
    n = len(args)
    if target_name == "print":
        return True
    if target_name in ("str", "bool"):
        return n <= 1
    if target_name == "repr":
        return n == 1
    if target_name == "len":
        return n == 1 and _iterable(args[0])
    if target_name in ("list", "tuple"):
        return n == 0 or (n == 1 and _iterable(args[0]))
    if target_name in ("iter", "enumerate", "all", "any"):
        return n == 1 and _iterable(args[0])
    if target_name == "zip":
        return all(_iterable(value) for value in args)
    if target_name in ("set", "frozenset"):
        return n == 0 or (n == 1 and _hashable_members(args[0]))
    if target_name == "dict":
        return n == 0 or (n == 1 and type(args[0]) is DictValue)
    if target_name == "hash":
        return n == 1 and _scalar(args[0])
    if target_name == "abs":
        return n == 1 and _ground_number(args[0])
    if target_name == "int":
        return n == 0 or (n == 1 and _ground_number(args[0]))
    if target_name == "float":
        return n == 0 or (n == 1 and _ground_number(args[0]))
    if target_name in ("sum", "sorted", "min", "max"):
        if n == 1:
            members = _finite_members(args[0])
            if members is None:
                return False
        else:
            members = args
        if not _comparable(members):
            return False
        if target_name == "sum":
            return n == 1 and all(_ground_number(v) for v in members)
        if target_name == "sorted":
            return n == 1
        return n >= 1 and len(members) > 0
    if target_name == "round":
        return n == 1 and _ground_number(args[0])
    if target_name == "range":
        if not (1 <= n <= 3) or not all(_ground_number(v, (int,)) for v in args):
            return False
        return n < 3 or args[2].value != 0
    return False


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


def builtin_list_construct(target_name, arg_values, ctx=None, keyword_names=()):
    """``list(xs)`` over a sequence whose members and order are decided.

    The builtin ``list`` (not a rebinding) with no keywords builds a new list
    of its iterable's members in iteration order: ``list()`` is ``[]``, a
    tuple or list gives its elements, a dict gives its keys in insertion
    order, and a finite comprehension gives its projected members.  It never
    raises for these (``builtin_call_total``).  A set's order depends on
    hashing, so it is not decided here, and neither is any other operand;
    those stay the ordinary bodiless call.
    """
    from .floor.comprehension_value import ComprehensionValue
    from .floor.dict_value import DictValue
    from .floor.list_value import ListValue
    from .floor.tuple_value import TupleValue
    from .outcome import Complete

    if target_name != "list" or keyword_names or not _is_the_builtin("list", ctx):
        return None
    if not arg_values:
        return Complete(ListValue(()))
    if len(arg_values) != 1:
        return None
    (source,) = arg_values
    if type(source) in (TupleValue, ListValue):
        return Complete(ListValue(tuple(source.elements)))
    if type(source) is DictValue:
        return Complete(ListValue(tuple(key for key, _ in source.entries)))
    if type(source) is ComprehensionValue and source.finite_elements is not None:
        return Complete(ListValue(tuple(source.finite_elements)))
    return None


def builtin_dunder_call(target_name, arg_values, ctx=None, keyword_names=()):
    """The may-raise testimony for a dunder-invoking builtin, or None.

    An operand whose type is not a decided builtin may run user code
    (``BuiltinDunderCallV1``); decided operands may still be refused by value
    (``BuiltinValueCallV1``) unless ``builtin_call_total`` lists the shape."""
    if target_name not in DUNDER_BUILTINS or not _is_the_builtin(target_name, ctx):
        return None
    if target_name in SHALLOW_DUNDER_BUILTINS:
        decided = all(_builtin_container(value) for value in arg_values)
    else:
        decided = all(builtin_typed_value(value) for value in arg_values)
    if not decided:
        return BuiltinDunderCallV1(target_name)
    if builtin_call_total(target_name, arg_values, keyword_names):
        return None
    return BuiltinValueCallV1(target_name)
