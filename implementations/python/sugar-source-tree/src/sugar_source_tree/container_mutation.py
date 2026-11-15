"""A built-in container's mutation is a store on the object, seen by every alias.

``r = []; a = r; r.append(1); return a`` returns ``[1]``: ``append`` changes
the list object, and ``a`` names that same object. An assignment binds its
target to a reference to its own evaluation (``Assign.target_evaluations``),
which carries the right-hand side it was given as the object the name denotes
(``_evaluation_ref``, ``of``); the object is that node (``_identity``): two
names given the same node (``a = r``, ``x = y = []``) are the same object,
and a node built by another evaluation is another object.

THE LAW, at a statement that may mutate the object a name denotes -- a
method call on it, whatever the method is spelled (``r.append(x)``, ``x =
r.pop()``, ``o.reset()``), an item store (``r[k] = v``), an item delete
(``del r[k]``), an augmented assignment (``r += x``) or an augmented item
store (``r[k] += x``, a read-modify-store) -- whatever the name was given (a
display, ``'a b'.split()``, a parameter, a global, an object place, the
receiver an active ``__init__`` constructs):

- **One door** (``name_mutation_statement``).  The operation becomes one
  ``PathContainerCall`` with no path steps, evaluated at the statement: its
  halts leave there.  The VALUE the receiver holds at reduce decides it
  (``PathContainerCallSugar``): a ``ListValue``/``DictValue``/``SetValue``
  takes the cited CPython mutation (``floor/builtin_container_method``); any
  other value takes the ordinary operation -- the call, ``__setitem__``,
  ``__delitem__``, the in-place operator -- and its contents afterwards are
  unknown (an immutable value, or a container under a method its law does
  not cite as a mutation, is unchanged).  The source's spelling of the
  method or of the right-hand side never chooses the door: every name a
  call can reach takes it (``reaches``).
- **The object's names.** Every name bound to the receiver's object is
  rebound to the object after the call (``PathAfterCall``): the post-state.
  A target (``x = r.pop()``) is bound to the call's value; ``r += x`` binds
  ``r`` to the in-place result, as Python does.
- **Every other alias.** A name whose value merely holds the object
  (``outer = [r]``) is not rebuilt: it reads an unknown value minted at the
  call when the value the call changed is mutable (``ReceiverAfterCall``,
  decided at reduce).  Never the pre-call contents.
- **Exposure.** An object passed to a call the floor does not cite as pure
  (or formatted by an f-string, which runs ``format``), or the receiver of a
  method call outside the door, may be changed by it: each name bound to it
  -- a parameter, an instance of a source class, an object place and the
  receiver an active ``__init__`` constructs as much as a display -- is
  rebound to its value after the call, which the value decides at reduce
  (``ReceiverAfterCall``): a builtin container or a source object the call
  may change is unknown; an immutable value, or a container the call's cited
  method or cited pure builtin leaves alone, is unchanged.
- **Beyond the operands.** Code a call runs and the caller does not follow
  may reach what the caller holds without being handed it: the module
  objects it reads and the closure cells of its function
  (``_ambient_targets``).  One rule for every operation that may run code
  -- a call of any kind (a method, a callable value, an import, a builtin,
  a source function not followed), an operator, a comparison, a truth
  test, an item or attribute access, an iteration, an ``await``
  (``_sites_at``): each is rebound to its value after the operation,
  unknown when it runs code (decided at reduce by the values it runs on:
  a builtin value runs none; a call bound to a builtin exception class
  that stores its actuals as ``args`` runs none, decided by its binding,
  ``_constructs_builtin_exception``) and the value is one a call may change; a
  cell a nested scope declares ``nonlocal`` is unknown whatever it holds.
  Code that runs in the frame's own namespace -- ``exec``/``eval`` handed
  no globals mapping, any operation handed a ``locals()``/``vars()``
  mapping of it -- reaches every name of the frame too (``_frame_targets``):
  in a function each object a local is bound to is exposed (no local is
  rebound: CPython 3.13, PEP 667); at module or class scope each name may
  be rebound.
  A source function that is followed carries what it did to each one it
  names out of the call, as it does its actuals and the binding it wrote
  to each cell it declares ``nonlocal``: each name of the caller bound to
  such an object reads the value the call carried for it
  (``source_helper_actual_states``, ``call_site_value.caller_visible_values``).
- **A field store** (``o.f = v``, ``nodes.ReceiverFieldStoreStatement``) is
  ``type(o).__setattr__``: one operation more (``_FieldStore``).  The
  receiver's value decides at reduce what it runs
  (``field_store_method``, ``ObjectValue.field_store_route``): an instance
  whose class takes ``object``'s ``__setattr__`` and binds no data descriptor
  for the name stores the field and changes the object only; a source
  ``__setattr__`` or descriptor ``__set__`` is that function's call; a
  class lookup that does not decide, or a receiver that is no source
  instance, is a call the caller does not follow.  Where it runs code, what
  the object shares (``holder_states``), the stored value's objects
  (``_call_targets``) and what the caller holds beyond them
  (``_ambient_targets``) are exposed as at any such call.

The same door serves a mutation through a path (``path_mutation_statement``,
``path_item_statement``: ``a.b.append(x)``, ``a[i][j] = v``, ``d['k'][0] +=
1``, ``del a.b[k]``), an augmented item store on a receiver no bound name
reaches (``unrooted_item_statement``: ``f()[0] += 1``) and
``d.setdefault(k, v).<mutator>(...)`` on a name or through a path
(``self.d.setdefault(k, []).append(x)``), its value bound or not
(``setdefault_mutation_statement``: the setdefault is the receiver's
operation, its value the path's receiver).

Which object a read out of another object is, is decided only where the
source says (``_contains``): two members of one opaque value (``a, b =
g()``) may be one object, so a mutation through one makes every other (and
every holder) the mutation's opaque post-state.

Names are only rebound; nothing here decides what a call does.
"""

from __future__ import annotations

import functools
from typing import NamedTuple

from .construction_cache import AmbientSet


class _CitedBuiltins(NamedTuple):
    """The builtins this law cites, as the ``LanguageCallee`` members their
    binding reaches (CPython "Built-in Functions")."""

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
    # Runs the code it is handed in the calling frame's namespaces when it is
    # handed no globals mapping (``exec``, ``eval``).
    frame_code: frozenset
    # Called bare, returns a mapping of the calling frame's namespace
    # (``locals()``, ``vars()``).
    frame_mapping: frozenset


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
        frame_code=frozenset({C.BUILTIN_EXEC, C.BUILTIN_EVAL}),
        frame_mapping=frozenset({C.BUILTIN_LOCALS, C.BUILTIN_VARS}),
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


def _state(value):
    from .binding_state import BindingEntryV1, unwrap_binding_state

    if isinstance(value, BindingEntryV1):
        value = value.state
    return _identity(unwrap_binding_state(value))


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
        elif kind == "ReceiverFieldStoreState":
            # ``o.x = v``: the object ``o`` was, with a field stored.
            node = _identity(node.receiver)
        elif kind == "SourceCallActualAfter":
            # An object a followed callee shares, read after the call
            # (``_actual_after``): the object it was before the call.
            node = _identity(node.prior)
        else:
            break
        seen += 1
    return node


def _ref(node):
    """The object a node denotes: its backend handle, or the coordinate its
    construction authenticated.

    A read of a formal is re-spanned to its use site (``Name.substitute``), so
    every read is a fresh node over the same ``coordinate``.  Every read of
    an object place is the one object its construction made
    (``object_identity_cid``); the receiver an active
    ``__init__`` constructs is its binding coordinate.  A read of an
    assigned name is the object its assignment was given (``_identity``);
    a name's object after a mutation is the object before it (``_object``).

    Which object a node denotes is a fact of the node: the tree is immutable
    after materialize, and every field the answer reads (``of``, ``prior``,
    ``root``, ``receiver``, a coordinate) is read off the node's
    construction row.  The answer is kept on that row and decided once
    (``_denoted_ref``), never again at each ask: a name ``k`` statements'
    calls may have changed is ``k`` post-states deep, and every statement
    asks this of every binding in its scope and of every node it walks."""
    coordinate = getattr(type(node), "_coordinate", None)
    if coordinate is None:
        # Not a node (a binding state that holds none): nothing to keep it on.
        return _denoted_ref(node)
    row = coordinate(node)[2]
    if _REF in row:
        return row[_REF]
    ref = row[_REF] = _denoted_ref(node)
    return ref


# The construction-row key ``_ref`` keeps a node's answer under.
_REF = "__object_ref__"


def _denoted_ref(node):
    """``_ref``, decided from the node (``_object``)."""
    node = _object(node)
    kind = getattr(node, "kind", None)
    if kind in _FORMAL_KINDS and hasattr(node, "coordinate"):
        return ("formal", node.kind, _coordinate_key(node.coordinate))
    if kind == "ObjectPlaceStateV1":
        return ("object-place", node.object_identity_cid)
    if kind == "ConstructedReceiverRef":
        return ("constructed-receiver", node.binding_coordinate_cid)
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
    left_ref, right_ref = _ref(left), _ref(right)
    if isinstance(left_ref, tuple):
        # A coordinate key (``_ref``): every read of the object carries it.
        return left_ref == right_ref
    return left_ref is right_ref


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


def _walk_values(node, *, kept_only=True, closed=None):
    """Every node that may be (or hold) an object of this value: not inside
    code that does not run, nor inside an operand the value does not keep.

    ``kept_only=False`` asks what a call operand hands onward instead: an
    element read (``g(r[0])``) hands the element object itself.

    ``closed`` is a set the reader fills with ``id(current)`` for a node it
    was just handed and already has the answer for (``_holds``): nothing
    under that node is walked for it."""
    from .nodes import ClassDef, FunctionDef, AsyncFunctionDef, Lambda, Node

    stack = [node]
    seen = set()
    while stack:
        current = stack.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        yield current
        if closed is not None and id(current) in closed:
            continue
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
        if getattr(current, "kind", None) == "ReceiverAfterCall":
            # A value a call may have changed is the value it was (``prior``)
            # or an unknown.  The reads that decide which (``subjects``) are
            # not values it holds: a name exposed at a store on ``o`` does
            # not hold ``o`` by that.
            prior = getattr(current, "prior", None)
            if isinstance(prior, Node):
                stack.append(prior)
            continue
        for _name, _index, child in current._child_edges():
            if isinstance(child, Node):
                stack.append(child)


def _contains(state, target, depth=0) -> bool:
    """Whether the value ``state`` holds (or may be) ``target``'s object.

    An object read out of another -- ``x = d['k']``, ``a = c.items``, an
    unpack's member (``a, b = pair``: ``a`` is the object ``pair`` holds
    first, ``Assign._unpack_member_objects``) -- is held by the object it was
    read from, and so by every value that is or holds that object: a
    mutation of ``a`` changes what ``pair`` holds.

    Which object an item read is, is decided only where the source says
    (``_static_member``: ``r = [x]; r[0]`` is ``x``'s object).  Elsewhere --
    two members of one opaque value (``a, b = g()``: ``g`` may return the
    same list twice), a starred member's list, which holds the value's
    other members -- the read may be, or hold, anything the object it was
    read from holds (``_read_may_hold``): its identity is undecided, and a
    mutation through one makes the other the mutation's opaque post-state,
    never its old value.  ``depth`` bounds the chase; past it, a value may
    hold anything."""
    from .nodes import Name, Node

    if not isinstance(state, Node):
        return False
    if depth > _CONTAINS_DEPTH:
        return True
    if _holds(state, target, depth):
        return True
    if isinstance(target, Name):
        return False
    root, _steps = path_steps(_identity(target))
    if root is None:
        return False
    return same_object(state, root) or _contains(state, root, depth + 1)


# How many reads out of reads ``_contains`` follows before it answers that a
# value may hold the object (an undecided answer is never "it does not").
_CONTAINS_DEPTH = 16


def _holds(state, target, depth) -> bool:
    """Whether some node the value ``state`` reaches (``_walk_values``) is
    ``target``'s object, the member the source says ``target`` reads, or an
    item read that may hold it (``_read_may_hold``): ``_contains``'s walk.

    The answer is a fact of the two nodes: the tree is immutable after
    materialize, and nothing here reads a scope.  It is kept on ``state``'s
    construction row under what was asked of it (``_asked``) and decided
    once.  A node the walk reaches that already has its answer to the same
    question is not walked again: what it reaches is what its own walk
    reached (``_walk_values`` descends by the node alone).  A value after a
    call holds the value before it (``ReceiverAfterCall.prior``), so the
    answer for the new state of a name is one step from the answer its
    last state already has -- not a walk of every state the object has had,
    asked again for every name in the scope after every statement."""
    from .nodes import Name

    question, pinned = _asked(target)
    asked = (question, depth)
    known = state._coordinate()[2].get(_HOLDS)
    if known is not None and asked in known:
        return known[asked][0]
    named = isinstance(target, Name)
    member = None if named else _member_object(target)
    closed = set()
    found = False
    for node in _walk_values(state, closed=closed):
        if node is not state:
            earlier = node._coordinate()[2].get(_HOLDS)
            if earlier is not None and asked in earlier:
                if earlier[asked][0]:
                    found = True
                    break
                closed.add(id(node))
                continue
        if named:
            if isinstance(node, Name) and node.id == target.id:
                found = True
                break
        elif same_object(node, target) or (
            member is not None and same_object(node, member)
        ):
            found = True
            break
        if _read_may_hold(node, target, depth):
            found = True
            break
    state._coordinate()[2].setdefault(_HOLDS, {})[asked] = (found, pinned)
    return found


# The construction-row key ``_holds`` keeps a node's answers under:
# ``{(question, depth): (answer, pinned)}``.
_HOLDS = "__holds__"


def _asked(target):
    """``(question, pinned)``: what ``_contains`` reads of ``target``, as a
    key, and the object whose address the key holds (kept alive beside the
    answer so the address is never another object's), or None.

    A ``Name`` is asked by its spelling.  A read through a path (an
    attribute or item read) is asked by the node it denotes: its root, its
    steps and the member the source says it reads are that node's.  Any
    other target is asked only which object it is (``_ref``): it has no
    path, so every comparison ``_contains`` makes with it is
    ``same_object``."""
    from .nodes import Attribute, Name, Subscript

    if isinstance(target, Name):
        return ("name", target.id), None
    denoted = _identity(target)
    if isinstance(denoted, (Attribute, Subscript)):
        row = denoted._coordinate()[2]
        return ("path", id(row)), row
    ref = _ref(target)
    if isinstance(ref, tuple):
        return ("object", ref), None
    return ("object", id(ref)), ref


def _member_object(node):
    """The node a read out of a display the source decides names
    (``_static_member``: ``r = [x]; r[0]`` names ``x``), or None."""
    root, steps = path_steps(_identity(node))
    if root is None:
        return None
    return _static_member(_identity(root), steps)


def _undecided_member(node) -> bool:
    """Whether ``node`` denotes an item read out of an object whose member
    there the source does not say (``a, b = g()``'s ``a``, ``r[i]``, a
    starred member's slice): its identity is undecided."""
    from .nodes import Subscript

    node = _identity(node)
    return (
        isinstance(node, Subscript)
        and path_steps(node)[0] is not None
        and _member_object(node) is None
    )


