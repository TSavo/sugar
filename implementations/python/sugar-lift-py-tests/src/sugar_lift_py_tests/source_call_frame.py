from __future__ import annotations

from dataclasses import dataclass, field, replace
from sugar_lift_python_source.canonical import cid_of_json
from sugar_source_tree.binding_provenance import BindingCoordinateV1
from sugar_source_tree.binding_provenance import BoundBindingStateV1
from sugar_source_tree.binding_state import BindingEntryV1

from .context_manager_resolution import SourceFragmentCoordinateV1


def _reauthenticate_binding_coordinates(coordinates: tuple) -> None:
    from sugar_source_tree.binding_provenance import BindingProvenanceGap

    seen = set()
    for coordinate in coordinates:
        if type(coordinate) is not BindingCoordinateV1:
            raise SourceCallBindingGap(
                "formal coordinate roster contains a foreign coordinate type"
            )
        if cid_of_json(coordinate.preimage) != coordinate.cid:
            raise SourceCallBindingGap("formal coordinate roster contains a stale CID")
        try:
            decoded = BindingCoordinateV1.decode(coordinate.wire())
        except BindingProvenanceGap as exc:
            raise SourceCallBindingGap(
                "formal coordinate roster failed wire authentication"
            ) from exc
        if decoded != coordinate or coordinate.cid in seen:
            raise SourceCallBindingGap(
                "formal coordinate roster contains duplicate or foreign testimony"
            )
        seen.add(coordinate.cid)


def _reauthenticate_native_coordinates(coordinates: tuple) -> None:
    from sugar_lift_py_tests.formal_parameter import FormalParameterCoordinateV1

    seen = set()
    for coordinate in coordinates:
        if type(coordinate) is not FormalParameterCoordinateV1:
            raise SourceCallBindingGap(
                "native formal coordinate roster contains a foreign coordinate type"
            )
        try:
            authenticated = FormalParameterCoordinateV1(
                coordinate.owner_source_identity_cid,
                coordinate.owner_definition_locus,
                coordinate.declaration_locus,
                coordinate.ordinal,
                coordinate.parameter_kind,
                coordinate.declared_name,
                coordinate.sort,
                coordinate.coordinate_cid,
                coordinate.kind,
                coordinate.schema_version,
            )
        except ValueError as exc:
            raise SourceCallBindingGap(
                "native formal coordinate roster failed authentication"
            ) from exc
        if authenticated != coordinate or coordinate.coordinate_cid in seen:
            raise SourceCallBindingGap(
                "native formal coordinate roster contains duplicate testimony"
            )
        seen.add(coordinate.coordinate_cid)


def _source_coordinate(node) -> SourceFragmentCoordinateV1:
    span = node.line_col_span()
    return SourceFragmentCoordinateV1(
        node.unit.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )


@dataclass(frozen=True)
class BoundNativeOperationActualsV1:
    """The one Python binder's ordered result, indexed by formal coordinate."""

    actuals: tuple
    by_formal_coordinate: dict[str, object]
    source_actuals: BoundSourceCallActualsV1

    def __post_init__(self) -> None:
        if self.source_actuals.actuals != self.actuals:
            raise SourceCallBindingGap("native actual testimony values diverge")


@dataclass(frozen=True)
class BoundFormalActualV1:
    coordinate: BindingCoordinateV1
    actual: object


@dataclass(frozen=True, eq=False)
class BoundSourceCallActualsV1:
    """One binder result with its authenticated coordinate testimony."""

    actuals: tuple
    formal_coordinates: tuple[BindingCoordinateV1, ...]
    native_formal_coordinates: tuple = ()

    def __post_init__(self) -> None:
        actual_count = len(self.actuals)
        if len(self.formal_coordinates) != actual_count or (
            self.native_formal_coordinates
            and len(self.native_formal_coordinates) != actual_count
        ):
            raise SourceCallBindingGap("bound actual coordinate arity mismatch")
        _reauthenticate_binding_coordinates(self.formal_coordinates)
        _reauthenticate_native_coordinates(self.native_formal_coordinates)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, BoundSourceCallActualsV1):
            return (
                self.actuals == other.actuals
                and self.formal_coordinates == other.formal_coordinates
                and self.native_formal_coordinates == other.native_formal_coordinates
            )
        return NotImplemented

    @property
    def pairs(self) -> tuple[BoundFormalActualV1, ...]:
        return tuple(
            BoundFormalActualV1(coordinate, actual)
            for coordinate, actual in zip(
                self.formal_coordinates, self.actuals, strict=True
            )
        )

    @property
    def by_native_formal_coordinate(self) -> dict[str, object]:
        return {
            coordinate.coordinate_cid: actual
            for coordinate, actual in zip(
                self.native_formal_coordinates, self.actuals, strict=True
            )
        }


