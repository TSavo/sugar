from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1
from sugar_lift_py_tests.ir import Term, _term_content_cid, ctor
from sugar_lift_python_source.canonical import cid_of_json

from .closed_operation_witness import (
    ClosedSemanticOperationWitness,
    PythonRuntimeIdentity,
)
from .floor_value import FloorValue


_TUPLE_COORDINATE_OWNER = object()


def _constructor_coordinate_cid(
    witness: ClosedSemanticOperationWitness,
    call_occurrence: SourceFragmentCoordinateV1,
) -> str:
    return cid_of_json(
        {
            "kind": "python-tuple-coordinate",
            "schemaVersion": "1",
            "operationWitnessCid": witness.witness_cid,
            "callOccurrence": call_occurrence.wire(),
            "callOccurrenceCid": call_occurrence.cid,
        }
    )


def _slice_coordinate_cid(
    *,
    parent_coordinate_cid: str,
    constructor_witness: ClosedSemanticOperationWitness,
    index_cid: str,
    use_occurrence: SourceFragmentCoordinateV1,
    result_cid: str,
) -> str:
    return cid_of_json(
        {
            "kind": "python-tuple-slice-coordinate",
            "schemaVersion": "1",
            "resultKind": "tuple",
            "receiverCoordinateCid": parent_coordinate_cid,
            "constructorWitnessCid": constructor_witness.witness_cid,
            "indexCid": index_cid,
            "useOccurrence": use_occurrence.wire(),
            "useOccurrenceCid": use_occurrence.cid,
            "resultTermCid": result_cid,
        }
    )


