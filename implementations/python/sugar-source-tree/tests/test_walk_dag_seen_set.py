"""walk() is a DAG walk by identity — not a tree walk of shared structure.

Regression for the nanops setup_method seal hang: sequential self.field stores
build a shared ReceiverFieldStoreState DAG; walk() without a seen-set was
exponential in sharing depth.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Node
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.tree import SourceFile

FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "receiver_field_store_fibonacci_blowup.py"
)


def _open(text: str, name: str = "walk_dag.py") -> SourceFile:
    if not text.endswith("\n"):
        text += "\n"
    return SourceFile(
        (text, name, blake3_512_of(text.encode())),
        reporter=CollectingReporter(),
    )


def test_shared_node_visited_once_by_default() -> None:
    """A diamond DAG yields the shared child once under unique=True."""
    # Build:  two parents point at the same Name node object via rewrite-like share.
    # We can't easily mint arbitrary DAGs without substitute; use field-store
    # path which is the production share shape.
    text = (
        "class C:\n"
        "    def f(self):\n"
        "        self.x = 1\n"
        "        self.y = self.x\n"
        "        self.z = self.y + self.x\n"
    )
    sf = _open(text)
    fn = next(f for f in sf.functions() if f.name == "f")
    substituted = fn.substitute({})
    # After substitute, body is ReceiverFieldStoreStatement chain sharing prior state.
    last = substituted.body[-1]
    once = list(last.walk())
    paths = list(last.walk(unique=False))
    assert len(once) == len({id(n) for n in once})
    # Path walk (tree expansion) visits shared structure multiple times.
    assert len(paths) >= len(once)
    # Every identity from the unique walk appears in the path walk.
    assert {id(n) for n in once} <= {id(n) for n in paths}


def test_fibonacci_self_field_store_walk_grows_linearly() -> None:
    """Minimal nanops reproducer: walk node count linear in statement count.

    Historical tree-walk counts (unique=False) grew ~3× per statement:
      4, 9, 29, 89, 269, 809, 2429, … — combinatorial.
    DAG walk (unique=True, default) must stay linear in #statements.
    """
    text = FIXTURE.read_text()
    sf = _open(text, name=FIXTURE.name)
    fn = next(f for f in sf.functions() if f.name == "setup_method")
    # Empty scope: same door FunctionDef._construct_sugar uses for temporal
    # substitute of method bodies (formals masked separately).
    from sugar_source_tree.nodes import (
        RuntimeBindingEntryFactoryV1,
        SubstitutionTraceBuilderV1,
        _BINDING_ENTRY_FACTORY,
        _SCOPE_OWNER_CID,
        _SUBSTITUTION_TRACE_BUILDER,
    )
    from sugar_lift_python_source.canonical import cid_of_json

    scope_owner_cid = cid_of_json(
        {
            "kind": "binding-scope-owner",
            "schemaVersion": "1",
            "source": fn.fragment.seal().to_dict(),
        }
    )
    substituted = fn.substitute(
        {
            _SCOPE_OWNER_CID: scope_owner_cid,
            _SUBSTITUTION_TRACE_BUILDER: SubstitutionTraceBuilderV1(scope_owner_cid),
            _BINDING_ENTRY_FACTORY: RuntimeBindingEntryFactoryV1(scope_owner_cid),
        }
    )

    # Prefix sizes: after k self-field stores, unique walk count is O(k).
    # Collect walk sizes of each produced body statement (post-substitute).
    sizes = [len(list(stmt.walk())) for stmt in substituted.body]
    assert len(sizes) == 12  # a0..a11
    # Linear ceiling: each new store adds a bounded number of nodes (RFS +
    # BinOp + two Attribute loads).  Allow generous constant, still far below
    # the historical 590_489 at statement 12.
    for i, n in enumerate(sizes):
        # O(i) with roomy constant — 200 nodes/statement is already generous.
        assert n <= 200 * (i + 1), (
            f"stmt#{i} walk nodes={n} exceeds linear bound; "
            f"series={sizes} — walk is re-expanding a DAG as a tree"
        )
    # Explicit: last statement must not be combinatorial (~590k tree-walk).
    assert sizes[-1] < 5_000
    # Monotone non-decreasing is fine; growth factor vs prior must stay small.
    for i in range(1, len(sizes)):
        if sizes[i - 1] == 0:
            continue
        ratio = sizes[i] / sizes[i - 1]
        assert ratio < 2.5, (
            f"stmt#{i} grew {ratio:.2f}× (sizes {sizes[i-1]}→{sizes[i]}); "
            f"combinatorial tree-walk reintroduced"
        )


def test_fibonacci_self_field_store_constructs() -> None:
    """Full FunctionDef.sugar of the minimal file must complete (not hang)."""
    text = FIXTURE.read_text()
    sf = _open(text, name=FIXTURE.name)
    fn = next(f for f in sf.functions() if f.name == "setup_method")
    # Bound construct: if walk regresses, this is where the seal hung.
    result = fn.sugar()
    assert result is not None


def test_walk_default_is_unique() -> None:
    """Default signature visits once; unique=False remains available."""
    import inspect

    sig = inspect.signature(Node.walk)
    assert sig.parameters["unique"].default is True
