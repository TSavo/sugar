from __future__ import annotations

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.floor import CallSiteValue
from sugar_lift_py_tests.floor.builtin_super_value import BuiltinSuperValue
from sugar_lift_py_tests.floor.named_expression_value import peel_walrus_binds
from sugar_lift_py_tests.floor.string_value import StringValue
from sugar_lift_py_tests.outcome import Completed
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import ClassDef
from sugar_source_tree.tree import SourceFile
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1

from frame_fresh import FRAME_FRESH


def _constructed(source: str):
    tree = SourceFile(
        (source, "super_dispatch.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    context = ReduceContext.root(owner="test")
    values = []
    for node in tree.root.body:
        if not isinstance(node, ClassDef):
            continue
        value = node.sugar().desugar(context).completed_value()
        context.temporal = context.temporal.bind_value(value.class_name, value)
        values.append(value)
    return context, values


def _call_fragment(source: str, text: str):
    """The source fragment of the call spelled ``text`` in ``source``: the
    site the lifter hands a ``super().<name>(...)`` call (a ground exit
    cites the source it can re-read, never prose)."""
    from sugar_source_tree.nodes import Call

    tree = SourceFile(
        (source, "super_dispatch.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    return next(
        node.fragment
        for node in tree.nodes()
        if isinstance(node, Call) and node.fragment.text == text
    )


def _edge_call(outcome):
    """The call coordinate ``outcome`` completes with: a method call on a
    receiver whose class is decided is its coordinate and edge (#7757 step
    6, #8738), the unanswered call's two faces, completing under its
    ``completes`` atom and halting under the complement.  The method's body
    is never applied here."""
    (done,) = [arm for arm in outcome.exits if isinstance(arm, Completed)]
    assert outcome.halts(), outcome
    _binds, call = peel_walrus_binds(done.value)
    assert isinstance(call, CallSiteValue), type(call)
    return call


# --- truthful twin: zero-arg super() into a same-module source base -----------
_TRUTHFUL = (
    "class Base:\n"
    "    def __init__(self, x):\n"
    "        self.x = x\n"
    "\n"
    "class Derived(Base):\n"
    "    def __init__(self, x):\n"
    "        super().__init__(x)\n"
)


_LIAR = (
    "class Base:\n"
    "    def __init__(self, x):\n"
    "        self.x = x\n"
    "\n"
    "class Derived(Base):\n"
    "    def __init__(self, x):\n"
    "        super().greet(x)\n"
)


def test_super_naming_an_absent_method_is_the_attribute_error() -> None:
    # Derived's MRO is read whole (Derived, Base, object) and no class after
    # Derived binds ``greet``: CPython's AttributeError, never a base method.
    context, (_base, derived) = _constructed(_LIAR)
    receiver = derived.fresh_receiver("receiver", allocation=FRAME_FRESH)
    zuper = BuiltinSuperValue(current_class=derived, receiver=receiver)

    outcome = zuper.call_method_value(
        "greet",
        (StringValue("v"),),
        owner="test",
        blame=_call_fragment(_LIAR, "super().greet(x)"),
        ctx=context,
    )

    assert outcome.halts() == outcome.exits
    assert [halt.effect.exception_name for halt in outcome.halts()] == [
        "AttributeError"
    ]


# --- a method the selected class writes, never one it inherits -----------------
_OWN_METHOD_ONLY = (
    "class Base:\n"
    "    def __init__(self, x):\n"
    "        self.x = x\n"
    "\n"
    "class Middle(Base):\n"
    "    pass\n"
    "\n"
    "class Derived(Middle):\n"
    "    def __init__(self, x):\n"
    "        super().__init__(x)\n"
)


def test_super_runs_the_first_class_after_the_cell_that_binds_the_name() -> None:
    # ``Middle`` binds no ``__init__``: the first class after ``Derived``'s
    # cell that does is ``Base``, never the one ``Middle`` inherits through.
    # The call is ``Base.__init__``'s coordinate and edge (#7757 step 6,
    # #8738); the store ``self.x = x`` its body makes on the receiver is
    # joined from ``Base.__init__``'s contract at prove (step 7), so it is
    # no longer read here (it was, while the body was applied at lift; the
    # application was deleted by #8751).
    context, (_base, _middle, derived) = _constructed(_OWN_METHOD_ONLY)
    receiver = derived.fresh_receiver("receiver", allocation=FRAME_FRESH)

    call = _edge_call(
        BuiltinSuperValue(current_class=derived, receiver=receiver).call_method_value(
            "__init__",
            (StringValue("v"),),
            owner="test",
            blame="super-init",
            ctx=context,
        )
    )

    assert call.target_name.endswith("Base.__init__"), call.target_name
    assert "Middle" not in call.target_name
    assert call.arg_values[-1] == StringValue("v")


_ANNOTATED = (
    "class Base:\n"
    "    def __init__(self, match=None):\n"
    "        self.match = match\n"
    "        self._fail_reason: str | None = None\n"
    "        self._nested: bool = False\n"
    "        self.is_baseexception = False\n"
    "\n"
    "class Derived(Base):\n"
    "    def __init__(self, match=None):\n"
    "        super().__init__(match=match)\n"
    "        self.expected_exceptions = ()\n"
)


