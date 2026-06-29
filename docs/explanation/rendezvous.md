<!--
  Rendezvous — how kits register interest in a project and the CLI selects them.
  Grounded in implementations/rust/sugar-cli/src/{component_plan.rs,kit_declaration.rs}:
  census_workspace → discover_components → kit-declaration handshake → ComponentPlan.
  This is the FRONT of the pipeline (kit selection), distinct from verification/recompute.
-->
# Rendezvous — how kits register interest in a project

Before a single contract is lifted, the `sugar` CLI has to figure out **which kits
handle this project**. That's the rendezvous: the CLI censuses the project, discovers
the kits that have registered interest, lets each declare what it claims, and assembles
a pinned plan of who does what. The CLI owns the rendezvous; each kit owns its
declaration; nothing about a language is decided above the RPC line.

It runs in four steps (`plan_workspace` in `sugar-cli/src/component_plan.rs`).

## 1. Census

The CLI takes a **workspace census** — `LanguageEvidence` and forensic items: which
languages and project shapes are actually present (a `pyproject.toml` + `.py` files →
Python evidence; a `Cargo.toml` → Rust; a `pom.xml` → Java). The census is the neutral
description of the project that kits get to react to. It does **not** decide which kit
wins — it's the evidence the kits register interest against.

## 2. Discover the registered components

A kit registers interest by dropping a **component manifest** (`manifest.toml`) into one
of the discovery roots. `discover_components()` reads every manifest under, in order:

- `/etc/sugar/components`, `/usr/local/share/sugar/components`, `/usr/share/sugar/components` (system)
- `~/.config/sugar/components` (user)
- the project's own ancestor `.sugar/components/` directories (project-local)
- any paths in the `SUGAR_COMPONENT_PATH` env var

A manifest is small — it only says *who you are and how to start you*:

```toml
name = "rust-walk"
protocol_version = "sugar-lsp-shared/1"
command = ["sugar-walk-rpc", "--rpc"]
# working_dir = "..."   # optional
```

That `command` is the kit's RPC entry point. (This is exactly what you saw failing in a
fresh checkout — `spawn ["…/target/debug/sugar-walk-rpc"]: No such file` means a
registered component's binary wasn't built yet.)

## 3. Each kit declares what it claims

For every discovered component, the CLI spawns its `command` and runs a short JSON-RPC
handshake (`kit_declaration.rs`):

```
initialize  ->  sugar.plugin.kit_declaration  ->  shutdown
```

The middle call is the one that matters: **the kit owns its declaration.** Given the
census, the kit says which surfaces and roles it claims for *this* project — which lift
surfaces it provides, which IR compilers it brings, which package shapes it understands.
The CLI never infers this; it asks, and the kit answers. A kit that doesn't recognize the
project simply claims nothing.

## 4. Assemble the component plan

The CLI collects the declarations into a `ComponentPlan`: the `PlannedLiftManifest`s and
`PlannedIrCompiler`s that will run, plus `ComponentDiagnostic`s for anything that
couldn't register (missing binary, bad manifest, protocol mismatch). **This plan is the
rendezvous** — the agreed, recorded set of "who handles what" for the project. It is part
of what gets pinned: pinning the toolchain plan is what lets an independent party
reproduce the same lift later, not just the same inputs.

## Registering a kit (for kit authors)

To make your kit show up in a project's rendezvous:

1. **Ship an RPC entry point** that speaks the handshake — at minimum `initialize`,
   `sugar.plugin.kit_declaration`, and `shutdown` — and returns a declaration naming the
   lift surfaces / IR compilers you provide.
2. **Register a manifest** (`name`, `protocol_version`, `command`) in a discovery root —
   `.sugar/components/<name>/manifest.toml` for project-local, `~/.config/sugar/components/`
   to make it available everywhere you work.
3. From there, your kit is discovered, declares against the census, and its lift surfaces
   join the plan. What it then lifts is governed by the [lifting rules](../contributing/lifting-rules.md);
   how to structure that lift is the [factory/sugar/floor](../contributing/factory-sugar-floor.md) guideline.

## Where this sits

Rendezvous is the **front** of the pipeline — kit *selection*. It is distinct from the
**back** (verification): once kits are selected and have lifted, the CLI's other job is
to discharge and recompute the result. The CLI owning *both* ends — rendezvous and
verification — while never learning a single Pythonism or Java-ism is exactly what keeps
it language-blind: kits register in their own terms, but everything that crosses the RPC
line is the one content-addressed form.

---

See also: [concepts](concepts.md) · [the docs map](../README.md) ·
[lifting rules](../contributing/lifting-rules.md) · [factory/sugar/floor](../contributing/factory-sugar-floor.md).
