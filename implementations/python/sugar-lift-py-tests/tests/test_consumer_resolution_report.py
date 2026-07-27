from __future__ import annotations

from dataclasses import replace

import pytest

from sugar_lift_py_tests.consumer_resolution_report import (
    BinaryCellTestimony,
    CallerAttribution,
    CallerReportTestimony,
    ConsumerResolutionMiss,
    ConsumerResolutionRequest,
    DemandTableCellTestimony,
    LauncherSelectionTestimony,
    print_consumer_hit,
    resolve_consumer_hit,
)
from sugar_lift_py_tests.demand_table_identity import DemandTableIdentityV1
from sugar_lift_py_tests.no_call_body_attribution import AttributionOutcome

STAMP = "blake3-512_" + "b" * 128
MANIFEST = (
    "blake3-512:6f317a5a489eb7e730064d79792f0d1656723130603309e2f2ed9cbedb604ed"
    "a1c4b77a26dc90c980411292ea3994af9015da4cd850b5a307af5a4998b563530"
)
HISTORICAL_PATH_SHAPE_DIGEST = (
    "sha256:a223a4499d0909f22190748b4aca9144e35a58fec31e84cb924e2c25fd3c03d0"
)


def _matching_testimony():
    demand_identity = DemandTableIdentityV1(
        content_key="blake3-512:" + "d" * 128,
        corpus_manifest_cid=MANIFEST,
        schema_version="python-demand-table/v1",
        producer_source_cid="blake3-512:" + "p" * 128,
        resolution_config_cid="blake3-512:" + "r" * 128,
        parser_identity="cpython-3.12",
        file_count=1421,
    )
    binary = BinaryCellTestimony(
        source_stamp=STAMP,
        platform="linux-x86_64",
        profile="release",
        binary_name="sugar",
        artifact_verified=True,
    )
    demand = DemandTableCellTestimony(
        identity=demand_identity,
        runtime="cpython-3.12.13",
        platform="linux-x86_64",
        profile="release",
        artifact_verified=True,
    )
    launcher = LauncherSelectionTestimony(
        runtime="cpython-3.12.13",
        corpus_manifest_cid=MANIFEST,
        corpus_files=1421,
        selected_binary_source_stamp=STAMP,
        selected_binary_platform="linux-x86_64",
        selected_binary_profile="release",
        selected_demand_content_key=demand_identity.content_key,
        selected_demand_runtime="cpython-3.12.13",
        selected_demand_platform="linux-x86_64",
        selected_demand_profile="release",
        artifact_verification_succeeded=True,
    )
    request = ConsumerResolutionRequest(
        source_stamp=STAMP,
        runtime="cpython-3.12.13",
        platform="linux-x86_64",
        profile="release",
        corpus_manifest_cid=MANIFEST,
        corpus_files=1421,
    )
    caller = CallerReportTestimony(
        concrete_source_site="pandas/tests/example.py:41:8",
        before_outcome="named-refusal:opaque-call",
        after_outcome="authenticated-exceptional-exit:TypeError",
        surviving=(
            CallerAttribution(
                AttributionOutcome.NAMED_REFUSAL,
                "opaque native callback remains source-undecided",
            ),
        ),
    )
    return request, binary, demand, launcher, caller


def test_matching_three_artifacts_print_composite_hit():
    request, binary, demand, launcher, caller = _matching_testimony()
    report = resolve_consumer_hit(request, binary, demand, launcher, caller)
    assert report.lines() == (
        f"sourceStamp {STAMP}",
        "runtime cpython-3.12.13",
        f"corpusManifest {MANIFEST}",
        "demandTableIdentity blake3-512:" + "d" * 128,
        "concreteSourceSite reported pandas/tests/example.py:41:8",
        "beforeOutcome reported named-refusal:opaque-call",
        "afterOutcome reported authenticated-exceptional-exit:TypeError",
        "survivingTypedGapsOrReattributions reported "
        "[named-refusal:opaque native callback remains source-undecided]",
    )


def test_matching_three_artifacts_print_to_the_consumer_edge(capsys):
    request, binary, demand, launcher, caller = _matching_testimony()
    print_consumer_hit(request, binary, demand, launcher, caller)
    assert capsys.readouterr().out.splitlines() == [
        f"sourceStamp {STAMP}",
        "runtime cpython-3.12.13",
        f"corpusManifest {MANIFEST}",
        "demandTableIdentity blake3-512:" + "d" * 128,
        "concreteSourceSite reported pandas/tests/example.py:41:8",
        "beforeOutcome reported named-refusal:opaque-call",
        "afterOutcome reported authenticated-exceptional-exit:TypeError",
        "survivingTypedGapsOrReattributions reported "
        "[named-refusal:opaque native callback remains source-undecided]",
    ]


