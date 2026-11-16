"""A method call on an instance whose class the method does not know (#7757
step 8): the receiver's class is an input of the contract, and the call is
its coordinate plus an edge resolved at prove through that input.

The owner's ruling of 2026-11-15, "Edge, join at prove": every same-file call
is a coordinate plus an edge, joined at prove; the lifter never follows a
body.  Every method call is the one dispatched edge, and prove alone looks
the method up (#7757 entry 6: one MRO lookup): on an instance whose class is
decided here its class rides with it (``class_value``); ``Cls.m(...)`` and
``super().m(...)`` name where to look (``lookup_term``).  Where the class is
not decided here -- ``self.m()`` in a method's own proof, a method of a
parameter -- it is an input of the contract, ``class:<param>``
(``contract_input.CLASS_INPUT``, ``nodes._receiver_class_parameters``), as a
module global is ``global:<name>``.  The call stands as:

    call:dispatch:<m>(<receiver>, <args>..., py.kwarg(...)...,
                      py.class("0", <receiver class>), py.class(<key>, ...)...)

with an edge whose member names the method alone (``python:dispatch:<m>``).
A caller that knows the class of an argument supplies it, keyed by the
argument (its position in decimal digits, or its keyword):
``py.class(<key>, python:instance(<class symbol>, <field>...))``
(``class_arguments``).  Prove's one binder binds ``class:<param>`` from it,
and the one resolution (``consistency::dispatched_symbol``) looks the method
up on the order the class's own proof states (``tree_enumerate.
class_namespace_row``) and joins that function's contract.  Where nothing
binds a decided class, the call is the owed member: never a guessed target.

One binder, one resolution: nothing here resolves a method.
"""

from __future__ import annotations

#: The call target of a dispatched method call: ``dispatch:<m>``; its edge's
#: member symbol is ``python:dispatch:<m>``, a symbol no definition is
#: spelled with (``consistency::DISPATCH_SYMBOL_PREFIX``).
DISPATCH_TARGET_PREFIX = "dispatch:"

#: The mark of a dispatched attribute read after the prefix:
#: ``dispatch:.<name>`` is the read ``obj.<name>`` a property's getter
#: answers at prove, ``dispatch:<m>`` the call ``obj.<m>(...)``
#: (``consistency::DISPATCH_READ_MARK``).  No Python name starts with ``.``.
DISPATCH_READ_MARK = "."

#: The mark after which a call's member symbol names the operands that may
#: share an object (``object_identity.shared_pairs``, ``shares_mark``):
#: ``python:dispatch:<m>#0~1,0~k`` for a dispatched call,
#: ``python:<mod>.<f>#0~1,0~global:G`` for a same-file definition's
#: (``lambda_callable.definition_edge_call``) -- each pair by its keys (a
#: position, a keyword, or a ``cell:``/``global:`` input), joined by
#: ``DISPATCH_SHARED_PAIR``.  Whether the callee changes the shared object
#: through either is its contract's to state (``python:leaves``), so it is
#: prove that asks, for every call alike
#: (``consistency::DISPATCH_SHARES_MARK``).  No Python name holds ``#``.
DISPATCH_SHARES_MARK = "#"
DISPATCH_SHARED_PAIR = "~"


def shares_mark(keyed) -> str:
    """The suffix of a call's member symbol naming each pair of its operands
    that may share an object (``DISPATCH_SHARES_MARK``), or ``""`` where none
    may.  ``keyed`` is ``((key, value), ...)``: every value the call binds a
    formal or an input of the callee's contract to, each under the key prove
    reads it by.  The one place the pairs are spelled, for a dispatched call
    and a same-file definition's call alike (#7757 step 9: the alias risk is
    decided at prove, from the callee's contract)."""
    from sugar_lift_py_tests.floor.object_identity import shared_pairs

    keyed = tuple(keyed)
    pairs = shared_pairs(tuple(value for _key, value in keyed))
    if not pairs:
        return ""
    return DISPATCH_SHARES_MARK + ",".join(
        keyed[left][0] + DISPATCH_SHARED_PAIR + keyed[right][0]
        for left, right in pairs
    )

#: ``python:instance(<class symbol>, <field>...)``: a decided instance's
#: class, as a caller binds a class input to it; the fields are every name
#: its ``__dict__`` may hold at the call (``consistency::PYTHON_INSTANCE``).
INSTANCE = "python:instance"

#: ``python:constructed(<class symbol>)``: the class of a same-file class
#: call's result as it stands where its construction left it -- an instance
#: of that class whose ``__dict__`` holds what the class's contract states
#: on every completed face (``constructed_class_facts``).  Prove binds it to
#: ``python:instance(<class symbol>, <field>...)`` read off that statement
#: (``consistency::PYTHON_CONSTRUCTED``) before it dispatches.
CONSTRUCTED = "python:constructed"

#: ``python:type_is(<object>, <class symbol>)``: ``type(<object>)`` is the
#: class the symbol names (``consistency::PYTHON_TYPE_IS``).  A class's
#: contract states it of the instance it makes.
TYPE_IS = "python:type_is"

