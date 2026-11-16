from __future__ import annotations

from dataclasses import dataclass, field
from sugar_lift_python_source.canonical import cid_of_json
from sugar_source_tree.binding_provenance import BindingCoordinateV1

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
class BoundFormalActualV1:
    coordinate: BindingCoordinateV1
    actual: object


@dataclass(frozen=True, eq=False)
class BoundSourceCallActualsV1:
    """One binder result with its authenticated coordinate testimony."""

    actuals: tuple
    formal_coordinates: tuple[BindingCoordinateV1, ...]
    projected_pairs: tuple[BoundFormalActualV1, ...] = ()

    def __post_init__(self) -> None:
        actual_count = len(self.actuals)
        if len(self.formal_coordinates) != actual_count:
            raise SourceCallBindingGap("bound actual coordinate arity mismatch")
        _reauthenticate_binding_coordinates(self.formal_coordinates)
        _reauthenticate_binding_coordinates(
            tuple(pair.coordinate for pair in self.projected_pairs)
        )
        from sugar_lift_py_tests.floor import DictValue, TupleValue

        def _projected_members(kind, actual):
            # ``variadic`` indexes the collected ``*args`` tuple;
            # ``variadic-keyword`` indexes the collected ``**kwargs`` entries.
            if kind == "variadic" and type(actual) is TupleValue:
                return actual.elements
            if kind == "variadic-keyword" and type(actual) is DictValue:
                return tuple(value for _key, value in actual.entries)
            return None

        roots = tuple(zip(self.formal_coordinates, self.actuals, strict=True))
        for pair in self.projected_pairs:
            matching = tuple(
                (root, actual)
                for root, actual in roots
                if pair.coordinate.scope_owner_cid == root.scope_owner_cid
                and pair.coordinate.binding_site == root.binding_site
                and pair.coordinate.projection_path[: len(root.projection_path)]
                == root.projection_path
            )
            suffix = (
                pair.coordinate.projection_path[len(matching[0][0].projection_path) :]
                if len(matching) == 1
                else ()
            )
            members = (
                _projected_members(suffix[0], matching[0][1])
                if len(suffix) == 2
                else None
            )
            if (
                len(matching) != 1
                or members is None
                or not isinstance(suffix[1], int)
                or isinstance(suffix[1], bool)
                or suffix[1] < 0
                or suffix[1] >= len(members)
                or pair.actual is not members[suffix[1]]
                or pair.coordinate != matching[0][0].project(*suffix)
            ):
                raise SourceCallBindingGap(
                    "projected formal coordinate is foreign or cross-wired"
                )

    def __eq__(self, other: object) -> bool:
        if isinstance(other, BoundSourceCallActualsV1):
            return (
                self.actuals == other.actuals
                and self.formal_coordinates == other.formal_coordinates
                and self.projected_pairs == other.projected_pairs
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


def _constructing_module_execution_site():
    """The module execution site the frame being constructed is under."""
    from sugar_source_tree.nodes import current_module_execution_site

    return current_module_execution_site()


def frame_at_current_module_execution_site(frame):
    """``frame`` read again at the module execution site the reduction
    running now is under (``current_module_execution_site``), when it was
    constructed at another one.

    A method frame is constructed with its class statement, but an implicit
    call runs its body where the call stands: ``x = 1; x += 1; class C:
    def __add__(self, o): return x; y = C() + 0; x += 1`` runs ``__add__``
    at ``y = C() + 0`` (the operator's sugar reduces at its stamped site,
    ``reduce_at_stamped_module_execution_site``), so its body reads the
    first ``x += 1``.  The frame is read again from its definition exactly
    as ``CallSiteSugar.desugar`` reads a declaration frame at its site
    (``frame_read_at_module_execution_site``); a frame with no definition to
    read it from is served as it is.
    """
    from sugar_source_tree.nodes import current_module_execution_site

    if not isinstance(frame, SourceVisibleCallFrameV1):
        return frame
    site = current_module_execution_site()
    if site == frame.module_execution_site:
        return frame
    if not hasattr(frame.owner, "source_visible_call_frame"):
        return frame
    return frame_read_at_module_execution_site(frame, site)


def frame_read_at_module_execution_site(frame, site):
    """The frame of ``frame``'s definition, read again at the module
    execution ``site``: its body reads a module global as the module binds
    it there."""
    from sugar_source_tree.nodes import construct_at_module_execution_site

    return construct_at_module_execution_site(
        site, frame.owner.source_visible_call_frame
    )


@dataclass(frozen=True)
class SourceVisibleCallFrameV1:
    """A callable's call frame: its signature, formal and captured
    coordinates and default keys, what the one binder binds a call by.  A
    ``def``'s frame and a lambda's hold no body (``body`` None): the body is
    the function's own universe's, built once (#7757 N4).  A class
    constructor's frame carries its body."""

    source_identity_cid: str
    definition_site: SourceFragmentCoordinateV1
    definition_fragment_cid: str
    parameters: tuple[str, ...]
    formal_coordinates: tuple[BindingCoordinateV1, ...]
    formal_declaration_sites: tuple[dict, ...]
    formal_projection_paths: tuple[tuple[str | int, ...], ...]
    parameter_kinds: tuple[str, ...]
    default_sugars: tuple[object | None, ...] = field(compare=False)
    default_fragments: tuple[object | None, ...] = field(compare=False)
    default_fragment_cids: tuple[str | None, ...]
    body: object = field(compare=False)
    owner: object = field(compare=False, repr=False)
    #: ``X = 1 // 0`` at module level: the module never finishes importing,
    #: so a call into any frame of it is that halt.  The one ``Halted`` arm
    #: of the first such constant in source order, reduced once per module.
    module_halt: object | None = field(default=None, compare=False)
    constructed_new_method: object | None = field(default=None, compare=False)
    declaration_frame_cid: str | None = field(default=None, compare=False)
    #: Where the call this frame was constructed for runs while its module
    #: body runs (``sugar_source_tree.nodes.ModuleExecutionSiteV1``), or None:
    #: called from outside the module's execution.  A body reads a module
    #: global as the module binds it there, so the frame read again at reduce
    #: is read at the same site (``CallSiteSugar.desugar``).  A lookup aid,
    #: never testimony: what the site decided is in the body.
    module_execution_site: object | None = field(
        default_factory=lambda: _constructing_module_execution_site(),
        compare=False,
        repr=False,
        metadata={"testimony": "lookup"},
    )
    #: The enclosing function's locals the body reads (its free names), and
    #: the coordinate each is read through (``FunctionDef._captured_bindings``).
    #: A call binds each from its own scope's binding at the call.
    captured_names: tuple[str, ...] = ()
    captured_coordinates: tuple[BindingCoordinateV1, ...] = ()
    frame_cid: str = field(init=False)

    def __post_init__(self) -> None:
        if self.constructed_new_method is not None:
            from sugar_lift_py_tests.floor.class_definition_value import (
                ConstructedClassMethodV1,
            )
            from sugar_lift_py_tests.sugar.class_constructor_body_sugar import (
                ClassConstructorBodySugar,
            )
            from sugar_source_tree.nodes import ClassDef, FunctionDef

            method = self.constructed_new_method
            if (
                type(method) is not ConstructedClassMethodV1
                or not isinstance(self.owner, ClassDef)
                or type(method.source_call_frame) is not SourceVisibleCallFrameV1
                or not isinstance(method.source_call_frame.owner, FunctionDef)
                or method.source_call_frame.owner.name != "__new__"
                or not any(
                    item is method.source_call_frame.owner for item in self.owner.body
                )
                or method.name != method.source_call_frame.owner.name
                or method.definition_fragment_cid
                != method.source_call_frame.owner.fragment.seal().cid
                or method.source_call_frame.definition_fragment_cid
                != method.definition_fragment_cid
                or method.source_call_frame.source_identity_cid
                != self.source_identity_cid
                or type(self.body) is not ClassConstructorBodySugar
                or self.body.constructed_new_method is not method
            ):
                raise SourceCallBindingGap(
                    "constructed __new__ method testimony is foreign or cross-wired"
                )
        elif getattr(self.body, "constructed_new_method", None) is not None:
            raise SourceCallBindingGap(
                "constructor body carries unseated __new__ method testimony"
            )
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
            # A generator function's body is constructed as every body is
            # (#7757 step 6); the preimage keeps the slot its steps' CIDs
            # held, constant, so no other frame CID moves.
            "generatorStepFragmentCids": [],
            # A decorated module name is bound by the one decorator
            # application (``DecoratedDefinitionRef``), never by a frame; the
            # preimage keeps its constant slot so no frame CID moves.
            "decoratedClassBindingCids": [],
        }
        if self.module_halt is not None:
            effect = self.module_halt.effect
            preimage["moduleHalt"] = {
                "exceptionName": getattr(effect, "exception_name", None),
                "occurrence": str(getattr(effect, "occurrence_id", None)),
            }
        if len(self.captured_names) != len(self.captured_coordinates):
            raise SourceCallBindingGap(
                "captured binding names and coordinates are cross-wired"
            )
        if self.captured_names:
            preimage["capturedBindings"] = [
                {"name": name, "coordinate": coordinate.wire()}
                for name, coordinate in zip(
                    self.captured_names, self.captured_coordinates, strict=True
                )
            ]
        if self.declaration_frame_cid is not None:
            preimage["declarationFrameCid"] = self.declaration_frame_cid
        if self.constructed_new_method is not None:
            preimage["constructedNewMethod"] = {
                "definitionFragmentCid": (
                    self.constructed_new_method.definition_fragment_cid
                ),
                "sourceCallFrameCid": (
                    self.constructed_new_method.source_call_frame.frame_cid
                ),
            }
        object.__setattr__(self, "frame_cid", cid_of_json(preimage))
        if self.declaration_frame_cid is None:
            object.__setattr__(self, "declaration_frame_cid", self.frame_cid)

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
        projected_pairs = []
        for index, (name, kind, default) in enumerate(
            zip(
                self.parameters,
                self.parameter_kinds,
                self.default_sugars,
                strict=True,
            )
        ):
            if kind == "vararg":
                values = tuple(remaining)
                root = self.formal_coordinates[index]
                projected_pairs.extend(
                    BoundFormalActualV1(root.project("variadic", ordinal), actual)
                    for ordinal, actual in enumerate(values)
                )
                bound.append(TupleValue(values))
                remaining.clear()
                continue
            if kind == "kwarg":
                # Each collected keyword is the ``variadic-keyword`` projection
                # of this formal, in collection order, so a
                # body read of that entry finds the caller's Floor, exactly as
                # a ``variadic`` (``*args``) element does.
                root = self.formal_coordinates[index]
                projected_pairs.extend(
                    BoundFormalActualV1(
                        root.project("variadic-keyword", ordinal), actual
                    )
                    for ordinal, actual in enumerate(named.values())
                )
                # The ``**kwargs`` dict is a new dict the call makes, at the
                # formal that collects it, and no other frame holds: its
                # contents are its contents (``object_identity.
                # contents_current``).  A formal read passes it through as it
                # is (``FormalRefSugar``), so it names its construction here.
                bound.append(
                    DictValue(
                        tuple(
                            (StringValue(key), value) for key, value in named.items()
                        ),
                        allocation=root.cid,
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
                # The value the ``def`` statement bound under the default's
                # key, the same object for every call (``DefaultValueSugar``).
                exits = default.desugar(ctx)
                # One completed arm under truth that owes nothing: a default
                # that owes would drop its debt into the bound actual.
                value = None if exits.owed_items() else exits.completed_value()
                if value is None:
                    raise SourceCallBindingGap("default did not construct completely")
                present = True
            if not present:
                raise SourceCallBindingGap(f"missing required formal {index}")
            bound.append(value)
        if remaining or named:
            raise SourceCallBindingGap("unconsumed call actual")
        return BoundSourceCallActualsV1(
            tuple(bound),
            self.formal_coordinates,
            tuple(projected_pairs),
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


class SourceCallBindingGap(ValueError):
    pass


SourceCallFrameV1 = SourceVisibleCallFrameV1
