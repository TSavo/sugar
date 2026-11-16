"""Zero-argument ``super().__new__`` over a tail of builtins is the one call
(#7757 L5).

``super().__new__(mcs, name, bases, namespace)`` in a metaclass's
``__new__`` reaches ``type.__new__``: the order after ``__class__`` (``type``,
``object``) holds no source class.  The lift used to answer that call by the
floor's own ``type.__new__`` (a class value over the namespace),
beside the dispatched call the same lookup takes through any source class.
Now it is the one dispatched call after ``__class__`` for every tail; with no
workspace root (these classes name no join symbol) it is the one unanswered
call of ``super.__new__``, owed, both faces standing.  The lift builds no
class and refuses no namespace shape of its own.
"""

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import (
    BuiltinSuperValue,
    CallSiteValue,
    DictValue,
    StringValue,
    TermValue,
    TupleValue,
)
from sugar_lift_py_tests.floor.named_expression_value import peel_walrus_binds
from sugar_lift_py_tests.outcome import Completed
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import ClassDef
from sugar_source_tree.tree import SourceFile

from frame_fresh import FRAME_FRESH

_METACLASS = (
    "class Meta(type):\n"
    "    def __new__(mcs, name, bases, namespace, **kwds):\n"
    "        return super().__new__(mcs, name, bases, namespace)\n"
)


def _metaclass():
    # ``super()`` in a metaclass's ``__new__`` binds the metaclass itself, a
    # class whose own MRO (Meta, type, object) it walks.
    tree = SourceFile(
        (_METACLASS, "type_new_transport.py", blake3_512_of(_METACLASS.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    definition = next(node for node in tree.root.body if isinstance(node, ClassDef))
    meta = definition.sugar().desugar(ReduceContext.root(owner="test")).completed_value()
    assert meta is not None
    return meta


def _super_value(meta):
    return BuiltinSuperValue(current_class=meta, receiver=meta)


def _the_one_call(outcome) -> None:
    (done,) = [arm for arm in outcome.exits if isinstance(arm, Completed)]
    (halt,) = outcome.halts()
    assert isinstance(halt.effect, UndeterminedRaiseEffect)
    assert halt.effect.producer_node_owner == "UnknownCallee:super.__new__"
    _binds, call = peel_walrus_binds(done.value)
    assert isinstance(call, CallSiteValue), type(call)
    assert call.body is None
    assert outcome.owed_items()


def test_super_new_over_type_is_the_one_call_never_a_class_built_here() -> None:
    namespace = DictValue(
        ((StringValue("member"), TermValue(7)),),
        allocation=FRAME_FRESH,
    )

    meta = _metaclass()
    _the_one_call(
        _super_value(meta).call_method_value(
            "__new__",
            (
                meta,
                StringValue("Made"),
                TupleValue(()),
                namespace,
            ),
            owner="test",
            blame="new-site",
        )
    )


def test_super_new_over_type_never_refuses_a_namespace_shape() -> None:
    # ``type.__new__`` decides what it accepts; the lift no longer reads its
    # operands to refuse them.
    meta = _metaclass()
    _the_one_call(
        _super_value(meta).call_method_value(
            "__new__",
            (
                meta,
                StringValue("Made"),
                TupleValue(()),
                StringValue("not-a-namespace"),
            ),
            owner="test",
            blame="new-site",
        )
    )
