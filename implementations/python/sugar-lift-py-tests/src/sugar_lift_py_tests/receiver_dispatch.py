"""A method call on an instance whose class the method does not know (#7757
step 8): the receiver's class is an input of the contract, and the call is
its coordinate plus an edge resolved at prove through that input.

The owner's ruling of 2026-11-15, "Edge, join at prove": every same-file call
is a coordinate plus an edge, joined at prove; the lifter never follows a
body.  A method call on a receiver whose class is decided here is the edge to
that method (``object_value.method_edge_call``).  Where the class is not
decided here -- ``self.m()`` in a method's own proof, a method of a
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

#: ``python:may_hold(<object>, <name>)``: the object's ``__dict__`` may hold
#: ``<name>`` (``consistency::PYTHON_MAY_HOLD``), one fact per name.
MAY_HOLD = "python:may_hold"

#: ``python:class_undecided(<object>)``: what the object's class is, or what
#: its ``__dict__`` holds, is not decided (``consistency::
#: PYTHON_CLASS_UNDECIDED``).
CLASS_UNDECIDED = "python:class_undecided"

#: The named argument that supplies a class input (``consistency::
#: PYTHON_CLASS``).
CLASS_ARGUMENT = "py.class"

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

    Prove reads them off the row (``consistency::constructed_instance``):
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
      left.

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
        fields |= set(value.deferred_helper_fields)
        fields -= set(value.deleted_instance_fields)
        return instance_term(symbol, fields)
    return None


def class_arguments(positional, keywords, *, shift: int = 0) -> list:
    """``py.class(<key>, <class>)`` for each actual whose class is decided
    here (``class_value``): a positional actual keyed by its position (plus
    ``shift``) in decimal digits, a keyword actual by its keyword.  Prove's
    one binder binds each to the ``class:<param>`` input of the parameter
    that argument binds, where the callee's contract takes one."""
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


def dispatch_on_receiver(name, receiver, positional, kw_values, site, *, unit):
    """``receiver.name(*positional, **kw_values)`` as its coordinate and the
    dispatched edge (``dispatch_edge_call``) when its receiver's class is a
    class input here, else None (the call takes the path it took before):

    - ``receiver`` is the plain value of a positional or keyword parameter
      of the function whose own proof this is (``FormalParameterCoordinateV1``
      on a ``SymbolicValue``): its class is ``class:<param>``, unbound here.
      Only for a method name this module never spells as anything but a
      callee (``module_attribute_names``): a field of that name stored on
      the formal in the frame would shadow the method unseen;
    - ``receiver`` is the instance an ``__init__``'s own contract runs on
      (``self``: an ``ObjectValue`` that arrived through the initializer's
      receiver coordinate, ``initializer_receiver_formals``) and the class
      of that parameter is an input of the ``__init__``'s contract: its
      class is ``class:<param>``, bound by the caller -- ``super().
      __init__()`` from a subclass supplies the subclass -- under the same
      method-name guard as a formal;
    - ``receiver`` is a same-file class's call result that ``type.__call__``
      makes with a builtin ``__new__`` (``class_value``:
      ``python:constructed(<class>)``), in a module that is not dynamic
      (``module_attribute_names``: no computed store, no ``__class__``
      store): prove binds its class to what the class's contract states and
      resolves the method on it as on any other.

    An instance a construction in this frame made is dispatched where the
    one attribute lookup selected a method (``ObjectValue.call_member``,
    over its class), never here.  ``unit`` is the module the call stands
    in; without it nothing is dispatched."""
    if unit is None or site is None:
        return None
    receiver_class = _receiver_class(name, receiver, unit)
    if receiver_class is None:
        return None
    return dispatch_edge_call(
        name, receiver, receiver_class, positional, kw_values, site
    )


_PARAMETER_KINDS = ("positional-only", "positional-or-keyword", "keyword-only")


def _receiver_class(name, receiver, unit):
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.floor.object_value import ObjectValue
    from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
    from sugar_lift_py_tests.formal_parameter import FormalParameterCoordinateV1
    from sugar_lift_py_tests.ir import make_var

    if isinstance(receiver, CallSiteValue):
        # A store on the result itself leaves another value
        # (``constructed_by_edge``); one through an alias, or a computed
        # store, in a dynamic module may give it another class unseen.
        if module_attribute_names(unit)[1]:
            return None
        return class_value(receiver)
    if isinstance(receiver, ObjectValue):
        if receiver.allocation is not None or receiver.arrival is None:
            return None
        formal = initializer_receiver_formals(unit).get(receiver.arrival)
        if formal is None:
            return None
        names, dynamic = module_attribute_names(unit)
        if dynamic or name in names:
            return None
        from sugar_lift_py_tests.contract_input import CLASS_INPUT, input_formal

        return make_var(input_formal(CLASS_INPUT, formal))
    coordinate = getattr(receiver, "formal_coordinate", None)
    if (
        type(receiver) is SymbolicValue
        and isinstance(coordinate, FormalParameterCoordinateV1)
        and coordinate.parameter_kind in _PARAMETER_KINDS
        and coordinate.coordinate_cid in class_input_formals(unit)
    ):
        names, dynamic = module_attribute_names(unit)
        if dynamic or name in names:
            return None
        from sugar_lift_py_tests.contract_input import CLASS_INPUT, input_formal

        return make_var(input_formal(CLASS_INPUT, coordinate.declared_name))
    return None