@dataclass(frozen=True)
class SourceVisibleCallFrameV1:
    """A body constructed by FunctionDef through the ordinary tree door."""

    source_identity_cid: str
    definition_site: SourceFragmentCoordinateV1
    definition_fragment_cid: str
    parameters: tuple[str, ...]
    formal_coordinates: tuple[BindingCoordinateV1, ...]
    formal_declaration_sites: tuple[dict, ...]
    formal_projection_paths: tuple[tuple[str | int, ...], ...]
    parameter_kinds: tuple[str, ...]
    default_sugars: tuple[object | None, ...] = field(compare=False)
    default_nodes: tuple[object | None, ...] = field(compare=False)
    default_fragments: tuple[object | None, ...] = field(compare=False)
    default_fragment_cids: tuple[str | None, ...]
    body: object = field(compare=False)
    owner: object = field(compare=False, repr=False)
    native_operation_formal_coordinates: tuple = field(default=(), compare=False)
    pending_native_operation: object | None = field(default=None, compare=False)
    runtime_entries: tuple[BindingEntryV1, ...] = field(
        default=(), compare=False, repr=False
    )
    generator_steps: tuple | None = field(default=None, compare=False, repr=False)
    generator_step_fragment_cids: tuple[str, ...] = ()
    frame_cid: str = field(init=False)

    def __post_init__(self) -> None:
        preimage = {
            "kind": "source-visible-call-frame",
            "schemaVersion": "1",
            "sourceIdentityCid": self.source_identity_cid,
            "definitionSite": self.definition_site.wire(),
            "definitionFragmentCid": self.definition_fragment_cid,
            "parameters": list(self.parameters),
            "formalCoordinates": [item.wire() for item in self.formal_coordinates],
            "formalDeclarationSites": list(self.formal_declaration_sites),
            "formalProjectionPaths": [
                list(path) for path in self.formal_projection_paths
            ],
            "parameterKinds": list(self.parameter_kinds),
            "defaultFragmentCids": list(self.default_fragment_cids),
            "generatorStepFragmentCids": list(self.generator_step_fragment_cids),
        }
        object.__setattr__(self, "frame_cid", cid_of_json(preimage))

    def bind_actuals(
        self, positional: tuple, keywords: tuple, ctx=None
    ) -> BoundSourceCallActualsV1:
        """Bind positional/keyword FloorValues onto this frame's formals.

        ``keywords`` is ``(name, value)`` pairs in source order. A name of
        ``None`` or ``\"**\"`` is a typed ``**`` expansion: when the value is a
        constructed ``DictValue`` with string keys, its entries join the
        named-keyword map (Python's call-time ``**mapping`` projection). Other
        expansion shapes stay a ``SourceCallBindingGap`` so the call remains
        loud rather than inventing keys.
        """
        from sugar_lift_py_tests.floor import DictValue, StringValue, TupleValue

        self._validate_formal_coordinate_rosters()

        remaining = list(positional)
        named: dict = {}
        for key, value in keywords:
            if key is None or key == "**":
                if type(value) is not DictValue:
                    raise SourceCallBindingGap(
                        "spread keyword requires typed DictValue projection"
                    )
                for entry_key, entry_value in value.entries:
                    if type(entry_key) is not StringValue:
                        raise SourceCallBindingGap("non-string keyword expansion key")
                    if entry_key.value in named:
                        raise SourceCallBindingGap(
                            "duplicate keyword actual from expansion"
                        )
                    named[entry_key.value] = entry_value
                continue
            if key in named:
                raise SourceCallBindingGap("duplicate keyword actual")
            named[key] = value
        bound = []
        for index, (name, kind, default) in enumerate(
            zip(
                self.parameters,
                self.parameter_kinds,
                self.default_sugars,
                strict=True,
            )
        ):
            if kind == "vararg":
                bound.append(TupleValue(tuple(remaining)))
                remaining.clear()
                continue
            if kind == "kwarg":
                bound.append(
                    DictValue(
                        tuple((StringValue(key), value) for key, value in named.items())
                    )
                )
                named.clear()
                continue
            value = None
            present = False
            if kind in {"positional_only", "positional_or_keyword"} and remaining:
                value = remaining.pop(0)
                present = True
                if name in named:
                    raise SourceCallBindingGap("formal received positional and keyword")
            elif kind != "positional_only" and name in named:
                value = named.pop(name)
                present = True
            if not present and default is not None:
                from sugar_lift_py_tests.outcome import Complete

                outcome = default.desugar(ctx)
                if not isinstance(outcome, Complete):
                    raise SourceCallBindingGap("default did not construct completely")
                value = outcome.value
                present = True
            if not present:
                raise SourceCallBindingGap(f"missing required formal {index}")
            bound.append(value)
        if remaining or named:
            raise SourceCallBindingGap("unconsumed call actual")
        return BoundSourceCallActualsV1(
            tuple(bound),
            self.formal_coordinates,
            self.native_operation_formal_coordinates,
        )

    def _validate_formal_coordinate_rosters(self) -> None:
        owner = self.owner
        owner_fragment = getattr(owner, "fragment", None)
        if owner_fragment is None or self.definition_site != _source_coordinate(owner):
            raise SourceCallBindingGap(
                "source call frame has a foreign definition site"
            )
        if owner_fragment.seal().cid != self.definition_fragment_cid:
            raise SourceCallBindingGap(
                "source call frame has a foreign definition fragment"
            )

        coordinates = self.formal_coordinates
        if len(coordinates) != len(self.parameters):
            raise SourceCallBindingGap("formal coordinate roster is missing an entry")
        _reauthenticate_binding_coordinates(coordinates)
        cids = tuple(coordinate.cid for coordinate in coordinates)
        if len(set(cids)) != len(cids):
            raise SourceCallBindingGap("formal coordinate roster contains a duplicate")
        if len(self.formal_projection_paths) != len(coordinates) or any(
            coordinate.projection_path != expected
            for coordinate, expected in zip(
                coordinates, self.formal_projection_paths, strict=True
            )
        ):
            raise SourceCallBindingGap("formal coordinate roster is reordered")
        if any(
            coordinate.scope_owner_cid != self.definition_fragment_cid
            for coordinate in coordinates
        ):
            raise SourceCallBindingGap(
                "formal coordinate roster has a foreign scope owner"
            )
        declaration_sites = self.formal_declaration_sites
        if len(declaration_sites) != len(coordinates) or any(
            coordinate.binding_site != declaration_site
            for coordinate, declaration_site in zip(
                coordinates, declaration_sites, strict=True
            )
        ):
            raise SourceCallBindingGap(
                "formal coordinate roster has a foreign declaration site"
            )

        native = self.native_operation_formal_coordinates
        if not native:
            return
        owner_parameters = tuple(self.owner.params)
        _reauthenticate_native_coordinates(native)
        native_cids = tuple(coordinate.coordinate_cid for coordinate in native)
        expected_kinds = {
            "positional_only": "positional-only",
            "positional_or_keyword": "positional-or-keyword",
            "vararg": "variadic-positional",
            "keyword_only": "keyword-only",
            "kwarg": "variadic-keyword",
        }
        from sugar_lift_py_tests.ir import PrimitiveSort

        if (
            len(native) != len(self.parameters)
            or len(set(native_cids)) != len(native_cids)
            or any(
                coordinate.owner_source_identity_cid != self.source_identity_cid
                or coordinate.owner_definition_locus != self.definition_site
                or coordinate.declaration_locus
                != _source_coordinate(owner_parameters[index])
                or coordinate.parameter_kind
                != expected_kinds[self.parameter_kinds[index]]
                or coordinate.sort != PrimitiveSort("Value")
                or coordinate.ordinal != index
                or coordinate.declared_name != self.parameters[index]
                for index, coordinate in enumerate(native)
            )
        ):
            raise SourceCallBindingGap("native formal coordinate roster is cross-wired")
        pending = self.pending_native_operation
        if pending is None:
            raise SourceCallBindingGap(
                "native formal coordinate roster omitted its pending demand"
            )
        by_cid = {coordinate.coordinate_cid: coordinate for coordinate in native}
        demanded = pending.demand.operand_coordinate_cids
        for coordinate_cid, stored in zip(
            demanded, pending.coordinates, strict=True
        ):
            if coordinate_cid is None:
                if stored is not None:
                    raise SourceCallBindingGap(
                        "pending carrier demand coordinate testimony is cross-wired"
                    )
                continue
            if coordinate_cid not in by_cid or stored != by_cid[coordinate_cid]:
                raise SourceCallBindingGap(
                    "pending carrier demand coordinate testimony is cross-wired"
                )

    def bind_native_operation_actuals(
        self, positional: tuple, keywords: tuple, ctx=None
    ) -> BoundNativeOperationActualsV1:
        """Bind once, then key that exact result by formal coordinates."""
        bound = self.bind_actuals(positional, keywords, ctx)
        return BoundNativeOperationActualsV1(
            actuals=bound.actuals,
            by_formal_coordinate=bound.by_native_formal_coordinate,
            source_actuals=bound,
        )

    def with_native_operation_projection(self, formal_coordinates, pending):
        """Seat one already-constructed formal operation on this call frame."""
        return replace(
            self,
            native_operation_formal_coordinates=tuple(formal_coordinates),
            pending_native_operation=pending,
        )

    def bind_node_actuals(
        self,
        positional: tuple,
        keywords: tuple,
        testimonies: tuple[object | None, ...] | None = None,
    ) -> "SourceVisibleCallFrameV1":
        """Substitute real typed actual Nodes before constructing body Sugars."""
        remaining = list(positional)
        named = dict(keywords)
        if len(named) != len(keywords):
            raise SourceCallBindingGap("duplicate keyword actual")
        bound = []
        for index, (name, kind, default) in enumerate(
            zip(
                self.parameters,
                self.parameter_kinds,
                self.default_nodes,
                strict=True,
            )
        ):
            if kind == "vararg":
                coordinate = self.formal_coordinates[index]
                bound.append(
                    self._tuple_node(
                        tuple(
                            _same_unit_actual_node(
                                self.owner.unit,
                                value,
                                coordinate.project("variadic", actual_index),
                            )
                            for actual_index, value in enumerate(remaining)
                        )
                    )
                )
                remaining.clear()
                continue
            if kind == "kwarg":
                coordinate = self.formal_coordinates[index]
                bound.append(
                    self._dict_node(
                        tuple(
                            (
                                key,
                                _same_unit_actual_node(
                                    self.owner.unit,
                                    value,
                                    coordinate.project("variadic-keyword", actual_index),
                                ),
                            )
                            for actual_index, (key, value) in enumerate(named.items())
                        )
                    )
                )
                named.clear()
                continue
            value = None
            present = False
            if kind in {"positional_only", "positional_or_keyword"} and remaining:
                value = remaining.pop(0)
                present = True
                if name in named:
                    raise SourceCallBindingGap("formal received positional and keyword")
            elif kind != "positional_only" and name in named:
                value = named.pop(name)
                present = True
            if not present and default is not None:
                value = default
                present = True
            if not present:
                raise SourceCallBindingGap(f"missing required formal {index}")
            bound.append(value)
        if remaining or named:
            raise SourceCallBindingGap("unconsumed call actual")

        # Rehost foreign-unit actuals onto this frame's SourceUnit so binding
        # never carries cross-unit LineTable offsets into construction.
        owner_unit = self.owner.unit
        bound = tuple(
            _same_unit_actual_node(owner_unit, node, coordinate)
            for node, coordinate in zip(bound, self.formal_coordinates, strict=True)
        )

        supplied_testimonies = testimonies or (None,) * len(bound)
        if len(supplied_testimonies) != len(bound):
            raise SourceCallBindingGap("formal testimony arity mismatch")
        entries = tuple(
            BindingEntryV1(
                coordinate,
                node,
                BoundBindingStateV1(testimony) if testimony is not None else None,
            )
            for coordinate, node, testimony in zip(
                self.formal_coordinates, bound, supplied_testimonies, strict=True
            )
        )
        scope = dict(zip(self.parameters, entries, strict=True))
        generator_steps = (
            None
            if self.generator_steps is None
            else self.owner._source_visible_generator_steps(scope)
        )
        # Specialize the body by inlining the exact typed actual Nodes for each
        # formal. A source-visible callback (a formal invoked as ``fn(value)``)
        # then reduces through the actual callable's own construction, rather
        # than raising on the unspecialized BindingCoordinateRef formal.
        node_scope = dict(zip(self.parameters, bound, strict=True))
        rebuild = getattr(self.owner, "_source_visible_body", None)
        body = self.body if rebuild is None else rebuild(node_scope)
        return replace(
            self,
            runtime_entries=entries,
            generator_steps=generator_steps,
            body=body,
        )

    def _tuple_node(self, values: tuple):
        from sugar_source_tree.backend import Children, materialize
        from sugar_source_tree.shadow import ShadowNode, _handle_of

        return materialize(
            self.owner.unit,
            ShadowNode(
                "Tuple",
                self.owner.span,
                (("elts", Children(tuple(_handle_of(value) for value in values))),),
            ),
            self.owner.reporter,
        )

    def _dict_node(self, values: tuple[tuple[str, object], ...]):
        from sugar_source_tree.backend import Child, Children, Leaf, materialize
        from sugar_source_tree.shadow import ShadowNode, _handle_of

        items = []
        for key, value in values:
            key_node = materialize(
                self.owner.unit,
                ShadowNode(
                    "Constant",
                    self.owner.span,
                    (("value", Leaf(key)),),
                ),
                self.owner.reporter,
            )
            items.append(
                materialize(
                    self.owner.unit,
                    ShadowNode(
                        "DictItem",
                        self.owner.span,
                        (
                            ("key", Child(_handle_of(key_node))),
                            ("value", Child(_handle_of(value))),
                        ),
                    ),
                    self.owner.reporter,
                )
            )
        return materialize(
            self.owner.unit,
            ShadowNode(
                "Dict",
                self.owner.span,
                (("items", Children(tuple(_handle_of(item) for item in items))),),
            ),
            self.owner.reporter,
        )


