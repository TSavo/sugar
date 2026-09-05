"""A lambda asked for outside a substituted body still constructs (1 row, 2026-09-05 board).

``LambdaSugar`` existed, but only for a lambda already rewritten by its
enclosing body's substitution (``self.ref`` a ShadowNode). ``f=lambda x:
x.sum()`` as a DEFAULT formal is asked for by ``Param.sugar()`` before any
body substitution ran, and fell to the bare gap. Same law either way: mask
the formals by substitution, then construct.
"""

from __future__ import annotations

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.lambda_sugar import LambdaSugar
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
from sugar_source_tree.nodes import Lambda
from sugar_source_tree.reporter import CollectingReporter


def _lambda(tmp_path, source: str) -> Lambda:
    path = tmp_path / "lam.py"
    path.write_text(source)
    source_file = open_source_file_for_construction(
        path,
        root=tmp_path,
        reporter=CollectingReporter(),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
        populate_derived=False,
    )
    return next(n for n in source_file.nodes() if isinstance(n, Lambda))


def test_unsubstituted_lambda_constructs_by_substituting_first(tmp_path) -> None:
    """Truthful twin: ``lambda x, y: x + y`` asked for as a default formal."""
    node = _lambda(tmp_path, "def g(x, y, f=lambda x, y: x + y):\n    return f(x, y)\n")
    sugar = node.sugar()
    assert isinstance(sugar, LambdaSugar)
    assert isinstance(sugar, ConstructedTermSugar)
    assert sugar.formals == ("x", "y")
    assert len(sugar.formal_coordinate_cids) == 2
    assert sugar.source_call_frame is not None
    assert isinstance(sugar.desugar(None), Complete)


def test_lambda_default_formal_folds_into_the_owner(tmp_path) -> None:
    """The board's shape: the default carries the lambda's universe sugar."""
    from sugar_lift_py_tests.sugar.param_sugar import ParamSugar
    from sugar_source_tree.nodes import Param

    path = tmp_path / "own.py"
    path.write_text("def check(df, f=lambda x: x.sum()):\n    return f(df)\n")
    source_file = open_source_file_for_construction(
        path, root=tmp_path, reporter=CollectingReporter(),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
        populate_derived=False,
    )
    param = next(n for n in source_file.nodes() if isinstance(n, Param) and n.default is not None)
    sugar = param.sugar()
    assert isinstance(sugar, ParamSugar)
    assert isinstance(sugar.default, LambdaSugar)
    assert sugar.default.formals == ("x",)


def test_lambda_formals_are_its_own_never_the_enclosing_defs(tmp_path) -> None:
    """Lying twin: ``lambda x: x`` inside ``def g(x)`` must not borrow g's ``x``.

    Substituting first is what masks the lambda's formals; a construction
    that skipped it would let the body's ``x`` resolve to g's coordinate."""
    from sugar_source_tree.nodes import FunctionDef

    path = tmp_path / "shadow.py"
    path.write_text("def g(x, f=lambda x: x):\n    return f(x)\n")
    source_file = open_source_file_for_construction(
        path, root=tmp_path, reporter=CollectingReporter(),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
        populate_derived=False,
    )
    g = next(f for f in source_file.functions() if f.name == "g")
    node = next(n for n in source_file.nodes() if isinstance(n, Lambda))
    sugar = node.sugar()
    g_cids = {c.coordinate_cid for c in g.formal_coordinates()}
    assert set(sugar.formal_coordinate_cids).isdisjoint(g_cids)
    assert sugar.source_call_frame.owner is not g
