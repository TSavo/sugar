"""A built-in container's mutation is a store on the object, seen by every alias.

``r = []; a = r; r.append(1); return a`` returns ``[1]``: ``append`` changes
the list object, and ``a`` names that same object. An assignment binds its
target to a reference to its own evaluation (``Assign.target_evaluations``),
which carries the right-hand side it was given as the object the name denotes
(``_evaluation_ref``, ``of``); the object is that node (``_identity``): two
names given the same node (``a = r``, ``x = y = []``) are the same object,
and a node built by another evaluation is another object.

THE LAW, at a statement that mutates the object a name denotes -- a
mutating-named method call (``r.append(x)``, ``x = r.pop()``), an item store
(``r[k] = v``), an item delete (``del r[k]``) or an augmented assignment
(``r += x``) -- whatever the name was given (a display, ``'a b'.split()``, a
parameter, a global):

- **One door** (``name_mutation_statement``).  The operation becomes one
  ``PathContainerCall`` with no path steps, evaluated at the statement: its
  halts leave there.  The VALUE the receiver holds at reduce decides it
  (``PathContainerCallSugar``): a ``ListValue``/``DictValue``/``SetValue``
  takes the cited CPython mutation (``floor/builtin_container_method``); any
  other value takes the ordinary operation -- the call, ``__setitem__``,
  ``__delitem__``, the in-place operator -- and its contents afterwards are
  unknown (an immutable value is unchanged).  The source's spelling of the
  right-hand side never chooses the door.
- **The object's names.** Every name bound to the receiver's object is
  rebound to the object after the call (``PathAfterCall``): the post-state.
  A target (``x = r.pop()``) is bound to the call's value; ``r += x`` binds
  ``r`` to the in-place result, as Python does.
- **Every other alias.** A name whose value merely holds the object
  (``outer = [r]``) is not rebuilt: it reads an unknown value minted at the
  call when the value the call changed is mutable (``ReceiverAfterCall``,
  decided at reduce).  Never the pre-call contents.
- **Exposure.** An object passed to a call the floor does not cite as pure,
  or the receiver of a method call outside the door, may be changed by it:
  each name bound to it is rebound to its value after the call, which the
  value decides at reduce (``ReceiverAfterCall``): a builtin container the
  call may change is unknown; an immutable value, or a container the call's
  cited method or cited pure builtin leaves alone, is unchanged.

Names are only rebound; nothing here decides what a call does.
"""

from __future__ import annotations

import functools
from typing import NamedTuple, Optional

from .construction_cache import AmbientSet

_DISPLAY_KIND = {"List": "list", "Dict": "dict", "Set": "set"}


class _CitedBuiltins(NamedTuple):
    """The builtins this law cites, as the ``LanguageCallee`` members their
    binding reaches (CPython "Built-in Functions")."""

    # ``list()``/``dict()``/``set()``: the container each constructor builds.
    container_kind: dict
    # Never mutates an argument.
    pure: frozenset
    # Pure, and invokes no dunder of its operands: ``isinstance(c, C)`` reads
    # ``type(c)``; ``id``/``type`` read the object header.
    no_dunder: frozenset
    # The result never holds a reference to an argument object.
    no_reference: frozenset
    # The result is always a value of an immutable builtin type, whatever the
    # operand's dunder returns (CPython checks ``__str__``/``__len__``/...
    # results).
    immutable_result: frozenset
    # Builds a builtin container (or iterator) of the operand's items.
    constructors: frozenset


@functools.cache
def _cited() -> _CitedBuiltins:
    from .nodes import LanguageCallee as C

    no_reference = frozenset(
        {
            C.BUILTIN_ABS,
            C.BUILTIN_ALL,
            C.BUILTIN_ANY,
            C.BUILTIN_BOOL,
            C.BUILTIN_CHR,
            C.BUILTIN_DIVMOD,
            C.BUILTIN_FLOAT,
            C.BUILTIN_FORMAT,
            C.BUILTIN_HASH,
            C.BUILTIN_ID,
            C.BUILTIN_INT,
            C.BUILTIN_ISINSTANCE,
            C.BUILTIN_ISSUBCLASS,
            C.BUILTIN_LEN,
            C.BUILTIN_ORD,
            C.BUILTIN_REPR,
            C.BUILTIN_ROUND,
            C.BUILTIN_STR,
        }
    )
    return _CitedBuiltins(
        container_kind={
            C.BUILTIN_LIST: "list",
            C.BUILTIN_DICT: "dict",
            C.BUILTIN_SET: "set",
        },
        pure=no_reference
        | {
            C.BUILTIN_DICT,
            C.BUILTIN_ENUMERATE,
            C.BUILTIN_FROZENSET,
            C.BUILTIN_ITER,
            C.BUILTIN_LIST,
            C.BUILTIN_MAX,
            C.BUILTIN_MIN,
            C.BUILTIN_PRINT,
            C.BUILTIN_RANGE,
            C.BUILTIN_REVERSED,
            C.BUILTIN_SET,
            C.BUILTIN_SORTED,
            C.BUILTIN_SUM,
            C.BUILTIN_TUPLE,
            C.BUILTIN_TYPE,
            C.BUILTIN_ZIP,
        },
        no_dunder=frozenset(
            {C.BUILTIN_ID, C.BUILTIN_ISINSTANCE, C.BUILTIN_ISSUBCLASS, C.BUILTIN_TYPE}
        ),
        no_reference=no_reference,
        immutable_result=frozenset(
            {
                C.BUILTIN_BOOL,
                C.BUILTIN_CHR,
                C.BUILTIN_FORMAT,
                C.BUILTIN_HASH,
                C.BUILTIN_ID,
                C.BUILTIN_ISINSTANCE,
                C.BUILTIN_ISSUBCLASS,
                C.BUILTIN_LEN,
                C.BUILTIN_ORD,
                C.BUILTIN_REPR,
                C.BUILTIN_STR,
            }
        ),
        constructors=frozenset(
            {
                C.BUILTIN_BYTES,
                C.BUILTIN_COMPLEX,
                C.BUILTIN_DICT,
                C.BUILTIN_FLOAT,
                C.BUILTIN_FROZENSET,
                C.BUILTIN_INT,
                C.BUILTIN_LIST,
                C.BUILTIN_RANGE,
                C.BUILTIN_SET,
                C.BUILTIN_SORTED,
                C.BUILTIN_TUPLE,
            }
        ),
    )


