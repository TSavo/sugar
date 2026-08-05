"""The shard must say WHO it saw, not merely how many rows it emitted (#7374).

PR #7368 built the REQUIREMENT: ``authenticate_relation_membership`` refuses a
partial that carries no membership manifest, and ``mint_partial`` marks that
shard unmeasured with no frontierWidth and no bodyCid. The PRODUCER side did
not exist, so every shard defaulted the argument to ``None`` and the whole
corpus stayed honestly unmeasured.

This is the producer's contract, over the entrance the census actually uses:
an installed distribution, ``measure_file_via_enumerate`` -> ``sugar.enumerate``
-> ``lift_rpc._dispatch_request``. A bare ``SourceFile.from_path`` is a
different door and proves nothing about the census.

The casualty being prevented is #7351: two sealed ``frontierWidth=477``
receipts described their observed run exactly and carried ZERO lexical-call
testimony. A width over an unknown denominator, and no seal failed.

Four facts, four teeth, and each guard dies alone under mutation:

  ATTENDS   a walked file publishes positive, conserved membership for both
            declared relations, and the shard attestation the driver hands
            ``mint_partial`` authenticates clean.
  SILENT    one walked file with no testimony -> NO attestation is minted and
            the reason NAMES that file. The shard stays unmeasured.
  GAP       a refusing roster demand -> the row carries a GAP, never an empty
            population. A shard that cannot say who it saw must not be able to
            look exactly like a shard that saw nobody.
  STRANDED  an enrolled occurrence whose relation READ refuses stays in
            ``expected`` and drops out of ``observed`` -> the seal refuses by
            the name ``relation-membership-missing:<relation>``, which is not
            ``-absent``, not ``-extra``, and not ``-duplicate``.
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
COMPOSE = _load("compose_control_effect_board")

SEAT = "widget/frame.py"
FILE_REL = "widget/frame.py"

# One lexical call (``inner()`` resolves to a FunctionDef binding in the
# enclosing scope) and one target pattern (``for a, b in pairs``). Both
# relations are populated, so neither can pass by being empty.
SOURCE = """\
def outer(pairs):
    def inner():
        return 1

    total = inner()
    seen = pairs.copy()
    for a, b in pairs:
        total = total + a + b + len(seen)
    return total
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
    (package / "frame.py").write_text(SOURCE, encoding="utf-8")
    _recorded_seats.cache_clear()
    return install_root


def _walk_one(install_root: Path) -> dict:
    return CONSUMER.measure_file_via_enumerate(
        workspace_root=install_root,
        file_rel=FILE_REL,
        distribution="widget",
        source_workspace_root=install_root,
    )


def test_a_walked_file_attests_positive_membership_for_both_relations(
    installed_corpus: Path,
) -> None:
    """ATTENDS: the census entrance publishes WHO it saw, and it authenticates."""
    row = _walk_one(installed_corpus)
    assert CONSUMER.RELATION_MEMBERSHIP_GAP_ROW_FIELD not in row, row.get(
        CONSUMER.RELATION_MEMBERSHIP_GAP_ROW_FIELD
    )
    membership = row[CONSUMER.RELATION_MEMBERSHIP_ROW_FIELD]
    assert set(membership) == set(COMPOSE.RELATION_MEMBERSHIP_RELATIONS)
    for relation in COMPOSE.RELATION_MEMBERSHIP_RELATIONS:
        # Positive, not merely well-formed: an empty manifest is the unknown
        # denominator this whole construct exists to make unreachable.
        assert membership[relation]["expected"], relation
        assert membership[relation]["observed"] == membership[relation]["expected"]

    attestation, silence = CONSUMER.shard_relation_membership_attestation(
        [(FILE_REL, row)]
    )
    assert silence is None
    verdict = COMPOSE.authenticate_relation_membership(attestation)
    assert verdict.refusal_reason() is None
    wire = verdict.conserved_wire()
    for relation in COMPOSE.RELATION_MEMBERSHIP_RELATIONS:
        assert wire["relations"][relation]["observed"]["memberCount"] > 0


