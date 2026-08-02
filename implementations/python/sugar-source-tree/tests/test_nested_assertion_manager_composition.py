"""Nested assertion managers compose in source order without vendor authority."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from types import MappingProxyType

from sugar_lift_py_tests.effect.authenticated_raise_locus import AuthenticatedRaiseLocus
from sugar_lift_py_tests.context_manager_contract import (
    CallParameterV1,
    EffectBoundarySemanticsV1,
    EnterResultContractV1,
    ExceptionInfoBindingV1,
    ExitContractV1,
    ExpectsModeV1,
    FormalArgumentProjectionV1,
    KeywordOnlyV1,
    LiteralDefaultV1,
    NeverSuppressesDispositionV1,
    NoDefaultV1,
    OptionalFormalArgumentProjectionV1,
    PositionalOrKeywordV1,
    ProtocolResourceSemanticsV1,
    RaiseEffectKindV1,
    WarningEffectKindV1,
    WarningObservationBindingV1,
)
from sugar_lift_py_tests.context_manager_resolution import (
    ContextManagerContractRefV1,
    ImportSignatureV2,
    ResolvedContractRefsV1,
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
    _hash_json,
)
from sugar_lift_py_tests.floor import CallSiteValue, StringValue
from sugar_lift_py_tests.floor.authenticated_exception_type_value import (
    AuthenticatedExceptionTypeValue,
)
from sugar_lift_py_tests.ir import PrimitiveSort
from sugar_lift_py_tests.sugar.with_effect_boundary_sugar import WithEffectBoundarySugar
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.with_resource_sugar import WithResourceSugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile


SOURCE = (
    "from dependency import halting, observing\n"
    "def f():\n"
    '    msg = "unsupported operand type.+for &:"\n'
    '    warn_msg = "deprecated operand"\n'
    "    with halting(TypeError, match=msg):\n"
    "        with observing(FutureWarning, match=warn_msg):\n"
    '            raise TypeError("unsupported operand type for &:")\n'
)

STRESS_SOURCE = (
    "from dependency import observing, halting\n"
    "def f(using_feature):\n"
    "    from dependency import pa\n"
    "    warn = FutureWarning if using_feature else None\n"
    "    if using_feature:\n"
    '        with observing(warn, match="Operation between non"):\n'
    "            with halting(\n"
    "                pa.lib.ArrowNotImplementedError, match=\"has no kernel\"\n"
    "            ):\n"
    '                raise pa.lib.ArrowNotImplementedError("has no kernel")\n'
)

SIGNATURE = ImportSignatureV2(
    (
        CallParameterV1(
            "expected",
            PrimitiveSort("Value"),
            PositionalOrKeywordV1(),
            True,
            NoDefaultV1(),
        ),
        CallParameterV1(
            "match",
            PrimitiveSort("String"),
            KeywordOnlyV1(),
            False,
            LiteralDefaultV1({"kind": "ctor", "name": "None", "args": []}),
        ),
    )
)


def _cid(char: str) -> str:
    return "blake3-512:" + char * 128


def _coordinate(node) -> SourceFragmentCoordinateV1:
    span = node.line_col_span()
    return SourceFragmentCoordinateV1(
        node.unit.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )


def _ref(use_site, semantics, salt: str) -> ContextManagerContractRefV1:
    return ContextManagerContractRefV1(
        resolution_cid=_cid(salt),
        demand_cid=_cid("d"),
        use_site=use_site,
        use_site_cid=_hash_json(use_site.wire()),
        authenticated_import_use_cid=_cid("u"),
        import_binding_cid=_cid("i"),
        construction_context_generation_cid=_cid("g"),
        contract_cid=_cid("m"),
        payload_cid=_cid("p"),
        provenance_cid=_cid("v"),
        distribution_artifact_cid=_cid("a"),
        dependency_artifact_graph_cid=_cid("b"),
        module_source_cid=_cid("s"),
        resolved_definition_cid=_cid("f"),
        manager_construction_cid=_cid("n"),
        enter_testimony_cid=_cid("1"),
        exit_testimony_cid=_cid("2"),
        import_signature=SIGNATURE,
        semantics=semantics,
    )


def _resource_ref(use_site, salt: str) -> ContextManagerContractRefV1:
    return _ref(
        use_site,
        ProtocolResourceSemanticsV1(
            enter=EnterResultContractV1(sort=PrimitiveSort("Value")),
            exit=ExitContractV1(disposition=NeverSuppressesDispositionV1()),
        ),
        salt,
    )


def _constructed_boundaries(tmp_path, source=SOURCE, *, warning_first=False):
    path = tmp_path / "renamed.py"
    path.write_text(source, encoding="utf-8")
    identity = path_source(str(path))
    probe = SourceFile(identity)
    with_nodes = [node for node in probe.nodes() if node.kind == "With"]
    assert len(with_nodes) == 2
    coordinates = [_coordinate(node.items[0].context_expr) for node in with_nodes]
    raise_semantics = EffectBoundarySemanticsV1(
        ExpectsModeV1(),
        RaiseEffectKindV1(),
        FormalArgumentProjectionV1(0),
        OptionalFormalArgumentProjectionV1(1),
        ExceptionInfoBindingV1(),
    )
    warning_semantics = EffectBoundarySemanticsV1(
        ExpectsModeV1(),
        WarningEffectKindV1(),
        FormalArgumentProjectionV1(0),
        OptionalFormalArgumentProjectionV1(1),
        WarningObservationBindingV1(),
    )
    semantics = (
        (warning_semantics, raise_semantics)
        if warning_first
        else (raise_semantics, warning_semantics)
    )
    rows = {
        coordinate: _ref(coordinate, selected, salt)
        for coordinate, selected, salt in zip(
            coordinates, semantics, ("r", "q"), strict=True
        )
    }
    context = TreeConstructionContextV1(
        ResolvedContractRefsV1(
            _cid("c"), _cid("t"), MappingProxyType(rows)
        )
    )
    function = next(SourceFile(identity, construction_context=context).functions())
    sugar = function.sugar()
    boundaries = []

    def walk(node):
        if isinstance(node, WithEffectBoundarySugar):
            boundaries.append(node)
        for field in (
            "body",
            "statements",
            "entries",
            "then_body",
            "else_body",
        ):
            for child in getattr(node, field, ()) or ():
                walk(child)

    walk(sugar)
    return tuple(boundaries)


def test_variable_patterns_reach_both_nested_boundaries(tmp_path):
    """Truthful: Assign substitution supplies both real ``match=`` operands."""
    outer, inner = _constructed_boundaries(tmp_path)
    outer_call = outer.manager.desugar().value
    inner_call = inner.manager.desugar().value
    assert isinstance(outer_call, CallSiteValue)
    assert isinstance(inner_call, CallSiteValue)
    assert outer_call.arg_values[-1] == StringValue("unsupported operand type.+for &:")
    assert inner_call.arg_values[-1] == StringValue("deprecated operand")


def test_lying_variable_patterns_do_not_alias_between_boundaries(tmp_path):
    """Lying: swapped expectations must fail; the two bindings stay distinct."""
    outer, inner = _constructed_boundaries(tmp_path)
    outer_pattern = outer.manager.desugar().value.arg_values[-1]
    inner_pattern = inner.manager.desugar().value.arg_values[-1]
    assert outer_pattern != inner_pattern


def test_reverse_order_branch_constructs_both_native_boundaries(tmp_path):
    """The stress shape stays source-ordered under a branch and local import."""
    outer, inner = _constructed_boundaries(
        tmp_path, STRESS_SOURCE, warning_first=True
    )
    assert isinstance(outer.semantics.effect_kind, WarningEffectKindV1)
    assert isinstance(inner.semantics.effect_kind, RaiseEffectKindV1)
    assert outer.manager.desugar().value.arg_values[-1] == StringValue(
        "Operation between non"
    )
    inner_call = inner.manager.desugar().value
    assert isinstance(inner_call.arg_values[0], AuthenticatedExceptionTypeValue)
    assert inner_call.arg_values[-1] == StringValue(
        "has no kernel"
    )


def test_reassigned_local_import_head_has_no_exception_identity(tmp_path):
    """Lying: an intervening assignment defeats the import coordinate."""
    source = STRESS_SOURCE.replace(
        "    warn = FutureWarning if using_feature else None\n",
        "    pa = replacement\n"
        "    warn = FutureWarning if using_feature else None\n",
    )
    path = tmp_path / "shadowed.py"
    path.write_text(source, encoding="utf-8")
    tree = SourceFile(path_source(str(path)))
    expected = next(
        node
        for node in tree.nodes()
        if node.kind == "Attribute" and node.attr == "ArrowNotImplementedError"
    )
    assert tree.root.unit.imported_exception_type_identity(expected) is None


def _pinned_pandas_root() -> Path:
    from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus

    return authenticated_pandas_corpus().root
PINNED_DATETIMELIKE_CID = (
    "blake3-512:a8a3afcef87a93452db841a304673c4bca0a52e29e5a63932580a3b638f39300"
    "2003a95d615bfd1bec91d03c90f792b2600a007f5e5c98120c8ca56bb8b79f00"
)
PINNED_INVALID_ARG_CID = (
    "blake3-512:1a2b00ed9faeb66823b5bf57d534f5ec309cdf5201045bf43b199fabd931e597f"
    "f0d207c885c936577ec06e599da93a29f8497c97c1e03b94f3224923e997889"
)
PINNED_IO_COMMON_CID = (
    "blake3-512:bb8ffaae9d8a417b4054f7688905c4eb405c54ec80fe72daa62ba8394b2fde393"
    "9e11e9ea25977d357b872820e3e46f6c8c267e7be3cf09889dbb9f04b83a3a9"
)
PINNED_ERRORS_CID = (
    "blake3-512:e0c0e46661f4028ee20659af69bba7b9f87b047b6b1126491bfd5d5c941119c1"
    "113df8ed9daeb5413832a45b7434689a4768068013d513dc0f634e683b212a33"
)


def _pinned_identity(relative_path: str, expected_cid: str):
    root = _pinned_pandas_root()
    path = root / relative_path
    source = path.read_bytes()
    source_cid = blake3_512_of(source)
    assert source_cid == expected_cid
    return source.decode("utf-8"), str(path), source_cid


def _raise_semantics():
    return EffectBoundarySemanticsV1(
        ExpectsModeV1(),
        RaiseEffectKindV1(),
        FormalArgumentProjectionV1(0),
        OptionalFormalArgumentProjectionV1(1),
        ExceptionInfoBindingV1(),
    )


def _warning_semantics():
    return EffectBoundarySemanticsV1(
        ExpectsModeV1(),
        WarningEffectKindV1(),
        FormalArgumentProjectionV1(0),
        OptionalFormalArgumentProjectionV1(1),
        WarningObservationBindingV1(),
    )


def _built_function(identity, name, rows):
    context = TreeConstructionContextV1(
        ResolvedContractRefsV1(_cid("c"), _cid("t"), MappingProxyType(rows))
    )
    return next(
        node
        for node in SourceFile(identity, construction_context=context).functions()
        if node.name == name
    ).sugar()


def _with_routers(sugar):
    routers = []

    def walk(node):
        if isinstance(node, (WithEffectBoundarySugar, WithResourceSugar)):
            routers.append(node)
        for field in ("body", "statements", "entries", "then_body", "else_body"):
            for child in getattr(node, field, ()) or ():
                walk(child)

    walk(sugar)
    return tuple(routers)


def _real_three_deep_assertion_resource_chain():
    identity = _pinned_identity("tests/io/test_common.py", PINNED_IO_COMMON_CID)
    probe = SourceFile(identity)
    function = next(node for node in probe.functions() if node.name == "test_close_on_error")
    with_nodes = sorted(
        (node for node in function.walk() if node.kind == "With"),
        key=lambda node: node.line_col_span().start_line,
    )
    assert [node.line_col_span().start_line for node in with_nodes] == [638, 639, 640]
    rows = {}
    for index, node in enumerate(with_nodes):
        coordinate = _coordinate(node.items[0].context_expr)
        rows[coordinate] = (
            _ref(coordinate, _raise_semantics(), "h")
            if index == 0
            else _resource_ref(coordinate, str(index))
        )
    return _with_routers(_built_function(identity, function.name, rows))


def _real_juxtaposed_assertion_resource_chain():
    identity = _pinned_identity("tests/test_errors.py", PINNED_ERRORS_CID)
    probe = SourceFile(identity)
    function = next(
        node for node in probe.functions() if node.name == "test_pandas_warnings_filter"
    )
    with_nodes = [node for node in function.walk() if node.kind == "With"]
    assert len(with_nodes) == 1
    node = with_nodes[0]
    assert node.line_col_span().start_line == 142
    assert len(node.items) == 2
    first = _coordinate(node.items[0].context_expr)
    second = _coordinate(node.items[1].context_expr)
    rows = {
        first: _ref(first, _warning_semantics(), "w"),
        second: _resource_ref(second, "z"),
    }
    return _with_routers(_built_function(identity, function.name, rows))


def test_pinned_three_deep_assertion_over_two_resources_preserves_source_order():
    """Truthful: the subject manager stays inside both outer boundaries."""
    outer, middle, inner = _real_three_deep_assertion_resource_chain()
    assert isinstance(outer, WithEffectBoundarySugar)
    assert isinstance(middle, WithResourceSugar)
    assert isinstance(inner, WithResourceSugar)
    assert middle in outer.body
    assert inner in middle.body


def test_pinned_three_deep_chain_cannot_move_the_assertion_inside_cleanup():
    """Lying: contract kind cannot reorder authenticated source occurrences."""
    outer, middle, inner = _real_three_deep_assertion_resource_chain()
    assert not isinstance(outer, WithResourceSugar)
    assert not isinstance(middle, WithEffectBoundarySugar)
    assert not isinstance(inner, WithEffectBoundarySugar)


class _FixedOutcomeSugar(Sugar):
    """One test seam for exercising the routers built from the pinned source."""

    def __init__(self, outcome, *, probe=None):
        self.outcome = outcome
        self.probe = probe

    def desugar(self, ctx=None):
        del ctx
        if self.probe is not None:
            self.probe.append(1)
        return self.outcome

    @classmethod
    def witnesses(cls):
        return ()


def _three_deep_manager_halt(exception_name: str):
    """Route an innermost construction halt through the same three routers."""
    from sugar_lift_py_tests.effect import RaiseEffect
    from sugar_lift_py_tests.ir import ctor, str_const
    from sugar_lift_py_tests.outcome import Complete, Incomplete

    source = (
        "def test_close_on_error():\n"
        "    with boundary(OSError):\n"
        "        with bytes_io() as buffer:\n"
        "            with get_handle(buffer) as handles:\n"
        "                pass\n"
    )
    identity = (source, "test_common_three_deep.py", blake3_512_of(source.encode()))
    probe = SourceFile(identity)
    with_nodes = sorted(
        (node for node in probe.nodes() if node.kind == "With"),
        key=lambda node: node.line_col_span().start_line,
    )
    rows = {}
    for index, node in enumerate(with_nodes):
        coordinate = _coordinate(node.items[0].context_expr)
        rows[coordinate] = (
            _ref(coordinate, _raise_semantics(), "h")
            if index == 0
            else _resource_ref(coordinate, str(index))
        )
    outer, middle, inner = _with_routers(
        _built_function(identity, "test_close_on_error", rows)
    )
    original_middle = middle
    original_inner = inner
    middle_exit, inner_enter, inner_exit = [], [], []
    effect = RaiseEffect(exception_type_coordinate=ctor('python:exception_type_identity', [str_const('builtins'), str_const(exception_name)]), occurrence=AuthenticatedRaiseLocus.of('test_common.py:640'), exception_name=exception_name)
    inner = replace(
        inner,
        manager=_FixedOutcomeSugar(Incomplete(effect)),
        enter=_FixedOutcomeSugar(
            Complete(StringValue("inner-enter")), probe=inner_enter
        ),
        exit=_FixedOutcomeSugar(Complete(StringValue("inner-exit")), probe=inner_exit),
    )
    middle = replace(
        middle,
        manager=_FixedOutcomeSugar(Complete(StringValue("bytes-io"))),
        enter=_FixedOutcomeSugar(Complete(StringValue("buffer"))),
        exit=_FixedOutcomeSugar(
            Complete(StringValue("bytes-io-exit")), probe=middle_exit
        ),
        body=tuple(
            inner if child is original_inner else child for child in middle.body
        ),
    )
    outer = replace(
        outer,
        body=tuple(
            middle if child is original_middle else child for child in outer.body
        ),
    )
    return outer.desugar(), middle_exit, inner_enter, inner_exit


@dataclass(frozen=True)
class _LevelRoutingReceipt:
    level: str
    effect: object
    attribution: object
    consumed: bool
    passed: bool

    @property
    def authenticated_exceptional_exits(self) -> int:
        from sugar_lift_py_tests.no_call_body_attribution import AttributionOutcome

        return int(self.attribution is AttributionOutcome.AUTHENTICATED_EXIT)

    @property
    def named_refusals(self) -> int:
        from sugar_lift_py_tests.no_call_body_attribution import AttributionOutcome

        return int(self.attribution is AttributionOutcome.NAMED_REFUSAL)

    @property
    def construction_panics(self) -> int:
        from sugar_lift_py_tests.no_call_body_attribution import AttributionOutcome

        return int(self.attribution is AttributionOutcome.CONSTRUCTION_PANIC)


def _account_level(level: str, effect, evaluate):
    """Account one incoming edge without reconstructing its identity."""
    from sugar_lift_py_tests.gap.panic import ConstructionPanic
    from sugar_lift_py_tests.no_call_body_attribution import AttributionOutcome
    from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
    from sugar_lift_py_tests.sugar.exit_set_routing import promote_raise_halts
    from sugar_lift_py_tests.sugar.function_universe_sugar import (
        reduce_block_to_exitset,
    )
    from sugar_source_tree.panic import SugarNotWritten

    try:
        outcome = evaluate()
    except SugarNotWritten:
        return (
            _LevelRoutingReceipt(
                level, effect, AttributionOutcome.NAMED_REFUSAL, False, False
            ),
            None,
        )
    except ConstructionPanic:
        return (
            _LevelRoutingReceipt(
                level, effect, AttributionOutcome.CONSTRUCTION_PANIC, False, False
            ),
            None,
        )

    # Observe the exact projection the next enclosing boundary consumes. The
    # linear Outcome adapter may carry a hard raise inside BlockValue; routing
    # sees it only after the ordinary block reduction promotes that native
    # entry back to a Halted ExitSet face.
    exits = (
        promote_raise_halts(outcome)
        if isinstance(outcome, ExitSet)
        else promote_raise_halts(
            reduce_block_to_exitset((_FixedOutcomeSugar(outcome),), None)
        )
    )
    passed = any(
        isinstance(face, Halted) and face.effect is effect for face in exits.exits
    )
    completed = any(isinstance(face, Completed) for face in exits.exits)
    if passed and completed:
        raise AssertionError(
            f"{level} duplicated the incoming edge into a completed arm: {exits!r}"
        )
    consumed = not passed and completed
    if consumed == passed:
        raise AssertionError(
            f"{level} must consume or pass the exact incoming edge once: {exits!r}"
        )
    return (
        _LevelRoutingReceipt(
            level, effect, AttributionOutcome.AUTHENTICATED_EXIT, consumed, passed
        ),
        outcome,
    )


def _three_deep_level_receipts(exception_name: str):
    """Expose the pinned chain's ExitSet after each source-ordered router."""
    from sugar_lift_py_tests.effect import RaiseEffect
    from sugar_lift_py_tests.floor import BlockValue, ClassValue, StringValue
    from sugar_lift_py_tests.floor.authenticated_exception_type_value import (
        AuthenticatedExceptionTypeValue,
    )
    from sugar_lift_py_tests.ir import ctor, str_const
    from sugar_lift_py_tests.outcome import Complete, Incomplete

    source = (
        "def test_close_on_error():\n"
        "    with boundary(OSError):\n"
        "        with bytes_io() as buffer:\n"
        "            with get_handle(buffer) as handles:\n"
        "                pass\n"
    )
    identity = (source, "test_common_three_deep.py", blake3_512_of(source.encode()))
    probe = SourceFile(identity)
    with_nodes = sorted(
        (node for node in probe.nodes() if node.kind == "With"),
        key=lambda node: node.line_col_span().start_line,
    )
    rows = {}
    for index, node in enumerate(with_nodes):
        coordinate = _coordinate(node.items[0].context_expr)
        rows[coordinate] = (
            _ref(coordinate, _raise_semantics(), "h")
            if index == 0
            else _resource_ref(coordinate, str(index))
        )
    outer, middle, inner = _with_routers(
        _built_function(identity, "test_close_on_error", rows)
    )
    effect = RaiseEffect(exception_type_coordinate=ctor('python:exception_type_identity', [str_const('builtins'), str_const(exception_name)]), occurrence=AuthenticatedRaiseLocus.of('test_common.py:640'), exception_name=exception_name)
    inner = replace(
        inner,
        manager=_FixedOutcomeSugar(Incomplete(effect)),
        enter=_FixedOutcomeSugar(Complete(StringValue("inner-enter"))),
        exit=_FixedOutcomeSugar(Complete(StringValue("inner-exit"))),
    )
    inner_receipt, inner_outcome = _account_level("inner", effect, inner.desugar)
    assert inner_outcome is not None, inner_receipt

    middle = replace(
        middle,
        manager=_FixedOutcomeSugar(Complete(StringValue("bytes-io"))),
        enter=_FixedOutcomeSugar(Complete(StringValue("buffer"))),
        exit=_FixedOutcomeSugar(Complete(StringValue("bytes-io-exit"))),
        body=(_FixedOutcomeSugar(inner_outcome),),
    )
    middle_receipt, middle_outcome = _account_level("middle", effect, middle.desugar)
    assert middle_outcome is not None, middle_receipt

    expected_identity = ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const("OSError")],
    )
    expected = AuthenticatedExceptionTypeValue(
        ClassValue("OSError", (), BlockValue(())),
        expected_identity,
        (expected_identity,),
    )
    manager_call = CallSiteValue(
        "boundary",
        (expected,),
        ("expected",),
        ctor("call:boundary", []),
        None,
    )
    outer = replace(
        outer,
        manager=_FixedOutcomeSugar(Complete(manager_call)),
        body=(_FixedOutcomeSugar(middle_outcome),),
    )
    outer_receipt, outer_outcome = _account_level("outer", effect, outer.desugar)
    assert outer_outcome is not None, outer_receipt
    return inner_receipt, middle_receipt, outer_receipt


