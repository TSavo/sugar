"""A built-in container's mutation is a store on the object, seen by every alias.

``r = []; a = r; r.append(1); return a`` returns ``[1]``: ``append`` changes
the list object, and ``a`` names that same object. An assignment binds its
target to a reference to its own evaluation (``Assign.target_evaluations``),
which carries the right-hand side it was given as the object the name denotes
(``_evaluation_ref``, ``of``); the object is that node (``_identity``): two
names given the same node (``a = r``, ``x = y = []``) are the same object,
and a node built by another evaluation is another object.

THE LAW, at a statement that calls a mutating method of a built-in container:

- **Decided receiver.** The receiver is bound to a ``list``/``dict``/``set``
  display (or to such a receiver's post-state). The call becomes one
  ``BuiltinContainerCall`` evaluated at the statement (``sugar/
  builtin_container_call_sugar.py``): its halts leave there, and every name
  bound to the receiver's object is rebound to the post-state projection.
  A target (``x = r.pop()``) is bound to the result projection.
- **Every other alias.** A name whose value merely CONTAINS the object
  (``outer = [r]``) is not rebuilt: it is rebound to an unknown value minted at
  the call. Never the pre-call contents.
- **Undecided receiver.** A mutating method name on any other receiver keeps
  its ordinary (opaque) call, and the receiver and its aliases are rebound to
  an unknown value minted at the call.
- **Exposure.** A decided container passed to a call the floor does not cite
  as pure may be mutated by it: the object and its aliases are rebound to an
  unknown after that statement.

Names are only rebound; nothing here decides what a call does.
"""

from __future__ import annotations

from typing import Optional

from .construction_cache import AmbientSet

_DISPLAY_KIND = {"List": "list", "Dict": "dict", "Set": "set"}


def _evaluation(site_node, tags) -> str:
    """The coordinate of one evaluation a shadow node stands for.

    The site's source extent plus the occurrence tags of the copy it was
    built in (the iteration segments, outermost first). A pure function of
    the source and the copy, so a CID that holds it is the same in every
    process, whatever that process lifted before (#7838, inventory item 44).
    It replaces a process-wide draw counter.
    """
    span = site_node.span
    return "/".join((f"[{span.start},{span.end})", *tags))


# Builtins whose call never mutates an argument (CPython "Built-in Functions").
PURE_BUILTINS = frozenset(
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
        "id",
        "int",
        "isinstance",
        "issubclass",
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
        "type",
        "zip",
    }
)

# Pure builtins that invoke no dunder of their operands: ``isinstance(c, C)``
# reads ``type(c)``; ``id``/``type``/``callable`` read the object header.
NO_DUNDER_BUILTINS = frozenset({"callable", "id", "isinstance", "issubclass", "type"})


def runs_operand_code(call, scope) -> bool:
    """Whether ``call`` may run code that can change its operands' objects:
    anything but a cited pure builtin over operands whose dunders are builtin."""
    from .nodes import Call

    return isinstance(call, Call) and not _is_pure_call(call, scope)


def _identity(node):
    """The node whose object ``node`` denotes.

    A read of a name an assignment bound is a reference to the assignment's
    evaluation (``EvaluationRef``) carrying the right-hand side the name was
    given (``of``): the name denotes the object that right-hand side built
    (or names), never the reference node, which every read mints afresh.
    Any other node denotes itself."""
    seen = 0
    while getattr(node, "kind", None) == "EvaluationRef" and seen < 64:
        of = getattr(node, "of", None)
        if of is None:
            break
        node = of
        seen += 1
    return node


def decided_container_kind(node) -> Optional[str]:
    """``list``/``dict``/``set`` when ``node`` builds (or is the post-state of) one."""
    from .nodes import BuiltinContainerProjection

    node = _identity(node)
    if isinstance(node, BuiltinContainerProjection):
        return node.call.container_kind if node.index == 0 else None
    kind = getattr(node, "kind", None)
    if kind == "SourceCallActualAfter":
        # The helper only mutated the object: its type is the actual's.
        return decided_container_kind(node.state)
    if kind == "OpaqueObjectStateV1":
        # ``s = set()``: the call result's identity wrapper over the call.
        return decided_container_kind(node.base)
    if kind == "Call":
        # ``list()``/``dict()``/``set()`` with the builtin still in scope: a
        # read of a locally bound name would have substituted to its value.
        func = node.func
        if (
            getattr(func, "kind", None) == "Name"
            and func.id in ("list", "dict", "set")
            and not node.keywords
            and len(node.args) <= 1
        ):
            return func.id
        return None
    return _DISPLAY_KIND.get(kind)


def _state(value):
    from .binding_state import BindingEntryV1, unwrap_binding_state

    if isinstance(value, BindingEntryV1):
        value = value.state
    try:
        value = unwrap_binding_state(value)
    except Exception:  # pragma: no cover - defensive: not a node state
        return value
    return _identity(value)


_FORMAL_KINDS = ("FormalRef", "BindingCoordinateRef")


def _ref(node):
    """The object a node denotes: its backend handle, or a formal's coordinate.

    A read of a formal is re-spanned to its use site (``Name.substitute``), so
    every read is a fresh node over the same ``coordinate``.  A read of an
    assigned name is the object its assignment was given (``_identity``)."""
    node = _identity(node)
    if getattr(node, "kind", None) in _FORMAL_KINDS and hasattr(node, "coordinate"):
        return ("formal", node.kind, _coordinate_key(node.coordinate))
    return getattr(node, "ref", node)


