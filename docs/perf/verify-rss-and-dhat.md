# sugar verify RSS and dhat profiling

This page is the perf referee for `sugar verify`. Optimization PRs should cite
numbers from this harness before and after the change.

## Peak RSS

Build a `sugar` binary, prepare or choose a project fixture, then run:

```bash
cd implementations/rust
cargo build -p sugar-cli --bin sugar -p sugar-ir-compiler-smt-lib --bin sugar-ir-smt-lib
cd ../..
```

```bash
tools/perf/verify-rss.sh --project-root examples/std-core-showcase/.work/proof-scope --sugar implementations/rust/target/debug/sugar -- --quiet
```

If the showcase fixture is unavailable, generate a synthetic O(100) bridge pool
that exercises `sugar verify` without depending on the lift pipeline:

```bash
cd implementations/rust
cargo run -p sugar-cli --example synthetic_rss_fixture -- /tmp/sugar-rss-synthetic-120 120 --compiler target/debug/sugar-ir-smt-lib
cd ../..
tools/perf/verify-rss.sh --project-root /tmp/sugar-rss-synthetic-120 --sugar implementations/rust/target/debug/sugar --label synthetic-120 -- --quiet
```

The harness calls the host `/usr/bin/time` around:

```bash
sugar verify --project <project-root>
```

It handles both supported time formats:

- macOS: `/usr/bin/time -l`, `maximum resident set size` in bytes.
- Linux CI: `/usr/bin/time -v`, `Maximum resident set size (kbytes)` in KiB.

To arm a 10 percent regression floor, pass the Linux CI reference:

```bash
tools/perf/verify-rss.sh --project-root examples/std-core-showcase/.work/proof-scope --sugar implementations/rust/target/debug/sugar --reference-kib 123456 -- --quiet
```

`--reference-kib` is the measured reference peak RSS, not the already-inflated
budget. The harness computes `ceil(reference_kib * 1.10)` and fails when the
current run exceeds it. Mac numbers are useful local telemetry, but do not set
the Linux CI floor from a Mac run.

The parser/floor self-test is:

```bash
tools/perf/verify-rss.sh --self-test
```

## dhat heap profiling

`sugar-cli` exposes an opt-in `dhat-heap` feature. Normal builds do not link or
start dhat. To profile heap allocations for a verify run:

```bash
cd implementations/rust
cargo run -p sugar-cli --features dhat-heap --bin sugar -- verify --project ../../examples/std-core-showcase/.work/proof-scope --quiet
```

The run writes `dhat-heap.json` in the current directory. Open it with DHAT's
`dh_view.html` viewer, version 3.17 or later. If your workstation has a
`dhat-viewer` wrapper installed, the local command is:

```bash
dhat-viewer dhat-heap.json
```

Use this when a perf claim needs allocation attribution, for example deciding
whether repeated environment cloning or canonical JSON encoding dominates a
particular run. JCS plus BLAKE3 recomputation is correctness-mandatory and is
not an optimization target.
