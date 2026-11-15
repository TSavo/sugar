"""With census conservation: construct-or-panic partition teeth.

Conservation identity (binding):
  site:with-item == constructed + cited-opaque + unconstructed
  over the ``with`` items of the file.

THREE columns because there are three facts (#7384). A cited-opaque With
constructed, so it is not unconstructed; sugar holds no enter/exit contract
for it, so it is not constructed either. Collapsing it into either neighbour
is how a sealed board comes to report knowledge nobody has.

The tally owns canonical coordinate-keyed rows. The partition consumes those
same keys exactly once while splitting the closed constructed/unconstructed
outcomes; deleted resolution kinds and gap buckets never re-enter through a
compatibility decoder.

An item's outcome is what its ``with`` statement built, read off the
construction roll (``with_item_events_off_the_roll``). No table is read
(#7757).
"""

from __future__ import annotations

import importlib.util
import sys
from collections import Counter
from pathlib import Path

import pytest

from sugar_lift_py_tests.repo_root import sugar_lift_py_tests_package_root

_SCRIPTS = sugar_lift_py_tests_package_root() / "scripts"
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


def test_cited_opaque_is_its_own_column_and_conserves():
    """A citation is countable on the board, in neither neighbour's bucket."""
    module = _load()
    rows = [
        *[_resolution_row(index, "constructed") for index in range(1, 3)],
        *[_resolution_row(index, "cited-opaque") for index in range(3, 7)],
        *[_resolution_row(index, "unconstructed") for index in range(7, 9)],
    ]
    partition = module._with_census_partition(rows, Counter({"site:with-item": 8}))
    assert partition["constructed"] == 2
    assert partition["citedOpaque"] == 4
    assert partition["unconstructed"] == 2
    assert partition["conserves"] is True
    assert partition["unaccounted"] == 0
    # The citation is NOT laundered into either neighbour.
    assert len(partition["citedOpaqueRows"]) == 4
    assert all(row["outcome"] == "constructed" for row in partition["constructedRows"])
    assert all(
        row["outcome"] == "unconstructed" for row in partition["unconstructedRows"]
    )
    assert "cited-opaque" in partition["conservationIdentity"]
    assert "4 cited-opaque" in partition["reconciliation"]


def test_a_citation_never_seals_as_a_constructed_contract():
    """The board must not be able to spell a citation 'constructed'.

    If it could, this construct would launder ignorance into apparent
    knowledge -- the one outcome that makes it worse than the refusal it
    replaced (#7384, #7387).
    """
    module = _load()
    rows = [_resolution_row(index, "cited-opaque") for index in range(1, 4)]
    partition = module._with_census_partition(rows, Counter({"site:with-item": 3}))
    assert partition["constructed"] == 0
    assert partition["citedOpaque"] == 3


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
    assert (
        ok["edgeWitness"]["inputKeyManifest"] == ok["edgeWitness"]["outputKeyManifest"]
    )
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


def _with_item(line: int, *, kind: str = "With") -> dict[str, object]:
    """One keyed ``with`` item as the enumerate level states it."""
    return {
        "inputKey": {
            "sourceCid": "sha256:" + ("a" * 64),
            "startLine": line,
            "startCol": 9,
            "endLine": line,
            "endCol": 12,
        },
        "observedEventType": f"sugar_source_tree.nodes.{kind}",
        "statement": {"kind": kind, "line": line, "col": 4},
    }


def _roll(*loci: tuple[str, str, int, int]) -> dict[str, object]:
    """An audit leaf whose roll holds exactly these (status, kind, line, col)."""
    return {
        "auxiliaryRows": {
            "sourceAudit": {
                "loci": [
                    {
                        "status": status,
                        "kind": kind,
                        "name": kind,
                        "source_cid": "sha256:" + ("b" * 64),
                        "locus": {"file": "planted.py", "line": line, "col": col},
                    }
                    for status, kind, line, col in loci
                ]
            }
        }
    }


