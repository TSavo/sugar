from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import ClassVar

from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import Sugar


#: ``(noun, owner)`` of each attribute mutation's undecided faces, whatever
#: the undecided receiver.
_ATTRIBUTE_MUTATIONS = {
    "__setattr__": ("setattr", "UndecidedSetattr"),
    "__delattr__": ("delattr", "UndecidedDelattr"),
}


def attribute_mutation(method, receiver, attr: str, operands, site, ctx, *, unit):
    """``receiver.attr = v`` (``__setattr__``, ``operands`` the value) or
    ``del receiver.attr`` (``__delattr__``, no operand) on a receiver that is
    no instance of a source class: THE attribute store or delete, one way
    (#7757 step 7).  Python runs ``type(receiver).__setattr__(receiver,
    "attr", v)`` / ``type(receiver).__delattr__(receiver, "attr")`` (data
    descriptors are found inside it), a different method and obligation from
    the read path (``attribute``, ``__getattribute__``, ``__getattr__``).
    The one field store (``ReceiverFieldStoreSugar``), the one attribute
    delete (``AttributeDeleteEffectSugar``) and a value that only carries
    another (an authenticated exception-type operand) all take it.

    - A formal of the function whose own proof this is (its plain value, a
      ``SymbolicValue`` with a ``formal_coordinate``) waits on no caller's
      actual:

      - ``del p.f`` where ``p``'s class is a class input here
        (``receiver_dispatch.dispatch_on_receiver``) is the dispatched call
        ``call:dispatch:__delattr__(p, "f")``, resolved at prove at the class
        the caller binds (a source ``__delattr__``'s contract; owed where
        nothing answers it, ``object``'s included).  The receiver after it is
        ``python:after(<call>, "0")`` (``receiver_after_dispatch``).
      - any other store or delete on a formal is the undecided mutation
        (``undecided_attribute_mutation_faces``): it completes under its own
        atom or raises something undetermined, both faces owing the
        undecided member.  A store on a parameter whose class is a contract
        input (``receiver_dispatch.stored_class_input``) completes also
        where the store is the plain ``__dict__`` store
        (``python:plain_store(class:<p>, "<f>")``, decided at prove on the
        class the caller binds, ``consistency::plain_store_holds``, and
        nowhere else); its halt is the complement.
    - A receiver whose type the lift decides is its floor's own store or
      delete, every face of it (an ``AttributeError``, a ``TypeError``)
      kept.
    - Any other receiver -- an undecided call result, a free name -- is the
      same undecided mutation a formal's is
      (``undecided_attribute_mutation_faces``, #7757 NEW-4), with no
      ``plain`` guard: no class input of this proof names its class.  There
      is one spelling of "an attribute store or delete nothing decides", as
      there is one of an item store or delete
      (``undecided_item_mutation_faces``)."""
    noun, owner = _ATTRIBUTE_MUTATIONS[method]
    plain = None
    if getattr(receiver, "formal_coordinate", None) is not None:
        from sugar_lift_py_tests.floor import StringValue
        from sugar_lift_py_tests.receiver_dispatch import (
            dispatch_on_receiver,
            plain_store_atom,
            receiver_after_dispatch,
            stored_class_input,
        )

        if method == "__delattr__":
            dispatched = dispatch_on_receiver(
                method, receiver, (StringValue(attr),), (), site, unit=unit
            )
            if dispatched is not None:
                from sugar_lift_py_tests.sugar.builtin_container_call_sugar import (
                    _unknown_after,
                )

                def after(result):
                    post = receiver_after_dispatch(receiver, result)
                    return ExitSet.completed(
                        post if post is not None else _unknown_after(site, method)
                    )

                return dispatched.and_then(after)
        if method == "__setattr__":
            class_input = stored_class_input(receiver, attr, unit)
            if class_input is not None:
                from sugar_lift_py_tests.ir import make_var

                plain = plain_store_atom(make_var(class_input), attr)
    elif receiver.runtime_type_is_decided():
        if method == "__setattr__":
            return receiver.setattr(attr, *operands, site, ctx)
        return receiver.delattr(attr, site, ctx)
    return undecided_attribute_mutation_faces(
        receiver, attr, site, noun=noun, method=method, owner=owner, plain=plain
    )


