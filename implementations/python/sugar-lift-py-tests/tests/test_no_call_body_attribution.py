from __future__ import annotations

import pytest

from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.floor import RaiseValue
from sugar_lift_py_tests.ir import str_const
from sugar_lift_py_tests.no_call_body_attribution import (
    CANONICAL_CORPUS_MANIFEST_CID,
    FAMILY_DENOMINATORS,
    HISTORICAL_PATH_SHAPE_DIGEST,
    AttributionOutcome,
    AttributionInvariantError,
    BodyAttribution,
    BodyProbe,
    DemandTableRefusal,
    ProducerFamily,
    attribute_body_probe,
    attribute_body_probes,
    discover_no_call_body_probes,
    require_expected_denominators,
    summarize_attribution_outcomes,
    validate_shared_demand_table,
)
from sugar_lift_py_tests.outcome import Complete
from sugar_source_tree.panic import SugarNotWritten, UnattributableRefusal


def _probe(family: ProducerFamily, evaluator) -> BodyProbe:
    return BodyProbe(
        body_id=f"pandas/example.py:1:{family.value}",
        family=family,
        evaluator=evaluator,
    )


def _raise_value():
    return Complete(
        RaiseValue(
            RaiseEffect(
                exception_type_coordinate=str_const("TypeError"),
                occurrence="pandas/example.py:1:4",
            )
        )
    )


def _nameless_raise_value():
    return Complete(RaiseValue(RaiseEffect()))


def _call_owned_raise_value():
    return Complete(
        RaiseValue(
            RaiseEffect(
                exception_type_coordinate=str_const("TypeError"),
                occurrence="pandas/example.py:1:4",
                producer_node_owner="Call",
            )
        )
    )


def _named_refusal():
    raise SugarNotWritten(
        blame="test_no_call_body_attribution.py:native-producer",
        owner="native-producer",
        observed="source-visible operands do not decide the failure mode",
        requested="authenticated exceptional exit or retained refusal",
        fix="retain this named refusal without inventing an effect",
    )


def _refusal(*, refusal_type=SugarNotWritten, owner: str):
    raise refusal_type(
        blame="test_no_call_body_attribution.py:boundary",
        owner=owner,
        observed="source-visible construction is unresolved",
        requested="an attributable outcome at this boundary",
        fix="carry the typed refusal to the layer that can classify it",
    )


def _construction_panic():
    from sugar_lift_py_tests.gap.panic import construction_panic_gap

    construction_panic_gap(
        owner="producer-construction",
        blame="pandas/example.py:1",
        observed="missing native operand construction",
        requested="constructed producer operands",
        fix="construct the missing operand without inventing an effect",
    )


def test_truthful_authenticated_body_is_counted_as_an_exceptional_exit() -> None:
    report = attribute_body_probes((_probe(ProducerFamily.SUBSCRIPT, _raise_value),))

    row = report.by_family[ProducerFamily.SUBSCRIPT]
    assert row.authenticated_exceptional_exits == 1
    assert row.named_refusals == 0
    assert row.construction_panics == 0
    assert report.bodies[0].outcome is AttributionOutcome.AUTHENTICATED_EXIT


def test_authenticated_exit_ledger_projects_both_source_coordinates() -> None:
    report = attribute_body_probes((_probe(ProducerFamily.SUBSCRIPT, _raise_value),))

    assert (
        "authenticatedExceptionalExit body=pandas/example.py:1:Subscript "
        f"exceptionTypeCoordinate={str_const('TypeError')!r} "
        "raiseOccurrence=pandas/example.py:1:4"
    ) in report.render()


