"""A constructed value whose testimony cannot be content-addressed stays LOUD.

``ConstructionTestimonyReporterV1.present_construction`` used to have two
silent ``return`` doors: one when the node's construction-shape CID would not
canonicalize, one when the constructed value would not. Either one left a
falsely green construction coordinate -- the node registered, construction
succeeded, testimony serialization failed, and the failure disappeared. (The
measured proof it was hiding real work: teaching canonicalization to serialize
a Node by its construction-shape CID moved pandas ``__internal_pivot_table``
from 364s to 976s, because canonicalization that used to abort early now
completes.)

There is no third arm now:

    canonicalization succeeds -> present testimony
    canonicalization fails    -> report the gap, THEN raise the typed panic

The gap is testified through the SAME roll call the census reads, and
``Node.sugar`` raises before recording the present answer, so conservation is
atomic: exactly one discharge per coordinate, and it is the loud absent one.
"""

import os
import tempfile

from sugar_source_tree.backend import materialize
from sugar_source_tree.binding_state import (
    ConstructionTestimonyReporterV1,
    SubstitutionTraceBuilderV1,
)
from sugar_source_tree.nodes import KIND_REGISTRY
from sugar_source_tree.panic import (
    ConstructedValueTestimonyNotWritten,
    SugarNotWritten,
)
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.tree import SourceFile

_SCOPE_CID = "blake3-512:" + "0" * 8


class Unserializable:
    """A constructed value category canonicalization has not been taught.

    Not a dataclass, no authenticated native CID -- exactly the shape that
    made canonicalization raise in production (``unserializable constructed
    value LineTable``), and that ConstructedValueV2 reports as the typed
    ``ConstructedValueCategoryGap`` rather than reflecting over.
    """


def _module(src):
    d = tempfile.mkdtemp()
    p = os.path.join(d, "m.py")
    with open(p, "w") as fh:
        fh.write(src)
    return p


def _testimony_tree(src):
    """One module materialized under a testimony reporter over a collector."""
    path = _module(src)
    collector = CollectingReporter()
    sf = SourceFile.from_path(path, reporter=collector)
    reporter = ConstructionTestimonyReporterV1(
        collector, SubstitutionTraceBuilderV1(_SCOPE_CID)
    )
    root = materialize(sf.root.unit, sf.root.ref, reporter)
    return root, reporter, collector


def _first(root, kind):
    for node in root.walk():
        if node.kind == kind:
            return node
    raise AssertionError(f"no {kind} in fixture")


def _unsupported_constructing(kind):
    """Patch ONE node class to construct a value of an untaught category."""
    cls = KIND_REGISTRY[kind]
    original = cls._construct_sugar

    def _construct(self):
        return Unserializable()

    cls._construct_sugar = _construct
    return cls, original


def test_unsupported_constructed_value_is_a_typed_loud_gap():
    # Skip door #2: the value does not canonicalize. Never a silent return.
    root, reporter, collector = _testimony_tree("x = 1\n")
    node = _first(root, "Constant")
    try:
        reporter.present_construction(node, Unserializable())
    except ConstructedValueTestimonyNotWritten as panic:
        assert panic.owner == "CollectingReporter.present_construction"
        assert "Unserializable" in panic.observed
        assert "constructed value" in panic.observed
        assert panic.requested == "content-addressable constructed-value testimony"
        assert "teach canonicalization" in panic.fix
    else:
        raise AssertionError("failed testimony returned silently")
    # ...and it is a SugarNotWritten, so the census counts it on the frontier
    # rather than seeing a native crash.
    assert issubclass(ConstructedValueTestimonyNotWritten, SugarNotWritten)
    assert len(collector.gaps) == 1
    assert collector.gaps[0][0] is node


