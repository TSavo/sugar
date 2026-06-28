<!--
  How-to: behavioral semver / catch drift on upgrade. House rule: receipts, not
  assertions. The `sugar diff` surface (--require/--frozen) is grounded against
  implementations/rust/sugar-cli/src/cmd_diff.rs; the wrappers against
  implementations/rust/cargo-sugar and tools/sugar-check. Where a wrapper's exact
  subcommand isn't confirmed here, point at its --help, don't invent it.
-->
# Catch behavior drift on upgrade — behavioral semver with `sugar diff`

A version number versions the *shadow*: it moves when bytes move and holds still when
behavior moves under a frozen version. `sugar diff` versions the *object* — it compares
two minted proof sets by **behavior, not text**, classifies each behavior-CID as
held / renamed / new / lost, and reports the bump the delta actually implies. It is
the report no vendor can ship, because the dragons are `your coupling ∩ their change`.

## The gate

Grounded in `cmd_diff.rs`:

```sh
sugar diff <a> <b>                  # behavior diff of two minted proof sets
sugar diff <a> <b> --require minor  # fail unless the delta fits within this bump
sugar diff <a> <b> --frozen         # fail iff the accounting moved at all
```

- **`--require none|minor|major`** — the honest-semver gate: *fail unless the behavior
  delta fits within this bump.* `none < minor < major`; `--require minor` rejects a
  MAJOR delta (a behavior lost or changed). The implied bump is computed from the delta
  (`DiffReport::bump()`), so a release that calls itself `minor` while a behavior was
  lost is refused at publish time.
- **`--frozen`** — fail iff the accounting moved *at all*, even an improvement. Pinning,
  not semver — the install-time guard. Overrides `--require`.

The verb exits nonzero when the gate fails; wire that exit into CI or a hook.

## In CI — Rust

`cargo sugar` wraps `sugar diff` against the published baseline and forwards
`--require` (it shells out with `["--require", req]`, `cargo-sugar/src/main.rs`). Run
it in CI so a dishonest bump fails the build; see `cargo sugar --help` for its exact
subcommand surface. The gate it enforces is the `sugar diff --require <bump>` above.

## As a pre-commit hook — Python

`tools/sugar-check` is *"behavioral semver for Python packages: `sugar diff` over the
harvested pytest contracts,"* delivered as a pre-commit hook — one stanza in
`.pre-commit-config.yaml`:

```sh
sugar-check check --rev <git-rev> [--require none|minor|major]
sugar-check diff <a> <b>            # passthrough to `sugar diff`
```

For the exact `.pre-commit-config.yaml` stanza, see
[`tools/sugar-check/README.md`](../../tools/sugar-check/README.md).

## Pinned dependencies — `--frozen`

For a dependency you have pinned, `--frozen` is the install-time guard: any behavior
delta under the fixed version — a poisoned patch shipped under a continuous-looking
version number — fails. New behavior means new effects (reads, writes, sockets), and
effects cannot hide inside a fingerprint that records them: the CID moves, or the
fingerprint is lying.

## Honest scope

This works **today** as `cargo sugar` (Rust) and `sugar-check` (Python). The npm / JS
wedge is in progress — what is missing is the lifter, not the thesis. Full argument:
the README's
[*"Why it matters: the version lied, the behavior moved, Sugar saw it"*](../../README.md#why-it-matters-the-version-lied-the-behavior-moved-sugar-saw-it).

---

See also: [getting-started](../getting-started.md) ·
[publish & inherit a `.proof`](publish-and-inherit-a-proof.md) ·
[concepts](../explanation/concepts.md).
