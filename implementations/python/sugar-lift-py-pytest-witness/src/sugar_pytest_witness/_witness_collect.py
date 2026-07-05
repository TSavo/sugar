# SPDX-License-Identifier: MIT OR Apache-2.0
"""A pytest plugin that records (node id -> outcome) for every test in ONE run.

This is what makes the witness PER TEST instead of per file. The old lifter ran
`pytest <file>` and keyed a single witness off the file's exit code, so one
failing test out of thousands refused the whole file. With this plugin the
lifter runs the file ONCE and mints one witness per test node id -- the package's
own execution context (conftest, fixtures, relative imports) is preserved
because it is a normal full-file pytest run.

Outcomes are written as a {nodeid: outcome} JSON map to the path named by the
SUGAR_WITNESS_OUT env var at session end. Recompute (verify) reuses the SAME
single-file run so lift and recompute agree on outcome under shared file state.
"""

import json
import os

_RESULTS: dict[str, str] = {}


def pytest_runtest_logreport(report):
    nodeid = report.nodeid
    if report.when == "call":
        # passed | failed | skipped for the test body itself
        _RESULTS[nodeid] = report.outcome
    elif report.when == "setup" and report.outcome == "failed":
        # a setup/collection error never reaches the call phase; record it so the
        # test is a witness (a 'failed' one), not silently dropped.
        _RESULTS.setdefault(nodeid, "error")


def pytest_sessionfinish(session, exitstatus):
    out = os.environ.get("SUGAR_WITNESS_OUT")
    if out:
        with open(out, "w", encoding="utf-8") as f:
            json.dump(_RESULTS, f)
