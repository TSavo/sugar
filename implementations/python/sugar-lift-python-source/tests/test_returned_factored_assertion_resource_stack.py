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


def _item_use_site_coordinate(site: With, item):
    """Exact SourceFragmentCoordinate for one With-item occurrence."""
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceFragmentCoordinateV1,
    )

    start_line, start_col, end_line, end_col = item._manager_use_site_span()
    return SourceFragmentCoordinateV1(
        site.unit.source_cid,
        start_line,
        start_col,
        end_line,
        end_col,
    )


def _require_item_ref(site: With, item, *, index: int):
    """Exact seated ref for one With-item coordinate.

    No try/except swallow. No table-wide fallback. A missing seat is an
    honorable red naming the coordinate — the dual-Name producer instrument.
    """
    coordinate = _item_use_site_coordinate(site, item)
    ref = site._prebound_manager_resolution(item)
    if ref is None:
        pytest.fail(
            "MISSING PRODUCER: With-item has no prebound manager resolution.\n"
            f"  item index: {index}\n"
            f"  coordinate: {coordinate}\n"
            f"  expected: SourceDerivedContextManagerRefV1 (or factored) seated "
            f"at this exact use-site coordinate in source_derived_contract_refs\n"
            f"  fix: seat the returned/assigned manager identity at the item "
            f"coordinate before With construction — never prove the stack from "
            f"an unrelated published ref"
        )
    if isinstance(ref, ContextManagerResolutionGapV1):
        pytest.fail(
            "MISSING PRODUCER: With-item coordinate seats a resolution gap, "
            "not an authenticated manager contract.\n"
            f"  item index: {index}\n"
            f"  coordinate: {coordinate}\n"
            f"  gap: {ref}\n"
            f"  expected: ProtocolResource or EffectBoundary source-derived ref "
            f"at this exact coordinate"
        )
    return ref


def _require_item_refs(site: With):
    """One exact ref per With-item, in source order — no soft green."""
    return tuple(
        _require_item_ref(site, item, index=index)
        for index, item in enumerate(site.items)
    )


def _ref_kind(ref) -> str:
    if isinstance(ref, FactoredSourceDerivedContextManagerRefV1):
        return "factored-boundary"
    if isinstance(ref, SourceDerivedContextManagerRefV1):
        if isinstance(ref.semantics, EffectBoundarySemanticsV1):
            return "boundary"
        if isinstance(ref.semantics, ProtocolResourceSemanticsV1):
            return "resource"
        return type(ref.semantics).__name__
    return type(ref).__name__


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

    # Exact seating: each With-item coordinate owns its own ref (no table sweep).
    refs = _require_item_refs(site)
    assert len(refs) == 2
    assert _ref_kind(refs[0]) == "resource", (_ref_kind(refs[0]), refs[0])
    assert _ref_kind(refs[1]) in {"boundary", "factored-boundary"}, (
        _ref_kind(refs[1]),
        refs[1],
    )
    # Distinct seats — item 1 must not silently borrow item 0's ref.
    assert refs[0] is not refs[1]
    assert _item_use_site_coordinate(site, site.items[0]) != _item_use_site_coordinate(
        site, site.items[1]
    )


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
    # Exact per-item seats follow source order too.
    refs = _require_item_refs(site)
    assert _ref_kind(refs[0]) in {"boundary", "factored-boundary"}, _ref_kind(refs[0])
    assert _ref_kind(refs[1]) == "resource", _ref_kind(refs[1])


def test_dual_name_assigned_stack_seats_each_item_coordinate(tmp_path: Path):
    """Acceptance instrument for dual-Name assigned multi-item producer (codex-3).

    ``r = make_guard(...); b = make_boundary(...); with r, b:`` must seat an
    authenticated ref at **each** Name use-site coordinate. Soft green via
    table-wide fallback is forbidden. Missing seats / construction gaps fail
    with MISSING PRODUCER — never catch-and-continue.
    """
    from sugar_source_tree.panic import SugarNotWritten

    dist = _distribution(tmp_path, _STACK_PKG)
    consumer = (
        "import arbitrary\n"
        "def use():\n"
        "    r = arbitrary.make_guard('r')\n"
        "    b = arbitrary.make_boundary(ValueError)\n"
        "    with r, b as info:\n"
        "        raise ValueError('boom')\n"
    )
    try:
        tree, context, _ = _populate(tmp_path, consumer, dist=dist)
    except SugarNotWritten as gap:
        # Honest red: projection never seated the Name coordinates. Do not
        # recover; restate as the dual-Name producer handoff for codex-3.
        pytest.fail(
            "MISSING PRODUCER: dual-Name assigned multi-item stack failed during "
            "populate/projection before each With-item coordinate can be read.\n"
            f"  error: {gap}\n"
            "  expected: both Name use sites (r and b) seat "
            "SourceDerivedContextManagerRefV1 at their exact coordinates, then "
            "With._nest_items builds outer WithSourceResourceSugar + inner "
            "WithEffectBoundarySugar\n"
            "  owned boundary: return/assignment projection into "
            "source_derived_contract_refs for multi-item Name heads before "
            "substitute — never prove the stack from a table-wide fallback"
        )
    site = next(n for n in _with_nodes(tree) if len(n.items) == 2)
    assert [item.context_expr.kind for item in site.items] == ["Name", "Name"]
    # Exact seats — this is the green path once the dual-Name producer lands.
    refs = _require_item_refs(site)
    assert len(refs) == 2
    assert _ref_kind(refs[0]) == "resource", (_ref_kind(refs[0]), refs[0])
    assert _ref_kind(refs[1]) in {"boundary", "factored-boundary"}, (
        _ref_kind(refs[1]),
        refs[1],
    )
    chain = _with_chain(site._nest_items().sugar())
    assert len(chain) == 2, [type(n).__name__ for n in chain]
    assert isinstance(chain[0], WithSourceResourceSugar)
    assert isinstance(chain[1], WithEffectBoundarySugar)


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
    # Exact seats: item 0 is resource; item 1 must not become EffectBoundary.
    refs = _require_item_refs(site)
    assert _ref_kind(refs[0]) == "resource", _ref_kind(refs[0])
    assert (
        _ref_kind(refs[1]) != "boundary" and _ref_kind(refs[1]) != "factored-boundary"
    ), (
        _ref_kind(refs[1]),
        refs[1],
    )
    assert any(isinstance(n, WithSourceResourceSugar) for n in chain)
