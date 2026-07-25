"""Discrimination twins for the Python-package-suite identity gate.

Every tooth here has BOTH faces. A tooth that only ever shows its green face is
not a tooth, so each law is exercised once with the shape that must pass and
once with the shape that must fail, and the failing arm asserts the specific
crime rather than "something went wrong".

The origin: suite run 30175741263 at main d94f67a31 concluded `success` while
publishing `sourceStamp: {"unavailable": "CalledProcessError: ..."}` and
`testExtraInputHash: None`. Counts were fully conserved -- 1212 collected, 1212
verdicts. Complete, attended, conserved, and NOT authoritative: nothing in it
proved which authenticated source and test-input universe produced the
verdicts. Tooth 6 is that exact object, and it must read as unresolved rather
than as a populated field.

Runs with pytest, or standalone with no dependency at all:

    python3 tests/test_python_suite_identity_gate_twins.py
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import stat
import subprocess
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO_ROOT, "tools"))

import python_package_suite_report as suite_report  # noqa: E402
import python_suite_identity_gate as gate  # noqa: E402
import python_test_environment_identity as identity_tool  # noqa: E402

COMMIT = "d94f67a3100000000000000000000000000000ab"
STAMP = "blake3-512_" + "ab" * 64
EXTRAS_HASH = "cd" * 32
ENV_HASH = "ef" * 32

# The marker shape run 30175741263 published, verbatim in structure.
UNAVAILABLE_STAMP = {
    "unavailable": "CalledProcessError: Command '['/opt/hostedtoolcache/Python/"
    "3.12.13/x64/bin/python', 'tools/sugar_source_stamp.py', '--stream']' "
    "returned non-zero exit status 1.",
    "stderr": "error: no such command: `metadata`",
}


def _identity_blob(**overrides):
    blob = {
        "schemaVersion": 1,
        "sourceStamp": {"algorithm": "blake3-512", "value": STAMP},
        "dependencyAuthority": {
            "package": "sugar-lift-py-tests",
            "testExtraInputHash": EXTRAS_HASH,
            "declared": {"optional-dependencies": {"test": ["pytest>=8", "numpy"]}},
        },
        "environmentIdentityHash": ENV_HASH,
    }
    blob.update(overrides)
    return blob


def _report(**overrides):
    """A report that is complete, conserved, and fully identified."""
    collected = ["t.py::a", "t.py::b", "t.py::c", "t.py::d"]
    report = {
        "schemaVersion": 1,
        "measuredCommit": COMMIT,
        "sourceStamp": STAMP,
        "testExtraInputHash": EXTRAS_HASH,
        "environmentIdentityHash": ENV_HASH,
        "binarySourceStamp": STAMP,
        "requestedBinaryProfile": "release",
        "resolvedBinaryProfile": "release",
        "authority": {
            "status": "provisional",
            "profileIdentity": "unverified",
        },
        "environmentIdentity": _identity_blob(),
        "runnerIdentity": {"githubSha": COMMIT},
        "collectedNodeIds": collected,
        "executedOrderNodeIds": collected,
        "passedNodeIds": ["t.py::a", "t.py::b"],
        "failedNodeIds": ["t.py::c"],
        "errorNodeIds": [],
        "skippedNodeIds": ["t.py::d"],
        "xfailedNodeIds": [],
        "xpassedNodeIds": [],
        "notReportedNodeIds": [],
        "collectionErrorNodeIds": [],
        "counts": {
            "collected": 4,
            "passed": 2,
            "failed": 1,
            "error": 0,
            "skipped": 1,
            "xfailed": 0,
            "xpassed": 0,
            "collectionError": 0,
            "notReported": 0,
        },
        "conservation": {
            "collected": 4,
            "verdicts": 4,
            "executedOrder": 4,
            "buckets": {
                "passed": 2,
                "failed": 1,
                "error": 0,
                "skipped": 1,
                "xfailed": 0,
                "xpassed": 0,
                "notReported": 0,
            },
            "collectionError": 0,
        },
    }
    report.update(overrides)
    return report


def _crimes(report, require_commit=COMMIT):
    return gate.gate(report, require_commit)


def _crime_kinds(crimes):
    return {crime.split(" ", 1)[0] for crime in crimes}


# --- tooth 1: sourceStamp resolution failure -------------------------------
#
# Exercised against the REAL `_source_stamp`, with a stand-in
# tools/sugar_source_stamp.py, so the law under test is the minting code path
# rather than a re-description of it. The red arm reproduces the actual failure
# of run 30175741263: the stamp script exits non-zero because cargo is not
# reachable.

_FAKE_STAMP_OK = """#!/usr/bin/env python3
import sys
if "--stream" in sys.argv:
    sys.stdout.buffer.write(b"4:path5:a.rs")
