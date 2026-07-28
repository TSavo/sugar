"""Returned/assigned stack: factored assertion manager + source-resource manager.

Return projection must preserve both manager identities, their contracts, and
source-order nesting (enter first manager first; exit last manager first) when
the consumer writes multi-item ``with`` over returned or assigned factories.
"""

from __future__ import annotations

import csv
import importlib.metadata
from pathlib import Path

import pytest

from sugar_lift_py_tests.context_manager_contract import (
    EffectBoundarySemanticsV1,
    NoMessagePatternV1,
    OptionalFormalArgumentProjectionV1,
    ProtocolResourceSemanticsV1,
)
from sugar_lift_py_tests.context_manager_resolution import (
    ContextManagerResolutionGapV1,
    FactoredSourceDerivedContextManagerRefV1,
    SourceDerivedContextManagerRefV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.sugar.with_effect_boundary_sugar import WithEffectBoundarySugar
from sugar_lift_py_tests.sugar.with_source_resource_sugar import WithSourceResourceSugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.manager_summary_derivation import (
    populate_source_derived_resource_refs,
)
from sugar_source_tree.nodes import With
from sugar_source_tree.tree import SourceFile

_STACK_PKG = (
    "class Guard:\n"
    "    def __init__(self, marker):\n"
    "        self.marker = marker\n"
    "    def __enter__(self):\n"
    "        return self.marker\n"
    "    def __exit__(self, effect_type, effect, traceback):\n"
    "        return False\n"
    "\n"
    "class Boundary:\n"
    "    def __init__(self, expected, match=None):\n"
    "        self.expected = expected\n"
    "        self.match = match\n"
    "    def __enter__(self):\n"
    "        return self\n"
    "    def __exit__(self, effect_type, effect, traceback):\n"
    "        if effect_type is None:\n"
    "            raise RuntimeError('unmet')\n"
    "        return effect_type is self.expected\n"
    "\n"
    "def make_guard(marker):\n"
    "    return Guard(marker)\n"
    "\n"
    "def make_boundary(expected, match=None):\n"
    "    return Boundary(expected, match)\n"
)


def _distribution(root: Path, source: str):
    package = root / "arbitrary"
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text(
        "from arbitrary.manager import make_guard, make_boundary\n",
        encoding="utf-8",
    )
    (package / "manager.py").write_text(source, encoding="utf-8")
    metadata = root / "arbitrary_dist-1.0.dist-info"
    metadata.mkdir(exist_ok=True)
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: arbitrary-dist\nVersion: 1.0\n",
        encoding="utf-8",
    )
    files = (
        "arbitrary/__init__.py",
        "arbitrary/manager.py",
        "arbitrary_dist-1.0.dist-info/METADATA",
        "arbitrary_dist-1.0.dist-info/RECORD",
    )
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for file in files:
            writer.writerow((file, "", ""))
    return importlib.metadata.Distribution.at(metadata)


def _populate(root: Path, consumer: str, *, dist):
    path = root / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (consumer, str(path), blake3_512_of(consumer.encode("utf-8"))),
        construction_context=context,
    )
    populate_source_derived_resource_refs(
        tree,
        root=root,
        path=path,
        distribution_index={"arbitrary": dist},
    )
    return tree, context, path


def _with_nodes(tree):
    return [node for node in tree.nodes() if isinstance(node, With)]


def _with_chain(sugar):
    """Outermost-first chain of resource/boundary routers."""
    chain = []

    def walk(node):
        if isinstance(node, (WithSourceResourceSugar, WithEffectBoundarySugar)):
            chain.append(node)
            for child in getattr(node, "body", ()) or ():
                walk(child)
            return
        for field in ("body", "statements", "entries"):
            for child in getattr(node, field, ()) or ():
                walk(child)

    walk(sugar)
    return chain


def _item_refs(tree, context):
    """Per-item prebound manager resolution for the multi-item With site."""
    site = next(n for n in _with_nodes(tree) if len(n.items) >= 1)
    # Multi-item sites nest; resolve each item coordinate through populate table.
    refs = []
    for item in site.items:
        try:
            ref = item.context_expr and site._prebound_manager_resolution(item)
        except Exception:
            ref = None
        if ref is None:
            # Fall back to all source-derived refs ordered by use-site appearance.
            break
        refs.append(ref)
    if len(refs) == len(site.items):
        return site, refs
    # Assigned Name managers seat refs by projected call, not always on the item.
    all_refs = list(context.source_derived_contract_refs.values())
    return site, all_refs