#: ``python:isinstance(<object>, <class symbol>)``: the ``bool``
#: ``isinstance(<object>, <class>)`` returns, for a source class whose
#: metaclass is ``type`` (``ClassDefinitionValue.test_python_type``).  Prove
#: states it ``true`` where a contract states ``python:type_is(<object>, D)``
#: and ``D``'s order contains the class (``consistency::with_isinstance_law``),
#: and ``false`` where it does not and ``x.__class__`` is decided to be
#: ``object.__class__``'s getter (``ISINSTANCE_COMPLETES``).
ISINSTANCE = "python:isinstance"

#: ``python:isinstance.completes(<isinstance term>, <occurrence key>)``: the
#: type test completes (``type(x)`` a subclass of the class, or ``x.__class__``
#: read by ``object.__class__``'s getter alone).  Prove states it where a
#: contract states ``python:type_is(<object>, D)`` and ``D``'s namespace rows
#: decide it (``consistency::isinstance_law_facts``); its complement is the
#: test's owed halt face.
ISINSTANCE_COMPLETES = "python:isinstance.completes"

#: ``python:may_hold(<object>, <name>)``: the object's ``__dict__`` may hold
#: ``<name>`` (``consistency::PYTHON_MAY_HOLD``), one fact per name.
MAY_HOLD = "python:may_hold"

#: ``python:holds_decided(<object>)``: the ``python:may_hold`` facts stated
#: beside it of ``<object>`` are every name its ``__dict__`` may hold beyond
#: what it held before the call that states them: an ``__init__``'s
#: contract of its receiver (``UniverseValue.receiver_holds_facts``, #7757
#: B2; ``consistency::PYTHON_HOLDS_DECIDED``).
HOLDS_DECIDED = "python:holds_decided"

#: ``python:class_undecided(<object>)``: what the object's class is, or what
#: its ``__dict__`` holds, is not decided (``consistency::
#: PYTHON_CLASS_UNDECIDED``).
CLASS_UNDECIDED = "python:class_undecided"

#: The named argument that supplies a class input (``consistency::
#: PYTHON_CLASS``).
CLASS_ARGUMENT = "py.class"

#: ``py.lookup(<on>, <after>)``: where a dispatched call looks its method up
#: when that is not the instance its first argument is, from the first class
#: of that instance's order (``consistency::PYTHON_LOOKUP``).  ``<on>`` is
#: the join symbol of the class object the method is read off (``Cls.m(...)``,
#: ``super()`` in a ``classmethod``: no receiver among the arguments), ``""``
#: for the instance; ``<after>`` the join symbol of the class after which
#: the lookup starts in the order (zero-argument ``super()``), ``""`` for the
#: first class.  It is part of the call's term: two calls that look a method
#: up from different places are never one term.
LOOKUP_ARGUMENT = "py.lookup"


def lookup_term(on: str | None, after: str | None):
    """``py.lookup("<on>", "<after>")`` (``LOOKUP_ARGUMENT``)."""
    from sugar_lift_py_tests.ir import ctor, str_const

    return ctor(LOOKUP_ARGUMENT, [str_const(on or ""), str_const(after or "")])

#: ``python:plain_store(<class>, <field>)``: a store of ``<field>`` on an
#: instance of ``<class>`` is the plain ``__dict__`` store, and a read of the
#: field afterwards is that entry (#7757 step 7).  Stated over a class input
#: (``class:<param>``) as the guard of what a callee stores on a parameter;
#: prove decides it on the class's namespace row once a caller binds the
#: input (``consistency::plain_store_holds``), and nothing else ever does.
PLAIN_STORE = "python:plain_store"


def plain_store_atom(class_term, name: str):
    """``python:plain_store(<class_term>, "<name>")`` (``PLAIN_STORE``)."""
    from sugar_lift_py_tests.ir import atomic, str_const

    return atomic(PLAIN_STORE, [class_term, str_const(name)])


def is_dunder(name: str) -> bool:
    """Whether ``name`` is spelled ``__<x>__``: ``object``'s own data
    descriptors (``__class__``, ``__dict__``) are such names, and no
    namespace row states them, so no plain store of one is ever stated."""
    return len(name) > 4 and name.startswith("__") and name.endswith("__")


def stored_class_input(receiver, name: str, unit):
    """The class input a store ``receiver.<name> = v`` is guarded by
    (``plain_store_atom``), or None: ``receiver`` is the plain value of a
    positional or keyword parameter of the function whose own proof this is,
    whose class is an input of its contract (``class_input_formals``), in a
    module that gives no object another class and stores no computed name
    (``module_attribute_names``), and ``name`` is no dunder name.  Its value
    is the formal ``class:<param>``."""
    from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
    from sugar_lift_py_tests.formal_parameter import FormalParameterCoordinateV1

    if unit is None or is_dunder(name):
        return None
    coordinate = getattr(receiver, "formal_coordinate", None)
    if (
        type(receiver) is not SymbolicValue
        or not isinstance(coordinate, FormalParameterCoordinateV1)
        or coordinate.parameter_kind not in _PARAMETER_KINDS
        or coordinate.coordinate_cid not in class_input_formals(unit)
        or module_attribute_names(unit)[1]
    ):
        return None
    from sugar_lift_py_tests.contract_input import CLASS_INPUT, input_formal

    return input_formal(CLASS_INPUT, coordinate.declared_name)


