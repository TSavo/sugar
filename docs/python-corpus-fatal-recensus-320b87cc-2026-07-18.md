# Python corpus fatal recensus at `320b87cc`

This measurement supersedes [#4775](https://github.com/TSavo/sugar/issues/4775)
and records the completed 1,032-file refresh requested by
[#5121](https://github.com/TSavo/sugar/issues/5121). It is pinned to commit
`320b87cc13375bbdb887e57d1ff4a46100767390`.

This is a measurement report only. The existing aggregate artifacts were read
after the run; no corpus jobs were restarted.

## Completion

The run completed all 1,032 files containing assertions:

- corpus files discovered: 1,828
- files with assertions and triaged: 1,032 / 1,032
- files without assertions: 796
- assertions represented: 20,769

The terminal categories conserve the complete triaged set:

| Terminal category | Files |
|---|---:|
| completed | 812 |
| typed `FactoryPanic` | 190 |
| bare exception | 28 |
| native segfault | 0 |
| timeout | 2 |
| **Total** | **1,032** |

Vector: **812 / 190 / 28 / 0 / 2**.

## Typed-panic owner histogram

The owner counts sum to all 190 typed `FactoryPanic` rows.

| Owner fingerprint | Count |
|---|---:|
| `TemporalContext` | 58 |
| `AppendCallSugar` | 26 |
| `ConstructorCallSugar` | 23 |
| `multiply` | 7 |
| `ImportAliasValue` | 6 |
| `RuntimeEffect` | 5 |
| `FunctionCallable` | 4 |
| `RaiseSugar` | 4 |
| `SequentialDigBody` | 4 |
| `WithSugar` | 4 |
| `add` | 4 |
| `CallSiteValue.truth` | 3 |
| `WhileSugar` | 3 |
| `bitwise_or` | 3 |
| `truth` | 3 |
| `ForElseSugar` | 2 |
| `ForSugar` | 2 |
| `ForSugar.static_unfold` | 2 |
| `FormatDunderCallSugar` | 2 |
| `ImportAliasValue.truth` | 2 |
| `bitwise_and` | 2 |
| `bitwise_invert` | 2 |
| `divide` | 2 |
| `floor_divide` | 2 |
| `python.factory` | 2 |
| `unary_minus` | 2 |
| `.venv-recensus/lib/python3.12/site-packages/pandas/core/frame.py:130:15` | 1 |
| `AttributeSugar` | 1 |
| `GetattrBuiltinSugar` | 1 |
| `WithSugar manager result` | 1 |
| `bitwise_xor` | 1 |
| `left_shift` | 1 |
| `modulo` | 1 |
| `numpy/f2py/f2py2e.py:642:23` | 1 |
| `pandas/core/internals/managers.py:1399:34` | 1 |
| `subscript` | 1 |
| `subtract` | 1 |

## Measurement provenance

- host: `battleaxe`
- Python: 3.12.3
- NumPy: 2.5.1
- pandas: 3.0.3
- remote measurement root:
  `/home/tsavo/remote/fatal-recensus-refresh-320b87cc/sugar`
- authoritative aggregate and embedded per-category lists:
  `receipts/final-combined.json` (`terminal_categories`, `category_files`)
- discovery aggregate: `receipts/discovery-combined.json`
- timeout escalation list: `receipts/timeout-escalation.json`
- shard aggregates: `receipts/shard0.json`, `receipts/shard1.json`,
  `receipts/shard2.json`

At collection time, tmux session `recensus-refresh` remained present with six
idle `sleep` panes. The aggregate was complete and required no restart.

The earlier merged report and checked-in ledger are in
[`python-fatalfront-remeasure-320b87cc-2026-07-18.md`](python-fatalfront-remeasure-320b87cc-2026-07-18.md)
and [`ledgers/recensus-1032-live/`](ledgers/recensus-1032-live/).
