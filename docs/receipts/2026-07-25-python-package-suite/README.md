# First authoritative `sugar-lift-py-tests` package-suite artifact

Produced by `.github/workflows/python-package-suite.yml`, job
`python-package-suite (canonical)`, run
[30173652905](https://github.com/TSavo/sugar/actions/runs/30173652905) on
PR #6280 (merge commit `875add427effaed5fff273fcce6e4121c6b44641`).

This is the first time the whole package has been swept by a job that runs on
every PR and push. Before it, the only whole-package coverage was
`restored-suite-scoreboard`, nightly cron / manual dispatch only — which is why
the 22 unit tests for `ExitSet.and_exit` did not gate #6270, the PR that
rewrote that algebra.

## Counts

Counts are summaries. The node-ID lists in this directory are the evidence, and
every number below is `len()` of a file shipped beside it.

| axis | count | file |
| --- | ---: | --- |
| collected | 1200 | `collected.txt` |
| passed | 1051 | `passed.txt` |
| failed | 132 | `failed.txt` |
| error | 5 | `error.txt` |
| skipped | 12 | `skipped.txt` |
| xfailed | 0 | `xfailed.txt` |
| xpassed | 0 | `xpassed.txt` |
| collectionError | 0 | `collection-error.txt` |
| notReported | 0 | `not-reported.txt` |

`notReported` is 0 and `collectionError` is 0: every collected node produced a
verdict, and no module aborted collection. pytest exit status 1.

## Environment identity

```
environmentIdentityHash  5e00d8745943dbf1d629d778c9d5911b5503fe934108bcb63e3dbf399e6b3d11
python                   CPython 3.12.13, abi cpython-312-x86_64-linux-gnu
platform                 Linux-6.6.87.2-microsoft-standard-WSL2-x86_64-with-glibc2.39
runner                   tsavo-sugar-runner-8c793a4b928d, 32 cpus, load 23.08
wall / cpu               385.34s wall, 304.86s user, 34.54s system
```

**Known gap in this first artifact:** `sourceStamp` is `unavailable`. The
identity minted before the Rust toolchain was on PATH, and
`tools/sugar_source_stamp.py` shells out to cargo. It recorded the failure with
its stderr rather than hashing a hole, which is the right behaviour, but the
build-input testimony is missing from *this* run. Fixed by ordering the
toolchain step before the environment action, and pinned by a new
`Every identity field resolved` step so the ordering cannot silently regress.
The next artifact carries a real stamp; this one is honest about not having one.

## Against the prior art

`docs/receipts/2026-07-25-sugar-lift-py-tests.failed-node-ids.txt` (136 entries)
was explicitly prior art, not truth — it predates several merges and two cache
repairs. Compared node-ID by node-ID against this run's `failed` ∪ `error`
(137 entries), after stripping the `sugar-lift-py-tests/` prefix:

- **136 shared** — every prior-art entry reproduces.
- **0 in prior art only** — nothing silently "fixed".
- **1 new**: `tests/test_numpy_pandas_panic_audit.py::test_missing_sugar_binary_counts_as_unexpected`

That one new entry is **environment-induced, not a verdict about the code**:

```
PermissionError: [Errno 13] Permission denied:
  '/home/runner/.cache/sugar/python-panic-audit-workspaces'
```

The test's own workspace cache under `$HOME/.cache` is not writable by this job
on this runner. It is recorded as red rather than excused — it is a real red on
a real runner — but it names a runner/cache-ownership defect to fix, not a lift
regression. It is not caused by the read-only venv this workflow builds: that
`chmod` covers `$RUNNER_TEMP/sugar-python-test-environment/venv/lib` and never
touches `$HOME/.cache`.

## Reading these files

Never truncate them. A prior agent's `tail -25` over a 28-entry list dropped 4
node IDs and produced a false "4 fixed" claim. Every file here is written in
full by `tools/python_package_suite_summary.py`, and the comparison above was
done with `comm` over sorted whole files.
