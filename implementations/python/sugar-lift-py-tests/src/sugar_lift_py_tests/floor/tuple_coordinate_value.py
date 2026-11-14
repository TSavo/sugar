from __future__ import annotations

from dataclasses import dataclass, field

from sugar_lift_py_tests.call_symbol import call_symbol
from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1
from sugar_lift_py_tests.ir import Term, _term_content_cid, ctor
from sugar_lift_python_source.canonical import cid_of_json

from .call_site_value import CallSiteValue
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
class TupleLengthValue(CallSiteValue):
    """Successful ``len`` of a constructed tuple is an ``int``.

    Members and cardinality stay unknown. ``tuple.__len__`` cannot fail and
    always returns ``int``, so ``len(xs) == 1`` is native int equality
    rather than undecided ``__eq__`` dispatch. A plain CallSiteValue for
    ``len`` leaves the result type undecided, which turned that RaisesExc
    check into ComparisonOpSugar.Eq exit-may-halt after the field had
    already been written.
    """

    def runtime_type_is_decided(self) -> bool:
        return True


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
    _producer_owner: object = field(
        default=None,
        compare=False,
        repr=False,
        metadata={"testimony": "authority"},
    )

    @classmethod
    def _from_builtin_construct(
        cls,
        *,
        source: FloorValue,
        call_occurrence: SourceFragmentCoordinateV1,
        runtime: PythonRuntimeIdentity,
    ) -> "TupleCoordinateValue":
        source_term = source.to_term(owner="python.tuple.construct")
        term = ctor("python.tuple.construct", (source_term,), symbol_kind="coordinate")
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

    def truth(self, site):
        """Stand as a condition via the construction term, without inventing cardinality.

        ``if not self.expected_exceptions`` asks this coordinate whether the
        constructed tuple is empty. Members are not invented, so truth cannot
        fold to a Bool; it can emit ``py.truthy`` over the same term a
        bodyless ``tuple(...)`` CallSiteValue uses when the result is not
        lift-time decidable. Default FloorValue.truth panicked
        ``truth:TupleCoordinateValue`` and turned that RaisesExc check into
        exit-may-halt after the field had already been written.
        """
        from sugar_lift_py_tests.floor.predicate_value import PredicateValue
        from sugar_lift_py_tests.ir import py_truthy
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(PredicateValue(py_truthy(self.term), site))

    def subscript(self, index, site):
        return self.subscript_with_occurrence(index, site, None)

    def subscript_with_occurrence(self, index, site, occurrence):
        from sugar_lift_py_tests.floor.slice_value import SliceValue
        from sugar_lift_py_tests.outcome import ExitSet
        from sugar_source_tree.panic import SugarNotWritten

        if type(index) is not SliceValue:
            from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
            from sugar_lift_py_tests.ir import ctor

            # Name the lookup without inventing the member. RaisesExc reads
            # ``self.expected_exceptions[0]`` after a bodyless ``tuple(...)``
            # writes this coordinate. Members stay unknown: emit
            # ``py.subscript`` over the construction term the same way
            # ``truth`` emits ``py.truthy`` and ``format_data_model`` names
            # ``call:__format__`` without inventing the formatted string.
            return ExitSet.completed(
                CallSiteValue(
                    target_name="__getitem__",
                    arg_values=(self, index),
                    parameters=(),
                    term=ctor(
                        "py.subscript",
                        (
                            self.to_term(owner="TupleCoordinateValue.subscript"),
                            index.to_term(owner="TupleCoordinateValue.subscript"),
                        ),
                        symbol_kind="coordinate",
                    ),
                    body=None,
                    site=site,
                )
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
        return ExitSet.completed(
            self._from_slice(source=self, index=index, use_occurrence=occurrence)
        )

    def python_isinstance(self, type_name: str, type_term, site):
        """A constructed tuple is exactly an instance of ``tuple`` / ``object``.

        Members stay unknown; the construction itself is still a tuple, so
        ``isinstance(expected_exceptions, type)`` in RaisesExc's mismatch
        diagnostic is False rather than an open predicate that would then
        ask ``issubclass`` of a non-class.
        """
        from sugar_lift_py_tests.floor.python_type_coordinate import (
            authenticated_python_type_spelling,
        )
        from sugar_lift_py_tests.outcome import ExitSet
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )

        del type_name
        authenticated = authenticated_python_type_spelling(
            type_term, owner="TupleCoordinateValue.python_isinstance", site=site
        )
        if authenticated in {"tuple", "object"}:
            return ExitSet.completed(TrueBoolLiteralSugar(site=site))
        if authenticated in {
            "list",
            "dict",
            "set",
            "frozenset",
            "str",
            "bytes",
            "int",
            "bool",
            "float",
            "type",
            "NoneType",
        }:
            return ExitSet.completed(FalseBoolLiteralSugar(site=site))
        return super().python_isinstance(authenticated, type_term, site)

    def test_python_type(self, value, site):
        """Name isinstance against this constructed tuple without inventing members.

        RaisesExc's ``matches`` checks ``isinstance(exception, expected_exceptions)``.
        A tuple of types is valid classinfo. Members stay unknown, so this cannot
        fold to a Bool or expand into an or of per-element tests the way
        TupleValue does. Emit ``adt.is_python_type(value, tuple_term)`` the same
        way ``native_type_tester`` names a cited type coordinate without
        inventing the Boolean.
        """
        from sugar_lift_py_tests.floor.type_tester import native_type_tester

        return native_type_tester(
            value,
            self.to_term(owner="TupleCoordinateValue.test_python_type"),
            site,
        )

    def length(self, site):
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(
            TupleLengthValue(
                target_name="len",
                arg_values=(self,),
                parameters=(),
                term=ctor(
                    call_symbol("len"),
                    (self.term,),
                    symbol_kind="builtin",
                ),
                body=None,
                site=site,
            )
        )
