# Sugar Build and Execution

`bin/sugarbin` is the single broker for reusable Rust executables and command
execution. It caches executable artifacts. It never caches a command result or
a test result.

## Execution routes

There are three supported operating modes:

| Route | Meaning | Dependency owner |
| --- | --- | --- |
| local ambient | Run on the current machine | The caller |
| bx ambient | Sync to battleaxe and run natively | The caller and battleaxe |
| bx Docker | Sync to battleaxe and run in an immutable capability closure | `sugar-build.toml` |

Ambient routes do not install tools, create virtual environments, or repair the
host. A missing dependency is the caller's environment failure. Managed Docker
routes are the reproducible choice.

The restored-suite workflow is an explicit exception in topology, not an
implicit broker feature: it already runs inside a battleaxe runner container,
declares `SUGAR_EXECUTION_ROUTE=local-ambient`, and installs its job-local
Python environment there. It must not make a nested SSH hop back to bx. This
ambient CI route is visible in the workflow and is not owned by a wrapper.

The broker does not cross-compile. A local build produces the current machine's
native platform. A bx build produces `linux-x86_64`. Therefore an Intel Darwin
artifact must be built on an Intel Mac, and an arm64 Darwin artifact must be
built on an arm64 Mac.

## Commands

Resolve the stamped `sugar` executable for the local native platform:

```bash
bin/sugarbin --profile release
bin/sugarbin --bin sugar-ir-smt-lib --profile release
```

Run locally in the ambient environment:

```bash
bin/sugarbin run --needs sugar -- sugar --version
```

Run on bx without managed dependencies:

```bash
bin/sugarbin run --host bx -- uname -a
bin/sugarbin cargo --host bx -- test -p sugar-cli
```

Run on bx in an immutable managed environment:

```bash
bin/sugarbin run --host bx --env docker:solver-z3 --needs sugar -- sugar --version
bin/sugarbin cargo --host bx --env docker:core -- test -p sugar-cli
bin/sugarbin run --host bx --task python-unit -- -q tests/test_lift.py
```

Resolve binaries without executing a command, or inspect a route without
executing it:

```bash
bin/sugarbin build --host bx --needs sugar,sugar-ir-smt-lib
bin/sugarbin explain --host bx --task examples-gate
bin/sugarbin explain --host bx --env docker:solver-z3 --needs sugar
```

`explain` prints the selected host, environment, observed platform, capability
closure, named task, required executables, and immutable Docker image digest.

`bin/bcargo`, `bin/brun`, and `bin/bpytest` are compatibility adapters. They
select `--host bx`; they do not own synchronization, provisioning, artifact
resolution, or execution policy. `bpytest` additionally selects the managed
`python-unit` task.

## Capabilities and named tasks

`sugar-build.toml` owns exact tool versions, capability dependencies, immutable
image digests, and named tasks. `tools/sugar-build/contract.py` resolves and
validates that declaration. Capabilities are compositional dependency claims;
tasks declare a capability set, required Sugar executables, an argv prefix, and
an explicit `network = "none"` or `network = "required"` policy, which
`sugarbin explain` reports. The caller's arguments are appended and the command
still runs every time. Managed tasks run with Docker networking disabled only
when the named task contract claims a complete dependency closure. Ad-hoc
Docker commands default to networking available because they have no declared
dependency closure.
`examples-gate` declares required networking because its acceptance examples
exercise dependency and language ecosystems that are not an offline contract.
`rust-unit` and `restored-suite-scoreboard` also require networking because
their Cargo commands consume the locked dependency graph and the managed image
does not vendor the Cargo registry.

Current task names are `python-unit`, `python-lift`, `rust-unit`,
`examples-gate`, `pandas-wall`, `numpy-wall`, and
`restored-suite-scoreboard`. Query the checked-in contract rather than copying
their capability lists into wrappers.

To add or update a managed capability:

1. Add its exact tool version and dependency edge to `sugar-build.toml`.
2. Add a Docker target in `tools/sugar-build/Dockerfile` that installs the tool
   and fails its build-time version smoke when the declared version differs.
3. Build the target on bx for `linux/amd64`, push it to
   `ghcr.io/tsavo/sugar-env`, and read the registry's `RepoDigest`.
4. Record only the immutable `ghcr.io/...@sha256:...` reference under the
   sorted capability closure in `[images]`.
5. Add or update the focused contract fixture that resolves the closure and
   runs the tool's version smoke without a network.

