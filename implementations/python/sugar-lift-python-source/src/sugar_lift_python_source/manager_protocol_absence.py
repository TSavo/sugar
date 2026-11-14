"""Prove, from source, that a class's instances lack ``__enter__``/``__exit__``.

``with x:`` looks the protocol up on ``type(x)``'s MRO only.  An absence proof
therefore walks the C3 MRO of the class (the same linearization law the Floor
uses, :func:`sugar_lift_py_tests.floor.class_definition_value.c3_tail`) and
requires every class on it to be either

* a module-level ``class`` statement whose body is read here -- no class
  decorators, no metaclass or other class keywords, a body of plain method
  definitions and simple name assignments whose calls are only to unshadowed
  builtins, no ``__new__`` (construction must return the instance) and no
  ``__init_subclass__`` (a base could install the protocol on a subclass); or
* a cited language base, ``object`` or ``abc.ABC``, whose attribute sets are
  read from the running interpreter (never transcribed).

A base is recognised by its binding (``SourceUnit.language_callee_of``: the
one import table, then the builtin namespace nothing rebinds), never by its
spelling.  A method decorator is admitted only where it leaves the method a
plain function: a builtin method descriptor constructor, or a decorator the one
decorator application answers as returning its argument
(``sugar_source_tree.nodes.builtin_decorator_step``, #7757).

Any base that is neither keeps the use a runtime-selected gap.  The defining
module must also never store ``__enter__``/``__exit__``/``__class__`` as an
attribute, never call ``setattr``/``delattr`` where it could name them, and
never call ``exec``/``eval``/``globals``/``locals``/``vars``.  Each callee is
known by the binding its read reaches (``SourceUnit.language_callee_of`` and
``SourceUnit.reads_dynamic_global_writer``), never by its spelling: a
module's own ``exec`` is none of these, and ``from builtins import setattr as
put`` makes ``put`` one.

The proof answers which of the two names the MRO binds; when one is missing
the ``with`` halts with the interpreter's own observed ``TypeError``.
"""

from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.manager_protocol_absence_refusal import (
    PROTOCOL_NAMES,
    cited_language_base,
)

_FORBIDDEN_STORES = frozenset({*PROTOCOL_NAMES, "__class__"})
_FORBIDDEN_CLASS_NAMES = frozenset({"__new__", "__init_subclass__"})


@dataclass(frozen=True)
class ManagerProtocolAbsenceV1:
    """Source proof that ``type_name`` instances miss part of the protocol."""

    type_name: str
    has_enter: bool
    has_exit: bool
    # Qualified names of the MRO, head first (source classes by module and
    # name, cited bases by their interpreter names).
    linearization: tuple[str, ...]


class _Entry:
    """One MRO member compared by identity (source node or cited base)."""

    def __init__(self, key, class_def=None, cited=None):
        self.key = key
        self.class_def = class_def
        self.cited = cited
        self.bases = ()

    def __eq__(self, other):
        return isinstance(other, _Entry) and other.key == self.key

    def __hash__(self):
        return hash(self.key)


def prove_manager_protocol_absence(class_def) -> ManagerProtocolAbsenceV1 | None:
    """The absence proof for ``class_def``'s instances, or None when unproven."""
    from sugar_source_tree.nodes import LanguageCallee
    from sugar_source_tree.panic import SugarNotWritten

    from sugar_lift_py_tests.floor.class_definition_value import c3_tail

    entries: dict = {}
    if _resolve_source_class(class_def, entries) is None:
        return None
    head = entries[("source", id(class_def))]
    tails: dict = {}

    def tail_of(entry):
        if entry in tails:
            return tails[entry]
        if entry.cited is not None:
            # A cited base's own MRO is the interpreter's: its tail is the
            # cited classes after it (``abc.ABC`` -> ``object``).
            tail = tuple(_cited_entry(callee, entries) for callee in entry.cited.tail)
        else:
            tail = c3_tail(
                _direct_bases(entry, entries),
                tail_of,
                blame=entry.class_def.fragment,
                owner="prove_manager_protocol_absence",
            )
        tails[entry] = tail
        return tail

    try:
        mro = (head, *tail_of(head))
    except SugarNotWritten:
        return None
    if not any(
        entry.cited is not None and entry.cited.callee is LanguageCallee.BUILTIN_OBJECT
        for entry in mro
    ):
        return None
    present: set[str] = set()
    for entry in mro:
        if entry.cited is not None:
            if entry.cited.metaclass_overrides_call:
                return None
            if entry.cited.subclass_gains & set(PROTOCOL_NAMES):
                return None
            present |= entry.cited.protocol_names
        else:
            present |= _class_scope_names(entry.class_def) & set(PROTOCOL_NAMES)
    if _leaves_an_abstract_method(mro):
        # Construction itself would raise (an abstract class): not this law.
        return None
    has_enter = "__enter__" in present
    has_exit = "__exit__" in present
    if has_enter and has_exit:
        return None
    return ManagerProtocolAbsenceV1(
        type_name=class_def.name,
        has_enter=has_enter,
        has_exit=has_exit,
        linearization=tuple(_entry_name(entry) for entry in mro),
    )


