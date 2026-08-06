"""RED: "foreign OR absent" is two faults sharing one representation.

``retain_registered_node_from`` refused the pandas aggregate with::

    observed: foreign or absent producer node registration
              (producer=NullReporter, node_reporter=NullReporter)

Those are not one fault:

* ABSENT -- the producer is a reporter that owns no registration table at all
  (``NullReporter``, or any reporter that is neither authenticated kind). No
  node it ever carried is registered anywhere. This is a SEATING defect: some
  door opened a construction tree without a channel. Nothing at the retention
  site can repair it.
* FOREIGN -- the producer IS a registering reporter, but the node this consumer
  was handed is not the occurrence that producer registered. This is an
  IDENTITY defect: a remint, a rematerialized view, or a node from another roll.

Absence and lookup-failure must never share a representation. Both arms stay
loud ``BackendDefect``; the refusal now says WHICH, so the next reader is not
made to guess between "seat a reporter" and "stop reminting".

BOTH ARMS. Each test below is proved against its own guard: removing the absent
classification must not be survivable by the foreign refusal, and removing the
retention check entirely must fail both.
"""

from __future__ import annotations

import pytest

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.binding_state import (
    ConstructionTestimonyReporterV1,
    SubstitutionTraceBuilderV1,
)
from sugar_source_tree.nodes import FunctionDef
from sugar_source_tree.panic import BackendDefect
from sugar_source_tree.reporter import CollectingReporter, NullReporter
from sugar_source_tree.tree import SourceFile

OWNER = "ConstructionTestimonyReporterV1.retain_registered_node_from"
SOURCE = "def exact():\n    return 1\n"


def _opened(name: str) -> tuple[SourceFile, FunctionDef, CollectingReporter]:
    collector = CollectingReporter()
    tree = SourceFile(
        (SOURCE, name, blake3_512_of(SOURCE.encode())), reporter=collector
    )
    definition = next(n for n in tree.nodes() if isinstance(n, FunctionDef))
    assert definition.reporter is collector
    return tree, definition, collector


def _consumer(tree: SourceFile) -> ConstructionTestimonyReporterV1:
    return ConstructionTestimonyReporterV1(
        CollectingReporter(), SubstitutionTraceBuilderV1(tree.unit.source_cid)
    )


def test_absent_arm_names_the_missing_registration_table() -> None:
    """GUARD (absent): a producer that owns no table says so, and says seating.

    This is the exact arm the pandas aggregate hit. It must not read as an
    identity problem, because no identity work can fix it.
    """
    tree, definition, _collector = _opened("retain_absent.py")
    with pytest.raises(BackendDefect) as gap:
        _consumer(tree).retain_registered_node_from(definition, NullReporter())
    assert gap.value.owner == OWNER
    assert "producer reporter owns no registration table" in gap.value.observed, (
        f"the absent arm must name the missing table; got {gap.value.observed!r}"
    )
    assert "NullReporter" in gap.value.observed
    assert "seat" in gap.value.fix, (
        "the absent arm must send the reader to the door that opened the tree"
    )


def test_foreign_arm_names_the_wrong_occurrence() -> None:
    """GUARD (foreign): a registering producer that did not register THIS node.

    ``other_collector`` is a real ``CollectingReporter`` -- it owns a roster.
    It simply is not the reporter ``definition`` was opened with. That is a
    different fault from absence and must read differently.
    """
    tree, definition, _collector = _opened("retain_foreign.py")
    other_collector = CollectingReporter()
    with pytest.raises(BackendDefect) as gap:
        _consumer(tree).retain_registered_node_from(definition, other_collector)
    assert gap.value.owner == OWNER
    assert "foreign producer node registration" in gap.value.observed, (
        f"the foreign arm must name the wrong occurrence; got {gap.value.observed!r}"
    )
    assert "producer reporter owns no registration table" not in gap.value.observed, (
        "a producer that owns a roster must not be reported as having no table"
    )


def test_the_two_arms_do_not_share_a_representation() -> None:
    """GUARD: the discriminator itself.

    Both arms above pass if the refusal emits one message containing both
    phrases. This runs the two inputs and refuses equal observations -- the
    exact conflation ("foreign OR absent") that was there before.
    """
    tree, definition, _collector = _opened("retain_split.py")
    with pytest.raises(BackendDefect) as absent:
        _consumer(tree).retain_registered_node_from(definition, NullReporter())
    with pytest.raises(BackendDefect) as foreign:
        _consumer(tree).retain_registered_node_from(definition, CollectingReporter())

    def _fault(observed: str) -> str:
        # The FAULT NAMED, not the raw string. Comparing raw strings is
        # answered by the incidental `producer=<type>` suffix, so two inputs
        # collapsed onto one refusal would still look distinct.
        named = {
            phrase
            for phrase in (
                "producer reporter owns no registration table",
                "foreign producer node registration",
            )
            if phrase in observed
        }
        assert len(named) == 1, (
            f"a refusal must name exactly one fault; {observed!r} names {named}"
        )
        return next(iter(named))

    assert _fault(absent.value.observed) != _fault(foreign.value.observed), (
        "absence and lookup-failure still share one representation: both "
        f"report {_fault(absent.value.observed)!r}"
    )


def test_the_lawful_producer_is_still_retained() -> None:
    """GUARD: the split did not clear the arms by accepting everything.

    Three refusal teeth are all satisfied by a check that refuses every
    producer. The lawful file-open door must still retain, by identity.
    """
    tree, definition, collector = _opened("retain_lawful.py")
    consumer = _consumer(tree)
    retained = consumer.retain_registered_node_from(definition, collector)
    assert retained is definition
    assert consumer.materialized_node_for_ref(definition.ref) is definition
