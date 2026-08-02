# Sample construct panic walk v2 (mr_orange)

**When:** 2026-08-02  
**Seed:** 7135 · **N:** 80 pandas files  
**Schema:** `sample-construct-panic-walk/v2`  
**Reports:** `/tmp/orange_sample_report_v2.json`, `/tmp/orange_sample_report_v2_summary.json`  
**Tip measured:** worktree at origin/main + tool only (`orange/sample-install-root-v2`)  
**Corpus:** host `site-packages/pandas` (battleaxe `.local`), open root via `install_root_for` → site-packages seats.

## v1 failure (do not quote)

v1 rooted open at `.../pandas`, so locus was `_config/display.py` while RECORD seat is `pandas/_config/display.py`.  
**80/80 `SourceUnavailable`** — instrument defect, not construct residual.

## v2 result (quote this)

| status | count |
| --- | ---: |
| clean | 31 |
| construct_panic | 49 |
| functionsSum | 1662 |
| SourceUnavailable | **0** |

### First-panic-per-file ranking (what blocks most sampled files)

| rank | owner | n files | type |
| ---: | --- | ---: | --- |
| 1 | `With._construct_sugar` | **34** | `ContextManagerResolutionConstructionGap` |
| 2 | `FunctionDef.bridge_source_symbol` | **10** | `SugarNotWritten` (absolute locus complaint) |
| 3 | `Try._construct_sugar` | **3** | except identity |
| 4 | `CollectingReporter.present_construction` | **1** | `ConstructedValueTestimonyNotWritten` |
| 5 | `ControlConstructionContextV1.nearest_exception_slot` | **1** | bare raise |

### With managers (34 files) — contract missing at require door

| manager | n |
| --- | ---: |
| `pytest.raises` | 24 |
| `pandas._testing.assert_produces_warning` | 7 |
| `numpy.errstate` | 1 |
| `matplotlib.rc_context` | 1 |
| `warnings.catch_warnings` | 1 |

Fix named by panic: publish/resolve typed `ContextManagerContractRefV1` before construction; With constructs only through the require door.

### Caveats

1. **First panic wins** — later residuals in the same file are invisible. Ranking is file-blocking, not total gap mass.
2. **Not the board** — not recensus denominator; sample only.
3. **Host pandas, not pin** — unless this site-packages matches `docs/ledgers/pins/pandas-3.0.3.pin.json`, do not treat as pin board.
4. **708 release / regression vs pre-708** — **UNMEASURED** by this walk (single tip only). Need paired tip-before vs tip sample or board ΔR for that.
5. **`FunctionDef.bridge_source_symbol` absolute locus** — may be secondary door defect under bridge (open was seat-correct; bridge may re-address absolute). Investigate before treating as missing sugar.

## Tool

`tools/sample_construct_panic_walk.py` — always opens with `install_root_for`.
