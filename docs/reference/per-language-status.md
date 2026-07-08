<!--
  Per-language status. House rule: grounded in what EXISTS (implementations/ kits +
  examples/ run.sh). Asserts NO coverage numbers or version figures — that is exactly
  how the previous per-language-status.md drifted. The runnable examples are the test
  of record; run them. Marks ✅ only on demos personally reproduced this session.
-->
# Per-language status

**No coverage numbers here, on purpose.** The previous per-language status drifted
because it hard-coded version and coverage figures; coverage is empirical and moves
faster than prose. This page maps what *exists* — kits and runnable examples — and the
**examples are the test of record**: each `run.sh` mints, proves, and verifies end to
end, so running it is the honest picture of what works today.

> Build the workspace binaries first — the demos invoke `target/debug/…` directly:
> `(cd implementations/rust && cargo build)`.

## First-class kits

Three language kits live under [`implementations/`](../../implementations/):

| Kit | Path | Native surfaces it lifts |
|---|---|---|
| **Rust** | `implementations/rust` | test assertions, `#[requires]`/`#[ensures]` contracts, source walk |
| **Python** | `implementations/python` | pytest/unittest assertions, the source oracle (installed-package bodies) |
| **Java** | `implementations/java` | JUnit / TestNG, JSR-380 / Bean Validation, Maven-shaped package data |

Other languages (e.g. Go) appear in [`examples/`](../../examples/) and the plugin demos
(`examples/lsp-plugins`, `examples/ir-compiler-plugins`) but are **not** first-class
kits under `implementations/` — treat them as demo/plugin-level.

## Runnable evidence, by language

Each entry is a directory under [`examples/`](../../examples/) with a `run.sh`.
(✅ = personally reproduced this session.)

- **Python** — numpy / pandas / sklearn / polars / stdlib:
  `numpy-vendor` ✅, `numpy-showcase` ✅, the inheritance E2E ✅
  (`implementations/python/sugar-lift-py-tests`), `pandas-showcase`, `sklearn-showcase`,
  `polars-showcase`, `python-literal-base64`, `python-urlsafe-seam`,
  `python-bodyguard-precondition`, `python-guard-shapes`.
- **Rust** — std + real crates:
  `rust-coretests-report`, `std-core-showcase`, `serde-json-showcase`, `regex-showcase`,
  `tokio-{channel,await,mutex}-implication-edge`, `uuid-showcase`, `url-showcase`,
  `bitflags-showcase`, `itertools-showcase`, `num-integer-showcase`.
- **Java** — Commons Codec / validation / regex:
  `java-commons-codec-crc32`, `java-codec-universe`, `java-b64-strong`, `java-b64-tails`,
  `java-abs-flagship`, `java-pattern-regex`, `java-urlsafe-seam`, `java-witness-recompute`,
  `signup-service` (a real Maven project).

See [`examples/`](../../examples/) for the full set (~90 demos and fixtures).

## How to read it honestly

- A passing `run.sh` is the claim; anything that does not pass end to end is in progress.
- The behavioral-semver wedges that ship today are `cargo sugar` (Rust) and
  `sugar-check` (Python); the npm / JS wedge is in progress (missing the lifter, not the
  thesis). See [behavioral-semver](../how-to/behavioral-semver.md).
- For the protocol your install speaks, run `sugar self-check`.

---

See also: [getting-started](../getting-started.md) · [examples/](../../examples/) ·
[the docs map](../README.md).