Never record a mutable tag as an execution image. Tags are publication handles;
the contract consumes registry digests.

## Executable artifacts and the shelf

Rust source bytes are stamped with BLAKE3-512. The per-executable build identity
also includes the complete Rust and Cargo version reports, native platform and
target triple, profile, features, package, and binary name. Each executable has
an adjacent `<binary>.sugarbin.json` containing exactly:

```text
schema, binary, package, sourceStamp, buildIdentity, platform, targetTriple,
profile, features, rustc, cargo, sha256, built, executed
```

The executable checksum is verified before reuse. Building one executable does
not validate a sibling executable.

The local cache defaults to:

```text
~/.cache/sugar/binaries/
  <binary>-<platform>-<profile>-<buildIdentity>/
    <binary>
    <binary>.sugarbin.json
```

Managed bx artifact builds mount the persistent verified cache at
`/home/tsavo/.cache/sugar/binaries` into the core toolchain container. Override
the host path with `BCARGO_REMOTE_BINARY_CACHE`. Cache identity includes the
container's Rust/Cargo reports, so an ambient artifact cannot alias a managed
toolchain artifact. The core image need not contain `gh` for warm reuse; a valid
local cache cell is verified before the resolver considers a shelf download.
Cargo intermediates live separately under
`/home/tsavo/.cache/sugar/managed-targets/<core-image-digest>` and are mounted as
`/managed-target`; neither Cargo nor the manifest writer touches an ambient bx
workspace target. `BCARGO_REMOTE_MANAGED_TARGET` can override that location.

The GitHub release named by `SUGAR_BINARY_SHELF_TAG` (default
`sugar-binary-shelf`) is a dumb content-addressed shelf. A cache miss downloads
the executable and manifest, verifies them, and otherwise builds and publishes.
Managed containers receive the resolved binaries read-only under
`/opt/sugar/bin`, with `SUGAR_BIN`, `SUGAR_BINARY_DIR`, and `PATH` set to that
verified injection directory. Environment images do not bake in a moving Sugar
binary.

## Cache semantics

A valid local target or shelf hit may skip only Rust compilation. `run`,
`cargo`, and every named task always execute the requested command. Test output,
exit status, reports, and pytest or Cargo results are never cached. Corruption,
an identity mismatch, or a missing manifest invalidates the artifact and either
causes a rebuild or a loud failure when builds are disabled.

## Diagnostics

Use `bin/sugarbin explain ...` first. Unsupported host, environment, or platform
combinations fail before synchronization or command execution. Common loud
diagnostics include:

- missing Python 3.12 for parsing `sugar-build.toml`
- unknown task or capability
- a capability closure without an immutable image
- a requested platform incompatible with the selected native route
- missing `b3sum`, Cargo, Docker, SSH, or rsync
- artifact identity or checksum mismatch
- a required executable that cannot be fetched or built
- a foreign bx executable refused from a Darwin target directory

Once a command starts, its exact exit code is the broker's exit code. Red tests
stay red; the broker never reclassifies them as an environment success.

## Cleanup and recovery

Each checkout maps to a distinct bx root under
`/home/tsavo/remote/sugar-bcargo-<checkout-hash>`. Old safe roots are reaped by
age. Set `BCARGO_CLEAN_REMOTE_ROOT=success` or `always` for explicit cleanup.
Cleanup outside the `sugar-bcargo-*` namespace is refused unless
`BCARGO_CLEAN_REMOTE_ROOT_UNSAFE=1` is explicitly set.

For a poisoned remote checkout, remove only that checkout's printed remote root
and rerun. For a corrupted executable cache cell, remove the named build-identity
directory; the next resolution verifies the shelf or rebuilds. For a Docker
problem, use the digest printed by `explain`, pull that exact digest on bx, and
run the task's version smoke. Do not repair a managed image by installing tools
inside a running container; publish a new image and update the contract digest.

## Focused contracts

```bash
python3.12 -m pytest tests/test_sugar_build_contract.py -q
cargo test --manifest-path implementations/rust/Cargo.toml \
  -p sugar-cli --test sugarbin_execution_contract -- --nocapture
cargo test --manifest-path implementations/rust/Cargo.toml \
  -p sugar-cli --test bcargo_sync_contract -- --nocapture
```

These contracts pin parsing, routing, wrapper thinness, synchronization,
per-executable manifests, immutable image selection, and the stable-zero
duplicate-provisioning instrument.
