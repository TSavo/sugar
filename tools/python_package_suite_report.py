"""Authoritative Python-package-suite instrument.

One cold pytest process over the whole package produces ONE report: the exact
collected node-ID manifest in collection order, the exact failed / error /
skipped node-ID sets, timing, and the environment / runner / resource
testimony that makes the verdict re-derivable.

Counts are summaries only. The node-ID lists are the evidence; every count in
the report is derived from a list that is also present in the report.

Usage (as a pytest plugin, never as a conftest):

    python -m pytest <package>/tests -q \
        -p no:cacheprovider -p no:randomly \
        -p python_package_suite_report \
        --suite-report=suite-report.json \
        --suite-identity=environment-identity.json \
        --suite-order=canonical

`--suite-order` exists for the SCHEDULED discrimination run: `reversed` and
`shuffled` execute the identical collected set in a different order, in their
own cold process, and their verdict sets must match the canonical run's. It is
not a per-merge cost -- per-merge CI runs `canonical` only.

This module declares no dependency of its own. It imports stdlib and the
pytest that `sugar-lift-py-tests[test]` already declares -- that table stays
the sole dependency authority (#6275).
"""

from __future__ import annotations

import json
import os
import platform
import random
import sys
import time
from pathlib import Path

# Phase of a report that failed decides failure-vs-error, the same split the
# terminal summary shows: a call-phase failure is a FAILED test, a setup- or
# teardown-phase failure is an ERROR.
_ERROR_PHASES = ("setup", "teardown")

# Job-log doctrine: pytest -q's TTY progress bar does not flush in CI — a
# 200s silence after "[15%]" is blind by construction. Heartbeat every ≤30s
# (and every N finished tests) with running counts so a hard kill still leaves
# what the shard found in the Actions log.
_JOB_LOG_EVERY_N = max(1, int(os.environ.get("SUITE_JOB_LOG_EVERY_N", "25")))

# One owner for "is this field an excuse rather than a value".
from python_suite_identity_gate import (  # noqa: E402
    IDENTITY_FIELDS,
    unavailable_marker as _unavailable_marker,
)

try:
    from job_log_heartbeat import JobLogHeartbeat, narrate  # noqa: E402
except ImportError:  # pragma: no cover — tools/ not on path in exotic launches
    JobLogHeartbeat = None  # type: ignore[misc, assignment]

    def narrate(msg: str) -> None:
        print(msg, flush=True)


class SuiteIdentityUnresolved(Exception):
    """Raised during configure, before a single test runs.

    Deliberately at configure time: an unresolved identity makes the whole
    sweep unpublishable, so paying three hours of measurement first and then
    discovering it is pure waste -- and a report on disk that a later step
    might read.
    """


def pytest_addoption(parser):
    group = parser.getgroup("sugar-package-suite")
    group.addoption(
        "--suite-report",
        action="store",
        default=None,
        metavar="PATH",
        help="write the authoritative suite report JSON to PATH",
    )
    group.addoption(
        "--suite-identity",
        action="store",
        default=None,
        metavar="PATH",
        help="environment-identity JSON to embed verbatim in the report",
    )
    group.addoption(
        "--suite-order",
        action="store",
        default="canonical",
        choices=("canonical", "reversed", "shuffled"),
        help="execution order; collection order is always recorded canonically",
    )
    group.addoption(
        "--suite-shuffle-seed",
        action="store",
        type=int,
        default=None,
        metavar="N",
        help="seed for --suite-order=shuffled (recorded in the report)",
    )
    group.addoption(
        "--suite-commit",
        action="store",
        default=None,
        metavar="SHA",
        help=(
            "the commit these verdicts measure. Required: falls back to "
            "GITHUB_SHA only when that is set, never to a guess."
        ),
    )
    group.addoption(
        "--suite-binary-stamp",
        action="store",
        default=None,
        metavar="STAMP",
        help=(
            "sourceStamp read from the RESOLVED binary's .sugarbin.json "
            "manifest -- the stamp the measured binary actually has"
        ),
    )
    group.addoption(
        "--suite-label",
        action="store",
        default=None,
        metavar="LABEL",
        help="free-form label recorded in the report (e.g. the CI job name)",
    )
    group.addoption(
        "--suite-shard-index",
        action="store",
        type=int,
        default=None,
        metavar="N",
        help=(
            "0-based shard index when the suite runs as parallel CI jobs. "
            "Recorded in the report for enrollment roll call; each shard "
            "writes its own identity-bound report (no shared aggregate)."
        ),
    )
    group.addoption(
        "--suite-shard-count",
        action="store",
        type=int,
        default=None,
        metavar="N",
        help="enrolled shard count (roster size) for this campaign",
    )