@dataclass(frozen=True)
class TupleCoordinateValue(FloorValue):
    """Runtime tuple testimony without invented members or cardinality."""

    source: FloorValue
    call_occurrence: SourceFragmentCoordinateV1
    call_occurrence_cid: str
    term: Term
    witness: ClosedSemanticOperationWitness
    coordinate_cid: str
    index: FloorValue | None = None
    use_occurrence: SourceFragmentCoordinateV1 | None = None
    use_occurrence_cid: str | None = None
    parent_coordinate_cid: str | None = None
    _producer_owner: object = field(default=None, compare=False, repr=False)

    @classmethod
    def _from_builtin_construct(
        cls,
        *,
        source: FloorValue,
        call_occurrence: SourceFragmentCoordinateV1,
        runtime: PythonRuntimeIdentity,
    ) -> "TupleCoordinateValue":
        source_term = source.to_term(owner="python.tuple.construct")
        term = ctor(
            "python.tuple.construct", (source_term,), symbol_kind="coordinate"
        )
        witness = ClosedSemanticOperationWitness.mint(
            runtime, "python.tuple.construct", (source_term,), term
        )
        return cls(
            source=source,
            call_occurrence=call_occurrence,
            call_occurrence_cid=call_occurrence.cid,
            term=term,
            witness=witness,
            coordinate_cid=_constructor_coordinate_cid(witness, call_occurrence),
            _producer_owner=_TUPLE_COORDINATE_OWNER,
        )

    @classmethod
    def _from_slice(
        cls,
        *,
        source: "TupleCoordinateValue",
        index: FloorValue,
        use_occurrence: SourceFragmentCoordinateV1,
    ) -> "TupleCoordinateValue":
        index_term = index.to_term(owner="TupleCoordinateValue.subscript")
        term = ctor(
            "py.subscript",
            (
                source.to_term(owner="TupleCoordinateValue.subscript"),
                index_term,
            ),
            symbol_kind="coordinate",
        )
        return cls(
            source=source,
            call_occurrence=source.call_occurrence,
            call_occurrence_cid=source.call_occurrence_cid,
            term=term,
            witness=source.witness,
            coordinate_cid=_slice_coordinate_cid(
                parent_coordinate_cid=source.coordinate_cid,
                constructor_witness=source.witness,
                index_cid=_term_content_cid(index_term),
                use_occurrence=use_occurrence,
                result_cid=_term_content_cid(term),
            ),
            index=index,
            use_occurrence=use_occurrence,
            use_occurrence_cid=use_occurrence.cid,
            parent_coordinate_cid=source.coordinate_cid,
            _producer_owner=_TUPLE_COORDINATE_OWNER,
        )

    def __post_init__(self) -> None:
        if self._producer_owner is not _TUPLE_COORDINATE_OWNER:
            raise ValueError("tuple coordinate requires its private producer authority")
        if type(self.call_occurrence) is not SourceFragmentCoordinateV1:
            raise ValueError("tuple coordinate call occurrence is not authenticated")
        if self.call_occurrence_cid != self.call_occurrence.cid:
            raise ValueError(
                "tuple coordinate call occurrence does not authenticate source"
            )
        runtime = PythonRuntimeIdentity.current()
        if self.index is None:
            if (
                self.use_occurrence is not None
                or self.use_occurrence_cid is not None
                or self.parent_coordinate_cid is not None
            ):
                raise ValueError(
                    "tuple coordinate call occurrence does not authenticate source"
                )
            source_term = self.source.to_term(owner="python.tuple.construct")
            self.witness.verify(
                runtime,
                "python.tuple.construct",
                (source_term,),
                self.term,
            )
            expected_cid = _constructor_coordinate_cid(
                self.witness, self.call_occurrence
            )
            if self.coordinate_cid != expected_cid:
                raise ValueError(
                    "tuple coordinate call occurrence does not authenticate source"
                )
            return

        from sugar_lift_py_tests.floor.slice_value import SliceValue

        if (
            type(self.source) is not TupleCoordinateValue
            or type(self.index) is not SliceValue
            or type(self.use_occurrence) is not SourceFragmentCoordinateV1
            or self.use_occurrence_cid != self.use_occurrence.cid
            or self.call_occurrence is not self.source.call_occurrence
            or self.witness is not self.source.witness
            or self.parent_coordinate_cid != self.source.coordinate_cid
        ):
            raise ValueError(
                "tuple slice coordinate does not authenticate receiver, index, and use occurrence"
            )
        source_term = self.source.source.to_term(owner="python.tuple.construct")
        self.witness.verify(
            runtime,
            "python.tuple.construct",
            (source_term,),
            self.source.term,
        )
        index_term = self.index.to_term(owner="TupleCoordinateValue.subscript")
        expected_term = ctor(
            "py.subscript",
            (self.source.term, index_term),
            symbol_kind="coordinate",
        )
        expected_cid = _slice_coordinate_cid(
            parent_coordinate_cid=self.source.coordinate_cid,
            constructor_witness=self.witness,
            index_cid=_term_content_cid(index_term),
            use_occurrence=self.use_occurrence,
            result_cid=_term_content_cid(expected_term),
        )
        if self.term != expected_term or self.coordinate_cid != expected_cid:
            raise ValueError(
                "tuple slice coordinate does not authenticate receiver, index, and use occurrence"
            )

    def to_term(self, *, owner: str):
        del owner
        return self.term

    def subscript(self, index, site):
        return self.subscript_with_occurrence(index, site, None)

    def subscript_with_occurrence(self, index, site, occurrence):
        from sugar_lift_py_tests.floor.slice_value import SliceValue
        from sugar_lift_py_tests.outcome import Complete
        from sugar_source_tree.panic import SugarNotWritten

        if type(index) is not SliceValue:
            raise SugarNotWritten(
                blame=site,
                owner="TupleCoordinateValue.subscript",
                observed="member lookup without authenticated tuple members",
                requested="SliceValue projection or finite tuple testimony",
                fix="retain unknown tuple members; do not invent finite_elements",
            )
        if type(occurrence) is not SourceFragmentCoordinateV1:
            raise SugarNotWritten(
                blame=site,
                owner="TupleCoordinateValue.subscript",
                observed="slice lacks authenticated use occurrence",
                requested="exact SourceFragmentCoordinateV1 for tuple slice",
                fix="transport the Subscript occurrence without reconstruction",
            )
        if occurrence.source_cid != self.call_occurrence.source_cid:
            raise SugarNotWritten(
                blame=site,
                owner="TupleCoordinateValue.subscript",
                observed="slice use occurrence outside tuple source",
                requested="same-source authenticated slice occurrence",
                fix="transport the producer-minted Subscript occurrence unchanged",
            )
        return Complete(
            self._from_slice(source=self, index=index, use_occurrence=occurrence)
        )

    def length(self, site):
        from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
        from sugar_lift_py_tests.outcome import Complete

        return Complete(
            CallSiteValue(
                target_name="len",
                arg_values=(self,),
                parameters=(),
                term=ctor(
                    "call:len",
                    (self.term,),
                    symbol_kind="builtin",
                ),
                body=None,
                site=site,
            )
        )