def test_an_item_is_constructed_when_its_with_answered_present_on_the_roll():
    """Truthful: the statement answered present, so its item is constructed."""
    _load()
    from recensus_enumerate_consumer import with_item_events_off_the_roll

    (event,) = with_item_events_off_the_roll(
        [_with_item(2)], _roll(("warranted", "With", 2, 4))
    )
    assert event["outcome"] == "constructed"
    assert event["inputKey"]["startLine"] == 2
    assert event["observedEventType"] == "sugar_source_tree.nodes.With"


def test_an_item_is_unconstructed_when_its_with_did_not_answer_present():
    """Lying: nothing on the roll says this statement was built."""
    _load()
    from recensus_enumerate_consumer import with_item_events_off_the_roll

    item = _with_item(2)
    # The statement is on the roll, unanswered.
    (refused,) = with_item_events_off_the_roll(
        [item], _roll(("unresolved", "With", 2, 4))
    )
    assert refused["outcome"] == "unconstructed"
    # Some other node answered present at the same place: not this statement.
    (other_kind,) = with_item_events_off_the_roll(
        [item], _roll(("warranted", "Name", 2, 4))
    )
    assert other_kind["outcome"] == "unconstructed"
    # Another ``with`` answered present elsewhere: not this statement.
    (other_place,) = with_item_events_off_the_roll(
        [item], _roll(("warranted", "With", 7, 4))
    )
    assert other_place["outcome"] == "unconstructed"
    # The roll never came back (the audit leaf failed).
    (no_roll,) = with_item_events_off_the_roll([item], None)
    assert no_roll["outcome"] == "unconstructed"


def test_every_item_of_one_statement_shares_its_statements_answer():
    """``with a, b:`` is one statement: both items read the same roll answer."""
    _load()
    from recensus_enumerate_consumer import with_item_events_off_the_roll

    first = _with_item(3)
    second = _with_item(3)
    second["inputKey"] = {**first["inputKey"], "startCol": 14, "endCol": 17}
    events = with_item_events_off_the_roll(
        [first, second], _roll(("warranted", "With", 3, 4))
    )
    assert [event["outcome"] for event in events] == ["constructed", "constructed"]
    assert events[0]["inputKey"] != events[1]["inputKey"]


def test_a_with_that_constructs_is_counted_constructed(tmp_path: Path):
    """Truthful, through the real door: the census counts what was built.

    ``with mgr:`` over a formal constructs from its head alone (the manager
    is what the head reduces to), so its item is ``constructed`` and the file
    ends constructed with no ``with`` left unconstructed.
    """
    module = _load()
    from recensus_enumerate_consumer import measure_file_via_enumerate

    path = tmp_path / "consumer.py"
    path.write_text(
        "def consume(mgr):\n" "    with mgr:\n" "        pass\n",
        encoding="utf-8",
    )
    row = measure_file_via_enumerate(workspace_root=tmp_path, file_rel="consumer.py")

    assert row["terminalKind"] == "constructed", row
    (event,) = row["contextManagerResolutionEvents"]
    assert event["outcome"] == "constructed"
    assert event["observedEventType"] == "sugar_source_tree.nodes.With"

    source_cid = row["inputKey"]["sourceCid"]
    rows = module._tally_cm_resolutions(
        source_cid=source_cid,
        resolution_events=list(row["contextManagerResolutionEvents"]),
    )
    sites = module._ast_site_prevalence(path)
    assert sites.get("site:with-item", 0) == 1
    partition = module._with_census_partition(rows, sites)
    assert partition["constructed"] == 1
    assert partition["unconstructed"] == 0
    assert partition["conserves"] is True