def undecided_attribute_mutation_faces(
    receiver, attr: str, site, *, noun: str, method: str, owner: str, plain=None
):
    """Two faces for ``p.attr = v`` / ``del p.attr`` over a receiver whose
    type nothing here decides.

    The mutation completes only under ``python:<noun>.completes(python:
    <noun>(<receiver>, "<attr>", <occurrence>))`` -- the receiver named by
    its identity (``identity_term``), keyed on this exact site and
    occurrence so two mutations are never forced to agree, the spelling
    ``ObjectValue._undecided_delattr`` already gives an undecided delete --
    or under ``plain`` where it is given (``or(plain, <completes>)``: the
    plain ``__dict__`` store, decided at prove).  Its post-state is
    ``python:receiver_after_call(<occurrence>, <method>)``: the receiver's
    contents after the call are unknown.  The complement halts with an
    ``UndeterminedRaiseEffect`` (``owner``): a slot class, a read-only
    property, a ``__setattr__`` / ``__delattr__`` that raises are not ruled
    out, and no exception type is guessed."""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.floor.object_identity import identity_term
    from sugar_lift_py_tests.ir import atomic, ctor, or_, str_const
    from sugar_lift_py_tests.occurrence import occurrence_key
    from sugar_lift_py_tests.sugar.builtin_container_call_sugar import _unknown_after

    key = occurrence_key(site)
    receiver_term = identity_term(receiver, site, "receiver", owner=str(site))
    guard = atomic(
        f"python:{noun}.completes",
        [ctor(f"python:{noun}", (receiver_term, str_const(attr), str_const(key)))],
    )
    if plain is not None:
        guard = or_([plain, guard])
    return ExitSet.two_faced(
        _unknown_after(site, method),
        UndeterminedRaiseEffect(
            blame=str(site),
            occurrence=key,
            producer_node_owner=owner,
            site=site,
        ),
        guard=guard,
        site=site,
    )


@dataclass(frozen=True)
class SubscriptStoreEffectSugar(Sugar):
    """`receiver[index] = value` — evaluate once, then project the store face.

    Python order: RHS first, then the receiver, then the index, each exactly
    once.  Dispatch is ``__setitem__`` via Floor ``setitem`` — a different
    method and obligation from the load path ``subscript`` / ``__getitem__``.

    The store itself is the one item mutation (``item_mutation``), the same
    one the container-mutation door's ``__setitem__`` takes.
    """

    receiver: Sugar
    index: Sugar
    value: Sugar
    site: object = dataclass_field(compare=False)
    # Nothing binds before the store's halt (the RHS's, the receiver's, the
    # index's, the store's own face): its pre-halt record is the block's
    # prefix.
    halts_at_statement_head: ClassVar[bool] = True

    @classmethod
    def witnesses(cls):
        # The source-visible completed/exceptional and loud-refusal laws are
        # discrimination tests in test_subscript_store_desugar.py /
        # test_setitem_formal_caller.py. The former typed-runtime-effect
        # witness asserted the superseded generic effect.
        return ()

    def desugar(self, ctx: object = None) -> ExitSet:
        # Python evaluates the RHS before the target receiver and key.
        return self.value.desugar(ctx).and_then(
            lambda value: self.receiver.desugar(ctx).and_then(
                lambda receiver: self.index.desugar(ctx).and_then(
                    lambda index: self._store(receiver, index, value, ctx)
                )
            )
        )

    def _store(self, receiver, index, value, ctx) -> ExitSet:
        return item_mutation(
            "__setitem__",
            receiver,
            (index, value),
            self.site,
            ctx,
            unit=getattr(self.site, "unit", None),
        )


#: ``(noun, owner)`` of each item mutation's undecided faces.
_ITEM_MUTATIONS = {
    "__setitem__": ("setitem", "UndecidedSetitem"),
    "__delitem__": ("delitem", "UndecidedDelitem"),
}


