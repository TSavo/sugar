"""pytest plugin: carry unchanged test results forward (see tools/scorecard_carry.py).

Enable with ``-p scorecard_carry_pytest --carry-store DIR --carry-summary FILE``.

* After collection, every test whose stored record is still valid for this
  tree is deselected and reported as carried with its recorded outcome.
* Every test that runs is recorded with its depset: what it executed, plus
  what its collectors (module import, parametrization) and its higher-scoped
  fixtures executed, plus everything executed before collection began.
* Every collected test file is recorded with the node IDs it produced, so
  ``scorecard_carry.py suite-plan`` can skip a file without starting pytest.
* ``--carry-summary`` names every node ID with its buckets and whether it was
  carried or rerun; ``scorecard_carry.py summarize`` turns summaries into
  totals.

Outcome buckets follow tools/python_package_suite_report.py exactly.
"""

from __future__ import annotations

import os
import time
from typing import Any

import pytest

import scorecard_carry as carry

_ERROR_PHASES = {"setup", "teardown"}


def pytest_addoption(parser: Any) -> None:
    group = parser.getgroup("scorecard-carry", "carry unchanged results forward")
    group.addoption(
        "--carry-store",
        default=None,
        help="fingerprint store directory; enables carrying and recording",
    )
    group.addoption(
        "--carry-label",
        default="suite",
        help="part of the store key (one label per invocation shape)",
    )
    group.addoption(
        "--carry-summary",
        default=None,
        help="write every node ID's buckets and carried/rerun here",
    )


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: Any) -> None:
    store = config.getoption("--carry-store")
    summary = config.getoption("--carry-summary")
    if store or summary:
        config.pluginmanager.register(
            CarryPlugin(config, store, summary), "sugar-scorecard-carry"
        )


def _ancestor(collector_nodeid: str, file: str) -> bool:
    if collector_nodeid in ("", "."):
        return True
    if collector_nodeid == file or collector_nodeid.startswith(file + "::"):
        return True
    return file.startswith(collector_nodeid.rstrip("/") + "/")