class SuiteReporter:
    def __init__(self, config):
        self.config = config
        self.collected: list[str] = []
        self.executed_order: list[str] = []
        self.failed: list[str] = []
        self.errored: list[str] = []
        self.skipped: list[str] = []
        self.xfailed: list[str] = []
        self.xpassed: list[str] = []
        self.passed: list[str] = []
        self.collection_errors: list[str] = []
        self._seen_outcome: set[str] = set()
        self._wall_start = time.perf_counter()
        self._cpu_start = os.times()
        self.shuffle_seed = None
        self._beat: object | None = None
        self._current_nodeid: str | None = None
        # Per-test-file wall seconds (sum of call durations) → LPT prior.
        self._file_duration_s: dict[str, float] = {}
        # Resolved NOW, so an unresolvable identity costs zero measurement.
        self.identity = self._identity()
        self.measured_commit = self._measured_commit()

    # -- collection ---------------------------------------------------------

    def pytest_collection_modifyitems(self, session, config, items):
        # Canonical manifest is captured BEFORE any reordering: the collected
        # set is an order-independent fact about the package.
        self.collected = [item.nodeid for item in items]
        order = config.getoption("--suite-order")
        if order == "reversed":
            items.reverse()
        elif order == "shuffled":
            seed = config.getoption("--suite-shuffle-seed")
            if seed is None:
                seed = random.SystemRandom().randrange(2**31)
            self.shuffle_seed = seed
            random.Random(seed).shuffle(items)
        self.executed_order = [item.nodeid for item in items]
        self._start_job_log_heartbeat()

    def pytest_collectreport(self, report):
        # A collection failure is an error with no test node behind it; it is
        # exactly the #6260 shape, so it must never be summarised away.
        if report.failed:
            self._record(self.collection_errors, report.nodeid or "<root>")

    # -- execution ----------------------------------------------------------

    def pytest_runtest_logstart(self, nodeid, location):
        """Current test — so a 30s alive line names what is blocking."""
        del location
        self._current_nodeid = nodeid
        self._heartbeat(force=False, status="running")

    def pytest_runtest_logreport(self, report):
        nodeid = report.nodeid
        # Accumulate call-phase duration per test file for LPT prior write-through.
        if report.when == "call":
            duration = float(getattr(report, "duration", 0.0) or 0.0)
            file_key = nodeid.split("::", 1)[0]
            self._file_duration_s[file_key] = (
                self._file_duration_s.get(file_key, 0.0) + duration
            )
        if report.failed:
            if report.when in _ERROR_PHASES:
                self._record(self.errored, nodeid)
            else:
                self._record(self.failed, nodeid)
            self._seen_outcome.add(nodeid)
            self._heartbeat_after_outcome(nodeid)
        elif report.skipped:
            if getattr(report, "wasxfail", None) is not None:
                self._record(self.xfailed, nodeid)
            else:
                self._record(self.skipped, nodeid)
            self._seen_outcome.add(nodeid)
            self._heartbeat_after_outcome(nodeid)
        elif report.when == "call":
            if getattr(report, "wasxfail", None) is not None:
                self._record(self.xpassed, nodeid)
            else:
                self._record(self.passed, nodeid)
            self._seen_outcome.add(nodeid)
            self._heartbeat_after_outcome(nodeid)

    def _heartbeat_after_outcome(self, nodeid: str) -> None:
        done = len(self._seen_outcome)
        total = len(self.executed_order) or len(self.collected) or 0
        force = (
            done == 1
            or done == total
            or (done % _JOB_LOG_EVERY_N == 0)
        )
        self._current_nodeid = nodeid
        self._heartbeat(force=force, status="outcome")

    def _start_job_log_heartbeat(self) -> None:
        total = len(self.executed_order) or len(self.collected)
        shard_i = self.config.getoption("--suite-shard-index")
        shard_n = self.config.getoption("--suite-shard-count")
        label = self.config.getoption("--suite-label") or "suite"
        if shard_i is not None and shard_n is not None:
            phase = f"suite-pytest-shard-{int(shard_i):02d}-of-{int(shard_n)}"
        else:
            phase = f"suite-pytest-{label}"
        narrate(
            f"JOB_LOG phase={phase} status=collection_done "
            f"collected={len(self.collected)} to_run={total} "
            f"order={self.config.getoption('--suite-order')}"
        )
        if JobLogHeartbeat is None or total <= 0:
            return
        self._beat = JobLogHeartbeat(phase, total=total)
        # Watch keeps ≤30s silence if one test hangs without logreport.
        self._beat.watch()

    def _heartbeat(self, *, force: bool, status: str) -> None:
        beat = self._beat
        if beat is None:
            return
        done = len(self._seen_outcome)
        extra = {
            "passed": len(self.passed),
            "failed": len(self.failed),
            "error": len(self.errored),
            "skipped": len(self.skipped),
            "xfailed": len(self.xfailed),
            "xpassed": len(self.xpassed),
        }
        if self._current_nodeid:
            # Keep nodeid short enough for log grepping without multi-line mess.
            node = self._current_nodeid
            if len(node) > 160:
                node = node[:157] + "..."
            extra["nodeid"] = node
        beat.tick(n=done, force=force, status=status, **extra)

    @staticmethod
    def _record(bucket, nodeid):
        if nodeid not in bucket:
            bucket.append(nodeid)

    # -- report -------------------------------------------------------------

    def pytest_sessionfinish(self, session, exitstatus):
        # Stop heartbeat first so the last line carries final running counts
        # even if report write fails or the process is about to die.
        if self._beat is not None:
            self._heartbeat(force=True, status="sessionfinish")
            try:
                self._beat.stop(status=f"exit={int(exitstatus)}")
            except Exception:  # noqa: BLE001 — never fail report for narration
                pass
            self._beat = None
        # Write content-addressed LPT prior so the NEXT run packs by measured
        # cost (cold equal-count seeds the shelf; second run is LPT).
        # Never let prior write fail the suite report — missing import or shelf
        # IO must not kill suite-report.json (freeze tip: NameError on Path).
        try:
            self._write_lpt_prior()
        except Exception as error:  # noqa: BLE001 — report is load-bearing
            try:
                narrate(
                    f"JOB_LOG phase=lpt-prior-write status=failed "
                    f"error={type(error).__name__}:{error!s}"
                )
            except Exception:  # noqa: BLE001
                pass
        path = self.config.getoption("--suite-report")
        if not path:
            return
        wall = time.perf_counter() - self._wall_start
        cpu_end = os.times()
        report = {
            "schemaVersion": 1,
            "label": self.config.getoption("--suite-label"),
            "order": self.config.getoption("--suite-order"),
            "shuffleSeed": self.shuffle_seed,
            "shardIndex": self.config.getoption("--suite-shard-index"),
            "shardCount": self.config.getoption("--suite-shard-count"),
            "pytestExitStatus": int(exitstatus),
            # THE REPORT ITSELF CARRIES ITS IDENTITY.
            #
            # These are not a convenience copy of the embedded blob. The
            # artifact is what leaves this machine; a consumer holding only
            # suite-report.json must be able to say WHICH source tree, WHICH
            # declared test extras and WHICH commit produced these verdicts
            # without being handed a second file. Every one is re-checked on
            # the serialized artifact by tools/python_suite_identity_gate.py,
            # and any disagreement with the embedded identity is red.
            "measuredCommit": self.measured_commit,
            "sourceStamp": (self.identity.get("sourceStamp") or {}).get("value"),
            "testExtraInputHash": (
                self.identity.get("dependencyAuthority") or {}
            ).get("testExtraInputHash"),
            "environmentIdentityHash": self.identity.get("environmentIdentityHash"),
            "binarySourceStamp": self.config.getoption("--suite-binary-stamp"),
            "environmentIdentity": self.identity,
            "runnerIdentity": _runner_identity(),
            "resourceTelemetry": _resource_telemetry(),
            "timing": {
                "wallSeconds": round(wall, 6),
                "cpuUserSeconds": round(
                    (cpu_end.user - self._cpu_start.user)
                    + (cpu_end.children_user - self._cpu_start.children_user),
                    6,
                ),
                "cpuSystemSeconds": round(
                    (cpu_end.system - self._cpu_start.system)
                    + (cpu_end.children_system - self._cpu_start.children_system),
                    6,
                ),
                "startedAtUnix": _start_unix(),
                "finishedAtUnix": time.time(),
            },
            # The evidence. Node-ID lists, never counts alone.
            "collectedNodeIds": self.collected,
            "executedOrderNodeIds": self.executed_order,
            "failedNodeIds": self.failed,
            "errorNodeIds": self.errored,
            "skippedNodeIds": self.skipped,
            "xfailedNodeIds": self.xfailed,
            "xpassedNodeIds": self.xpassed,
            "passedNodeIds": self.passed,
            "collectionErrorNodeIds": self.collection_errors,
            "notReportedNodeIds": [
                n for n in self.collected if n not in self._seen_outcome
            ],
            # Summaries only. Every one of these is len() of a list above.
            "counts": {
                "collected": len(self.collected),
                "passed": len(self.passed),
                "failed": len(self.failed),
                "error": len(self.errored),
                "skipped": len(self.skipped),
                "xfailed": len(self.xfailed),
                "xpassed": len(self.xpassed),
                "collectionError": len(self.collection_errors),
                "notReported": len(
                    [n for n in self.collected if n not in self._seen_outcome]
                ),
            },
            # Collection and verdict conservation, stated in the artifact so a
            # consumer can check it rather than take our word. Counts alone
            # said "1212 collected, 1212 verdicts" for run 30175741263 -- true,
            # and worth nothing without an identity beside it.
            "conservation": {
                "collected": len(self.collected),
                "verdicts": len(self._seen_outcome),
                "executedOrder": len(self.executed_order),
                "buckets": {
                    "passed": len(self.passed),
                    "failed": len(self.failed),
                    "error": len(self.errored),
                    "skipped": len(self.skipped),
                    "xfailed": len(self.xfailed),
                    "xpassed": len(self.xpassed),
                    "notReported": len(
                        [n for n in self.collected if n not in self._seen_outcome]
                    ),
                },
                "collectionError": len(self.collection_errors),
            },
        }
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=False)
            handle.write("\n")

    def _identity(self):
        """The environment identity, or nothing at all.

        This used to return `{"unavailable": "..."}` when the identity was
        missing or unreadable. That object is truthy, so every reader
        downstream treated it as a present field -- which is how run
        30175741263 published `sourceStamp: {"unavailable": ...}` under a green
        check. A marker downstream code can mistake for a value is the defect.
        Now the session dies before a report exists to mistake.
        """
        path = self.config.getoption("--suite-identity")
        if not path:
            raise SuiteIdentityUnresolved(
                "no --suite-identity supplied; a suite report without an "
                "environment identity is not a measurement"
            )
        try:
            with open(path, encoding="utf-8") as handle:
                identity = json.load(handle)
        except (OSError, ValueError) as exc:
            raise SuiteIdentityUnresolved(
                f"--suite-identity {path}: {type(exc).__name__}: {exc}"
            ) from None
        marker = _unavailable_marker(identity)
        if marker is not None:
            raise SuiteIdentityUnresolved(
                f"--suite-identity {path} carries an unavailable marker at "
                f"{marker} -- an excuse is not a field value"
            )
        return identity

    def _measured_commit(self):
        """Which commit these verdicts are about. Stated, never inferred.

        `--suite-commit` wins; `GITHUB_SHA` is accepted because CI sets it from
        the checked-out ref. Neither present is an unresolved identity -- we do
        not shell out to `git rev-parse` and call a dirty working tree a
        commit.
        """
        commit = self.config.getoption("--suite-commit") or os.environ.get("GITHUB_SHA")
        if not commit:
            raise SuiteIdentityUnresolved(
                "no --suite-commit and no GITHUB_SHA: the report cannot say "
                "which commit it measured"
            )
        return commit

    def _write_lpt_prior(self) -> None:
        """Persist per-file pytest call seconds into the CA LPT cost shelf."""
        if not self._file_duration_s:
            return
        try:
            from lpt_file_shards import ContentAddressedCostPrior
        except ImportError:
            return
        prior = ContentAddressedCostPrior()
        if not prior.enabled:
            return
        # nodeid file keys are usually relative to pytest rootdir (cwd).
        root = Path(self.config.rootpath)
        written = 0
        for file_key, cost in self._file_duration_s.items():
            candidates = [
                root / file_key,
                Path(file_key),
            ]
            # Workflow runs with working-directory implementations/python.
            if not file_key.startswith("implementations/"):
                candidates.append(
                    root / "implementations" / "python" / file_key
                )
            path = next((p for p in candidates if p.is_file()), None)
            if path is None:
                continue
            if prior.put_for_path(
                path,
                float(cost),
                source="suite-pytest-call-duration",
                path_hint=file_key,
            ):
                written += 1
        narrate(
            f"JOB_LOG phase=lpt-prior-write population=suite-pytest "
            f"files_written={written} files_measured={len(self._file_duration_s)}"
        )