def _leaves_an_abstract_method(mro) -> bool:
    """Whether the most-derived binding of some ``abc.abstractmethod`` name is
    itself abstract (instantiation would raise before any ``with``).

    A method is abstract when a decorator's binding is ``abc.abstractmethod``
    (``@abc.abstractmethod`` or ``@abstractmethod`` imported from ``abc``)."""
    from sugar_source_tree.nodes import AsyncFunctionDef, FunctionDef, LanguageCallee

    def abstract_names(class_def):
        unit = class_def.unit
        names = set()
        for statement in class_def.body:
            if isinstance(statement, (FunctionDef, AsyncFunctionDef)) and any(
                unit.language_callee_of(d) is LanguageCallee.ABC_ABSTRACTMETHOD
                for d in statement.decorators
            ):
                names.add(statement.name)
        return names

    sources = [entry.class_def for entry in mro if entry.cited is None]
    declared_abstract = set().union(*(abstract_names(c) for c in sources))
    for name in declared_abstract:
        owner = next(c for c in sources if name in _class_scope_names(c))
        if name in abstract_names(owner):
            return True
    return False


def _entry_name(entry) -> str:
    if entry.cited is not None:
        return entry.cited.qualified_name
    return f"{entry.class_def.unit.filename}:{entry.class_def.name}"


def _cited_entry(callee, entries):
    key = ("cited", callee)
    if key not in entries:
        cited = cited_language_base(callee)
        if cited is None:
            raise _Unproven(callee)
        entries[key] = _Entry(key, cited=cited)
    return entries[key]


class _Unproven(Exception):
    pass


def _direct_bases(entry, entries):
    return entry.bases


def _resolve_source_class(class_def, entries):
    """Read one source class and (recursively) its bases; None when unproven."""
    key = ("source", id(class_def))
    if key in entries:
        return entries[key]
    from sugar_source_tree.nodes import LanguageCallee

    entry = _Entry(key, class_def=class_def)
    entries[key] = entry
    try:
        if not _module_admits_absence_proof(class_def.unit):
            raise _Unproven("module")
        if not _class_statement_admits_absence_proof(class_def):
            raise _Unproven("class statement")
        bases = []
        for base in class_def.bases:
            resolved = _resolve_base(base, class_def.unit, entries, class_def)
            if resolved is None:
                raise _Unproven("base")
            bases.append(resolved)
        if not bases:
            # The language's implicit base of a ``class`` statement.
            bases.append(_cited_entry(LanguageCallee.BUILTIN_OBJECT, entries))
        entry.bases = tuple(bases)
    except _Unproven:
        del entries[key]
        return None
    return entry



def _precedes(earlier, later) -> bool:
    """A base class statement must run before the class statement naming it."""
    first = earlier.line_col_span()
    second = later.line_col_span()
    return (first.end_line, first.end_col) <= (second.start_line, second.start_col)


def _resolve_base(base, unit, entries, derived):
    from sugar_source_tree.nodes import ClassDef, Name

    # A language base by its binding (``object`` nothing rebinds, ``abc.ABC``
    # under ``import abc``, ``ABC`` under ``from abc import ABC``); a binding
    # no citation answers for leaves the base unproven.
    callee = unit.language_callee_of(base)
    if callee is not None:
        return _cited_entry(callee, entries)
    if not isinstance(base, Name):
        return None
    # A source base by the binding the read reaches at its own coordinate
    # (``SourceUnit.module_definition_at``): a parameter, local, free or
    # nonlocal of the function around the class statement is that binding,
    # never the module's ``class`` statement of the same name.
    bound = unit.module_definition_at(base.id, base.line_col_span())
    if not isinstance(bound, ClassDef) or not _precedes(bound, derived):
        return None
    return _resolve_source_class(bound, entries)


def _class_statement_admits_absence_proof(class_def) -> bool:
    from sugar_source_tree.nodes import (
        AnnAssign,
        Assign,
        AsyncFunctionDef,
        Constant,
        Expr,
        FunctionDef,
        Name,
        Pass,
    )

    if class_def.decorators or class_def.keywords or class_def.type_params:
        return False
    unit = class_def.unit
    for statement in class_def.body:
        if isinstance(statement, (FunctionDef, AsyncFunctionDef)):
            if statement.name in _FORBIDDEN_CLASS_NAMES:
                return False
            if not all(
                _decorator_keeps_the_function(statement, d)
                for d in statement.decorators
            ):
                return False
            if not all(_expression_is_inert(d, unit) for d in statement.decorators):
                return False
            continue
        if isinstance(statement, Pass):
            continue
        if isinstance(statement, Expr):
            if not isinstance(statement.value, Constant):
                return False
            continue
        if isinstance(statement, Assign):
            if not all(isinstance(target, Name) for target in statement.targets):
                return False
            if any(t.id in _FORBIDDEN_CLASS_NAMES for t in statement.targets):
                return False
            if not _expression_is_inert(statement.value, unit):
                return False
            continue
        if isinstance(statement, AnnAssign):
            if not isinstance(statement.target, Name):
                return False
            if statement.target.id in _FORBIDDEN_CLASS_NAMES:
                return False
            if statement.value is not None and not _expression_is_inert(
                statement.value, unit
            ):
                return False
            continue
        return False
    return True