def _builtin_callee(call):
    """The builtin ``call``'s callee is bound to, or None.

    Read through the unit's one binding lookup (``SourceUnit.
    language_callee_of``: the builtin namespace a bare name falls through to,
    or an import of ``builtins``), never the spelling: a parameter, local,
    module binding or import that rebinds ``len`` reaches no builtin here."""
    return call.unit.language_callee_of(call.func)


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
    """``list``/``dict``/``set`` when ``node`` builds (or is the post-state of) one.

    Asked only about the object a creation node built: ``is`` between two
    creations, a source helper's actual, a ``try`` edge.  Never which door a
    mutation takes, nor whether a call changed an object: the value decides
    those at reduce (``name_mutation_statement``, ``ReceiverAfterCall``)."""
    node = _identity(node)
    kind = getattr(node, "kind", None)
    if kind == "PathAfterCall":
        # A name's object after a mutation through the one door: the same
        # object, whose type no mutation changes.
        if node.mode == "root" and not node.steps:
            return decided_container_kind(node.root)
        return None
    if kind == "BuiltinContainerProjection":
        # ``r += x``: the in-place result of a builtin container is the
        # container itself.
        call = node.call
        if node.index == 1 and str(getattr(call, "method", "")).startswith("__i"):
            return decided_container_kind(call.receiver)
        return None
    if kind == "SourceCallActualAfter":
        # The helper only mutated the object: its type is the actual's.
        return decided_container_kind(node.state)
    if kind == "OpaqueObjectStateV1":
        # ``s = set()``: the call result's identity wrapper over the call.
        return decided_container_kind(node.base)
    if kind == "Call":
        # ``list()``/``dict()``/``set()`` whose callee is bound to the builtin
        # (``_builtin_callee``): ``from collections import deque as list``
        # builds no list.
        if node.keywords or len(node.args) > 1:
            return None
        return _cited().container_kind.get(_builtin_callee(node))
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


def _object(node):
    """The node whose object ``node`` denotes, through mutations too.

    ``_identity``, and: the object a name denotes after the one door's call
    (``PathAfterCall`` with no steps) is the object the call was made on,
    and a name's value after a call that may have changed it
    (``ReceiverAfterCall`` with a ``prior``) is the object it was bound to --
    a mutation changes an object's contents, never which object it is.  Only
    object identity asks this; what a value holds is read through
    ``_identity``, whose post-state still holds what the call stored."""
    seen = 0
    node = _identity(node)
    while seen < 64:
        kind = getattr(node, "kind", None)
        if (
            kind == "PathAfterCall"
            and getattr(node, "mode", None) == "root"
            and not getattr(node, "steps", ())
        ):
            node = _identity(node.root)
        elif kind == "ReceiverAfterCall" and getattr(node, "prior", None) is not None:
            # A name's value after a call that may have changed it: the same
            # object it was bound to before.
            node = _identity(node.prior)
        else:
            break
        seen += 1
    return node


def _ref(node):
    """The object a node denotes: its backend handle, or a formal's coordinate.

    A read of a formal is re-spanned to its use site (``Name.substitute``), so
    every read is a fresh node over the same ``coordinate``.  A read of an
    assigned name is the object its assignment was given (``_identity``);
    a name's object after a mutation is the object before it (``_object``)."""
    node = _object(node)
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
    return getattr(_object(node), "kind", None) in _FORMAL_KINDS


def _holds_no_reference(node) -> bool:
    """A value built from its operands that cannot be (or hold) one of them:
    ``len(r)`` (the builtin ``len``, by its binding), ``r[0]`` (the element,
    read when evaluated), ``r == s``.  A method call's value may hold its
    receiver: the receiver's type is the value's, decided at reduce."""
    from .nodes import Call, Compare, Subscript

    if isinstance(node, (Compare, Subscript)):
        return True
    if isinstance(node, Call):
        callee = _builtin_callee(node)
        if callee is not None:
            return callee in _cited().no_reference
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


