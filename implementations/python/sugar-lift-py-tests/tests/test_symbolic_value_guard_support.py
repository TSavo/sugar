from sugar_lift_py_tests.floor import SymbolicValue
from sugar_lift_py_tests.ir import atomic, make_var


def test_symbolic_support_keeps_one_identity_under_a_guard() -> None:
    value = SymbolicValue(make_var("value"))
    guarded = value.guarded(atomic("path", []))

    assert guarded is value
    assert guarded.to_term(owner="test") == make_var("value")


def test_guard_does_not_become_symbolic_value_content_identity() -> None:
    value = SymbolicValue(make_var("value"))

    assert value.guarded(atomic("left", [])) is value.guarded(atomic("right", []))
    assert value.inv_contribution() == ()
    assert value.post_contribution() == ()


def _completed_member(outcome):
    """The value of the one completed arm of a two-faced attribute read."""
    from sugar_lift_py_tests.outcome import Completed

    (done,) = [arm for arm in outcome.exits if isinstance(arm, Completed)]
    return done.value


def test_symbolic_name_attribute_is_a_coordinate_not_an_invented_string() -> None:
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.ir import ctor
    from sugar_lift_py_tests.outcome import Halted

    value = SymbolicValue(make_var("expected"))
    site = "symbolic-name-attr"
    outcome = value.attribute("__name__", site, None)

    member = _completed_member(outcome)
    assert isinstance(member, CallSiteValue)
    assert member.target_name == "__name__"
    assert member.term == ctor(
        "attr:__name__",
        [value.to_term(owner=str(site))],
        symbol_kind="method-coordinate",
    )
    # The read keeps its raise face: an object need not have a ``__name__``.
    (halt,) = [arm for arm in outcome.exits if isinstance(arm, Halted)]
    assert type(halt.effect) is UndeterminedRaiseEffect
    assert halt.effect.producer_node_owner == "SymbolicValue.attribute"


def test_symbolic_unknown_attribute_stays_undecided() -> None:
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.outcome import Completed, Halted

    value = SymbolicValue(make_var("expected"))
    outcome = value.attribute("not_a_data_model_name", "symbolic-unknown-attr", None)
    (halt,) = [arm for arm in outcome.exits if isinstance(arm, Halted)]
    (done,) = [arm for arm in outcome.exits if isinstance(arm, Completed)]
    assert type(halt.effect) is UndeterminedRaiseEffect
    assert halt.effect.producer_node_owner == "SymbolicValue.attribute"
    assert "not_a_data_model_name" in repr(done.guard)


def test_call_site_name_attribute_is_a_coordinate_not_an_invented_string() -> None:
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.ir import ctor

    receiver = CallSiteValue(
        target_name="__getitem__",
        arg_values=(SymbolicValue(make_var("xs")),),
        parameters=(),
        term=ctor(
            "py.subscript",
            [SymbolicValue(make_var("xs")).to_term(owner="callsite-name")],
            symbol_kind="coordinate",
        ),
        body=None,
        site="callsite-name",
    )
    site = "callsite-name-attr"
    outcome = receiver.attribute("__name__", site, None)

    assert outcome.completed_value() is not None
    assert isinstance(outcome.completed_value(), CallSiteValue)
    assert outcome.completed_value().target_name == "__name__"
    assert outcome.completed_value().term == ctor(
        "attr:__name__",
        [receiver.to_term(owner=str(site))],
        symbol_kind="method-coordinate",
    )