def test_three_deep_innermost_manager_halt_reaches_outer_assertion_after_cleanup():
    """Truthful: the subject's OSError crosses BytesIO cleanup and is consumed."""
    from sugar_lift_py_tests.outcome import Completed
    from sugar_lift_py_tests.outcome.exit_set import outcome_to_exitset

    outcome, middle_exit, inner_enter, inner_exit = _three_deep_manager_halt("OSError")
    exits = outcome_to_exitset(outcome)
    completed = [face for face in exits.exits if isinstance(face, Completed)]
    assert len(completed) == 1
    assert not any(
        getattr(getattr(face, "effect", None), "exception_name", None) == "OSError"
        for face in exits.exits
    )
    assert middle_exit == [1]
    assert inner_enter == []
    assert inner_exit == []


def test_three_deep_nonmatching_manager_halt_stays_halted_after_cleanup():
    """Lying twin: outer OSError boundary must not consume a TypeError halt."""
    from sugar_lift_py_tests.outcome import Completed, Halted
    from sugar_lift_py_tests.outcome.exit_set import outcome_to_exitset

    outcome, middle_exit, inner_enter, inner_exit = _three_deep_manager_halt(
        "TypeError"
    )
    exits = outcome_to_exitset(outcome)
    preserved = [
        face
        for face in exits.exits
        if isinstance(face, Halted)
        and getattr(face.effect, "exception_name", None) == "TypeError"
    ]
    assert len(preserved) == 1
    assert not any(isinstance(face, Completed) for face in exits.exits)
    assert middle_exit == [1]
    assert inner_enter == []
    assert inner_exit == []


