# Criterion 14 wall baselines: numpy / pandas / scikit-learn / itsdangerous (2026-07-06)

Part of #3731 (retry: predecessor lane orphaned waiting on battleaxe). Seeds
the package-wall matrix in #3731 with measured rows. Consumes the
`lineAccounting` field PR #3721 added to `report_to_json`
(`implementations/rust/sugar-cli/src/report_fmt.rs`), and the Criterion 14
law from #3707.

## Mechanism

All lifts ran on battleaxe via `bin/brun` against a freshly built release
`sugar` binary (`bin/brun -- bin/sugarbin --profile release`, source stamp
`9e31823685f0270437e77f49b60529a3252030407a9bad730ba804e61d4e7f4f40771e56053
7225357022da5b2ea2f2cdacab95b06771ea63fd962ca04ebb431`, built from main at
#3730). `numpy`/`pandas`/`scikit-learn`/`itsdangerous` were pip-installed
into the remote bcargo-provisioned Python kit venv
(`python-kit-env/bin/pip install numpy pandas itsdangerous scikit-learn`)
since the venv `make bcargo-python-kit-env` provisions does not carry them
by default.

- **numpy**, **pandas**: measured via the existing wall runners
  (`tools/numpy_wall.py`, `tools/pandas_wall.py`), which resolve the
  installed package path, copy it into an audit workspace, and run
  `sugar lift --report --json <workspace>`.
- **scikit-learn**, **itsdangerous** (full package, not the #3721 slice
  fixture): no wall runner existed for either. A one-shot ad hoc driver,
  `tools/vendor_source_ledger.py`, reuses the same
  `_resolve_installed_package_path` / `_prepare_audit_workspace` primitives
  to do the same thing for an arbitrary installed package name. It is not
  wired into any gate; it exists to produce this measurement.

## A named, real gap: the wall path does not emit `lineAccounting`

`tools/criterion14_conservation.py` (and the `numpy_wall.py`/`pandas_wall.py`
summarizers PR #3721 rewired) all read the `lineAccounting` field from
`report_fmt::report_to_json`. But whole-directory lift (`sugar lift --report
--json <dir>`) does **not** go through `report_to_json` at all -- it
assembles its JSON directly in `cmd_lift.rs` (around line 3069), emitting
`sourceLedger` / `sourceAudits` / `factoryAudits` / `diagnostics` /
`contracts`, with no `lineAccounting` key anywhere in the object. This was
confirmed by grepping the raw 54 MB numpy report and the 305 MB pandas
report for the literal string `lineAccounting`: zero matches in either, and
`"lineAccounting" in report_json` is `False` for every wall report measured
here.

Consequence: `numpy_wall.py`/`pandas_wall.py`'s post-#3721 `green`/
`red_reasoned`/`red_bare` summary is always `0/0/0` against a real wall run
(confirmed below), and `tools/criterion14_conservation.py` cannot be run
against a whole-package wall report at all -- it has nothing to read. The
`sourceLedger` totals (`source_loci` / `source_warranted` / `source_support`
/ `source_boundary` / `source_unresolved` / `unclassified_source`) are the
only accounting the wall path actually produces today; that is what the
matrix rows below report as "ledger totals." Closing this gap (routing the
directory-lift path's JSON assembly through `line_accounting` the same way
`report_to_json` does) is the real retirement path for every wall row's
`R(unaccounted)` column, not a numbers-massaging fix in the summarizers.

`source_loci` measures audited constructs (one entry per `sourceAudits` row,
matching `contracts` closely), not raw physical line count -- numpy's 1511
and pandas' 8321 are far smaller than either package's physical LOC. This
report uses the vendor's own vocabulary; do not read `source_loci` as
"lines."

## Measured rows

| package | snapshot | ledger totals (`source_loci`/`warranted`/`support`/`boundary`/`unresolved`) | `lineAccounting` present | R(unaccounted, criterion14_conservation.py) | runner/env | retirement path |
|---|---|---|---|---|---|---|
| numpy | 2.5.1 (battleaxe pip) | 1511 / 1511 / 0 / 0 / 0 (0 unclassified) | **no** | not runnable -- wall report has no `lineAccounting` | `tools/numpy_wall.py` via `bin/brun`; wall gate summary all-zero (`green=0 pre_bearing=25 implications=11`, breaches its own `green>=1309` floor) because the gate's summarizer reads a field the wall path never emits | route directory-lift JSON assembly (`cmd_lift.rs`) through `line_accounting`, the same way `report_to_json` already does, so wall-scale reports carry `lineAccounting` too |
| pandas | 3.0.3 (battleaxe pip) | 8321 / 8321 / 0 / 0 / 0 (0 unclassified) | **no** | not runnable, same gap | `tools/pandas_wall.py` via `bin/brun`; wall gate all-zero (`green=0`, breaches `green>=7870` floor) | same as numpy |
| itsdangerous (full package, 8 files) | 2.2.0 (battleaxe pip) | 0 / 0 / 0 / 0 / 0 (0 unclassified) despite 62 real refusal diagnostics and 0 crash | **no** | not runnable | `tools/vendor_source_ledger.py` (new, ad hoc) via `bin/brun`; exit 0, but zero contracts/zero sourceAudits at whole-package scope | distinct from the #3721 slice fixture (R=7 on one 31-line function pair): full-package lift produces *no* warranted content at all today; needs the same `lineAccounting` wiring plus investigation of why whole-file lift yields zero `sourceAudits` where the single-function slice yielded 2 warrant rows |
| scikit-learn | 1.9.0 (battleaxe pip) | unmeasured -- lift dies before any report | n/a (no report emitted) | not runnable | `tools/vendor_source_ledger.py`; exit 2, loud named failure, not a silent skip | close the floor gap: `BinaryOperatorOperation` support for a `SymbolicValue`/`StringValue` operand pair, named at `sklearn/datasets/tests/test_base.py:497:16`, owner `BinOpSugar` |

Full scikit-learn failure payload (not a bare string -- a structured
`LiftPluginDiagnosticPayload`):

```
error: lift plugin diagnostic kind=transport frontend=sugar-cli::lift_plugin
input_format=lift-plugin-json-rpc-v1 path=lift-plugin.transport: lift plugin
returned error: {"code":-32603,"message":"write more Floor for this
Construction: owner=BinOpSugar
blame=sklearn/datasets/tests/test_base.py:497:16
observed=SymbolicValue/StringValue requested=binary operator operand floor
fix=add BinaryOperatorOperation support for SymbolicValue / StringValue", ...}
```

## Receipts

- Distilled measurement fixtures (committed, not the raw 54 MB / 305 MB
  reports which are receipts-too-large-to-commit):
  `tests/fixtures/criterion14/wall-baselines-2026-07-06/numpy.ledger-summary.json`,
  `.../pandas.ledger-summary.json`,
  `.../itsdangerous-full.ledger-summary.json`,
  `.../sklearn.failure.json`.
- Ratchet test pinning these exact numbers against the committed fixtures
  only (never re-lifts): `tests/wall_baselines_2026_07_06_test.py` (4 tests,
  `python3 -m pytest tests/wall_baselines_2026_07_06_test.py -q`: all pass).
- New one-shot driver used for the sklearn/itsdangerous-full measurements:
  `tools/vendor_source_ledger.py`.
- Raw wall-gate stdout (numpy/pandas ratchet-breach summaries) and the raw
  sklearn transport-error JSON are quoted verbatim above; the full 54 MB /
  305 MB `report.json` outputs and the 6 KB sklearn `report.json` (partial,
  tracing-log-then-error, not valid JSON) live only on battleaxe under
  `/home/tsavo/remote/sugar-bcargo-fdfe8f08fe3a/sugar/.sugar/{numpy,pandas,
  sklearn,itsdangerous}-wall/report.json` -- not copied into the repo given
  their size; the distilled summaries above are the durable receipt.

## Ratchet direction

None of these four rows are closed. The single common blocker across
numpy/pandas/itsdangerous is the same one: whole-package lift's JSON
assembly path in `cmd_lift.rs` needs to emit `lineAccounting`, the same way
`report_fmt::report_to_json` already does for the row-based report shape,
before `criterion14_conservation.py` (or any `lineAccounting`-driven wall
gate) can run against it at all. scikit-learn additionally needs a real
`Floor` closed (`BinaryOperatorOperation` for `SymbolicValue`/`StringValue`)
before it produces any report at all. Closing the shared gap first
(numpy/pandas/itsdangerous) is the highest-leverage next step; it does not
touch scikit-learn's separate construction gap.
