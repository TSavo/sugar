from __future__ import annotations

from pathlib import Path

from tools.datetime_claim_twins_telemetry import summarize


def test_truthful_pipeline_failure_is_one_blocker_not_45_fake_lies(
    tmp_path: Path,
) -> None:
    junit = tmp_path / "junit.xml"
    cases = "".join(
        f'<testcase name="test_datetime_claim_twins_reach_real_sat_unsat_verdicts[sha256:{index}]">'
        '<error message="FactoryPanic in truthful fixture">FactoryPanic: write more Floor</error>'
        "</testcase>"
        for index in range(45)
    )
    junit.write_text(
        f'<testsuite tests="45" errors="45">{cases}</testsuite>', encoding="utf-8"
    )

    vector = summarize(junit, pytest_exit=1, run_url="run")

    assert vector["R"]["truthful_pipeline_error"] == 1
    assert vector["R"]["unevaluated_twins"] == 45
    assert vector["R"]["lying_not_unsat"] == 0
    assert len(vector["offenders"]) == 1


def test_each_lie_is_classified_by_claim_cid(tmp_path: Path) -> None:
    junit = tmp_path / "junit.xml"
    junit.write_text(
        """<testsuite tests="3" failures="2">
<testcase name="test_datetime_claim_twins_reach_real_sat_unsat_verdicts[sha256:good]" />
<testcase name="test_datetime_claim_twins_reach_real_sat_unsat_verdicts[sha256:missing]"><failure message="evaded the referee" /></testcase>
<testcase name="test_datetime_claim_twins_reach_real_sat_unsat_verdicts[sha256:sat]"><failure message="datetime lying twin verdict=sat" /></testcase>
</testsuite>""",
        encoding="utf-8",
    )

    vector = summarize(junit, pytest_exit=1, run_url="run")

    assert vector["passedTwins"] == 1
    assert vector["R"]["missing_claim"] == 1
    assert vector["R"]["lying_not_unsat"] == 1
    assert [row["claimCid"] for row in vector["offenders"]] == [
        "sha256:missing",
        "sha256:sat",
    ]