#: ``python:plain_read(<class>, <field>)``: a read of ``<field>`` on an
#: instance of ``<class>`` is its ``__dict__`` entry by Python's own rule --
#: no ``__getattribute__`` or ``__getattr__`` and no binding of the name
#: (a data descriptor would win over the entry) in the order of ``<class>``
#: (``consistency::PYTHON_PLAIN_READ``, decided on the namespace rows).
PLAIN_READ = "python:plain_read"

# A read of any of these names, or of these attributes, may store any name
# on any object: ``setattr(o, name, v)``, ``vars(o)[name] = v``,
# ``o.__dict__[name] = v``, ``object.__setattr__(o, name, v)`` -- and so
# ``setattr(o, "__class__", C)`` and ``object.__setattr__(o, "__class__",
# C)``, which give ``o`` another class.
_DYNAMIC_NAMES = frozenset({"setattr", "delattr", "vars"})
_DYNAMIC_ATTRIBUTES = frozenset({"__dict__", "__setattr__", "__delattr__"})

# A store to (or delete of) this attribute anywhere in the module may give an
# object another class: ``o.__class__ = C`` (``object.__class__``'s setter,
# ``object_set_class``).  A class input bound to the class the caller saw,
# or the class an instance was made of, would then name a class the object
# no longer has, so the module is dynamic exactly as for ``setattr``.  A read
# (``self.__class__.__name__``) changes nothing.
_CLASS_ATTRIBUTE = "__class__"

# Module -> (module, answer), the last few typed modules read.
_ATTRIBUTE_NAMES: dict = {}


def module_attribute_names(unit) -> tuple:
    """``(names, dynamic)`` for the module ``unit`` holds: every attribute
    name the module spells anywhere but as the callee of a call
    (``o.m(...)``) -- a store ``o.n = v``, ``del o.n``, a read ``o.n`` -- and
    whether it spells a way to store a computed name (``setattr``, ``vars``,
    ``__dict__``, ``__setattr__``) or to give an object another class (a
    store to or delete of ``o.__class__``, ``_class_stores``).

    A method call on a parameter is dispatched only for a name this module
    never spells otherwise (``dispatch_on_receiver``): a store of a field of
    that name in the frame before the call would leave the formal standing
    as it was (``ReceiverFieldStoreStateSugar``), and the field would shadow
    the method.  In a dynamic module nothing is dispatched over a class
    input: the class a caller binds it to may not be the object's class at
    the call.  Read once per typed module."""
    from sugar_source_tree.nodes import Attribute, Call, Name

    module = getattr(unit, "typed_module", None)
    if module is None:
        return frozenset(), True
    held = _ATTRIBUTE_NAMES.get(id(module))
    if held is not None and held[0] is module:
        return held[1]
    nodes = []
    for statement in module.body:
        nodes.extend(statement.walk())
    callees = {
        id(node.func)
        for node in nodes
        if isinstance(node, Call) and isinstance(node.func, Attribute)
    }
    names = set()
    dynamic = _class_stores(nodes)
    for node in nodes:
        if isinstance(node, Attribute):
            if node.attr in _DYNAMIC_ATTRIBUTES:
                dynamic = True
            if id(node) not in callees:
                names.add(node.attr)
        elif isinstance(node, Name) and node.id in _DYNAMIC_NAMES:
            dynamic = True
    answer = (frozenset(names), dynamic)
    if len(_ATTRIBUTE_NAMES) >= 8:
        _ATTRIBUTE_NAMES.clear()
    _ATTRIBUTE_NAMES[id(module)] = (module, answer)
    return answer


def _class_stores(nodes) -> bool:
    """Whether any of ``nodes`` stores to or deletes ``<x>.__class__``: an
    attribute ``__class__`` in a target position -- an assignment's target
    (plain, augmented, annotated), a ``del``, a ``for`` or comprehension
    target, a ``with ... as`` target -- at any depth of a tuple, list or
    starred target."""
    from sugar_source_tree.nodes import (
        AnnAssign,
        Assign,
        AsyncFor,
        Attribute,
        AugAssign,
        Comprehension,
        Delete,
        For,
        List,
        Starred,
        Tuple_,
        WithItem,
    )

    targets = []
    for node in nodes:
        if isinstance(node, (Assign, Delete)):
            targets.extend(node.targets)
        elif isinstance(node, (AugAssign, AnnAssign, For, AsyncFor, Comprehension)):
            targets.append(node.target)
        elif isinstance(node, WithItem) and node.optional_vars is not None:
            targets.append(node.optional_vars)
    while targets:
        target = targets.pop()
        if isinstance(target, Attribute):
            if target.attr == _CLASS_ATTRIBUTE:
                return True
        elif isinstance(target, (Tuple_, List)):
            targets.extend(target.elts)
        elif isinstance(target, Starred):
            targets.append(target.value)
    return False


def instance_term(symbol: str, fields=()):
    """``python:instance(<symbol>, <field>...)``, the fields in name order."""
    from sugar_lift_py_tests.ir import ctor, str_const

    return ctor(
        INSTANCE,
        [str_const(symbol), *(str_const(name) for name in sorted(fields))],
    )