def _coordinate_key(coordinate):
    cid = getattr(coordinate, "cid", None)
    if cid is not None:
        return cid
    try:
        hash(coordinate)
        return coordinate
    except TypeError:
        return id(coordinate)


def same_object(left, right) -> bool:
    if left is right:
        return True
    return _ref(left) == _ref(right) if _is_formal(left) else _ref(left) is _ref(right)


def _is_formal(node) -> bool:
    return getattr(_identity(node), "kind", None) in _FORMAL_KINDS


# Builtins whose result never holds a reference to an argument object.
_NO_REFERENCE_BUILTINS = frozenset(
    {
        "abs",
        "all",
        "any",
        "bool",
        "chr",
        "divmod",
        "float",
        "format",
        "hash",
        "id",
        "int",
        "isinstance",
        "issubclass",
        "len",
        "ord",
        "repr",
        "round",
        "str",
    }
)


def _holds_no_reference(node) -> bool:
    """A value built from its operands that cannot be (or hold) one of them:
    ``len(r)``, ``r[0]`` (the element, read when evaluated), ``r == s``,
    ``r.copy()``/``r.index(x)`` on a decided container."""
    from .nodes import Attribute, Call, Compare, Name, Subscript

    if isinstance(node, (Compare, Subscript)):
        return True
    if isinstance(node, Call):
        func = node.func
        if isinstance(func, Name):
            return func.id in _NO_REFERENCE_BUILTINS
        if isinstance(func, Attribute) and decided_container_kind(func.value):
            from sugar_lift_py_tests.floor.builtin_container_method import (
                MUTATING_METHODS,
            )

            return func.attr not in MUTATING_METHODS[decided_container_kind(func.value)]
    return False


def _walk_values(node, *, kept_only=True):
    """Every node that may be (or hold) an object of this value: not inside
    code that does not run, nor inside an operand the value does not keep.

    ``kept_only=False`` asks what a call operand hands onward instead: an
    element read (``g(r[0])``) hands the element object itself."""
    from .nodes import ClassDef, FunctionDef, AsyncFunctionDef, Lambda, Node

    stack = [node]
    seen = set()
    while stack:
        current = stack.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        yield current
        if isinstance(current, (Lambda, FunctionDef, AsyncFunctionDef, ClassDef)):
            continue
        if _holds_no_reference(current) and (
            kept_only or getattr(current, "kind", None) != "Subscript"
        ):
            continue
        denoted = _identity(current)
        if denoted is not current and isinstance(denoted, Node):
            # A read of an assigned name holds what its assignment was given.
            stack.append(denoted)
            continue
        for _name, _index, child in current._child_edges():
            if isinstance(child, Node):
                stack.append(child)


def _contains(state, target) -> bool:
    from .nodes import Name, Node

    if not isinstance(state, Node):
        return False
    for node in _walk_values(state):
        if isinstance(target, Name):
            if isinstance(node, Name) and node.id == target.id:
                return True
        elif same_object(node, target):
            return True
    return False


def aliases(scope, receiver):
    """``(exact, containing)``: names bound to ``receiver``'s object, and names
    whose value holds it. An unbound ``Name`` receiver (a formal, a global) is
    the object every unsubstituted read of that name denotes."""
    from .nodes import Name, Node

    if isinstance(receiver, Name) and receiver.id in scope:
        # An unsubstituted read (a loop body kept whole) names the object its
        # binding holds.
        state = _state(scope[receiver.id])
        if isinstance(state, Node) and not isinstance(state, Name):
            exact, containing = aliases(scope, state)
            if receiver.id not in exact:
                exact.append(receiver.id)
            return exact, containing
    exact, containing = [], []
    for name, value in scope.items():
        if not isinstance(name, str):
            continue
        state = _state(value)
        if not isinstance(state, Node):
            continue
        if isinstance(receiver, Name):
            if isinstance(state, Name) and state.id == receiver.id:
                exact.append(name)
                continue
        elif same_object(state, receiver):
            exact.append(name)
            continue
        if _contains(state, receiver):
            containing.append(name)
    if isinstance(receiver, Name) and receiver.id not in scope:
        exact.append(receiver.id)
    return exact, containing


def _materialize(statement, kind, fields, tags=()):
    from .backend import materialize
    from .shadow import OccurrenceShadowNode, ShadowNode

    if tags:
        ref = OccurrenceShadowNode(kind, statement.span, fields, tags)
    else:
        ref = ShadowNode(kind, statement.span, fields)
    return materialize(statement.unit, ref, statement.reporter)


def _call_node(statement, site_node, receiver, method, args, kind, tags, value_first):
    from .backend import Child, Children, Leaf
    from .shadow import _handle_of

    return _materialize(
        site_node,
        "BuiltinContainerCall",
        (
            ("receiver", Child(_handle_of(receiver))),
            ("args", Children(tuple(_handle_of(arg) for arg in args))),
            ("method", Leaf(method)),
            ("container_kind", Leaf(kind)),
            ("value_first", Leaf(value_first)),
            ("occurrence", Leaf(_evaluation(site_node, tags))),
        ),
        tags,
    )


def _projection(site_node, call, index, tags):
    from .backend import Child, Leaf
    from .shadow import _handle_of

    return _materialize(
        site_node,
        "BuiltinContainerProjection",
        (("call", Child(_handle_of(call))), ("index", Leaf(index))),
        tags,
    )