def _read_may_hold(node, target, depth) -> bool:
    """Whether ``node``, an item read out of an object (``r[i]``, an unpack
    member ``For._item_of``, a starred member's slice), may be or hold
    ``target``'s object.

    Where the source says which member it reads (``_static_member``), that
    member's answer.  Otherwise the read's identity is undecided: it may be,
    or hold, anything the object it was read from holds -- never that
    object itself.  Only an item read asks: ``_walk_values`` stops at one
    (``_holds_no_reference``); an attribute read is walked through to its
    root already."""
    from .nodes import Name, Subscript

    if not isinstance(node, Subscript):
        return False
    root, steps = path_steps(node)
    if root is None:
        return False
    member = _static_member(_identity(root), steps)
    if member is not None:
        return _contains(member, target, depth + 1)
    if isinstance(target, Name):
        if isinstance(root, Name) and root.id == target.id:
            return False
    elif same_object(root, target):
        return False
    return _contains(root, target, depth + 1)


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


def _projection(site_node, call, index, tags, evaluation=None, *, binds=None):
    """Element ``index`` of ``call``'s ``(post-state, result)`` pair.

    With ``evaluation`` (the statement's key, ``name_mutation_statement``,
    ``path_mutation_statement``) the projection reads the pair the statement
    bound under that key (``ContainerMutationStatementSugar``): ``d[k] = v;
    ...; d[k]`` reads the dict the store left, never the call (and ``v``)
    evaluated again.  With ``binds`` (a call on ``self`` evaluated in place,
    ``nodes._call_on_self_in_place``) the projection evaluates the call
    where it stands and binds the pair under that key, as a walrus binds
    its value (``BuiltinContainerProjectionSugar``)."""
    from .backend import Child, Leaf
    from .shadow import _handle_of

    fields = (("call", Child(_handle_of(call))), ("index", Leaf(index)))
    if evaluation is not None:
        fields = (*fields, ("evaluation", Leaf(evaluation)))
    if binds is not None:
        fields = (*fields, ("binds", Leaf(binds)))
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


def object_across_items(loop, name, before):
    """The object ``name`` denotes at a live loop's header, for a name no item
    rebinds (``nodes._loop_header_bindings``): the object ``before`` (its
    read before the loop) denotes, as the earlier items' calls may have
    changed it -- the value after a call that may have changed it
    (``ReceiverAfterCall`` with ``prior``, ``_object``).  Only object
    identity asks it (the header reference's ``of``): the value is the
    header's key, and nothing reads the value it had before the loop as
    the shape of the value it has at an item."""
    from .shadow import occurrence_tags_of

    return _havoc(
        loop,
        name,
        occurrence_tags_of(loop),
        prior=before,
        conditions=[(None, _OPERAND_RULES[0])],
    )


def _read_of(value):
    """The node a read of a name bound to ``value`` is (``Name.substitute``),
    or None when the binding holds no node."""
    from .binding_state import BindingEntryV1, unwrap_binding_state
    from .nodes import Node

    if isinstance(value, BindingEntryV1):
        value = value.state
    value = unwrap_binding_state(value)
    return value if isinstance(value, Node) else None


def _statement(
    statement,
    names,
    states,
    evaluated,
    tags,
    evaluation=None,
    rebinds=None,
    pairs=(),
    pair_evaluation=None,
):
    """The shadow statement; ``evaluation`` is the statement's key, and it
    binds its call's pair (``evaluated[0]``) under ``pair_evaluation`` (the
    statement's key when None), which its projections read.  ``pairs`` are
    ``(key, index)``: a later operation's pair ``evaluated[index]`` the
    statement binds under ``key`` (``d.setdefault(k, v).append(x)``: the
    append's, after the setdefault's).

    ``rebinds`` is ``(name, index, key)`` for every statement that assigns a
    name (``r += x``, ``x = r.m()``, ``x = a.b.m()``, ``x = d.setdefault(k,
    v).m()``): the statement writes ``name`` -- the result
    ``evaluated[index]`` -- under ``key``, its evaluation of that name
    (``_name_write``): the write every later read of ``name`` reads.

    Every statement, bare or assigned, also writes each other name it binds
    -- a name bound to the object the call changed, a holder, a name sharing
    it -- to its state after the call under its own projection of the
    statement's key (``projection_key(evaluation, name)``), the state
    evaluated here, once, with the statement's values.  ``writes`` holds
    every ``(name, index, key)`` the statement writes, the assigned name's
    first: what a live loop carries from item to item
    (``ContainerMutationStatement.written_keys``), so an item begins with
    the object as the item before it left it.  The names' bindings are their
    states: every later read in the block reads the state, as before."""
    from .backend import Children, Leaf
    from .shadow import _handle_of

    evaluated = list(evaluated)
    writes = [] if rebinds is None else [tuple(rebinds)]
    if isinstance(evaluation, str):
        from sugar_lift_py_tests.temporal.temporal_context import projection_key

        assigned = None if rebinds is None else rebinds[0]
        for name, state in zip(names, states, strict=True):
            if name == assigned:
                continue
            index = next(
                (position for position, node in enumerate(evaluated) if node is state),
                None,
            )
            if index is None:
                evaluated.append(state)
                index = len(evaluated) - 1
            writes.append((name, index, projection_key(evaluation, name)))
    fields = (
        ("names", Leaf(tuple(names))),
        ("states", Children(tuple(_handle_of(state) for state in states))),
        ("evaluated", Children(tuple(_handle_of(node) for node in evaluated))),
    )
    if rebinds is not None:
        fields = (*fields, ("rebinds", Leaf(rebinds[0])))
    if writes:
        fields = (*fields, ("writes", Leaf(tuple(writes))))
    if evaluation is not None:
        fields = (*fields, ("evaluation", Leaf(evaluation)))
    if pair_evaluation is not None and pair_evaluation != evaluation:
        fields = (*fields, ("pair_evaluation", Leaf(pair_evaluation)))
    if pairs:
        fields = (*fields, ("pair_evaluations", Leaf(tuple(pairs))))
    if statement.kind == "Expr" and not pairs:
        # One call in statement position (``evaluated[0]``): when the
        # receiver's value takes the ordinary call, its value is recorded as a
        # bare call's is (``ContainerMutationStatementSugar``,
        # ``record_statement_value``).
        fields = (*fields, ("records_value", Leaf(True)))
    return _materialize(statement, "ContainerMutationStatement", fields, tags)


def _is_pure_call(call, scope) -> bool:
    """A cited pure builtin (by its binding) over builtin operands, or a
    method of a literal.  A method call on anything else is not pure here:
    whether it changes its receiver is the receiver's value's question, asked
    at reduce (``_call_targets``, ``ReceiverAfterCall``, the one door)."""
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


def threaded_header(statement) -> tuple:
    """The expressions a compound ``statement`` evaluates before its body: an
    ``if`` or ``while`` test, a ``for`` iterable, a ``with`` item's manager, a
    ``match`` subject (a live loop's, its loop's).  Each is threaded before
    what follows it reads the objects its calls reach (``thread_header``):
    by the statement's own substitution, for its body, and by the block, for
    the statements after it (``havoc_after``).  Empty for any other
    statement: everything a simple statement evaluates (an ``assert`` test,
    a ``return``, ``yield`` or ``raise`` operand, an assignment's value)
    runs before what follows it, which the block threads after it."""
    kind = getattr(statement, "kind", None)
    if kind == "LoopRecurrenceStatement":
        return threaded_header(statement.loop)
    if kind in ("If", "While"):
        return (statement.test,)
    if kind == "For":
        return (statement.iter,)
    if kind == "Match":
        return (statement.subject,)
    if kind == "With":
        return tuple(item.context_expr for item in statement.items)
    return ()


def _repeats_header(statement) -> bool:
    """Whether ``statement`` evaluates its header again before every item (a
    ``while`` test, a live ``while``'s): what the header's calls did is then
    the loop's, as every call in its body is (``havoc_after``)."""
    kind = getattr(statement, "kind", None)
    if kind == "LoopRecurrenceStatement":
        return _repeats_header(statement.loop)
    return kind == "While"


def thread_header(header, pre_scope, scope, *, repeated=False, operated=False):
    """``scope`` with what the calls in ``header`` (one expression, or a
    tuple of them in evaluation order) did to the objects they reach: the one
    rule for an expression a statement evaluates before what follows reads
    those objects (``havoc_after`` over it).  ``pre_scope`` is the scope the
    header was substituted against.  ``repeated``: the header runs again
    before every item of a loop (``_repeats_header``), so its calls take the
    loop's rule.  ``operated``: the statement then runs dunders of the
    header's value before what follows (``_operates_header``: a ``for``
    iterates it, an ``if``/``while`` tests its truth, a ``match`` matches
    it), which may run code as any operation does (``_Operated``).

    A compound statement's substitution threads its header before its body
    (``If``, ``While``, ``For``, ``With``, ``Match``, a comprehension's first
    iterable), and the block threads it again before the rest of the
    statement's calls (``havoc_after``, ``threaded_header``), as both bind a
    walrus in it (``nodes._scope_after``)."""
    nodes = header if isinstance(header, tuple) else (header,)
    for node in nodes:
        if node is not None:
            scope = havoc_after(
                node, pre_scope, scope, loop=repeated, operated=operated
            )
    return scope


def _operates_header(statement) -> bool:
    """Whether ``statement`` runs dunders of its header's value
    (``threaded_header``) before its body: a ``for`` iterates it
    (``__iter__``, ``__next__``), an ``if`` or ``while`` tests its truth
    (``__bool__``, ``__len__``), a ``match`` matches it (``__eq__``,
    ``__match_args__``, ``__getitem__``, ...)."""
    kind = getattr(statement, "kind", None)
    if kind == "LoopRecurrenceStatement":
        return _operates_header(statement.loop)
    return kind in ("For", "If", "While", "Match")


_ABSENT = object()


def _calls(statement, bound_refs, *, include_container_calls, threaded=()):
    """The operations ``statement`` runs now that may run code (``_sites_at``:
    every call, f-string field, operator, comparison, truth test, item or
    attribute access, iteration, ``await`` and ``yield``): not inside a
    nested def, and
    not inside a value a name was already bound to (that value's operations
    ran earlier), nor in ``threaded`` (the header the statement threads
    first, ``threaded_header``)."""
    from .nodes import (
        AsyncFunctionDef,
        ClassDef,
        FunctionDef,
        Lambda,
        Node,
        PathContainerCall,
    )

    stack = [statement]
    seen = set()
    headers = tuple(_handle(node) for node in threaded if node is not None)
    while stack:
        current = stack.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if headers and any(_handle(current) is header for header in headers):
            continue
        if current is not statement and _ref(current) in bound_refs:
            continue
        if isinstance(current, (Lambda, FunctionDef, AsyncFunctionDef, ClassDef)):
            if current is not statement:
                continue
            return
        yield from _sites_at(current, headers)
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


def havoc_after(statement, pre_scope, scope, *, loop=None, operated=False):
    """Rebind every object ``statement``'s calls may have changed to an unknown.

    ``pre_scope`` is the scope the statement was substituted against; the
    statement's calls name objects by the nodes that scope bound.  ``loop``:
    whether the statement may run its calls any number of times (by default,
    whether it is a loop).  ``operated``: ``statement`` is a header whose
    value its statement operates on (``thread_header``), one operation more.

    A compound statement's header (``threaded_header``) is evaluated before
    the rest of it: its calls are threaded first (``thread_header``), and the
    rest of the statement's calls, which its substitution read the header's
    objects after (``If.substitute`` and the others), are threaded from what
    the header left.  A name the statement itself bound keeps its binding.
    """
    from .nodes import (
        ContainerMutationStatement,
        For,
        LoopRecurrenceStatement,
        Node,
        PathContainerCall,
        While,
    )

    header = threaded_header(statement)
    if header:
        threaded = thread_header(
            header,
            pre_scope,
            pre_scope,
            repeated=_repeats_header(statement),
            operated=_operates_header(statement),
        )
        moved = {
            name: state
            for name, state in threaded.items()
            if pre_scope.get(name, _ABSENT) is not state
            and scope.get(name, _ABSENT) is pre_scope.get(name, _ABSENT)
        }
        if moved:
            scope = {**scope, **moved}
        pre_scope = threaded

    bound_refs = {
        _ref(_state(value))
        for value in pre_scope.values()
        if isinstance(_state(value), Node)
    }
    held = []

    def holdings():
        if not held:
            held.append(_ambient_objects(statement, pre_scope))
        return held[0]

    def ambient(site):
        # What the code ``site`` runs may reach beyond its operands
        # (``_ambient_targets``); the caller's holdings are read once.
        return _ambient_targets(statement, site, pre_scope, holdings)

    if isinstance(statement, ContainerMutationStatement):
        # Each of its calls is threaded (``d.setdefault(k, v).append(x)``
        # makes two); what their operands' own calls (or a call, for an
        # operand it keeps) may change is not, nor what a receiver's own
        # calls may change (``f(r)[0] += 1``, ``d[g(r)].append(x)``: what it
        # is handed, and a module object a source function reaches, as for
        # any statement's call).  A receiver no bound name reaches
        # (``unrooted_item_statement``: ``(a or b)[0] += 1``) may be any
        # object it reaches: the store may change each, which its value
        # decides at reduce.
        targets = []
        for call in statement.evaluated:
            if not isinstance(call, PathContainerCall):
                continue
            # The operation itself, when the receiver's value takes the
            # ordinary call, runs code the caller does not follow: what it
            # may reach beyond its operands (``_ambient_targets``).  So does
            # every operation its receiver and operands run.
            targets.extend(ambient(call))
            for inner in _calls(
                call.receiver, bound_refs, include_container_calls=False
            ):
                targets.extend(_call_targets(inner, pre_scope, bound_refs))
                targets.extend(ambient(inner))
            if _unrooted(call.receiver):
                rules = ((call.method, False, False),)
                targets.extend(
                    (node, rules, None) for node in _exposed(call.receiver, bound_refs)
                )
            for arg in call.args:
                targets.extend(
                    (node, _OPERAND_RULES, None) for node in _exposed(arg, bound_refs)
                )
                for inner in _calls(arg, bound_refs, include_container_calls=False):
                    targets.extend(_call_targets(inner, pre_scope, bound_refs))
                    targets.extend(ambient(inner))
        # A call on ``self`` in place among its operands
        # (``lst.append(super().m())``) is one call more (``calls_on_self``).
        on_self = calls_on_self(statement)
        targets.extend(_calls_on_self_reach(on_self, bound_refs, ambient))
        havocked = _rebind(statement, pre_scope, scope, targets)
        return calls_on_self_left(statement, pre_scope, scope, havocked, calls=on_self)
    # A loop that may run its body any number of times leaves every object a
    # mutation in that body changed unknown (when its value is one a
    # mutation changes); a branch's mutations are threaded by the branch and
    # joined.
    if loop is None:
        loop = isinstance(statement, (For, While, LoopRecurrenceStatement))
    targets = []
    applied = []
    sites = _calls(
        statement,
        bound_refs,
        include_container_calls=loop,
        threaded=header,
    )
    if operated:
        sites = (*sites, _Operated(statement))
    for call in sites:
        # A call handed the frame's own namespace (``_reaches_the_frame``)
        # may change through it what no actual names: it is not followed,
        # and takes the one exposure rule (``_ambient_targets``).
        helper = (
            None
            if loop or _reaches_the_frame(statement, call)
            else source_helper_actual_states(call, bound_refs, pre_scope)
        )
        if helper is not None:
            havoc_targets, states = helper
            targets.extend(havoc_targets)
            applied.extend(states)
            continue
        if isinstance(call, PathContainerCall):
            targets.extend(ambient(call))
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
        # An operation this statement does not follow -- a call of a source
        # function, a method, a callable value, an import, a builtin; an
        # operator, a truth test, an item or attribute access, an
        # iteration, an ``await``, a ``yield`` (the consumer's code, before
        # the frame resumes) -- may change what the caller holds beyond
        # its operands: the module objects and the closure cells its code
        # can reach (``_ambient_targets``).
        targets.extend(ambient(call))
    # A call on ``self`` evaluated in place (``nodes._call_on_self_in_place``)
    # is a call like any other: what it is handed and what its code may
    # reach beyond them take the exposure rule, and every name bound to
    # ``self`` reads it as the call states it left it (``calls_on_self_left``).
    on_self = calls_on_self(statement, threaded=header)
    targets.extend(_calls_on_self_reach(on_self, bound_refs, ambient))
    havocked = _rebind(statement, pre_scope, scope, targets)
    if applied:
        havocked = _apply_actual_states(
            statement, pre_scope, scope, havocked, applied
        )
    return calls_on_self_left(
        statement, pre_scope, scope, havocked, loop=loop, calls=on_self
    )