def constructed_term(symbol: str):
    """``python:constructed(<symbol>)``: an instance of the class ``symbol``
    names as its construction left it (``CONSTRUCTED``)."""
    from sugar_lift_py_tests.ir import ctor, str_const

    return ctor(CONSTRUCTED, [str_const(symbol)])


def constructed_class_facts(instance, constructed):
    """What a class's constructor contract states of the class of the
    instance it makes, on one completed face (#7757 step 8), ``constructed``
    the term the contract names that instance by (``python:after(out,
    "out")``):

    - ``python:type_is(<constructed>, <class symbol>)``: the class the
      construction made it of (``class_value``);
    - ``python:may_hold(<constructed>, <name>)`` for every name its
      ``__dict__`` holds where it is left (``class_value``'s fields).

    Prove reads them off the row (``consistency::initialized_instance``):
    the class and the union of the names over every completed face is the
    ``python:instance(<class symbol>, <field>...)`` a caller's
    ``python:constructed(<class>)`` is bound to before a method on the
    result is dispatched.  Each is an atom of fixed arity, never a
    ``python:instance`` term, whose arity varies with its fields.

    Where the face does not decide them -- an instance handed to code or
    otherwise not current, one whose ``__class__`` was stored, no class
    symbol, anything but an instance -- it states only
    ``python:class_undecided(<constructed>)``: prove binds no class, and the
    dispatch over the result stays owed by name."""
    from sugar_lift_py_tests.floor.object_value import ObjectValue
    from sugar_lift_py_tests.ir import atomic

    term = None
    if isinstance(instance, ObjectValue) and "__class__" not in (
        item.name for item in instance.fields
    ):
        term = class_value(instance)
    if term is None:
        return [atomic(CLASS_UNDECIDED, [constructed])]
    symbol, *fields = term.args
    return [
        atomic(TYPE_IS, [constructed, symbol]),
        *(atomic(MAY_HOLD, [constructed, field]) for field in fields),
    ]


def class_value(value):
    """The class ``value``'s class input is bound to at a call, or None when
    it is not decided here:

    - an instance of a source class a construction in this frame made, whose
      fields are its fields now (``object_identity.contents_current``): its
      class's join symbol and those fields;
    - the result of a call of a same-file class that ``type.__call__``
      makes with a builtin ``__new__`` (``CallSiteValue.instance_of``), as
      that construction left it (``constructed_by_edge``: a store on it or
      code it is handed leaves another value):
      ``python:constructed(<class symbol>)``, bound at prove to the class
      and fields the class's contract states on every completed face
      (``constructed_term``).  The lift never reads what its ``__init__``
      left;
    - a value of a builtin class the lifter itself decides
      (``builtin_class_name``: a list, dict or set it constructed, a tuple,
      a ``str``, an ``int``): ``python:builtin("<name>")``, the class object
      the builtin namespace binds (#7757 step 7).  Its class is exact -- no
      floor here holds an instance of a subclass -- and a builtin
      instance's ``__class__`` cannot be stored, so the class is the one
      the object has wherever the callee reads it.  Prove applies a
      builtin method's law only where the input is bound to it.

    Anything else -- an instance that arrived by binding, a formal, a call's
    result of any other class -- is None: no class is supplied."""
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.floor.object_identity import contents_current
    from sugar_lift_py_tests.floor.object_value import ObjectValue

    if isinstance(value, CallSiteValue):
        symbol = getattr(value, "instance_of", None)
        if symbol and getattr(value, "constructed_by_edge", False):
            return constructed_term(symbol)
        return None
    if isinstance(value, ObjectValue) and contents_current(value):
        definition = getattr(value.defining_class, "class_definition", None)
        if definition is None:
            return None
        symbol = definition.bridge_source_symbol()
        if symbol is None:
            return None
        fields = {item.name for item in value.fields}
        fields -= set(value.deleted_instance_fields)
        return instance_term(symbol, fields)
    builtin = builtin_class_name(value)
    if builtin is not None:
        return builtin_class_term(builtin)
    return None


#: ``python:builtin("<name>")``: the class object the builtin namespace binds
#: under ``<name>`` (``temporal.builtin_name_bindings``), as a caller binds
#: a class input to it (``consistency::PYTHON_BUILTIN_CLASS``).
BUILTIN_CLASS = "python:builtin"


def builtin_class_term(name: str):
    """``python:builtin("<name>")``: the builtin class ``name``."""
    from sugar_lift_py_tests.ir import ctor, str_const

    return ctor(BUILTIN_CLASS, [str_const(name)])


def builtin_class_name(value):
    """The name of the builtin class ``value`` is an exact instance of, where
    the lifter itself decides it, else None: a ``list``, ``dict`` or ``set``
    the lifter constructed (``builtin_container_method.container_kind``), a
    ``tuple``, a ``str``, an ``int`` (never a ``bool``: ``type(True)`` is
    ``bool``).  A value standing for a formal (``formal_coordinate``) is the
    caller's, and its class is not decided here."""
    from sugar_lift_py_tests.floor import builtin_container_method as law
    from sugar_lift_py_tests.floor.string_value import StringValue
    from sugar_lift_py_tests.floor.term_value import TermValue
    from sugar_lift_py_tests.floor.tuple_value import TupleValue

    if getattr(value, "formal_coordinate", None) is not None:
        return None
    kind = law.container_kind(value)
    if kind is not None:
        return kind
    if type(value) is TupleValue:
        return "tuple"
    if type(value) is StringValue:
        return "str"
    if type(value) is TermValue and type(value.value) is int:
        return "int"
    return None