def test_three_deep_each_level_accounts_the_outer_matching_edge_once():
    """Real site: two resources pass OSError; only the assertion consumes it."""
    receipts = _three_deep_level_receipts("OSError")

    assert [receipt.level for receipt in receipts] == ["inner", "middle", "outer"]
    assert [receipt.consumed for receipt in receipts] == [False, False, True]
    assert [receipt.passed for receipt in receipts] == [True, True, False]
    assert all(receipt.authenticated_exceptional_exits == 1 for receipt in receipts)
    assert all(receipt.named_refusals == 0 for receipt in receipts)
    assert all(receipt.construction_panics == 0 for receipt in receipts)


def test_three_deep_outer_only_edge_cannot_be_consumed_at_an_inner_level():
    """Load-bearing lying twin: OSError is the outer contract's edge alone."""
    inner, middle, outer = _three_deep_level_receipts("OSError")

    assert inner.passed and not inner.consumed
    assert middle.passed and not middle.consumed
    assert outer.consumed and not outer.passed
    assert inner.effect is middle.effect is outer.effect


def test_three_deep_edge_matching_no_level_escapes_all_three_unchanged():
    """A TypeError belongs to no level and must remain the identical loud edge."""
    inner, middle, outer = _three_deep_level_receipts("TypeError")

    assert all(
        receipt.passed and not receipt.consumed for receipt in (inner, middle, outer)
    )
    assert inner.effect is middle.effect is outer.effect
    assert all(
        receipt.authenticated_exceptional_exits == 1
        for receipt in (inner, middle, outer)
    )
    assert all(receipt.named_refusals == 0 for receipt in (inner, middle, outer))
    assert all(receipt.construction_panics == 0 for receipt in (inner, middle, outer))