def test_nameless_halted_face_stays_loud_in_the_exit_ledger() -> None:
    """Lying twin: a Halted face cannot borrow authenticated identity.

    Undischarged excludes the face from the authenticated-exit tally; the
    nameless-halted-face tripwire must still fire (coordinates are carried so
    the scan is reachable). A guard that cannot fire is worse than no guard.
    """
    report = attribute_body_probes(
        (_probe(ProducerFamily.SUBSCRIPT, _nameless_raise_value),)
    )

    row = report.by_family[ProducerFamily.SUBSCRIPT]
    assert row.authenticated_exceptional_exits == 0
    assert row.named_refusals == 0
    assert row.undischarged == 1
    assert len(report.exceptional_exit_identity_discrepancies) == 1
    assert report.exceptional_exit_identity_discrepancies[0].body_id == (
        "pandas/example.py:1:Subscript"
    )
    assert report.exceptional_exit_identity_discrepancies[0].missing == (
        "exceptionTypeCoordinate",
        "raiseOccurrence",
    )
    assert report.loud_failure_count == 1
    assert "authenticatedExceptionalExit body=" not in report.render()
    assert "undischarged body=pandas/example.py:1:Subscript" in report.render()
    assert (
        "NAMELESS HALTED FACE body=pandas/example.py:1:Subscript "
        "missing=exceptionTypeCoordinate,raiseOccurrence"
    ) in report.render()


def test_corpus_tally_does_not_count_nameless_halted_faces_as_exits() -> None:
    report = attribute_body_probes(
        tuple(_probe(ProducerFamily.COMPARE, _nameless_raise_value) for _ in range(503))
    )

    row = report.by_family[ProducerFamily.COMPARE]
    assert row.enrolled == 503
    assert row.authenticated_exceptional_exits == 0
    assert row.named_refusals == 0
    assert row.undischarged == 503
    assert row.construction_panics == 0
    assert report.outcome_total == 503
    # Each nameless face trips the identity tripwire; exits stay zero.
    assert len(report.exceptional_exit_identity_discrepancies) == 503
    assert report.loud_failure_count == 503


def test_declared_typed_gap_is_a_named_refusal_not_a_failure() -> None:
    """Lying twin: declared refusal must not inflate the failure frontier."""
    report = attribute_body_probes((_probe(ProducerFamily.BINOP, _named_refusal),))

    row = report.by_family[ProducerFamily.BINOP]
    assert row.authenticated_exceptional_exits == 0
    assert row.named_refusals == 1
    assert row.construction_panics == 0
    assert row.failures == 0
    assert report.bodies[0].outcome is AttributionOutcome.NAMED_REFUSAL


def test_ordinary_refusal_is_attributed_even_with_provider_owner_spelling() -> None:
    """Lying twin: owner text cannot make an ordinary refusal escape."""
    body = attribute_body_probe(
        _probe(
            ProducerFamily.ATTRIBUTE,
            lambda: _refusal(owner="provider_exception_type_construction"),
        )
    )

    assert body.outcome is AttributionOutcome.NAMED_REFUSAL


def test_unattributable_refusal_escapes_regardless_of_owner_spelling() -> None:
    """Truthful twin: the refusal type, not its owner text, crosses the boundary."""
    probe = _probe(
        ProducerFamily.ATTRIBUTE,
        lambda: _refusal(refusal_type=UnattributableRefusal, owner="unrelated-owner"),
    )

    with pytest.raises(UnattributableRefusal, match="unrelated-owner"):
        attribute_body_probe(probe)


def test_shared_outcome_summary_keeps_refusals_separate_from_panics() -> None:
    bodies = (
        attribute_body_probe(_probe(ProducerFamily.BINOP, _named_refusal)),
        BodyAttribution(
            "pandas/example.py:1:BinOp",
            ProducerFamily.BINOP,
            AttributionOutcome.CONSTRUCTION_PANIC,
            "producer-construction",
        ),
        attribute_body_probe(_probe(ProducerFamily.BINOP, _raise_value)),
    )

    summary = summarize_attribution_outcomes(bodies)

    assert summary.enrolled == 3
    assert summary.authenticated_exceptional_exits == 1
    assert summary.named_refusals == 1
    assert summary.construction_panics == 1


