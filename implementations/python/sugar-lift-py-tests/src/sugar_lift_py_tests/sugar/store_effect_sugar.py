from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import ClassVar

from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import Sugar


def project_setattr(
    receiver, attr: str, value, site, ctx, *, plain_store_input=None
) -> ExitSet:
    """``receiver.attr = value`` on a receiver that is no instance of a
    source class: the ordinary store, already-evaluated receiver and value.
    The one field store (``ReceiverFieldStoreSugar``) takes it for every
    such receiver its value gives.  Dispatch is ``__setattr__`` / descriptor
    ``__set__`` via Floor ``setattr`` — a different method and obligation
    from the read path ``attribute`` / ``__getattr__`` /
    ``__getattribute__``.

    1. Formal receiver → undischarged ``setattr_named`` carrier
       (``mint_setattr_named_carrier``): the n-ary projector (#6614) unwraps
       the name and calls ``receiver.setattr(name.value, value, site, ctx)``;
       an ordinary source caller supplies actuals.  ``plain_store_input``
       (``receiver_dispatch.stored_class_input``) is the class input of a
       parameter whose class the contract takes: the store completes where
       it is the plain store (#7757 step 7).
    2. Decided runtime type → Floor ``setattr``; a raise is its halted arm
       (halted store, not statement green)
    3. Undecided non-formal → the two faces of the store (``store_faces``:
       completes with ``AttributeStoreRuntimeEffect`` testimony or raises
       something undetermined; never consumer ``SugarNotWritten``)
    """
    formal_coordinate = getattr(receiver, "formal_coordinate", None)
    if formal_coordinate is not None:
        return mint_setattr_named_carrier(
            site=site,
            receiver=receiver,
            attr=attr,
            value=value,
            plain_store_input=plain_store_input,
        )

    if receiver.runtime_type_is_decided():
        return receiver.setattr(attr, value, site, ctx)

    from sugar_lift_py_tests.effect import (
        AttributeStoreRuntimeEffect,
        runtime_effect_evidence_from_terms,
    )
    from sugar_lift_py_tests.floor.store_outcome_coordinate import store_faces
    from sugar_lift_py_tests.ir import ctor, str_const

    operation = ctor(
        "python:attribute_store",
        [
            receiver.to_term(owner="project_setattr.receiver"),
            str_const(attr),
            value.to_term(owner="project_setattr.value"),
        ],
    )
    return store_faces(
        AttributeStoreRuntimeEffect(
            "attribute assignment runtime boundary: attribute store "
            f"target `.{attr}` -- receiver identity belongs to "
            "Python's runtime __setattr__/descriptor dispatch; "
            f"attr={attr} site={site}",
            **runtime_effect_evidence_from_terms(operation, operation, site),
        )
    )


def mint_setattr_named_carrier(
    *, site, receiver, attr: str, value, plain_store_input=None
):
    """Producer-side contract for n-ary ``setattr_named`` discharge.

    Operand order matches the projector table (#6614):
    ``receiver.setattr(name.value, value, site, ctx)`` after unwrap.
    Coordinates: ``(receiver.formal, None, value.formal)`` — lengths and
    order are load-bearing (#6613 ``__post_init__``).  ``plain_store_input``
    rides on the carrier (``NativeOperationExitCarrierV1.plain_store_input``).
    """
    from dataclasses import replace

    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )
    from sugar_lift_py_tests.floor import StringValue

    formal_coordinate = getattr(receiver, "formal_coordinate", None)
    if formal_coordinate is None:
        raise ValueError("setattr_named carrier requires a receiver formal_coordinate")
    value_coordinate = getattr(value, "formal_coordinate", None)
    carrier = NativeOperationExitCarrierV1.mint(
        site=site,
        operator="setattr_named",
        operands=(receiver, StringValue(attr), value),
        coordinates=(formal_coordinate, None, value_coordinate),
    )
    if plain_store_input is None:
        return carrier
    return replace(carrier, plain_store_input=plain_store_input)


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
      ``TypeError``) kept.

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