def test_pinned_juxtaposed_assertion_and_resource_nest_left_to_right():
    """Two items use Python nesting and the same routers as nested source."""
    outer, inner = _real_juxtaposed_assertion_resource_chain()
    assert isinstance(outer, WithEffectBoundarySugar)
    assert isinstance(outer.semantics.effect_kind, WarningEffectKindV1)
    assert isinstance(inner, WithResourceSugar)
    assert inner in outer.body


def test_pinned_juxtaposition_cannot_swap_the_two_item_occurrences():
    """Lying: the right-hand resource cannot become the outer assertion."""
    outer, inner = _real_juxtaposed_assertion_resource_chain()
    assert not isinstance(outer, WithResourceSugar)
    assert not isinstance(inner, WithEffectBoundarySugar)

def _real_resource_outer_boundary_inner():
    root = _pinned_pandas_root()
    path = root / "tests/arrays/test_datetimelike.py"
    source = path.read_bytes()
    source_cid = blake3_512_of(source)
    assert source_cid == PINNED_DATETIMELIKE_CID
    identity = (source.decode("utf-8"), str(path), source_cid)
    probe = SourceFile(identity)
    function = next(
        node
        for node in probe.functions()
        if node.name == "test_searchsorted_castable_strings"
    )
    with_nodes = {
        node.line_col_span().start_line: node
        for node in function.walk()
        if node.kind == "With"
    }
    assert set(with_nodes) == {327, 342, 343}
    raise_semantics = EffectBoundarySemanticsV1(
        ExpectsModeV1(),
        RaiseEffectKindV1(),
        FormalArgumentProjectionV1(0),
        OptionalFormalArgumentProjectionV1(1),
        ExceptionInfoBindingV1(),
    )
    rows = {}
    for line, node in with_nodes.items():
        coordinate = _coordinate(node.items[0].context_expr)
        rows[coordinate] = (
            _resource_ref(coordinate, "o")
            if line == 342
            else _ref(coordinate, raise_semantics, "e")
        )
    context = TreeConstructionContextV1(
        ResolvedContractRefsV1(_cid("c"), _cid("t"), MappingProxyType(rows))
    )
    built = next(
        node
        for node in SourceFile(identity, construction_context=context).functions()
        if node.name == function.name
    ).sugar()
    outer = None

    def walk(sugar):
        nonlocal outer
        if isinstance(sugar, WithResourceSugar) and sugar.site.line == 342:
            outer = sugar
            return
        for field in ("body", "statements", "entries", "then_body", "else_body"):
            for child in getattr(sugar, field, ()) or ():
                walk(child)

    walk(built)
    assert outer is not None
    inner = next(
        child for child in outer.body if isinstance(child, WithEffectBoundarySugar)
    )
    return outer, inner


