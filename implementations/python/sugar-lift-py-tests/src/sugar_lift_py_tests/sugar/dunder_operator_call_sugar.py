from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody

# The closed CPython binary-operator data model (`object.__mul__` et al):
# https://docs.python.org/3/reference/datamodel.html#emulating-numeric-types
# `x OP y` desugars to `x.__dunder__(y)` (or `y.__rdunder__(x)` when the left
# type refuses). An explicit `x.__mul__(y)` Call is that SAME protocol spelled
# longhand -- structurally, not semantically, different from `x * y`. This
# table is the language's own closed operator vocabulary, not a vendor
# whitelist: it never grows for a library, only for a new Python operator.
#
# name -> floor verb method the BinOp-family Sugars already call.
_DIRECT_DUNDER_VERBS: dict[str, str] = {
    "__add__": "add",
    "__sub__": "subtract",
    "__mul__": "multiply",
    "__truediv__": "divide",
    "__floordiv__": "floor_divide",
    "__mod__": "modulo",
    "__pow__": "power",
    "__matmul__": "matrix_multiply",
    "__and__": "bitwise_and",
    "__or__": "bitwise_or",
    "__xor__": "bitwise_xor",
    "__lshift__": "left_shift",
    "__rshift__": "right_shift",
}

_REFLECTED_DUNDER_VERBS: dict[str, str] = {
    "__radd__": "add",
    "__rsub__": "subtract",
    "__rmul__": "multiply",
    "__rtruediv__": "divide",
    "__rfloordiv__": "floor_divide",
    "__rmod__": "modulo",
    "__rpow__": "power",
    "__rmatmul__": "matrix_multiply",
    "__rand__": "bitwise_and",
    "__ror__": "bitwise_or",
    "__rxor__": "bitwise_xor",
    "__rlshift__": "left_shift",
    "__rrshift__": "right_shift",
}

# `x.__getitem__(i)` is `x[i]` spelled longhand -- SubscriptSugar's protocol,
# not an arithmetic verb. Bridged here too: same "explicit dunder call ==
# desugared syntax" mechanism, one recognizer for the whole call-vs-syntax
# split rather than a second bridge just for subscript.
_SUBSCRIPT_DUNDER = "__getitem__"

_DUNDER_NAMES = frozenset(
    {*_DIRECT_DUNDER_VERBS, *_REFLECTED_DUNDER_VERBS, _SUBSCRIPT_DUNDER}
)