def item_mutation(
    method, receiver, operands, site, ctx, *, unit, label="receiver"
) -> ExitSet:
    """``receiver[k] = v`` (``__setitem__``, ``operands`` the key and the
    value) or ``del receiver[k]`` (``__delitem__``, the key): THE item store
    or delete, one way (#7757 step 7), whatever the receiver is.  Python runs
    ``type(receiver).__setitem__(receiver, k, v)``; the operation completes
    with the receiver as it left it.  Every operand is projected to its value
    first (``a[f()] = 9`` stores at what ``f`` returns).

    - A receiver whose type binds no such method (``receiver_lacks_item_
      method``) raises its ``TypeError``, whatever the key and the value
      are.
    - A receiver whose class is a class input here or a same-file class's
      call result (``receiver_dispatch.dispatch_on_receiver``: a formal's,
      a captured cell's, an ``__init__`` receiver's) is the dispatched call
      ``call:dispatch:__setitem__(...)``, resolved at prove at the class the
      caller binds: a builtin ``list`` or ``dict`` takes its law
      (``consistency::builtin_dispatch_answer``, #8864), a source class its
      method's contract; owed where nothing binds it.  The receiver after
      it is ``python:after(<call>, "0")`` (``receiver_after_dispatch``).
    - A receiver whose type nothing here decides -- a formal whose class is
      no input, an opaque call result -- is the undecided mutation
      (``undecided_item_mutation_faces``): it completes under its own atom
      or raises something undetermined, both faces owing the undecided
      member.  No operation waits on a caller's actual.
    - A receiver whose type the lift decides is its floor's own store or
      delete, every face of it (an ``IndexError``, a ``KeyError``, a
      ``TypeError``) kept.  A value that only carries others (a guarded
      choice, ``GuardedValue``; a walrus, ``NamedExpressionValue``; an
      authenticated exception-type operand) takes each value it carries
      through this door again, never that value's own ``setitem`` or
      ``delitem``: a symbolic arm of a guarded receiver is the undecided
      mutation here as it is unguarded, its halt kept.

    ``label`` names the receiver's unknown post-state where a dispatched
    call leaves no ``after`` term."""
    from sugar_lift_py_tests.floor.floor_value import receiver_lacks_item_method
    from sugar_lift_py_tests.receiver_dispatch import (
        dispatch_on_receiver,
        receiver_after_dispatch,
    )

    owner = f"item_mutation({method})"
    receiver = receiver.project_operation_receiver(ctx, owner=f"{owner} receiver")
    operands = tuple(
        operand.project_operation_receiver(ctx, owner=f"{owner} operand")
        for operand in operands
    )

    def floor():
        if method == "__setitem__":
            return receiver.setitem(*operands, site, ctx)
        return receiver.delitem(*operands, site, ctx)

    if receiver_lacks_item_method(receiver, method):
        return floor()
    dispatched = dispatch_on_receiver(method, receiver, operands, (), site, unit=unit)
    if dispatched is not None:
        from sugar_lift_py_tests.sugar.builtin_container_call_sugar import (
            _unknown_after,
        )

        def after(result):
            post = receiver_after_dispatch(receiver, result)
            return ExitSet.completed(
                post if post is not None else _unknown_after(site, label)
            )

        return dispatched.and_then(after)
    if not receiver.runtime_type_is_decided():
        noun, undecided_owner = _ITEM_MUTATIONS[method]
        return undecided_item_mutation_faces(
            site, noun=noun, method=method, owner=undecided_owner
        )
    return floor()


def undecided_item_mutation_faces(site, *, noun: str, method: str, owner: str):
    """Two faces for ``r[k] = v`` / ``del r[k]`` over an undecided receiver.

    The mutation completes only under
    ``python:<noun>.completes(python:<noun>(<occurrence>))``, keyed on this
    exact site and occurrence so two mutations are never forced to agree, and
    its post-state is ``python:receiver_after_call(<occurrence>, <method>)``:
    the receiver's contents after the call are unknown, as for any undecided
    mutation.  The complement halts with an ``UndeterminedRaiseEffect``
    (``owner``).  No entry is written or removed and no exception type is
    guessed.
    """
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.ir import atomic, ctor, str_const
    from sugar_lift_py_tests.occurrence import occurrence_key
    from sugar_lift_py_tests.outcome.exit_set import ExitSet
    from sugar_lift_py_tests.sugar.builtin_container_call_sugar import _unknown_after

    key = occurrence_key(site)
    completes = atomic(
        f"python:{noun}.completes",
        [ctor(f"python:{noun}", (str_const(key),))],
    )
    return ExitSet.two_faced(
        _unknown_after(site, method),
        UndeterminedRaiseEffect(
            blame=str(site),
            occurrence=key,
            producer_node_owner=owner,
            site=site,
        ),
        guard=completes,
        site=site,
    )
