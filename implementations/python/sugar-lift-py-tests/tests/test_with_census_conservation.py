"""With census conservation: Class B refusal + measurement partition teeth.

Conservation identity (binding):
  site:with-item == constructed + typed_gaps
  over the effective use-site set With construction sees.

Landmine class A (fixed elsewhere): families rebind.
This module: Class B honest refusal when the identity fails, and teeth that
discriminate measurement defect (wrong table) from product residual.
"""

from __future__ import annotations

import importlib.util
import sys
from collections import Counter
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
SCRIPT = _SCRIPTS / "control_effect_recensus.py"


def _load():
    if str(_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS))
    spec = importlib.util.spec_from_file_location("control_effect_recensus", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_conservation_identity_is_stated_on_partition_and_refusal():
    module = _load()
    law = module.WITH_CENSUS_CONSERVATION_IDENTITY
    assert "site:with-item" in law
    assert "constructed" in law
    assert "typed_gaps" in law

    # Conserving case embeds the law.
    ok = module._with_census_partition(
        Counter({"derived-contract": 2, "gap:runtime-selected": 3}),
        Counter({"site:with-item": 5}),
    )
    assert ok["conserves"] is True
    assert ok["conservationIdentity"] == law
    assert ok["unaccounted"] == 0

    # Refusal names the law and which side is short.
    with pytest.raises(ValueError, match="LAW:") as caught:
        module._with_census_partition(
            Counter({"gap:runtime-selected": 12}),
            Counter({"site:with-item": 7915}),
        )
    msg = str(caught.value)
    assert "with_items_total=7915" in msg
    assert "constructed=0" in msg
    assert "typed_gaps=12" in msg
    assert "unaccounted=7903" in msg
    assert "Do not suppress" in msg


def test_known_constructed_with_item_shows_constructed_gt_zero(tmp_path: Path):
    """Planted constructed testimony at a real with-item must tally constructed>0.

    Without this tooth, constructed=0 on a corpus could be an off-by-everything
    counter and still look like product residual. Plants SourceDerived at the
    live use-site (same type With construction consumes) after opening a real
    with-item file — derivation population is not required to validate the tally.
    """
    module = _load()
    from types import SimpleNamespace

    from sugar_lift_py_tests.context_manager_contract import (
        EnterResultContractV1,
        ExitContractV1,
        ImportSignatureV2,
        ProtocolResourceSemanticsV1,
        ReturnTruthinessDispositionV1,
    )
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceDerivedContextManagerRefV1,
        SourceFragmentCoordinateV1,
    )
    from sugar_lift_py_tests.ir import PrimitiveSort
    from sugar_lift_py_tests.lift_rpc import (
        open_source_file_for_construction,
        provisional_contract_refs_from_demands,
        tree_construction_context_for_workspace,
    )
    from sugar_lift_py_tests.outcome import Complete

    path = tmp_path / "consumer.py"
    path.write_text(
        "def consume(mgr):\n"
        "    with mgr:\n"
        "        pass\n",
        encoding="utf-8",
    )
    refs = provisional_contract_refs_from_demands(tmp_path)
    ctx = tree_construction_context_for_workspace(tmp_path, contract_refs=refs)
    source_file = open_source_file_for_construction(
        path, root=tmp_path, construction_context=ctx, populate_derived=False
    )
    # Use-site coordinate from the provisional demand (same seat With uses).
    assert len(refs.by_use_site) == 1
    use_site = next(iter(refs.by_use_site))

    class _Protocol:
        def enter_resource_outcome(self, _ctx=None):
            return Complete(SimpleNamespace(enter_value=None))

        def exit_outcome_for(self, _entered, _ctx=None):
            return Complete(False)

    ctx.source_derived_contract_refs[use_site] = SourceDerivedContextManagerRefV1(
        use_site=use_site,
        summary_cid="blake3-512:" + ("a" * 128),
        semantics=ProtocolResourceSemanticsV1(
            enter=EnterResultContractV1(sort=PrimitiveSort("Value")),
            exit=ExitContractV1(disposition=ReturnTruthinessDispositionV1()),
        ),
        import_signature=ImportSignatureV2(()),
        protocol=_Protocol(),
    )
    buckets, _ = module._tally_cm_resolutions(
        ctx, source_cid=source_file.unit.source_cid
    )
    sites = module._ast_site_prevalence(path)
    assert sites.get("site:with-item", 0) == 1
    assert buckets.get("derived-contract", 0) >= 1, (
        f"known-constructed with must show constructed>0; got {dict(buckets)}"
    )
    partition = module._with_census_partition(buckets, sites)
    assert partition["constructed"] >= 1
    assert partition["conserves"] is True


def test_unconstructed_with_item_appears_in_typed_gap_not_silent_drop(tmp_path: Path):
    """Planted opaque with must land in residual (typed gap), never vanish."""
    module = _load()
    from sugar_lift_py_tests.lift_rpc import (
        open_source_file_for_construction,
        provisional_contract_refs_from_demands,
        tree_construction_context_for_workspace,
    )

    path = tmp_path / "opaque.py"
    path.write_text(
        "def run():\n"
        "    with mystery():\n"
        "        pass\n",
        encoding="utf-8",
    )
    refs = provisional_contract_refs_from_demands(tmp_path)
    ctx = tree_construction_context_for_workspace(tmp_path, contract_refs=refs)
    source_file = open_source_file_for_construction(
        path, root=tmp_path, construction_context=ctx, populate_derived=True
    )
    buckets, _ = module._tally_cm_resolutions(
        ctx, source_cid=source_file.unit.source_cid
    )
    sites = module._ast_site_prevalence(path)
    assert sites.get("site:with-item", 0) == 1
    typed = sum(v for k, v in buckets.items() if k.startswith("gap:"))
    assert typed >= 1, f"unconstructed with must residual; got {dict(buckets)}"
    assert buckets.get("derived-contract", 0) == 0
    partition = module._with_census_partition(buckets, sites)
    assert partition["constructed"] == 0
    assert sum(partition["typed_gaps"].values()) == 1
    assert partition["conserves"] is True


def test_effective_tally_includes_contract_refs_not_only_source_derived(
    tmp_path: Path,
):
    """Measurement defect class: source_derived-only under-counts provisional table."""
    module = _load()
    from sugar_lift_py_tests.lift_rpc import (
        open_source_file_for_construction,
        provisional_contract_refs_from_demands,
        tree_construction_context_for_workspace,
    )

    path = tmp_path / "opaque.py"
    path.write_text(
        "def run():\n"
        "    with mystery():\n"
        "        pass\n",
        encoding="utf-8",
    )
    refs = provisional_contract_refs_from_demands(tmp_path)
    ctx = tree_construction_context_for_workspace(tmp_path, contract_refs=refs)
    source_file = open_source_file_for_construction(
        path, root=tmp_path, construction_context=ctx, populate_derived=True
    )
    # Old defect shape: derived empty, provisional has the gap.
    assert len(ctx.source_derived_contract_refs) == 0
    assert len(refs.by_use_site) == 1
    buckets, _ = module._tally_cm_resolutions(
        ctx, source_cid=source_file.unit.source_cid
    )
    assert sum(buckets.values()) == 1, dict(buckets)