def _havoc(site_node, label, tags):
    from .backend import Leaf

    return _materialize(
        site_node,
        "ReceiverAfterCall",
        (("label", Leaf(label)), ("occurrence", Leaf(_evaluation(site_node, tags)))),
        tags,
    )


def _statement(statement, names, states, evaluated, tags):
    from .backend import Children, Leaf
    from .shadow import _handle_of

    return _materialize(
        statement,
        "ContainerMutationStatement",
        (
            ("names", Leaf(tuple(names))),
            ("states", Children(tuple(_handle_of(state) for state in states))),
            ("evaluated", Children(tuple(_handle_of(node) for node in evaluated))),
        ),
        tags,
    )


def mutation_statement(
    statement,
    scope,
    *,
    call_site,
    receiver,
    method,
    args,
    target_name=None,
    value_first=False,
):
    """The shadow statement for one decided mutating call, or None.

    ``receiver`` and ``args`` are already substituted against ``scope``.
    """
    from .shadow import occurrence_tags_of
    from sugar_lift_py_tests.floor.builtin_container_method import MUTATING_METHODS

    kind = decided_container_kind(receiver)
    if kind is None or method not in MUTATING_METHODS[kind]:
        return None
    tags = occurrence_tags_of(statement)
    call = _call_node(
        statement, call_site, receiver, method, args, kind, tags, value_first
    )
    post = _projection(call_site, call, 0, tags)
    exact, containing = aliases(scope, receiver)
    names, states, evaluated = [], [], [call]
    for name in exact:
        names.append(name)
        states.append(post)
    for name in containing:
        havoc = _havoc(call_site, name, tags)
        names.append(name)
        states.append(havoc)
        evaluated.append(havoc)
    if target_name is not None:
        names.append(target_name)
        states.append(_projection(call_site, call, 1, tags))
    return _statement(statement, names, states, evaluated, tags)


def _is_pure_call(call, scope) -> bool:
    from .nodes import Attribute, Constant, Name

    func = call.func
    if call.keywords:
        # ``sorted(r, key=f)``: ``f`` runs and may reach the argument.
        return False
    if isinstance(func, Name):
        # ``print(c)``/``sum([c])``/``sorted(c)`` run ``c``'s ``__str__``/
        # ``__radd__``/``__iter__``/``__lt__``: pure only when every operand
        # is a decided builtin all the way down, so no dunder is user code.
        if func.id not in PURE_BUILTINS or func.id in scope:
            return False
        if func.id in NO_DUNDER_BUILTINS:
            return True
        return all(builtin_typed(arg, scope) for arg in call.args)
    if isinstance(func, Attribute):
        if isinstance(func.value, Constant):
            return True
        kind = decided_container_kind(func.value)
        if kind is not None:
            from sugar_lift_py_tests.floor.builtin_container_method import (
                MUTATING_METHODS,
            )

            return func.attr not in MUTATING_METHODS[kind]
    return False


def _calls(statement, bound_refs, *, include_container_calls):
    """Calls ``statement`` makes now: not inside a nested def, and not inside a
    value a name was already bound to (that value's calls ran earlier)."""
    from .nodes import (
        AsyncFunctionDef,
        BuiltinContainerCall,
        Call,
        ClassDef,
        FunctionDef,
        Lambda,
        Node,
        PathContainerCall,
    )

    stack = [statement]
    seen = set()
    while stack:
        current = stack.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if current is not statement and _ref(current) in bound_refs:
            continue
        if isinstance(current, (Lambda, FunctionDef, AsyncFunctionDef, ClassDef)):
            if current is not statement:
                continue
            return
        if isinstance(current, Call):
            yield current
        if include_container_calls and isinstance(current, BuiltinContainerCall):
            yield current
        if isinstance(current, PathContainerCall):
            # Its ``fallback`` is this same call, not a second one.
            if include_container_calls:
                yield current
            stack.append(current.receiver)
            stack.extend(current.args)
            continue
        for _name, _index, child in current._child_edges():
            if isinstance(child, Node):
                stack.append(child)


def havoc_after(statement, pre_scope, scope):
    """Rebind every object ``statement``'s calls may have changed to an unknown.

    ``pre_scope`` is the scope the statement was substituted against; the
    statement's calls name objects by the nodes that scope bound.
    """
    from .nodes import (
        BuiltinContainerCall,
        ContainerMutationStatement,
        DictSetDefaultAppendStatement,
        For,
        LoopRecurrenceStatement,
        MappingPopAssignStatement,
        Node,
        PathContainerCall,
        While,
    )

    if isinstance(
        statement,
        (DictSetDefaultAppendStatement, MappingPopAssignStatement),
    ):
        # These shadow statements already bind the receiver's post-state.
        return scope
    bound_refs = {
        _ref(_state(value))
        for value in pre_scope.values()
        if isinstance(_state(value), Node)
    }
    if isinstance(statement, ContainerMutationStatement):
        # The cited call itself is threaded; what its operands' own calls (or
        # the call, for an operand it keeps) may change is not.
        targets = []
        for call in statement.evaluated[:1]:
            for arg in call.args:
                targets.extend(_exposed(arg, bound_refs))
                for inner in _calls(arg, bound_refs, include_container_calls=False):
                    targets.extend(_call_targets(inner, pre_scope, bound_refs))
        return _rebind(statement, pre_scope, scope, targets)
    # A loop that may run its body any number of times leaves every object a
    # cited call in that body changed unknown; a branch's cited calls are
    # threaded by the branch and joined.
    loop = isinstance(statement, (For, While, LoopRecurrenceStatement))
    targets = []
    applied = []
    for call in _calls(statement, bound_refs, include_container_calls=loop):
        if isinstance(call, BuiltinContainerCall):
            targets.append(call.receiver)
            continue
        helper = None if loop else source_helper_actual_states(call, bound_refs)
        if helper is not None:
            havoc_targets, states = helper
            targets.extend(havoc_targets)
            applied.extend(states)
            continue
        if isinstance(call, PathContainerCall):
            root, _steps = path_steps(call.receiver)
            if root is not None:
                targets.append(root)
                targets.extend(_sharing_states(pre_scope, root))
            continue
        targets.extend(_call_targets(call, pre_scope, bound_refs))
    havocked = _rebind(statement, pre_scope, scope, targets)
    if not applied:
        return havocked
    return _apply_actual_states(statement, pre_scope, scope, havocked, applied)