class CarryPlugin:
    def __init__(self, config: Any, store_root: str | None, summary_path: str | None):
        self.t0 = time.perf_counter()
        self.config = config
        self.summary_path = summary_path
        self.label = config.getoption("--carry-label")
        self.items_out: dict[str, dict[str, Any]] = {}
        self.buckets: dict[str, list[str]] = {}
        self.collection_errors: list[str] = []
        self.opaque: dict[str, str] = {}
        self.collector_sinks: dict[str, carry.Sink] = {}
        self.fixture_sinks: dict[int, carry.Sink] = {}
        self._collecting: list[carry.Sink] = []
        self.session: carry.CarrySession | None = None
        self.baseline: carry.Sink | None = None
        if store_root:
            rootdir = str(config.rootpath)
            self.session = carry.CarrySession.open(
                store_root,
                start=rootdir,
                extra=lambda tree: carry.pytest_key_extra(tree, rootdir, self.label),
            )
            if self.session is not None and self.session.recorder is not None:
                self.baseline = self.session.recorder.push()

    @property
    def _recorder(self) -> carry.Recorder | None:
        return self.session.recorder if self.session is not None else None

    # -- collection -------------------------------------------------------

    @pytest.hookimpl(tryfirst=True)
    def pytest_collection(self, session: Any) -> None:
        if self.baseline is not None and self._recorder is not None:
            self._recorder.pop(self.baseline)

    @pytest.hookimpl(hookwrapper=True)
    def pytest_make_collect_report(self, collector: Any):
        # Collector sinks never nest: pytest collects children inside the
        # parent's report, and a parent sink holding every child's imports
        # would make each test depend on every test file. The parent is
        # suspended while a child collects and resumed after.
        recorder = self._recorder
        parent = self._collecting[-1] if self._collecting else None
        sink = None
        if recorder is not None:
            if parent is not None:
                recorder.pop(parent)
            sink = recorder.push()
            self._collecting.append(sink)
        try:
            yield
        finally:
            if sink is not None and recorder is not None:
                recorder.pop(sink)
                self._collecting.pop()
                if parent is not None:
                    recorder.resume(parent)
        if sink is not None:
            existing = self.collector_sinks.get(collector.nodeid)
            if existing is None:
                self.collector_sinks[collector.nodeid] = sink
            else:
                existing.merge(sink)

    def pytest_collectreport(self, report: Any) -> None:
        if report.failed:
            nodeid = report.nodeid or "<root>"
            if nodeid not in self.collection_errors:
                self.collection_errors.append(nodeid)

    @pytest.hookimpl(tryfirst=True)
    def pytest_collection_modifyitems(self, session: Any, config: Any, items: list) -> None:
        if self.session is None:
            return
        self._record_files(items)
        kept, carried = [], []
        for item in items:
            payload = self.session.lookup("test", item.nodeid)
            buckets = payload.get("buckets") if isinstance(payload, dict) else None
            if isinstance(buckets, list):
                self.items_out[item.nodeid] = {"buckets": list(buckets), "how": "carried"}
                carried.append(item)
            else:
                kept.append(item)
        if carried:
            items[:] = kept
            config.hook.pytest_deselected(items=carried)
        carry.narrate(
            f"SCORECARD CARRY COLLECTED label={self.label} carried={len(carried)} "
            f"to_run={len(kept)}"
        )

    def _record_files(self, items: list) -> None:
        by_file: dict[str, list[str]] = {}
        rootdir = str(self.config.rootpath)
        for arg in self.config.args:
            path = arg.split("::", 1)[0]
            if path.endswith(".py") and os.path.isfile(path):
                rel = os.path.relpath(os.path.abspath(path), rootdir).replace(os.sep, "/")
                by_file.setdefault(rel, [])
        for item in items:
            by_file.setdefault(item.nodeid.split("::", 1)[0], []).append(item.nodeid)
        failed = {error.split("::", 1)[0] for error in self.collection_errors}
        for file, nodeids in by_file.items():
            if file in failed or "<root>" in failed:
                continue
            sinks = [self.baseline] + [
                sink for nodeid, sink in self.collector_sinks.items() if _ancestor(nodeid, file)
            ]
            self.session.record("file", file, sinks, {"nodeids": nodeids})  # type: ignore[union-attr]

    # -- execution --------------------------------------------------------

    @pytest.hookimpl(hookwrapper=True)
    def pytest_fixture_setup(self, fixturedef: Any, request: Any):
        recorder = self._recorder
        if recorder is None or fixturedef.scope == "function":
            yield
            return
        sink = recorder.push()
        try:
            yield
        finally:
            recorder.pop(sink)
        self.fixture_sinks.setdefault(id(fixturedef), carry.Sink()).merge(sink)

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_protocol(self, item: Any, nextitem: Any):
        recorder = self._recorder
        sink = recorder.push() if recorder is not None else None
        try:
            yield
        finally:
            if sink is not None and recorder is not None:
                recorder.pop(sink)
        nodeid = item.nodeid
        buckets = list(self.buckets.get(nodeid, []))
        self.items_out[nodeid] = {"buckets": buckets, "how": "rerun"}
        if sink is None or not buckets or self.session is None:
            return
        chain = {node.nodeid for node in item.listchain() if node is not item}
        sinks = [self.baseline, sink]
        sinks.extend(s for nid, s in self.collector_sinks.items() if nid in chain)
        info = getattr(item, "_fixtureinfo", None)
        for defs in (getattr(info, "name2fixturedefs", None) or {}).values():
            for fixturedef in defs:
                fixture_sink = self.fixture_sinks.get(id(fixturedef))
                if fixture_sink is not None:
                    sinks.append(fixture_sink)
        reason = self.session.record("test", nodeid, sinks, {"buckets": buckets})
        if reason is not None:
            self.opaque[nodeid] = reason

    def pytest_runtest_logreport(self, report: Any) -> None:
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

    # -- summary ----------------------------------------------------------

    def pytest_sessionfinish(self, session: Any, exitstatus: int) -> None:
        wall = round(time.perf_counter() - self.t0, 3)
        carried = sum(1 for e in self.items_out.values() if e["how"] == "carried")
        rerun = len(self.items_out) - carried
        recorded = self.session.recorded if self.session is not None else 0
        carry.narrate(
            f"SCORECARD CARRY PYTEST label={self.label} carried={carried} rerun={rerun} "
            f"recorded={recorded} opaque={len(self.opaque)} "
            f"collection_errors={len(self.collection_errors)} wall_s={wall}"
        )
        if self.summary_path:
            carry._write_json(
                self.summary_path,
                {
                    "schema": carry.SUMMARY_SCHEMA,
                    "label": self.label,
                    "items": self.items_out,
                    "collectionErrors": self.collection_errors,
                    "opaque": self.opaque,
                    "pytestExitStatus": int(exitstatus),
                    "wallSeconds": wall,
                },
            )
        if self.session is not None:
            self.session.close()