def class_arguments(positional, keywords, *, shift: int = 0) -> list:
    """``py.class(<key>, <class>)`` for each actual whose class is decided
    here (``class_value``): a positional actual keyed by its position (plus
    ``shift``) in decimal digits, a keyword actual by its keyword.  Prove's
    one binder binds each to the ``class:<param>`` input of the parameter
    that argument binds, where the callee's contract takes one.  A captured
    cell's value is keyed by the input it supplies, ``cell:<name>``
    (``lambda_callable.definition_edge_call``), and binds
    ``class:cell:<name>``: the class of the formal that argument binds, the
    one input kind."""
    from sugar_lift_py_tests.ir import ctor, str_const

    arguments = []
    for position, value in enumerate(positional):
        term = class_value(value)
        if term is not None:
            arguments.append(
                ctor(CLASS_ARGUMENT, [str_const(str(position + shift)), term])
            )
    for name, value in keywords:
        term = class_value(value)
        if term is not None:
            arguments.append(ctor(CLASS_ARGUMENT, [str_const(name), term]))
    return arguments


def dispatch_on_receiver(
    name, receiver, positional, kw_values, site, *, unit, halted_at=None
):
    """``receiver.name(*positional, **kw_values)`` as its coordinate and the
    dispatched edge (``dispatch_edge_call``) when its receiver's class is a
    class input here, else None (the call takes the path it took before):

    - ``receiver`` is the plain value of a positional or keyword parameter
      of the function whose own proof this is (``FormalParameterCoordinateV1``
      on a ``SymbolicValue``): its class is ``class:<param>``, unbound here.
      Only for a method name this module never spells as anything but a
      callee (``module_attribute_names``): a field of that name stored on
      the formal in the frame would shadow the method unseen;
    - ``receiver`` is the plain value of a captured cell of the function
      whose own proof this is (its ``cell:<name>`` input,
      ``ContractInputCoordinateV1``) whose class is an input too
      (``nodes._receiver_class_cells``): its class is ``class:cell:<name>``,
      under the same method-name guard (#7757 step 7).  An ``__init__``'s
      receiver is such a formal (#7757 B2): its class is ``class:<self>``,
      bound by the caller -- the class call's dispatched ``__init__`` edge,
      or ``super().__init__()`` from a subclass;
    - ``receiver`` is a same-file class's call result that ``type.__call__``
      makes with a builtin ``__new__`` (``class_value``:
      ``python:constructed(<class>)``), in a module that is not dynamic
      (``module_attribute_names``: no computed store, no ``__class__``
      store): prove binds its class to what the class's contract states and
      resolves the method on it as on any other.

    An instance a construction in this frame made is dispatched where the
    one attribute lookup selected a method (``ObjectValue.call_member``,
    over its class), never here.  ``unit`` is the module the call stands
    in; without it nothing is dispatched.  ``halted_at``: the fragment a
    halt of a synthetic call leaves at (``UnknownCalleeCallV1.faces``)."""
    if unit is None or site is None:
        return None
    receiver_class = _receiver_class(name, receiver, unit)
    if receiver_class is None:
        return None
    return dispatch_edge_call(
        name,
        receiver,
        receiver_class,
        positional,
        kw_values,
        site,
        halted_at=halted_at,
    )


_PARAMETER_KINDS = ("positional-only", "positional-or-keyword", "keyword-only")


def _receiver_class(name, receiver, unit):
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
    from sugar_lift_py_tests.ir import make_var

    if isinstance(receiver, CallSiteValue):
        # A store on the result itself leaves another value
        # (``constructed_by_edge``); one through an alias, or a computed
        # store, in a dynamic module may give it another class unseen.
        if module_attribute_names(unit)[1]:
            return None
        return class_value(receiver)
    coordinate = getattr(receiver, "formal_coordinate", None)
    if (
        type(receiver) is SymbolicValue
        and _class_input_coordinate(coordinate)
        and coordinate.coordinate_cid in class_input_formals(unit)
    ):
        names, dynamic = module_attribute_names(unit)
        if dynamic or name in names:
            return None
        from sugar_lift_py_tests.contract_input import CLASS_INPUT, input_formal

        return make_var(input_formal(CLASS_INPUT, coordinate.declared_name))
    return None


def _class_input_coordinate(coordinate) -> bool:
    """Whether ``coordinate`` is one a class input may name: a positional or
    keyword parameter's (``FormalParameterCoordinateV1``), or a captured
    cell's ``cell:<name>`` input's (``ContractInputCoordinateV1``)."""
    from sugar_lift_py_tests.contract_input import (
        CELL_INPUT,
        ContractInputCoordinateV1,
    )
    from sugar_lift_py_tests.formal_parameter import FormalParameterCoordinateV1

    if isinstance(coordinate, FormalParameterCoordinateV1):
        return coordinate.parameter_kind in _PARAMETER_KINDS
    return (
        isinstance(coordinate, ContractInputCoordinateV1)
        and coordinate.input_kind == CELL_INPUT
    )