# Module -> (module, coordinate CIDs), the last few typed modules read.
_CLASS_INPUT_FORMALS: dict = {}


def class_input_formals(unit) -> frozenset:
    """The coordinate CIDs of every parameter of a function of the module
    ``unit`` holds whose class is an input of that function's contract
    (``nodes._receiver_class_parameters``): the formals a method call on
    which is dispatched.  A formal with no such input keeps the path it took
    before (the ``method_call`` operation waiting for an actual), since
    nothing would ever bind its class.  Read once per typed module."""
    from sugar_lift_py_tests.formal_parameter import FormalParameterCoordinateV1
    from sugar_source_tree.nodes import (
        AsyncFunctionDef,
        FunctionDef,
        Lambda,
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


# Module -> (module, {receiver coordinate CID: formal}), the last few read.
_INITIALIZER_RECEIVERS: dict = {}


def initializer_receiver_formals(unit) -> dict:
    """``{receiver coordinate CID: parameter name}`` for each ``__init__`` a
    class statement of the module ``unit`` holds writes
    (``SourceUnit.lexical_class_owner_for``) whose receiver parameter's
    class is an input of its contract (``nodes._receiver_class_parameters``).

    An ``__init__``'s own contract runs on the instance its class's
    constructor makes, seated at that receiver coordinate
    (``FunctionDef._constructed_receiver_coordinate``, the coordinate the
    class's constructor frame mints) and arrived by binding through it
    (``ClassConstructorBodySugar._made``: no class call of the reading frame
    made it).  A method call on that instance is a method call on the
    parameter: its class is the ``class:<param>`` input, never the class
    whose body wrote the ``__init__`` (a subclass's ``super().__init__()``
    runs it on an instance of the subclass).  Read once per typed module."""
    from sugar_source_tree.nodes import FunctionDef, _receiver_class_parameters

    module = getattr(unit, "typed_module", None)
    if module is None:
        return {}
    held = _INITIALIZER_RECEIVERS.get(id(module))
    if held is not None and held[0] is module:
        return held[1]
    found = {}
    for statement in module.body:
        for node in statement.walk():
            if (
                not isinstance(node, FunctionDef)
                or node.name != "__init__"
                or not node.params
            ):
                continue
            receiver = node.params[0]
            if receiver.name not in _receiver_class_parameters(node):
                continue
            # The coordinate is minted from the class statement and the
            # parameter alone; an ``__init__`` the class does not run seats
            # no instance there, so its entry is never read.
            owner = node.unit.lexical_class_owner_for(node)
            if owner is None:
                continue
            coordinate = node._constructed_receiver_coordinate(owner, receiver)
            found[coordinate.cid] = receiver.name
    if len(_INITIALIZER_RECEIVERS) >= 8:
        _INITIALIZER_RECEIVERS.clear()
    _INITIALIZER_RECEIVERS[id(module)] = (module, found)
    return found


def dispatch_edge_call(
    name, receiver, receiver_class, positional, kw_values, site, *, read=False
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
    (``DISPATCH_READ_MARK``), with no other actual."""
    from sugar_lift_py_tests.call_symbol import call_symbol
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.ir import ctor, str_const
    from sugar_lift_py_tests.source_call_resolution import UnknownCalleeCallV1

    owner = str(site)
    target = DISPATCH_TARGET_PREFIX + (DISPATCH_READ_MARK if read else "") + name
    arguments = (
        [receiver.to_term(owner=owner)]
        + [value.to_term(owner=owner) for value in positional]
        + [
            ctor("py.kwarg", [str_const(keyword), value.to_term(owner=owner)])
            for keyword, value in kw_values
        ]
        + [ctor(CLASS_ARGUMENT, [str_const("0"), receiver_class])]
        + class_arguments(tuple(positional), tuple(kw_values), shift=1)
    )
    callsite = CallSiteValue(
        target_name=target,
        arg_values=(receiver, *positional, *(value for _name, value in kw_values)),
        parameters=(),
        term=ctor(call_symbol(target), arguments, symbol_kind="coordinate"),
        body=None,
        keyword_names=tuple(keyword for keyword, _value in kw_values),
        site=site,
        authenticated_target_symbol="python:" + target,
        runtime_dispatch_receiver=receiver,
    )
    return UnknownCalleeCallV1(target).faces(callsite, site)
