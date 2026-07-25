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

# Phase of a report that failed decides failure-vs-error, the same split the
# terminal summary shows: a call-phase failure is a FAILED test, a setup- or
# teardown-phase failure is an ERROR.
_ERROR_PHASES = ("setup", "teardown")


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
        "--suite-label",
        action="store",
        default=None,
        metavar="LABEL",
        help="free-form label recorded in the report (e.g. the CI job name)",
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

    def pytest_collectreport(self, report):
        # A collection failure is an error with no test node behind it; it is
        # exactly the #6260 shape, so it must never be summarised away.
        if report.failed:
            self._record(self.collection_errors, report.nodeid or "<root>")

    # -- execution ----------------------------------------------------------

    def pytest_runtest_logreport(self, report):
        nodeid = report.nodeid
        if report.failed:
            if report.when in _ERROR_PHASES:
                self._record(self.errored, nodeid)
            else:
                self._record(self.failed, nodeid)
            self._seen_outcome.add(nodeid)
        elif report.skipped:
            if getattr(report, "wasxfail", None) is not None:
                self._record(self.xfailed, nodeid)
            else:
                self._record(self.skipped, nodeid)
            self._seen_outcome.add(nodeid)
        elif report.when == "call":
            if getattr(report, "wasxfail", None) is not None:
                self._record(self.xpassed, nodeid)
            else:
                self._record(self.passed, nodeid)
            self._seen_outcome.add(nodeid)

    @staticmethod
    def _record(bucket, nodeid):
        if nodeid not in bucket:
            bucket.append(nodeid)

    # -- report -------------------------------------------------------------

    def pytest_sessionfinish(self, session, exitstatus):
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
            "pytestExitStatus": int(exitstatus),
            "environmentIdentity": self._identity(),
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
        }
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=False)
            handle.write("\n")

    def _identity(self):
        path = self.config.getoption("--suite-identity")
        if not path:
            return {"unavailable": "no --suite-identity supplied"}
        try:
            with open(path, encoding="utf-8") as handle:
                return json.load(handle)
        except OSError as exc:
            # Loud, never silent: an unreadable identity is testimony too.
            return {"unavailable": f"{type(exc).__name__}: {exc}", "path": path}


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
