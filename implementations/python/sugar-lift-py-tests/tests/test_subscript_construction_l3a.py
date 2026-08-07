"""L3a: SubscriptSugar routes through SubscriptOperation when floors own it.

owner=subscript construction panics were floors with subscript_with but no
legacy subscript. Prefer the operation edge; legacy subscript floors still work.
"""

from __future__ import annotations

from sugar_lift_python_source.canonical import blake3_512_of, cid_of_json
from sugar_source_tree.nodes import (
    RuntimeBindingEntryFactoryV1,
    SubstitutionTraceBuilderV1,
    _BINDING_ENTRY_FACTORY,
    _SCOPE_OWNER_CID,
    _SUBSTITUTION_TRACE_BUILDER,
)
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.tree import SourceFile
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1


def _sugar_fn(src: str):
    sf = SourceFile(
        (src, "l3a_sub.py", blake3_512_of(src.encode())),
        reporter=CollectingReporter(),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    fn = next(sf.functions())
    cid = cid_of_json(
        {
            "kind": "binding-scope-owner",
            "schemaVersion": "1",
            "source": fn.fragment.seal().to_dict(),
        }
    )
    scope = {
        _SCOPE_OWNER_CID: cid,
        _SUBSTITUTION_TRACE_BUILDER: SubstitutionTraceBuilderV1(cid),
        _BINDING_ENTRY_FACTORY: RuntimeBindingEntryFactoryV1(cid),
    }
    return fn.substitute(scope).sugar()


def _desugar_return(src: str):
    from sugar_lift_py_tests.sugar.function_universe_sugar import FunctionUniverseSugar

    sugar = _sugar_fn(src)
    assert isinstance(sugar, FunctionUniverseSugar)
    # Full desugar of body is heavy; construct path already ran. Desugar the
    # return expression's constructed universe entry via sugar.desugar when cheap.
    return sugar.desugar()


def test_dict_literal_subscript_constructs_and_desugars_without_owner_subscript_gap():
    """DictLiteralValue has subscript_with only — must not hit FloorValue.subscript."""
    # Constructs (SubscriptSugar mint) and desugars without ConstructionGap owner=subscript.
    outcome = _desugar_return("def A():\n    return {1: 2}[1]\n")
    # Completed path or Incomplete typed effect — not a construction_panic.
    from sugar_lift_py_tests.outcome import Complete, Incomplete, ExitSet

    assert isinstance(outcome, (Complete, Incomplete, ExitSet))


def test_tuple_literal_multi_index_constructs():
    sugar = _sugar_fn("def A():\n    return (10, 20, 30)[1]\n")
    assert sugar is not None


def test_list_literal_subscript_legacy_path_still_constructs():
    """ListValue implements subscript (legacy); still one door through sugar."""
    sugar = _sugar_fn("def A():\n    return [10, 20, 30][1]\n")
    assert sugar is not None


def test_none_subscript_constructs_typeerror_exit_not_owner_subscript_gap():
    """NoneValue.subscript is written — TypeError exit, not floor gap."""
    from sugar_lift_py_tests.outcome import Incomplete
    from sugar_lift_py_tests.gap.panic import ConstructionPanic

    try:
        outcome = _desugar_return("def A():\n    return None[0]\n")
    except ConstructionPanic as e:
        raise AssertionError(f"owner=subscript gap still fires: {e}") from e
    # Desugar may Incomplete(TypeError effect) or Complete(RaiseValue)
    assert outcome is not None


def test_subscript_operation_module_exists_for_floor_edges():
    from sugar_lift_py_tests.operations.subscript_operation import SubscriptOperation

    assert SubscriptOperation.method_name == "subscript_with"
