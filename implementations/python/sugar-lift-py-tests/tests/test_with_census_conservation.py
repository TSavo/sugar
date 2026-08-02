"""With census conservation: construct-or-panic partition teeth.

Conservation identity (binding):
  site:with-item == constructed + unconstructed
  over the effective use-site set With construction sees.

The tally owns canonical coordinate-keyed rows. The partition consumes those
same keys exactly once while splitting the closed constructed/unconstructed
outcomes; deleted resolution kinds and gap buckets never re-enter through a
compatibility decoder.
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


def _resolution_row(index: int, outcome: str) -> dict[str, object]:
    return {
        "inputKey": {
            "sourceCid": "sha256:" + ("a" * 64),
            "startLine": index,
            "startCol": 4,
            "endLine": index,
            "endCol": 8,
        },
        "observedEventType": "tests.PlantedResolution",
        "outcome": outcome,
    }


def test_conservation_identity_is_stated_on_partition_and_refusal():
    module = _load()
    law = module.WITH_CENSUS_CONSERVATION_IDENTITY
    assert "site:with-item" in law
    assert "constructed" in law
    assert "unconstructed" in law

    # Conserving case embeds the law.
    rows = [
        *[_resolution_row(index, "constructed") for index in range(1, 3)],
        *[_resolution_row(index, "unconstructed") for index in range(3, 6)],
    ]
    ok = module._with_census_partition(
        rows,
        Counter({"site:with-item": 5}),
    )
    assert ok["conserves"] is True
    assert ok["conservationIdentity"] == law
    assert ok["unaccounted"] == 0
    assert ok["accounted"] == 5
    assert ok["unconstructed"] == 3
    assert ok["edgeWitness"]["inputKeyManifest"] == ok["edgeWitness"][
        "outputKeyManifest"
    ]
    assert ok["edgeWitness"]["missingKeys"] == []
    assert ok["edgeWitness"]["extraKeys"] == []
    assert "typed_gaps" not in ok
    assert "typed_gap_kinds_total" not in ok
    assert "unrecognized_resolution_kinds" not in ok

    # Refusal names the law and which side is short.
    with pytest.raises(ValueError, match="LAW:") as caught:
        module._with_census_partition(
            [_resolution_row(index, "unconstructed") for index in range(12)],
            Counter({"site:with-item": 7915}),
        )
    msg = str(caught.value)
    assert "with_items_total=7915" in msg
    assert "constructed=0" in msg
    assert "unconstructed=12" in msg
    assert "unaccounted=7903" in msg
    assert "Construct or panic" in msg


def test_partition_rejects_deleted_resolution_vocabulary() -> None:
    module = _load()
    with pytest.raises(TypeError, match="closed outcomes"):
        module._with_census_partition(
            [_resolution_row(1, "derived-contract")],
            Counter({"site:with-item": 1}),
        )


def test_partition_rejects_duplicate_coordinate_rows() -> None:
    module = _load()
    row = _resolution_row(1, "constructed")
    with pytest.raises(TypeError, match="duplicate"):
        module._with_census_partition(
            [row, row],
            Counter({"site:with-item": 2}),
        )


def test_cm_zero_requires_separate_key_attestation() -> None:
    module = _load()
    with pytest.raises(ValueError, match="key attestation"):
        module._attested_cm_counts({"cmResolutions": {}})

    measured_zero = module._with_census_partition(
        [],
        Counter({"site:with-item": 0}),
    )
    assert module._attested_cm_counts(
        {
            "cmResolutions": {"constructed": 0, "unconstructed": 0},
            "withCensus": measured_zero,
        }
    ) == (0, 0)


def test_seal_board_additive_legacy_reads_remain_reconciled() -> None:
    compose_path = _SCRIPTS / "compose_control_effect_board.py"
    source = compose_path.read_text(encoding="utf-8")
    assert 'cm.get("constructed", 0) + cm.get("derived-contract", 0)' in source
    assert 'cm.get("unconstructed", 0)' in source
    assert 'str(k).startswith("gap:")' in source


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
    rows = module._tally_cm_resolutions(
        ctx, source_cid=source_file.unit.source_cid
    )
    sites = module._ast_site_prevalence(path)
    assert sites.get("site:with-item", 0) == 1
    assert sum(row["outcome"] == "constructed" for row in rows) >= 1, rows
    partition = module._with_census_partition(rows, sites)
    assert partition["constructed"] >= 1
    assert partition["conserves"] is True


def test_unconstructed_with_item_is_counted_not_silently_dropped(tmp_path: Path):
    """Planted opaque With must remain present as unconstructed, never vanish."""
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
    rows = module._tally_cm_resolutions(
        ctx, source_cid=source_file.unit.source_cid
    )
    sites = module._ast_site_prevalence(path)
    assert sites.get("site:with-item", 0) == 1
    assert sum(row["outcome"] == "unconstructed" for row in rows) == 1, rows
    assert sum(row["outcome"] == "constructed" for row in rows) == 0
    partition = module._with_census_partition(rows, sites)
    assert partition["constructed"] == 0
    assert partition["unconstructed"] == 1
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
    rows = module._tally_cm_resolutions(
        ctx, source_cid=source_file.unit.source_cid
    )
    assert len(rows) == 1, rows


def test_enumerate_with_rows_reach_partition_with_identical_keys(
    tmp_path: Path,
) -> None:
    """The production enumerate door and partition conserve the same members."""
    module = _load()
    from recensus_enumerate_consumer import demand_context_manager_resolution_events
    from sugar_lift_py_tests.lift_rpc import (
        install_provisional_contract_refs,
        provisional_contract_refs_from_demands,
    )
    from sugar_lift_python_source.source_oracle import path_source

    path = tmp_path / "opaque.py"
    path.write_text(
        "def run():\n"
        "    with mystery():\n"
        "        pass\n",
        encoding="utf-8",
    )
    refs = provisional_contract_refs_from_demands(tmp_path)
    install_provisional_contract_refs(tmp_path, refs)
    source_cid = path_source(str(path))[2]

    events, gaps = demand_context_manager_resolution_events(
        workspace_root=tmp_path,
        file_rel="opaque.py",
        source_cid=source_cid,
    )
    assert gaps == []
    assert len(events) == 1
    assert events[0]["outcome"] == "unconstructed"
    assert "." in str(events[0]["observedEventType"])

    rows = module._tally_cm_resolutions(
        source_cid=source_cid,
        resolution_events=events,
    )
    partition = module._with_census_partition(
        rows,
        module._ast_site_prevalence(path),
    )
    event_keys = [event["inputKey"] for event in events]
    row_keys = [row["inputKey"] for row in rows]
    edge = partition["edgeWitness"]
    assert event_keys == row_keys
    assert edge["inputKeyManifest"] == row_keys
    assert edge["outputKeyManifest"] == row_keys
    assert edge["missingKeys"] == []
    assert edge["extraKeys"] == []
    assert edge["duplicateKeys"] == []