def test_probe_batch_stops_at_construction_panic_before_following_body() -> None:
    """A producer panic cannot be collected while later probes keep running."""
    from sugar_lift_py_tests.gap.panic import ConstructionPanic

    reached_following_probe = False

    def following_probe():
        nonlocal reached_following_probe
        reached_following_probe = True
        return _raise_value()

    with pytest.raises(ConstructionPanic, match="producer-construction"):
        attribute_body_probes(
            (
                _probe(ProducerFamily.SUBSCRIPT, _construction_panic),
                _probe(ProducerFamily.BINOP, following_probe),
            )
        )

    assert reached_following_probe is False


def test_report_keeps_all_six_families_separate() -> None:
    probes = tuple(_probe(family, _named_refusal) for family in ProducerFamily)
    report = attribute_body_probes(probes)

    assert tuple(report.by_family) == tuple(ProducerFamily)
    assert FAMILY_DENOMINATORS == {
        ProducerFamily.SUBSCRIPT: 392,
        ProducerFamily.BINOP: 367,
        ProducerFamily.COMPARE: 181,
        ProducerFamily.ATTRIBUTE: 53,
        ProducerFamily.UNARYOP: 13,
        ProducerFamily.BOOLOP: 2,
    }
    assert sum(FAMILY_DENOMINATORS.values()) == 1008
    assert [row.family for row in report.rows()] == list(ProducerFamily)


def test_construction_panic_propagates_instead_of_becoming_attribution() -> None:
    """Producer-owned construction failure must halt the attribution run."""
    from sugar_lift_py_tests.gap.panic import ConstructionPanic

    with pytest.raises(ConstructionPanic, match="producer-construction"):
        attribute_body_probes((_probe(ProducerFamily.ATTRIBUTE, _construction_panic),))


def test_silent_completion_stays_a_separate_loud_discrepancy() -> None:
    report = attribute_body_probes(
        (_probe(ProducerFamily.BOOLOP, lambda: Complete(object())),)
    )

    assert report.by_family[ProducerFamily.BOOLOP].enrolled == 1
    assert report.outcome_total == 0
    assert report.loud_failure_count == 1
    assert len(report.discrepancies) == 1
    assert "completed without" in report.discrepancies[0].detail
    assert (
        "unaccounted body=pandas/example.py:1:BoolOp node=BoolOp "
        "detail=pandas/example.py:1:BoolOp (BoolOp) completed without"
        in report.render()
    )
    assert (
        "FAMILY OUTCOME DISCREPANCY family=BoolOp enrolled=1 "
        "outcomeTotal=0 unaccounted=1" in report.render()
    )
    assert (
        "OUTCOME TOTAL DISCREPANCY enrolled=1 outcomeTotal=0 discrepancies=1 "
        "conservationShortfall=0"
    ) in report.render()


def test_construction_panic_keeps_producer_owner_not_probe_family() -> None:
    """Lying twin: a Subscript enrollment cannot steal the panic owner."""
    from sugar_lift_py_tests.gap.panic import ConstructionPanic

    with pytest.raises(ConstructionPanic) as raised:
        attribute_body_probe(_probe(ProducerFamily.SUBSCRIPT, _construction_panic))

    assert raised.value.info.owner == "producer-construction"


def test_receiver_call_panic_is_owned_by_call_before_subscript_is_reached() -> None:
    """Lying twin: root shape cannot steal a failure from its receiver Call."""
    from sugar_lift_py_tests.gap.panic import ConstructionPanic, construction_panic_gap

    def receiver_call_panic():
        construction_panic_gap(
            owner="Call",
            blame="pandas/example.py:1:receiver",
            observed="receiver call raised before returning a value",
            requested="a completed receiver before Subscript evaluation",
            fix="attribute this failing edge to Call",
        )

    with pytest.raises(ConstructionPanic) as raised:
        attribute_body_probe(
            BodyProbe(
                body_id="pandas/example.py:1:Subscript",
                family=ProducerFamily.SUBSCRIPT,
                evaluator=receiver_call_panic,
            )
        )

    assert raised.value.info.owner == "Call"