def _class_scope_names(class_def) -> set[str]:
    from sugar_source_tree.nodes import AnnAssign, Assign, AsyncFunctionDef, FunctionDef

    names: set[str] = set()
    for statement in class_def.body:
        if isinstance(statement, (FunctionDef, AsyncFunctionDef)):
            names.add(statement.name)
        elif isinstance(statement, Assign):
            names.update(target.id for target in statement.targets)
        elif isinstance(statement, AnnAssign) and statement.value is not None:
            names.add(statement.target.id)
    return names


def _decorator_keeps_the_function(method, decorator) -> bool:
    """Whether ``decorator`` of the class-body ``method`` binds the method's
    name to a function or a builtin method descriptor of it.

    A builtin method descriptor constructor (``classmethod``, ``staticmethod``,
    ``property``, the class body's one descriptor table) is admitted by its
    binding.  Any other decorator is the one decorator application's
    (``builtin_decorator_step``): admitted only where that application
    returns its argument (``typing.final``, ``abc.abstractmethod``).  A source
    or imported decorator may return anything and is not admitted.
    """
    from sugar_source_tree.nodes import (
        METHOD_DESCRIPTOR_KINDS,
        builtin_decorator_step,
    )

    if method.unit.language_callee_of(decorator) in METHOD_DESCRIPTOR_KINDS:
        return True
    step = builtin_decorator_step(method, decorator)
    return step is not None and step.kind == "identity"


def _expression_is_inert(expression, unit) -> bool:
    """No walrus, no lambda-free surprises: calls only to unshadowed builtins."""
    from sugar_source_tree.nodes import Call, Name, NamedExpr

    for node in expression.walk():
        if isinstance(node, NamedExpr):
            return False
        if isinstance(node, Call):
            # The builtin is known by the read's binding at its coordinate
            # (``SourceUnit.builtin_reference_at``), never a second resolver.
            if (
                not isinstance(node.func, Name)
                or unit.builtin_reference_at(node.func.id, node.func.line_col_span())
                is None
            ):
                return False
            if unit.reads_dynamic_global_writer(node.func) or _writes_an_attribute(
                unit, node.func
            ):
                return False
    return True


def _writes_an_attribute(unit, callee) -> bool:
    """Whether the read ``callee`` is bound to ``setattr`` or ``delattr``:
    known by its binding at the read (``SourceUnit.language_callee_of``),
    never by its spelling."""
    from sugar_source_tree.nodes import LanguageCallee

    return unit.language_callee_of(callee) in (
        LanguageCallee.BUILTIN_SETATTR,
        LanguageCallee.BUILTIN_DELATTR,
    )


def _module_admits_absence_proof(unit) -> bool:
    """No statement in the module may install, remove or retarget the protocol."""
    return _scan_module(unit)


def _scan_module(unit) -> bool:
    from sugar_source_tree.nodes import (
        AnnAssign,
        Assign,
        AsyncFor,
        AsyncWith,
        Attribute,
        AugAssign,
        Call,
        Constant,
        Delete,
        DeleteAttribute,
        For,
        ImportFrom,
        With,
    )

    module = getattr(unit, "typed_module", None)
    if module is None:
        return False
    for node in module.walk():
        if isinstance(node, ImportFrom) and any(a.name == "*" for a in node.names):
            return False
        if isinstance(node, DeleteAttribute) and node.attr in _FORBIDDEN_STORES:
            return False
        targets = ()
        if isinstance(node, (Assign, Delete)):
            targets = node.targets
        elif isinstance(node, (AugAssign, AnnAssign, For, AsyncFor)):
            targets = (node.target,)
        elif isinstance(node, (With, AsyncWith)):
            targets = tuple(
                item.optional_vars for item in node.items if item.optional_vars
            )
        for target in targets:
            for leaf in target.walk():
                if isinstance(leaf, Attribute) and leaf.attr in _FORBIDDEN_STORES:
                    return False
        if not isinstance(node, Call):
            continue
        # The callee is the binding its read reaches, never its spelling.
        if unit.reads_dynamic_global_writer(node.func):
            return False
        if _writes_an_attribute(unit, node.func):
            if len(node.args) < 2:
                return False
            # A computed attribute name may be anything, on any receiver: a
            # module bound by ``import`` holds the bases a class statement
            # reads (``abc.ABC``), so only a constant name not in the
            # protocol is admitted.
            attribute = node.args[1]
            if not isinstance(attribute, Constant):
                return False
            if attribute.value in _FORBIDDEN_STORES:
                return False
    return True