# Module -> (module, coordinate CIDs), the last few typed modules read.
_CLASS_INPUT_FORMALS: dict = {}


def class_input_formals(unit) -> frozenset:
    """The coordinate CIDs of every parameter of a function of the module
    ``unit`` holds whose class is an input of that function's contract
    (``nodes._receiver_class_parameters``): the formals a method call on
    which is dispatched.  A method call on a formal with no such input is
    the one unanswered call (``UnknownCalleeCallV1``), two-faced and owed,
    never a dispatched edge, since nothing would ever bind its class (#7757
    NEW-1, #8960 decision 1).  Each captured cell whose class is an
    input (``nodes._receiver_class_cells``) is named so too, by the
    coordinate of its ``cell:<name>`` input (#7757 step 7).  Read once per
    typed module."""
    from sugar_lift_py_tests.contract_input import (
        CELL_INPUT,
        ContractInputCoordinateV1,
    )
    from sugar_lift_py_tests.formal_parameter import FormalParameterCoordinateV1
    from sugar_source_tree.nodes import (
        AsyncFunctionDef,
        FunctionDef,
        Lambda,
        _receiver_class_cells,
        _receiver_class_parameters,
    )

    module = getattr(unit, "typed_module", None)
    if module is None:
        return frozenset()
    held = _CLASS_INPUT_FORMALS.get(id(module))
    if held is not None and held[0] is module:
        return held[1]
    found = set()
    for statement in module.body:
        for node in statement.walk():
            if not isinstance(node, (FunctionDef, AsyncFunctionDef, Lambda)):
                continue
            cells = _receiver_class_cells(node)
            if cells:
                # The coordinate the function's own universe reads the cell
                # through (``nodes._contract_inputs``).
                owner = node.fragment.seal().cid
                for name in cells:
                    found.add(
                        ContractInputCoordinateV1.mint(
                            owner_definition_cid=owner,
                            input_kind=CELL_INPUT,
                            name=name,
                        ).coordinate_cid
                    )
            inputs = set(_receiver_class_parameters(node))
            if not inputs:
                continue
            for formal in node.formal_coordinates():
                if (
                    isinstance(formal, FormalParameterCoordinateV1)
                    and formal.declared_name in inputs
                ):
                    found.add(formal.coordinate_cid)
    answer = frozenset(found)
    if len(_CLASS_INPUT_FORMALS) >= 8:
        _CLASS_INPUT_FORMALS.clear()
    _CLASS_INPUT_FORMALS[id(module)] = (module, answer)
    return answer


# Module -> (module, {coordinate CID: {field: ContractInputV1}}), the last
# few typed modules read.
_FIELD_INPUTS: dict = {}


def field_inputs(unit) -> dict:
    """``{coordinate CID: {field: input}}`` for every parameter of a
    function of the module ``unit`` holds whose fields are inputs of that
    function's contract (``nodes._receiver_field_inputs``): the
    ``field:<param>.<field>`` input (``ContractInputV1``) a read of that
    field of that parameter is.  Read once per typed module."""
    from sugar_lift_py_tests.contract_input import FIELD_INPUT, ContractInputV1
    from sugar_lift_py_tests.formal_parameter import FormalParameterCoordinateV1
    from sugar_source_tree.nodes import (
        AsyncFunctionDef,
        FunctionDef,
        Lambda,
        _receiver_field_inputs,
    )

    module = getattr(unit, "typed_module", None)
    if module is None:
        return {}
    held = _FIELD_INPUTS.get(id(module))
    if held is not None and held[0] is module:
        return held[1]
    found: dict = {}
    for statement in module.body:
        for node in statement.walk():
            if not isinstance(node, (FunctionDef, AsyncFunctionDef, Lambda)):
                continue
            reads = _receiver_field_inputs(node)
            if not reads:
                continue
            owner_cid = node.fragment.seal().cid
            for formal in node.formal_coordinates():
                if not isinstance(formal, FormalParameterCoordinateV1):
                    continue
                for parameter, field in reads:
                    if parameter != formal.declared_name:
                        continue
                    found.setdefault(formal.coordinate_cid, {})[field] = (
                        ContractInputV1.mint(
                            owner_definition_cid=owner_cid,
                            input_kind=FIELD_INPUT,
                            name=f"{parameter}.{field}",
                        )
                    )
    if len(_FIELD_INPUTS) >= 8:
        _FIELD_INPUTS.clear()
    _FIELD_INPUTS[id(module)] = (module, found)
    return found


