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
  a builtin value runs none) and the value is one a call may change; a
  cell a nested scope declares ``nonlocal`` is unknown whatever it holds.
  A source function that is followed carries what it did to each one it
  names, as it does to its actuals, and the binding it wrote to each cell
  it declares ``nonlocal`` (``source_helper_actual_states``).

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
            # An object after a source helper's stores (``_actual_after``):
            # the state its one-door mutations left, of the same object.
            node = _identity(node.state)
        else:
            break
        seen += 1
    return node


def _ref(node):
    """The object a node denotes: its backend handle, or the coordinate its
    construction authenticated.

    A read of a formal is re-spanned to its use site (``Name.substitute``), so
    every read is a fresh node over the same ``coordinate``.  Every version
    of an object place (each field store mints one) is the one object its
    construction made (``object_identity_cid``); the receiver an active
    ``__init__`` constructs is its binding coordinate.  A read of an
    assigned name is the object its assignment was given (``_identity``);
    a name's object after a mutation is the object before it (``_object``)."""
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
    member = None if isinstance(target, Name) else _member_object(target)
    for node in _walk_values(state):
        if isinstance(target, Name):
            if isinstance(node, Name) and node.id == target.id:
                return True
        elif same_object(node, target) or (
            member is not None and same_object(node, member)
        ):
            return True
        if _read_may_hold(node, target, depth):
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
    statement, names, states, evaluated, tags, evaluation=None, rebinds=None, pairs=()
):
    """The shadow statement; with ``evaluation`` it binds its call's pair
    (``evaluated[0]``) under that key, which its projections read.  ``pairs``
    are ``(key, index)``: a later operation's pair ``evaluated[index]`` the
    statement binds under ``key`` (``d.setdefault(k, v).append(x)``: the
    append's, after the setdefault's).

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
        return _rebind(statement, pre_scope, scope, targets)
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
        helper = (
            None if loop else source_helper_actual_states(call, bound_refs, pre_scope)
        )
        if helper is not None:
            havoc_targets, states = helper
            targets.extend(havoc_targets)
            # A halt inside the helper leaves an object in the state the
            # helper holds at every halt only where nothing the statement
            # evaluates before the call can halt first (``_halts_before``):
            # one rule wherever the call sits.
            before = _halts_before(statement, call)
            applied.extend(
                (actual, state, label, holds and not before, name)
                for actual, state, label, holds, name in states
            )
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
    havocked = _rebind(statement, pre_scope, scope, targets)
    if not applied:
        return havocked
    return _apply_actual_states(statement, pre_scope, scope, havocked, applied)


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
    # reaches (``sharer``).  A receiver whose identity is undecided -- a
    # member of an opaque value (``a, b = g()``), an item the source does
    # not say (``r[i]``) -- may be any object the value it was read from
    # reaches: a name sharing one may hold it, never only share with it.
    graph = _graph(root)
    undecided = _undecided_member(root)
    for alias, value in scope.items():
        if not isinstance(alias, str) or alias in names or alias == target_name:
            continue
        state = _state(value)
        if not isinstance(state, Node):
            continue
        if getattr(state, "kind", None) in _NEVER_HAVOC_KINDS:
            continue
        shares = bool(graph) and bool(_graph(state) & graph)
        holds = alias in containing or (undecided and shares)
        if holds or shares:
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
    # The statement evaluates the call once and binds its pair under its own
    # key; the root after it, the object after it and the call's value read
    # that key, never the call (and its operands) evaluated again.
    if evaluation is None:
        evaluation = statement._evaluation_key(scope)
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
    if target_name is not None:
        names.append(target_name)
        states.append(_projection(site, path_call, 1, tags, evaluation))
    return _statement(
        statement,
        names,
        states,
        evaluated,
        tags,
        keys[0],
        pairs=tuple((key, index) for index, key in enumerate(keys) if index),
    )


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
# The objects followed are every one the helper reaches that its caller holds:
# its actuals, the module objects it (or a source function it calls by name)
# reads as globals, and the closure cells it reads or declares ``nonlocal``
# (``_callee_reach``). What it may reach and does not follow -- every other
# module object and cell of the caller, when some call in it runs code that is
# not a source function by name (``_Reach.closed``) -- takes the havoc, as
# every call that is not followed does (``_ambient_targets``).
#
# The call's own halts are its faces at the call (the Call producer); a halt
# path never reaches the statement's continuation. A handler that catches one
# reads the object in the state the helper holds at every halt inside it
# (``holds_at_halt``, ``Try._mid_statement_state``): the same state the
# completed path reads, when every statement of the body that may halt begins
# with the object already in it, or is the object's own one-door mutation
# (whose halt the state's re-read sees: it is then unknown), and nothing the
# caller's statement evaluates before the call may halt (``_halts_before``),
# wherever in the statement the call sits. Otherwise a halt carries the
# object unknown, never the pre-call contents.
# ---------------------------------------------------------------------------

_HELPER_STATEMENT_KINDS = frozenset(
    {
        "Expr",
        "Assign",
        "AnnAssign",
        "AugAssign",
        "Pass",
        "Raise",
        "Assert",
        # A declaration: the body's writes of the name are the enclosing
        # cell's, followed as the caller's binding (``_callee_reach``).
        "Nonlocal",
    }
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
        if getattr(node, "kind", None) == "SourceCallActualAfter":
            # A source helper the helper called left it there: the state its
            # own one-door mutations left (``_actual_after``).
            node = _identity(node.state)
            continue
        # The read the chain began from is the actual itself, never a value
        # some other call left of the same object (``ReceiverAfterCall``):
        # what that call did is not a mutation this projection states.
        return _same_read(node, actual)


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


def _mutated(state) -> bool:
    """Whether ``state`` is an object after a mutation through the one door
    (its value is not the object's value before), or after a source helper's
    such mutations (``SourceCallActualAfter``)."""
    node = _identity(state)
    kind = getattr(node, "kind", None)
    return kind == "SourceCallActualAfter" or (
        kind == "PathAfterCall" and node.mode == "root" and not node.steps
    )


def _closed_operand(node, *, kinds=_CLOSED_OPERAND_KINDS) -> bool:
    from .nodes import Node

    stack = [node]
    while stack:
        current = stack.pop()
        if getattr(current, "kind", None) not in kinds:
            return False
        for _name, _index, child in current._child_edges():
            if isinstance(child, Node):
                stack.append(child)
    return True


def source_helper_actual_states(call, bound_refs, scope):
    """``(havoc_targets, [(object, state, label, holds_at_halt, name)])`` for
    a call to a followable source helper, or None when the call is not one
    (it keeps its havoc, ``havoc_after``).  ``havoc_targets`` are
    ``_rebind``'s ``(object, rules, subject)``.  ``name``: the cell the
    helper declares ``nonlocal`` and rebinds, whose name alone takes
    ``state`` (the helper's write); None for an object every alias of which
    takes it.

    The objects the helper reaches that its caller holds are followed alike:
    every actual that is a bound object a call may change
    (``_may_be_changed``, the exposure candidates), whatever it was given,
    every module object the helper reaches (its globals and those of the
    source functions it calls) that ``scope``, the caller's, binds -- the
    helper's read of it is the caller's object -- and every closure cell it
    reads or declares ``nonlocal`` (``_callee_reach``).  What the helper's
    mutation of one does is the one door's, decided by the object's value at
    reduce (``PathContainerCallSugar``), never by the spelling of its
    binding.  A cell the helper declares ``nonlocal`` and rebinds (``n +=
    1``, ``n = v``) is the caller's binding: the caller's name reads the
    helper's write after the call (the key the write's statement binds when
    the call runs), as the helper's own later reads do; a rebinding no key
    names is unknown after it.  What it may reach and does not follow takes
    the havoc (``_unfollowed_reach``).

    ``holds_at_halt``: ``state`` is the object's state at every halt inside
    the call too (``_holds_at_every_halt``), so the one state stands on both
    the completed and the halted arm."""
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
    if not _straight_line_helper(definition):
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
    for name, node in reach.module:
        if name in node_scope:
            # A formal of the same name hides the module object from the
            # helper's body: what a function it calls does to it is not
            # followed here, so it takes the havoc.
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
    havoc_targets.extend(
        _unfollowed_reach(
            call, scope, reach, {_object_key(node) for _n, node, _l, _r in followed}
        )
    )
    edges: list = []
    _HELPERS_IN_PROGRESS.add(key)
    try:
        _body, _changed, net = definition._substitute_body_tracked(
            definition.body, node_scope, edge_states=edges
        )
    finally:
        _HELPERS_IN_PROGRESS.discard(key)
    # Before the body runs the call evaluates its operands: one that may
    # halt halts with every object as it was.
    operands_halt_free = all(
        _closed_operand(arg, kinds=_HALT_FREE_OPERAND_KINDS) for arg in call.args
    )
    states = []
    claimed = {id(arg) for _index, arg in actuals}
    for index, arg in enumerate(call.args):
        havoc_targets.extend(
            (node, _OPERAND_RULES, None)
            for node in _exposed(arg, bound_refs)
            if id(node) not in claimed
        )
    for name, actual, label, rebinds in followed:
        state = _state(net[name]) if name in net else actual
        written = _read_of(net[name]) if rebinds and name in net else None
        if (
            written is not None
            and getattr(written, "kind", None) not in _MUTATED_BINDINGS
            and not _same_read(written, actual)
        ):
            # The helper rebound the caller's cell (``n += 1``, ``n = v``):
            # its write is the caller's binding.  A write reads the key the
            # helper's statement binds when the call runs
            # (``EvaluationRef``): the caller's name reads that key after
            # the call, as the helper's own later reads do.  Only the cell's
            # name is rebound -- another name bound to the object it held
            # keeps it.  Only a binding the one door's mutation left (never a
            # write's reference, ``r += x`` included) is a mutation.
            if getattr(written, "kind", None) != "EvaluationRef":
                havoc_targets.append((actual, None, None))
                continue
            holds = operands_halt_free and _holds_at_every_halt(edges, name, state)
            states.append((actual, written, label, holds, name))
            continue
        if not _closed_state(state, actual):
            havoc_targets.append((actual, None, None))
            continue
        if not _mutated(state):
            # The helper left the object as it was.
            continue
        holds = operands_halt_free and _holds_at_every_halt(edges, name, state)
        states.append((actual, state, label, holds, None))
    return havoc_targets, states


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
    the name to (``Call._closure_definition``); None otherwise."""
    from .binding_state import unwrap_binding_state
    from .nodes import AsyncFunctionDef, Call, FunctionDef, Name
    from .panic import SugarNotWritten

    if not isinstance(call, Call) or not isinstance(call.func, Name):
        return None
    try:
        definition = call.unit.source_function_definition_for_call(call)
    except SugarNotWritten:
        return None
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
    decide is refused by name where its body is reduced; it adds nothing
    here."""
    from .panic import SugarNotWritten

    found = []
    for current in functions:
        try:
            references = current._module_global_references()
        except SugarNotWritten:
            references = {}
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
    (``_is_pure_call``); any other operation over values that are builtin
    all the way down (``_code_subjects``)."""
    from .nodes import Call

    if isinstance(call, Call):
        return _is_pure_call(call, {})
    return _code_subjects(call, {}) == []


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
    arguments) answers what the caller holds, once per statement."""
    from .nodes import Call

    subjects = reach = None
    if not isinstance(call, Call):
        # An operation no source function is named at: its operands' values
        # decide, asked first (most run over builtin values, and reach
        # nothing).
        subjects = _code_subjects(call, scope)
        if subjects is not None and not subjects:
            return []
    objects, rebound = (
        _ambient_objects(statement, scope) if ambient is None else ambient()
    )
    if not objects and not rebound:
        return []
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
        # It runs no code: nothing beyond its operands is reached.
        return []
    if subjects is None:
        targets = [(node, _OPERAND_RULES, None) for node in objects]
    else:
        targets = [
            (node, rules, subject) for node in objects for subject, rules in subjects
        ]
    targets.extend((node, None, None) for node in rebound)
    return targets


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


def _import_member(node) -> bool:
    """``node`` is an attribute read the unit's import receipt names a
    module's member (``import_value_use_receipt``): a module binding read
    by name, which runs nothing.  Only a dotted read of a name can be one;
    a unit whose receipts are refused has none (the read is an operation)."""
    if node.kind != "Attribute":
        return False
    root = node.value
    while getattr(root, "kind", None) == "Attribute":
        root = root.value
    if getattr(root, "kind", None) != "Name":
        return False
    from sugar_lift_py_tests.import_binding import AuthenticatedImportUseV1

    from .panic import SugarNotWritten

    span = node.line_col_span()
    try:
        receipt = node.unit.import_value_use_receipt(
            (span.start_line, span.start_col, span.end_line, span.end_col)
        )
    except SugarNotWritten:
        return False
    return type(receipt) is AuthenticatedImportUseV1


def _site_operands(site):
    """The operands whose values' dunders the operation ``site`` runs
    (``_sites_at``)."""
    kind = site.kind
    if kind == "Operated":
        return (site.node,)
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
    ``_is_pure_call``; an operation over builtin values).  None: no read
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
    if call.kind == "FormattedValue":
        operands = (call.value,)
    elif isinstance(call, PathContainerCall):
        operands = (call.receiver, *call.args)
    elif isinstance(call, Call):
        if _is_pure_call(call, scope):
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


# Source statement nodes whose evaluation cannot raise (``Try._HALT_FREE_NODES``,
# and a docstring): a halt never leaves a helper at one.
_HALT_FREE_SOURCE_KINDS = frozenset(
    {"Assign", "Expr", "Name", "Constant", "Tuple", "List", "Pass", "Nonlocal"}
)
# A substituted operand whose evaluation cannot raise: a closed operand
# (``_CLOSED_OPERAND_KINDS``) but a set or dict display, which hashes its
# members.
_HALT_FREE_OPERAND_KINDS = _CLOSED_OPERAND_KINDS - {"Set", "Dict"}


def _holds_at_every_halt(edges, name, final) -> bool:
    """Whether ``final`` (the formal ``name``'s state after the helper body)
    is its state at every halt inside the body too.

    ``edges`` is the body's threading reported per statement
    (``_substitute_body_tracked``'s ``edge_states``): each statement with the
    state in effect when it begins.  A halt leaves the body at a statement
    that may halt, with the state it began with.  So ``final`` holds at every
    halt when every such statement begins with the formal already in it, or
    is the formal's own one-door mutation and nothing else
    (``_halts_only_in_its_store``): a halt there is the mutation's, and the
    re-read of ``final`` sees that mutation halt and is an unknown
    (``SourceCallActualAfterSugar``), never the earlier state."""
    for index, (statement, pre) in enumerate(edges):
        before = _state(pre[name]) if name in pre else None
        if before is final or _handle(before) is _handle(final):
            continue
        if all(
            getattr(node, "kind", None) in _HALT_FREE_SOURCE_KINDS
            for node in statement.walk()
        ):
            continue
        after = (
            _state(edges[index + 1][1][name])
            if index + 1 < len(edges) and name in edges[index + 1][1]
            else final
        )
        if _halts_only_in_its_store(statement, name, before, after):
            continue
        return False
    return True


def _handle(node):
    return getattr(node, "ref", node)


def _halts_only_in_its_store(statement, name, before, after) -> bool:
    """``statement`` is ``name.method(operands)`` alone, over operands that
    cannot halt, and is the one-door mutation that takes ``name`` from
    ``before`` to ``after``: its only halt is that mutation's."""
    from .nodes import Attribute, Call, Expr, Name

    if not isinstance(statement, Expr):
        return False
    value = statement.value
    if not isinstance(value, Call) or value.keywords:
        return False
    func = value.func
    if not (
        isinstance(func, Attribute)
        and isinstance(func.value, Name)
        and func.value.id == name
    ):
        return False
    if not all(
        getattr(node, "kind", None) in _HALT_FREE_SOURCE_KINDS
        for arg in value.args
        for node in arg.walk()
    ):
        return False
    if before is None or not _mutated(after):
        return False
    receiver = getattr(getattr(after, "call", None), "receiver", None)
    return receiver is not None and same_object(_identity(receiver), before)


def _halts_before(statement, call) -> bool:
    """Whether something ``statement`` evaluates before ``call`` may halt.

    Python evaluates a node's operands in order (an assignment's value before
    its targets) and the node itself after them.  So what runs before
    ``call`` is, at every node on the path from ``statement`` down to it, the
    operands evaluated before the one that holds it.  A halt there leaves
    every object as the statement found it; a halt inside ``call`` or after
    it (the rest of the statement, the node that consumes the call's value)
    finds the objects as the call left them.  One rule wherever the call
    sits: a statement alone, an assignment's value, an argument, a
    condition, a returned value.  A call the walk does not find may follow
    anything."""
    path = _path_to(statement, call)
    if path is None:
        return True
    for node, position in path:
        for _name, _index, earlier in _evaluation_order(node)[:position]:
            if not _cannot_halt(earlier):
                return True
    return False


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


def _cannot_halt(node) -> bool:
    """``node``'s evaluation cannot raise: a read of a binding
    (``_READ_KINDS``), a constant, or a tuple or list display of such
    (``Try._HALT_FREE_NODES``)."""
    from .nodes import Node

    stack = [node]
    while stack:
        current = stack.pop()
        kind = getattr(current, "kind", None)
        if kind in _READ_KINDS or kind == "Constant":
            continue
        if kind not in ("Tuple", "List"):
            return False
        stack.extend(
            child
            for _name, _index, child in current._child_edges()
            if isinstance(child, Node)
        )
    return True


def _actual_after(site_node, state, label, tags, *, holds_at_halt=False):
    """The actual after the helper: ``state``.  ``holds_at_halt``: it is the
    actual's state at a halt inside the call too (the halted arm reads the
    same node, ``Try._mid_statement_state``)."""
    from .backend import Child, Leaf
    from .shadow import _handle_of

    fields = (
        ("state", Child(_handle_of(state))),
        ("label", Leaf(label)),
        ("occurrence", Leaf(_evaluation(site_node, tags))),
    )
    if holds_at_halt:
        fields = (*fields, ("holds_at_halt", Leaf(True)))
    return _materialize(site_node, "SourceCallActualAfter", fields, tags)


def _apply_actual_states(statement, pre_scope, scope, havocked, applied):
    """Rebind every name bound to an actual's object to its state after the
    helper; a name the havoc already rebound, or the statement itself bound,
    keeps that binding. A name that merely contains the object is unknown.
    A cell the helper rebinds (``name``) is that name alone: the object it
    held is not changed, and every other name keeps it."""
    from .shadow import occurrence_tags_of

    tags = occurrence_tags_of(statement)
    binding = {}
    havoc_names = []
    for actual, state, label, holds_at_halt, cell in applied:
        if cell is not None:
            if cell in binding or cell in havoc_names:
                # Two calls of the statement wrote it: which wrote last is
                # not followed here.
                binding.pop(cell, None)
                if cell not in havoc_names:
                    havoc_names.append(cell)
            elif _untouched(cell, pre_scope, scope, havocked):
                binding[cell] = _actual_after(
                    statement, state, label, tags, holds_at_halt=holds_at_halt
                )
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
                after = _actual_after(
                    statement,
                    state,
                    label,
                    tags,
                    holds_at_halt=holds_at_halt,
                )
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