def _is_call_on_self(node) -> bool:
    """Whether ``node`` is a call on ``self`` evaluated in place
    (``nodes._call_on_self_in_place``): the projection of the value of a
    ``PathContainerCall`` made on the frame's receiver formal."""
    if getattr(node, "kind", None) != "BuiltinContainerProjection":
        return False
    call = getattr(node, "call", None)
    return getattr(call, "kind", None) == "PathContainerCall" and isinstance(
        getattr(call, "frame_receiver", None), str
    )


def calls_on_self(evaluated, threaded=()) -> list:
    """The calls on ``self`` evaluated in place (``_is_call_on_self``) that
    ``evaluated`` runs itself: not one in a statement of a suite it holds
    (each is its block's, threaded there), in a header its statement
    threaded first (``threaded``, ``thread_header``), in a function, lambda
    or class nested in it, or inside a read of a value an earlier evaluation
    made (``_READ_KINDS``).  Each once, by its handle."""
    from .nodes import AsyncFunctionDef, ClassDef, FunctionDef, Lambda, Node, Statement

    span = getattr(evaluated, "span", None)
    unit = getattr(evaluated, "unit", None)
    if (
        span is not None
        and unit is not None
        and unit.source.find("super", span.start, span.end) < 0
    ):
        # A call on ``self`` is spelled ``super``: none here.
        return []
    headers = tuple(_handle(node) for node in threaded if node is not None)
    nested = (Statement, Lambda, FunctionDef, AsyncFunctionDef, ClassDef)
    found = []
    seen = set()
    stack = [evaluated]
    while stack:
        current = stack.pop()
        if not isinstance(current, Node) or id(current) in seen:
            continue
        seen.add(id(current))
        if headers and any(_handle(current) is header for header in headers):
            continue
        if current is not evaluated and isinstance(current, nested):
            continue
        if _is_call_on_self(current):
            if not any(_handle(current) is _handle(known) for known in found):
                found.append(current)
            # Its operands are evaluated before it, in place.
            stack.extend(current.call.args)
            continue
        if current is not evaluated and getattr(current, "kind", None) in _READ_KINDS:
            continue
        stack.extend(child for _name, _index, child in current._child_edges())
    return found


def _calls_on_self_reach(found, bound_refs, ambient):
    """``_rebind``'s targets for the calls on ``self`` in place ``found``:
    every bound object an operand hands the call (``_OPERAND_RULES``), and
    what the code it runs may reach beyond them (``ambient``,
    ``_ambient_targets``) -- the one exposure rule, as for every call."""
    targets = []
    for projection in found:
        call = projection.call
        targets.extend(ambient(call))
        for arg in call.args:
            targets.extend(
                (node, _OPERAND_RULES, None) for node in _exposed(arg, bound_refs)
            )
    return targets


def calls_on_self_left(evaluated, pre_scope, scope, result, *, loop=False, calls=None):
    """``result`` with every name bound to ``self`` reading it as the calls
    on ``self`` that ``evaluated`` runs in place (``calls_on_self``) left
    it: the one call form of ``super().m(...)``
    (``nodes._call_on_self_in_place``), wherever it sits.

    ``pre_scope`` is the scope ``evaluated`` was substituted against,
    ``scope`` the one after the names it binds itself, ``result`` that one
    after the exposure rule (``havoc_after``); in an expression's own
    threading (``nodes._scope_after``) all three are one scope.

    - Where the position decides it (``_last_call_on_self``: the call ran
      once on every path through ``evaluated``, and every other such call ran
      before it, on the object it read), each name bound to the object reads
      the receiver after that call: a read of the pair the call bound under
      its key (``PathAfterCall``), what the call states it did to it
      (``call_site_value.receiver_after_its_call``).
    - Where it does not -- a conditional operand (``a and super().m()``, a
      conditional expression's arm, a later comparison of a chain), a loop
      or a ``while`` test, a comprehension, two calls neither of which read
      the object the other left -- each reads the one undecided member: the
      object's value after a call that may have changed it
      (``ReceiverAfterCall``), never its state before the call.
    - A name ``evaluated`` bound itself keeps that binding where it was made
      after the call (a field store on the object the call left,
      ``self.y = 1 + super().m()``), or rebinds the name away from the
      object; one made on the object as it stood before the call
      (``self.items.append(super().m())``) is the undecided member.  A name
      the exposure rule rebound (another call may have changed it too) keeps
      that unknown.
    - Every name whose value holds the object reads its value after the call
      (``holder_states``, the one holder rule)."""
    from .nodes import Node
    from .shadow import occurrence_tags_of

    found = calls_on_self(evaluated) if calls is None else calls
    if not found:
        return result
    tags = occurrence_tags_of(evaluated)
    last = None if loop else _last_call_on_self(evaluated, found)
    binding = {}

    def untouched(name) -> bool:
        before = pre_scope.get(name, _ABSENT)
        return (
            scope.get(name, _ABSENT) is before
            and result.get(name, _ABSENT) is before
        )

    def site_of(projection):
        # The call itself, as the one door's statement names its site.
        fallback = getattr(projection.call, "fallback", None)
        return projection if fallback is None else fallback

    for projection in found:
        call = projection.call
        site = site_of(projection)
        root = _identity(call.receiver)
        exact, containing = aliases(pre_scope, root)
        if call.frame_receiver not in exact:
            exact.append(call.frame_receiver)
        for name in exact:
            if name in binding:
                continue
            before = pre_scope.get(name, _ABSENT)
            now = scope.get(name, _ABSENT)
            if now is not before:
                # ``evaluated`` bound it itself.
                state = _state(now) if now is not _ABSENT else None
                prior = _state(before) if before is not _ABSENT else None
                if (
                    isinstance(state, Node)
                    and isinstance(prior, Node)
                    and not _built_after(state, found)
                    and same_object(state, prior)
                ):
                    binding[name] = _havoc(evaluated, name, tags)
                continue
            if result.get(name, _ABSENT) is not now:
                continue
            prior = _read_of(before) if before is not _ABSENT else None
            if last is not None:
                after = last.call
                binding[name] = _path_after(
                    site_of(last),
                    after,
                    after.receiver,
                    (),
                    "root",
                    name,
                    tags,
                    True,
                    evaluation=last.binds,
                    prior=prior if prior is not None else after.receiver,
                )
            else:
                binding[name] = _havoc(
                    evaluated,
                    name,
                    tags,
                    prior=prior,
                    conditions=[(None, (call.method, False, False))],
                )
        for alias, holder in holder_states(
            site,
            pre_scope,
            receiver=call.receiver,
            root=root,
            containing=containing,
            method=call.method,
            tags=tags,
            skip=exact,
        ):
            if alias not in binding and untouched(alias):
                binding[alias] = holder
    if not binding:
        return result
    binding = evaluated._binding_entries(binding, result)
    return {**result, **binding}


def _last_call_on_self(evaluated, found):
    """The call of ``found`` whose receiver after it is the object as
    ``evaluated`` leaves it, or None where the position does not decide one:
    a call that binds its pair under a key (``binds``), runs once on every
    path through ``evaluated`` (``_once_on_every_path``), and read the object
    as every other call of ``found`` left it (``_built_after``: they ran
    before it, in place, ``nodes._scope_after``)."""
    for candidate in found:
        if not isinstance(getattr(candidate, "binds", None), str):
            continue
        if not _once_on_every_path(evaluated, candidate):
            continue
        if all(
            _handle(other) is _handle(candidate)
            or _built_after(candidate.call.receiver, (other,))
            for other in found
        ):
            return candidate
    return None


def _built_after(state, calls) -> bool:
    """Whether ``state``, an object's state, was made on the object as one of
    ``calls`` (calls on ``self`` in place) left it -- its read after the
    call, a field store on that, a mutation's post-state of that -- or on a
    state some call may have changed (``ReceiverAfterCall``: unknown at
    reduce, so never a state from before the call)."""
    handles = tuple(_handle(projection.call) for projection in calls)
    node = _identity(state)
    for _ in range(64):
        kind = getattr(node, "kind", None)
        if kind == "ReceiverAfterCall":
            return True
        if kind == "PathAfterCall" and getattr(node, "mode", None) == "root":
            if any(_handle(node.call) is handle for handle in handles):
                return True
            node = _identity(node.root)
        elif kind == "ReceiverFieldStoreState":
            node = _identity(node.receiver)
        elif kind == "SourceCallActualAfter":
            node = _identity(node.prior)
        else:
            return False
    return False


def _once_on_every_path(evaluated, node) -> bool:
    """Whether ``evaluated`` evaluates ``node`` once on every path through
    it that completes: each node on the way down evaluates the next as one
    of its operands (``_evaluated_edge``)."""
    path = _path_to(evaluated, node)
    if path is None:
        return False
    for parent, position in path:
        name, index, _child = _evaluation_order(parent)[position]
        if not _evaluated_edge(parent, name, index):
            return False
    return True


def _evaluated_edge(node, name, index) -> bool:
    """Whether Python evaluates ``node``'s child at ``(name, index)`` once on
    every path through ``node`` that completes, as one of its operands --
    never in a branch of ``and``/``or``/``x if t else y`` or a later
    comparison of a chain, never in a comprehension or a nested scope, never
    an assignment's target, never after an augmented store's target was read
    (``self.n += super().m()``), and never in a statement's own suite."""
    kind = node.kind
    if kind in _OPERAND_EDGE_KINDS:
        return True
    if kind in _VALUE_EDGE_KINDS:
        return name == "value"
    if kind == "AnnAssign":
        return name == "value" and getattr(node.target, "kind", None) == "Name"
    if kind in ("Assert", "IfExp"):
        return name == "test"
    if kind == "BoolOp":
        return index == 0
    if kind == "Compare":
        return name == "left" or index == 0
    return False


# Nodes every operand of which Python evaluates, in order, before the node
# itself completes.
_OPERAND_EDGE_KINDS = frozenset(
    {
        "Expr",
        "Return",
        "Raise",
        "Call",
        "Keyword",
        "Starred",
        "Attribute",
        "Subscript",
        "Slice",
        "BinOp",
        "UnaryOp",
        "Tuple",
        "List",
        "Set",
        "JoinedStr",
    }
)
# Nodes whose ``value`` Python evaluates once, first, on every path through
# them: an assignment's (a field store's) right-hand side, a walrus's, an
# f-string field's.
_VALUE_EDGE_KINDS = frozenset(
    {"Assign", "ReceiverFieldStoreStatement", "NamedExpr", "FormattedValue"}
)


# An operand handed to a call the floor does not cite: a builtin container in
# it may be changed; any other value is kept (``_may_change``).
_OPERAND_RULES = (("", False, False),)


def _call_targets(call, scope, bound_refs):
    """``(object, rules, subject)`` for every object ``call`` may change
    (``_rebind``): the receiver of a method call, whatever the method is
    spelled, and, unless the call is pure, every bound object its operands
    reach -- every name the call can reach is a candidate.  ``rules`` say how
    the value decides at reduce (``_may_change``); never the spelling of the
    method or of the receiver's binding.

    An f-string's replacement field (``f'{v}'``) runs ``format(v, spec)``:
    the cited pure builtin's rule over what ``v`` reaches.  An ``await``
    runs the awaitable's code, which may change whatever the awaitable
    holds: it is handed to that code as an operand is.  So is the value a
    ``yield`` hands its consumer, and the iterable a ``yield from``
    delegates to (``_SUSPENSION_KINDS``).  Any other operation
    (``_sites_at``) changes nothing here beyond what it reaches
    (``_ambient_targets``)."""
    from .nodes import Attribute, Call, Name

    if call.kind == "FormattedValue":
        if builtin_typed(call.value, scope):
            # A builtin's ``__format__`` over builtin values runs no user code.
            return []
        pure = (("", True, False),)
        return [(node, pure, None) for node in _exposed(call.value, bound_refs)]
    if call.kind == "Await" or call.kind in _SUSPENSION_KINDS:
        if call.value is None:
            # A bare ``yield`` hands the consumer ``None``.
            return []
        return [
            (node, _OPERAND_RULES, None) for node in _exposed(call.value, bound_refs)
        ]
    if call.kind == "FieldStore":
        # The stored value is handed to the code the store runs, as an
        # operand is to a call: the receiver's value decides whether it runs
        # any (``_field_store_rules``).
        if builtin_typed(call.receiver, scope):
            return []
        rules, subject = _field_store_rules(call, operand=True)
        return [(node, rules, subject) for node in _exposed(call.value, bound_refs)]
    if not isinstance(call, Call):
        return []
    targets = []
    func = call.func
    if (
        isinstance(func, Attribute)
        and isinstance(func.value, Name)
        and reaches(func.value, scope)
    ):
        # An unbound read (a formal, a global): no bound node names its
        # object, so the read itself is the candidate; its value decides.  A
        # bound receiver is a candidate below, as every operand is.
        targets.append((func.value, ((func.attr, False, False),), None))
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


# Bindings whose object may be one a call changes, which only its value at
# reduce decides (``_may_change``): a display or comprehension, a call result
# (an instance of a source class included), an item or attribute read, an
# operator result, a key reference with no right-hand side, a mutation's
# post-state (a field store's included), a parameter, an object place, the
# receiver an active ``__init__`` constructs.  A literal, a definition and an
# import are not.
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
        "ReceiverFieldStoreState",
        "ObjectPlaceStateV1",
        "ConstructedReceiverRef",
        *_FORMAL_KINDS,
    }
)


def _may_be_changed(node) -> bool:
    """Whether the object ``node`` denotes may be one a call changes: one
    rule for every name a call can reach, whatever it was given."""
    return getattr(_identity(node), "kind", None) in _EXPOSED_KINDS