def receiver_field_read(receiver, name, site):
    """``receiver.name`` where ``receiver`` is a parameter of the function
    whose own proof this is and the field is an input of its contract
    (``field_inputs``, ``nodes._receiver_field_inputs``), else None (the
    read takes the path it took before):

    - under ``python:plain_read(class:<param>, "<name>")`` it completes with
      the ``field:<param>.<name>`` input: the value the ``__dict__`` the
      object arrived with holds, which the caller binds at prove where it
      states it, and which is free otherwise;
    - under the complement it is the one two-faced undecided read, keyed per
      evaluation (``floor_value.undecided_attribute_result``): its
      completion owes the ``undecided`` member, and its halt is kept.

    The guard is decided at prove on the namespace rows of the class the
    caller binds ``class:<param>`` to (``consistency::plain_read_holds``);
    where nothing binds a decided class it stands, and neither face is
    chosen.  In a dynamic module (``module_attribute_names``) nothing is
    read through a field input: a computed store may have changed the
    object's ``__dict__`` or its class unseen."""
    from sugar_lift_py_tests.contract_input import CLASS_INPUT, input_formal
    from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
    from sugar_lift_py_tests.formal_parameter import FormalParameterCoordinateV1
    from sugar_lift_py_tests.ir import atomic, make_var, not_, str_const
    from sugar_lift_py_tests.occurrence import occurrence_key
    from sugar_lift_py_tests.outcome import ExitSet
    from sugar_lift_py_tests.outcome.exit_set import partition
    from sugar_source_tree.fragment import SourceFragment

    coordinate = getattr(receiver, "formal_coordinate", None)
    if (
        type(receiver) is not SymbolicValue
        or not isinstance(coordinate, FormalParameterCoordinateV1)
        or coordinate.parameter_kind not in _PARAMETER_KINDS
        or type(site) is not SourceFragment
    ):
        return None
    unit = site.unit
    item = field_inputs(unit).get(coordinate.coordinate_cid, {}).get(name)
    if item is None or module_attribute_names(unit)[1]:
        return None
    guard = atomic(
        PLAIN_READ,
        [
            make_var(input_formal(CLASS_INPUT, coordinate.declared_name)),
            str_const(name),
        ],
    )
    plain, other = partition(("receiver_field_read", occurrence_key(site), name))
    read = ExitSet.completed(item.value()).guarded(guard, plain)
    from sugar_lift_py_tests.floor.floor_value import undecided_attribute_result

    undecided = undecided_attribute_result(
        receiver, name, site, owner="receiver_dispatch.receiver_field_read"
    ).guarded(not_(guard), other)
    return read.union(undecided)


def dispatch_edge_call(
    name,
    receiver,
    receiver_class,
    positional,
    kw_values,
    site,
    *,
    read=False,
    halted_at=None,
    on_class=None,
    after=None,
):
    """THE dispatched method call (#7757 step 8): the coordinate
    ``call:dispatch:<name>(<receiver>, <positional>..., py.kwarg(...)...,
    py.class("0", <receiver_class>), py.class(...)...)`` sent down the path
    every edge takes (``UnknownCalleeCallV1.faces``: completes under its
    ``completes`` atom, halts under the complement, both arms owe it), its
    member's symbol ``python:dispatch:<name>``.  The receiver is the first
    positional argument, as a plain function a lookup binds to an instance
    takes it; each other actual's class rides as its own ``py.class`` where
    it is decided (``class_arguments``).  Nothing here names which function
    runs, nor how its descriptor binds the receiver: prove resolves both on
    the class's namespace row (the kind each binding states) where a read
    binds the receiver's class (``consistency::dispatch_answer``).

    ``read``: the attribute read ``receiver.<name>`` a property's getter
    answers, ``call:dispatch:.<name>(<receiver>, py.class("0", ...))``
    (``DISPATCH_READ_MARK``), with no other actual.

    A receiver whose class is not decided here (``receiver_class`` None:
    what a source ``__new__`` returned, on which ``type.__call__`` runs
    ``type(obj).__init__``, ``ClassConstructorBodySugar._returned_by_new``)
    rides with no ``py.class("0", ...)``: prove resolves no method without
    the receiver's class (``consistency::dispatch_answer``), so the call is
    owed, both faces standing.

    Where the method is looked up is part of the term (``lookup_term``), and
    prove's one resolution reads it (``consistency::dispatched_target``):

    - ``on_class``: the join symbol of a class object the method is read off
      (``Cls.m(...)``, ``super()`` in a ``classmethod``): there is no
      receiver (``receiver`` and ``receiver_class`` are None), the written
      actuals stand as written, keyed from ``"0"``, and prove binds what the
      class's namespace row states the name holds as ``__get__(None, cls)``
      binds it;
    - ``after``: the join symbol of the class after which the lookup starts
      in the order (zero-argument ``super()``, ``super_getattro``): on the
      receiver's class's order (``receiver_class``), or on ``on_class``'s.

    Nothing here selects the method: the lift names where to look, prove
    looks (#7757 entry 6: one MRO lookup).

    The method's contract states its receiver and its other formals as
    distinct objects.  A call whose receiver is, or holds, an object an
    actual is or holds -- ``o.m(o)``, ``o.m(o.items)`` where ``m`` stores
    through ``self.items`` -- is that contract's call only where the
    function changes the shared object through neither formal: a store
    through one would leave the other's entry value standing at prove, a
    lie.  That is the alias rule's own test (``object_identity.
    shared_pairs``), spelled on the member by the one ``shares_mark`` a
    same-file definition's edge spells it with
    (``lambda_callable.definition_edge_call``): the member's symbol names
    every pair that may share and prove joins the function it resolves only
    where its contract states it leaves both formals unchanged
    (``python:leaves``, ``tree_enumerate.parameters_left_unchanged``) or the
    operand's class holds nothing a call could change; anything else stays
    owed (``consistency::dispatch_answer``)."""
    from sugar_lift_py_tests.call_symbol import call_symbol
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.ir import ctor, str_const
    from sugar_lift_py_tests.source_call_resolution import UnknownCalleeCallV1

    owner = str(site)
    target = DISPATCH_TARGET_PREFIX + (DISPATCH_READ_MARK if read else "") + name
    # The operands: the receiver first where there is one (a lookup on a
    # class object has none), then the written actuals.
    received = () if on_class is not None else (receiver,)
    # Each operand by its argument key: each positional operand by its
    # position (the receiver ``0``), each keyword actual by its keyword (the
    # keys its ``py.class`` rides under, ``class_arguments``).
    symbol = "python:" + target + shares_mark(
        (
            *(
                (str(index), value)
                for index, value in enumerate((*received, *positional))
            ),
            *kw_values,
        )
    )
    arguments = (
        [value.to_term(owner=owner) for value in (*received, *positional)]
        + [
            ctor("py.kwarg", [str_const(keyword), value.to_term(owner=owner)])
            for keyword, value in kw_values
        ]
        + (
            [lookup_term(on_class, after)]
            if on_class is not None or after is not None
            else []
        )
        + (
            [ctor(CLASS_ARGUMENT, [str_const("0"), receiver_class])]
            if received and receiver_class is not None
            else []
        )
        + class_arguments(tuple(positional), tuple(kw_values), shift=len(received))
    )
    callsite = CallSiteValue(
        target_name=target,
        arg_values=(*received, *positional, *(value for _name, value in kw_values)),
        parameters=(),
        term=ctor(call_symbol(target), arguments, symbol_kind="coordinate"),
        body=None,
        keyword_names=tuple(keyword for keyword, _value in kw_values),
        site=site,
        authenticated_target_symbol=symbol,
        runtime_dispatch_receiver=receiver,
    )
    return UnknownCalleeCallV1(target).faces(callsite, site, halted_at=halted_at)