class SourceCallBindingGap(ValueError):
    pass


def _same_unit_actual_node(owner_unit, node, coordinate):
    """Rehost a bound actual onto the frame owner unit when needed.

    Same-unit nodes pass through. Foreign-unit actuals must never carry their
    LineTable offsets into owner-unit construction (``offset N outside 0..M``):
    mint a ``BindingCoordinateRef`` at the formal's owner-local span only.

    Value-use resolutions are **not** transferred or re-seated here: frames
    consume exact seats on the owning SourceUnit (source-CID authenticated at
    publication). No broad Exception catch, no fallback fabrication of seats.
    """
    from sugar_source_tree.backend import Leaf, materialize
    from sugar_source_tree.nodes import Node
    from sugar_source_tree.shadow import ShadowNode
    from sugar_source_tree.spans import Span

    if not isinstance(node, Node):
        return node
    if node.unit.source_cid == owner_unit.source_cid:
        return node

    site = coordinate.binding_site
    if not isinstance(site, dict):
        raise SourceCallBindingGap(
            "foreign actual requires owner-local formal binding site"
        )
    site_cid = site.get("source_cid") or site.get("sourceCid")
    if site_cid != owner_unit.source_cid:
        raise SourceCallBindingGap(
            "formal binding site is not on the frame owner unit"
        )
    span_info = site.get("span")
    if not isinstance(span_info, dict):
        raise SourceCallBindingGap("formal binding site missing sealed span")
    start = span_info.get("start")
    end = span_info.get("end")
    if not isinstance(start, int) or not isinstance(end, int) or end < start:
        raise SourceCallBindingGap("formal binding site span is not unit-local")
    owner_span = Span(start, end)

    return materialize(
        owner_unit,
        ShadowNode(
            "BindingCoordinateRef",
            owner_span,
            (("coordinate", Leaf(coordinate)),),
        ),
        node.reporter,
    )


SourceCallFrameV1 = SourceVisibleCallFrameV1