def _projection(site_node, call, index, tags, evaluation=None):
    """Element ``index`` of ``call``'s ``(post-state, result)`` pair.

    With ``evaluation`` (the statement's key, ``name_mutation_statement``,
    ``path_mutation_statement``) the projection reads the pair the statement
    bound under that key (``ContainerMutationStatementSugar``): ``d[k] = v;
    ...; d[k]`` reads the dict the store left, never the call (and ``v``)
    evaluated again."""
    from .backend import Child, Leaf
    from .shadow import _handle_of

    fields = (("call", Child(_handle_of(call))), ("index", Leaf(index)))
    if evaluation is not None:
        fields = (*fields, ("evaluation", Leaf(evaluation)))
    return _materialize(site_node, "BuiltinContainerProjection", fields, tags)


def _havoc(site_node, label, tags, *, prior=None, conditions=None):
    """The value a call may have changed, read after it.

    With no ``conditions`` it is an unknown minted at the call.  With
    ``conditions`` -- ``(subject, (method, pure, sharer))`` pairs -- the value
    decides at reduce (``ReceiverAfterCallSugar``): ``prior`` is the name's
    read before the call; it is kept unless some condition's object (its
    ``subject`` read, or ``prior`` itself when None) has a value the call may
    have changed (``_may_change``), and an immutable ``prior`` is kept."""
    from .backend import Children, Leaf, MaybeChild
    from .shadow import _handle_of

    if conditions is None or prior is None:
        prior, conditions = None, ()
    subjects = []
    rules = []
    for subject, (method, pure, sharer) in conditions:
        index = -1
        if subject is not None:
            for position, known in enumerate(subjects):
                if known is subject:
                    index = position
                    break
            else:
                subjects.append(subject)
                index = len(subjects) - 1
        rule = (method, pure, sharer, index)
        if rule not in rules:
            rules.append(rule)
    return _materialize(
        site_node,
        "ReceiverAfterCall",
        (
            ("label", Leaf(label)),
            ("occurrence", Leaf(_evaluation(site_node, tags))),
            ("prior", MaybeChild(None if prior is None else _handle_of(prior))),
            ("subjects", Children(tuple(_handle_of(node) for node in subjects))),
            ("rules", Leaf(tuple(rules))),
        ),
        tags,
    )


def _read_of(value):
    """The node a read of a name bound to ``value`` is (``Name.substitute``),
    or None when the binding holds no node."""
    from .binding_state import BindingEntryV1, unwrap_binding_state
    from .nodes import Node

    if isinstance(value, BindingEntryV1):
        value = value.state
    try:
        value = unwrap_binding_state(value)
    except Exception:  # pragma: no cover - defensive: not a node state
        return None
    return value if isinstance(value, Node) else None


def _statement(
    statement, names, states, evaluated, tags, evaluation=None, rebinds=None
):
    """The shadow statement; with ``evaluation`` it binds its call's pair
    (``evaluated[0]``) under that key, which its projections read.

    ``rebinds`` is ``(name, index, key)`` for ``r += x``: the statement
    writes ``name`` -- the in-place result ``evaluated[index]`` -- under
    ``key``, the statement's own evaluation (``evaluation``; the pair is
    then bound under ``pair_evaluation``): the write every later read of
    ``name`` reads and a live loop carries
    (``live_loop_construction._carried_writes``)."""
    from .backend import Children, Leaf
    from .shadow import _handle_of

    fields = (
        ("names", Leaf(tuple(names))),
        ("states", Children(tuple(_handle_of(state) for state in states))),
        ("evaluated", Children(tuple(_handle_of(node) for node in evaluated))),
    )
    if rebinds is not None:
        fields = (
            *fields,
            ("rebinds", Leaf(rebinds[0])),
            ("rebinds_index", Leaf(rebinds[1])),
            ("evaluation", Leaf(rebinds[2])),
        )
        if evaluation is not None:
            fields = (*fields, ("pair_evaluation", Leaf(evaluation)))
    elif evaluation is not None:
        fields = (*fields, ("evaluation", Leaf(evaluation)))
    return _materialize(statement, "ContainerMutationStatement", fields, tags)


def _is_pure_call(call, scope) -> bool:
    """A cited pure builtin (by its binding) over builtin operands, or a
    method of a literal.  A method call on anything else is not pure here:
    whether it changes its receiver is the receiver's value's question, asked
    at reduce (``_call_targets``, ``ReceiverAfterCall``)."""
    from .nodes import Attribute, Constant

    func = call.func
    if call.keywords:
        # ``sorted(r, key=f)``: ``f`` runs and may reach the argument.
        return False
    callee = _builtin_callee(call)
    if callee is not None:
        # A builtin by its binding (``_builtin_callee``): ``print(c)``/
        # ``sum([c])``/``sorted(c)`` run ``c``'s ``__str__``/``__radd__``/
        # ``__iter__``/``__lt__``: pure only when every operand is a decided
        # builtin all the way down, so no dunder is user code.
        cited = _cited()
        if callee not in cited.pure:
            return False
        if callee in cited.no_dunder:
            return True
        return all(builtin_typed(arg, scope) for arg in call.args)
    return isinstance(func, Attribute) and isinstance(func.value, Constant)