def _call_targets(call, scope, bound_refs):
    from .nodes import Attribute, Name
    from sugar_lift_py_tests.floor.builtin_container_method import (
        ANY_MUTATING_METHOD,
    )

    targets = []
    func = call.func
    if (
        isinstance(func, Attribute)
        and func.attr in ANY_MUTATING_METHOD
        and decided_container_kind(func.value) is None
    ):
        receiver = func.value
        if isinstance(receiver, Name) or _ref(receiver) in bound_refs:
            targets.append(receiver)
    if _is_pure_call(call, scope):
        return targets
    roots = list(call.args) + [keyword.value for keyword in call.keywords]
    if isinstance(func, Attribute):
        roots.append(func.value)
    for root in roots:
        targets.extend(_exposed(root, bound_refs))
    return targets


def _exposed(root, bound_refs):
    """Decided containers reachable from a call operand."""
    found = []
    for node in _walk_values(root, kept_only=False):
        if decided_container_kind(node) is not None and _ref(node) in bound_refs:
            found.append(node)
    return found


# Builtins whose result is always a value of an immutable builtin type, whatever
# the operand's dunder returns (CPython checks ``__str__``/``__len__``/... results).
_IMMUTABLE_RESULT_BUILTINS = frozenset(
    {
        "bool",
        "chr",
        "format",
        "hash",
        "id",
        "isinstance",
        "issubclass",
        "len",
        "ord",
        "repr",
        "str",
    }
)
# Builtins that build a builtin container (or iterator) of the operand's items.
_BUILTIN_CONSTRUCTORS = frozenset(
    {
        "bytes",
        "complex",
        "dict",
        "float",
        "frozenset",
        "int",
        "list",
        "range",
        "set",
        "sorted",
        "tuple",
    }
)


def builtin_typed(node, scope, depth=0) -> bool:
    """Whether ``node`` is a decided builtin value all the way down: every
    object it is or holds has a builtin type, so no dunder a builtin invokes on
    it is user code."""
    from .nodes import (
        BuiltinContainerCall,
        BuiltinContainerProjection,
        Call,
        Constant,
        Dict,
        List,
        Name,
        Set,
        Starred,
        Tuple_,
    )

    if depth > 32:
        return False
    node = _identity(node)
    if isinstance(node, Constant):
        return True
    if isinstance(node, (List, Tuple_, Set)):
        return all(builtin_typed(e, scope, depth + 1) for e in node.elts)
    if isinstance(node, Dict):
        return all(
            k is not None and builtin_typed(k, scope, depth + 1)
            for k in node.keys
        ) and all(builtin_typed(v, scope, depth + 1) for v in node.values)
    if isinstance(node, Starred):
        return builtin_typed(node.value, scope, depth + 1)
    if isinstance(node, BuiltinContainerProjection):
        return builtin_typed(node.call, scope, depth + 1)
    if isinstance(node, BuiltinContainerCall):
        return builtin_typed(node.receiver, scope, depth + 1) and all(
            builtin_typed(a, scope, depth + 1) for a in node.args
        )
    if getattr(node, "kind", None) == "OpaqueObjectStateV1":
        return builtin_typed(node.base, scope, depth + 1)
    if (
        isinstance(node, Call)
        and isinstance(node.func, Name)
        and node.func.id not in scope
        and not node.keywords
    ):
        if node.func.id in _IMMUTABLE_RESULT_BUILTINS:
            return True
        if node.func.id in _BUILTIN_CONSTRUCTORS:
            return all(builtin_typed(a, scope, depth + 1) for a in node.args)
    return False


def _rebind(statement, pre_scope, scope, targets):
    """Rebind each name that held a target object before ``statement`` and
    still holds that value: a name the statement itself bound holds the value
    the statement computed (``x = g(r)``), not the object ``g`` was given."""
    from .shadow import occurrence_tags_of

    if not targets:
        return scope
    names = []
    for target in targets:
        exact, containing = aliases(scope, target)
        for name in (*exact, *containing):
            if name in names:
                continue
            if name in scope and (
                name not in pre_scope or scope[name] is not pre_scope[name]
            ):
                continue
            names.append(name)
    if not names:
        return scope
    tags = occurrence_tags_of(statement)
    binding = {name: _havoc(statement, name, tags) for name in names}
    binding = statement._binding_entries(binding, scope)
    return {**scope, **binding}


