# Kit Provenance Gate Design

## Goal

Make every Python report mint testify to the source code actually imported by
the Python kit and refuse before report emission when that source commit differs
from the Rust binary's embedded substrate commit.

## Architecture

The Python kit owns source testimony. A shared Python helper resolves the
imported `sugar_lift_py_tests` and `sugar_lift_python_source` package trees. If
both are in Git, it reports their `HEAD` commit and whether either source tree
is dirty. If Git identity is unavailable, it reports one deterministic
Blake3-512 content identity over both package trees.

The testimony travels in the kit's `initialize` result. Rust preserves that
initialize result through the typed lift session rather than inspecting Python
paths itself. `cmd_lift` compares the kit's clean base commit to the compile-time
`SUGAR_BUILD_GIT_HEAD` before report construction, proof work, rendering, or
output writes.

## Refusal and Rendering

A commit mismatch prints exactly:

```text
refusing to mint from a split pipeline: kit @A != binary @B
```

The command exits nonzero and creates no report. A matching commit proceeds and
the prologue renders `kit source: <identity>` beside `substrate commit`. Dirty
matched trees render `kit source: <commit> (dirty)` but do not refuse: the
committed base is not split, while the annotation loudly discloses local source
changes. A content CID cannot equal a Git commit and therefore refuses against
a Git-identified binary rather than silently weakening the gate.

## Binary Identity

`sugar-cli/build.rs` already embeds `SUGAR_BUILD_GIT_HEAD`, preferring the
explicit build environment and otherwise running `git rev-parse HEAD`. Focused
validation must build a release binary and prove `sugar version --json` reports
the worktree commit rather than an empty or `unknown` value.

## Tests and Receipts

- Python unit tests cover same-tree clean, same-tree dirty, and non-Git content
  fallback testimony.
- Rust focused tests cover initialize testimony preservation, exact mismatch
  refusal text, refusal before output creation, matched rendering, and dirty
  annotation.
- An isolated editable installation pins Black 26.5.1.
- A real battleaxe datetime mint from the branch must show equal kit and
  substrate commits and exit zero.

## Scope

This change is Part of #4577 and Part of #4424. It does not close either issue.
It is not merged and broad validation is telemetry, not a publication gate.
