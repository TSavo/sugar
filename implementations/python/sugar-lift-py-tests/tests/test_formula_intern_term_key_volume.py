"""#5338 — formula intern must not re-CID whole term DAGs per atomic.

Product residual after #5429: ``pandas/io/stata.py`` hard-timeouts on
reduce_body with tip ``NotInOpSugar`` at the For+If column-dtype check
(``dtype not in (object_type, self._dtyplist[idx])``). Profile under
``term_intern_scope``:

  - left/right reduce finishes in milliseconds
  - ``not_(atomic("py.in", [left.term, right.term]))`` alone pays ~19s
  - root cause: ``_formula_cycle_key`` builds a fresh ``TermTableBuilder``
    and full blake3 CID for every atomic arg on every intern

That is not a pandas special-case. Any membership / equality formula over a
large interned CallSiteValue term re-pays full wire-CID materialization for
hash-cons keys that already have request-scoped term identity.

Replacement architecture (#5569):
  formula keys always use permanent content CIDs (scope-stable). Under
  ``term_intern_scope``, memoize CID so repeated interns do not re-pay
  blake3 — never ``id(_intern_term)`` as identity.
  ``finite_membership_value`` refuses non-literal domain elements (docstring
  already requires literal domains) so opaque column membership does not
  re-enter equals → formula-intern volume.

This instrument stays red while atomic/not_ intern wall scales with term
depth via repeated CID materialization. Never soft-complete; never raise the
product bound.
"""

from __future__ import annotations

import time

from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
from sugar_lift_py_tests.floor.tuple_value import TupleValue
from sugar_lift_py_tests.ir import (
    atomic,
    ctor,
    make_var,
    not_,
    term_intern_scope,
)
from sugar_lift_py_tests.sugar.in_op_sugar import finite_membership_value


def _deep_term(depth: int):
    term = make_var("leaf")
    for index in range(depth):
        term = ctor(f"ssa:{index}", [term])
    return term


def test_formula_intern_of_deep_terms_stays_under_budget() -> None:
    """Atomic py.in over a deep interned DAG must not re-pay full CID walks.

    Microbench before fix (depth 250): not_(atomic(py.in)) is multi-100ms+;
    depth 800 ~19s on the product seat. Budget is tight enough that the
    CID-per-key path fails without a 30s product hang.
    """
    depth = 250
    budget_seconds = 0.12
    with term_intern_scope():
        left = _deep_term(depth)
        right = _deep_term(depth)
        assert left is right
        started = time.perf_counter()
        formula = not_(atomic("py.in", [left, right]))
        again = not_(atomic("py.in", [left, right]))
        elapsed = time.perf_counter() - started
    assert formula is again, (
        "structurally equal formulas must hash-cons under term_intern_scope"
    )
    assert elapsed < budget_seconds, (
        f"R=1 formula intern over deep terms paid {elapsed:.3f}s "
        f"(budget {budget_seconds}s at depth={depth}). "
        "Replacement: memoize permanent content CID under term_intern_scope "
        "(never id() as formula identity; #5569). "
        "Do not raise product timeout, soft-complete, or mint RuntimeEffect."
    )


def test_repeated_formula_intern_does_not_scale_with_cid_rebuilds() -> None:
    """N formula interns over the same deep terms must stay near-constant cost."""
    depth = 200
    repeats = 15
    budget_seconds = 0.15
    with term_intern_scope():
        left = _deep_term(depth)
        right = ctor("pair", [left, make_var("other")])
        started = time.perf_counter()
        formulas = [atomic("py.eq", [left, right]) for _ in range(repeats)]
        elapsed = time.perf_counter() - started
    assert all(f is formulas[0] for f in formulas)
    assert elapsed < budget_seconds, (
        f"R=1 repeated formula intern paid {elapsed:.3f}s for {repeats}× "
        f"depth={depth} (budget {budget_seconds}s). "
        "Keys must reuse memoized content CIDs, not rebuild TermTableBuilder "
        "walks on every atomic (#5569)."
    )