# ---------------------------------------------------------------------------
# A mutating call whose receiver is reached through a path.
#
# ``c.items.append(x)``, ``d['k'].append(x)``, ``obj.a.b.add(y)``: the receiver
# is the object the path evaluates to, and the store is on THAT object. It is
# also reachable from the path's root (``c``/``d``/``obj``) and from any name
# bound to it. THE LAW, at such a statement:
#
# - **The call.** One ``PathContainerCall`` evaluated at the statement. Its
#   receiver is evaluated once; if the value is a decided list/dict/set the call
#   is the cited CPython mutation (``floor/builtin_container_method``), else it
#   is the ordinary call, and the receiver's contents afterwards are unknown.
# - **The root.** Every name bound to the root's object is rebound to the root
#   after the call (``PathAfterCall``, mode ``root``): the root's value with the
#   path's member replaced by the post-state when every step is a plain field
#   or a decided item and no other member of the root can be the same object;
#   otherwise an unknown minted at the call.
# - **The object itself.** A name bound to the same path on the same root, or
#   to the node a display root holds there, is rebound to the post-state
#   (mode ``inner``) when the path's steps are plain; otherwise unknown.
# - **Everything else that may share it.** Any other name whose value holds the
#   root, or anything the root holds (``L`` in ``c = C(L)``), is rebound to an
#   unknown minted at the call. Never the pre-call contents.
# ---------------------------------------------------------------------------

# Root bindings that denote a (possibly mutable) object a path can reach into.
_PATH_ROOT_KINDS = frozenset(
    {
        "List",
        "Dict",
        "Set",
        "Tuple",
        "Call",
        "Attribute",
        "Subscript",
        "ObjectPlaceStateV1",
        "OpaqueObjectStateV1",
        "BuiltinContainerProjection",
        "ReceiverAfterCall",
        "PathAfterCall",
        "FormalRef",
        "BindingCoordinateRef",
    }
)
# Bindings no mutation can change: rebinding them would only lose information.
_NEVER_HAVOC_KINDS = frozenset(
    {
        "Constant",
        "FunctionDef",
        "AsyncFunctionDef",
        "ClassDef",
        "Lambda",
        "ImportAlias",
        "Import",
        "ImportFrom",
        "Module",
    }
)


def _decided_key(value) -> bool:
    return type(value) in (int, str)


def path_steps(receiver):
    """``(root, steps)`` of an attribute/subscript chain, or ``(None, ())``.

    A step is ``("attr", name)``, ``("item", key)`` for a ground ``int``/``str``
    constant key, or ``("undecided", None)``."""
    from .nodes import Attribute, Constant, Subscript

    steps = []
    node = receiver
    while isinstance(node, (Attribute, Subscript)):
        if isinstance(node, Attribute):
            steps.append(("attr", node.attr))
        elif isinstance(node.slice_, Constant) and _decided_key(node.slice_.value):
            steps.append(("item", node.slice_.value))
        else:
            steps.append(("undecided", None))
        node = node.value
    if not steps:
        return None, ()
    return node, tuple(reversed(steps))


def _decided_steps(steps) -> bool:
    return all(kind != "undecided" for kind, _value in steps)


def _same_steps(left, right) -> bool:
    if len(left) != len(right) or not _decided_steps(left):
        return False
    return all(
        lk == rk and type(lv) is type(rv) and lv == rv
        for (lk, lv), (rk, rv) in zip(left, right)
    )


def _display_member(node, step):
    """The node a display holds at a decided item step, or None."""
    from .nodes import Constant, Starred

    kind, key = step
    if kind != "item":
        return None
    node_kind = getattr(node, "kind", None)
    if node_kind == "Dict":
        found = None
        for item in node.items:
            if item.key is None or not isinstance(item.key, Constant):
                return None
            existing = item.key.value
            if not _decided_key(existing):
                return None
            if type(existing) is type(key) and existing == key:
                found = item.value
        return found
    if node_kind in ("List", "Tuple") and type(key) is int:
        if any(isinstance(element, Starred) for element in node.elts):
            return None
        if -len(node.elts) <= key < len(node.elts):
            return node.elts[key]
    return None


def _static_member(root, steps):
    """The node a display root holds at ``steps``, when the source says."""
    from .nodes import Name

    node = root
    for step in steps:
        node = _display_member(_identity(node), step)
        if node is None or isinstance(node, Name):
            return None
    return node


def _path_count(node, target, memo):
    """How many child paths from ``node`` reach ``target`` (DAG-safe)."""
    from .nodes import AsyncFunctionDef, ClassDef, FunctionDef, Lambda, Node

    key = id(node)
    if key in memo:
        return memo[key]
    memo[key] = 0
    count = 1 if same_object(node, target) else 0
    denoted = _identity(node)
    if denoted is not node:
        # A read of an assigned name reaches what its assignment was given;
        # when it is the target itself that is this one path.
        if not count and isinstance(denoted, Node):
            count += _path_count(denoted, target, memo)
    elif not isinstance(node, (Lambda, FunctionDef, AsyncFunctionDef, ClassDef)):
        for _name, _index, child in node._child_edges():
            if isinstance(child, Node):
                count += _path_count(child, target, memo)
    memo[key] = count
    return count


def _object_key(node):
    ref = _ref(node)
    return ref if isinstance(ref, tuple) else id(ref)


def _graph(node):
    """Keys of every object ``node``'s value may be, hold, or be read from."""
    from .nodes import Node

    if not isinstance(node, Node):
        return set()
    return {
        _object_key(member)
        for member in _walk_values(node, kept_only=False)
        if getattr(member, "kind", None) not in _NEVER_HAVOC_KINDS
    }