def test_a_with_that_refuses_is_counted_unconstructed(tmp_path: Path):
    """Lying, through the real door: ``async with`` refuses by name, so its
    item is counted, and counted ``unconstructed`` -- never dropped, never
    reported as built."""
    _load()
    from recensus_enumerate_consumer import measure_file_via_enumerate

    path = tmp_path / "refused.py"
    path.write_text(
        "async def consume(mgr):\n" "    async with mgr:\n" "        pass\n",
        encoding="utf-8",
    )
    row = measure_file_via_enumerate(workspace_root=tmp_path, file_rel="refused.py")

    assert row["terminalKind"] == "construction-panic", row
    (event,) = row["contextManagerResolutionEvents"]
    assert event["outcome"] == "unconstructed"
    assert event["observedEventType"] == "sugar_source_tree.nodes.AsyncWith"


def test_enumerate_with_rows_reach_partition_with_identical_keys(
    tmp_path: Path,
) -> None:
    """The production enumerate door and partition conserve the same members."""
    module = _load()
    from recensus_enumerate_consumer import (
        demand_context_manager_resolution_events,
        with_item_events_off_the_roll,
    )
    from sugar_lift_python_source.source_oracle import path_source

    path = tmp_path / "opaque.py"
    path.write_text(
        "def run():\n" "    with mystery():\n" "        pass\n",
        encoding="utf-8",
    )
    source_cid = path_source(str(path))[2]

    items, gaps = demand_context_manager_resolution_events(
        workspace_root=tmp_path,
        file_rel="opaque.py",
        source_cid=source_cid,
    )
    assert gaps == []
    assert len(items) == 1
    # The level keys the item and names its statement; it states no outcome.
    assert "outcome" not in items[0]
    assert items[0]["statement"] == {"kind": "With", "line": 2, "col": 4}
    assert "." in str(items[0]["observedEventType"])

    events = with_item_events_off_the_roll(items, None)
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


def test_the_level_keys_every_with_item_and_constructs_nothing(
    tmp_path: Path,
) -> None:
    """The level keeps the row of a ``with`` whose head is a name bound to a
    call nobody answers.

    It reads the tree, item by item; it does not construct, so it has no
    construction terminal to raise and no outcome to state. The item is one
    row, keyed on its own coordinate, naming the statement that owns it.
    """
    _load()
    from recensus_enumerate_consumer import demand_context_manager_resolution_events
    from sugar_lift_python_source.source_oracle import path_source

    path = tmp_path / "provider.py"
    path.write_text(
        "def run():\n"
        "    handle_data = get_data()\n"
        "    with handle_data as payload:\n"
        "        return payload\n",
        encoding="utf-8",
    )
    source_cid = path_source(str(path))[2]

    items, gaps = demand_context_manager_resolution_events(
        workspace_root=tmp_path,
        file_rel="provider.py",
        source_cid=source_cid,
    )
    assert gaps == []
    assert len(items) == 1, items
    (item,) = items
    assert "outcome" not in item
    # The row is keyed on a coordinate, as every row the partition reads is.
    assert isinstance(item["inputKey"], dict) and item["inputKey"]
    assert item["inputKey"]["sourceCid"] == source_cid
    assert item["statement"] == {"kind": "With", "line": 3, "col": 4}


def test_a_constructed_file_leaves_no_with_unconstructed(
    tmp_path: Path,
) -> None:
    """The board's two readings agree: a file that ends constructed has every
    ``with`` item counted constructed (#7699), and the item is never lost."""
    _load()
    from recensus_enumerate_consumer import measure_file_via_enumerate

    path = tmp_path / "provider.py"
    path.write_text(
        "def run():\n"
        "    handle_data = get_data()\n"
        "    with handle_data as payload:\n"
        "        return payload\n",
        encoding="utf-8",
    )

    row = measure_file_via_enumerate(
        workspace_root=tmp_path,
        file_rel="provider.py",
    )

    assert len(row["contextManagerResolutionEvents"]) == 1
    (event,) = row["contextManagerResolutionEvents"]
    built = row["terminalKind"] == "constructed"
    assert event["outcome"] == ("constructed" if built else "unconstructed"), row