def test_receiver_call_exceptional_exit_is_not_claimed_by_root_subscript() -> None:
    report = attribute_body_probes(
        (_probe(ProducerFamily.SUBSCRIPT, _call_owned_raise_value),)
    )

    body = report.bodies[0]
    assert body.family is ProducerFamily.SUBSCRIPT
    assert body.outcome is AttributionOutcome.AUTHENTICATED_EXIT
    assert body.detail == "Call"


def _table_payload() -> dict:
    return {
        "contentKey": "blake3-512:" + "d" * 128,
        "authentication": {
            "python": "cpython-3.12.13",
            "authenticatedCorpusManifestCid": CANONICAL_CORPUS_MANIFEST_CID,
            "pandas": "3.0.3",
        },
        "identity": {
            "corpusManifestCid": CANONICAL_CORPUS_MANIFEST_CID,
            "fileCount": 1421,
        },
        "rows": [],
    }


def test_shared_table_accepts_only_the_canonical_content_manifest() -> None:
    payload = _table_payload()
    validated = validate_shared_demand_table(
        payload, expected_content_key=payload["contentKey"]
    )
    assert validated is payload

    payload = _table_payload()
    payload["authentication"][
        "authenticatedCorpusManifestCid"
    ] = HISTORICAL_PATH_SHAPE_DIGEST
    payload["identity"]["corpusManifestCid"] = HISTORICAL_PATH_SHAPE_DIGEST
    with pytest.raises(DemandTableRefusal, match="historical path-shape"):
        validate_shared_demand_table(
            payload, expected_content_key=payload["contentKey"]
        )


def test_nameless_tripwire_fires_when_coordinates_are_none() -> None:
    """Mutation as transaction: None-coordinate effects must trip NAMELESS FACE.

    If the undischarged route dropped coordinates, this scan was dead and a
    mutation that flipped counts to authenticated exits had nothing catching it.
    """
    report = attribute_body_probes(
        (_probe(ProducerFamily.BINOP, _nameless_raise_value),)
    )

    assert report.bodies[0].exceptional_exit_coordinates == ((None, None),)
    assert report.exceptional_exit_identity_discrepancies
    assert report.loud_failure_count >= 1
    assert "NAMELESS HALTED FACE body=pandas/example.py:1:BinOp" in report.render()


def test_conservation_shortfall_is_a_hard_loud_failure() -> None:
    """Conservation is asserted, not merely printed.

    A report whose enrolled probes exceed attributed outcomes + discrepancies
    must exit non-zero via loud_failure_count even without AttributionInvariantError.
    """
    from sugar_lift_py_tests.no_call_body_attribution import (
        AttributionReport,
        FamilyAttribution,
    )

    report = AttributionReport(
        bodies=(),
        discrepancies=(),
        exceptional_exit_identity_discrepancies=(),
        by_family={
            family: FamilyAttribution(
                family=family,
                enrolled=1 if family is ProducerFamily.SUBSCRIPT else 0,
                authenticated_exceptional_exits=0,
                named_refusals=0,
                construction_panics=0,
                undischarged=0,
            )
            for family in ProducerFamily
        },
    )

    assert report.conservation_shortfall == 1
    assert report.loud_failure_count == 1
    assert "conservationShortfall=1" in report.render()


def test_resolved_demand_without_matching_with_is_named_not_silent(
    tmp_path,
) -> None:
    """Lying twin: a resolved demand cannot vanish via bare continue."""
    from sugar_lift_python_source.canonical import blake3_512_of

    package = tmp_path / "pandas"
    package.mkdir()
    path = package / "missing_with.py"
    source = "def f():\n    return 1\n"
    path.write_text(source, encoding="utf-8")
    source_cid = blake3_512_of(source.encode())
    rows = [
        {
            "kind": "context-manager-demand",
            "gapKind": None,
            "useSite": {
                "sourceCid": source_cid,
                "startLine": 99,
                "startCol": 0,
                "endLine": 99,
                "endCol": 4,
            },
        }
    ]

    with pytest.raises(AttributionInvariantError, match="no-matching-with"):
        discover_no_call_body_probes({"rows": rows}, package)


