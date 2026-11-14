"""One law, not eight arms: a binary operation with an undecided operand.

The binary-operation floor gaps measured on the pinned pandas tree
(``docs/ledgers/pandas-3.0.3-control-effect-9a78828ee.json``) came in eight
operator names -- ``add``, ``subtract``, ``multiply``, ``divide``,
``bitwise_and``/``or``/``xor`` -- wearing one shape: a left value with no arm
named for THIS right operand, falling to the (owner x pair) gap.

Most of those pairs are not eight arms to write. When at least one operand's
runtime TYPE is undecided, Python's own operator dispatch for the pair is
undecided, so the operation may raise anything (the #7585 law, as for
ordering in #7622): it completes with the undecided
``python:binary_result(op, left, right, <occurrence>)`` only under
``python:binary_op.completes(python:binary_op(op, <occurrence>))`` and halts
with an ``UndeterminedRaiseEffect`` (owner ``UndecidedBinary:<op>``) under the
complement.  No exception type is named and no result is folded.

The category is read from each value's own testimony (``denotes_value`` /
``runtime_type_is_decided``), never from a lexical type name.

Every positive arm below carries its discriminating arm: the law admits the
undecided pair and stays LOUD everywhere else.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.floor.bytes_value import BytesValue
from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
from sugar_lift_py_tests.floor.complex_value import ComplexValue
from sugar_lift_py_tests.floor.comprehension_value import ComprehensionValue
from sugar_lift_py_tests.floor.list_value import ListValue
from sugar_lift_py_tests.floor.none_value import NoneValue
from sugar_lift_py_tests.floor.predicate_value import PredicateValue
from sugar_lift_py_tests.floor.set_value import SetValue
from sugar_lift_py_tests.floor.string_value import StringValue
from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
from sugar_lift_py_tests.floor.term_value import TermValue
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.ir import PrimitiveSort, _Atomic, _Lambda, ctor, make_var

SITE = "undecided-binary-site"


def _symbolic() -> SymbolicValue:
    return SymbolicValue(make_var("s"))


def _callsite() -> CallSiteValue:
    return CallSiteValue("vendor.op", (), (), ctor("call:vendor.op", []), None)


def _predicate() -> PredicateValue:
    return PredicateValue(_Atomic("py.gt", (make_var("a"), make_var("b"))), SITE)


def _comprehension() -> ComprehensionValue:
    return ComprehensionValue(
        ctor(
            "py.listcomp",
            [
                make_var("xs"),
                _Lambda("p", PrimitiveSort("Value"), make_var("p")),
                ctor("python:loop.exhaustion", []),
            ],
        )
    )


def _two_faced(left, right, method: str, operator: str):
    """Undecided native dispatch: completes under its atom, else halts undetermined."""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.outcome.exit_set import Completed, Halted

    exits = getattr(left, method)(right, SITE, None).exits
    (done,) = [face for face in exits if isinstance(face, Completed)]
    (halt,) = [face for face in exits if isinstance(face, Halted)]
    assert "python:binary_op.completes" in repr(done.guard)
    assert isinstance(done.value, SymbolicValue)
    assert done.value.term.name == "python:binary_result"
    assert done.value.term.args[0].value == operator
    # No exception type is named: the halt is undetermined.
    assert type(halt.effect) is UndeterminedRaiseEffect
    assert halt.effect.producer_node_owner == f"UndecidedBinary:{operator}"
    return done, halt


def test_undecided_native_bitwise_dispatch_is_two_faced() -> None:
    """The producer cannot choose sole ``__and__`` or sole TypeError."""
    _two_faced(_symbolic(), TermValue(0), "bitwise_and", "&")


@pytest.mark.parametrize(
    ("method", "operator"),
    (
        ("add", "+"),
        ("subtract", "-"),
        ("multiply", "*"),
        ("divide", "/"),
        ("floor_divide", "//"),
        ("modulo", "%"),
        ("power", "**"),
        ("matrix_multiply", "@"),
        ("bitwise_and", "&"),
        ("bitwise_or", "|"),
        ("bitwise_xor", "^"),
        ("left_shift", "<<"),
        ("right_shift", ">>"),
    ),
)
def test_undecided_call_result_is_two_faced(method: str, operator: str) -> None:
    _two_faced(_callsite(), TermValue(2), method, operator)


@pytest.mark.parametrize(
    ("method", "operator"),
    (
        ("add", "+"),
        ("subtract", "-"),
        ("multiply", "*"),
        ("divide", "/"),
        ("floor_divide", "//"),
        ("modulo", "%"),
        ("power", "**"),
        ("matrix_multiply", "@"),
        ("bitwise_and", "&"),
        ("bitwise_or", "|"),
        ("bitwise_xor", "^"),
        ("left_shift", "<<"),
        ("right_shift", ">>"),
    ),
)
def test_symbolic_left_operand_is_two_faced(method: str, operator: str) -> None:
    _two_faced(_symbolic(), TermValue(2), method, operator)


def test_ground_total_addition_never_acquires_an_exceptional_edge() -> None:
    """Lying twin: source-decided integer addition remains one completion."""
    outcome = TermValue(1).add(TermValue(2), SITE, None)
    assert outcome.completed_value() == TermValue(3)


def test_swapped_symbolic_operands_are_each_their_own_two_faces() -> None:
    """Both orderings are two-faced, and they are different operations."""
    left = SymbolicValue(make_var("left"))
    right = SymbolicValue(make_var("right"))
    forward, _ = _two_faced(left, right, "subtract", "-")
    reverse, _ = _two_faced(right, left, "subtract", "-")
    assert forward.value != reverse.value


def test_a_named_exception_type_is_never_invented_for_the_halt() -> None:
    """A boundary matcher sees an undetermined halt, never a minted TypeError."""
    _, halt = _two_faced(_symbolic(), TermValue(2), "add", "+")
    assert "TypeError" not in repr(halt.effect)


# -- positive arm: the pairs the pinned census actually found -----------------


@pytest.mark.parametrize(
    ("left", "right", "method", "operator"),
    (
        # pandas/io/formats/{excel,html,xml}.py, io/parsers/arrow_parser_wrapper.py
        (_comprehension(), _symbolic(), "add", "+"),
        # pandas/io/formats/html.py, io/formats/style.py
        (_predicate(), _symbolic(), "add", "+"),
        # pandas/core/ops/missing.py, tests/io/pytables/test_select.py
        (_predicate(), _callsite(), "bitwise_and", "&"),
        # pandas/core/strings/accessor.py
        (SetValue((TermValue(1),)), _callsite(), "subtract", "-"),
        # pandas/io/stata.py, tests/io/json/test_ujson.py
        (BytesValue(b"x"), _symbolic(), "multiply", "*"),
        (BytesValue(b"x"), _symbolic(), "add", "+"),
        (BytesValue(b"x"), _callsite(), "add", "+"),
        # pandas/tests/internals/test_internals.py
        (ComplexValue(1.0, 2.0), _symbolic(), "multiply", "*"),
        # pandas/tests/arithmetic/test_string.py
        (NoneValue(), _callsite(), "add", "+"),
    ),
)
def test_an_undecided_operand_is_two_faced(
    left, right, method, operator
) -> None:
    _two_faced(left, right, method, operator)


def test_the_law_answers_every_operator_it_names_from_one_place() -> None:
    """Eight operator names, one law -- so a ninth costs no new arm."""
    for method, operator in (
        ("add", "+"),
        ("subtract", "-"),
        ("multiply", "*"),
        ("divide", "/"),
        ("floor_divide", "//"),
        ("modulo", "%"),
        ("power", "**"),
        ("matrix_multiply", "@"),
        ("bitwise_and", "&"),
        ("bitwise_or", "|"),
        ("bitwise_xor", "^"),
        ("left_shift", "<<"),
        ("right_shift", ">>"),
    ):
        _two_faced(BytesValue(b"x"), _symbolic(), method, operator)


def test_both_operands_are_conserved_in_the_undecided_result() -> None:
    """The result names both operands; no sole TypeError is invented."""
    left = BytesValue(b"ab")
    right = _symbolic()
    done, _ = _two_faced(left, right, "add", "+")
    assert done.value.term.args[1] == left.to_term(owner=SITE)
    assert done.value.term.args[2] == right.to_term(owner=SITE)


# -- the real reproducers: whole functions, lifted from source ---------------


@pytest.mark.parametrize(
    ("name", "source"),
    (
        # pandas/io/stata.py: `b"\x00" * (n - len(name))`
        ("bytes_times_param", 'def f(n):\n    return b"x" * n\n'),
        # pandas/tests/arithmetic/test_string.py
        ("none_plus_call", "def f(g):\n    return None + g()\n"),
        # pandas/io/formats/{excel,html,xml}.py
        ("comp_plus_param", "def f(xs, y):\n    return [x for x in xs] + y\n"),
        # pandas/io/stata.py: `self.sep + want_bytes(x)`
        ("bytes_plus_call", 'def f(g):\n    return b"x" + g()\n'),
        # pandas/core/strings/accessor.py
        ("set_minus_call", "def f(g):\n    return {1, 2} - g()\n"),
    ),
)
def test_the_whole_function_publishes_the_undecided_binary_halt(
    tmp_path, name, source
) -> None:
    """Whole-function construction cannot launder sole completion or TypeError."""
    from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
    from sugar_lift_python_source.source_oracle import path_source
    from sugar_source_tree.tree import SourceFile

    path = tmp_path / f"{name}.py"
    path.write_text(source, encoding="utf-8")

    fn = next(
        SourceFile(
            path_source(str(path)),
            construction_context=TreeConstructionContextV1.for_test_without_workspace(),
        ).functions()
    )
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.outcome.exit_set import Halted

    exits = fn.sugar().desugar(None).exits
    owners = [
        face.effect.producer_node_owner
        for face in exits
        if isinstance(face, Halted) and type(face.effect) is UndeterminedRaiseEffect
    ]
    assert any(owner.startswith("UndecidedBinary:") for owner in owners)
    assert any(not isinstance(face, Halted) for face in exits)


class _FragmentSite:
    """Workspace-relative locus so ground TypeError can mint its halt."""

    filename = "ground-binop-twin.py"
    line = 1
    col = 0
    source = "left + right"
    unit = type("_Unit", (), {"source": "left + right\n"})()


def _assert_ground_type_error(outcome) -> None:
    from sugar_lift_py_tests.effect import RaiseEffect
    assert outcome.halts() == outcome.exits
    (halt,) = outcome.halts()
    assert isinstance(halt.effect, RaiseEffect)
    assert halt.effect.exception_name == "TypeError"


@pytest.mark.parametrize(
    ("left", "right", "method"),
    (
        # Two DECIDED types are a ground question, not an unknown:
        # `list + predicate` is Python's TypeError — an authenticated halt.
        (ListValue((TermValue(1),)), _predicate(), "add"),
        # Predicate does not own addition; still loud construction (not TypeError).
        (_predicate(), TermValue(1), "add"),
        (_predicate(), StringValue("x"), "add"),
        (_comprehension(), SetValue((TermValue(1),)), "subtract"),
    ),
)
def test_two_decided_operands_do_not_invent_coordinates(left, right, method) -> None:
    if type(left) is ListValue and method == "add":
        _assert_ground_type_error(getattr(left, method)(right, _FragmentSite(), None))
        return
    with pytest.raises(ConstructionPanic) as raised:
        getattr(left, method)(right, SITE, None)

    info = raised.value.info
    assert info.owner == method
    assert info.observed == type(left).__name__
    assert type(right).__name__ in info.fix


def test_a_value_that_has_not_testified_stays_loud() -> None:
    """``denotes_value`` defaults to the honest "no": carrying a term is not
    the discriminator, so a class that has not spoken never enters the law."""
    from sugar_lift_py_tests.floor.floor_value import FloorValue

    class _Unspoken(FloorValue):
        def to_term(self, *, owner: str):
            return make_var("unspoken")

    assert _Unspoken().denotes_value() is False

    with pytest.raises(ConstructionPanic) as raised:
        _Unspoken().add(_symbolic(), SITE, None)

    assert raised.value.info.observed == "_Unspoken"


def test_a_term_bearing_callable_never_enters_the_law() -> None:
    """The trap that killed the widening in ``751142009``, pinned on the real
    artifacts rather than a stand-in.

    ``{List,Tuple}Value.contains x CallSiteValue`` was once implemented by
    treating any TERM-BEARING operand as undecided, measured, then reverted:
    ``LambdaCallable`` carries a term too, and two pinned refusals
    (``test_opaque_list_member_stays_loud``, ``test_opaque_member_stays_loud``)
    say a callable is never a member. Carrying a term is not the
    discriminator. Denoting a value is, and this class states nothing, so it
    can never enter the law from either side -- however opaque its operand
    happens to be.
    """
    from sugar_lift_py_tests.floor.lambda_callable import LambdaCallable

    callables = (
        LambdaCallable(parameters=("p",), body=None, construction_identity="lam"),
    )

    for callable_value in callables:
        # It carries a term -- and that buys it nothing.
        assert callable_value.to_term(owner=SITE) is not None
        assert callable_value.denotes_value() is False

        # Refused from the left...
        with pytest.raises(ConstructionPanic) as from_left:
            callable_value.add(_symbolic(), SITE, None)
        assert from_left.value.info.observed == type(callable_value).__name__

        # ...and from the right, where an undecided left operand would
        # otherwise have carried the pair into the law.
        with pytest.raises(ConstructionPanic) as from_right:
            BytesValue(b"x").add(callable_value, SITE, None)
        assert type(callable_value).__name__ in from_right.value.info.fix


def test_a_non_denoting_operand_stays_loud() -> None:
    """A callable is not an operand. The law refuses it from the right too."""
    from sugar_lift_py_tests.floor.floor_value import FloorValue

    class _NotAValue(FloorValue):
        def runtime_type_is_decided(self) -> bool:
            return False

        def to_term(self, *, owner: str):
            return make_var("callable")

    assert _NotAValue().denotes_value() is False

    with pytest.raises(ConstructionPanic) as raised:
        BytesValue(b"x").add(_NotAValue(), SITE, None)

    assert raised.value.info.observed == "BytesValue"
    assert "_NotAValue" in raised.value.info.fix


@pytest.mark.parametrize(
    ("left", "right"),
    (
        (ComplexValue(0.0, 1.0), StringValue("x")),
        (StringValue("x"), ComplexValue(0.0, 1.0)),
    ),
)
def test_a_ground_type_error_is_an_authenticated_raise(left, right) -> None:
    """``1j + "x"`` is Python's ``TypeError`` halt, never a coordinate.

    Both operands have decided runtime types, so the operation is not unknown
    -- it is known to raise. A coordinate would invent an operation that never
    happens; a RuntimeEffect would invent runtime dependence that is not there.
    """
    if type(left) is ComplexValue:
        _assert_ground_type_error(left.add(right, _FragmentSite(), None))
        return
    # String + complex: StringValue.add routes undecided/symbolic peers; a
    # decided ComplexValue right is TypeError on the string addition floor.
    _assert_ground_type_error(left.add(right, _FragmentSite(), None))


def test_the_field_law_is_consulted_before_the_base_law() -> None:
    """The undecided law must not intercept ahead of a ground field law.

    ``ComplexValue.add`` folds through ``complex_arithmetic`` FIRST and only
    falls to ``super()`` on ``None``, so any refusal that law states -- an
    overflow into the float field, a non-finite result that
    ``ComplexValue.to_term`` has no coordinate for -- still runs and still
    decides. Hoisting a coordinate onto the base class did not make the field
    law's guards dead code.

    Asserted by observing the field law actually being reached, including on
    the symbolic pair that this law ultimately answers.
    """
    from sugar_lift_py_tests.floor import complex_arithmetic

    reached: list[tuple[str, str]] = []
    original = complex_arithmetic.complex_add

    def _traced(left, right, site):
        reached.append((type(left).__name__, type(right).__name__))
        return original(left, right, site)

    complex_arithmetic.complex_add = _traced
    try:
        # A pair the field law owns and folds.
        ComplexValue(1.0, 0.0).add(ComplexValue(2.0, 0.0), SITE, None)
        # A pair the field law REFUSES -- it decides, then falls through.
        with pytest.raises(ConstructionPanic):
            TermValue(10**400).add(ComplexValue(0.0, 1.0), SITE, None)
        # The pair this law answers -- the field law still got asked first.
        _two_faced(ComplexValue(0.0, 1.0), _symbolic(), "add", "+")
    finally:
        complex_arithmetic.complex_add = original

    assert reached == [
        ("ComplexValue", "ComplexValue"),
        ("TermValue", "ComplexValue"),
        ("ComplexValue", "SymbolicValue"),
    ]


def test_the_law_never_converts_a_panic_into_two_faces() -> None:
    """A non-denoting right still panics; a decided list+peer is a TypeError halt."""
    with pytest.raises(ConstructionPanic):
        BytesValue(b"x").add(_predicate(), SITE, None)
    _assert_ground_type_error(
        ListValue((TermValue(1),)).add(_predicate(), _FragmentSite(), None)
    )


# -- the testimony is the value's own, never a lexical name ------------------


@pytest.mark.parametrize(
    "undecided",
    (
        SymbolicValue(make_var("s")),
        CallSiteValue("f", (), (), ctor("call:f", []), None),
    ),
)
def test_undecided_values_testify_to_their_own_category(undecided) -> None:
    assert undecided.denotes_value() is True
    assert undecided.runtime_type_is_decided() is False


@pytest.mark.parametrize(
    "ground",
    (
        TermValue(1),
        StringValue("x"),
        BytesValue(b"x"),
        NoneValue(),
        ListValue(()),
        SetValue(()),
        ComplexValue(0.0, 1.0),
    ),
)
def test_ground_values_testify_that_their_type_is_decided(ground) -> None:
    assert ground.denotes_value() is True
    assert ground.runtime_type_is_decided() is True


def test_a_fold_knows_its_own_sequence_type() -> None:
    """A comprehension's constructor names the sequence it builds, so the fold
    alone never makes a pair undecided -- only its operand can."""
    assert _comprehension().denotes_value() is True
    assert _comprehension().runtime_type_is_decided() is True


# -- the law is still HERE ---------------------------------------------------


def test_the_base_class_still_states_the_law() -> None:
    """A merged law has no instrument saying it is still there an hour later.

    #6427 wrote `floor_value.py` wholesale from a base that predated #6415 and
    deleted this law -- the map, both testimony methods, `_undecided_binary_law`
    and the `return` on every binary arm -- with no conflict to review, because
    a whole-file overwrite is not a conflict. Five files lost content and 30
    tests went red on main before anyone looked.

    Those 30 caught it eventually. This one names it in a single assertion, so
    the next overwrite reports "the law is gone" instead of thirty downstream
    symptoms.
    """
    from sugar_lift_py_tests.floor.floor_value import (
        _BINARY_OPERATOR_COORDINATE,
        FloorValue,
    )

    for method in ("denotes_value", "runtime_type_is_decided", "_undecided_binary_law"):
        assert method in vars(FloorValue), f"FloorValue lost {method}"

    # All thirteen operators, keyed by the dispatch surface's own vocabulary.
    assert len(_BINARY_OPERATOR_COORDINATE) == 13


def test_no_value_class_states_testimony_the_base_class_lost() -> None:
    """An override of a method that no longer exists is a silent no-op.

    When #6427 removed the base methods, the per-class `denotes_value`
    overrides survived on eleven value classes -- each one a dead declaration
    that reads as intent. This fires on the orphan directly, so the state
    cannot recur quietly on any class that has spoken or ever will.
    """
    import importlib
    import inspect

    from sugar_lift_py_tests.floor.floor_value import FloorValue

    testimony = ("denotes_value", "runtime_type_is_decided")
    orphaned = []
    for module_name in (
        "bytes_value",
        "call_site_value",
        "complex_value",
        "comprehension_value",
        "dict_value",
        "list_value",
        "none_value",
        "predicate_value",
        "set_value",
        "string_value",
        "symbolic_value",
        "term_value",
        "tuple_value",
    ):
        module = importlib.import_module(f"sugar_lift_py_tests.floor.{module_name}")
        for value in vars(module).values():
            if not (inspect.isclass(value) and issubclass(value, FloorValue)):
                continue
            for method in testimony:
                if method in vars(value) and not hasattr(FloorValue, method):
                    orphaned.append(f"{value.__name__}.{method}")

    assert orphaned == []


def test_the_undecided_pair_is_two_faced_end_to_end() -> None:
    """The one shape that proves the law is wired, not merely present."""
    _two_faced(BytesValue(b"x"), _symbolic(), "add", "+")
