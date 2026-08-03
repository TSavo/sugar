# D3 residency exposure before #7171

This is the **before-repair exposure measurement**, not a panic magnitude and
not a frontier-width result.

## Authenticated conditions

- Unrepaired main: `b87bde34c3cdbe4255dccc41a75949242fabe5ca`.
- Counter overlay: five files, local and battleaxe manifests byte-identical at
  `sha256:1525e5a53db7d931b5da5695cf34724255a9d5b6b3b6663a902cd5f735d822b1`.
- Overlay patch: `sha256:e9d22430d49a2a0245d5d0fc4cdb7d4c47e0e0588f66642f74016747e086c0d1`.
- Additive proof: the audit `SourceFile` open count is `1` on base and `1` with
  the counter; the D3 demand call count is `1` on base and `1` with the counter;
  no measurement-gate file changed.
- Battleaxe exclusive lease held at
  `/home/tsavo/.cache/sugar/binaries/.sugar-heavy-measurement.lease`.
- Before gate: `load1=2.47`, `cpu_idle=95.03%`, `nproc=32`.
- After gate: `load1=5.53`, `cpu_idle=90.54%`, `nproc=32`.
- Corpus: pandas `3.0.3`, `1,421` files, aggregate
  `bbb70a76f4032eda3362102c8bd872ca769b6f8143a91f60a36374fa1066b76c`.
- The census restated the same 1,421-file denominator and measured commit.

The counter is available in both sealed-board and frontier-refusal envelopes.
That is load-bearing here: compose refused frontier attestation, so a
sealed-board-only counter would have emitted no result.

## Result

The refusal envelope reports:

- D3 reached: `1,418`; D3 not reached: `3`.
- Resident hit: `1,418`; resident miss: `0`.
- Presence confirmed: `1,418`; mismatch: `0`; unconfirmed: `0`.
- Reporter seated: `0`; reporter unseated: `1,418`.
- Collector registered: `0`; collector empty: `1,418`.
- The raw `hitFiles` and `collectorEmptyFiles` arrays are exactly equal.
- Therefore the headline exposure is **1,418 of 1,421 files took the D3
  residency-hit path and ended with an empty collector**.

The three files that did not reach D3 are:

1. `pandas/io/parsers/readers.py`
2. `pandas/io/pytables.py`
3. `pandas/io/stata.py`

Those are exactly the three surviving With-conservation violations. They
refused before reaching the reporter-binding leak; that early refusal is the
only reason their panics remained visible. The remaining 1,418 files reached
the blind path.

The raw arrays and refusal body are preserved at
`.receipts/hockney-d3-before-b87bde34-02/recensus.json`: 212,462 bytes,
`sha256:18809b841aeb0711be457b066c1cc89456e0736a83748c075a2e01f3aea63ba1`.
The remote and read-only-recovered local copies are byte-identical.

## Refusals and transport observations

- The result is `status=unmeasured`, `measured=false`: compose refused frontier
  attestation with six instrument failures. The D3 exposure survived in that
  refusal envelope; no frontier width was emitted.
- `1,418` is an exposure population. It does **not** say that 1,418 panics were
  lost, nor how many panics were lost inside those files.
- Attempt 1 is excluded. It spent five minutes in pytest's automatic
  `bin/sugarbin --profile release` setup and emitted no test or census signal.
- Attempt 2 is the authenticated measurement described above.
- `brun --sync-back` succeeded previously for individual files, but directory
  sync-back failed here with `mkpath: Not a directory` and rsync code `12`.
  The already-written remote result was recovered read-only and authenticated
  by matching SHA-256. This does not establish directory sync-back support.

The after-repair discrimination is the same population and counter. The repair
must change reporter seating and collector registration without changing the
single-open/single-demand proof; a later authenticated census supplies the
after result.