def test_joined_str_names_unground_interpolation_as_an_fstring_coordinate(
    tmp_path,
) -> None:
    from pathlib import Path

    from sugar_lift_py_tests.context import ReduceContext
    from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
    from sugar_lift_py_tests.temporal.builtin_name_bindings import builtin_name_temporal

    path = Path(tmp_path) / "diag.py"
    # ``unknown`` must be a name something may bind, or its read is not an
    # undecided operand at all: a name nothing in the module binds halts with
    # ``NameError`` (``NameSugar``), and the f-string never completes.  A star
    # import the lifter cannot read may bind it, so it is the free operand.
    path.write_text(
        "from elsewhere import *\n"
        'result = f"DID NOT RAISE {unknown.__name__}"\n',
        encoding="utf-8",
    )
    tree = open_source_file_for_construction(
        path,
        root=Path(tmp_path),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    joined = next(node for node in tree.nodes() if node.kind == "JoinedStr")
    ctx = ReduceContext.root(owner="fstring-diag").with_temporal(
        builtin_name_temporal()
    )
    outcome = joined.sugar().desugar(ctx)

    # ``unknown.__name__`` is not a decided builtin, so formatting it runs a
    # ``__format__`` that may be user code: the f-string is the one unanswered
    # call, completing only under its atom and halting undetermined under its
    # complement.  A symbolic receiver's ``__name__`` read is itself the one
    # two-faced undecided read, so its own raise face may stand beside it.
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet, Halted

    assert isinstance(outcome, ExitSet), outcome
    (completed,) = [e for e in outcome.exits if isinstance(e, Completed)]
    halts = [e for e in outcome.exits if isinstance(e, Halted)]
    assert "python:unknown_callee_call.completes" in repr(completed.guard)
    assert all(isinstance(halt.effect, UndeterminedRaiseEffect) for halt in halts)
    owners = {halt.effect.producer_node_owner for halt in halts}
    assert "UnknownCallee:format" in owners
    assert owners <= {"UnknownCallee:format", "SymbolicValue.attribute"}
    assert isinstance(completed.value, CallSiteValue)
    assert getattr(completed.value.term, "name", None) == "python:fstring"


def test_type_call_result_is_a_type_object() -> None:
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.ir import ctor, str_const
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    term = ctor(
        "call:type",
        [SymbolicValue(make_var("exc")).to_term(owner="type-call")],
        symbol_kind="builtin",
    )
    # The builtin binding's citation (``python_type_coordinate``), never the
    # spelling ``type``, is what makes the result a type object.
    spelled = CallSiteValue(
        target_name="type",
        arg_values=(SymbolicValue(make_var("exc")),),
        parameters=(),
        term=term,
        body=None,
        site="type-call",
    )
    assert not isinstance(
        spelled.python_isinstance(
            "type", ctor("python:type", [str_const("type")]), "site"
        ).completed_value(),
        TrueBoolLiteralSugar,
    )
    result = CallSiteValue(
        target_name="type",
        arg_values=(SymbolicValue(make_var("exc")),),
        parameters=(),
        term=term,
        body=None,
        site="type-call",
        python_type_coordinate=term,
    )

    as_type = result.python_isinstance(
        "type", ctor("python:type", [str_const("type")]), "site"
    )
    assert as_type.completed_value() is not None
    assert isinstance(as_type.completed_value(), TrueBoolLiteralSugar)

    as_tuple = result.python_isinstance(
        "tuple", ctor("python:type", [str_const("tuple")]), "site"
    )
    assert as_tuple.completed_value() is not None
    assert isinstance(as_tuple.completed_value(), FalseBoolLiteralSugar)


def _name_attribute_callsite():
    """``exc_type.__name__`` as the attribute read mints it (its marker,
    ``type_name_attribute``), never a hand-spelled ``attr:__name__`` term."""
    receiver = SymbolicValue(make_var("exc_type"))
    name = _completed_member(receiver.attribute("__name__", "name-attr", None))
    assert name.type_name_attribute
    return name


def test_name_attribute_plus_string_is_a_concat_coordinate_not_an_invented_string() -> None:
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.floor.string_value import StringValue
    from sugar_lift_py_tests.ir import ctor

    name = _name_attribute_callsite()
    suffix = StringValue("()")
    site = "name-plus-string"
    outcome = name.add(suffix, site, None)

    assert outcome.completed_value() is not None
    assert isinstance(outcome.completed_value(), CallSiteValue)
    assert not isinstance(outcome.completed_value(), StringValue)
    assert outcome.completed_value().target_name == "__add__"
    assert outcome.completed_value().term == ctor(
        "call:__add__",
        [
            name.to_term(owner="CallSiteValue.named_string_concat"),
            suffix.to_term(owner="CallSiteValue.named_string_concat"),
        ],
        symbol_kind="coordinate",
    )


def test_string_plus_name_attribute_is_a_concat_coordinate_not_an_invented_string() -> None:
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.floor.string_value import StringValue
    from sugar_lift_py_tests.ir import ctor

    name = _name_attribute_callsite()
    prefix = StringValue("`")
    site = "string-plus-name"
    outcome = prefix.add(name, site, None)

    assert outcome.completed_value() is not None
    assert isinstance(outcome.completed_value(), CallSiteValue)
    assert not isinstance(outcome.completed_value(), StringValue)
    assert outcome.completed_value().target_name == "__add__"
    assert outcome.completed_value().term == ctor(
        "call:__add__",
        [
            prefix.to_term(owner="CallSiteValue.named_string_concat"),
            name.to_term(owner="CallSiteValue.named_string_concat"),
        ],
        symbol_kind="coordinate",
    )



def test_backquote_joins_a_named_concat_without_inventing_the_string() -> None:
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.floor.string_value import StringValue
    from sugar_lift_py_tests.ir import ctor

    name = _name_attribute_callsite()
    inner = name.add(StringValue("()"), "inner", None)
    assert inner.completed_value() is not None
    prefixed = StringValue("`").add(inner.completed_value(), "prefix", None)
    assert prefixed.completed_value() is not None
    assert isinstance(prefixed.completed_value(), CallSiteValue)
    assert not isinstance(prefixed.completed_value(), StringValue)
    wrapped = prefixed.completed_value().add(StringValue("`"), "suffix", None)
    assert wrapped.completed_value() is not None
    assert isinstance(wrapped.completed_value(), CallSiteValue)
    assert not isinstance(wrapped.completed_value(), StringValue)
    assert wrapped.completed_value().target_name == "__add__"
    assert getattr(wrapped.completed_value().term, "name", None) == "call:__add__"
    assert wrapped.completed_value().term == ctor(
        "call:__add__",
        [
            prefixed.completed_value().to_term(owner="CallSiteValue.named_string_concat"),
            StringValue("`").to_term(owner="CallSiteValue.named_string_concat"),
        ],
        symbol_kind="coordinate",
    )



def test_string_plus_join_callsite_is_a_concat_coordinate_not_an_invented_string() -> None:
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.floor.opaque_op_callsite import OpaqueOpCallsite
    from sugar_lift_py_tests.floor.string_value import StringValue
    from sugar_lift_py_tests.ir import ctor
    from sugar_source_tree.nodes import LanguageCallee

    join = OpaqueOpCallsite(
        callee="join",
        arg=StringValue(", "),
        computed=None,
        extra_args=(SymbolicValue(make_var("names")),),
        language_callee=LanguageCallee.STR_JOIN,
    )
    prefix = StringValue("(")
    site = "string-plus-join"
    outcome = prefix.add(join, site, None)

    assert outcome.completed_value() is not None
    assert isinstance(outcome.completed_value(), CallSiteValue)
    assert not isinstance(outcome.completed_value(), StringValue)
    assert outcome.completed_value().target_name == "__add__"
    assert outcome.completed_value().term == ctor(
        "call:__add__",
        [
            prefix.to_term(owner="CallSiteValue.named_string_concat"),
            join.to_term(owner="CallSiteValue.named_string_concat"),
        ],
        symbol_kind="coordinate",
    )

    wrapped = outcome.completed_value().add(StringValue(")"), "join-plus-suffix", None)
    assert wrapped.completed_value() is not None
    assert isinstance(wrapped.completed_value(), CallSiteValue)
    assert not isinstance(wrapped.completed_value(), StringValue)
    assert getattr(wrapped.completed_value().term, "name", None) == "call:__add__"


def test_str_join_coordinate_is_known_by_its_callee_never_its_spelling() -> None:
    """The join coordinate the string fold mints carries ``STR_JOIN``; a
    coordinate merely spelled ``join`` (no decided callee) is not named a
    string concatenation (#7757)."""
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.floor.opaque_op_callsite import OpaqueOpCallsite
    from sugar_lift_py_tests.floor.string_value import (
        StringValue,
        _fold_string_method,
    )
    from sugar_source_tree.nodes import LanguageCallee

    class _Join:
        name = "join"
        arguments = (SymbolicValue(make_var("names")),)
        blame = "fold-join"

    minted = _fold_string_method(StringValue(", "), _Join()).completed_value()
    assert type(minted) is OpaqueOpCallsite
    assert minted.language_callee is LanguageCallee.STR_JOIN

    spelled = OpaqueOpCallsite(
        callee="join",
        arg=StringValue(", "),
        computed=None,
        extra_args=(SymbolicValue(make_var("names")),),
    )
    from sugar_source_tree.panic import SugarNotWritten

    try:
        outcome = StringValue("(").add(spelled, "spelled-join", None)
    except SugarNotWritten:
        return  # refused by name: not a string concatenation either
    assert not any(
        isinstance(getattr(face, "value", None), CallSiteValue)
        for face in outcome.exits
    )


def _two_arm_method_callsite():
    """A source-backed method whose body reduces to two completed faces.

    ``RaisesExc._check_type`` / ``matches`` partitions on the constructor wrap
    and both arms return predicates; dig must not invent one bool.
    """
    from dataclasses import dataclass

    from sugar_lift_py_tests.claim import SugarRole
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.floor.predicate_value import PredicateValue
    from sugar_lift_py_tests.ir import atomic, ctor
    from sugar_lift_py_tests.outcome import ExitSet
    from sugar_lift_py_tests.outcome.exit_set import Completed
    from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
    from sugar_lift_py_tests.sugar_body import SugarBody

    @dataclass
    class _Body(ConstructedTermSugar):
        @classmethod
        def witnesses(cls):
            return None

        def desugar(self, ctx=None):
            del ctx
            return ExitSet(
                (
                    Completed(atomic("then", []), PredicateValue(atomic("ok", []), "then")),
                    Completed(
                        atomic("else_face", []),
                        PredicateValue(atomic("no", []), "else"),
                    ),
                )
            )

        def to_term(self, *, owner: str):
            del owner
            return ctor("test:two-arm-method", ())

    return CallSiteValue(
        target_name="RaisesExc.matches",
        arg_values=(),
        parameters=(),
        term=ctor("call:RaisesExc.matches", ()),
        body=SugarBody(_Body(), SugarRole.CONTROL_FLOW_BODY),
        site="two-arm-matches",
        source_call_frame_cid="blake3-512:" + "7" * 128,
    )


def _negated_truth_standing_on_the_call(outcome):
    """The negated truth ``not <call>`` states, read off its completed arm.

    The call's body is not dug to one value, so the truth of its result is
    not decided here: taking it is two-faced (``bool_op_sugar.truth_of``).  It
    completes under its own ``python:truth.completes`` atom with the negation
    of the undecided ``py.truthy(<call>)``, or the truth test itself raises
    something undetermined (the result's ``__bool__`` may be user code).
    Exactly those two arms; never an unconditional completion."""
    from sugar_lift_py_tests.effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.floor.predicate_value import PredicateValue
    from sugar_lift_py_tests.outcome import Completed

    assert outcome.completed_value() is None
    (completed,) = [face for face in outcome.exits if isinstance(face, Completed)]
    (halted,) = outcome.halts()
    assert completed.guard.name == "python:truth.completes"
    assert isinstance(halted.effect, UndeterminedRaiseEffect)
    assert halted.effect.producer_node_owner == "UnaryOpSugar.not"
    assert isinstance(completed.value, PredicateValue)
    return completed.value.formula


def test_dig_leaves_a_two_arm_method_body_absent() -> None:
    callsite = _two_arm_method_callsite()
    dug = callsite._dig_floor_or_none(None, owner="UnaryOpSugar.not method body")
    assert dug is None


def test_not_of_a_two_arm_method_body_stands_on_the_call() -> None:
    from dataclasses import dataclass

    from sugar_lift_py_tests.floor.predicate_value import PredicateValue
    from sugar_lift_py_tests.ir import ctor
    from sugar_lift_py_tests.outcome import ExitSet
    from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
    from sugar_lift_py_tests.sugar.unary_op_sugar import UnaryOpSugar

    callsite = _two_arm_method_callsite()

    @dataclass
    class _Yield(ConstructedTermSugar):
        value: object

        @classmethod
        def witnesses(cls):
            return None

        def desugar(self, ctx=None):
            del ctx
            return ExitSet.completed(self.value)

        def to_term(self, *, owner: str):
            return self.value.to_term(owner=owner)

    outcome = UnaryOpSugar("Not", _Yield(callsite), "not-two-arm").desugar(None)
    negated = _negated_truth_standing_on_the_call(outcome)
    assert "truthy" in str(negated)
    assert "call:RaisesExc.matches" in str(negated)


def _deferred_lookup_method_callsite():
    """A source-backed method whose body is an undischarged ``exc.message`` lookup."""
    from dataclasses import dataclass

    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )
    from sugar_lift_py_tests.claim import SugarRole
    from sugar_lift_py_tests.floor import StringValue
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.floor.manager_coordinate import ExitValueCoordinate
    from sugar_lift_py_tests.ir import ctor
    from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
    from sugar_lift_py_tests.sugar_body import SugarBody

    from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_source_tree.tree import SourceFile

    source = "effect.message\n"
    tree = SourceFile(
        (source, "deferred-lookup.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    site = next(node for node in tree.nodes() if node.kind == "Attribute").fragment
    coordinate = ExitValueCoordinate("not-message-face")

    @dataclass
    class _Body(ConstructedTermSugar):
        @classmethod
        def witnesses(cls):
            return None

        def desugar(self, ctx=None):
            del ctx
            return NativeOperationExitCarrierV1.mint(
                site=site,
                operator="attribute_named",
                operands=(coordinate, StringValue("message")),
                coordinates=(coordinate, None),
            )

        def to_term(self, *, owner: str):
            del owner
            return ctor("test:deferred-lookup-method", ())

    return CallSiteValue(
        target_name="stringify",
        arg_values=(),
        parameters=(),
        term=ctor("call:stringify", ()),
        body=SugarBody(_Body(), SugarRole.CONTROL_FLOW_BODY),
        site="deferred-lookup",
        source_call_frame_cid="blake3-512:" + "8" * 128,
    )


def test_dig_leaves_a_deferred_lookup_method_body_absent() -> None:
    callsite = _deferred_lookup_method_callsite()
    dug = callsite._dig_floor_or_none(None, owner="UnaryOpSugar.not method body")
    assert dug is None


def test_not_of_a_deferred_lookup_method_body_stands_on_the_call() -> None:
    from dataclasses import dataclass

    from sugar_lift_py_tests.floor.predicate_value import PredicateValue
    from sugar_lift_py_tests.ir import ctor
    from sugar_lift_py_tests.outcome import ExitSet
    from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
    from sugar_lift_py_tests.sugar.unary_op_sugar import UnaryOpSugar

    callsite = _deferred_lookup_method_callsite()

    @dataclass
    class _Yield(ConstructedTermSugar):
        value: object

        @classmethod
        def witnesses(cls):
            return None

        def desugar(self, ctx=None):
            del ctx
            return ExitSet.completed(self.value)

        def to_term(self, *, owner: str):
            return self.value.to_term(owner=owner)

    outcome = UnaryOpSugar("Not", _Yield(callsite), "not-deferred-lookup").desugar(None)
    negated = _negated_truth_standing_on_the_call(outcome)
    assert "truthy" in str(negated)
    assert "call:stringify" in str(negated)


def _multi_return_block_method_callsite():
    """A source-backed method whose reduced body is an unprojectable block.

    ``RaisesExc.matches`` retains several GuardedReturns (early ``return False``
    arms and ``return self._check_check(...)``), not one authenticated return.
    """
    from dataclasses import dataclass

    from sugar_lift_py_tests.claim import SugarRole
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.floor.floor_value import FloorValue
    from sugar_lift_py_tests.floor.guarded_return import GuardedReturn
    from sugar_lift_py_tests.floor.predicate_value import PredicateValue
    from sugar_lift_py_tests.ir import atomic, ctor
    from sugar_lift_py_tests.outcome import ExitSet
    from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
    from sugar_lift_py_tests.sugar_body import SugarBody

    block = BlockValue(
        statements=(
            GuardedReturn(
                guards=(atomic("type_mismatch", []),),
                value=PredicateValue(atomic("false", []), "false-arm"),
            ),
            GuardedReturn(
                guards=(atomic("check_check", []),),
                value=CallSiteValue(
                    target_name="RaisesExc._check_check",
                    arg_values=(),
                    parameters=(),
                    term=ctor("call:RaisesExc._check_check", ()),
                    body=None,
                    site="check-check",
                ),
            ),
        ),
        fall_through=(),
        can_fall_through=False,
    )

    @dataclass
    class _Body(ConstructedTermSugar):
        value: FloorValue

        @classmethod
        def witnesses(cls):
            return None

        def desugar(self, ctx=None):
            del ctx
            return ExitSet.completed(self.value)

        def to_term(self, *, owner: str):
            del owner
            return ctor("test:multi-return-block", ())

    return CallSiteValue(
        target_name="RaisesExc.matches",
        arg_values=(),
        parameters=(),
        term=ctor("call:RaisesExc.matches", ()),
        body=SugarBody(_Body(block), SugarRole.CONTROL_FLOW_BODY),
        site="multi-return-matches",
        source_call_frame_cid="blake3-512:" + "7" * 128,
    )


def test_dig_leaves_a_multi_return_block_absent() -> None:
    callsite = _multi_return_block_method_callsite()
    dug = callsite._dig_floor_or_none(None, owner="UnaryOpSugar.not method body")
    assert dug is None


def test_not_of_a_multi_return_block_stands_on_the_call() -> None:
    from dataclasses import dataclass

    from sugar_lift_py_tests.floor.predicate_value import PredicateValue
    from sugar_lift_py_tests.outcome import ExitSet
    from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
    from sugar_lift_py_tests.sugar.unary_op_sugar import UnaryOpSugar

    callsite = _multi_return_block_method_callsite()

    @dataclass
    class _Yield(ConstructedTermSugar):
        value: object

        @classmethod
        def witnesses(cls):
            return None

        def desugar(self, ctx=None):
            del ctx
            return ExitSet.completed(self.value)

        def to_term(self, *, owner: str):
            return self.value.to_term(owner=owner)

    outcome = UnaryOpSugar("Not", _Yield(callsite), "not-multi-return").desugar(None)
    negated = _negated_truth_standing_on_the_call(outcome)
    assert "truthy" in str(negated)
    assert "call:RaisesExc.matches" in str(negated)