@pytest.mark.parametrize(
    ("coordinate", "mutate"),
    [
        ("source stamp", lambda r: replace(r, source_stamp="blake3-512_" + "0" * 128)),
        ("runtime", lambda r: replace(r, runtime="cpython-3.12.12")),
        ("profile/platform", lambda r: replace(r, profile="debug")),
        (
            "corpus identity",
            lambda r: replace(r, corpus_manifest_cid="sha256:" + "0" * 64),
        ),
    ],
)
def test_each_request_coordinate_misses_by_its_own_name(coordinate, mutate):
    request, binary, demand, launcher, caller = _matching_testimony()
    with pytest.raises(ConsumerResolutionMiss) as caught:
        resolve_consumer_hit(mutate(request), binary, demand, launcher, caller)
    assert caught.value.coordinate == coordinate
    assert str(caught.value).startswith(
        f"consumer resolution MISS: {coordinate} differs:"
    )


def test_platform_difference_is_the_same_named_coordinate_as_profile():
    request, binary, demand, launcher, caller = _matching_testimony()
    request = replace(request, platform="darwin-arm64")
    with pytest.raises(ConsumerResolutionMiss, match=r"MISS: profile/platform differs"):
        resolve_consumer_hit(request, binary, demand, launcher, caller)


def test_consumer_refuses_unverified_artifact_instead_of_printing_a_hit():
    request, binary, demand, launcher, caller = _matching_testimony()
    with pytest.raises(ConsumerResolutionMiss) as caught:
        resolve_consumer_hit(
            request, replace(binary, artifact_verified=False), demand, launcher, caller
        )
    assert caught.value.coordinate == "artifact verification"


def test_historical_path_shape_digest_is_a_named_corpus_identity_miss():
    """Even unanimous testimony cannot upgrade a non-corpus preimage."""
    request, binary, demand, launcher, caller = _matching_testimony()
    request = replace(request, corpus_manifest_cid=HISTORICAL_PATH_SHAPE_DIGEST)
    demand = replace(
        demand,
        identity=replace(
            demand.identity, corpus_manifest_cid=HISTORICAL_PATH_SHAPE_DIGEST
        ),
    )
    launcher = replace(launcher, corpus_manifest_cid=HISTORICAL_PATH_SHAPE_DIGEST)
    with pytest.raises(ConsumerResolutionMiss) as caught:
        resolve_consumer_hit(request, binary, demand, launcher, caller)
    assert caught.value.coordinate == "corpus identity"
    assert HISTORICAL_PATH_SHAPE_DIGEST in str(caught.value)


def test_caller_testimony_cannot_inherit_or_override_artifact_verification():
    request, binary, demand, launcher, caller = _matching_testimony()
    caller = replace(
        caller,
        before_outcome="artifact verification success",
        after_outcome="artifact verification success",
    )
    with pytest.raises(ConsumerResolutionMiss) as caught:
        resolve_consumer_hit(
            request,
            replace(binary, artifact_verified=False),
            demand,
            launcher,
            caller,
        )
    assert caught.value.coordinate == "artifact verification"


def test_surviving_construction_panic_is_not_rendered_as_named_refusal():
    request, binary, demand, launcher, caller = _matching_testimony()
    caller = replace(
        caller,
        surviving=(
            CallerAttribution(
                AttributionOutcome.CONSTRUCTION_PANIC,
                "missing constructed operand",
            ),
        ),
    )
    report = resolve_consumer_hit(request, binary, demand, launcher, caller)
    assert report.lines()[-1].endswith(
        "[construction-panic:missing constructed operand]"
    )


def test_surviving_reattribution_keeps_its_distinct_outcome_name():
    request, binary, demand, launcher, caller = _matching_testimony()
    caller = replace(
        caller,
        surviving=(
            CallerAttribution(
                AttributionOutcome.REATTRIBUTED,
                "Subscript:undecided_subscript",
            ),
        ),
    )

    report = resolve_consumer_hit(request, binary, demand, launcher, caller)

    assert report.lines()[-1].endswith("[reattributed:Subscript:undecided_subscript]")