_START_UNIX = time.time()


def _start_unix():
    return _START_UNIX


def _runner_identity():
    return {
        "hostname": platform.node(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "githubRunId": os.environ.get("GITHUB_RUN_ID"),
        "githubRunAttempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "githubJob": os.environ.get("GITHUB_JOB"),
        "githubWorkflow": os.environ.get("GITHUB_WORKFLOW"),
        "githubSha": os.environ.get("GITHUB_SHA"),
        "githubRef": os.environ.get("GITHUB_REF"),
        "runnerName": os.environ.get("RUNNER_NAME"),
        "runnerOs": os.environ.get("RUNNER_OS"),
        "runnerArch": os.environ.get("RUNNER_ARCH"),
    }


def _resource_telemetry():
    telemetry = {
        "cpuCount": os.cpu_count(),
        "pythonExecutable": sys.executable,
    }
    try:
        telemetry["loadAverage1_5_15"] = list(os.getloadavg())
    except (AttributeError, OSError):
        telemetry["loadAverage1_5_15"] = None
    try:
        telemetry["schedAffinityCount"] = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        telemetry["schedAffinityCount"] = None
    try:
        import resource

        usage = resource.getrusage(resource.RUSAGE_CHILDREN)
        telemetry["maxRssChildrenKb"] = usage.ru_maxrss
    except Exception:  # pragma: no cover - platform dependent
        telemetry["maxRssChildrenKb"] = None
    return telemetry


def pytest_configure(config):
    config.pluginmanager.register(SuiteReporter(config), "sugar-suite-reporter")