#: The label a dispatched call's receiver is read by after the call:
#: ``python:after(<call result>, "0")``, the key its class rides under
#: (``py.class("0", ...)``).  The lift does not know which function runs, so
#: it names the operand by its argument key, never by a parameter's name
#: (``consistency::DISPATCH_RECEIVER_LABEL``).
DISPATCH_RECEIVER_LABEL = "0"


def receiver_after_dispatch(receiver, result):
    """``receiver`` as the dispatched call it was made on left it
    (``result``, the call's completed value): ``python:after(<call result>,
    "0")`` (``source_call_resolution.object_after_call``,
    ``DISPATCH_RECEIVER_LABEL``), the one post-call state term, decided at
    prove by the contract that answers the dispatched member at the class
    its input is bound to -- a builtin ``list`` or ``dict`` method's law
    (``consistency::builtin_dispatch_answer``) -- and undecided where
    nothing answers it (#7757 step 7).  A source method's contract states
    what it leaves in its receiver over its own receiver parameter
    (``python:after(out, "self")``); prove's one binder pairs that
    parameter with the key ``"0"`` the caller names it by
    (``consistency::argument_key_aliases``).

    The same read for ``super().m(...)`` on an instance: it is a dispatched
    call whose receiver is the frame's receiver, keyed ``"0"``
    (``BuiltinSuperValue._selected_call``), so the caller reads it after the
    call by that key and prove pairs it with the method's receiver parameter
    the same way.

    ``receiver`` is a formal's or a cell's plain value (``SymbolicValue``),
    a same-file class call's result the call was dispatched on
    (``CallSiteValue``, ``dispatch_on_receiver``), or an instance the frame
    holds (``ObjectValue``: ``super()``'s receiver, or one a dispatched call
    was made on): the object as the call left it is that term whatever it
    was before.  None where ``result`` is no completed call of either kind
    made on ``receiver`` (an attribute read through dispatch included), or
    ``receiver`` is any other value: the receiver is then what the one
    exposure rule leaves."""
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.floor.named_expression_value import peel_walrus_binds
    from sugar_lift_py_tests.floor.object_value import ObjectValue
    from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
    from sugar_lift_py_tests.source_call_resolution import object_after_call

    if type(receiver) is not SymbolicValue and not isinstance(
        receiver, (CallSiteValue, ObjectValue)
    ):
        return None
    _binds, call = peel_walrus_binds(result)
    if not isinstance(call, CallSiteValue):
        return None
    prefix = "python:" + DISPATCH_TARGET_PREFIX
    symbol = getattr(call, "authenticated_target_symbol", None) or ""
    if not symbol:
        return None
    if symbol.startswith(prefix):
        member = symbol[len(prefix) :]
        if not member or member.startswith(DISPATCH_READ_MARK):
            return None
    held = call.runtime_dispatch_receiver
    if held is None or held != receiver:
        return None
    return SymbolicValue(object_after_call(call.term, DISPATCH_RECEIVER_LABEL))
