"""pytest plugin: the main scorecard's per-shard summary (see tools/scorecard_carry.py).

Enable with ``-p scorecard_carry_pytest --carry-label L --carry-summary FILE``.

* ``--carry-summary`` names every node ID that ran with its outcome buckets,
  every collection error and pytest's exit status;
  ``scorecard_carry.py summarize`` turns summaries into totals, and
  tools/main_scorecard_shard_plan.py reads them to check every shard reported
  and to refresh the per-file test-count ledger.
* Every test file that ran has its wall seconds (setup + call + teardown of
  its tests) written to the LPT cost prior when ``SUGAR_LPT_PRIOR_DIR`` is
  set (tools/lpt_file_shards.py), so the next scorecard run packs its shards
  by measured cost (tools/main_scorecard_shard_plan.py, #8416).
* The PYTEST line names the peak resident memory of pytest and of its
  children (``max_rss_mb``, ``children_max_rss_mb``): the memory floor a
  runner seat needs.

Nothing is recorded or carried and no bytecode is instrumented: the
``sys.monitoring`` carry recorder this plugin used to run was deleted (#8416).

Outcome buckets follow tools/python_package_suite_report.py exactly.
"""

from __future__ import annotations

import os
import resource
import time
from pathlib import Path
from typing import Any

import pytest

import scorecard_carry as carry

_ERROR_PHASES = {"setup", "teardown"}


def pytest_addoption(parser: Any) -> None:
    group = parser.getgroup("scorecard-carry", "the main scorecard's shard summary")
    group.addoption(
        "--carry-label",
        default="suite",
        help="the population this pytest measures (suite, twins, tree, source)",
    )
    group.addoption(
        "--carry-summary",
        default=None,
        help="write every node ID's buckets here",
    )


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: Any) -> None:
    summary = config.getoption("--carry-summary")
    if summary:
        config.pluginmanager.register(SummaryPlugin(config, summary), "sugar-scorecard-carry")


class SummaryPlugin:
    def __init__(self, config: Any, summary_path: str):
        self.t0 = time.perf_counter()
        self.config = config
        self.summary_path = summary_path
        self.label = config.getoption("--carry-label")
        self.items_out: dict[str, dict[str, Any]] = {}
        self.buckets: dict[str, list[str]] = {}
        self.collection_errors: list[str] = []
        self.file_seconds: dict[str, float] = {}

    def pytest_collectreport(self, report: Any) -> None:
        if report.failed:
            nodeid = report.nodeid or "<root>"
            if nodeid not in self.collection_errors:
                self.collection_errors.append(nodeid)

    def pytest_runtest_logfinish(self, nodeid: str, location: Any) -> None:
        self.items_out[nodeid] = {"buckets": list(self.buckets.get(nodeid, []))}

    def pytest_runtest_logreport(self, report: Any) -> None:
        file = report.nodeid.split("::", 1)[0]
        self.file_seconds[file] = self.file_seconds.get(file, 0.0) + float(
            getattr(report, "duration", 0.0) or 0.0
        )
        bucket = self.buckets.setdefault(report.nodeid, [])

        def add(name: str) -> None:
            if name not in bucket:
                bucket.append(name)

        xfail = getattr(report, "wasxfail", None) is not None
        if report.failed:
            add("error" if report.when in _ERROR_PHASES else "failed")
        elif report.skipped:
            add("xfailed" if xfail else "skipped")
        elif report.when == "call":
            add("xpassed" if xfail else "passed")

    def pytest_sessionfinish(self, session: Any, exitstatus: int) -> None:
        wall = round(time.perf_counter() - self.t0, 3)
        # ru_maxrss is KiB on Linux.
        own_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024
        children_mb = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss // 1024
        carry.narrate(
            f"SCORECARD CARRY PYTEST label={self.label} ran={len(self.items_out)} "
            f"collection_errors={len(self.collection_errors)} wall_s={wall} "
            f"max_rss_mb={own_mb} children_max_rss_mb={children_mb}"
        )
        self._write_cost_prior()
        carry._write_json(
            self.summary_path,
            {
                "schema": carry.SUMMARY_SCHEMA,
                "label": self.label,
                "items": self.items_out,
                "collectionErrors": self.collection_errors,
                "pytestExitStatus": int(exitstatus),
                "wallSeconds": wall,
            },
        )

    def _write_cost_prior(self) -> None:
        """Each file's measured wall seconds into the shared LPT prior."""
        if not os.environ.get("SUGAR_LPT_PRIOR_DIR") or not self.file_seconds:
            return
        try:
            from lpt_file_shards import ContentAddressedCostPrior

            prior = ContentAddressedCostPrior()
            root = Path(str(self.config.rootpath))
            written = 0
            for file, seconds in self.file_seconds.items():
                path = root / file
                if not path.is_file():
                    continue
                try:
                    if prior.put_for_path(
                        path, seconds, source="scorecard-pytest-wall", path_hint=file
                    ):
                        written += 1
                except OSError:
                    continue
            carry.narrate(
                f"SCORECARD CARRY COSTS label={self.label} files_written={written} "
                f"files_measured={len(self.file_seconds)} prior_root={prior.root}"
            )
        except Exception as error:  # noqa: BLE001 - a prior is never the measurement
            carry.narrate(f"SCORECARD CARRY COSTS label={self.label} not written: {error!r}")