def test_pinned_resource_outer_assertion_inner_uses_two_authenticated_demands():
    """The concrete 3.0.3 site, never a historical or synthetic substitute."""
    outer, inner = _real_resource_outer_boundary_inner()
    assert isinstance(outer, WithResourceSugar)
    assert isinstance(inner, WithEffectBoundarySugar)
    assert inner in outer.body


def test_pinned_resource_outer_order_is_not_assertion_outer():
    """Lying: swapping the two structural roles must bite on the real site."""
    outer, inner = _real_resource_outer_boundary_inner()
    assert not isinstance(outer, WithEffectBoundarySugar)
    assert not isinstance(inner, WithResourceSugar)


def _real_assertion_outer_resource_inner():
    root = _pinned_pandas_root()
    path = root / "tests/apply/test_invalid_arg.py"
    source = path.read_bytes()
    source_cid = blake3_512_of(source)
    assert source_cid == PINNED_INVALID_ARG_CID
    identity = (source.decode("utf-8"), str(path), source_cid)
    probe = SourceFile(identity)
    function = next(
        node
        for node in probe.functions()
        if node.name == "test_transform_and_agg_err_agg"
    )
    with_nodes = {
        node.line_col_span().start_line: node
        for node in function.walk()
        if node.kind == "With"
    }
    assert set(with_nodes) == {309, 310}
    raise_semantics = EffectBoundarySemanticsV1(
        ExpectsModeV1(),
        RaiseEffectKindV1(),
        FormalArgumentProjectionV1(0),
        OptionalFormalArgumentProjectionV1(1),
        ExceptionInfoBindingV1(),
    )
    rows = {}
    for line, node in with_nodes.items():
        coordinate = _coordinate(node.items[0].context_expr)
        rows[coordinate] = (
            _ref(coordinate, raise_semantics, "x")
            if line == 309
            else _resource_ref(coordinate, "r")
        )
    context = TreeConstructionContextV1(
        ResolvedContractRefsV1(_cid("c"), _cid("t"), MappingProxyType(rows))
    )
    built = next(
        node
        for node in SourceFile(identity, construction_context=context).functions()
        if node.name == function.name
    ).sugar()
    outer = None

    def walk(sugar):
        nonlocal outer
        if isinstance(sugar, WithEffectBoundarySugar) and sugar.site.line == 309:
            outer = sugar
            return
        for field in ("body", "statements", "entries", "then_body", "else_body"):
            for child in getattr(sugar, field, ()) or ():
                walk(child)

    walk(built)
    assert outer is not None
    inner = next(child for child in outer.body if isinstance(child, WithResourceSugar))
    return outer, inner


def test_pinned_assertion_outer_resource_inner_uses_two_authenticated_demands():
    """The inverse order composes by nesting through the same constructors."""
    outer, inner = _real_assertion_outer_resource_inner()
    assert isinstance(outer, WithEffectBoundarySugar)
    assert isinstance(inner, WithResourceSugar)
    assert inner in outer.body


def test_pinned_inverse_order_is_not_resource_outer():
    """Lying: contract kind cannot reorder the two real source occurrences."""
    outer, inner = _real_assertion_outer_resource_inner()
    assert not isinstance(outer, WithResourceSugar)
    assert not isinstance(inner, WithEffectBoundarySugar)