def test_both_outcomes_are_remembered_at_the_same_coordinate():
    # Present and absent are symmetric at the shape coordinate: a testified
    # shape is not recomputed, and a FAILED shape re-raises the SAME typed
    # panic -- without adding roll-call mass, because the gap was testified
    # once, when it happened.
    root, reporter, collector = _testimony_tree("x = 1\n")
    node = _first(root, "Constant")
    first = second = None
    try:
        reporter.present_construction(node, Unserializable())
    except ConstructedValueTestimonyNotWritten as panic:
        first = panic
    try:
        reporter.present_construction(node, Unserializable())
    except ConstructedValueTestimonyNotWritten as panic:
        second = panic
    assert first is not None and second is not None
    assert first is second
    assert len(collector.gaps) == 1, collector.gaps


def test_supported_node_valued_construction_still_canonicalizes():
    # Regression guard for the fix that made this loud path reachable: a
    # constructed value legitimately CARRYING a Node canonicalizes by that
    # node's construction-shape CID (it must not field-walk into unit ->
    # SourceUnit -> LineTable and fail).
    root, reporter, _ = _testimony_tree("x = 1\n")
    node = _first(root, "Constant")
    reporter.present_construction(node, {"held": node})
    testimony = reporter.testimony_for(node)
    assert testimony is not None
    assert testimony.cid.startswith("blake3-512:")


def test_gap_is_recorded_once_and_the_node_registers_once():
    # Conservation, atomically: one registered coordinate, exactly one
    # discharge, and that discharge is the loud absent one -- never a present
    # answer beside it.
    cls, original = _unsupported_constructing("Constant")
    try:
        root, reporter, collector = _testimony_tree("x = 1\n")
        node = _first(root, "Constant")
        try:
            node.sugar()
        except ConstructedValueTestimonyNotWritten:
            pass
        else:
            raise AssertionError("construction stayed green")
        coordinate = {id(n.ref) for n in collector.registered if n.kind == "Constant"}
        assert len(coordinate) == 1, coordinate
        assert len(collector.gaps) == 1, collector.gaps
        assert [n for n in collector.present if n.ref is node.ref] == []
    finally:
        cls._construct_sugar = original


def test_repeated_sugar_reraises_the_memoized_panic_without_new_roll_mass():
    # The coordinate memo remembers the panic. A gap stays a gap on every
    # call -- the SAME panic object -- and re-asking must not multiply the
    # roll-call mass the census counts.
    cls, original = _unsupported_constructing("Constant")
    try:
        root, reporter, collector = _testimony_tree("x = 1\n")
        node = _first(root, "Constant")
        first = second = None
        try:
            node.sugar()
        except ConstructedValueTestimonyNotWritten as panic:
            first = panic
        gaps_after_first = len(collector.gaps)
        try:
            node.sugar()
        except ConstructedValueTestimonyNotWritten as panic:
            second = panic
        assert first is not None and second is not None
        assert first is second, "the memo must re-raise the SAME panic"
        assert len(collector.gaps) == gaps_after_first == 1
    finally:
        cls._construct_sugar = original


def test_no_reporter_silently_returns_from_failed_testimony_construction():
    # Every reporter that CAN build testimony must have no silent-return door.
    # ``NullReporter`` / ``CollectingReporter`` build none at all (nothing can
    # fail); the testimony reporter is the only one that canonicalizes, and its
    # two doors are checked above. This twin pins that no NEW silent door
    # appears in its body.
    import inspect

    from sugar_source_tree import binding_state

    source = inspect.getsource(
        binding_state.ConstructionTestimonyReporterV1.present_construction
    )
    for handler in ("except (TypeError, ValueError)", "except Exception"):
        if handler in source:
            body = source.split(handler, 1)[1]
            assert "_testimony_gap" in body.split("\n\n", 1)[0], source
    assert source.count("return") == 1, "only the content-addressed memo returns"


def test_no_raw_typeerror_or_valueerror_escapes():
    root, reporter, _ = _testimony_tree("x = 1\n")
    node = _first(root, "Constant")
    try:
        reporter.present_construction(node, Unserializable())
    except (TypeError, ValueError) as raw:
        raise AssertionError(f"raw {type(raw).__name__} escaped: {raw}")
    except ConstructedValueTestimonyNotWritten:
        pass