def _calls(statement, bound_refs, *, include_container_calls):
    """Calls ``statement`` makes now: not inside a nested def, and not inside a
    value a name was already bound to (that value's calls ran earlier)."""
    from .nodes import (
        AsyncFunctionDef,
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
        ContainerMutationStatement,
        DictSetDefaultAppendStatement,
        For,
        LoopRecurrenceStatement,
        Node,
        PathContainerCall,
        While,
    )

    if isinstance(statement, DictSetDefaultAppendStatement):
        # This shadow statement already binds the receiver's post-state.
        return scope
    bound_refs = {
        _ref(_state(value))
        for value in pre_scope.values()
        if isinstance(_state(value), Node)
    }
    if isinstance(statement, ContainerMutationStatement):
        # The call itself is threaded; what its operands' own calls (or the
        # call, for an operand it keeps) may change is not.
        targets = []
        for call in statement.evaluated[:1]:
            for arg in call.args:
                targets.extend(
                    (node, _OPERAND_RULES, None) for node in _exposed(arg, bound_refs)
                )
                for inner in _calls(arg, bound_refs, include_container_calls=False):
                    targets.extend(_call_targets(inner, pre_scope, bound_refs))
        return _rebind(statement, pre_scope, scope, targets)
    # A loop that may run its body any number of times leaves every object a
    # mutation in that body changed unknown (when its value is one a
    # mutation changes); a branch's mutations are threaded by the branch and
    # joined.
    loop = isinstance(statement, (For, While, LoopRecurrenceStatement))
    targets = []
    applied = []
    for call in _calls(statement, bound_refs, include_container_calls=loop):
        helper = None if loop else source_helper_actual_states(call, bound_refs)
        if helper is not None:
            havoc_targets, states = helper
            targets.extend(havoc_targets)
            applied.extend(states)
            continue
        if isinstance(call, PathContainerCall):
            root, _steps = path_steps(call.receiver)
            if root is None:
                # No steps (``name_mutation_statement``): the receiver is the
                # object the call may change, and its value decides whether
                # it did.
                rules = ((call.method, False, False),)
                targets.append((call.receiver, rules, None))
                targets.extend(
                    (state, rules, call.receiver)
                    for state in _sharing_states(pre_scope, call.receiver)
                )
                continue
            targets.append((root, None, None))
            targets.extend(
                (state, None, None) for state in _sharing_states(pre_scope, root)
            )
            continue
        targets.extend(_call_targets(call, pre_scope, bound_refs))
    havocked = _rebind(statement, pre_scope, scope, targets)
    if not applied:
        return havocked
    return _apply_actual_states(statement, pre_scope, scope, havocked, applied)


# An operand handed to a call the floor does not cite: a builtin container in
# it may be changed; any other value is kept (``_may_change``).
_OPERAND_RULES = (("", False, False),)


def _call_targets(call, scope, bound_refs):
    """``(object, rules, subject)`` for every object ``call`` may change
    (``_rebind``): its receiver when the method name is a builtin container's
    mutator, and, unless the call is pure, every bound object its operands
    reach.  ``rules`` say how the value decides at reduce (``_may_change``);
    never the spelling of the receiver's binding."""
    from .nodes import Attribute, Name
    from sugar_lift_py_tests.floor.builtin_container_method import (
        ANY_MUTATING_METHOD,
    )

    targets = []
    func = call.func
    if isinstance(func, Attribute) and func.attr in ANY_MUTATING_METHOD:
        receiver = func.value
        if isinstance(receiver, Name) or _ref(receiver) in bound_refs:
            targets.append((receiver, ((func.attr, False, False),), None))
    if _is_pure_call(call, scope):
        return targets
    # A cited pure builtin whose operands the source does not type: an
    # operand whose value is builtin all the way down is unchanged.
    pure = (("", _builtin_callee(call) in _cited().pure, False),)
    for root in (*call.args, *(keyword.value for keyword in call.keywords)):
        targets.extend((node, pure, None) for node in _exposed(root, bound_refs))
    if isinstance(func, Attribute):
        receiver = func.value
        method = ((func.attr, False, False),)
        # What the receiver holds changes only when the receiver's value
        # runs an ordinary call (``sharer``): a builtin container's own
        # method changes the container at most.
        shared = ((func.attr, False, True),)
        for node in _exposed(receiver, bound_refs):
            if same_object(node, receiver):
                targets.append((node, method, None))
            elif getattr(receiver, "kind", None) in _READ_KINDS:
                targets.append((node, shared, receiver))
            else:
                targets.append((node, _OPERAND_RULES, None))
    return targets


# Nodes whose evaluation is a read of a value an earlier evaluation made:
# reading one again after the call runs nothing.
_READ_KINDS = frozenset(
    {
        "Name",
        "EvaluationRef",
        "FormalRef",
        "BindingCoordinateRef",
        "PathAfterCall",
        "ReceiverAfterCall",
        "BuiltinContainerProjection",
        "SourceCallActualAfter",
    }
)