def _sharing_states(scope, root):
    """Bound values that may hold, or be read from, anything ``root`` holds."""
    from .nodes import Node

    graph = _graph(root)
    found = []
    for name, value in scope.items():
        state = _state(value)
        if not isinstance(name, str) or not isinstance(state, Node):
            continue
        if getattr(state, "kind", None) in _NEVER_HAVOC_KINDS:
            continue
        if _graph(state) & graph:
            found.append(state)
    return found


def _path_after(site_node, call, root, steps, mode, label, tags, unshared, inner=None):
    from .backend import Child, Leaf, MaybeChild
    from .shadow import _handle_of

    fields = [
        ("call", Child(_handle_of(call))),
        ("root", Child(_handle_of(root))),
        ("steps", Leaf(tuple(steps))),
        ("mode", Leaf(mode)),
        ("label", Leaf(label)),
        ("unshared", Leaf(unshared)),
        ("occurrence", Leaf(_evaluation(site_node, tags))),
        # The root after the call holds the object after it: a later
        # mutation of that object through another name reaches the root.
        ("inner", MaybeChild(None if inner is None else _handle_of(inner))),
    ]
    return _materialize(site_node, "PathAfterCall", tuple(fields), tags)


def path_mutation_statement(statement, scope, *, call, target_name=None):
    """The shadow statement for ``<path>.<mutator>(*args)``, or None.

    ``call`` is the statement's call, already substituted against ``scope``.
    """
    from .backend import Child, Children, Leaf
    from .nodes import Attribute, Call, Node, Starred
    from .shadow import _handle_of, occurrence_tags_of
    from sugar_lift_py_tests.floor.builtin_container_method import (
        ANY_MUTATING_METHOD,
    )

    if (
        not isinstance(call, Call)
        or call.keywords
        or not isinstance(call.func, Attribute)
        or call.func.attr not in ANY_MUTATING_METHOD
        or any(isinstance(arg, Starred) for arg in call.args)
    ):
        return None
    receiver = call.func.value
    root, steps = path_steps(receiver)
    root = _identity(root)
    if root is None or getattr(root, "kind", None) not in _PATH_ROOT_KINDS:
        return None
    bound = {
        _object_key(_state(value))
        for name, value in scope.items()
        if isinstance(name, str) and isinstance(_state(value), Node)
    }
    if _object_key(root) not in bound:
        # A root no name holds (``f().items.append(x)``) leaves nothing here
        # for the store to rebind.
        return None
    tags = occurrence_tags_of(statement)
    path_call = _materialize(
        call,
        "PathContainerCall",
        (
            ("receiver", Child(_handle_of(receiver))),
            ("args", Children(tuple(_handle_of(arg) for arg in call.args))),
            ("method", Leaf(call.func.attr)),
            ("fallback", Child(_handle_of(call))),
            ("occurrence", Leaf(_evaluation(call, tags))),
        ),
        tags,
    )
    member = _static_member(root, steps)
    # Distinct display nodes are distinct objects: the source alone says the
    # root holds this member once, and nothing else in it can be the object.
    unshared = member is not None and _path_count(root, member, {}) == 1
    if (
        member is None
        and getattr(root, "kind", None) == "PathAfterCall"
        and root.mode == "root"
        and root.inner is not None
        and _same_steps(tuple(root.steps), steps)
    ):
        # The root after an earlier call through this same path holds that
        # call's object there.
        member = root.inner
    inner = _path_after(call, path_call, root, steps, "inner", "", tags, unshared)
    root_after = _path_after(
        call, path_call, root, steps, "root", "", tags, unshared, inner=inner
    )
    exact, _containing = aliases(scope, root)
    names, states, evaluated = [], [], [path_call, root_after, inner]
    for name in exact:
        names.append(name)
        states.append(root_after)
    graph = _graph(root)
    for name, value in scope.items():
        if not isinstance(name, str) or name in names or name == target_name:
            continue
        state = _state(value)
        if not isinstance(state, Node):
            continue
        if getattr(state, "kind", None) in _NEVER_HAVOC_KINDS:
            continue
        bound_root, bound_steps = path_steps(state)
        if (
            bound_root is not None
            and same_object(bound_root, root)
            and _same_steps(bound_steps, steps)
        ) or (member is not None and same_object(state, member)):
            names.append(name)
            states.append(inner)
            continue
        if _graph(state) & graph:
            havoc = _havoc(call, name, tags)
            names.append(name)
            states.append(havoc)
            evaluated.append(havoc)
    if target_name is not None:
        names.append(target_name)
        states.append(_projection(call, path_call, 1, tags))
    return _statement(statement, names, states, evaluated, tags)


# ---------------------------------------------------------------------------
# A call to a lifted source helper applies its body's stores to the actuals.
#
# ``def add(l): l.append(1)`` / ``r = []; add(r); return r`` returns ``[1]``:
# ``l`` is bound to the very object ``r`` names, and the helper's append is a
# store on that object. THE LAW, at a statement that calls a same-module
# source function whose body substitution can be followed:
#
# - The helper's body is substituted with each formal bound to the caller's
#   actual node (the object), exactly as its node-specialized frame is. The
#   formal's binding after the body is the object's state after the call.
# - That state is applied (every name bound to the object is rebound to it)
#   only when it is CLOSED: the actual itself (the helper did not change it)
#   or a chain of cited built-in container mutations rooted at the actual,
#   whose operands are constants, displays of constants, or formals -- nothing
#   whose re-evaluation could raise, call, or mint a second unknown. A read
#   keeps that state only when it evaluates to one plain completed value;
#   otherwise it is an unknown minted at the call.
# - Anything else -- a body with control flow the substitution cannot follow
#   on every path (loops, try, with, an early return, a non-raising branch),
#   a formal rebound to another object, an object the helper exposed to code
#   it does not project, an object only CONTAINED in an actual -- keeps the
#   havoc: unknown after the call, never the pre-call contents.
#
# The call's own halts are its faces at the call (the Call producer); a halt
# path never reaches the statement's continuation, so the state is the
# completed path's.
# ---------------------------------------------------------------------------

