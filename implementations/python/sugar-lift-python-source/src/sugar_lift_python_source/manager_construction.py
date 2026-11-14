"""Import call seats and constructed manager behavior.

An imported call is a coordinate plus an edge: no route here reads an
imported callee's body, and no file is opened here. A file becomes a node
tree one way, the one opener over step 2's file list
(``sugar_lift_py_tests.lift_rpc.open_source_file_for_construction``). The
module-prefix door and the lexical import runner, which opened a dependency
module a second way with their own context, are gone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from sugar_lift_py_tests.context_manager_resolution import (
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.floor import (
    FloorValue,
    ObjectValue,
    ReceiverStatePartitionValue,
)
from sugar_lift_py_tests.ir import _term_content_cid
from sugar_source_tree.binding_state import BindingEntryV1
from sugar_source_tree.nodes import Call

from .canonical import cid_of_json
from .dependency_artifact import DependencyArtifactGraph
from .resolution_session import SourceResolutionSession


def _dependency_graph_for_top(
    top_level: str,
    *,
    session: SourceResolutionSession,
    dependency_graphs: dict[str, DependencyArtifactGraph],
    distribution_index=None,
) -> DependencyArtifactGraph:
    """Authenticate ``top_level`` once per session (and local map)."""
    hit = dependency_graphs.get(top_level)
    if hit is not None:
        return hit
    if session.enabled:
        hit = session.dependency_graphs.get(top_level)
        if hit is not None:
            dependency_graphs[top_level] = hit
            return hit
    from .dependency_artifact import authenticate_dependency_top_level

    graph = authenticate_dependency_top_level(
        top_level, distribution_index=distribution_index
    )
    dependency_graphs[top_level] = graph
    if session.enabled:
        session.dependency_graphs[top_level] = graph
    return graph


@dataclass(frozen=True)
class ConstructedManagerBehaviorV1:
    resolved_object_cid: str
    manager_construction_cid: str
    receiver_state: ObjectValue | ReceiverStatePartitionValue = field(compare=False)
    receiver_state_cid: str
    formal_actual_bindings: tuple[BindingEntryV1, ...]
    source_call_frame_cid: str
    formal_actual_values: tuple[FloorValue, ...] = field(default=(), compare=False)
    source_call_frame: object | None = field(default=None, compare=False, repr=False)
    factory_prefix: tuple[FloorValue, ...] = field(default=(), compare=False)
    factory_prefix_cids: tuple[str, ...] = ()

    @property
    def preimage(self):
        return {
            "kind": "constructed-manager-behavior",
            "schemaVersion": "1",
            "resolvedObjectCid": self.resolved_object_cid,
            "receiverStateCid": self.receiver_state_cid,
            "formalActualBindings": [
                item.wire() for item in self.formal_actual_bindings
            ],
            "sourceCallFrameCid": self.source_call_frame_cid,
            "factoryPrefixCids": list(self.factory_prefix_cids),
        }

    def __post_init__(self) -> None:
        if self.receiver_state.identity != self.receiver_state_cid:
            raise ValueError("receiver state CID does not match ordinary construction")
        if cid_of_json(self.preimage) != self.manager_construction_cid:
            raise ValueError("manager construction CID does not match its preimage")
        if self.formal_actual_values:
            if len(self.formal_actual_values) != len(self.formal_actual_bindings):
                raise ValueError("formal actual value/binding arity mismatch")
            for value, entry in zip(
                self.formal_actual_values, self.formal_actual_bindings, strict=True
            ):
                testimony = entry.sealed_state.testimony
                if (
                    testimony is None
                    or testimony.semantic_value_cid
                    != _term_content_cid(value.to_term(owner=self.resolved_object_cid))
                ):
                    raise ValueError("formal actual value lacks matching testimony")
        if self.source_call_frame is not None and (
            self.source_call_frame.frame_cid != self.source_call_frame_cid
        ):
            raise ValueError("source call frame CID mismatch")


# The four conditions that ``opaque-call-target`` used to fuse into one name.
#
# ``opaque-call-target`` named a *symptom* -- "construction could not see through
# this call" -- and four structurally different conditions arrived under it, three
# of them carrying a callee spelling as their detail.  Each is decided here by a
# condition construction already evaluates; none reads a name table.
#
# ``call-graph-cycle``
#     Re-entry of a frame already being projected, a returned-callsite cycle, or a
#     fixpoint that stops making progress.  Carries NO symbol.  The fix is a cycle
#     policy.
# ``value-call-target``
#     The callee is bound by the enclosing definition itself -- a parameter or a
#     local -- so it is a runtime VALUE.  Higher-order dispatch.  No export lookup
#     can ever resolve it, because there is nothing to look up.  The fix is a
#     capability, not coverage.
# ``call-target-source-absent``
#     The authenticated export door declined the name: no defining source for it
#     inside this distribution artifact.  An artifact-COVERAGE gap.
# ``call-target-export-unresolved``
#     The export door DID authenticate an object in this artifact, but projecting
#     its frame failed.  A defect in the door, not a coverage gap -- and invisible
#     for as long as it shares a bucket with the other three.
# ``call-target-off-population``
#     The export door authenticated a defining source, but that source is outside
#     the enrolled measurement population (stdlib / off-pin).  Cite via the opaque
#     obligation path; do NOT MaterializeModule / ClassDef.sugar the unenrolled
#     module.  Successful resolution used to be punished with a full rebuild
#     while failure already cited -- the population membrane closes that hole.

@dataclass(frozen=True)
class ManagerConstructionGapV1:
    kind: Literal[
        "artifact-mismatch",
        "definition-missing",
        "call-graph-cycle",
        "value-call-target",
        "call-target-source-absent",
        "call-target-export-unresolved",
        "call-target-off-population",
        "non-manager-result",
        "call-binding",
        "force-floor",
    ]
    resolved_object_cid: str
    detail: str


def _graph_is_off_population(
    graph: "DependencyArtifactGraph | None",
    *,
    session: SourceResolutionSession | None = None,
    module_name: str | None = None,
) -> bool:
    """True when ``graph`` is outside the enrolled measurement population.

    This is the one answer to "is this callee bridged": the lifter has it
    only when an authenticated artifact holds its source AND the population
    enrolls that source.  A graph that holds no source for ``module_name``
    does not have it.  ``graph=None`` means no artifact authenticates
    ``module_name``'s top-level module at all, so the lifter does not have
    it either: it is not bridged, whatever it is implemented in.

    The roster (``session.enrolled_distributions``) is step 2's file list
    (``project_file_roster``): the content CID of every file the lift lists,
    and nothing else. No distribution is enrolled by name and no module by a
    module-scoped entry. A module is enrolled only when the source its
    artifact seats for it is one of those files. An installed module outside
    the file list is not population, even when the opened code imports it:
    an imported call is a coordinate plus an edge, answered by an imported
    proof, and its body is never lifted (#7796). Without ``module_name`` only
    a listed file of the graph admits.
    """
    if session is None:
        raise TypeError(
            "population classification requires an enrolled distribution roster"
        )
    roster = session.enrolled_distributions
    if graph is None:
        return bool(module_name)
    if not module_name:
        return not any(item.content_cid in roster for item in graph.files)
    source_cid = graph.modules.source_cid_of(module_name)
    if source_cid is None:
        # The artifact authenticates, but holds no source for this module
        # (an extension file, or a module it never ships): the lifter does
        # not have it, enrolled or not.
        return True
    return source_cid not in roster


def _floor_tuple_construct_fields(
    receiver: ObjectValue | ReceiverStatePartitionValue,
    actuals: tuple[FloorValue, ...],
) -> ObjectValue | ReceiverStatePartitionValue:
    """Project bodyless ``tuple(...)`` field stores to TupleValue when decidable.

    RaisesExc writes ``self.expected_exceptions = tuple(_parse_exc(e) for e in ...)``.
    That store may remain a bodyless CallSiteValue or complete as a
    TupleCoordinateValue whose source is the same generator. When the generator
    cannot yet project finite_elements (iterable still a
    branch-result conditional) but the callsite supplied exactly one authenticated
    class actual, the source-visible non-tuple/non-None arm is exactly
    ``(actual,)`` after ``_parse_exc`` identity for BaseException types.

    The same one-class arm is also the else of ``isinstance(..., tuple)`` /
    ``is None`` before that parse, stored as a nested GuardedValue whose
    leaves are the raw class, ``()``, and ``(actual,)``. Floor that field so
    ``not self.expected_exceptions`` / ``len`` / ``[0]`` / exit derivation
    see a TupleValue rather than indexing the empty None arm.
    """
    if isinstance(receiver, ObjectValue):
        return _floor_object_tuple_fields(receiver, actuals)
    from sugar_lift_py_tests.outcome import ExitSet

    changed = False

    def floored(value):
        # Each completed face continues as its floored receiver beneath
        # itself (``ExitSet.sequence``), keeping its guard, faces and
        # ``owed``. A constructor halt stands.
        nonlocal changed
        if isinstance(value, (ObjectValue, ReceiverStatePartitionValue)):
            result = _floor_tuple_construct_fields(value, actuals)
            if result is not value:
                changed = True
            value = result
        return ExitSet.completed(value)

    exits = receiver.exits.sequence(floored)
    if not changed:
        return receiver
    return ReceiverStatePartitionValue(exits)


def _floor_object_tuple_fields(
    obj: ObjectValue, actuals: tuple[FloorValue, ...]
) -> ObjectValue:
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.floor.class_value import ClassValue
    from sugar_lift_py_tests.floor.comprehension_value import ComprehensionValue
    from sugar_lift_py_tests.floor.object_value import ObjectField
    from sugar_lift_py_tests.floor.tuple_value import TupleValue

    class_actuals = tuple(item for item in actuals if isinstance(item, ClassValue))
    fields_by_name = {field.name: field.value for field in obj.fields}
    changed = False
    for name, value in list(fields_by_name.items()):
        floored = _floor_one_tuple_callsite(value, class_actuals)
        if floored is None:
            floored = _floor_one_guarded_tuple_wrap(value, class_actuals)
        if floored is not None:
            fields_by_name[name] = floored
            changed = True
    if not changed:
        return obj
    return ObjectValue(
        obj.class_name,
        tuple(
            ObjectField(name, fields_by_name[name]) for name in sorted(fields_by_name)
        ),
        obj.methods,
        obj.class_fields,
        obj.identity,
        obj.deferred_helper_fields,
        obj.deleted_instance_fields,
        obj.defining_class,
        # The same object: it keeps its ``allocation`` and ``arrival``.
        allocation=obj.allocation,
        arrival=obj.arrival,
    )


def _floor_one_guarded_tuple_wrap(
    value: FloorValue, class_actuals: tuple[FloorValue, ...]
) -> FloorValue | None:
    """Select ``(actual,)`` from an isinstance/None wrap stored as GuardedValue.

    For one authenticated class actual the wrap's leaves are the raw class
    (isinstance-true), ``()`` (None), and ``(actual,)`` (else). Indexing the
    joined GuardedValue would halt on the empty None arm; the source-visible
    taken arm is the singleton tuple already present among the leaves.
    """
    from sugar_lift_py_tests.floor.guarded_value import GuardedValue
    from sugar_lift_py_tests.floor.tuple_value import TupleValue

    if len(class_actuals) != 1 or not isinstance(value, GuardedValue):
        return None
    actual = class_actuals[0]
    leaves: list[FloorValue] = []

    def walk(node: FloorValue) -> None:
        if isinstance(node, GuardedValue):
            walk(node.when_true)
            walk(node.when_false)
            return
        leaves.append(node)

    walk(value)
    has_empty = any(
        isinstance(leaf, TupleValue) and leaf.elements == () for leaf in leaves
    )
    singleton = next(
        (
            leaf
            for leaf in leaves
            if isinstance(leaf, TupleValue) and leaf.elements == (actual,)
        ),
        None,
    )
    if has_empty and singleton is not None:
        return singleton
    return None


def _floor_one_tuple_callsite(
    value: FloorValue, class_actuals: tuple[FloorValue, ...]
) -> FloorValue | None:
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.floor.comprehension_value import ComprehensionValue
    from sugar_lift_py_tests.floor.tuple_coordinate_value import TupleCoordinateValue
    from sugar_lift_py_tests.floor.tuple_value import TupleValue
    from sugar_source_tree.nodes import LanguageCallee

    arg = None
    if (
        isinstance(value, CallSiteValue)
        and value.language_callee is LanguageCallee.BUILTIN_TUPLE
    ):
        if len(value.arg_values) != 1:
            return None
        arg = value.arg_values[0]
    elif isinstance(value, TupleCoordinateValue) and value.index is None:
        # Completed ``tuple(iterable)`` testimony carries the same generator
        # as the bodyless CallSiteValue arm, without invented members.
        arg = value.source
    else:
        return None
    if isinstance(arg, ComprehensionValue) and arg.finite_elements is not None:
        return TupleValue(tuple(arg.finite_elements))
    if isinstance(arg, TupleValue):
        return arg
    # Sole class actual + bodyless tuple(genexp): the non-tuple/non-None arm of
    # RaisesExc-style factories is ``(expected,)`` after parse identity.
    if len(class_actuals) == 1 and isinstance(arg, ComprehensionValue):
        return TupleValue(class_actuals)
    return None


def _call_coordinate(call: Call):
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceFragmentCoordinateV1,
    )

    span = call.line_col_span()
    return SourceFragmentCoordinateV1(
        call.unit.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )


def _install_source_call_frame(
    context: TreeConstructionContextV1,
    call: Call,
    frame: object,
) -> None:
    from sugar_source_tree.panic import BackendDefect

    coordinate = _call_coordinate(call)
    if coordinate in context.opaque_source_call_obligations:
        raise BackendDefect(
            blame=call.fragment,
            owner="manager_construction._install_source_call_frame",
            observed="frame/obligation collision",
            requested="one source-call classification at the exact coordinate",
            fix="keep authenticated frames and opaque obligations disjoint",
        )
    existing = context.source_call_frames.get(coordinate)
    if existing is not None and existing != frame:
        raise BackendDefect(
            blame=call.fragment,
            owner="manager_construction._install_source_call_frame",
            observed="conflicting source-call frame",
            requested="byte-identical duplicate frame testimony",
            fix="resolve the conflicting authenticated source frame",
        )
    context.source_call_frames[coordinate] = frame