# Bindings whose object may be a builtin container whose type only its value
# at reduce decides: a display or comprehension, a call result, an item or
# attribute read, an operator result, a key reference with no right-hand
# side, a mutation's post-state.  A literal, a definition, an import, a
# formal, and an instance of a source class are not.
_EXPOSED_KINDS = frozenset(
    {
        "List",
        "Dict",
        "Set",
        "ListComp",
        "DictComp",
        "SetComp",
        "Call",
        "Subscript",
        "Attribute",
        "BinOp",
        "IfExp",
        "BoolOp",
        "EvaluationRef",
        "PathAfterCall",
        "BuiltinContainerProjection",
        "ReceiverAfterCall",
        "OpaqueObjectStateV1",
        "SourceCallActualAfter",
    }
)


def _may_be_changed(node) -> bool:
    """Whether the object ``node`` denotes may be one a call changes."""
    denoted = _identity(node)
    kind = getattr(denoted, "kind", None)
    if kind not in _EXPOSED_KINDS:
        return False
    if kind == "Call":
        allocation = getattr(denoted.unit, "source_allocation_definition_for_call", None)
        if allocation is not None and allocation(denoted) is not None:
            # An instance of a source class: its fields are the object's
            # own (``ObjectPlaceStateV1``), never a builtin container's.
            return False
    return True


def _exposed(root, bound_refs):
    """Bound objects reachable from a call operand that a call may change.

    Whether one did is its value's question at reduce (``_may_change``):
    the candidates are every object the operand reaches, never only those
    whose binding the source spells as a container."""
    found = []
    for node in _walk_values(root, kept_only=False):
        if _ref(node) in bound_refs and _may_be_changed(node):
            found.append(node)
    return found


def builtin_typed(node, scope, depth=0, *, names=frozenset()) -> bool:
    """Whether ``node`` is a decided builtin value all the way down: every
    object it is or holds has a builtin type, so no dunder a builtin invokes on
    it is user code.

    A ``Name`` is one when ``names`` holds it (the caller decided the object
    it denotes is one).  An operator, comparison, conditional, item read or
    f-string over builtin values is one too: the dunder it dispatches is a
    builtin's, and what that returns is builtin (``in``/``not in``/``is``/
    ``is not``/``not`` always give a ``bool``)."""
    from .nodes import (
        BinOp,
        BoolOp,
        BuiltinContainerProjection,
        Call,
        Compare,
        Constant,
        Dict,
        IfExp,
        JoinedStr,
        List,
        Name,
        PathAfterCall,
        PathContainerCall,
        Set,
        Slice,
        Starred,
        Subscript,
        Tuple_,
        UnaryOp,
    )

    if depth > 32:
        return False

    def builtin(child) -> bool:
        return builtin_typed(child, scope, depth + 1, names=names)

    node = _identity(node)
    if isinstance(node, (Constant, JoinedStr)):
        return True
    if isinstance(node, Name):
        return node.id in names
    if isinstance(node, (List, Tuple_, Set)):
        return all(builtin(e) for e in node.elts)
    if isinstance(node, Dict):
        return all(k is not None and builtin(k) for k in node.keys) and all(
            builtin(v) for v in node.values
        )
    if isinstance(node, Starred):
        return builtin(node.value)
    if isinstance(node, BinOp):
        return builtin(node.left) and builtin(node.right)
    if isinstance(node, UnaryOp):
        return node.op.kind == "Not" or builtin(node.operand)
    if isinstance(node, BoolOp):
        return all(builtin(v) for v in node.values)
    if isinstance(node, Compare):
        operands = (node.left, *node.comparators)
        return all(
            op.kind in ("Is", "IsNot", "In", "NotIn")
            or (builtin(operands[index]) and builtin(operands[index + 1]))
            for index, op in enumerate(node.ops)
        )
    if isinstance(node, IfExp):
        return builtin(node.body) and builtin(node.orelse)
    if isinstance(node, Subscript):
        return builtin(node.value) and builtin(node.slice_)
    if isinstance(node, Slice):
        return all(
            part is None or builtin(part)
            for part in (node.lower, node.upper, node.step)
        )
    if isinstance(node, BuiltinContainerProjection):
        return builtin(node.call)
    if isinstance(node, PathAfterCall):
        # A name's object after the one door's call: a builtin receiver
        # given builtin operands is a builtin after it.
        return not node.steps and builtin(node.call)
    if isinstance(node, PathContainerCall):
        return builtin(node.receiver) and all(builtin(a) for a in node.args)
    if getattr(node, "kind", None) == "OpaqueObjectStateV1":
        return builtin(node.base)
    if isinstance(node, Call) and not node.keywords:
        # A builtin by its binding (``_builtin_callee``), never its spelling.
        callee = _builtin_callee(node)
        cited = _cited()
        if callee in cited.immutable_result:
            return True
        if callee in cited.constructors:
            return all(builtin(a) for a in node.args)
    return False


