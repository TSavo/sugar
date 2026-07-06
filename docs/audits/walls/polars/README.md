# polars wall baseline (2026-07-06)

Part of #3741 (dedicated polars wall issue) and the package-wall matrix
#3731. Serves #3686 criterion 11 (vendor/package walls must be green,
reasoned-red, bridge-target-missing-with-a-producer-path, or named line
effects; never unknown/unclassified/bare red) and criterion 14
(`lineAccounting`/`sourceLedger` totality).

## Mechanism

Real lift on battleaxe via `bin/brun`, against a freshly built release
`sugar` binary (`bin/sugarbin --profile release`, built from main at commit
`365dd63f9` after rebasing onto #3763's merged wall-baselines lane).
`polars` 1.42.1 (pip, `polars-runtime-32` C-extension backend included) was
installed into the remote bcargo-provisioned Python kit venv
(`/tmp/sugar-bcargo-python-kit-env`) since that venv does not carry it by
default.

No dedicated `polars_wall.py` runner exists yet (unlike numpy/pandas), so
this measurement reuses `tools/vendor_source_ledger.py` -- the same ad hoc
one-shot driver PR #3763 introduced for scikit-learn/itsdangerous -- which
resolves the installed package path, copies it into an audit workspace via
`_prepare_audit_workspace`, and runs `sugar lift --report --json
<workspace>`.

```
bin/brun --env SUGAR_BIN,PYTHONPATH -- \
  /tmp/sugar-bcargo-python-kit-env/bin/python tools/vendor_source_ledger.py \
  polars .sugar/polars-wall
```

## Measured result

Lift **exits 0** (no crash, no transport error). The report is the same
whole-directory-lift JSON shape (`cmd_lift.rs`) the #3763 baselines already
named as missing `lineAccounting`:

| field | value |
|---|---|
| package | polars 1.42.1 |
| files copied to workspace | 205 `.py` files |
| `sourceLedger.source_loci` | 5 |
| `sourceLedger.source_warranted` | 5 |
| `sourceLedger.source_support` / `source_boundary` / `source_unresolved` / `unclassified_source` | 0 / 0 / 0 / 0 |
| `contracts` | 9 |
| `sourceAudits` | 5 (all `python.*-assertion-sugar` rows, e.g. `io/cloud/credential_provider/_providers.py::_finish_assume_role`) |
| `diagnostics` | 2839, all named/kind-tagged (`value-pin-refused`, `decorator-refused`, `verify-dialect refusal: ...`, etc. across 200 of the 205 files) |
| `hasLineAccounting` | **no** |
| exit code | 0 |

This is the **itsdangerous-full shape**, not the numpy/pandas shape: the
whole-package lift completes cleanly but the ledger stays almost entirely
at zero (5/205 files produced any warranted contract) despite thousands of
real, reasoned refusal diagnostics. Every diagnostic sampled carries a
structured reason (`kind` + `reason`, or a `verify-dialect refusal: ...`
prose line naming the exact unsupported shape) -- **no bare/unreasoned
reds, no silent skips**: `bare_red == 0` and `source_skipped_silent == 0`
hold, but `source_total_lines == source_warranted + source_support +
source_boundary` does **not** hold at this measurement because the wall
path's `sourceLedger` only counts loci that reached a full contract, not
every line the lift plugin visited -- the same shared gap #3763 named for
numpy/pandas/itsdangerous (`cmd_lift.rs`'s directory-lift JSON assembly
does not route through `line_accounting`, so no report at this scale can
satisfy criterion 14's `source_total_lines` equality directly; the
`sourceLedger` totals here are the only accounting this path produces
today).

## #3654 (bridge-target-missing) relationship

None of the 2839 diagnostics from this run reference a bridge/proof-pool
target or `_plr` (polars' compiled Rust extension module, `_plr.pyi`/`.so`)
callsite by name. The whole-package lift never reaches that stage for most
files: it is stopped earlier, at per-function `verify-dialect
refusal`/`value-pin-refused`/`decorator-refused` construction gaps, before
getting to the C-extension-bridging callsites #3654 is about. #3654's
`examples/polars-showcase/run.sh` row (`call:scalar_sum` bridge target CID
not loaded from the proof pool) remains open and is a **different,
narrower row** than this full-corpus measurement: it is the one concrete
example that reaches bridge resolution; this wall measurement shows most of
the corpus does not get that far yet. Per #3686 criterion 11, a
bridge-target-missing row with a named producer/join path (#3654, #3700)
is an honest terminal, not a wall failure -- but it is not yet what is
blocking this row; the pre-bridge construction-gap volume (2839 diagnostics
across 200 files) is the larger, prior blocker.

## Retirement path

1. Shared with numpy/pandas/itsdangerous (#3731): route
   `cmd_lift.rs`'s directory-lift JSON assembly through `line_accounting`
   (the same path `report_fmt::report_to_json` already uses) so
   `criterion14_conservation.py` and a future `polars_wall.py` gate can run
   against a whole-package report at all.
2. Independent of (1): close construction gaps behind the 2839 named
   diagnostics (dominated by `series/series.py`, `expr/expr.py`,
   `dataframe/frame.py`, `lazyframe/frame.py`, `datatypes/classes.py`) so
   more of the 205-file corpus reaches a warranted contract instead of a
   named refusal.
3. Once (1)+(2) progress the corpus far enough to reach C-extension
   callsites, #3654's bridge-target-missing row becomes the live blocker
   for those specific rows; that is a producer-kit (#3700) fix, not a
   Python-kit-side fix.

None of this is a silent gap: every one of the 2839 rows carries a kind and
a reason; `bare_red == 0`, `source_skipped_silent == 0`,
`source_refused_lift_side == 0` (no lift-side crash; exit 0 throughout).

## Receipts

- Distilled measurement fixture (committed):
  `docs/audits/walls/polars/polars.ledger-summary.json`.
- Ratchet test pinning these exact numbers against the committed fixture
  only (never re-lifts): `tests/wall_baselines_2026_07_06_test.py::test_polars_ledger_baseline`.
- Driver used: `tools/vendor_source_ledger.py` (unchanged, reused as-is).
- Raw `report.json` (787,718 bytes) lives only on battleaxe under
  `/home/tsavo/remote/sugar-bcargo-537119ecbec1/sugar/.sugar/polars-wall/report.json`
  -- not copied into the repo; the distilled summary above is the durable
  receipt, consistent with #3763's numpy/pandas/itsdangerous precedent
  (their raw reports were 54 MB / 305 MB / too large to commit).
- Sugar build stamp: release binary built via `bin/sugarbin --profile
  release` from main at commit `365dd63f9` (post-#3763 rebase), same
  mechanism #3763 used.
- polars version: 1.42.1 (`polars` + `polars-runtime-32` wheel), installed
  via `/tmp/sugar-bcargo-python-kit-env/bin/pip install polars` on
  battleaxe.