_HELPER_STATEMENT_KINDS = frozenset(
    {"Expr", "Assign", "AnnAssign", "AugAssign", "Pass", "Raise", "Assert"}
)
# Ambient to memo rows: a row that asked is served only where the helper is
# in progress or not as it was.
_HELPERS_IN_PROGRESS: AmbientSet = AmbientSet("helpers_in_progress")
_CLOSED_OPERAND_KINDS = frozenset(
    {
        "Constant",
        "List",
        "Tuple",
        "Set",
        "Dict",
        "FormalRef",
        "BindingCoordinateRef",
        # A read of a key: the value its evaluation completed with, read
        # again at any later point without running anything.
        "EvaluationRef",
    }
)


def _straight_line_helper(definition) -> bool:
    """Every path through ``definition``'s body is the one substitution threads:
    straight-line statements, a trailing ``return``, and guards that only raise."""
    from .nodes import FunctionDef, If, Raise, Return

    if type(definition) is not FunctionDef or definition.decorators:
        return False
    if FunctionDef._owns_yield(definition.body):
        return False
    if any(param.param_kind != "positional_or_keyword" for param in definition.params):
        return False
    body = definition.body
    for index, statement in enumerate(body):
        kind = statement.kind
        if kind in _HELPER_STATEMENT_KINDS:
            continue
        if isinstance(statement, Return) and index == len(body) - 1:
            continue
        if (
            isinstance(statement, If)
            and not statement.orelse
            and len(statement.body) == 1
            and isinstance(statement.body[0], Raise)
        ):
            continue
        return False
    return True


def _closed_state(state, actual) -> bool:
    """``state`` is ``actual`` after cited mutations with closed operands."""
    from .nodes import BuiltinContainerCall, BuiltinContainerProjection

    node = state
    while True:
        if same_object(node, actual):
            return True
        if isinstance(node, BuiltinContainerProjection) and node.index == 0:
            call = node.call
            if not isinstance(call, BuiltinContainerCall):
                return False
            if not all(_closed_operand(arg) for arg in call.args):
                return False
            node = call.receiver
            continue
        return False


def _closed_operand(node) -> bool:
    from .nodes import Node

    stack = [node]
    while stack:
        current = stack.pop()
        if getattr(current, "kind", None) not in _CLOSED_OPERAND_KINDS:
            return False
        for _name, _index, child in current._child_edges():
            if isinstance(child, Node):
                stack.append(child)
    return True


def source_helper_actual_states(call, bound_refs):
    """``(havoc_targets, [(actual, state, index)])`` for a call to a followable
    source helper, or None when the call is not one (it keeps its havoc)."""
    from .nodes import Call, Name, Starred

    if (
        not isinstance(call, Call)
        or not isinstance(call.func, Name)
        or call.keywords
        or any(isinstance(arg, Starred) for arg in call.args)
    ):
        return None
    actuals = [
        (index, arg)
        for index, arg in enumerate(call.args)
        if decided_container_kind(arg) is not None and _ref(arg) in bound_refs
    ]
    if not actuals:
        return None
    definition = call.unit.source_function_definition_for_call(call)
    if definition is None or not _straight_line_helper(definition):
        return None
    params = definition.params
    if len(params) != len(call.args):
        return None
    key = id(definition)
    if key in _HELPERS_IN_PROGRESS:
        return None
    node_scope = {param.name: arg for param, arg in zip(params, call.args)}
    _HELPERS_IN_PROGRESS.add(key)
    try:
        _body, _changed, net = definition._substitute_body_tracked(
            definition.body, node_scope
        )
    finally:
        _HELPERS_IN_PROGRESS.discard(key)
    havoc_targets = []
    states = []
    claimed = {id(arg) for _index, arg in actuals}
    for index, arg in enumerate(call.args):
        exposed = [
            node for node in _exposed(arg, bound_refs) if id(node) not in claimed
        ]
        havoc_targets.extend(exposed)
    for index, actual in actuals:
        name = params[index].name
        state = _state(net[name]) if name in net else actual
        if not _closed_state(state, actual):
            havoc_targets.append(actual)
            continue
        if same_object(state, actual):
            continue
        states.append((actual, state, index))
    return havoc_targets, states


def _actual_after(site_node, state, label, tags):
    from .backend import Child, Leaf
    from .shadow import _handle_of

    return _materialize(
        site_node,
        "SourceCallActualAfter",
        (
            ("state", Child(_handle_of(state))),
            ("label", Leaf(label)),
            ("occurrence", Leaf(_evaluation(site_node, tags))),
        ),
        tags,
    )


def _apply_actual_states(statement, pre_scope, scope, havocked, applied):
    """Rebind every name bound to an actual's object to its state after the
    helper; a name the havoc already rebound, or the statement itself bound,
    keeps that binding. A name that merely contains the object is unknown."""
    from .shadow import occurrence_tags_of

    tags = occurrence_tags_of(statement)
    binding = {}
    havoc_names = []
    for actual, state, index in applied:
        exact, containing = aliases(scope, actual)
        after = None
        for name in exact:
            if name in binding or not _untouched(name, pre_scope, scope, havocked):
                continue
            if after is None:
                after = _actual_after(statement, state, f"actual:{index}", tags)
            binding[name] = after
        for name in containing:
            if name in binding or name in havoc_names:
                continue
            if _untouched(name, pre_scope, scope, havocked):
                havoc_names.append(name)
    for name in havoc_names:
        binding[name] = _havoc(statement, name, tags)
    if not binding:
        return havocked
    binding = statement._binding_entries(binding, havocked)
    return {**havocked, **binding}


