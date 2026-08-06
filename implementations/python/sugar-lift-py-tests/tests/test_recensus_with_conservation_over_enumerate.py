"""The census door must still conserve With items after every producer change.

This is the instrument #7380 lacked. That change added a
``level=relation-membership`` handler to ``_handle_enumerate`` and, in doing so,
swallowed the terminal ``_send_enumerate_result`` belonging to
``level=context-manager-resolutions``. That level then fell through to the
generic function-memento tail; the consumer dropped every foreign node for
lacking a ``coordinate``; and the corpus census reported ``constructed=0`` for
EVERY With item -- 96 instrument-failures at ``phase=main-file-producer``, all
one cause. Eight green teeth on the producer said nothing, because not one of
them asked the census door a With question.

So these teeth ask it, over the entrance the census actually uses
(``sugar.enumerate`` -> ``lift_rpc._handle_enumerate``), not
``SourceFile.from_path``, which is a different door and proves nothing.

The fixture's context manager is declared IN THE FILE. That is load-bearing: a
``with`` over a runtime-selected manager refuses at
``ContextManagerResolutionConstructionGap`` BEFORE the level ever sends, so
such a fixture answers identically on a healthy and a broken producer and
discriminates nothing. This one reaches the send.

Discrimination, measured rather than asserted -- ``KIND`` and ``CONSERVES``
both pass at c02e41a6d (main) and both FAIL at 904e44075 (the reverted #7380).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from sugar_lift_py_tests.repo_root import sugar_lift_py_tests_package_root

_SCRIPTS = sugar_lift_py_tests_package_root() / "scripts"


def _load(name: str) -> ModuleType:
    if str(_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS))
    path = _SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


CONSUMER = _load("recensus_enumerate_consumer")
DRIVER = _load("control_effect_recensus")

SEAT = "widget/holder.py"
FILE_REL = SEAT

# Two ``with`` statements over a manager this file declares, one of them
# nested in a second function, so a partition that loses only one arm still
# fails. Byte content is unique to this test: SourceUnits memoize by
# (source_cid, workspace-relative seat), and byte-identical fixtures share one
# unit (#7364).
SOURCE = """\
class Guard:
    def __enter__(self):
        return self

    def __exit__(self, kind, value, trace):
        return False


def hold():
    with Guard() as first:
        return first


def hold_again():
    with Guard() as second:
        return second
"""


@pytest.fixture()
def installed_corpus(tmp_path: Path) -> Path:
    """One installed distribution whose RECORD states the seat in full."""
    from sugar_lift_python_source.source_oracle import _recorded_seats

    install_root = tmp_path / "site-packages"
    dist_info = install_root / "widget-1.0.dist-info"
    dist_info.mkdir(parents=True)
    (dist_info / "RECORD").write_text(f"{SEAT},,\n", encoding="utf-8")
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: widget\nVersion: 1.0\n", encoding="utf-8"
    )
    package = install_root / "widget"
    package.mkdir()
    (package / "holder.py").write_text(SOURCE, encoding="utf-8")
    _recorded_seats.cache_clear()
    return install_root


def _source_cid(install_root: Path) -> str:
    row = CONSUMER.measure_file_via_enumerate(
        workspace_root=install_root,
        file_rel=FILE_REL,
        distribution="widget",
        source_workspace_root=install_root,
    )
    cid = (row.get("inputKey") or {}).get("sourceCid")
    assert isinstance(cid, str) and cid, row.get("inputKey")
    return cid


def test_the_cm_level_answers_with_cm_nodes_not_some_other_relations(
    installed_corpus: Path,
) -> None:
    """KIND: read the raw wire, below every consumer filter.

    Asserted on ``enumerate_rpc`` directly rather than on the consumer, so this
    tooth is independent of the consumer's own guard and would have failed at
    904e44075 even with that guard absent.
    """
    cid = _source_cid(installed_corpus)
    result = CONSUMER.enumerate_rpc(
        level="context-manager-resolutions",
        workspace_root=installed_corpus,
        at=CONSUMER.file_memento(file_rel=FILE_REL, source_cid=cid),
        seek=False,
        options={
            "distribution": "widget",
            "sourceWorkspaceRoot": str(installed_corpus),
        },
    )
    nodes = result.get("nodes") or []
    # Positive: an empty answer would satisfy any all() below it.
    assert len(nodes) == 2, nodes
    for node in nodes:
        assert node["memento"]["kind"] == "context-manager-resolution", node
        assert isinstance(node["memento"].get("coordinate"), dict), node


def test_with_items_conserve_through_the_census_enumerate_door(
    installed_corpus: Path,
) -> None:
    """CONSERVES: site:with-item == constructed + unconstructed, real entrance.

    Deliberately indifferent to HOW each item resolves: a file where every item
    is ``unconstructed`` conserves as lawfully as one where every item is
    ``constructed``. What it refuses is the partition losing items, which is
    the only shape the regression took.
    """
    path = installed_corpus / "widget" / "holder.py"
    cid = _source_cid(installed_corpus)
    events, gaps = CONSUMER.demand_context_manager_resolution_events(
        workspace_root=installed_corpus,
        file_rel=FILE_REL,
        source_cid=cid,
        distribution="widget",
        source_workspace_root=installed_corpus,
    )
    assert gaps == [], gaps

    sites = DRIVER._ast_site_prevalence(path)
    # The denominator is real: with no With items, a partition that drops
    # everything would conserve 0 == 0 + 0 and pass.
    assert int(sites.get("site:with-item", 0)) == 2, dict(sites)

    resolution_rows = DRIVER._tally_cm_resolutions(
        source_cid=cid, resolution_events=list(events)
    )
    # _with_census_partition RAISES on a shortfall, and that raise is the
    # census's own instrument-failure. Calling it is the assertion.
    partition = DRIVER._with_census_partition(resolution_rows, sites)

    assert partition["with_items_total"] == 2
    assert partition["accounted"] == 2
    assert partition["unaccounted"] == 0
    assert partition["constructed"] + partition["unconstructed"] == 2


def test_a_foreign_node_kind_is_named_not_silently_dropped(
    installed_corpus: Path,
) -> None:
    """LOUD: the regression's silent step, made to speak.

    #7380 did not fail at the producer; it failed at this filter, which threw
    away every node lacking a ``coordinate`` and left the caller reading a
    well-formed empty table. Absence and wrong-answer must not share one
    representation.
    """
    real = CONSUMER.enumerate_rpc

    def foreign(**kwargs):
        if kwargs.get("level") == "context-manager-resolutions":
            return {
                "nodes": [
                    {
                        "memento": {"kind": "source-memento", "function_name": "hold"},
                        "audit": None,
                        "payload": None,
                    }
                ],
                "gaps": [],
            }
        return real(**kwargs)

    CONSUMER.enumerate_rpc = foreign
    try:
        with pytest.raises(TypeError) as caught:
            CONSUMER.demand_context_manager_resolution_events(
                workspace_root=installed_corpus,
                file_rel=FILE_REL,
                source_cid="cid-does-not-matter-here",
                distribution="widget",
                source_workspace_root=installed_corpus,
            )
    finally:
        CONSUMER.enumerate_rpc = real

    message = str(caught.value)
    assert "answered with a foreign node kind" in message
    assert "'source-memento'" in message
