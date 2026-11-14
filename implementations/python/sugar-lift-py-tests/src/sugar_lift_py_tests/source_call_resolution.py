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
    unprojected,
    arg_values,
    keyword_names,
    site=None,
    language_callee=None,
    callsite=None,
):
    """A stdlib call with no projected body whose result CPython's source decides.

    ``unprojected`` is the call's may-raise testimony: a callee nothing here
    answers (``UnknownCalleeCallV1``); it says only that the call has no
    projected body, never which callee it is.

    ``language_callee`` is the ``LanguageCallee`` the Call node bound the
    callee to; ``importlib.import_module``, ``operator.index`` and the
    dunder-invoking builtins are recognised by that member (their binding),
    never by the callee's name.

    A dunder-invoking builtin (``builtin_dunder_call``) whose every operand
    is a ground value is decided by the builtin's own semantics on the
    pinned interpreter (``_builtin_ground_fold``): ``int('3')`` completes
    with ``3``, ``int('x')`` is the one ``ValueError`` halt, ``len('ab')`` is
    ``2`` and ``abs(-2)`` is ``2``.  It is that call's one answerer: no floor
    value folds a builtin over ground operands by hand (#7757).
    ``callsite`` is the call's coordinate, the completed value when the
    result is not a ground value the floor holds.

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

    if language_callee in _dunder_builtins()[0]:
        return _builtin_ground_fold(
            language_callee, arg_values, keyword_names, site, callsite
        )
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


# A floor value that is not a ground value the host interpreter can be handed.
_NOT_GROUND = object()


def _host_ground(value, depth=0, visits=None):
    """The object a ground floor value denotes, else ``_NOT_GROUND``.

    Only values whose every part is a known value: ``int``/``float``
    (``TermValue``), ``str``, ``bytes``, ``None``, ``True``/``False`` and
    lists, tuples and dicts of them.  A set is not handed over: iterating a
    set of strings follows the per-process string hash, so what a builtin
    reads from it is not the same on every run.  A value known only by its
    type (a call result, a comprehension, a formal) is not ground, and
    neither is a list or dict, at any depth, whose contents are not current
    (``object_identity.contents_stale``: it arrived by binding).

    ``visits`` (``id -> (position, object, value)``), when given, records
    each object handed over in the order the operands are walked, with the
    floor value that denotes it: the order a builtin first meets them
    (``_ground_floor`` reads a set result's construction order from it), and
    the value a result that is one of them is (``_handed_over``)."""
    raw = _host_object(value, depth, visits)
    if visits is not None and raw is not _NOT_GROUND and id(raw) not in visits:
        visits[id(raw)] = (len(visits), raw, value)
    return raw


def _host_object(value, depth, visits):
    """``_host_ground`` of one value, its members walked in order."""
    from .floor.bytes_value import BytesValue
    from .floor.dict_value import DictValue
    from .floor.list_value import ListValue
    from .floor.none_value import NoneValue
    from .floor.object_identity import contents_stale
    from .floor.string_value import StringValue
    from .floor.term_value import TermValue
    from .floor.tuple_value import TupleValue
    from .sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
    from .sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    if depth > 32 or contents_stale(value):
        return _NOT_GROUND
    kind = type(value)
    if kind is TermValue:
        return value.value if type(value.value) in (int, float) else _NOT_GROUND
    if kind is StringValue:
        return value.value if type(value.value) is str else _NOT_GROUND
    if kind is BytesValue:
        return value.value if type(value.value) is bytes else _NOT_GROUND
    if kind is NoneValue:
        return None
    if kind is TrueBoolLiteralSugar:
        return True
    if kind is FalseBoolLiteralSugar:
        return False
    if kind in (ListValue, TupleValue):
        members = tuple(_host_ground(e, depth + 1, visits) for e in value.elements)
        if any(member is _NOT_GROUND for member in members):
            return _NOT_GROUND
        return list(members) if kind is ListValue else members
    if kind is DictValue:
        pairs = tuple(
            (_host_ground(k, depth + 1, visits), _host_ground(v, depth + 1, visits))
            for k, v in value.entries
        )
        if any(k is _NOT_GROUND or v is _NOT_GROUND for k, v in pairs):
            return _NOT_GROUND
        try:
            return dict(pairs)
        except TypeError:
            return _NOT_GROUND
    return _NOT_GROUND


def _ground_floor(raw, site, depth=0, *, visits):
    """The floor value for a ground result ``raw``, else None.

    The inverse of ``_host_ground`` over the same values, and three results
    the floor holds by what the operands were (``visits``, the operands'
    walk):

    - a ``list`` or ``dict`` an operand handed over (``max(xs, ys)`` is
      ``xs``, ``d.get(k)`` a member, ``sum([], start)`` is ``start``): a
      builtin that returns its operand returns that object, so the result is
      that operand's own floor value, its ``allocation`` and ``arrival``
      with it (``_handed_over``).  Any other is new here
      (``object_identity.made_at``: ``'a b'.split()``, ``list(t)``,
      ``d.copy()``).
    - a ``set`` whose every member is an object handed over in ``visits``:
      CPython keeps the first of equal members, the operand's own object,
      so their order of first appearance in the operands is the set's
      construction order, the order ``SetValue`` holds (``set([1, 2, 1])``
      is ``SetValue((1, 2))``).  A member the builtin made (``set('ab')``'s
      characters) has no such order: not held.
    - an ``enumerate`` iterator: the ``ListIteratorValue`` of its
      ``(index, member)`` pairs, consumed here from the fresh iterator.
    - a ``dict_items`` view (``d.items()``): the ``TupleValue`` of its
      ``(key, value)`` pairs, the value the floor holds for it.

    A non-finite float, a ``frozenset``, a ``dict_keys``/``dict_values``
    view, any other iterator or any other object is not held as a value
    here."""
    import math

    from .floor.bytes_value import BytesValue
    from .floor.dict_value import DictValue
    from .floor.iterator_value import ListIteratorValue
    from .floor.list_value import ListValue
    from .floor.none_value import NoneValue
    from .floor.set_value import SetValue
    from .floor.string_value import StringValue
    from .floor.term_value import TermValue
    from .floor.tuple_value import TupleValue
    from .sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
    from .sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    if depth > 32:
        return None
    if raw is None:
        return NoneValue()
    if raw is True:
        return TrueBoolLiteralSugar(site=site)
    if raw is False:
        return FalseBoolLiteralSugar(site=site)
    from .floor.object_identity import made_at

    kind = type(raw)
    if kind is int:
        return TermValue(raw)
    if kind is float:
        return TermValue(raw) if math.isfinite(raw) else None
    if kind is str:
        return StringValue(raw)
    if kind is bytes:
        return BytesValue(raw)
    if kind in (list, dict):
        handed = _handed_over(raw, visits)
        if handed is not None:
            return handed
    if kind in (list, tuple):
        members = tuple(_ground_floor(e, site, depth + 1, visits=visits) for e in raw)
        if any(member is None for member in members):
            return None
        if kind is tuple:
            return TupleValue(members)
        return ListValue(members, allocation=made_at(site))
    if kind is dict:
        pairs = tuple(
            (
                _ground_floor(k, site, depth + 1, visits=visits),
                _ground_floor(v, site, depth + 1, visits=visits),
            )
            for k, v in raw.items()
        )
        if any(k is None or v is None for k, v in pairs):
            return None
        return DictValue(pairs, allocation=made_at(site))
    if kind is set:
        # A set is never handed over (``_host_ground``): a set result is new.
        if any(_unvisited(member, visits) for member in raw):
            return None
        ordered = sorted(raw, key=lambda member: visits[id(member)][0])
        members = tuple(
            _ground_floor(m, site, depth + 1, visits=visits) for m in ordered
        )
        if any(member is None for member in members):
            return None
        return SetValue(members, allocation=made_at(site))
    if kind is enumerate:
        members = tuple(
            _ground_floor(pair, site, depth + 1, visits=visits) for pair in raw
        )
        if any(member is None for member in members):
            return None
        return ListIteratorValue(members)
    if kind is type({}.items()):
        # ``d.items()``: the tuple of its ``(key, value)`` pairs, in the dict's
        # order -- the value the floor holds for an items view
        # (``DictValue``/``MappingObjectValue`` ``items``).
        members = tuple(
            _ground_floor(pair, site, depth + 1, visits=visits) for pair in raw
        )
        if any(member is None for member in members):
            return None
        return TupleValue(members)
    return None


def _handed_over(raw, visits):
    """The floor value of the operand object ``raw`` is, else None.

    A builtin that returns an object an operand handed over returns that
    object, not a copy of it (``max(xs, ys)`` is ``xs``): the operand's own
    floor value is the result, so it keeps that object's ``allocation`` --
    its contents are current exactly when the operand's are -- and its
    ``arrival``, which names it to an undecided read
    (``object_identity.identity_term``)."""
    if _unvisited(raw, visits):
        return None
    return visits[id(raw)][2]


def _unvisited(member, visits) -> bool:
    """``member`` is not an object the operands handed over."""
    entry = visits.get(id(member))
    return entry is None or entry[1] is not member


def _ground_operands(arg_values, visits=None):
    """The host objects every operand denotes, else None (one is not ground)."""
    operands = tuple(_host_ground(value, visits=visits) for value in arg_values)
    if any(operand is _NOT_GROUND for operand in operands):
        return None
    return operands


def builtin_ground_call(language_callee, arg_values, keyword_names=()) -> bool:
    """Whether ``cpython_cited_fold`` is this builtin call's one answerer.

    A dunder-invoking builtin (``_dunder_builtins``, its ``LanguageCallee``
    member) with no keyword actual whose every operand is a ground value
    (``_host_ground``): its outcome is the pinned interpreter's own builtin
    applied to those values, and no floor value folds it by hand.  ``print``
    is not (its effect is output)."""
    return _foldable_builtin(language_callee, keyword_names) and (
        _ground_operands(arg_values) is not None
    )


def _foldable_builtin(language_callee, keyword_names) -> bool:
    """A dunder-invoking builtin other than ``print``, with no keyword actual."""
    from sugar_source_tree.nodes import LanguageCallee

    if keyword_names or language_callee is LanguageCallee.BUILTIN_PRINT:
        return False
    return language_callee in _dunder_builtins()[0]


def builtin_ground_fold(language_callee, arg_values, site, callsite=None):
    """``builtin(*arg_values)`` over ground operands, decided, or None.

    The one door a floor value asks when it is reached for a builtin over
    itself (``StringValue.length``: ``len`` of a guarded face): the same
    fold ``cpython_cited_fold`` answers the call with."""
    return _builtin_ground_fold(language_callee, arg_values, (), site, callsite)


def _builtin_ground_fold(language_callee, arg_values, keyword_names, site, callsite):
    """A dunder-invoking builtin over ground operands, decided, or None.

    Every operand is a known value (``_host_ground``), so every dunder the
    builtin invokes is CPython's own and its outcome is the builtin's
    semantics on those values: the pinned interpreter's own builtin, bound
    to the same ``LanguageCallee`` member, applied to them.  A raise is the
    one ground halt with its builtin exception class (``int('x')``:
    ``ValueError``); a completion is the result's floor value (``int('3')``:
    ``3``), or the call's coordinate when the result is not a ground value
    the floor holds (an iterator other than ``enumerate``, a ``frozenset``,
    a ``hash``, which follows the per-process string hash).  An operand
    known only by its type, a keyword actual, or ``print`` (whose effect is
    output) is not decided here (``builtin_ground_call``): None, and the
    call stays the one unanswered call."""
    import builtins

    from sugar_source_tree.nodes import LanguageCallee

    if not _foldable_builtin(language_callee, keyword_names):
        return None
    visits: dict = {}
    operands = _ground_operands(arg_values, visits)
    if operands is None:
        return None
    builtin_name = language_callee.value.rsplit(".", 1)[1]
    return _host_applied(
        getattr(builtins, builtin_name),
        operands,
        site,
        owner=f"cpython_cited_fold:{builtin_name}",
        callsite=callsite,
        visits=visits,
        held=language_callee is not LanguageCallee.BUILTIN_HASH,
    )


def _host_applied(
    function, operands, site, *, owner, callsite, visits, held=True, holder=None
):
    """``function(*operands)`` on the pinned interpreter, as an outcome, or None.

    A raise is the one ground halt with its builtin exception class (a host
    exception that is not a builtin one, a ``MemoryError`` or a
    ``RecursionError`` decides nothing: None).  A completion is the result's
    floor value when ``held`` and the floor holds it (``_ground_floor``),
    else the call's coordinate (``callsite``), else None.  ``holder``, when
    given, is the one reader of the result instead (a constructed builtin
    exception instance, ``builtin_exception_cited_fold``): its floor value,
    or None when the floor does not hold it (nothing is decided)."""
    import builtins

    from .outcome import ExitSet
    from .temporal.builtin_name_bindings import BUILTIN_EXCEPTION_NAMES

    try:
        result = function(*operands)
    except (MemoryError, RecursionError):
        return None
    except Exception as exc:
        raised = type(exc).__name__
        if (
            site is None
            or raised not in BUILTIN_EXCEPTION_NAMES
            or getattr(builtins, raised, None) is not type(exc)
        ):
            return None
        from .floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(exception_name=raised, site=site, owner=owner)
    if holder is not None:
        value = holder(result)
        return None if value is None else ExitSet.completed(value)
    value = _ground_floor(result, site, visits=visits) if held else None
    if value is None:
        value = _occurrence_result(callsite, site)
    if value is None:
        return None
    return ExitSet.completed(value)


# The ``str`` methods whose call on a ground receiver the floor answers: each
# is the pinned interpreter's own ``str`` method (``str_method_cited_fold``).
_CITED_STR_METHODS = frozenset(
    {
        "endswith",
        "join",
        "lstrip",
        "rstrip",
        "split",
        "splitlines",
        "startswith",
        "strip",
    }
)


def str_method_cited_fold(receiver, name, arguments, site):
    """``receiver.<name>(*arguments)`` on a ground ``str``, decided, or None.

    ``receiver`` is a ``StringValue`` (its type is ``str``: the method is
    ``str``'s own, never a spelling looked up elsewhere).  When it and every
    argument are ground values (``_host_ground``) the outcome is the pinned
    interpreter's own ``str`` method applied to them, through the same door
    a builtin over ground operands is decided by (``_host_applied``):
    ``'a b'.split()`` is ``['a', 'b']`` (the ``ListValue`` a list display
    is), ``','.join(['a', 'b'])`` is ``'a,b'``, ``','.join([1])`` the one
    ``TypeError`` halt.  An argument known only by its type: None, and the
    method's floor keeps what the argument's shape decides."""
    if name not in _CITED_STR_METHODS:
        return None
    visits: dict = {}
    operands = _ground_operands((receiver, *arguments), visits)
    if operands is None or type(operands[0]) is not str:
        return None
    return _host_applied(
        getattr(str, name),
        operands,
        site,
        owner=f"cpython_cited_fold:str.{name}",
        callsite=None,
        visits=visits,
    )


# The documented methods of ``list``/``tuple``/``dict`` that do not change the
# receiver (Library Reference, "Built-in Types": *Common Sequence Operations*,
# *Lists*, *Mapping Types*): their call on a ground receiver is answered by the
# pinned interpreter's own method (``container_method_cited_fold``).  A set is
# never handed over (``_host_ground``), so no set method is here.
_CITED_CONTAINER_METHODS = {
    list: frozenset({"copy", "count", "index"}),
    tuple: frozenset({"count", "index"}),
    dict: frozenset({"copy", "get", "items", "keys", "values"}),
}

# The mutating methods whose call value the container law reads from the
# pinned interpreter (``container_mutator_result_fold``); the receiver's
# post-state stays the law's (``floor/builtin_container_method``).
_CITED_CONTAINER_MUTATOR_RESULTS = {
    list: frozenset({"pop"}),
    dict: frozenset({"pop", "popitem", "setdefault"}),
}


def cited_container_method(receiver, name) -> bool:
    """Whether ``container_method_cited_fold`` answers ``receiver.<name>(...)``.

    ``receiver`` is a ground ``list``/``tuple``/``dict`` (``_host_ground``) and
    ``name`` one of its documented methods that do not change it.  Its
    contents must be the object's contents at this call, which the value
    says, through the one currency rule ``_host_ground`` asks of every list
    and dict it hands over (``object_identity.contents_current``: a
    construction in this frame made it, or it is the one door's post-state
    of such an object, ``xs = 'a b'.split()`` as well as a display) -- or
    it is an immutable value all the way down (a hashable tuple), whose
    contents nothing can change.  A list or dict that reached the frame by
    binding (a parameter's actual, an attribute, a global:
    ``object_identity.arrived``) is not ground (#7618:
    ``redirect_stdout.__exit__``'s ``pop``): no contents read is decided on
    it here."""
    raw = _host_ground(receiver)
    if raw is _NOT_GROUND or name not in _CITED_CONTAINER_METHODS.get(type(raw), ()):
        return False
    if type(raw) is not tuple:
        return True
    try:
        hash(raw)
    except TypeError:
        return False
    return True


def container_method_cited_fold(receiver, name, arguments, site, callsite=None):
    """``receiver.<name>(*arguments)`` on a ground container, decided, or None.

    The caller asked ``cited_container_method`` first.  When every argument
    is ground too, the outcome is the pinned interpreter's own method of the
    receiver's type applied to them, through the door a builtin over ground
    operands is decided by (``_host_applied``): ``[1, 2].index(3)`` is the one
    ``ValueError`` halt, ``[1, 2, 1].count(1)`` is ``2``,
    ``{'a': 1}.get('b')`` is ``None``.  A result the floor does not hold as a
    value (a ``dict_keys`` view) completes as the call's coordinate
    (``callsite``).  An argument known only by its type: None, and the call
    keeps the receiver's other floors."""
    visits: dict = {}
    operands = _ground_operands((receiver, *arguments), visits)
    if operands is None:
        return None
    host_type = type(operands[0])
    if name not in _CITED_CONTAINER_METHODS.get(host_type, ()):
        return None
    return _host_applied(
        getattr(host_type, name),
        operands,
        site,
        owner=f"cpython_cited_fold:{host_type.__name__}.{name}",
        callsite=callsite,
        visits=visits,
    )


def container_mutator_result_fold(receiver, name, arguments, site):
    """The value (or halt) of a mutating ``receiver.<name>(*arguments)``, or None.

    The container law (``floor/builtin_container_method``) owns the
    receiver's post-state; the call's value is the pinned interpreter's own
    method applied to a fresh host copy of a ground receiver and ground
    arguments (``_host_ground`` builds a new ``list``/``dict`` on every
    call, so the copy's mutation is seen by nothing else): ``[1, 2].pop()``
    is ``2``, ``[].pop()`` the one ``IndexError`` halt, ``{}.popitem()`` the
    one ``KeyError`` halt.  A receiver or argument known only by its type:
    None, and the law reads the member by its position."""
    visits: dict = {}
    operands = _ground_operands((receiver, *arguments), visits)
    if operands is None:
        return None
    host_type = type(operands[0])
    if name not in _CITED_CONTAINER_MUTATOR_RESULTS.get(host_type, ()):
        return None
    return _host_applied(
        getattr(host_type, name),
        operands,
        site,
        owner=f"cpython_cited_fold:{host_type.__name__}.{name}",
        callsite=None,
        visits=visits,
    )


def re_cited_fold(name, arguments, site):
    """``re.<name>(*arguments)`` (``search``/``match``/``fullmatch``), or None.

    Every operand ground (``_host_ground``): the pinned interpreter's own
    ``re.<name>`` applied to them, through the door a builtin over ground
    operands is decided by (``_host_applied``).  A match is the
    ``ReMatchValue`` of its subject and spans, no match ``None``, a builtin
    raise its one halt (``re.search('a', 5)``: ``TypeError``).  A raise that
    is no builtin exception (``re.error`` for a pattern that does not
    compile), or a match over ``bytes``, decides nothing.

    A ground ``str`` pattern and a subject known only to be a ``str``
    (``names_a_string``): ``re.<name>`` compiles the pattern first
    (``Lib/re/__init__.py``: ``_compile(pattern, flags).<name>(string)``),
    and ``_sre`` reads any ``str`` without calling its methods, so the
    pattern's compilation on the pinned interpreter decides whether the call
    can raise.  When it compiles, the call completes on the two faces of its
    predicate ``py.re_<name>(pattern, subject)`` (#8115's message atom is
    ``py.re_search``): the match (its occurrence result) where it holds,
    ``None`` where it does not, owing nothing.  A builtin raise of the
    compilation is the call's one halt; any other raise decides nothing.

    Anything else (a subject whose type is undecided, a pattern known only
    by its type, more operands): None, and the call is the one unanswered
    call."""
    import re

    from .call_symbol import call_symbol
    from .floor.call_site_value import names_a_string
    from .floor.none_value import NoneValue
    from .floor.re_match_value import ReMatchValue
    from .ir import atomic, ctor, not_
    from .occurrence import occurrence_key, occurrence_term
    from .outcome import ExitSet
    from .outcome.exit_set import partition

    owner = f"cpython_cited_fold:re.{name}"
    visits: dict = {}
    operands = _ground_operands(arguments, visits)
    if operands is not None:

        def matched(result):
            if result is None:
                return NoneValue()
            if type(result) is re.Match and type(result.string) is str:
                return ReMatchValue.of_host(result)
            return None

        return _host_applied(
            getattr(re, name),
            operands,
            site,
            owner=owner,
            callsite=None,
            visits=visits,
            holder=matched,
        )
    if len(arguments) != 2 or site is None:
        return None
    pattern_value, subject = arguments
    pattern = _host_ground(pattern_value)
    if type(pattern) is not str or not names_a_string(subject):
        return None
    terms = [value.to_term(owner=owner) for value in arguments]
    call = ctor(call_symbol(f"re.{name}"), terms, symbol_kind="builtin")
    compiled = _host_applied(
        re.compile,
        (pattern,),
        site,
        owner=owner,
        callsite=None,
        visits={},
        holder=lambda _compiled: ReMatchValue.undecided(
            ctor("python:call_result", (call, occurrence_term(site)))
        ),
    )
    if compiled is None or compiled.halts():
        return compiled
    predicate = atomic(f"py.re_{name}", terms)
    holds, fails = partition((owner, occurrence_key(site)))
    return (
        ExitSet.completed(compiled.completed_value())
        .guarded(predicate, holds)
        .union(ExitSet.completed(NoneValue()).guarded(not_(predicate), fails))
    )


def builtin_exception_cited_fold(callsite, site):
    """A bodiless call of a builtin exception class over ground actuals, decided.

    ``callsite.builtin_exception_class`` is the class the callee's binding
    names (``CallSiteSugar._applied_builtin_exception_class``), never its
    spelling.  When every actual, positional and keyword, is a ground value
    (``_host_ground``), the pinned interpreter's own class is applied to
    them through the one door a builtin over ground operands is decided by
    (``_host_applied``), and the interpreter decides what the call is:

    - ``OSError(2, 'x')`` constructs a ``FileNotFoundError`` whose ``args``
      is ``(2, 'x')`` (``OSError_new`` selects the subclass by errno);
      ``OSError('m')`` an ``OSError``; ``OSError(2, 'x', 'f').args`` is
      ``(2, 'x')``;
    - ``SyntaxError('m', 5)`` and ``ValueError('a', code=1)`` are the one
      ``TypeError`` halt.

    The completed value is the call holding the class the interpreter
    constructed, by its builtin binding (``builtin_exception_class``), and
    the ``args`` tuple it stored (``constructed_args``): each member that
    is an operand the call handed over is that actual's own floor value,
    any other member its ground floor value.  Where the call's site
    authenticated it as the raised exception (``exception_type_coordinate``)
    and the interpreter constructed another class, the coordinate is that
    class's.  A result the floor does not hold decides nothing.

    An actual known only by its type: None, and
    ``CallSiteSugar._builtin_exception_construction`` decides what the call
    is (#7757)."""
    import builtins
    from dataclasses import replace

    from .floor.builtin_exception_class_value import BuiltinExceptionClassValue
    from .floor.ground_exit import _builtin_exception_identity
    from .floor.tuple_value import TupleValue
    from .temporal.builtin_name_bindings import (
        BUILTIN_EXCEPTION_NAMES,
        builtin_name_temporal,
        canonical_builtin_exception_name,
    )

    name = getattr(callsite.builtin_exception_class, "name", None)
    if not isinstance(name, str) or name not in BUILTIN_EXCEPTION_NAMES:
        return None
    applied = getattr(builtins, name, None)
    if not isinstance(applied, type) or not issubclass(applied, BaseException):
        return None
    keyword_names = tuple(callsite.keyword_names or ())
    arg_values = tuple(callsite.arg_values)
    positional_count = len(arg_values) - len(keyword_names)
    visits: dict = {}
    operands = _ground_operands(arg_values, visits)
    if operands is None:
        return None

    def construct(*actuals):
        return applied(
            *actuals[:positional_count],
            **dict(zip(keyword_names, actuals[positional_count:])),
        )

    def instance(result):
        result_name = type(result).__name__
        if (
            result_name not in BUILTIN_EXCEPTION_NAMES
            or getattr(builtins, result_name, None) is not type(result)
        ):
            return None
        result_class = builtin_name_temporal().value_if_bound(result_name)
        if not isinstance(result_class, BuiltinExceptionClassValue):
            return None
        members = []
        for member in result.args:
            held = next(
                (
                    value
                    for operand, value in zip(operands, arg_values)
                    if operand is member
                ),
                None,
            )
            if held is None:
                held = _ground_floor(member, site, visits=visits)
            if held is None:
                return None
            members.append(held)
        constructed = replace(
            callsite,
            builtin_exception_class=result_class,
            constructed_args=TupleValue(tuple(members)),
        )
        if callsite.exception_type_coordinate is None or (
            result_name == canonical_builtin_exception_name(name)
        ):
            return constructed
        identity, mro = _builtin_exception_identity(result_name)
        return replace(
            constructed, exception_type_coordinate=identity, exception_type_mro=mro
        )

    return _host_applied(
        construct,
        operands,
        site,
        owner=f"cpython_cited_fold:{name}",
        callsite=None,
        visits=visits,
        holder=instance,
    )


@dataclass(frozen=True)
class UnknownCalleeCallV1:
    """A call nothing here answers: not bridged, stated one way.

    ``h()`` with ``h`` unbound, ``y()`` with ``y`` a formal,
    ``random.random()`` whose module was not enrolled, or a callee the export
    door cited off the enrolled population (``call-target-off-population``:
    stdlib or an unenrolled distribution, whose body was not looked at), or
    a builtin over an operand that is not a decided builtin (``len(c)``: its
    ``__len__`` is not CPython's own, ``builtin_dunder_call``), or over an
    operand decided by its type but not its value (``int(s)`` with ``s`` a
    ``str`` nothing here knows): no
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

        key = occurrence_key(site)
        # The call term names its occurrence by coordinate (#7808); `key`
        # stays the raise effect's own occurrence (listed on #7808).
        call = ctor(
            "python:unknown_callee_call",
            (str_const(self.callee_name), occurrence_term(site)),
        )
        completes = atomic("python:unknown_callee_call.completes", [call])
        # Nothing here answers this call: the one constructor makes both arms
        # owe it (#7825, H4), and the full scan writes it once as the proof's
        # `undecided` member (step 8), with the one import table's target
        # symbol when the callee is import-bound, else none (Q5).
        return ExitSet.two_faced(
            _occurrence_result(callsite, site),
            UndeterminedRaiseEffect(
                blame=str(site) if site is not None else None,
                occurrence=key if site is not None else None,
                producer_node_owner=f"UnknownCallee:{self.callee_name}",
            ),
            guard=completes,
            site=site,
            symbol=getattr(callsite, "authenticated_target_symbol", None),
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
    """The decided members a list/tuple/set display iterates, or None (a
    container whose contents are not current holds none,
    ``object_identity.contents_stale``)."""
    from .floor.list_value import ListValue
    from .floor.object_identity import contents_stale
    from .floor.set_value import SetValue
    from .floor.tuple_value import TupleValue

    if type(value) in (ListValue, TupleValue, SetValue) and not contents_stale(value):
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


def builtin_list_construct(language_callee, arg_values, keyword_names=(), site=None):
    """``list(xs)`` over a sequence whose members and order are decided.

    The callee bound to the builtin ``list`` (``LanguageCallee.BUILTIN_LIST``,
    read from its binding: a rebinding, ``list = f``, reaches no member) with
    no keywords builds a new list
    of its iterable's members in iteration order.  Over a ground operand
    (``list()``, ``list((1, 2))``) the cited fold answers first
    (``builtin_dunder_call``, ``cpython_cited_fold``); this is reached only
    when a member is not ground and the operand's shape decides: a tuple or
    list gives its elements, a dict gives its keys in insertion order, and a
    finite comprehension gives its projected members.  It never raises for
    these (``builtin_call_total``).  A set's order depends on hashing, so it
    is not decided here, and neither is any other operand -- nor a list or
    dict whose contents are not current (``object_identity.contents_stale``);
    those stay the ordinary bodiless call.  The new list is made at ``site``
    (``object_identity.made_at``).
    """
    from sugar_source_tree.nodes import LanguageCallee

    from .floor.comprehension_value import ComprehensionValue
    from .floor.dict_value import DictValue
    from .floor.list_value import ListValue
    from .floor.object_identity import contents_stale, made_at
    from .floor.tuple_value import TupleValue
    from .outcome import ExitSet

    if language_callee is not LanguageCallee.BUILTIN_LIST or keyword_names:
        return None
    if len(arg_values) != 1:
        return None
    (source,) = arg_values
    if contents_stale(source):
        return None
    if type(source) in (TupleValue, ListValue):
        members = tuple(source.elements)
    elif type(source) is DictValue:
        members = tuple(key for key, _ in source.entries)
    elif type(source) is ComprehensionValue and source.finite_elements is not None:
        members = tuple(source.finite_elements)
    else:
        return None
    return ExitSet.completed(ListValue(members, allocation=made_at(site)))


def builtin_dunder_call(language_callee, arg_values, keyword_names=()):
    """The may-raise testimony for a dunder-invoking builtin, or None.

    ``language_callee`` is the ``LanguageCallee`` the call's callee is bound
    to (its binding, never its spelling: ``len = my_len`` reaches no member).
    ``str(c)`` runs ``type(c).__str__``, ``len(c)`` its ``__len__``,
    ``sum([c])`` its ``__radd__``, ``sorted(c)`` its ``__iter__`` and the
    items' ``__lt__``.  When an operand is not a decided builtin, that dunder
    is not CPython's own: whether it exists and what it raises is not decided
    here, so the call is the one unanswered call (``UnknownCalleeCallV1``:
    two-faced, owed as ``undecided``/``unanswered``, #7757).  When every
    operand is a ground value (``builtin_ground_call``) the call is the same
    unanswered form whatever its shape, and ``cpython_cited_fold`` -- its
    one answerer -- decides it (``int('3')`` is ``3``, ``int('x')`` the one
    ``ValueError`` halt, ``len('ab')`` is ``2``).  Otherwise decided operands
    complete outright only on a shape ``builtin_call_total`` lists (an
    operand known only by its type stays unanswered).  Each names the
    builtin its binding's target symbol names."""
    dunder, shallow = _dunder_builtins()
    if language_callee not in dunder:
        return None
    builtin_name = language_callee.value.rsplit(".", 1)[1]
    if builtin_ground_call(language_callee, arg_values, keyword_names):
        return UnknownCalleeCallV1(builtin_name)
    if language_callee in shallow:
        decided = all(_builtin_container(value) for value in arg_values)
    else:
        decided = all(builtin_typed_value(value) for value in arg_values)
    if decided and builtin_call_total(language_callee, arg_values, keyword_names):
        return None
    return UnknownCalleeCallV1(builtin_name)
