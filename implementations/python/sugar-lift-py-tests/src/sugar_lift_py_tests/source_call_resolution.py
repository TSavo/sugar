"""Closed exact-use outcomes for authenticated source-call preconstruction."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache


def _occurrence_result(callsite, site):
    """The value ONE evaluation of a bodiless call returned.

    ``call:<target>(<args>)`` names the callee applied to its arguments; as a
    value it would claim that every evaluation of that application returns the
    same object (two iterations of ``r.append(textwrap.dedent(s))``, or two
    sites calling it with equal arguments). Nothing testified to that, so the
    completed result is ``python:call_result(<call term>, <occurrence>)``: the
    application is kept, and the occurrence makes each evaluation its own
    unknown. The occurrence is ``python:occurrence(<site coordinate CID>,
    <path>…)`` (#7808), read under the same path the caller's own key was.
    """
    from dataclasses import replace

    from .floor.call_site_value import CallSiteValue
    from .ir import ctor
    from .occurrence import occurrence_term

    if not isinstance(callsite, CallSiteValue):
        return callsite
    return replace(
        callsite,
        term=ctor("python:call_result", (callsite.term, occurrence_term(site))),
    )


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


def cpython_cited_fold(
    unprojected, arg_values, keyword_names, site=None, language_callee=None
):
    """A stdlib call with no projected body whose result CPython's source decides.

    ``unprojected`` is the call's may-raise testimony: a callee nothing here
    answers (``UnknownCalleeCallV1``); it says only that the call has no
    projected body, never which callee it is.

    ``language_callee`` is the ``LanguageCallee`` the Call node bound the
    callee to; ``importlib.import_module`` and ``operator.index`` are
    recognised by that member (their binding), never by the callee's name.

    ``operator.index(a)`` is ``_operator.index`` (Modules/_operator.c,
    ``_operator_index``: ``return PyNumber_Index(a);``).  In
    Objects/abstract.c, ``_PyNumber_Index`` returns ``Py_NewRef(item)`` when
    ``PyLong_Check(item)``, and ``PyNumber_Index`` copies the result only when
    it is not ``PyLong_CheckExact``: an exact ``int`` passes through unchanged
    and nothing is raised.  Only that
    case is decided here: an exact int (never ``bool``, whose index is a copy),
    one positional, no keywords.  Every other operand keeps the unanswered
    call two-faced.
    """
    from .floor.term_value import TermValue
    from .outcome import ExitSet

    if not isinstance(unprojected, UnknownCalleeCallV1):
        return None
    from sugar_source_tree.nodes import LanguageCallee

    if language_callee is LanguageCallee.IMPORTLIB_IMPORT_MODULE:
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
    if language_callee is not LanguageCallee.OPERATOR_INDEX or keyword_names:
        return None
    if len(arg_values) != 1:
        return None
    (operand,) = arg_values
    if type(operand) is TermValue and type(operand.value) is int:
        return ExitSet.completed(operand)
    return None


@dataclass(frozen=True)
class UnknownCalleeCallV1:
    """A call nothing here answers: not bridged, stated one way.

    ``h()`` with ``h`` unbound, ``y()`` with ``y`` a formal,
    ``random.random()`` whose module was not enrolled, or a callee the export
    door cited off the enrolled population (``call-target-off-population``:
    stdlib or an unenrolled distribution, whose body was not looked at): no
    body, contract or floor testified to what runs, so the call may raise
    anything
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
        from .occurrence import occurrence_key, occurrence_term
        from .outcome.exit_set import ExitSet
        from .unanswered_calls import unanswered_call

        # Nothing here answers this call: both arms OWE it (#7825, H4), and
        # the full scan writes it once as the proof's `undecided` member
        # (step 8), with the one import table's target symbol when the callee
        # is import-bound, else none (Q5). Both arms, because the call is
        # incurred whether it completes or raises.
        owed = (
            unanswered_call(
                getattr(callsite, "authenticated_target_symbol", None), site
            ),
        )
        key = occurrence_key(site)
        # The call term names its occurrence by coordinate (#7808); `key`
        # stays the raise effect's own occurrence (listed on #7808).
        call = ctor(
            "python:unknown_callee_call",
            (str_const(self.callee_name), occurrence_term(site)),
        )
        completes = atomic("python:unknown_callee_call.completes", [call])
        return ExitSet.two_faced(
            _occurrence_result(callsite, site),
            UndeterminedRaiseEffect(
                blame=str(site) if site is not None else None,
                occurrence=key if site is not None else None,
                producer_node_owner=f"UnknownCallee:{self.callee_name}",
            ),
            guard=completes,
            owed=owed,
        )


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
        from .outcome.exit_set import ExitSet

        key = occurrence_key(site)
        call = ctor(
            "python:builtin_dunder_call",
            (str_const(self.builtin_name), str_const(key)),
        )
        completes = atomic("python:builtin_dunder_call.completes", [call])
        return ExitSet.two_faced(
            _occurrence_result(callsite, site),
            UndeterminedRaiseEffect(
                blame=str(site) if site is not None else None,
                occurrence=key if site is not None else None,
                producer_node_owner=f"BuiltinDunderCall:{self.builtin_name}",
            ),
            guard=completes,
        )


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
        from .outcome.exit_set import ExitSet

        key = occurrence_key(site)
        call = ctor(
            "python:builtin_call",
            (str_const(self.builtin_name), str_const(key)),
        )
        completes = atomic("python:builtin_call.completes", [call])
        return ExitSet.two_faced(
            _occurrence_result(callsite, site),
            UndeterminedRaiseEffect(
                blame=str(site) if site is not None else None,
                occurrence=key if site is not None else None,
                producer_node_owner=f"BuiltinCall:{self.builtin_name}",
            ),
            guard=completes,
        )


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


def builtin_call_total(language_callee, arg_values, keyword_names=()) -> bool:
    """Whether CPython documents the builtin ``language_callee`` (the
    ``LanguageCallee`` the call's callee is bound to, never its spelling)
    applied to ``arg_values`` as never raising: over decided builtin
    operands, or, for the builtins that run no code of their operands
    (``object()``, ``id``, ``callable``, one-operand ``type``), over any.
    Anything not listed may raise; a builtin that runs an operand's dunder
    (``hash``, ``len``, ``iter``) is listed only over decided operands."""
    from sugar_source_tree.nodes import LanguageCallee as L

    from .floor.dict_value import DictValue

    if keyword_names:
        return False
    args = tuple(arg_values)
    n = len(args)
    if language_callee is L.BUILTIN_PRINT:
        return True
    if language_callee in (L.BUILTIN_STR, L.BUILTIN_BOOL):
        return n <= 1
    if language_callee is L.BUILTIN_REPR:
        return n == 1
    if language_callee is L.BUILTIN_LEN:
        return n == 1 and _iterable(args[0])
    if language_callee in (L.BUILTIN_LIST, L.BUILTIN_TUPLE):
        return n == 0 or (n == 1 and _iterable(args[0]))
    if language_callee in (
        L.BUILTIN_ITER,
        L.BUILTIN_ENUMERATE,
        L.BUILTIN_ALL,
        L.BUILTIN_ANY,
    ):
        return n == 1 and _iterable(args[0])
    if language_callee is L.BUILTIN_ZIP:
        return all(_iterable(value) for value in args)
    if language_callee in (L.BUILTIN_SET, L.BUILTIN_FROZENSET):
        return n == 0 or (n == 1 and _hashable_members(args[0]))
    if language_callee is L.BUILTIN_DICT:
        return n == 0 or (n == 1 and type(args[0]) is DictValue)
    if language_callee is L.BUILTIN_HASH:
        return n == 1 and _scalar(args[0])
    if language_callee is L.BUILTIN_ABS:
        return n == 1 and _ground_number(args[0])
    if language_callee is L.BUILTIN_INT:
        return n == 0 or (n == 1 and _ground_number(args[0]))
    if language_callee is L.BUILTIN_FLOAT:
        return n == 0 or (n == 1 and _ground_number(args[0]))
    if language_callee in (
        L.BUILTIN_SUM,
        L.BUILTIN_SORTED,
        L.BUILTIN_MIN,
        L.BUILTIN_MAX,
    ):
        if n == 1:
            members = _finite_members(args[0])
            if members is None:
                return False
        else:
            members = args
        if not _comparable(members):
            return False
        if language_callee is L.BUILTIN_SUM:
            return n == 1 and all(_ground_number(v) for v in members)
        if language_callee is L.BUILTIN_SORTED:
            return n == 1
        return n >= 1 and len(members) > 0
    if language_callee is L.BUILTIN_ROUND:
        return n == 1 and _ground_number(args[0])
    if language_callee is L.BUILTIN_RANGE:
        if not (1 <= n <= 3) or not all(_ground_number(v, (int,)) for v in args):
            return False
        return n < 3 or args[2].value != 0
    # The builtins that run no code of any operand: ``object()`` allocates a
    # bare object (``object(x)`` is a ``TypeError``), ``bytes()`` is ``b''``
    # and ``complex()`` is ``0j``; ``id(x)`` is ``x``'s address, ``callable(x)``
    # reads ``type(x)``'s call slot (``PyCallable_Check``) and ``type(x)``
    # returns ``Py_TYPE(x)``, whatever ``x`` is.
    if language_callee in (L.BUILTIN_OBJECT, L.BUILTIN_BYTES, L.BUILTIN_COMPLEX):
        return n == 0
    if language_callee in (L.BUILTIN_ID, L.BUILTIN_CALLABLE, L.BUILTIN_TYPE):
        return n == 1
    if language_callee is L.BUILTIN_ISINSTANCE:
        # ``PyObject_IsInstance`` over a class whose metaclass is ``type``
        # (``PyType_CheckExact``) runs no ``__instancecheck__``; it tests
        # ``Py_TYPE(obj)``'s MRO and, on a miss, reads ``obj.__class__`` --
        # never user code when ``obj``'s own type is a decided builtin.
        return (
            n == 2
            and _builtin_container(args[0])
            and _builtin_class_info(args[1])
        )
    return False


def _builtin_class_info(value) -> bool:
    """``value`` is a builtin class the builtin namespace itself binds (the
    very floor object, never a value of that name), or a finite tuple of
    them: a class ``isinstance`` tests without running any code.

    Only the floors that ARE classes are admitted: the exception classes,
    ``object``, ``type``, ``dict``, ``tuple`` and ``set``.  The other
    builtin floors (``ClassValue('len')``, ...) are host callables, some of
    them functions, which ``isinstance`` refuses with ``TypeError``."""
    from .floor import (
        BuiltinExceptionClassValue,
        BuiltinObjectClassValue,
        BuiltinSemanticCallable,
    )
    from .floor.tuple_value import TupleValue
    from .temporal.builtin_name_bindings import (
        builtin_name_temporal,
        builtin_type_class,
    )

    if type(value) is TupleValue:
        return all(
            type(element) is not TupleValue and _builtin_class_info(element)
            for element in value.elements
        )
    if value is builtin_type_class():
        return True
    floor = builtin_name_temporal()
    if isinstance(value, (BuiltinExceptionClassValue, BuiltinObjectClassValue)):
        return value is floor.value_if_bound(value.name)
    if isinstance(value, BuiltinSemanticCallable):
        name = _CLASS_CONSTRUCTIONS.get(value.operation)
        return name is not None and value is floor.value_if_bound(name)
    return False


# The builtin semantic callables that are classes, by the name the builtin
# namespace binds each under.
_CLASS_CONSTRUCTIONS = {
    "python.dict.construct": "dict",
    "python.set.construct": "set",
    "python.tuple.construct": "tuple",
}


@lru_cache(maxsize=1)
def _dunder_builtins():
    """``(dunder, shallow)``: the cited pure builtins that invoke a dunder of
    (or iterate) their operands, and of those the ones that invoke only the
    operand's OWN iteration/length (``list.__iter__``, ``len``: the items
    are handed on, never asked anything).  Each is its ``LanguageCallee``
    member: a call reaches one only through its callee's binding."""
    from sugar_source_tree.nodes import LanguageCallee as L

    shallow = frozenset(
        {
            L.BUILTIN_ENUMERATE,
            L.BUILTIN_ITER,
            L.BUILTIN_LEN,
            L.BUILTIN_LIST,
            L.BUILTIN_REVERSED,
            L.BUILTIN_TUPLE,
            L.BUILTIN_ZIP,
        }
    )
    dunder = shallow | frozenset(
        {
            L.BUILTIN_ABS,
            L.BUILTIN_ALL,
            L.BUILTIN_ANY,
            L.BUILTIN_BOOL,
            L.BUILTIN_CHR,
            L.BUILTIN_DICT,
            L.BUILTIN_DIVMOD,
            L.BUILTIN_FLOAT,
            L.BUILTIN_FORMAT,
            L.BUILTIN_FROZENSET,
            L.BUILTIN_HASH,
            L.BUILTIN_INT,
            L.BUILTIN_MAX,
            L.BUILTIN_MIN,
            L.BUILTIN_ORD,
            L.BUILTIN_PRINT,
            L.BUILTIN_RANGE,
            L.BUILTIN_REPR,
            L.BUILTIN_ROUND,
            L.BUILTIN_SET,
            L.BUILTIN_SORTED,
            L.BUILTIN_STR,
            L.BUILTIN_SUM,
        }
    )
    return dunder, shallow


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


def builtin_list_construct(language_callee, arg_values, keyword_names=()):
    """``list(xs)`` over a sequence whose members and order are decided.

    The callee bound to the builtin ``list`` (``LanguageCallee.BUILTIN_LIST``,
    read from its binding: a rebinding, ``list = f``, reaches no member) with
    no keywords builds a new list
    of its iterable's members in iteration order: ``list()`` is ``[]``, a
    tuple or list gives its elements, a dict gives its keys in insertion
    order, and a finite comprehension gives its projected members.  It never
    raises for these (``builtin_call_total``).  A set's order depends on
    hashing, so it is not decided here, and neither is any other operand;
    those stay the ordinary bodiless call.
    """
    from sugar_source_tree.nodes import LanguageCallee

    from .floor.comprehension_value import ComprehensionValue
    from .floor.dict_value import DictValue
    from .floor.list_value import ListValue
    from .floor.tuple_value import TupleValue
    from .outcome import ExitSet

    if language_callee is not LanguageCallee.BUILTIN_LIST or keyword_names:
        return None
    if not arg_values:
        return ExitSet.completed(ListValue(()))
    if len(arg_values) != 1:
        return None
    (source,) = arg_values
    if type(source) in (TupleValue, ListValue):
        return ExitSet.completed(ListValue(tuple(source.elements)))
    if type(source) is DictValue:
        return ExitSet.completed(ListValue(tuple(key for key, _ in source.entries)))
    if type(source) is ComprehensionValue and source.finite_elements is not None:
        return ExitSet.completed(ListValue(tuple(source.finite_elements)))
    return None


def builtin_dunder_call(language_callee, arg_values, keyword_names=()):
    """The may-raise testimony for a dunder-invoking builtin, or None.

    ``language_callee`` is the ``LanguageCallee`` the call's callee is bound
    to (its binding, never its spelling: ``len = my_len`` reaches no member).
    An operand whose type is not a decided builtin may run user code
    (``BuiltinDunderCallV1``); decided operands may still be refused by value
    (``BuiltinValueCallV1``) unless ``builtin_call_total`` lists the shape.
    Each names the builtin its binding's target symbol names."""
    dunder, shallow = _dunder_builtins()
    if language_callee not in dunder:
        return None
    builtin_name = language_callee.value.rsplit(".", 1)[1]
    if language_callee in shallow:
        decided = all(_builtin_container(value) for value in arg_values)
    else:
        decided = all(builtin_typed_value(value) for value in arg_values)
    if not decided:
        return BuiltinDunderCallV1(builtin_name)
    if builtin_call_total(language_callee, arg_values, keyword_names):
        return None
    return BuiltinValueCallV1(builtin_name)