def reaches(receiver, scope) -> bool:
    """Whether a method call on ``receiver`` (its read at the call, already
    substituted against ``scope``) reaches an object a call may change: an
    unbound read (a formal, a global), whose value decides at reduce, or a
    name bound to an object the one exposure rule admits
    (``_may_be_changed``).  The method's spelling is never asked: the one
    door takes every such call and the receiver's value decides what it did
    (``PathContainerCallSugar``)."""
    from .nodes import Name

    if isinstance(receiver, Name):
        if receiver.id not in scope:
            return True
        # An unsubstituted read (a loop body kept whole): its binding's object.
        receiver = _state(scope[receiver.id])
    return _may_be_changed(receiver)


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
    named = {}
    for target, rules, explicit in targets:
        # A read and the node it was given are one object: ask once.
        key = _object_key(target)
        question = (key, rules, id(explicit))
        if question in asked:
            continue
        asked.add(question)
        # The names an object has are its own: asked once however many
        # operations' values decide it.
        if key not in named:
            named[key] = aliases(scope, target)
        exact, containing = named[key]
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


def method_call(call) -> bool:
    """``<receiver>.<m>(*args)`` with no keywords and no ``*`` argument,
    whatever ``m`` is spelled: the shape the one door's operation carries.
    What the call does to its receiver is the receiver's value's question
    at reduce (``PathContainerCallSugar``)."""
    from .nodes import Attribute, Call, Starred

    return (
        isinstance(call, Call)
        and not call.keywords
        and isinstance(call.func, Attribute)
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
    frame_receiver=None,
    evaluation=None,
):
    """One mutating operation's ``PathContainerCall``: the call is evaluated
    once and the receiver's value decides it (``PathContainerCallSugar``).

    ``fallback`` is the ordinary call a method takes on a value the floor
    does not cite; an item store, an item delete and an in-place operator
    have none (their ordinary operation is the floor's own).  ``label``
    names the unknown its receiver is after an ordinary call.
    ``frame_receiver``: the call is ``super().m(...)`` on the frame's
    receiver formal of that name, evaluated in place
    (``nodes._call_on_self_in_place``).

    ``evaluation`` is the key the operation's pair is bound under.  The
    operation evaluates its receiver once; the ordinary call (``fallback``
    on ``receiver``) reads it through the receiver's own projection of that
    key (``receiver_evaluation``), which ``PathContainerCallSugar`` binds
    before the call, never the receiver evaluated again."""
    from .backend import Child, Children, Leaf, MaybeChild
    from .shadow import _handle_of

    receiver_evaluation = None
    if (
        fallback is not None
        and evaluation is not None
        and frame_receiver is None
        and getattr(getattr(fallback, "func", None), "value", None) is receiver
    ):
        from .nodes import _evaluation_ref
        from .shadow import rewrite
        from sugar_lift_py_tests.temporal.temporal_context import projection_key

        receiver_evaluation = projection_key(evaluation, "<receiver>")
        held = _evaluation_ref(
            site_node,
            receiver.span,
            receiver_evaluation,
            label,
            place=True,
            of=receiver,
        )
        fallback = rewrite(fallback, func=rewrite(fallback.func, value=held))

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
    if frame_receiver is not None:
        fields = (*fields, ("frame_receiver", Leaf(frame_receiver)))
    if receiver_evaluation is not None:
        fields = (*fields, ("receiver_evaluation", Leaf(receiver_evaluation)))
    return _materialize(site_node, "PathContainerCall", fields, tags)


def path_mutation_statement(statement, scope, *, call, target_name=None):
    """The shadow statement for ``<path>.<method>(*args)``, or None.

    ``call`` is the statement's call, already substituted against ``scope``.
    Every method takes it, whatever it is spelled: the receiver's value at
    reduce decides what the call did (``method_call``).
    """
    if not method_call(call):
        return None
    # ``root_read`` is the read of the root at the statement: for a name an
    # assignment bound, a reference to its key.  The root after the call
    # reads ``root_read``, never the display or call evaluated again at each
    # read of the name.
    root_read, steps = path_steps(call.func.value)
    if root_read is None:
        return None
    return _mutation_through(
        statement,
        scope,
        site=call,
        receiver=call.func.value,
        method=call.func.attr,
        args=call.args,
        fallback=call,
        root_read=root_read,
        steps=steps,
        target_name=target_name,
    )


def path_item_statement(
    statement,
    scope,
    *,
    site,
    receiver,
    method,
    args,
    operator_kind=None,
    operator_site=None,
):
    """The shadow statement for an item store or delete through a path, or
    None when ``receiver`` is no path from a name (an ordinary store).

    ``a.b[k] = v`` and ``a[i][j] = v`` (``__setitem__``, ``args`` the key
    and the value, the value evaluated first) and ``del a.b[k]``
    (``__delitem__``): the operation on the object the path reaches, through
    the one door (``_mutation_through``), as ``a.b.append(x)`` is.
    ``d['k'][0] OP= v`` is the same store with ``operator_kind``: a
    read-modify-store (``PathContainerCallSugar``: the receiver and the key,
    the item read, ``v``, the in-place operator on the item, the store of
    its result), so the root and every alias read the store's post-state.
    ``receiver`` (the path, ``site`` the target) and ``args`` are already
    substituted."""
    root_read, steps = path_steps(receiver)
    if root_read is None:
        return None
    return _mutation_through(
        statement,
        scope,
        site=site,
        receiver=receiver,
        method=method,
        args=args,
        fallback=None,
        root_read=root_read,
        steps=steps,
        value_first=method == "__setitem__" and operator_kind is None,
        operator_kind=operator_kind,
        operator_site=operator_site,
    )


def unrooted_item_statement(
    statement, scope, *, site, receiver, args, operator_kind, operator_site
):
    """The shadow statement for ``f()[k] OP= v``: an augmented item store
    whose receiver no bound name reaches (``path_item_statement`` found no
    path from one) -- an unnamed temporary, or an object only an expression
    reaches (``(a or b)[k] += v``).

    The same door's read-modify-store (``PathContainerCallSugar``): the
    receiver and the key, the item read, ``v``, the in-place operator on
    the item, the store of its result -- each once, in Python's order, the
    receiver's value deciding the store.  No name denotes the temporary, so
    the statement rebinds none; what the receiver's own calls may change,
    and every bound object the receiver reaches (the store may change it),
    is rebound after it (``havoc_after``)."""
    from .shadow import occurrence_tags_of

    tags = occurrence_tags_of(statement)
    call = _container_call(
        site,
        receiver,
        "__setitem__",
        args,
        None,
        tags,
        label="receiver",
        operator_kind=operator_kind,
        operator_site=operator_site,
    )
    return _statement(
        statement, (), (), (call,), tags, statement._evaluation_key(scope)
    )


def _unrooted(receiver) -> bool:
    """Whether ``receiver`` (or the root of its path) is an expression the
    statement evaluates, not a read of a value a name was bound to: the
    object it reaches is no name's, so a store on it may change anything it
    reaches (``unrooted_item_statement``)."""
    root, _steps = path_steps(receiver)
    node = receiver if root is None else root
    return getattr(node, "kind", None) not in _READ_KINDS


def setdefault_mutation_statement(statement, scope, *, name, call, target_name=None):
    """The shadow statement for ``d.setdefault(k, v).<mutator>(*args)`` on a
    name ``d`` (``name``) or on a path from one (``name`` None:
    ``self.d.setdefault(k, []).append(x)``, ``d[i].setdefault(k, v).pop()``),
    or None; with ``target_name``, ``x = d.setdefault(k, v).<mutator>(*args)``,
    ``x`` bound to the mutator's value (the pair the statement binds for it).

    Two operations of the one door, in one statement, in Python's order:
    ``d.setdefault(k, v)`` is the receiver's own operation (its pair bound
    under the statement's key) -- on a path, the operation through it, the
    path's root after it read as the path door reads it -- and its value --
    the object ``d[k]`` holds after it -- is the receiver of
    ``.<mutator>(*args)``, a path from the root through the setdefault's
    path and the item ``k`` (``_mutation_through``).  Every name bound to
    the root reads it after both; a name bound to the object at ``d[k]``
    reads that object after the mutator; anything else that shares them
    (the default ``v`` included) is unknown.  The receiver's value at reduce
    decides each operation (``PathContainerCallSugar``).  ``call`` is the
    statement's call, already substituted against ``scope``."""
    from .nodes import Attribute, Call, Starred, ground_subscript_key
    from .shadow import occurrence_tags_of, rewrite
    from sugar_lift_py_tests.temporal.temporal_context import projection_key

    if not method_call(call):
        return None
    inner = call.func.value
    if (
        not isinstance(inner, Call)
        or inner.keywords
        or not isinstance(inner.func, Attribute)
        or inner.func.attr != "setdefault"
        or len(inner.args) not in (1, 2)
        or any(isinstance(arg, Starred) for arg in inner.args)
    ):
        return None
    receiver = inner.func.value
    path_root, path = (None, ()) if name is not None else path_steps(receiver)
    if name is None and path_root is None:
        # Neither a name nor a path from one (``f().setdefault(k,
        # v).append(x)``): nothing names the dict, an ordinary call.
        return None
    tags = occurrence_tags_of(statement)
    evaluation = statement._evaluation_key(scope)
    setdefault = _container_call(
        inner,
        receiver,
        "setdefault",
        inner.args,
        inner,
        tags,
        label=name if name is not None else "receiver",
        evaluation=evaluation,
    )
    key = ground_subscript_key(inner.args[0])
    step = ("undecided", None) if key is None else ("item", key)
    if path_root is None:
        # ``d`` after the setdefault, and its value: the path's root and
        # receiver.
        root_read = _path_after(
            inner,
            setdefault,
            receiver,
            (),
            "root",
            name,
            tags,
            True,
            evaluation=evaluation,
            prior=receiver,
        )
        root_object, steps = None, (step,)
    else:
        # The root after the setdefault through its path (the path door's
        # root after a call), and the mutator's path from that root: the
        # setdefault's path, then ``k``.  The root still denotes its object.
        shape = _identity(path_root)
        held = _static_member(shape, path)
        root_read = _path_after(
            inner,
            setdefault,
            path_root,
            path,
            "root",
            "",
            tags,
            held is not None and _path_count(shape, held, {}) == 1,
            evaluation=evaluation,
        )
        root_object, steps = path_root, (*path, step)
    member = _projection(inner, setdefault, 1, tags, evaluation)
    method = call.func.attr
    return _mutation_through(
        statement,
        scope,
        site=call,
        receiver=member,
        method=method,
        args=call.args,
        # The ordinary call reads its receiver from the setdefault's pair,
        # never the setdefault evaluated again.
        fallback=rewrite(call, func=rewrite(call.func, value=member)),
        root_read=root_read,
        steps=steps,
        target_name=target_name,
        evaluation=projection_key(evaluation, f"{method}()"),
        before=((setdefault, evaluation),),
        shape_root=receiver if root_object is None else root_object,
        root_object=root_object,
    )


def holder_states(
    site,
    scope,
    *,
    receiver,
    root,
    containing,
    method,
    tags,
    skip=(),
):
    """``[(name, state)]``: the one holder rule, for every operation that
    changes the object ``root`` denotes -- the one door's mutation
    (``name_mutation_statement``) and a field store on it
    (``nodes.ReceiverFieldStoreStatement``, ``method`` its
    ``field_store_method``).  The names bound to the object
    itself read its post-state (the caller's); every other name ``scope``
    binds (``skip`` excepted) whose value may see the change is rebound to
    its value after the operation, which the value decides at reduce
    (``ReceiverAfterCall``, ``_may_change`` by ``receiver``'s value under
    ``method``): the opaque post-state, never its old value.

    - A name whose value holds the object (``containing``, ``aliases``:
      ``lst = [o]``, ``d = {'k': o}``, ``t = (o,)``, another object's field)
      holds the changed object.
    - A receiver whose identity is undecided -- a member of an opaque value
      (``a, b = g()``), an item the source does not say (``r[i]``) -- may be
      any object the value it was read from reaches: a name sharing one may
      hold it, never only share with it.
    - The operation may be an ordinary call -- code that reaches whatever
      the object holds (``sharer``) -- which the receiver's value decides at
      reduce, for the one door's mutation and for a field store alike.  A
      builtin container's cited mutation changes the container only, and a
      field store whose receiver's class takes ``object``'s ``__setattr__``
      and binds no data descriptor for the name changes the object only:
      neither reaches a name that merely shares something with the object.
      A field store that runs a ``__setattr__`` or a descriptor's
      ``__set__``, or whose class lookup does not decide, does
      (``ObjectValue.field_store_runs_code``).  Where no read of the
      receiver decides it (``_reads_again``: a temporary, a path), a sharer
      is exposed as an operand handed to a call is (``_OPERAND_RULES``)."""
    from .nodes import Node

    undecided = _undecided_member(root)
    graph = _graph(root)
    decides = _reads_again(receiver)
    found = []
    for alias, value in scope.items():
        if not isinstance(alias, str) or alias in skip:
            continue
        state = _state(value)
        if not isinstance(state, Node):
            continue
        if getattr(state, "kind", None) in _NEVER_HAVOC_KINDS:
            continue
        shares = bool(graph) and bool(_graph(state) & graph)
        holds = alias in containing or (undecided and shares)
        if holds or shares:
            if holds or decides:
                conditions = [(receiver, (method, False, not holds))]
            else:
                conditions = [(None, _OPERAND_RULES[0])]
            found.append(
                (
                    alias,
                    _havoc(
                        site,
                        alias,
                        tags,
                        prior=_read_of(value),
                        conditions=conditions,
                    ),
                )
            )
    return found


# The method a rule names for the one field store (``_may_change``), and for
# an operand that store hands the code it runs.  No Python identifier holds
# ``:``, so no method a source spells is read as one.
_FIELD_STORE_METHOD = "__setattr__:"
_FIELD_STORE_OPERAND = "__setattr__:value:"


def field_store_method(attr: str, *, operand: bool = False) -> str:
    """The method a rule names for the one field store ``o.<attr> = v``
    (``nodes.ReceiverFieldStoreStatement``): ``type(o).__setattr__`` with the
    stored name, which the receiver's value needs to decide what the store
    runs (``field_store_rule``, ``ObjectValue.field_store_route``).
    ``operand``: the rule is for an object the stored value hands the code
    the store runs."""
    return f"{_FIELD_STORE_OPERAND if operand else _FIELD_STORE_METHOD}{attr}"


def field_store_rule(method) -> "tuple[str, bool] | None":
    """``(attr, operand)`` of a field store's rule (``field_store_method``),
    or None for any other method."""
    if not isinstance(method, str):
        return None
    if method.startswith(_FIELD_STORE_OPERAND):
        return method[len(_FIELD_STORE_OPERAND) :], True
    if method.startswith(_FIELD_STORE_METHOD):
        return method[len(_FIELD_STORE_METHOD) :], False
    return None