def _rebind(statement, pre_scope, scope, targets):
    """Rebind each name that held a target object before ``statement`` and
    still holds that value: a name the statement itself bound holds the value
    the statement computed (``x = g(r)``), not the object ``g`` was given.

    ``targets`` are ``(object, rules, subject)``: ``rules`` a tuple of
    ``(method, pure, sharer)`` (``_may_change``), None for an object left
    unknown whatever its value; ``subject`` the read whose value decides
    (None: a name bound to the object decides by its own value, a name that
    holds it by the object's).  Each name is rebound to its value after the
    call (``_havoc``), which the value decides at reduce."""
    from .nodes import Name
    from .shadow import occurrence_tags_of

    if not targets:
        return scope
    found = {}
    asked = set()
    for target, rules, explicit in targets:
        # A read and the node it was given are one object: ask once.
        question = (_object_key(target), rules, id(explicit))
        if question in asked:
            continue
        asked.add(question)
        exact, containing = aliases(scope, target)
        held = explicit
        if held is None:
            if exact and exact[0] in scope:
                held = _read_of(scope[exact[0]])
            elif isinstance(target, Name):
                held = target
        for name in (*exact, *containing):
            if name in scope and (
                name not in pre_scope or scope[name] is not pre_scope[name]
            ):
                continue
            if rules is None:
                conditions = None
            elif explicit is None and name in exact:
                conditions = [(None, rule) for rule in rules]
            elif held is None:
                # No read of the object it holds: nothing to decide by.
                conditions = None
            else:
                conditions = [(held, rule) for rule in rules]
            if name not in found:
                found[name] = conditions
            elif found[name] is None or conditions is None:
                found[name] = None
            else:
                found[name] = [*found[name], *conditions]
    if not found:
        return scope
    tags = occurrence_tags_of(statement)
    binding = {}
    for name, conditions in found.items():
        prior = _read_of(scope[name]) if name in scope else _global_read(targets, name)
        binding[name] = _havoc(
            statement, name, tags, prior=prior, conditions=conditions
        )
    binding = statement._binding_entries(binding, scope)
    return {**scope, **binding}


def _global_read(targets, name):
    """A target that is a read of the unbound ``name`` (a global), or None."""
    from .nodes import Name

    for target, _rules, _subject in targets:
        if isinstance(target, Name) and target.id == name:
            return target
    return None


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
#   Its ``(post-state, result)`` pair is bound under the statement's key;
#   every projection below reads the pair there, never the call again.
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


def path_steps(receiver):
    """``(root, steps)`` of an attribute/subscript chain, or ``(None, ())``.

    A step is ``("attr", name)``, ``("item", key)`` for a key whose ground
    value is an ``int``/``str`` (``ground_subscript_key``: a literal, ``-1``,
    or a key reference whose ``of`` is one; never the key reduced), or
    ``("undecided", None)``."""
    from .nodes import Attribute, Subscript, ground_subscript_key

    steps = []
    node = receiver
    while isinstance(node, (Attribute, Subscript)):
        if isinstance(node, Attribute):
            steps.append(("attr", node.attr))
        else:
            key = ground_subscript_key(node.slice_)
            steps.append(("undecided", None) if key is None else ("item", key))
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
    """The node a display holds at a decided item step, or None.  A dict
    display's key is decided as a subscript's is (``ground_subscript_key``:
    ``{k: []}`` where ``k`` holds ``'a'`` holds ``[]`` at ``'a'``); one key
    that is not decided (or a ``**`` member) leaves the member undecided."""
    from .nodes import Starred, ground_subscript_key

    kind, key = step
    if kind != "item":
        return None
    node_kind = getattr(node, "kind", None)
    if node_kind == "Dict":
        found = None
        for item in node.items:
            existing = None if item.key is None else ground_subscript_key(item.key)
            if existing is None:
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


def _path_after(
    site_node,
    call,
    root,
    steps,
    mode,
    label,
    tags,
    unshared,
    inner=None,
    evaluation=None,
    prior=None,
):
    """The root or the object after ``call``.  With ``evaluation`` (the
    statement's key, ``path_mutation_statement``) it reads the call's pair
    the statement bound under that key, never the call evaluated again.
    ``root`` is the read of the root at the statement (a name's reference
    to its key), never the expression the name was given.  ``prior`` (no
    steps) is the read of the name this node rebinds, before the call: an
    immutable receiver is unchanged, and the name keeps its own value."""
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
        ("prior", MaybeChild(None if prior is None else _handle_of(prior))),
    ]
    if evaluation is not None:
        fields.append(("evaluation", Leaf(evaluation)))
    return _materialize(site_node, "PathAfterCall", tuple(fields), tags)


def _mutating_named_call(call) -> bool:
    """``<receiver>.<m>(*args)`` with ``m`` a mutating method of some builtin
    container, no keywords and no ``*`` argument."""
    from .nodes import Attribute, Call, Starred
    from sugar_lift_py_tests.floor.builtin_container_method import (
        ANY_MUTATING_METHOD,
    )

    return (
        isinstance(call, Call)
        and not call.keywords
        and isinstance(call.func, Attribute)
        and call.func.attr in ANY_MUTATING_METHOD
        and not any(isinstance(arg, Starred) for arg in call.args)
    )


