# Java Showcase Retirement Design

## Goal

Retire exactly the 19 Java showcases ruled out of scope while preserving them as
enrolled, source-controlled, per-shard testimony. A retirement is neither a pass
nor a failure and must never be confused with a showcase that was never enrolled.

## Authority

`.github/showcase-retirements.json` is the sole retirement authority. Every row
contains an exact enrolled `path`, `language: "java"`, `outcome: "retired"`, and
the reason `out of scope per scope ruling - Java`. Missing reasons, duplicate
paths, unknown paths, unsupported outcomes, or non-Java rows refuse.

The enrolled roster remains `SHOWCASE_RUNS` in the Makefile. Retirement does not
remove a path from that roster. The runner partitions each selected shard row
through the manifest into exactly one of two outcomes:

- `executed`: the showcase body ran and retains its real exit code;
- `retired`: the body did not run and the manifest reason is recorded.

There is no implicit third bucket. Per shard, `executed + retired == enrolled`
is required before a receipt may be written.

## Runtime and Artifact Flow

A small Python owner validates the manifest against the full enrolled roster and
answers the selected shard partition. `make test-showcases` obtains that
partition before executing bodies. Retired rows emit a loud line of the form
`outcome=RETIRED path=... reason=...` and are never invoked. Executed rows follow
the existing pass/fail path unchanged.

The runner writes a per-shard scope receipt. The CI step incorporates it into
`showcase-shard-body.json` as explicit `enrolled`, `executed`, and `retired`
collections and counts. Each retired object retains its path, language, outcome,
and reason. `exitCode` continues to represent executed in-scope work, so any
Python-path or Rust CLI failure keeps the shard and aggregate red.

## Exact Retirement Population

- Shard 0: `java-testng-consistency`, `java-b64-tails`,
  `java-callbind-consistency`, `java-panama-bridge`, `java-pattern-regex`.
- Shard 1: `java-codec-universe`, `java-abs-universe`,
  `java-instance-universe`, `java-abs-model`.
- Shard 2: `java-assertion-consistency`, `java-urlsafe-seam`,
  `java-bound-federation`, `java-voltron`, `java-mt-reference`.
- Shard 3: `java-forall-loop`, `java-b64-strong`, `java-abs-bound`,
  `java-abs-flagship`, `java-crc32-universe`.

All paths are stored in the manifest with the full `examples/.../run.sh`
coordinate. No non-Java showcase may enter the retirement population.

## Discrimination and Conservation

Focused tests prove all of the following:

1. A retired showcase reports `RETIRED` and its body is not executed.
2. A non-retired showcase executes and can make the shard red.
3. Removing a manifest row makes that showcase execute again.
4. A passed showcase cannot acquire the retired outcome.
5. Missing/duplicate/foreign/non-Java manifest rows refuse by name.
6. Each shard conserves `retired + executed == enrolled`.
7. The artifact carries the exact 5/4/5/5 retirement distribution.
8. Active nonzero exits remain nonzero in the shard body and aggregate.

## Predicted Measurement

With in-scope output otherwise unchanged, A2 changes only by removing the Java
nonzero-exit rows: shard 0 `21 -> 16`, shard 1 `22 -> 18`, shard 2 `20 -> 15`,
and shard 3 `20 -> 15`. A1 remains `1/0/1/1`. All four shard bodies remain
attended and red while the measured Python-path and Rust CLI findings remain.

## Non-Goals

- No Java showcase directory or source is deleted.
- No Java result is converted to pass or skip.
- No Python, Rust, Swift, or linux-kernel row is retired.
- No in-scope semantic failure is repaired or reclassified.
- This change does not claim a green acid aggregate.