else:
    print("{stamp}")
"""

_FAKE_STAMP_FAILS = """#!/usr/bin/env python3
import sys
print("error: no such command: `metadata`", file=sys.stderr)
sys.exit(1)
"""

_FAKE_STAMP_GARBAGE = """#!/usr/bin/env python3
print("not-a-stamp")
"""


def _repo_with_stamp_script(tmp, body):
    tools = os.path.join(tmp, "tools")
    os.makedirs(tools, exist_ok=True)
    script = os.path.join(tools, "sugar_source_stamp.py")
    with open(script, "w", encoding="utf-8") as handle:
        handle.write(body)
    os.chmod(script, os.stat(script).st_mode | stat.S_IXUSR)
    return tmp


def test_tooth1_source_stamp_resolution():
    with tempfile.TemporaryDirectory() as tmp:
        # GREEN: the stamp resolves to the blake3-512 form sugarbin keys by.
        root = _repo_with_stamp_script(tmp, _FAKE_STAMP_OK.format(stamp=STAMP))
        resolved = identity_tool._source_stamp(root)
        assert resolved["value"] == STAMP, resolved
        assert resolved["preimageBytes"] > 0, resolved
        assert "unavailable" not in resolved, resolved

    with tempfile.TemporaryDirectory() as tmp:
        # RED: the exact failure of run 30175741263 -- and it RAISES, where it
        # used to return a truthy excuse.
        root = _repo_with_stamp_script(tmp, _FAKE_STAMP_FAILS)
        try:
            result = identity_tool._source_stamp(root)
        except identity_tool.IdentityUnresolved as exc:
            assert "cargo" in str(exc), exc
        else:
            raise AssertionError(f"stamp failure was swallowed into {result!r}")

    with tempfile.TemporaryDirectory() as tmp:
        # RED: a stamp of the wrong shape is not a stamp.
        root = _repo_with_stamp_script(tmp, _FAKE_STAMP_GARBAGE)
        try:
            identity_tool._source_stamp(root)
        except identity_tool.IdentityUnresolved as exc:
            assert "blake3-512" in str(exc), exc
        else:
            raise AssertionError("a malformed stamp was accepted")


# --- tooth 2: null extras hash ---------------------------------------------


def test_tooth2_null_extras_hash():
    # GREEN
    assert _crimes(_report()) == []

    # RED: exactly what run 30175741263 shipped -- `testExtraInputHash: None`.
    crimes = _crimes(_report(testExtraInputHash=None))
    assert "crime=identity-absent" in _crime_kinds(crimes), crimes

    # RED: present but covering nothing. A hash of an empty extras table is a
    # hash; it identifies no test-input universe.
    empty = _identity_blob()
    empty["dependencyAuthority"]["declared"]["optional-dependencies"]["test"] = []
    crimes = _crimes(_report(environmentIdentity=empty))
    assert "crime=identity-covers-nothing" in _crime_kinds(crimes), crimes

    # RED: malformed rather than absent.
    crimes = _crimes(_report(testExtraInputHash="none"))
    assert "crime=identity-malformed" in _crime_kinds(crimes), crimes


# --- tooth 3: identity removed from the report, environment prep still green -


def test_tooth3_environment_green_report_stripped():
    prepared = _identity_blob()
    # GREEN at the environment: preparation is genuinely fine.
    assert gate.gate_environment_identity(prepared) == []

    # RED at the artifact anyway: a green environment does not authorise a
    # report that lost the identity on the way to the file. This is the
    # populated-intermediate-silently-lost case, and only checking the
    # SERIALIZED report catches it.
    stripped = _report()
    del stripped["sourceStamp"]
    del stripped["testExtraInputHash"]
    del stripped["environmentIdentityHash"]
    crimes = _crimes(stripped)
    assert "crime=identity-absent" in _crime_kinds(crimes), crimes
    assert len(crimes) >= 3, crimes

    # RED: the whole embedded identity gone, report fields intact.
    crimes = _crimes(_report(environmentIdentity={}))
    assert "crime=identity-absent" in _crime_kinds(crimes), crimes


# --- tooth 4: contradictory testimony --------------------------------------


def test_tooth4_contradictory_testimony():
    other = "0" * 40
    other_stamp = "blake3-512_" + "cc" * 64

    # GREEN: one commit, one stamp, everyone agrees.
    assert _crimes(_report()) == []

    # RED: the report measures a different commit than the job checked out.
    crimes = _crimes(_report(measuredCommit=other))
    assert "crime=contradictory-testimony" in _crime_kinds(crimes), crimes

    # RED: the report contradicts the runner's own GITHUB_SHA.
    crimes = _crimes(_report(runnerIdentity={"githubSha": other}))
    assert "crime=contradictory-testimony" in _crime_kinds(crimes), crimes

    # RED: the environment's stamp is not the stamp the MEASURED BINARY has.
    crimes = _crimes(_report(binarySourceStamp=other_stamp))
    assert "crime=contradictory-testimony" in _crime_kinds(crimes), crimes

    # RED: the top-level copy contradicts the embedded identity it copied.
    crimes = _crimes(_report(sourceStamp=other_stamp, binarySourceStamp=other_stamp))
    assert "crime=contradictory-testimony" in _crime_kinds(crimes), crimes

    # RED: no binary stamp at all -- the source identity is then merely one we
    # recomputed beside the binary, not one the binary carries.
    crimes = _crimes(_report(binarySourceStamp=None))
    assert "crime=identity-absent" in _crime_kinds(crimes), crimes


# --- tooth 5: fully populated matching identity ----------------------------


def test_tooth5_fully_populated_is_green():
    report = _report()
    assert _crimes(report) == []

    # And it is green for its REASON, not by luck: perturb one field at a time
    # and every one of them must go red.
    for field in gate.IDENTITY_FIELDS:
        perturbed = _report()
        perturbed[field] = None
        assert _crimes(perturbed), f"{field} is not load-bearing"

    # Green through the CLI on a serialized file, which is what CI runs.
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "suite-report.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(report, handle)
        assert gate.main(["--report", path, "--require-commit", COMMIT]) == 0
        assert gate.main(["--report", path, "--require-commit", COMMIT]) == 1


# --- tooth 6: the {"unavailable": ...} object is UNRESOLVED, not truthy -----


def test_tooth6_unavailable_marker_is_not_a_value():
    # The premise, stated as an assertion so it cannot rot: the object is
    # truthy, and `x or {}` -- the idiom every reader used -- waves it through.
    assert bool(UNAVAILABLE_STAMP) is True
    assert (UNAVAILABLE_STAMP or {}).get("value") is None

    # RED: run 30175741263's report shape.
    blob = _identity_blob(sourceStamp=UNAVAILABLE_STAMP)
    run_30175741263 = _report(
        environmentIdentity=blob,
        sourceStamp=None,
        testExtraInputHash=None,
        binarySourceStamp=None,
    )
    crimes = _crimes(run_30175741263)
    kinds = _crime_kinds(crimes)
    assert "crime=identity-unresolved" in kinds, crimes
    assert "crime=identity-absent" in kinds, crimes

    # RED at the environment identity too, where it is minted.
    assert gate.gate_environment_identity(blob), "marker accepted at the mint"

    # RED wherever it hides: nesting does not launder it.
    buried = _report()
    buried["environmentIdentity"]["platform"] = {"libc": {"unavailable": "no ldd"}}
    crimes = _crimes(buried)
    assert "crime=identity-unresolved" in _crime_kinds(crimes), crimes

    # GREEN: the same report with the marker replaced by a resolved stamp.
    assert _crimes(_report()) == []


# --- tooth 6b: the reporting plugin refuses to write such a report ----------


class _FakeConfig:
    def __init__(self, options):
        self._options = options

    def getoption(self, name):
        return self._options.get(name.lstrip("-").replace("-", "_"))


def test_plugin_refuses_unresolved_identity_before_measuring():
    with tempfile.TemporaryDirectory() as tmp:
        good = os.path.join(tmp, "good.json")
        bad = os.path.join(tmp, "bad.json")
        with open(good, "w", encoding="utf-8") as handle:
            json.dump(_identity_blob(), handle)
        with open(bad, "w", encoding="utf-8") as handle:
            json.dump(_identity_blob(sourceStamp=UNAVAILABLE_STAMP), handle)

        # GREEN
        reporter = suite_report.SuiteReporter(
            _FakeConfig({"suite_identity": good, "suite_commit": COMMIT})
        )
        assert reporter.identity["environmentIdentityHash"] == ENV_HASH

        # RED, and at CONSTRUCTION -- before a single test has run, so an
        # unresolvable identity costs zero measurement time.
        for options in (
            {"suite_identity": bad, "suite_commit": COMMIT},
            {"suite_identity": None, "suite_commit": COMMIT},
            {"suite_identity": os.path.join(tmp, "nope.json"), "suite_commit": COMMIT},
        ):
            try:
                suite_report.SuiteReporter(_FakeConfig(options))
            except suite_report.SuiteIdentityUnresolved:
                pass
            else:
                raise AssertionError(f"plugin accepted {options!r}")

        # RED: no commit anywhere is an unresolved identity too.
        saved = os.environ.pop("GITHUB_SHA", None)
        try:
            suite_report.SuiteReporter(
                _FakeConfig({"suite_identity": good, "suite_commit": None})
            )
        except suite_report.SuiteIdentityUnresolved:
            pass
        else:
            raise AssertionError("plugin accepted a report with no measured commit")
        finally:
            if saved is not None:
                os.environ["GITHUB_SHA"] = saved


# --- conservation stays a law, not a decoration ----------------------------


def test_conservation_is_checked_on_the_artifact():
    # GREEN
    assert _crimes(_report()) == []

    # RED: a verdict bucket that does not match its own node-ID list.
    broken = _report()
    broken["conservation"]["buckets"]["passed"] = 3
    assert "crime=conservation-broken" in _crime_kinds(_crimes(broken)), broken

    # RED: a collected node with no verdict and no notReported entry.
    lost = _report()
    lost["collectedNodeIds"] = lost["collectedNodeIds"] + ["t.py::e"]
    lost["conservation"]["collected"] = 5
    assert "crime=conservation-broken" in _crime_kinds(_crimes(lost))

    # RED: no conservation block at all.
    bare = _report()
    del bare["conservation"]
    assert "crime=conservation-absent" in _crime_kinds(_crimes(bare))


# --- resolved profile is authenticated testimony ---------------------------


def test_profile_identity_presence_enumeration_and_equality():
    assert _crimes(_report()) == []

    missing_requested = _report()
    del missing_requested["requestedBinaryProfile"]
    crimes = _crimes(missing_requested)
    assert "crime=profile-identity-absent" in _crime_kinds(crimes), crimes

    missing_resolved = _report()
    del missing_resolved["resolvedBinaryProfile"]
    crimes = _crimes(missing_resolved)
    assert "crime=profile-manifest-predates-boundary" in _crime_kinds(crimes), crimes
    assert any("predates the profile identity boundary" in crime for crime in crimes)
    assert not any(
        crime.startswith("crime=profile-identity-mismatch") for crime in crimes
    )

    for field in ("requestedBinaryProfile", "resolvedBinaryProfile"):
        malformed = _report()
        malformed[field] = "fast"
        crimes = _crimes(malformed)
        assert "crime=profile-identity-malformed" in _crime_kinds(crimes), crimes

    mismatch = _report(resolvedBinaryProfile="debug")
    crimes = _crimes(mismatch)
    assert "crime=profile-identity-mismatch" in _crime_kinds(crimes), crimes


# --- authority is a one-way, single-shot artifact transition ---------------


def test_authority_prestate_is_single_shot_and_not_synthesized():
    assert _crimes(_report()) == []

    already = _report(
        authority={"status": "authoritative", "profileIdentity": "resolved"}
    )
    crimes = _crimes(already)
    assert "crime=authority-already-decided" in _crime_kinds(crimes), crimes

    absent = _report()
    del absent["authority"]
    crimes = _crimes(absent)
    assert "crime=authority-object-absent" in _crime_kinds(crimes), crimes

    stale = _report(
        authority={
            "status": "provisional",
            "profileIdentity": "unverified",
            "crimes": ["crime=old"],
        }
    )
    crimes = _crimes(stale)
    assert "crime=authority-stale-crimes" in _crime_kinds(crimes), crimes


def _write_json(path, value):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(value, handle)


def _read_json(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def test_gate_atomically_writes_exact_authority_verdict():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "suite-report.json")
        _write_json(path, _report())

        first_returncode = gate.main(
            ["--report", path, "--require-commit", COMMIT]
        )
        decided = _read_json(path)
        assert decided["authority"] == {
            "status": "authoritative",
            "profileIdentity": "resolved",
        }
        assert "crimes" not in decided["authority"]
        assert not [
            name for name in os.listdir(tmp) if name.startswith(".suite-report-")
        ]
        assert first_returncode == 0

        with contextlib.redirect_stderr(io.StringIO()) as captured:
            second_returncode = gate.main(
                ["--report", path, "--require-commit", COMMIT]
            )
        unchanged = _read_json(path)
        assert unchanged == decided
        assert "crime=authority-already-decided" in captured.getvalue()
        assert second_returncode == 1


def test_gate_replaces_provisional_crimes_with_full_current_list():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "suite-report.json")
        report = _report(resolvedBinaryProfile="debug")
        _write_json(path, report)

        returncode = gate.main(["--report", path, "--require-commit", COMMIT])
        decided = _read_json(path)
        authority = decided["authority"]
        assert authority["status"] == "provisional"
        assert authority["profileIdentity"] == "unresolved"
        assert authority["crimes"] == [
            crime.split(" ", 1)[0] for crime in gate.gate(report, COMMIT)
        ]
        assert returncode == 1


def test_gate_refuses_absent_authority_without_rewriting():
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "suite-report.json")
        report = _report()
        del report["authority"]
        _write_json(path, report)
        before = open(path, "rb").read()

        with contextlib.redirect_stderr(io.StringIO()) as captured:
            returncode = gate.main(
                ["--report", path, "--require-commit", COMMIT]
            )
        assert open(path, "rb").read() == before
        assert "crime=authority-object-absent" in captured.getvalue()
        assert not [
            name for name in os.listdir(tmp) if name.startswith(".suite-report-")
        ]
        assert returncode == 1


def main():
    failures = 0
    for name, function in sorted(globals().items()):
        if not name.startswith("test_") or not callable(function):
            continue
        try:
            function()
        except Exception as exc:  # noqa: BLE001 - this IS the report
            failures += 1
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
        else:
            print(f"ok   {name}")
    print(f"\n{failures} failing")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