def test_discovery_classifies_the_body_root_and_excludes_root_calls(
    tmp_path,
) -> None:
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_source_tree.nodes import With
    from sugar_source_tree.tree import SourceFile

    package = tmp_path / "pandas"
    package.mkdir()
    subscript_path = package / "subscript_body.py"
    subscript_source = (
        "def f(values):\n" "    with boundary(TypeError):\n" "        values[2]\n"
    )
    subscript_path.write_text(subscript_source, encoding="utf-8")
    call_path = package / "call_body.py"
    call_source = "def g():\n    with boundary(TypeError):\n        opaque()\n"
    call_path.write_text(call_source, encoding="utf-8")
    binop_path = package / "binop_body.py"
    binop_source = (
        "def h():\n" "    with boundary(TypeError):\n" "        opaque() + 1\n"
    )
    binop_path.write_text(binop_source, encoding="utf-8")

    rows = []
    for path, source in (
        (subscript_path, subscript_source),
        (call_path, call_source),
        (binop_path, binop_source),
    ):
        source_cid = blake3_512_of(source.encode())
        tree = SourceFile(
            (source, str(path), source_cid),
            construction_context=TreeConstructionContextV1.for_source_call_construction(),
        )
        node = next(item for item in tree.nodes() if isinstance(item, With))
        span = node.items[0].context_expr.line_col_span()
        rows.append(
            {
                "kind": "context-manager-demand",
                "gapKind": None,
                "targetSymbol": (
                    "native.boundary" if path == binop_path else "pytest.raises"
                ),
                "useSite": {
                    "sourceCid": source_cid,
                    "startLine": span.start_line,
                    "startCol": span.start_col,
                    "endLine": span.end_line,
                    "endCol": span.end_col,
                },
            }
        )

    probes = discover_no_call_body_probes({"rows": rows}, package)

    assert [(probe.family, probe.body_id) for probe in probes] == [
        (ProducerFamily.BINOP, "binop_body.py:3:BinOp"),
        (ProducerFamily.SUBSCRIPT, "subscript_body.py:3:Subscript"),
    ]
    # Call root is a named exclusion — never a silent continue that half-writes
    # "this demand did not exist".
    exclusions = discover_no_call_body_probes.last_named_exclusions
    assert any(
        "root-outside-selected-families" in row and "root=Call" in row
        for row in exclusions
    )

    binop_only = discover_no_call_body_probes(
        {"rows": rows}, package, families=frozenset({ProducerFamily.BINOP})
    )
    assert [(probe.family, probe.body_id) for probe in binop_only] == [
        (ProducerFamily.BINOP, "binop_body.py:3:BinOp")
    ]
    subset_exclusions = discover_no_call_body_probes.last_named_exclusions
    assert any("root-outside-selected-families" in row for row in subset_exclusions)


def test_population_selection_never_reads_manager_target_symbol() -> None:
    """All resolved managers enroll; manager spelling grants no membership."""
    assert "targetSymbol" not in discover_no_call_body_probes.__code__.co_consts