def test_returned_stack_resource_then_assertion_preserves_both_identities(
    tmp_path: Path,
):
    """``with make_guard(...), make_boundary(...):`` keeps both contracts + order."""
    dist = _distribution(tmp_path, _STACK_PKG)
    consumer = (
        "import arbitrary\n"
        "def use():\n"
        "    with arbitrary.make_guard('r'), arbitrary.make_boundary(ValueError) as info:\n"
        "        raise ValueError('boom')\n"
    )
    tree, context, _ = _populate(tmp_path, consumer, dist=dist)
    site = next(n for n in _with_nodes(tree) if len(n.items) == 2)

    # Nested construction: outer resource, inner assertion.
    nested = site._nest_items()
    outer_sugar = nested.sugar()
    chain = _with_chain(outer_sugar)
    assert len(chain) == 2, [type(n).__name__ for n in chain]
    assert isinstance(chain[0], WithSourceResourceSugar), type(chain[0])
    assert isinstance(chain[1], WithEffectBoundarySugar), type(chain[1])
    assert chain[1] in chain[0].body

    # Both managers authenticated — not gaps.
    site2, refs = _item_refs(tree, context)
    assert len(refs) >= 2 or context.source_derived_contract_refs, (
        "stack left no source-derived refs"
    )
    # At least one ProtocolResource and one EffectBoundary among seated refs.
    kinds = []
    for ref in context.source_derived_contract_refs.values():
        if isinstance(ref, ContextManagerResolutionGapV1):
            continue
        if isinstance(ref, FactoredSourceDerivedContextManagerRefV1):
            kinds.append("factored-boundary")
        elif isinstance(ref, SourceDerivedContextManagerRefV1):
            if isinstance(ref.semantics, EffectBoundarySemanticsV1):
                kinds.append("boundary")
            elif isinstance(ref.semantics, ProtocolResourceSemanticsV1):
                kinds.append("resource")
            else:
                kinds.append(type(ref.semantics).__name__)
    assert "resource" in kinds, kinds
    assert "boundary" in kinds or "factored-boundary" in kinds, kinds


def test_returned_stack_assertion_then_resource_swaps_outer(
    tmp_path: Path,
):
    """Source order twin: assertion first → assertion outer, resource inner."""
    dist = _distribution(tmp_path, _STACK_PKG)
    consumer = (
        "import arbitrary\n"
        "def use():\n"
        "    with arbitrary.make_boundary(ValueError), arbitrary.make_guard('r'):\n"
        "        raise ValueError('boom')\n"
    )
    tree, context, _ = _populate(tmp_path, consumer, dist=dist)
    site = next(n for n in _with_nodes(tree) if len(n.items) == 2)
    nested = site._nest_items()
    chain = _with_chain(nested.sugar())
    assert len(chain) == 2, [type(n).__name__ for n in chain]
    assert isinstance(chain[0], WithEffectBoundarySugar), type(chain[0])
    assert isinstance(chain[1], WithSourceResourceSugar), type(chain[1])
    assert chain[1] in chain[0].body


def test_returned_call_stack_is_stable_across_populate_runs(tmp_path: Path):
    """Two independent populate runs of the same returned stack agree on types."""
    returned = (
        "import arbitrary\n"
        "def use():\n"
        "    with arbitrary.make_guard('r'), arbitrary.make_boundary(ValueError):\n"
        "        raise ValueError('boom')\n"
    )
    root_a = tmp_path / "a"
    root_b = tmp_path / "b"
    root_a.mkdir()
    root_b.mkdir()
    tree_a, _, _ = _populate(root_a, returned, dist=_distribution(root_a, _STACK_PKG))
    tree_b, _, _ = _populate(root_b, returned, dist=_distribution(root_b, _STACK_PKG))

    site_a = next(n for n in _with_nodes(tree_a) if len(n.items) == 2)
    site_b = next(n for n in _with_nodes(tree_b) if len(n.items) == 2)
    chain_a = _with_chain(site_a._nest_items().sugar())
    chain_b = _with_chain(site_b._nest_items().sugar())
    assert [type(n) for n in chain_a] == [type(n) for n in chain_b]
    assert len(chain_a) == 2
    assert isinstance(chain_a[0], WithSourceResourceSugar)
    assert isinstance(chain_a[1], WithEffectBoundarySugar)


def test_discrimination_lying_resource_cannot_borrow_assertion_in_stack(
    tmp_path: Path,
):
    """Lying twin: ordinary resource spelling as second manager is not EffectBoundary."""
    lying = (
        "class Guard:\n"
        "    def __init__(self, marker):\n"
        "        self.marker = marker\n"
        "    def __enter__(self):\n"
        "        return self.marker\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        return False\n"
        "\n"
        "class Ordinary:\n"
        "    def __init__(self, expected, match=None):\n"
        "        self.expected = expected\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        return False\n"
        "\n"
        "def make_guard(marker):\n"
        "    return Guard(marker)\n"
        "\n"
        "def make_boundary(expected, match=None):\n"
        "    return Ordinary(expected, match)\n"
    )
    dist = _distribution(tmp_path, lying)
    consumer = (
        "import arbitrary\n"
        "def use():\n"
        "    with arbitrary.make_guard('r'), arbitrary.make_boundary(ValueError):\n"
        "        raise ValueError('boom')\n"
    )
    tree, context, _ = _populate(tmp_path, consumer, dist=dist)
    site = next(n for n in _with_nodes(tree) if len(n.items) == 2)
    chain = _with_chain(site._nest_items().sugar())
    # No WithEffectBoundarySugar may be invented for the lie.
    assert not any(isinstance(n, WithEffectBoundarySugar) for n in chain), [
        type(n).__name__ for n in chain
    ]
    # Resource identity for the first manager may still seat.
    assert any(isinstance(n, WithSourceResourceSugar) for n in chain) or any(
        isinstance(ref, SourceDerivedContextManagerRefV1)
        and isinstance(ref.semantics, ProtocolResourceSemanticsV1)
        for ref in context.source_derived_contract_refs.values()
    )