def _untouched(name, pre_scope, scope, havocked) -> bool:
    if name not in scope or name not in pre_scope:
        return name not in scope
    return scope[name] is pre_scope[name] and havocked.get(name) is scope[name]


# ---------------------------------------------------------------------------
# ``is`` between decided containers: object identity, never value equality.
#
# A display or a builtin ``list()``/``dict()``/``set()`` call builds a new
# object each time it is evaluated, so two different creation nodes are two
# objects; a post-state (a recorded mutation projection or a helper's actual
# after its body) is the object it mutated.  Only operands whose evaluation
# runs no code are decided here: the comparison then reads nothing it would
# not read anyway.
_IDENTITY_LEAF_KINDS = frozenset({"Constant", "FormalRef", "BindingCoordinateRef"})
_IDENTITY_STATE_KINDS = frozenset(
    {"BuiltinContainerProjection", "SourceCallActualAfter", "OpaqueObjectStateV1"}
)


def _identity_root(node):
    """The creation node (or formal) whose object ``node`` denotes, else None."""
    node = _identity(node)
    kind = getattr(node, "kind", None)
    if kind == "BuiltinContainerProjection":
        return _identity_root(node.call.receiver) if node.index == 0 else None
    if kind == "SourceCallActualAfter":
        return _identity_root(node.state)
    if kind == "OpaqueObjectStateV1":
        return _identity_root(node.base)
    if kind in _FORMAL_KINDS:
        return node
    if decided_container_kind(node) is not None:
        return node
    return None


def _runs_no_code(node) -> bool:
    """Evaluating ``node`` (a decided container operand) calls nothing."""
    kind = getattr(node, "kind", None)
    if kind == "EvaluationRef":
        # A read of a key: the value its evaluation already completed with.
        return True
    if kind in _IDENTITY_STATE_KINDS:
        # Answered from the evaluation its statement already recorded.
        return True
    if kind in _IDENTITY_LEAF_KINDS:
        return True
    if kind == "Call":
        return decided_container_kind(node) is not None and not node.args
    if kind in ("List", "Tuple", "Set"):
        return all(_runs_no_code(element) for element in node.elts)
    if kind == "Dict":
        # A dict display hashes its keys: only constants are decided here.
        return all(
            key is not None and getattr(key, "kind", None) == "Constant"
            for key in node.keys
        ) and all(_runs_no_code(value) for value in node.values)
    return False


def decided_identity(left, right) -> Optional[bool]:
    """``left is right`` when both denote decided containers, else None.

    Two different creation sites are two objects: False.  One creation site
    does not decide: an unrolled loop or a re-entered body evaluates it more
    than once, and each evaluation is another object, which a node cannot
    tell apart -- that comparison stays with the reduced values.  A formal may
    be any caller object: it decides only against its own coordinate."""
    if decided_container_kind(left) is None or decided_container_kind(right) is None:
        return None
    if not (_runs_no_code(left) and _runs_no_code(right)):
        return None
    left_root = _identity_root(left)
    right_root = _identity_root(right)
    if left_root is None or right_root is None:
        return None
    if _is_formal(left_root) or _is_formal(right_root):
        if _is_formal(left_root) and _is_formal(right_root) and same_object(
            left_root, right_root
        ):
            return True
        return None
    if _ref(left_root) is _ref(right_root):
        return None
    return False
# A cited mutation that cannot raise.
#
# ``r.append(x)`` on a decided list stores and completes: CPython's
# ``list.append`` has no exceptional exit for any operand (MemoryError aside,
# which no lift models).  A statement that is only such a call contributes no
# halt edge to an enclosing ``try`` -- an edge there would carry the state
# BEFORE the store into the handler as though the append could have raised.
# Only methods whose operands are never inspected are listed; an operand
# that is hashed, compared or iterated can run code and raise.
_NEVER_RAISING_METHODS = {
    "list": frozenset({"append", "clear", "reverse", "copy"}),
    "dict": frozenset({"clear", "copy"}),
    "set": frozenset({"clear", "copy"}),
}


def cited_call_cannot_halt(statement, scope) -> bool:
    """``statement`` is ``name.method(operand?)`` on a decided container whose
    cited method never raises, over an operand whose evaluation cannot."""
    from .binding_state import UnboundBinding
    from .nodes import Attribute, Call, Constant, Expr, Name

    if not isinstance(statement, Expr):
        return False
    call = statement.value
    if not isinstance(call, Call) or call.keywords:
        return False
    func = call.func
    if not isinstance(func, Attribute) or not isinstance(func.value, Name):
        return False
    if func.value.id not in scope:
        return False
    kind = decided_container_kind(_state(scope[func.value.id]))
    if kind is None or func.attr not in _NEVER_RAISING_METHODS[kind]:
        return False
    if func.attr != "append":
        return not call.args
    if len(call.args) != 1:
        return False
    (operand,) = call.args
    if isinstance(operand, Constant):
        return True
    return isinstance(operand, Name) and operand.id in scope and not isinstance(
        _state(scope[operand.id]), UnboundBinding
    )