def _container_call(
    site_node,
    receiver,
    method,
    args,
    fallback,
    tags,
    *,
    label,
    value_first=False,
    operator_kind=None,
    operator_site=None,
):
    """One mutating operation's ``PathContainerCall``: the call is evaluated
    once and the receiver's value decides it (``PathContainerCallSugar``).

    ``fallback`` is the ordinary call a method takes on a value the floor
    does not cite; an item store, an item delete and an in-place operator
    have none (their ordinary operation is the floor's own).  ``label``
    names the unknown its receiver is after an ordinary call."""
    from .backend import Child, Children, Leaf, MaybeChild
    from .shadow import _handle_of

    fields = (
        ("receiver", Child(_handle_of(receiver))),
        ("args", Children(tuple(_handle_of(arg) for arg in args))),
        ("method", Leaf(method)),
        ("fallback", MaybeChild(None if fallback is None else _handle_of(fallback))),
        ("occurrence", Leaf(_evaluation(site_node, tags))),
        ("label", Leaf(label)),
        ("value_first", Leaf(value_first)),
    )
    if operator_kind is not None:
        # ``r OP= x``: the operator (``operators.operator_for``) and its
        # source token, minted before substitution (``AugAssign``).
        fields = (
            *fields,
            ("operator_kind", Leaf(operator_kind)),
            ("operator_site", Leaf(operator_site)),
        )
    return _materialize(site_node, "PathContainerCall", fields, tags)


def path_mutation_statement(statement, scope, *, call, target_name=None):
    """The shadow statement for ``<path>.<mutator>(*args)``, or None.

    ``call`` is the statement's call, already substituted against ``scope``.
    """
    if not _mutating_named_call(call):
        return None
    # ``root_read`` is the read of the root at the statement: for a name an
    # assignment bound, a reference to its key.  The root after the call
    # reads ``root_read``, never the display or call evaluated again at each
    # read of the name.
    root_read, steps = path_steps(call.func.value)
    if root_read is None:
        return None
    return _mutation_through(statement, scope, call, root_read, steps, target_name)


def name_mutation_statement(
    statement,
    scope,
    *,
    site,
    name,
    receiver,
    method,
    args,
    fallback=None,
    target_name=None,
    value_first=False,
    operator_kind=None,
    operator_site=None,
    inplace=False,
):
    """The one door for a mutating operation on the object a name denotes.

    ``r.append(x)``, ``x = r.pop()`` (``fallback`` the call), ``r[k] = v``
    (``__setitem__``, ``value_first``: Python evaluates ``v`` first),
    ``del r[k]`` (``__delitem__``) and ``r += x`` (``__iadd__``,
    ``operator_kind``, ``inplace``; ``target_name`` the name itself, which
    Python binds to the in-place result), whatever ``name`` was given -- a display,
    ``'a b'.split()``, a parameter, a global.  ``receiver`` (the read of
    ``name`` at the statement) and ``args`` are already substituted.

    The operation is one ``PathContainerCall`` with no steps, evaluated at
    the statement; the value the read holds at reduce decides it
    (``PathContainerCallSugar``): a builtin container takes its cited
    mutation, any other value the ordinary operation.  Every name bound to
    the object is rebound to the object after the call (``PathAfterCall``),
    every name that holds it to its value after the call
    (``ReceiverAfterCall``), which the value decides at reduce."""
    from .nodes import Node, _evaluation_ref
    from .shadow import occurrence_tags_of

    tags = occurrence_tags_of(statement)
    call = _container_call(
        site,
        receiver,
        method,
        args,
        fallback,
        tags,
        label=name,
        value_first=value_first,
        operator_kind=operator_kind,
        operator_site=operator_site,
    )
    # The statement evaluates the call once and binds its pair under its own
    # key; the object after it and the call's value read that key.  ``r +=
    # x`` binds its in-place result under the statement's key, as Python
    # binds ``r`` to it, and the pair under a key of its own.
    evaluation = statement._evaluation_key(scope)
    rebinds_name = inplace and target_name == name
    pair_key = evaluation
    if rebinds_name and isinstance(evaluation, str):
        from sugar_lift_py_tests.temporal.temporal_context import projection_key

        pair_key = projection_key(evaluation, f"{method}()")

    def after_for(prior):
        return _path_after(
            site,
            call,
            receiver,
            (),
            "root",
            name,
            tags,
            True,
            evaluation=pair_key,
            prior=prior,
        )

    root = _identity(receiver)
    exact, containing = aliases(scope, root)
    if name not in exact:
        # ``name`` is the receiver: it denotes the object after the call,
        # whatever its binding is (a guarded read included).
        exact.append(name)
    after = after_for(receiver)
    names, states, evaluated = [], [], [call, after]
    for alias in exact:
        if alias == target_name or alias in names:
            continue
        names.append(alias)
        # Each name reads the object after the call; an immutable receiver
        # is unchanged, and the name keeps its own value.
        states.append(
            after
            if alias == name or alias not in scope
            else after_for(_read_of(scope[alias]))
        )
    # A name whose value holds the object, or shares anything with it: its
    # value after the call is decided at reduce by the receiver's value.  A
    # builtin container's cited mutation changes the container only (its
    # holders are unknown after it); an ordinary call may change anything it
    # reaches (``sharer``).
    graph = _graph(root)
    for alias, value in scope.items():
        if not isinstance(alias, str) or alias in names or alias == target_name:
            continue
        state = _state(value)
        if not isinstance(state, Node):
            continue
        if getattr(state, "kind", None) in _NEVER_HAVOC_KINDS:
            continue
        holds = alias in containing
        if holds or (graph and _graph(state) & graph):
            holder = _havoc(
                site,
                alias,
                tags,
                prior=_read_of(value),
                conditions=[(receiver, (method, False, not holds))],
            )
            names.append(alias)
            states.append(holder)
            evaluated.append(holder)
    rebinds = None
    if target_name is not None:
        result = _projection(site, call, 1, tags, pair_key)
        names.append(target_name)
        if rebinds_name and isinstance(evaluation, str):
            # ``r += x`` writes ``r`` under the statement's key: every later
            # read of ``r`` (a live loop's carried write, a function's read of
            # a module global) reads that key.  ``r`` still denotes the object
            # the call was made on (``of``): a container's in-place result is
            # the container, and an immutable receiver's aliases keep their
            # own value (``PathAfterCall``'s ``prior``).
            evaluated.append(result)
            rebinds = (target_name, len(evaluated) - 1, evaluation)
            states.append(
                _evaluation_ref(
                    statement, statement.target.span, evaluation, name, of=after
                )
            )
        else:
            states.append(result)
    return _statement(
        statement, names, states, evaluated, tags, pair_key, rebinds=rebinds
    )


