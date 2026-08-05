"""The ROSTER demand must mint the seat the distribution recorded.

`test_recorded_seat_locus_authority` proved two halves separately: the driver
derives the install root (`locus_root_for_corpus`), and the mint refuses a
non-seat locus (`workspace_path_source` -> `require_recorded_seat`). Neither
half touched the CONNECTIVE, and the connective is where the census broke:

    sugar.enumerate level=functions OPENS the file, so it MINTS the locus.
    The driver knew the install root and that demand never received it.

Run 30985305806 shard s1: every one of 178 pandas files came back
``instrument-failure phase=roster-gap``, reason ``... records the seat
`pandas/_testing/_hypothesis.py`, but this locus states
`_testing/_hypothesis.py``` -- completed=0, measured=False, for the whole
shard. Two spellings of one identity, so seat identity never matched.

THE REFUSAL IS CORRECT AND IS PINNED HERE TOO. The fix is not to soften it and
not to translate between spellings at comparison time; it is to state ONE
spelling, minted once, against the root the distribution states seats against.

Both arms, over the entrance the recensus walk actually uses -- the
`sugar.enumerate` request through `lift_rpc._dispatch_request`, reached via the
consumer module loaded by path exactly as the driver loads it:

  ATTRIBUTED  locus root = install root  -> the roster is served, no gap.
  REFUSED     locus root = package root  -> gap, BY NAME, with that reason.
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
    """The driver's own entrance to the consumer: by path, with a sys.modules entry."""
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
RECENSUS = _load("control_effect_recensus")

# The seat the synthetic distribution records, spelled in full. The defect is
# exactly the difference between this and its last segment.
SEAT = "widget/frame.py"
UNSEATED = "frame.py"


@pytest.fixture()
def installed_corpus(tmp_path: Path) -> tuple[Path, Path, str]:
    """One installed distribution: (install root, package root, file_rel).

    Shaped like the pandas corpus that broke: the driver is handed the PACKAGE
    directory as its corpus, while the RECORD states seats against the INSTALL
    root one level up.
    """
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
    (package / "frame.py").write_text(
        "def only_function():\n    return 1\n", encoding="utf-8"
    )
    # The seat table is cached per root; a fresh tmp root each test means no
    # cross-test reuse, but clear so a repeat root can never serve a stale set.
    _recorded_seats.cache_clear()
    return install_root, package, UNSEATED


def _roster(corpus: Path, file_rel: str, locus_root: Path | None):
    return CONSUMER.demand_function_roster(
        workspace_root=corpus,
        file_rel=file_rel,
        source_workspace_root=locus_root,
    )


# -- the premise: the two spellings really are different ----------------------


def test_the_two_roots_state_two_different_addresses(installed_corpus) -> None:
    """Without this, both arms could be measuring one root and prove nothing."""
    install_root, package, _file_rel = installed_corpus
    from sugar_lift_python_source.source_oracle import recorded_seat_for

    assert install_root != package
    assert recorded_seat_for(str(package / "frame.py")) == SEAT
    assert SEAT != UNSEATED
    assert RECENSUS.locus_root_for_corpus(package) == install_root


# -- ARM ONE: a locus that matches the recorded seat is ATTRIBUTED -------------


def test_the_roster_demand_rooted_at_the_install_root_is_served(
    installed_corpus,
) -> None:
    """The whole point: the file's functions come back, with no gap at all."""
    install_root, package, file_rel = installed_corpus

    nodes, gaps = _roster(package, file_rel, install_root)

    assert gaps == [], f"a correctly seated locus must not be refused: {gaps}"
    assert len(nodes) == 1
    assert nodes[0]["memento"]["file"] == file_rel


def test_the_served_terminal_measures_the_file(installed_corpus) -> None:
    """Through the driver's own per-file producer, not the demand alone.

    `measure_file_via_enumerate` is what the recensus loop calls; this pins
    that it FORWARDS the locus root, which is the connective that was missing.
    """
    install_root, package, file_rel = installed_corpus

    row = CONSUMER.measure_file_via_enumerate(
        workspace_root=package,
        file_rel=file_rel,
        distribution="widget",
        source_workspace_root=install_root,
    )

    assert "instrumentFailure" not in row, row.get("instrumentFailure")
    assert row["functionsTotal"] == 1


# -- ARM TWO: a locus that does NOT match is REFUSED, BY NAME -----------------


def test_the_roster_demand_rooted_at_the_package_is_refused_by_name(
    installed_corpus,
) -> None:
    """THE REPRODUCER of run 30985305806 shard s1, one file wide.

    The refusal is the seat law working. It is asserted by its SPECIFIC reason
    text, not by "some gap appeared": a neighbouring refusal (unreadable file,
    outside-root, CID mismatch) must not be able to satisfy this tooth.
    """
    _install_root, package, file_rel = installed_corpus

    nodes, gaps = _roster(package, file_rel, package)

    assert nodes == []
    assert len(gaps) == 1
    reason = gaps[0]["reason"]
    assert f"records the seat `{SEAT}`" in reason
    assert f"this locus states `{UNSEATED}`" in reason
    assert "no other checkout resolves" in reason


def test_an_absent_locus_root_is_refused_the_same_way(installed_corpus) -> None:
    """Omission is not permission. No locus root means the corpus root stands,
    and for an installed corpus that is precisely the unseated address."""
    _install_root, package, file_rel = installed_corpus

    nodes, gaps = _roster(package, file_rel, None)

    assert nodes == []
    assert len(gaps) == 1
    assert f"records the seat `{SEAT}`" in gaps[0]["reason"]


def test_the_refused_locus_becomes_a_roster_gap_terminal(installed_corpus) -> None:
    """The shape the shard actually banked: phase=roster-gap, mass unmeasured.

    Pinned so the class is recognizable in a run log, and so a future change
    that turns this refusal into a silent zero is loud here.
    """
    _install_root, package, file_rel = installed_corpus

    row = CONSUMER.measure_file_via_enumerate(
        workspace_root=package,
        file_rel=file_rel,
        distribution="widget",
        source_workspace_root=package,
    )

    failure = row["instrumentFailure"]
    assert failure["phase"] == "roster-gap"
    assert f"records the seat `{SEAT}`" in str(failure["message"])
    assert row["functionsEnumerated"] == 0


# -- scope: a first-party corpus has no RECORD and is untouched ---------------


def test_a_first_party_corpus_roster_is_served_with_no_locus_root(
    tmp_path: Path,
) -> None:
    """No distribution states an address here, so the corpus root is the whole
    law and this change must not have widened the refusal onto it."""
    package = tmp_path / "firstparty"
    package.mkdir()
    (package / "module.py").write_text(
        "def only_function():\n    return 1\n", encoding="utf-8"
    )

    nodes, gaps = _roster(package, "module.py", None)

    assert gaps == []
    assert len(nodes) == 1