def test_discovery_projects_one_family_through_one_typed_construction_per_source(
    tmp_path, monkeypatch
) -> None:
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_source_tree.nodes import With
    from sugar_source_tree.tree import SourceFile

    package = tmp_path / "pandas"
    package.mkdir()
    sources = {
        "attribute_body.py": (
            "def f(series):\n"
            "    with boundary(AttributeError):\n"
            "        series.bad\n"
        ),
        "subscript_body.py": (
            "def g(value):\n    with boundary(IndexError):\n        value[2]\n"
        ),
    }
    rows = []
    subscript_cid = None
    for filename, source in sources.items():
        path = package / filename
        path.write_text(source, encoding="utf-8")
        source_cid = blake3_512_of(source.encode())
        if filename == "subscript_body.py":
            subscript_cid = source_cid
        tree = SourceFile(
            (source, str(path), source_cid),
            construction_context=TreeConstructionContextV1.for_source_call_construction(),
        )
        node = next(item for item in tree.nodes() if isinstance(item, With))
        span = node.items[0].context_expr.line_col_span()
        rows.append(
            {
                "kind": "context-manager-demand",
                "gapKind": None,
                "targetSymbol": "pytest.raises",
                "useSite": {
                    "sourceCid": source_cid,
                    "startLine": span.start_line,
                    "startCol": span.start_col,
                    "endLine": span.end_line,
                    "endCol": span.end_col,
                },
            }
        )

    original = SourceFile.__init__
    constructed_source_cids = []

    def record_construction(self, source, *args, **kwargs):
        constructed_source_cids.append(source[2])
        return original(self, source, *args, **kwargs)

    def refuse_second_traversal(self):
        raise AssertionError("consumer started a second typed traversal")

    monkeypatch.setattr(SourceFile, "__init__", record_construction)
    monkeypatch.setattr(SourceFile, "nodes", refuse_second_traversal)
    probes = discover_no_call_body_probes(
        {"rows": rows}, package, families=frozenset({ProducerFamily.ATTRIBUTE})
    )

    assert [probe.body_id for probe in probes] == ["attribute_body.py:3:Attribute"]
    assert constructed_source_cids == [rows[0]["useSite"]["sourceCid"], subscript_cid]


def test_discovery_carries_source_property_binding_to_attribute_exit(tmp_path) -> None:
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_source_tree.nodes import With
    from sugar_source_tree.tree import SourceFile

    package = tmp_path / "pandas"
    package.mkdir()
    path = package / "property_body.py"
    source = (
        "import pytest\n"
        "class Receiver:\n"
        "    @property\n"
        "    def value(self):\n"
        "        raise ValueError('source getter')\n"
        "def use():\n"
        "    with pytest.raises(ValueError):\n"
        "        Receiver().value\n"
    )
    path.write_text(source, encoding="utf-8")
    source_cid = blake3_512_of(source.encode())
    tree = SourceFile(
        (source, str(path), source_cid),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    with_node = next(node for node in tree.nodes() if isinstance(node, With))
    span = with_node.items[0].context_expr.line_col_span()
    probes = discover_no_call_body_probes(
        {
            "rows": [
                {
                    "kind": "context-manager-demand",
                    "gapKind": None,
                    "useSite": {
                        "sourceCid": source_cid,
                        "startLine": span.start_line,
                        "startCol": span.start_col,
                        "endLine": span.end_line,
                        "endCol": span.end_col,
                    },
                }
            ]
        },
        package,
        families=frozenset({ProducerFamily.ATTRIBUTE}),
    )

    report = attribute_body_probes(probes)

    assert report.discrepancies == ()
    assert (
        report.by_family[ProducerFamily.ATTRIBUTE].authenticated_exceptional_exits == 1
    )
    assert report.by_family[ProducerFamily.ATTRIBUTE].named_refusals == 0


def test_selected_family_denominator_remains_fixed() -> None:
    probes = tuple(
        _probe(ProducerFamily.ATTRIBUTE, _named_refusal)
        for _ in range(FAMILY_DENOMINATORS[ProducerFamily.ATTRIBUTE])
    )
    assert (
        require_expected_denominators(
            probes, families=frozenset({ProducerFamily.ATTRIBUTE})
        )
        == probes
    )

    with pytest.raises(AttributionInvariantError, match="inventory differs"):
        require_expected_denominators(
            probes[:-1], families=frozenset({ProducerFamily.ATTRIBUTE})
        )


def test_attribute_family_denominator_is_native_root_inventory() -> None:
    assert FAMILY_DENOMINATORS[ProducerFamily.ATTRIBUTE] == 53