def _reads_again(node) -> bool:
    """Whether evaluating ``node`` again after its statement runs nothing: a
    read of a value an earlier evaluation made (``_READ_KINDS``), the
    receiver an active ``__init__`` constructs, an object place, or one of
    those after field stores (``ReceiverFieldStoreState``, whose stored
    value is a key's read).  Only such a read is a rule's subject at reduce
    (``_havoc``): a temporary (``f().x = v``) or a path (``a.b.x = v``) is
    evaluated once, by its statement."""
    seen = 0
    while getattr(node, "kind", None) == "ReceiverFieldStoreState" and seen < 64:
        node = node.receiver
        seen += 1
    return getattr(node, "kind", None) in _READ_KINDS or getattr(
        node, "kind", None
    ) in ("ConstructedReceiverRef", "ObjectPlaceStateV1")


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
    ``del r[k]`` (``__delitem__``), ``r += x`` (``__iadd__``,
    ``operator_kind``, ``inplace``; ``target_name`` the name itself, which
    Python binds to the in-place result) and ``r[k] += x`` (``__setitem__``
    with ``operator_kind``: the read-modify-store of the item, ``args`` the
    key and ``x``), whatever ``name`` was given -- a display,
    ``'a b'.split()``, a parameter, a global.  ``receiver`` (the read of
    ``name`` at the statement) and ``args`` are already substituted.

    The operation is one ``PathContainerCall`` with no steps, evaluated at
    the statement; the value the read holds at reduce decides it
    (``PathContainerCallSugar``): a builtin container takes its cited
    mutation, any other value the ordinary operation.  Every name bound to
    the object is rebound to the object after the call (``PathAfterCall``),
    every name that holds it to its value after the call
    (``ReceiverAfterCall``), which the value decides at reduce."""
    from .shadow import occurrence_tags_of

    tags = occurrence_tags_of(statement)
    # The statement evaluates the call once and binds its pair under its own
    # key; the object after it and the call's value read that key.  ``r +=
    # x`` binds its in-place result under the statement's key, as Python
    # binds ``r`` to it, and the pair under a key of its own; ``x = r.m()``
    # binds its value under ``x``'s projection of that key (``_name_write``).
    evaluation = statement._evaluation_key(scope)
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
        evaluation=evaluation,
    )
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
    # Every name whose value holds the object, or shares anything with it
    # (the one holder rule, ``holder_states``).
    for alias, holder in holder_states(
        site,
        scope,
        receiver=receiver,
        root=root,
        containing=containing,
        method=method,
        tags=tags,
        skip=(*names, target_name),
    ):
        names.append(alias)
        states.append(holder)
        evaluated.append(holder)
    rebinds = None
    if target_name is not None:
        result = _projection(site, call, 1, tags, pair_key)
        names.append(target_name)
        # ``r += x`` denotes the object the call was made on (``of``): a
        # container's in-place result is the container, and an immutable
        # receiver's aliases keep their own value (``PathAfterCall``'s
        # ``prior``).  ``x = r.m()`` denotes the call's value.
        state, rebinds = _name_write(
            statement,
            target_name,
            result,
            evaluated,
            evaluation,
            in_place=rebinds_name,
            of=after if rebinds_name else result,
        )
        states.append(state)
    return _statement(
        statement,
        names,
        states,
        evaluated,
        tags,
        evaluation,
        rebinds=rebinds,
        pair_evaluation=pair_key,
    )


def _name_write(statement, target_name, result, evaluated, evaluation, *, in_place, of):
    """``(state, rebinds)``: a mutation statement's one write of the name it
    assigns (``target_name``) to the call's ``result``.

    Every statement that writes a name binds what it wrote under its
    evaluation of that name, never the name: ``r += x`` under the
    statement's key (``in_place``, as an ``AugAssign`` binds its
    evaluation), ``x = r.m()`` under the target's projection of it (as an
    ``Assign`` binds each target, ``Assign.target_evaluations``).  ``result``
    is evaluated by the statement (``evaluated``) and bound under that key
    once every value has completed (``ContainerMutationStatementSugar``);
    every later read of the name reads the key (``_evaluation_ref``, ``of``
    the object it denotes), and a live loop carries it
    (``ContainerMutationStatement.written_keys``).  Where the statement has
    no key, the name is the result itself and nothing is written under a
    key."""
    from .nodes import _evaluation_ref

    if not isinstance(evaluation, str):
        return result, None
    if in_place:
        key = evaluation
    else:
        from sugar_lift_py_tests.temporal.temporal_context import projection_key

        key = projection_key(evaluation, target_name)
    evaluated.append(result)
    targets = getattr(statement, "targets", None)
    target = targets[0] if targets else statement.target
    return (
        _evaluation_ref(statement, target.span, key, target_name, of=of),
        (target_name, len(evaluated) - 1, key),
    )


def _mutation_through(
    statement,
    scope,
    *,
    site,
    receiver,
    method,
    args,
    fallback,
    root_read,
    steps,
    target_name=None,
    value_first=False,
    evaluation=None,
    before=(),
    shape_root=None,
    operator_kind=None,
    operator_site=None,
    root_object=None,
):
    """The path door's statement for ``receiver.<method>(*args)`` on the
    object ``root_read`` reaches through ``steps`` (``site`` the source
    operation, ``fallback`` its ordinary call, None for an item store or
    delete; ``operator_kind``/``operator_site`` an augmented item store's
    operator, ``path_item_statement``).

    ``before`` are ``(call, key)``: operations the statement evaluates first,
    each pair bound under its key (``d.setdefault(k, v)``, whose value is
    ``receiver``); this operation's pair is bound under ``evaluation`` (the
    statement's key by default).  ``shape_root`` is the object whose display
    decides which member the path names (the root by default).
    ``root_object`` is the read of the root whose object the names are bound
    to, where ``root_read`` is the root after an earlier operation through a
    path (``self.d.setdefault(k, v).append(x)``); ``root_read`` by
    default."""
    from .nodes import Node
    from .shadow import occurrence_tags_of

    # ``root`` is the object ``root_read`` denotes (``_identity``: the display
    # or call the name was given), which decides the shape only.
    root = _identity(root_read if root_object is None else root_object)
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
    # The statement evaluates the call once and binds its pair under its own
    # key; the root after it, the object after it and the call's value read
    # that key, never the call (and its operands) evaluated again.
    if evaluation is None:
        evaluation = statement._evaluation_key(scope)
    path_call = _container_call(
        site,
        receiver,
        method,
        args,
        fallback,
        tags,
        label="receiver",
        value_first=value_first,
        operator_kind=operator_kind,
        operator_site=operator_site,
        evaluation=evaluation,
    )
    shape = root if shape_root is None else _identity(shape_root)
    member = _static_member(shape, steps)
    # Distinct display nodes are distinct objects: the source alone says the
    # root holds this member once, and nothing else in it can be the object.
    unshared = member is not None and _path_count(shape, member, {}) == 1
    if (
        member is None
        and getattr(shape, "kind", None) == "PathAfterCall"
        and shape.mode == "root"
        and shape.inner is not None
        and _same_steps(tuple(shape.steps), steps)
    ):
        # The root after an earlier call through this same path holds that
        # call's object there.
        member = shape.inner
    inner = _path_after(
        site,
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
        site,
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
    first = [call for call, _key in before]
    keys = [*(key for _call, key in before), evaluation]
    names, states, evaluated = [], [], [*first, path_call, root_after, inner]
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
            havoc = _havoc(site, name, tags)
            names.append(name)
            states.append(havoc)
            evaluated.append(havoc)
    rebinds = None
    if target_name is not None:
        # ``x = a.b.m()``, ``x = d.setdefault(k, v).m()``: ``x`` is written
        # to the call's value under its projection of the statement's key
        # (``keys[0]``), as ``x = r.m()`` is.
        result = _projection(site, path_call, 1, tags, evaluation)
        names.append(target_name)
        state, rebinds = _name_write(
            statement,
            target_name,
            result,
            evaluated,
            keys[0],
            in_place=False,
            of=result,
        )
        states.append(state)
    return _statement(
        statement,
        names,
        states,
        evaluated,
        tags,
        keys[0],
        rebinds=rebinds,
        pairs=tuple((key, index) for index, key in enumerate(keys) if index),
    )


# ---------------------------------------------------------------------------
# What a followed source helper did to an object its caller holds reaches the
# caller through the one projection at the call.
#
# ``def add(l): l.append(1)`` / ``r = []; add(r); return r`` returns ``[1]``:
# ``l`` is bound to the very object ``r`` names, and the helper's append is a
# store on that object. THE LAW, at a statement that calls a same-module
# source function whose body substitution can be followed:
#
# - The callee's frame reads, where its body ends, each object it shares with
#   its caller -- each formal, each closure cell it reads or declares
#   ``nonlocal``, each module global it reads -- that its body changed
#   (``nodes._exit_reads``).  The call carries each one's value out of the
#   callee's frame on every arm, completed and halted, under the call's key
#   and the object's label (``call_site_value.caller_visible_values``), with
#   the receiver field stores the callee made: the one projection of what a
#   callee did to what its caller sees.  A value the callee's frame does not
#   decide where it left (an unknown, a halt before the store that made it)
#   is carried undecided, an unknown minted at the call.
# - Here the caller's own threading decides only WHICH of its names read that
#   value (``source_helper_actual_states``): the helper's body is substituted
#   with each formal bound to the caller's actual node (the object), and an
#   object whose binding after the body is a state of that same object is
#   one the helper changed; every name bound to it reads the value the call
#   carried for its label (``SourceCallActualAfter``), never a node of the
#   callee's frame.  A cell the helper rebinds is that name alone.
# - A body with control flow is followed as a straight one is: its threading
#   joins each object over the branches (an ``if``'s, a ``try``'s or a
#   ``match``'s phi), and the object is changed where some arm changed it
#   (``_changed_state``).  Each arm of the callee's reduction carries what
#   its frame left of the object where that arm ended: a ``return`` its read
#   where the ``return`` stands (``nodes.FrameReturn``), every other arm the
#   read where the body ends; undecided where that arm does not decide it.
# - Anything else -- a formal rebound to another object, an object a loop or
#   a ``with`` left unknown, an object only CONTAINED in an actual -- keeps
#   the havoc: unknown after the call, never the pre-call contents.
#
# The objects followed are every one the helper reaches that its caller holds:
# its actuals, the module objects it reads as globals, and the closure cells
# it reads or declares ``nonlocal`` (``_callee_reach``). What it may reach and
# its frame does not carry -- a module object or cell only a source function
# it calls reads, and every other module object and cell of the caller when
# some call in it runs code that is not a source function by name
# (``_Reach.closed``) -- takes the havoc, as every call that is not followed
# does (``_ambient_targets``).
#
# The call's own halts are its faces at the call (the Call producer); a halt
# path never reaches the statement's continuation. A handler that catches one
# reads each such name at the halt (``Try._mid_statement_state``): the value
# the call carried where the halt's record holds the call's key -- the call
# ran, and left on that arm -- and the object as the statement found it where
# it does not, since then the call never ran (``at_halt``).
# ---------------------------------------------------------------------------

# Ambient to memo rows: a row that asked is served only where the helper is
# in progress or not as it was.
_HELPERS_IN_PROGRESS: AmbientSet = AmbientSet("helpers_in_progress")


def _followable_helper(definition) -> bool:
    """``definition`` is a frame a call by name runs as written: a plain
    ``def`` (no decorator: the name is bound to the function itself), no
    generator (a call runs none of its body), every formal positional or
    keyword (each actual binds one formal).  Its body may branch, loop,
    ``try`` and ``return`` anywhere: the threading follows every path, and
    each arm of its reduction carries what it left (``nodes._exit_reads``,
    ``nodes.FrameReturn``)."""
    from .nodes import FunctionDef

    if type(definition) is not FunctionDef or definition.decorators:
        return False
    if FunctionDef._owns_yield(definition.body):
        return False
    return all(
        param.param_kind == "positional_or_keyword" for param in definition.params
    )


def _same_read(node, actual) -> bool:
    """``node`` and ``actual`` are one read of one binding: the same node, or
    two reads of one formal's coordinate (``Name.substitute`` re-spans
    each)."""
    node, actual = _identity(node), _identity(actual)
    if node is actual or _handle(node) is _handle(actual):
        return True
    return (
        getattr(node, "kind", None) in _FORMAL_KINDS
        and getattr(actual, "kind", None) in _FORMAL_KINDS
        and _ref(node) == _ref(actual)
    )


def source_helper_actual_states(call, bound_refs, scope):
    """``(havoc_targets, [(object, call, label, name)])`` for a call to a
    followable source helper, or None when the call is not one (it keeps its
    havoc, ``havoc_after``).  ``havoc_targets`` are ``_rebind``'s ``(object,
    rules, subject)``.  Each other entry is an object the helper changed:
    every name bound to it reads, after the call, the value the call carried
    out of the helper's frame for ``label`` (``_actual_after``,
    ``call_site_value.caller_visible_values``).  ``name``: the cell the
    helper declares ``nonlocal`` and rebinds, whose name alone reads it; None
    for an object every alias of which does.

    The objects the helper reaches that its caller holds are followed alike:
    every actual that is a bound object a call may change
    (``_may_be_changed``, the exposure candidates), whatever it was given,
    every module object the helper reads as a global that ``scope``, the
    caller's, binds -- the helper's read of it is the caller's object -- and
    every closure cell it reads or declares ``nonlocal`` (``_callee_reach``).
    The helper's body, substituted with each one bound to the caller's node,
    says which it changed: one whose binding after the body is a state of
    the same object (a mutation through the one door, a field store, a
    nested helper's carried value, a call's exposure of it), or a cell the
    helper rebinds (``n += 1``, ``n = v``).  What that state IS is never
    read here: it is the callee frame's own, carried by the call.  A formal
    the body rebound to another object takes the havoc, as does a module
    object only a source function the helper calls reads (the helper's frame
    does not read it) and what it may reach and does not follow
    (``_unfollowed_reach``)."""
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
        if _ref(arg) in bound_refs and _may_be_changed(arg)
    ]
    if not actuals and not any(_ambient_objects(call, scope)):
        # Nothing the caller holds is the helper's to reach.
        return None
    reach = _callee_reach(call, scope)
    if reach is None:
        return None
    cells = [cell for cell in reach.cells if cell.direct]
    if not actuals and not reach.module and not cells:
        return None
    definition = reach.definition
    if not _followable_helper(definition):
        return None
    params = definition.params
    if len(params) != len(call.args):
        return None
    key = id(definition)
    if key in _HELPERS_IN_PROGRESS:
        return None
    node_scope = {param.name: arg for param, arg in zip(params, call.args)}
    havoc_targets = []
    # ``(name, object, label, rebinds)``: ``rebinds``, the helper's write of
    # ``name`` is the caller's binding (a ``nonlocal`` cell), not a local.
    followed = [
        (params[index].name, actual, f"actual:{index}", False)
        for index, actual in actuals
    ]
    # The module globals the helper's own frame reads: each is a name its
    # frame carries out of the call (``nodes._exit_reads``).
    read_by_frame = definition._module_global_references()
    for name, node in reach.module:
        if name in node_scope or name not in read_by_frame:
            # A formal of the same name hides the module object from the
            # helper's body, and a module object only a source function it
            # calls reads is not its frame's to carry: what that function
            # does to it is not followed here, so it takes the havoc.
            havoc_targets.append((node, None, None))
            continue
        node_scope[name] = node
        followed.append((name, node, f"global:{name}", False))
    for cell in cells:
        if cell.name in node_scope:
            havoc_targets.append((cell.node, None, None))
            continue
        node_scope[cell.name] = cell.node
        followed.append((cell.name, cell.node, f"cell:{cell.name}", cell.nonlocal_))
    # Every holder the helper follows -- an actual, a module object, a cell --
    # is one object key: the value the call carries for it is what the
    # caller reads on both arms, and no havoc of what the helper may reach
    # unfollowed takes it, whichever way the caller hands it over.
    followed_keys = {_object_key(node) for _n, node, _l, _r in followed}
    havoc_targets.extend(_unfollowed_reach(call, scope, reach, followed_keys))
    _HELPERS_IN_PROGRESS.add(key)
    try:
        _body, _changed, net = definition._substitute_body_tracked(
            definition.body, node_scope
        )
    finally:
        _HELPERS_IN_PROGRESS.discard(key)
    states = []
    # What an operand reaches that the helper does not follow takes the
    # exposure an operand handed to a call takes.  A followed holder is
    # excluded by its object key, never by the node that spelled it: the
    # walk reaches an actual's object through its read too (``_walk_values``
    # follows a read to the object it denotes), and that object is the
    # actual.
    for arg in call.args:
        havoc_targets.extend(
            (node, _OPERAND_RULES, None)
            for node in _exposed(arg, bound_refs)
            if _object_key(node) not in followed_keys
        )
    for name, actual, label, rebinds in followed:
        state = _state(net[name]) if name in net else actual
        rebound = (
            _rebinds(_read_of(net[name]), actual) if rebinds and name in net else False
        )
        if rebound is None:
            # One arm rebound the cell and another changed the object it
            # held: no one set of names reads one value after the call.
            havoc_targets.append((actual, None, None))
            continue
        if rebound:
            # The helper rebound the caller's cell (``n += 1``, ``n = v``) on
            # some arm: its write is the caller's binding, which the call
            # carries out of its frame.  Only the cell's name reads it --
            # another name bound to the object it held keeps it.
            states.append((actual, call, label, name))
            continue
        changed = _changed_state(state, actual)
        if changed is None:
            havoc_targets.append((actual, None, None))
            continue
        if changed:
            states.append((actual, call, label, None))
        # Otherwise the helper left the object as it was.
    return havoc_targets, states


def _changed_state(state, actual, depth=0):
    """Whether ``state`` (a followed holder's binding after the helper's
    body) is ``actual``'s object as the helper changed it: True for a chain
    of mutations through the one door (``name_mutation_statement``), or of
    values source helpers it called carried out (``SourceCallActualAfter``),
    begun from the actual itself; False for the actual itself, left as it
    was; None for anything else -- a formal the body rebound to another
    object, a value some unfollowed call left of it (``ReceiverAfterCall``),
    which keeps the havoc.  A join the body's threading built over its
    branches (an ``if``'s, a ``try``'s or a ``match``'s phi, ``IfExp``) is
    asked of every arm: changed where some arm changed it and every arm is
    the object, else None.  What the state holds is never read here: the
    call carries it (``source_helper_actual_states``)."""
    from .nodes import PathAfterCall, PathContainerCall

    node = _identity(state)
    changed = False
    for _ in range(64):
        if isinstance(node, PathAfterCall) and node.mode == "root" and not node.steps:
            call = node.call
            if not isinstance(call, PathContainerCall):
                return None
            node = _identity(call.receiver)
        elif getattr(node, "kind", None) == "SourceCallActualAfter":
            node = _identity(node.prior)
        elif getattr(node, "kind", None) == "IfExp":
            if depth >= _JOIN_DEPTH:
                return None
            arms = (
                _changed_state(node.body, actual, depth + 1),
                _changed_state(node.orelse, actual, depth + 1),
            )
            if any(arm is None for arm in arms):
                return None
            return changed or any(arms)
        else:
            break
        changed = True
    if not _same_read(node, actual):
        return None
    return changed


# The joins nested in one binding a follower asks arm by arm.
_JOIN_DEPTH = 16


def _binding_arms(written, depth=0):
    """The bindings ``written`` (a name's binding after a body) is on each
    path: ``written`` itself where it is no join, else every arm of the join
    the threading built over the body's branches (``IfExp``), each asked
    again; None past ``_JOIN_DEPTH`` nested joins."""
    if written is None:
        return ()
    if getattr(_identity(written), "kind", None) != "IfExp":
        return (written,)
    if depth >= _JOIN_DEPTH:
        return None
    node = _identity(written)
    body = _binding_arms(node.body, depth + 1)
    orelse = _binding_arms(node.orelse, depth + 1)
    if body is None or orelse is None:
        return None
    return (*body, *orelse)


def _rebinds(written, actual):
    """Whether ``written`` (a ``nonlocal`` cell's binding after a body that
    began with the cell bound to ``actual``) is the body's rebinding of the
    cell: True where some path rebinds it (``n += 1``, ``n = v``: a write's
    reference, never a binding the one door's mutation left) and none
    changed the object it held; False where no path rebinds it; None where
    one path rebinds it and another changed the object (no one set of names
    reads one value after the call), or where the join is past asking."""
    arms = _binding_arms(written)
    if arms is None:
        return None
    rebound = mutated = False
    for arm in arms:
        if _same_read(arm, actual):
            continue
        if getattr(arm, "kind", None) in _MUTATED_BINDINGS:
            mutated = True
        else:
            rebound = True
    if rebound and mutated:
        return None
    return rebound


# A binding the one door's mutation (or a source helper's such mutations)
# leaves on a name: the object, changed.  A write's reference (``n = v``,
# ``r += x``) is a rebinding.
_MUTATED_BINDINGS = frozenset({"PathAfterCall", "SourceCallActualAfter"})


class _Cell(NamedTuple):
    """The caller's read of a closure cell a source callee reaches."""

    name: str
    node: object
    # A callee declares it ``nonlocal``: it may rebind it, whatever it holds.
    nonlocal_: bool
    # The callee's own (its body reads or declares it), not a cell only a
    # source function it calls by name reaches.
    direct: bool


class _Reach(NamedTuple):
    """What a call to a source function named at the call reaches of what
    its caller holds, beyond its operands (``_callee_reach``)."""

    definition: object
    # ``[(name, node)]``: the module objects it, or a source function it
    # calls by name, reads as globals (``_module_objects_named``).
    module: list
    # ``[_Cell]``: the closure cells it, or such a function, reads.
    cells: list
    # Every operation in it, and in every source function it calls by name,
    # is one of those calls or runs no code (``_runs_no_code``): it reaches
    # nothing else.
    closed: bool


def _source_callee(call, scope):
    """The source ``def`` a call by name runs: the one the unit's lexical
    rows (or the module) resolve it to, or the local ``def`` ``scope`` binds
    the name to (``Call._closure_definition``); None otherwise.  A unit whose
    resolution of the call raises ``SugarNotWritten`` raises it here."""
    from .binding_state import unwrap_binding_state
    from .nodes import AsyncFunctionDef, Call, FunctionDef, Name

    if not isinstance(call, Call) or not isinstance(call.func, Name):
        return None
    definition = call.unit.source_function_definition_for_call(call)
    if definition is not None:
        return definition
    bound = scope.get(call.func.id)
    if bound is None:
        return None
    bound = unwrap_binding_state(bound)
    if type(bound) in (FunctionDef, AsyncFunctionDef) and not bound.decorators:
        return bound
    return None


def _callee_reach(call, scope):
    """``_Reach`` for a call to a source function named at the call, or None.

    ``module``: each module object the callee reaches by name -- a global it
    reads, or one a source function it calls by name reads, through every
    such call -- that ``scope`` (the caller's) binds a mutable read of
    (``_module_objects_named``).  ``cells``: the caller's read of each
    closure cell it reads or declares ``nonlocal``, and of each one a source
    function it calls by name reads; the binding the call carries for it
    (``Call._closure_cells``), else the binding ``scope`` holds.  A callee
    changing one changes the caller's object, on its completed and its
    halted arm alike."""
    definition = _source_callee(call, scope)
    if definition is None:
        return None
    functions, frees, closed = _closure(definition)
    carried = dict(getattr(call, "closure_cells", None) or ())
    cells = []
    named = set()
    for reader, name, nonlocal_ in frees:
        if name in named:
            continue
        named.add(name)
        node = carried.get(name) if reader is definition else None
        if node is None and name in scope:
            node = _read_of(scope[name])
        if node is None or getattr(node, "kind", None) == "Name":
            continue
        if not nonlocal_ and not _may_be_changed(node):
            continue
        cells.append(_Cell(name, node, nonlocal_, reader is definition))
    return _Reach(
        definition, _module_objects_named(call, scope, functions), cells, closed
    )


def _module_objects_named(call, scope, functions):
    """``[(name, node)]``: the module objects ``functions`` (``_closure``'s)
    read as globals (``_module_reads``) that ``scope`` (the caller's) binds a
    mutable read of: ``node`` is the caller's read of it, ``name`` the name
    a function reaching it reads it by.

    Empty when the caller holds no module object a call may change
    (``_may_be_changed``).  A module body's own threading
    (``_MODULE_STATEMENT_STATES``) asks no callee's module bindings: they
    are read off that threading."""
    from .nodes import _MODULE_STATEMENT_STATES

    if scope.get(_MODULE_STATEMENT_STATES) is not None:
        return []
    held = _held_module_objects(scope, call.unit)
    if not held:
        return []
    found = []
    taken = set()
    for owner, name, reference in _module_reads(functions):
        for held_name, node in held:
            if _ref(node) in taken:
                continue
            if not (
                same_object(node, reference)
                or (
                    # An object the caller's threading left an unknown of
                    # (no prior to name it by) is the one its module name
                    # binds, where caller and reader share the module.
                    held_name == name
                    and owner.unit is call.unit
                    and _unnamed_unknown(node)
                )
            ):
                continue
            taken.add(_ref(node))
            found.append((name, node))
    return found


def _unnamed_unknown(node) -> bool:
    """An unknown minted at a call with no prior read to name the object by
    (``_havoc`` with no conditions)."""
    node = _identity(node)
    return (
        getattr(node, "kind", None) == "ReceiverAfterCall"
        and getattr(node, "prior", None) is None
    )


def _held_module_objects(scope, unit):
    """``[(name, read)]``: the caller's reads of the module objects ``scope``
    binds by their module names (``SourceUnit.module_threaded_names``) that a
    call may change (``_may_be_changed``)."""
    threaded = unit.module_threaded_names()
    held = []
    for name, value in scope.items():
        if not isinstance(name, str) or name not in threaded:
            continue
        node = _read_of(value)
        if node is not None and _may_be_changed(node):
            held.append((name, node))
    return held


def _module_reads(functions):
    """``[(reader, name, reference)]``: the module binding of each global
    each of ``functions`` reads where it is called
    (``FunctionDef._module_global_references``); ``reader`` the function
    that reads it.  A function whose module read the module body does not
    decide raises its ``SugarNotWritten`` here."""
    found = []
    for current in functions:
        references = current._module_global_references()
        found.extend((current, name, references[name]) for name in sorted(references))
    return found


@functools.lru_cache(maxsize=4096)
def _closure(definition):
    """``(functions, frees, closed)`` over ``definition`` and every source
    function it calls by name, through every such call (``_source_callee``):

    - ``functions``: each of them, ``definition`` first;
    - ``frees``: ``(reader, name, nonlocal)`` for each enclosing function's
      local one of them reads or declares ``nonlocal`` (``_free_names``);
    - ``closed``: every other operation any of them runs (``_sites_at``) --
      a method, a callable value, an import, a class, a builtin, an
      f-string's ``format``, an operator, a truth test, an item or
      attribute access, an iteration, an ``await``, a ``yield`` -- runs no code
      (``_runs_no_code``), so they reach nothing their bodies do not name.

    Read off the source alone (CPython's symtable, the unit's lexical call
    rows), once per definition."""
    from .nodes import FunctionDef

    functions, frees = [], []
    closed = True
    seen = set()
    pending = [definition]
    while pending:
        current = pending.pop(0)
        if id(current) in seen:
            continue
        seen.add(id(current))
        if not isinstance(current, FunctionDef):
            continue
        functions.append(current)
        frees.extend(
            (current, name, nonlocal_) for name, nonlocal_ in _free_names(current)
        )
        for inner in _body_calls(current):
            callee = _source_callee(inner, {})
            if callee is not None:
                if id(callee) not in seen:
                    pending.append(callee)
            elif not _runs_no_code(inner):
                closed = False
    return tuple(functions), tuple(frees), closed


def _free_names(definition):
    """``[(name, nonlocal)]``: each enclosing function's local
    ``definition``'s body reads, or declares ``nonlocal`` (CPython's free
    variables).  ``__class__`` (the cell a class body gives a method that
    uses ``super()``) is the class's, not a function's local."""
    table = definition.unit.function_symtable(
        definition.name, definition.line_col_span().start_line
    )
    return [
        (symbol.get_name(), symbol.is_nonlocal())
        for symbol in table.get_symbols()
        if (symbol.is_free() or symbol.is_nonlocal())
        and symbol.get_name() != "__class__"
    ]


def _body_calls(definition):
    """The operations ``definition``'s body runs that may run code
    (``_sites_at``: its calls, f-string fields, operators, truth tests, item
    and attribute accesses, iterations, awaits, yields), not inside a nested
    ``def``, ``class`` or ``lambda`` (which run when called)."""
    from .nodes import AsyncFunctionDef, ClassDef, FunctionDef, Lambda, Node

    stack = list(definition.body)
    while stack:
        current = stack.pop()
        if isinstance(current, (Lambda, FunctionDef, AsyncFunctionDef, ClassDef)):
            continue
        yield from _sites_at(current)
        for _name, _index, child in current._child_edges():
            if isinstance(child, Node):
                stack.append(child)


def _runs_no_code(call) -> bool:
    """An operation in a source body that runs no code: a cited pure builtin
    (by its binding) over constants or a method of a literal
    (``_is_pure_call``); a construction of a builtin exception class by
    BaseException's law (``_constructs_builtin_exception``); any other
    operation over values that are builtin all the way down
    (``_code_subjects``)."""
    from .nodes import Call

    if isinstance(call, Call):
        return _is_pure_call(call, {}) or _constructs_builtin_exception(call)
    return _code_subjects(call, {}) == []


def _constructs_builtin_exception(call) -> bool:
    """Whether the call ``call`` constructs a builtin exception class and so
    runs no code, whatever its actuals are.

    The callee is decided by its binding, never its spelling: the builtin
    namespace member a bare name falls through to, or an import of
    ``builtins`` binds (``SourceUnit.name_reference_at``, the one lookup
    ``_builtin_callee`` and the lifter's cited fold read,
    ``CallSiteSugar._builtin_reference``,
    ``builtin_exception_cited_fold``).  A user class, a subclass, a
    parameter or any rebinding spelled ``ValueError`` reaches none.

    The construction is cited as depending only on how many actuals it is
    handed, never on what they are
    (``builtin_exception_construction_reads_values`` False:
    ``BaseException_new`` stores them as ``args``, CPython
    Objects/exceptions.c), with no keyword actual or only keywords its
    constructor rejects with ``TypeError`` before reading any
    (``builtin_exception_constructor_rejects_keywords``).  The constructors
    that read their actuals -- ``OSError``'s errno subclass selection,
    ``SyntaxError``'s details tuple, the ``Unicode*Error`` signatures, the
    exception groups -- are not this.  A starred or ``**`` actual iterates
    a value, which may run code: not this either.  What each actual's own
    evaluation runs is its own operation (``_sites_at``)."""
    from sugar_lift_py_tests.temporal.builtin_name_bindings import (
        builtin_exception_construction_reads_values,
        builtin_exception_constructor_rejects_keywords,
    )

    from .nodes import Name, Starred

    func = call.func
    if not isinstance(func, Name):
        return False
    if any(isinstance(arg, Starred) for arg in call.args):
        return False
    if any(keyword.arg is None for keyword in call.keywords):
        return False
    target = call.unit.name_reference_at(func.id, func.line_col_span())
    prefix = "python:builtins."
    if target is None or not target.startswith(prefix):
        return False
    name = target[len(prefix) :]
    if call.keywords and not builtin_exception_constructor_rejects_keywords(name):
        return False
    return not builtin_exception_construction_reads_values(name, len(call.args))


def _unfollowed_reach(call, scope, reach, followed):
    """``_rebind``'s targets for what a followed source helper (``reach``)
    may change of what its caller holds and does not follow (``followed``:
    the object keys it follows): a cell only a source function it calls by
    name reads; and, unless every call in it is one it follows or runs no
    code (``_Reach.closed``), every module object and closure cell the
    caller holds (``_ambient_objects``).  A cell a nested scope declares
    ``nonlocal`` may be rebound, whatever it holds."""
    targets = []
    for cell in reach.cells:
        if cell.direct or _object_key(cell.node) in followed:
            continue
        targets.append((cell.node, None if cell.nonlocal_ else _OPERAND_RULES, None))
    if not reach.closed:
        objects, rebound = _ambient_objects(call, scope)
        targets.extend(
            (node, _OPERAND_RULES, None)
            for node in objects
            if _object_key(node) not in followed
        )
        targets.extend(
            (node, None, None) for node in rebound if _object_key(node) not in followed
        )
    return targets


def _ambient_targets(statement, call, scope, ambient=None):
    """``_rebind``'s targets for what ``call`` -- an operation the caller
    does not follow (``_sites_at``) -- may change of what the caller holds
    beyond its operands: the module objects and the closure cells the code
    it runs can reach (``ambient``, ``_ambient_objects`` at ``statement``).
    One rule for every operation that may run code.

    - A source function named at the call reaches what its body, and the
      source functions it calls by name, name (``_callee_reach``) when every
      other operation in them runs no code (``_Reach.closed``); otherwise
      every module object and cell the caller holds.  Each is exposed as an
      operand handed to it is (``_OPERAND_RULES``).
    - Any other operation -- a method on any receiver, a callable value (a
      bound function, a lambda, a class), an import, a builtin, an
      f-string's ``format``, the one door's operation, an operator, a
      comparison, a truth test, an item or attribute access, an iteration,
      an ``await``, a ``yield`` (its consumer's code) -- reaches every one,
      when it runs code at all: whether
      it does is decided at reduce by the values of the reads it runs on
      (``_code_subjects``: a builtin value runs none; a source object or an
      undecided value may); where no read decides it, each is exposed as an
      operand is.

    A cell a nested scope declares ``nonlocal`` may be rebound by such code
    whatever it holds: it is unknown after the call.  ``ambient`` (no
    arguments) answers what the caller holds, once per statement.

    An operation handed the frame's own namespace reaches every name of the
    frame as well (``_frame_targets``), whether or not it runs code: a
    builtin container's own method on a ``locals()`` mapping's member
    changes the local's object as much as code ``exec`` runs does."""
    from .nodes import Call

    frame = _frame_targets(statement, call, scope)
    subjects = reach = None
    if not isinstance(call, Call):
        # An operation no source function is named at: its operands' values
        # decide, asked first (most run over builtin values, and reach
        # nothing).
        subjects = _code_subjects(call, scope)
        if subjects is not None and not subjects:
            return frame
    objects, rebound = (
        _ambient_objects(statement, scope) if ambient is None else ambient()
    )
    if not objects and not rebound:
        return frame
    if isinstance(call, Call):
        reach = _callee_reach(call, scope)
    if reach is not None and reach.closed:
        objects = [node for _name, node in reach.module]
        objects.extend(cell.node for cell in reach.cells if not cell.nonlocal_)
        rebound = [cell.node for cell in reach.cells if cell.nonlocal_]
        subjects = None
    elif isinstance(call, Call):
        subjects = None if reach is not None else _code_subjects(call, scope)
    if subjects is not None and not subjects:
        # It runs no code: nothing beyond its operands (and the frame's
        # namespace it is handed) is reached.
        return frame
    if subjects is None:
        targets = [(node, _OPERAND_RULES, None) for node in objects]
    else:
        targets = [
            (node, rules, subject) for node in objects for subject, rules in subjects
        ]
    targets.extend((node, None, None) for node in rebound)
    targets.extend(frame)
    return targets


def _frame_targets(statement, call, scope):
    """``_rebind``'s targets for what ``call`` may change through the
    namespace of the frame ``statement`` runs in, when it is handed that
    namespace (``_reaches_the_frame``): ``exec``/``eval`` with no globals
    mapping run their code in it, and a ``locals()``/``vars()`` mapping of it
    holds every object its names are bound to.

    The interpreter rule followed is CPython 3.13's (PEP 667), the one
    every CPython 3 frame without a trace function keeps: in a function (an
    optimized frame: a ``def``, a lambda) ``locals()`` is a snapshot dict of
    the frame, and ``exec``/``eval`` read and write that snapshot -- never
    the frame's fast locals or cells.  So no name of the frame is rebound,
    and every object one is bound to is reachable: each is exposed as an
    operand is (``_OPERAND_RULES``: a builtin container's contents are
    unknown after the call, an ``int`` keeps its value; a cited pure builtin
    handed the mapping leaves a value builtin all the way down unchanged, as
    ``_call_targets`` says of its operands).  At module or class scope the
    namespace is the mapping itself: every name it binds may be rebound,
    unknown after the call whatever it held.  Names are read off CPython's
    symtable of that frame (``_frame_names``), never spelled."""
    from .nodes import Call

    if not _reaches_the_frame(statement, call):
        return []
    names, optimized = _frame_names(statement)
    rules = _OPERAND_RULES
    if isinstance(call, Call) and _builtin_callee(call) in _cited().pure:
        rules = (("", True, False),)
    targets = []
    for name in sorted(names):
        if name not in scope:
            continue
        node = _read_of(scope[name])
        if node is None or getattr(node, "kind", None) == "Name":
            continue
        if not optimized:
            targets.append((node, None, None))
        elif _may_be_changed(node):
            targets.append((node, rules, None))
    return targets


def _reaches_the_frame(statement, call) -> bool:
    """Whether the operation ``call`` (``_sites_at``) in ``statement`` is
    handed the namespace of the frame it runs in: a call of a builtin the
    law cites as running code there (``_cited().frame_code``: ``exec``,
    ``eval``, by binding) that names no globals mapping
    (``_runs_in_the_frame``), or an operand that is or holds a bare call of
    one cited as returning a mapping of it (``_cited().frame_mapping``:
    ``locals()``, ``vars()``) made in this same frame.

    A unit no read of which reaches any of them (``SourceUnit.
    _module_reaches_dynamic_global_writer``, by binding) answers at once."""
    from .nodes import Call, Node, PathContainerCall

    unit = statement.unit
    if not unit._module_reaches_dynamic_global_writer():
        return False
    cited = _cited()
    if isinstance(call, Call):
        if _builtin_callee(call) in cited.frame_code and _runs_in_the_frame(call):
            return True
        operands = (
            call.func,
            *call.args,
            *(keyword.value for keyword in call.keywords),
        )
    elif isinstance(call, PathContainerCall):
        operands = (call.receiver, *call.args)
    elif call.kind == "FormattedValue":
        operands = (call.value,)
    else:
        operands = _site_operands(call)
    frame = None
    for operand in operands:
        if not isinstance(operand, Node):
            continue
        for node in _walk_values(operand, kept_only=False):
            if not (
                isinstance(node, Call)
                and not node.args
                and not node.keywords
                and node.unit is unit
                and _builtin_callee(node) in cited.frame_mapping
            ):
                continue
            if frame is None:
                frame = (unit.scope_holding(statement.line_col_span()),)
            if unit.scope_holding(node.line_col_span()) is frame[0]:
                return True
    return False


def _runs_in_the_frame(call) -> bool:
    """Whether an ``exec``/``eval`` ``call`` runs its code in the calling
    frame's namespaces: its ``globals`` operand (the second, or the keyword)
    is absent or None, and then its ``locals`` is the frame's too (CPython's
    ``builtin_exec_impl``).  Only a dict display or comprehension is decided
    not to be None; any other operand, or a starred one, may be."""
    from .nodes import Starred

    if any(isinstance(arg, Starred) for arg in call.args) or any(
        keyword.arg is None for keyword in call.keywords
    ):
        return True
    if len(call.args) > 1:
        given = call.args[1]
    else:
        given = next(
            (keyword.value for keyword in call.keywords if keyword.arg == "globals"),
            None,
        )
    return given is None or getattr(_identity(given), "kind", None) not in (
        "Dict",
        "DictComp",
    )


def _frame_names(statement):
    """``(names, optimized)``: the names the frame ``statement`` runs in
    binds -- its locals, parameters and cells, CPython's symtable
    ``is_local`` -- and whether it is a function's (``scope_holding``: a
    ``def`` or a lambda body).  A module's or a class body's namespace is
    the mapping ``exec`` and ``locals()`` hand out, not an optimized frame."""
    from .nodes import ClassDef

    unit = statement.unit
    owner = unit.scope_holding(statement.line_col_span())
    if owner is None:
        tables, optimized = (unit.module_symtable,), False
    elif isinstance(owner, ClassDef):
        tables = (
            unit.class_symtable(owner.name, owner.line_col_span().start_line),
        )
        optimized = False
    else:
        tables, optimized = unit._frame_symtables(owner), True
    names = set()
    for table in tables:
        names.update(
            symbol.get_name() for symbol in table.get_symbols() if symbol.is_local()
        )
    return frozenset(names), optimized


# A read's value runs code an operation makes on it when no container law
# decides it (a source object, a function, a module, an unknown), or it is a
# container whose members are not builtin all the way down (their dunders:
# a builtin container's own method reaches its members' ``__eq__``,
# ``__hash__``, ``__del__``, ...).
_RUNS_CODE = (("", True, False), ("", False, True))


class _Operated(NamedTuple):
    """A value a statement or a comprehension clause runs dunders of: a
    ``for`` iterable (``__iter__``, then ``__next__`` before every item), an
    ``if``/``while``/``assert`` test or a clause's condition (``__bool__``,
    ``__len__``), a ``match`` subject (``__eq__``, ``__match_args__``, ...)."""

    node: object
    kind: str = "Operated"


class _FieldStore(NamedTuple):
    """The one field store ``<receiver>.<attr> = <value>`` a statement makes
    (``nodes.ReceiverFieldStoreStatement``): ``type(receiver).__setattr__``,
    which runs code when the receiver's class binds a ``__setattr__`` of its
    own or a data descriptor for ``attr``, and may when its class lookup
    does not decide.  The receiver's value decides it at reduce
    (``_field_store_rules``)."""

    receiver: object
    value: object
    attr: str
    kind: str = "FieldStore"


def _field_store_rules(site, *, operand=False):
    """``(rules, subject)`` for what the code the field store ``site`` runs
    may change (``_rebind``): the receiver's read decides at reduce whether
    the store runs code at all (``_may_change`` under ``field_store_method``,
    ``sharer``: a plain store reaches nothing beyond the object).
    ``operand``: the object is one the stored value hands that code, changed
    as an operand handed to a call is.  Where no read of the receiver
    decides it (``_reads_again``), the operand rule (``_OPERAND_RULES``), no
    subject."""
    if _reads_again(site.receiver):
        method = field_store_method(site.attr, operand=operand)
        return ((method, False, True),), site.receiver
    return _OPERAND_RULES, None


# Expressions whose own evaluation runs a dunder of its operands' values:
# ``a + b``, ``-a``, ``a and b`` (``__bool__``), ``x if t else y``
# (``__bool__``), ``a == b``/``x in y`` (``__eq__``, ``__contains__``),
# ``a[k]`` (``__getitem__``/``__setitem__``/``__delitem__``), ``o.x`` (a
# property, a descriptor, ``__getattr__``, ``__setattr__``), ``await a``
# (the awaitable's code), and a suspension (``_SUSPENSION_KINDS``).
_OPERATION_KINDS = frozenset(
    {
        "BinOp",
        "UnaryOp",
        "BoolOp",
        "IfExp",
        "Compare",
        "Subscript",
        "Attribute",
        "Await",
        "Yield",
        "YieldFrom",
    }
)
# ``yield v`` / ``yield from it``: the frame suspends and its consumer runs
# code of its own -- any code, holding the yielded value -- before the frame
# resumes.  No operand's value decides what that code is (``_code_subjects``
# answers None), and the yielded value is handed to it as an operand is
# (``_call_targets``): the generator's frame, at the yield, is exposed as a
# caller is at an unfollowed call.  The frame's own writes are released at
# the same yield by the machine (``generator_construction.YieldEffect``).
_SUSPENSION_KINDS = frozenset({"Yield", "YieldFrom"})
# Comparisons that run no dunder; and those whose value is a ``bool`` whatever
# a dunder returns.
_IDENTITY_OPS = frozenset({"Is", "IsNot"})
_BOOL_OPS = frozenset({"Is", "IsNot", "In", "NotIn"})


def _sites_at(node, headers=()):
    """The operations ``node``'s own evaluation runs that may run code: a
    call, an f-string field (it runs ``format``), an operation
    (``_OPERATION_KINDS``, a ``yield``/``yield from`` included: the
    consumer runs before the frame resumes) but an attribute read of an
    import's member (a
    module binding, read by its receipt: ``Attribute._construct_sugar``),
    and each value a statement or a comprehension clause operates on
    (``_Operated``).  ``headers``: the handles of a header its statement
    already threaded with its operation (``thread_header``), not counted
    again -- but a ``for`` iterable, whose ``__next__`` runs before every
    item."""
    from .nodes import (
        Assert,
        AsyncFor,
        Call,
        Comprehension,
        For,
        If,
        While,
    )

    if isinstance(node, Call) or node.kind == "FormattedValue":
        yield node
    elif node.kind in _OPERATION_KINDS and not _import_member(node):
        yield node
    if isinstance(node, (For, AsyncFor)):
        yield _Operated(node.iter)
    elif isinstance(node, (If, While)) or node.kind == "Match":
        tested = node.subject if node.kind == "Match" else node.test
        if not any(_handle(tested) is header for header in headers):
            yield _Operated(tested)
    elif isinstance(node, Assert):
        yield _Operated(node.test)
    elif isinstance(node, Comprehension):
        yield _Operated(node.iter)
        for condition in node.ifs:
            yield _Operated(condition)
    elif node.kind == "ReceiverFieldStoreStatement":
        # The one field store is ``type(receiver).__setattr__``: an
        # operation that may run code, as an item store is.
        state = node.post_state
        yield _FieldStore(state.receiver, node.value, state.attr)


def _import_member(node) -> bool:
    """``node`` is an attribute read the unit's import receipt names a
    module's member (``import_value_use_receipt``): a module binding read
    by name, which runs nothing.  Only a dotted read of a name can be one;
    a unit whose receipt read raises ``SugarNotWritten`` raises it here."""
    if node.kind != "Attribute":
        return False
    root = node.value
    while getattr(root, "kind", None) == "Attribute":
        root = root.value
    if getattr(root, "kind", None) != "Name":
        return False
    from sugar_lift_py_tests.import_binding import AuthenticatedImportUseV1

    span = node.line_col_span()
    receipt = node.unit.import_value_use_receipt(
        (span.start_line, span.start_col, span.end_line, span.end_col)
    )
    return type(receipt) is AuthenticatedImportUseV1


def _site_operands(site):
    """The operands whose values' dunders the operation ``site`` runs
    (``_sites_at``)."""
    kind = site.kind
    if kind == "Operated":
        return (site.node,)
    if kind == "FieldStore":
        return (site.receiver, site.value)
    if kind == "BinOp":
        return (site.left, site.right)
    if kind == "UnaryOp":
        return (site.operand,)
    if kind == "BoolOp":
        return tuple(site.values)
    if kind == "IfExp":
        return (site.test,)
    if kind == "Compare":
        return _compared(site, _IDENTITY_OPS)
    if kind == "Subscript":
        return (site.value, site.slice_)
    if kind in ("Attribute", "Await", *_SUSPENSION_KINDS):
        return () if site.value is None else (site.value,)
    return ()


def _compared(node, skipped):
    """The operands of the comparison ``node`` some operator not in
    ``skipped`` compares, each once."""
    operands = (node.left, *node.comparators)
    found = []
    for index, op in enumerate(node.ops):
        if op.kind in skipped:
            continue
        for operand in operands[index : index + 2]:
            if not any(operand is known for known in found):
                found.append(operand)
    return tuple(found)


def _result_operands(node):
    """The operands whose values decide whether ``node``'s value is builtin
    all the way down -- it is when theirs are (a builtin's dunder returns a
    builtin, a builtin's member is one, a display of builtins is one, a
    cited pure builtin over builtins gives one: ``range(n)``) -- or None when
    no operand does (any other call's result, a lambda, an import)."""
    from .nodes import Call, Dict, List, Set, Slice, Tuple_

    kind = getattr(node, "kind", None)
    if isinstance(node, Call):
        if node.keywords or _builtin_callee(node) not in _cited().pure:
            return None
        return tuple(node.args)
    if kind == "BinOp":
        return (node.left, node.right)
    if kind == "UnaryOp":
        return (node.operand,)
    if kind == "BoolOp":
        return tuple(node.values)
    if kind == "IfExp":
        return (node.body, node.orelse)
    if kind == "Compare":
        return _compared(node, _BOOL_OPS)
    if kind == "Subscript":
        return (node.value, node.slice_)
    if kind == "Attribute":
        return (node.value,)
    if isinstance(node, (List, Tuple_, Set)):
        return tuple(node.elts)
    if isinstance(node, Dict):
        return (*(key for key in node.keys if key is not None), *node.values)
    if isinstance(node, Slice):
        return tuple(
            part for part in (node.lower, node.upper, node.step) if part is not None
        )
    return None


def _operand_subjects(node, scope, depth=0):
    """``[(read, _RUNS_CODE)]``: the reads whose values decide, at reduce,
    whether ``node``'s value is builtin all the way down: ``[]`` when it is
    decided one (``builtin_typed``), the read itself when it is one, the
    reads of the operands that decide it (``_result_operands``); None when
    nothing decides it."""
    from .nodes import Starred

    if isinstance(node, Starred):
        node = node.value
    if builtin_typed(node, scope):
        return []
    if getattr(node, "kind", None) in _READ_KINDS:
        return [(node, _RUNS_CODE)]
    parts = _result_operands(node)
    if parts is None or depth > 32:
        return None
    subjects = []
    for part in parts:
        found = _operand_subjects(part, scope, depth + 1)
        if found is None:
            return None
        subjects.extend(found)
    return subjects


def _code_subjects(call, scope):
    """``[(read, rules)]``: the reads whose values decide, at reduce, whether
    the operation ``call`` (``_sites_at``) runs code (``_RUNS_CODE``): the
    receiver of a method (the one door's operation included, whatever the
    method), a callable value, and every operand -- an operand that is a
    decided builtin all the way down (``builtin_typed``) runs none, and an
    operation's value is one when its operands are (``_operand_subjects``).
    ``[]``: it runs no code (a cited pure builtin over builtin operands,
    ``_is_pure_call``; a builtin exception class constructed by
    BaseException's law, ``_constructs_builtin_exception``; an operation
    over builtin values).  None: no read
    decides it -- a callee or an operand that is not a read (an import, a
    class, a source function by its name, a path, a call's result), a
    builtin the law does not cite as running only its operands' dunders
    (``_cited().pure``: ``exec``/``eval`` run the source they are handed,
    a constant string as much as any; ``import_module`` runs a module's
    body), or a suspension (``_SUSPENSION_KINDS``: the consumer's code) --
    so it may run any."""
    from .nodes import Attribute, Call, Name, PathContainerCall

    if call.kind in _SUSPENSION_KINDS:
        return None
    if call.kind == "FieldStore":
        # The one field store: a builtin receiver runs none (its floor
        # answers the store); any other receiver's value decides by its
        # class (``_field_store_rules``), and where no read of it decides,
        # it may run any.
        if builtin_typed(call.receiver, scope):
            return []
        rules, subject = _field_store_rules(call)
        return None if subject is None else [(subject, rules)]
    if call.kind == "FormattedValue":
        operands = (call.value,)
    elif isinstance(call, PathContainerCall):
        operands = (call.receiver, *call.args)
    elif isinstance(call, Call):
        if _is_pure_call(call, scope) or _constructs_builtin_exception(call):
            return []
        func = call.func
        rest = (*call.args, *(keyword.value for keyword in call.keywords))
        if isinstance(func, Attribute):
            heads = (func.value,)
        elif isinstance(func, Name):
            if _builtin_callee(call) not in _cited().pure:
                # No builtin, or one whose own code the law does not cite:
                # its operands' values do not decide what it runs.
                return None
            heads = ()
        elif getattr(func, "kind", None) in _READ_KINDS:
            heads = (func,)
        else:
            return None
        operands = (*heads, *rest)
    else:
        operands = _site_operands(call)
    subjects = []
    for operand in operands:
        found = _operand_subjects(operand, scope)
        if found is None:
            return None
        for read, rules in found:
            if not any(read is known for known, _rules in subjects):
                subjects.append((read, rules))
    return subjects


def _ambient_objects(site, scope):
    """``(objects, rebound)``: the reads of what the caller at ``site`` holds
    that code it does not follow may reach other than through an operand --
    the module objects ``scope`` binds (``_held_module_objects``; none while
    a module body threads itself, ``_MODULE_STATEMENT_STATES``) and the
    closure cells of the function ``site`` runs in (``_frame_cells``).
    ``objects``: those a call may change; ``rebound``: the cells a nested
    scope declares ``nonlocal``, which it may rebind."""
    from .nodes import _MODULE_STATEMENT_STATES

    objects = []
    if scope.get(_MODULE_STATEMENT_STATES) is None:
        objects.extend(node for _name, node in _held_module_objects(scope, site.unit))
    cells, rebound = _frame_cells(site, scope)
    objects.extend(cells)
    return objects, rebound


def _frame_cells(site, scope):
    """``(cells, rebound)``: ``scope``'s reads of the closure cells of the
    function ``site`` runs in -- each local of it a function, lambda or
    class nested in it reads, and each enclosing function's local it reads
    itself (CPython's free variables, ``_cell_names``).  ``cells``: those a
    call may change (``_may_be_changed``); ``rebound``: those a scope
    declares ``nonlocal``, whatever they hold.  None outside a function."""
    from .nodes import AsyncFunctionDef, FunctionDef

    unit = site.unit
    owner = unit.innermost_function_containing(site.line_col_span())
    if not isinstance(owner, (FunctionDef, AsyncFunctionDef)):
        return [], []
    captured, declared = _cell_names(
        unit.function_symtable(owner.name, owner.line_col_span().start_line)
    )
    cells, rebound = [], []
    for name in sorted(captured | declared):
        if name not in scope:
            continue
        node = _read_of(scope[name])
        if node is None or getattr(node, "kind", None) == "Name":
            continue
        if name in declared:
            rebound.append(node)
        elif _may_be_changed(node):
            cells.append(node)
    return cells, rebound


@functools.lru_cache(maxsize=4096)
def _cell_names(table):
    """``(captured, declared)`` of a function's CPython symtable: the names
    of its own variables a nested scope reads (its locals some nested
    scope's free variable names) and those it reads from an enclosing
    function; ``declared`` those it or a nested scope declares
    ``nonlocal``.  ``__class__`` is a class's cell, not a function's."""
    symbols = table.get_symbols()
    own = {
        symbol.get_name()
        for symbol in symbols
        if symbol.is_local() or symbol.is_free() or symbol.is_nonlocal()
    }
    captured = {symbol.get_name() for symbol in symbols if symbol.is_free()}
    declared = {symbol.get_name() for symbol in symbols if symbol.is_nonlocal()}
    stack = list(table.get_children())
    while stack:
        child = stack.pop()
        stack.extend(child.get_children())
        for symbol in child.get_symbols():
            if symbol.is_nonlocal():
                declared.add(symbol.get_name())
            elif symbol.is_free():
                captured.add(symbol.get_name())
    declared = (declared & own) - {"__class__"}
    captured = (captured & own) - declared - {"__class__"}
    return frozenset(captured), frozenset(declared)


def _handle(node):
    return getattr(node, "ref", node)


def _evaluation_order(node):
    """``node``'s child edges in the order Python evaluates them: an
    assignment's value first, every other node its grammar order."""
    edges = node._child_edges()
    if getattr(node, "kind", None) in ("Assign", "AnnAssign"):
        return (
            *(edge for edge in edges if edge[0] == "value"),
            *(edge for edge in edges if edge[0] != "value"),
        )
    return edges


def _path_to(statement, call):
    """``[(node, position)]`` from ``statement`` down to ``call``: each node
    on the way and the position (``_evaluation_order``) of the child that
    holds ``call``; None when ``call`` is not evaluated in ``statement``."""
    from .nodes import AsyncFunctionDef, ClassDef, FunctionDef, Lambda, Node

    target = _handle(call)
    stack = [(statement, ())]
    while stack:
        node, path = stack.pop()
        if node is call or _handle(node) is target:
            return list(path)
        if node is not statement and (
            isinstance(node, (Lambda, FunctionDef, AsyncFunctionDef, ClassDef))
            or getattr(node, "kind", None) in _READ_KINDS
        ):
            continue
        for position, (_name, _index, child) in enumerate(_evaluation_order(node)):
            if isinstance(child, Node):
                stack.append((child, (*path, (node, position))))
    return None


def exit_read_keys(read) -> tuple:
    """The evaluation keys ``read`` reads through: a callee frame's read of
    an object it shares with its caller where its body ends
    (``nodes._exit_reads``), walked down the object's states -- each
    one-door mutation's pair (``PathAfterCall``), each value a source helper
    it called carried (``SourceCallActualAfter``), each field store
    (``ReceiverFieldStoreState``), the object a call may have changed
    (``ReceiverAfterCall``), to the binding it began from (a key reference's
    own key; a formal's or cell's coordinate is none).

    A halt's record holds a statement's key exactly when the statement
    completed before the halt, so the read is the object's state at the
    halt only where the record holds every one of them
    (``SourceVisibleFunctionBodySugar``); elsewhere what the callee left of
    the object there is undecided."""
    from .nodes import PathContainerCall

    keys = []
    node = read
    for _ in range(64):
        kind = getattr(node, "kind", None)
        evaluation = getattr(node, "evaluation", None)
        if isinstance(evaluation, str) and kind in (
            "PathAfterCall",
            "SourceCallActualAfter",
            "ReceiverFieldStoreState",
            "EvaluationRef",
        ):
            keys.append(evaluation)
        if (
            kind == "PathAfterCall"
            and getattr(node, "mode", None) == "root"
            and not getattr(node, "steps", ())
            and isinstance(getattr(node, "call", None), PathContainerCall)
        ):
            node = node.call.receiver
        elif kind == "SourceCallActualAfter":
            node = node.prior
        elif kind == "ReceiverFieldStoreState":
            node = node.receiver
        elif kind == "ReceiverAfterCall" and getattr(node, "prior", None) is not None:
            node = node.prior
        else:
            break
    return tuple(keys)


def _actual_after(site_node, call, label, prior, tags):
    """An object the followed ``call`` shares with its caller, read after
    the call: the value the call carried out of the callee's frame for
    ``label`` (``call_site_value.caller_visible_values``), under the call's
    key (``nodes.carried_evaluation``).  ``prior`` is the caller's read of
    the object before the call: which object it is, and what a halt read
    before the call ran finds (``at_halt_read``)."""
    from sugar_lift_py_tests.temporal.temporal_context import projection_key

    from .nodes import carried_evaluation

    return _caller_visible_read(
        site_node,
        projection_key(carried_evaluation(call), label),
        label,
        _evaluation(site_node, tags),
        prior,
        tags,
    )


def at_halt_read(site_node, read, tags):
    """``read`` (an ``_actual_after``) as a halt inside the statement that
    holds the call reads it (``Try._mid_statement_state``): the value the
    call carried where the halt's record holds its key -- the call ran and
    left on that arm, completed or halted -- else the object as the
    statement found it (``prior``): nothing of the call ran before that
    halt."""
    return _caller_visible_read(
        site_node,
        read.evaluation,
        read.label,
        read.occurrence,
        read.prior,
        tags,
        at_halt=True,
    )


def _caller_visible_read(
    site_node, evaluation, label, occurrence, prior, tags, *, at_halt=False
):
    """The one ``SourceCallActualAfter`` node: a read of the value a call
    carried under ``evaluation``."""
    from .backend import Child, Leaf
    from .shadow import _handle_of

    fields = (
        ("evaluation", Leaf(evaluation)),
        ("label", Leaf(label)),
        ("occurrence", Leaf(occurrence)),
        ("prior", Child(_handle_of(prior))),
    )
    if at_halt:
        fields = (*fields, ("at_halt", Leaf(True)))
    return _materialize(site_node, "SourceCallActualAfter", fields, tags)


def _apply_actual_states(statement, pre_scope, scope, havocked, applied):
    """Rebind every name bound to an object a followed helper changed to the
    value its call carried for it (``_actual_after``); a name the havoc
    already rebound, or the statement itself bound, keeps that binding. A
    name that merely contains the object is unknown.  A cell the helper
    rebinds (``name``) is that name alone: the object it held is not
    changed, and every other name keeps it."""
    from .shadow import occurrence_tags_of

    tags = occurrence_tags_of(statement)
    binding = {}
    havoc_names = []
    for actual, call, label, cell in applied:
        if cell is not None:
            if cell in binding or cell in havoc_names:
                # Two calls of the statement wrote it: which wrote last is
                # not followed here.
                binding.pop(cell, None)
                if cell not in havoc_names:
                    havoc_names.append(cell)
            elif _untouched(cell, pre_scope, scope, havocked):
                binding[cell] = _actual_after(statement, call, label, actual, tags)
            continue
        exact, containing = aliases(scope, actual)
        after = None
        for name in exact:
            if name in binding:
                if binding[name] is not after and name not in havoc_names:
                    # Two calls of the statement changed the object: which
                    # left it last is not followed here.
                    havoc_names.append(name)
                continue
            if not _untouched(name, pre_scope, scope, havocked):
                continue
            if after is None:
                after = _actual_after(statement, call, label, actual, tags)
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