@dataclass(frozen=True)
class DunderOperatorCallSugar(
    Sugar, role=SugarRole.TERM, comes_before=("MethodCallSugar",)
):
    """``x.__mul__(y)`` (and the rest of the closed binary-operator/subscript
    data-model protocol, direct or reflected) called out explicitly by name.

    An operator and its dunder are the SAME operation under two spellings:
    ``x * y`` desugars to exactly this call at the language level. Bridging
    the explicit spelling into the SAME floor verbs the ``BinOp``-family
    Sugars already call (``AddOpSugar`` -> ``.add``, ``FloorDivideOpSugar``
    -> ``.floor_divide``, ``SubscriptSugar`` -> ``.subscript``, ...) means one
    recognizer drains every member of the explicit-dunder-call shape, never a
    second parallel operator-semantics path.

    Authentication is entirely structural: the callee must be an Attribute
    whose name is a member of the closed CPython dunder-operator vocabulary,
    the receiver must be the Attribute's resolved (factory-built) value
    expression, and the call must carry exactly the operator's own arity (one
    positional argument, no keywords, no starred expansion) -- never a
    callee-name whitelist or vendor/module string. A lookalike callable
    reached through anything other than a direct ``receiver.__dunder__``
    Attribute (``getattr(x, '__dunder__')(y)``, a plain same-named non-dunder
    method, wrong arity) never matches ``owns`` and falls through to
    ``MethodCallSugar`` / the ordinary call floor untouched. A receiver whose
    floor type does not stand on the addressed operator floor (or whose
    object body cannot resolve the named method) stays the existing loud
    ``FactoryPanic`` those floors already raise for `x * y` on the same
    receiver -- this bridge adds no new suppression.
    """

    dunder_name: str
    receiver: SugarBody
    operand: SugarBody
    reflected: bool
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        if site.observed != "Call":
            return False
        if site.call_receiver() is None:
            return False
        if site.call_has_keywords():
            return False
        if site.call_arg_count() != 1:
            return False
        return site.call_target_name() in _DUNDER_NAMES

    @classmethod
    def new(cls, site, ctx) -> "DunderOperatorCallSugar":
        name = site.call_target_name()
        return cls(
            dunder_name=name,
            receiver=ctx.build_body(site.call_receiver(), SugarRole.TERM),
            operand=ctx.build_body(site.call_args()[0], SugarRole.TERM),
            reflected=name in _REFLECTED_DUNDER_VERBS,
            site=site,
        )

    @classmethod
    def witnesses(cls):
        direct_prefix = "def A(z):\n    return (5).__mul__(3)\n\n"
        reflected_prefix = "def A(z):\n    return (2).__rfloordiv__(7)\n\n"
        getitem_prefix = "def A(z):\n    return [10, 20, 30].__getitem__(1)\n\n"
        add_prefix = "def A(z):\n    return (5).__add__(2)\n\n"
        return (
            _call_pair(
                name="explicit_mul_dunder_call_return",
                owner_sugar="DunderOperatorCallSugar",
                truthful=direct_prefix + "def test_a():\n    assert A(5) == 15\n",
                lying=direct_prefix + "def test_a():\n    assert A(5) == 16\n",
            ),
            _call_pair(
                name="explicit_add_dunder_call_return",
                owner_sugar="DunderOperatorCallSugar",
                truthful=add_prefix + "def test_a():\n    assert A(5) == 7\n",
                lying=add_prefix + "def test_a():\n    assert A(5) == 8\n",
            ),
            _call_pair(
                name="explicit_reflected_floordiv_dunder_call_return",
                owner_sugar="DunderOperatorCallSugar",
                # (2).__rfloordiv__(7) means 7 // 2 == 3, NOT 2 // 7 == 0 --
                # the reflected twin: getting the operand order backwards
                # must refute.
                truthful=reflected_prefix + "def test_a():\n    assert A(5) == 3\n",
                lying=reflected_prefix + "def test_a():\n    assert A(5) == 0\n",
            ),
            _call_pair(
                name="explicit_getitem_dunder_call_return",
                owner_sugar="DunderOperatorCallSugar",
                truthful=getitem_prefix + "def test_a():\n    assert A(5) == 20\n",
                lying=getitem_prefix + "def test_a():\n    assert A(5) == 30\n",
            ),
        )

    def desugar(self, ctx: object = None) -> Outcome:
        return self.receiver.reduce(ctx).and_then(
            lambda receiver: self.operand.reduce(ctx).and_then(
                lambda operand: self._finish(receiver, operand, ctx)
            )
        )

    def _finish(self, receiver, operand, ctx):
        from sugar_lift_py_tests.floor import ObjectValue

        if isinstance(receiver, ObjectValue):
            # The written call names the receiver's OWN method table entry --
            # reflected or not, `receiver.__dunder__(operand)` always resolves
            # through the receiver's class body, never a swapped verb.
            return receiver.call_method_value(
                self.dunder_name,
                (operand,),
                owner=type(self).__name__,
                blame=self.site,
                ctx=ctx,
            )
        if self.dunder_name == _SUBSCRIPT_DUNDER:
            return receiver.subscript(operand, self.site)
        verb = (_REFLECTED_DUNDER_VERBS if self.reflected else _DIRECT_DUNDER_VERBS)[
            self.dunder_name
        ]
        if self.reflected:
            # `receiver.__rdunder__(operand)` means `operand OP receiver`:
            # the reflected call's own receiver is the RIGHT operand.
            return getattr(operand, verb)(receiver, self.site)
        return getattr(receiver, verb)(operand, self.site)

    def walk_children(self):
        return (self.receiver, self.operand)