def test_one_silent_file_refuses_the_whole_shard_attestation_by_name(
    installed_corpus: Path,
) -> None:
    """SILENT: seven files that can testify never absorb one that cannot."""
    row = _walk_one(installed_corpus)
    silent_row = {"category": "completed"}

    attestation, silence = CONSUMER.shard_relation_membership_attestation(
        [(FILE_REL, row), ("widget/silent.py", silent_row)]
    )
    assert attestation is None
    assert silence is not None
    assert "widget/silent.py" in silence

    # And the shard is then honestly unmeasured, by the ABSENT name -- which is
    # a different fact from missing, extra, or duplicate.
    refusal = COMPOSE.authenticate_relation_membership(attestation).refusal_reason()
    assert refusal is not None
    assert refusal.startswith("relation-membership-attestation-absent")


def test_a_refusing_roster_demand_yields_a_gap_never_an_empty_population(
    installed_corpus: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """GAP: absence and lookup-failure never share a representation.

    The forbidden outcome is a well-formed manifest with zero members: it would
    authenticate clean and seal a width over nobody. That is the 477 failure
    with extra ceremony.
    """
    from sugar_source_tree.nodes import SourceUnit

    def _refuse(self):
        raise RuntimeError("roster deliberately unavailable")

    monkeypatch.setattr(SourceUnit, "relation_membership_roster", _refuse)

    row = _walk_one(installed_corpus)
    assert CONSUMER.RELATION_MEMBERSHIP_ROW_FIELD not in row
    gaps = row[CONSUMER.RELATION_MEMBERSHIP_GAP_ROW_FIELD]
    assert gaps
    assert any("roster deliberately unavailable" in str(gap) for gap in gaps)

    attestation, silence = CONSUMER.shard_relation_membership_attestation(
        [(FILE_REL, row)]
    )
    assert attestation is None
    assert silence is not None and FILE_REL in silence


def test_an_enrolled_occurrence_the_table_never_seated_is_named_missing(
    installed_corpus: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """STRANDED: enrolled, never seated -> ``missing``, naming its own relation.

    The lever is the producer's own enrollment mint: a call the walk classified
    ``non-name-callee`` is published ENROLLED while the walk still seats no row
    for it. Roster and table then disagree by exactly one occurrence, which is
    the disagreement the two-sided manifest exists to carry.

    Asserted by the SPECIFIC name. A tooth that merely required "some refusal"
    would survive its own guard's removal on a neighbouring one.
    """
    from sugar_source_tree import backend as backend_module
    from sugar_source_tree.nodes import mint_lexical_call_enrollment

    def _enroll_everything(call_node, reason):
        return mint_lexical_call_enrollment(call_node, None)

    monkeypatch.setattr(
        backend_module, "mint_lexical_call_enrollment", _enroll_everything
    )
    row = _walk_one(installed_corpus)
    membership = row[CONSUMER.RELATION_MEMBERSHIP_ROW_FIELD]
    expected = membership["lexical-call"]["expected"]
    observed = membership["lexical-call"]["observed"]
    assert len(expected) > len(observed), (expected, observed)

    attestation, silence = CONSUMER.shard_relation_membership_attestation(
        [(FILE_REL, row)]
    )
    assert silence is None
    refusal = COMPOSE.authenticate_relation_membership(attestation).refusal_reason()
    assert refusal is not None
    assert "relation-membership-missing:lexical-call" in refusal
    assert "relation-membership-attestation-absent" not in refusal
    assert "relation-membership-extra" not in refusal
    assert "relation-membership-duplicate" not in refusal


@pytest.mark.parametrize(
    "relation", ["lexical-call", "target-pattern"]
)
def test_the_producers_own_members_discriminate_extra_from_duplicate(
    installed_corpus: Path, relation: str
) -> None:
    """Four facts, four names, over the REAL member CIDs this producer mints.

    Not a hand-rolled manifest: these are the occurrence identities the walk
    published, so what the seal discriminates on is what the shard ships.
    """
    row = _walk_one(installed_corpus)
    members = row[CONSUMER.RELATION_MEMBERSHIP_ROW_FIELD]

    def _attest(mutate) -> str | None:
        mutated = {
            name: {
                "expected": list(sides["expected"]),
                "observed": list(sides["observed"]),
            }
            for name, sides in members.items()
        }
        mutate(mutated[relation])
        mutated_row = dict(row)
        mutated_row[CONSUMER.RELATION_MEMBERSHIP_ROW_FIELD] = mutated
        attestation, silence = CONSUMER.shard_relation_membership_attestation(
            [(FILE_REL, mutated_row)]
        )
        assert silence is None
        return COMPOSE.authenticate_relation_membership(attestation).refusal_reason()

    duplicate = _attest(lambda sides: sides["observed"].append(sides["observed"][0]))
    assert duplicate is not None
    assert f"relation-membership-duplicate:{relation}" in duplicate

    extra = _attest(lambda sides: sides["expected"].pop())
    assert extra is not None
    assert f"relation-membership-extra:{relation}" in extra
    assert "relation-membership-duplicate" not in extra

    missing = _attest(lambda sides: sides["observed"].pop())
    assert missing is not None
    assert f"relation-membership-missing:{relation}" in missing
    assert "relation-membership-extra" not in missing


def test_a_roster_asked_before_the_walk_refuses_instead_of_answering_empty() -> None:
    """Nobody looked is not nobody was there.

    Asserted by THIS guard's own owner. "Some refusal" would be satisfied by
    the neighbouring ``constructed_module`` refusal and would survive this
    guard's removal, proving nothing.
    """
    from sugar_source_tree.nodes import SourceUnit

    unit = SourceUnit(source=SOURCE, filename=FILE_REL, source_cid="test-cid")
    with pytest.raises(BaseException) as refused:
        unit.relation_membership_roster()
    text = str(refused.value)
    assert "SourceUnit.relation_membership_roster" in text, text
    assert "enrollment roster was never published" in text, text


def test_two_byte_identical_seats_are_two_populations_not_one(
    tmp_path: Path,
) -> None:
    """#7364: SourceUnits memoize on (source_cid, filename). Members must not.

    Byte-identical files share one source CID. If a member CID did not address
    the SEAT as well as the occurrence, two seats would ship one population --
    compose concatenates shard manifests, so the collision would surface as a
    ``duplicate`` refusal, and a corpus with any repeated file could never
    seal. Attendance is per seat, and this proves the CID says so.
    """
    from sugar_lift_python_source.source_oracle import _recorded_seats

    install_root = tmp_path / "site-packages"
    dist_info = install_root / "widget-1.0.dist-info"
    dist_info.mkdir(parents=True)
    (dist_info / "RECORD").write_text(
        "widget/frame.py,,\nwidget/twin.py,,\n", encoding="utf-8"
    )
    (dist_info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: widget\nVersion: 1.0\n", encoding="utf-8"
    )
    package = install_root / "widget"
    package.mkdir()
    (package / "frame.py").write_text(SOURCE, encoding="utf-8")
    (package / "twin.py").write_text(SOURCE, encoding="utf-8")
    _recorded_seats.cache_clear()

    rows = []
    for seat in ("widget/frame.py", "widget/twin.py"):
        rows.append(
            (
                seat,
                CONSUMER.measure_file_via_enumerate(
                    workspace_root=install_root,
                    file_rel=seat,
                    distribution="widget",
                    source_workspace_root=install_root,
                ),
            )
        )
    assert (
        rows[0][1]["inputKey"]["sourceCid"] == rows[1][1]["inputKey"]["sourceCid"]
    ), "the fixture must actually be byte-identical, or it proves nothing"

    attestation, silence = CONSUMER.shard_relation_membership_attestation(rows)
    assert silence is None
    refusal = COMPOSE.authenticate_relation_membership(attestation).refusal_reason()
    assert refusal is None, refusal
    wire = COMPOSE.authenticate_relation_membership(attestation).conserved_wire()
    for relation in COMPOSE.RELATION_MEMBERSHIP_RELATIONS:
        single = rows[0][1][CONSUMER.RELATION_MEMBERSHIP_ROW_FIELD][relation]
        assert wire["relations"][relation]["observed"]["memberCount"] == 2 * len(
            single["observed"]
        )