def test_method_call_on_guarded_receiver_reduces_args_once() -> None:
    """Nested method args must not re-reduce per GuardedValue face (#5338).

    ``data.set_index(data.pop(index_col))`` with multi-face ``data`` was paying
    faces² arg reductions (each face of set_index re-projected pop over all
    faces again). Args reduce under a face-independent ctx — once is enough.
    """
    from sugar_lift_py_tests.claim import SugarRole
    from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
    from sugar_lift_py_tests.factory.build import build_node, default_catalog
    from sugar_lift_py_tests.floor.guarded_value import GuardedValue
    from sugar_lift_py_tests.floor.string_value import StringValue
    from sugar_lift_py_tests.ir import atomic, make_var
    from sugar_lift_py_tests.sugar.name_sugar import NameSugar

    # GuardedValue spine with 32 faces (depth-5 full binary tree).
    def spine(depth: int, tag: str):
        if depth == 0:
            return StringValue(tag)
        return GuardedValue(
            atomic("face", [make_var(f"{tag}:{depth}")]),
            spine(depth - 1, f"{tag}t"),
            spine(depth - 1, f"{tag}f"),
        )

    receiver = spine(5, "d")  # 32 faces
    ctx = FactoryBuildContext(filename="guarded_method.py", catalog=default_catalog())
    ctx = ctx.with_temporal(ctx.temporal.bind_value("data", receiver))
    ctx = ctx.with_temporal(ctx.temporal.bind_value("index_col", StringValue("ix")))

    import ast

    node = ast.parse("data.set_index(data.pop(index_col))", mode="eval").body
    sugar = build_node(
        node,
        filename="guarded_method.py",
        role=SugarRole.TERM,
        ctx=ctx,
    ).sugar

    name_reduces = {"index_col": 0}
    original = NameSugar.desugar

    def counting(self, ctx=None):
        if self.name == "index_col":
            name_reduces["index_col"] += 1
        return original(self, ctx)

    NameSugar.desugar = counting  # type: ignore[method-assign]
    try:
        started = time.perf_counter()
        with term_intern_scope():
            outcome = sugar.desugar(ctx)
        elapsed = time.perf_counter() - started
    finally:
        NameSugar.desugar = original  # type: ignore[method-assign]

    assert type(outcome).__name__ == "Complete"
    # index_col appears once in source; must not scale with faces or faces².
    assert name_reduces["index_col"] <= 2, (
        f"R=1 index_col NameSugar reduced {name_reduces['index_col']} times "
        f"over a 32-face guarded receiver (budget ≤2). Replacement: MethodCallSugar "
        f"must reduce remaining args once before projecting over GuardedValue faces."
    )
    assert elapsed < 0.5, (
        f"R=1 guarded method projection paid {elapsed:.3f}s over 32 faces; "
        "must stay sub-second after single-arg-reduction projection"
    )


def test_finite_membership_skips_non_ground_domain_elements() -> None:
    """Literal-domain refinement only; opaque CallSiteValue domains stay None.

    ``finite_membership_value`` docstring requires literal domains. Building
    GuardedValue trees via equals over CallSiteValue domain elements re-enters
    the same formula-intern volume (stata object_type / _dtyplist[idx]).
    """
    with term_intern_scope():
        needle = CallSiteValue(
            target_name="attr:dtype",
            arg_values=(),
            parameters=(),
            term=ctor("attr:dtype", [make_var("series")]),
            body=None,
        )
        domain = TupleValue(
            (
                CallSiteValue(
                    target_name="call:numpy.dtype",
                    arg_values=(),
                    parameters=(),
                    term=ctor("call:numpy.dtype", [make_var("object")]),
                    body=None,
                ),
                CallSiteValue(
                    target_name="py.subscript",
                    arg_values=(),
                    parameters=(),
                    term=ctor(
                        "py.subscript", [make_var("dtyplist"), make_var("idx")]
                    ),
                    body=None,
                ),
            )
        )
        refined = finite_membership_value(needle, domain, site="membership.py:1:0")
    assert refined is None, (
        "R=1 finite_membership_value refined a non-literal CallSiteValue domain; "
        "replacement=return None unless every domain element is a ground primitive "
        "(TermValue/StringValue/bool literals). Do not equals-fold opaque columns."
    )