def _mutation_through(statement, scope, call, root_read, steps, target_name):
    """The path door's statement for ``call`` on the object ``root_read``
    reaches through ``steps``."""
    from .nodes import Node
    from .shadow import occurrence_tags_of

    receiver = call.func.value
    # ``root`` is the object ``root_read`` denotes (``_identity``: the display
    # or call the name was given), which decides the shape only.
    root = _identity(root_read)
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
    path_call = _container_call(
        call, receiver, call.func.attr, call.args, call, tags, label="receiver"
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
    # The statement evaluates the call once and binds its pair under its own
    # key; the root after it, the object after it and the call's value read
    # that key, never the call (and its operands) evaluated again.
    evaluation = statement._evaluation_key(scope)
    inner = _path_after(
        call,
        path_call,
        root_read,
        steps,
        "inner",
        "",
        tags,
        unshared,
        evaluation=evaluation,
    )
    root_after = _path_after(
        call,
        path_call,
        root_read,
        steps,
        "root",
        "",
        tags,
        unshared,
        inner=inner,
        evaluation=evaluation,
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
        states.append(_projection(call, path_call, 1, tags, evaluation))
    return _statement(statement, names, states, evaluated, tags, evaluation)


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
    """``state`` is ``actual`` after mutations through the one door
    (``name_mutation_statement``) with closed operands."""
    from .nodes import PathAfterCall, PathContainerCall

    node = _identity(state)
    while True:
        if (
            isinstance(node, PathAfterCall)
            and node.mode == "root"
            and not node.steps
        ):
            call = node.call
            if not isinstance(call, PathContainerCall):
                return False
            if not all(_closed_operand(arg) for arg in call.args):
                return False
            node = _identity(call.receiver)
            continue
        return same_object(node, actual)


def _mutated(state) -> bool:
    """Whether ``state`` is an object after a mutation through the one door
    (its value is not the object's value before)."""
    node = _identity(state)
    return (
        getattr(node, "kind", None) == "PathAfterCall"
        and node.mode == "root"
        and not node.steps
    )


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
    source helper, or None when the call is not one (it keeps its havoc).
    ``havoc_targets`` are ``_rebind``'s ``(object, rules, subject)``."""
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
        havoc_targets.extend(
            (node, _OPERAND_RULES, None)
            for node in _exposed(arg, bound_refs)
            if id(node) not in claimed
        )
    for index, actual in actuals:
        name = params[index].name
        state = _state(net[name]) if name in net else actual
        if not _closed_state(state, actual):
            havoc_targets.append((actual, None, None))
            continue
        if not _mutated(state):
            # The helper left the object as it was.
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
    {
        "PathAfterCall",
        "BuiltinContainerProjection",
        "SourceCallActualAfter",
        "OpaqueObjectStateV1",
    }
)


def _identity_root(node):
    """The creation node (or formal) whose object ``node`` denotes, else None."""
    node = _identity(node)
    kind = getattr(node, "kind", None)
    if kind == "PathAfterCall":
        # The object after the one door's call is the object it was called on.
        if node.mode == "root" and not node.steps:
            return _identity_root(node.root)
        return None
    if kind == "BuiltinContainerProjection":
        # ``r += x``: a builtin container's in-place result is itself.
        call = node.call
        if node.index == 1 and str(getattr(call, "method", "")).startswith("__i"):
            if decided_container_kind(call.receiver) is not None:
                return _identity_root(call.receiver)
        return None
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
        # A dict display hashes its keys: only a key decided as a subscript's
        # is (``ground_subscript_key``: an ``int``/``str``, whose hash calls
        # nothing) is decided here.
        from .nodes import ground_subscript_key

        return all(
            key is not None and ground_subscript_key(key) is not None
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
