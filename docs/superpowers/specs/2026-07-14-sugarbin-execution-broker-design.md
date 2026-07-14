# Sugarbin Execution Broker Design

## Status

Approved conversational design, 2026-07-14.

## Purpose

`bin/sugarbin` becomes the single front door for resolving stamped Rust
executables and running commands locally or on a selected build host. It keeps
one narrow cache promise: Rust executables may be reused when their complete
build identity matches. Commands and test results are never cached. Every
requested command executes and returns its real exit status.

The first managed host is `bx`, an Intel i9-13900K Linux machine. It supports
both its ambient host environment and pinned Docker capability environments.
The local host remains ambient and unmanaged: callers are responsible for
installing local dependencies.

## Concepts

The command model separates three concerns:

- **Host**: where execution occurs, initially `local` or `bx`.
- **Environment**: how dependencies are supplied on that host, initially
  `ambient` or a Docker capability closure.
- **Platform**: the native platform produced by the selected host and
  environment, detected rather than requested by default.

Examples:

```text
local + ambient       -> native platform of the caller
bx + ambient          -> linux-x86_64 using installed battleaxe tools
bx + docker:core      -> linux-x86_64 using the pinned minimum image
bx + docker:z3        -> linux-x86_64 using core plus the Z3 capability
```

An explicit platform is a constraint. It never triggers implicit host
selection, SDK downloading, emulation, or cross-compilation. An incompatible
host, environment, and platform combination fails before execution.

Consequently, an Intel Mac produces `darwin-x86_64`, an Apple Silicon Mac
produces `darwin-arm64`, and battleaxe produces `linux-x86_64`. Darwin
universal binaries and cross-compilation are outside the initial scope.

## Command Surface

Existing artifact resolution remains compatible:

```bash
bin/sugarbin
bin/sugarbin --bin sugar-ir-smt-lib --profile release
```

New execution and build commands are:

```bash
# Local ambient execution. Dependencies are the caller's responsibility.
bin/sugarbin run -- python -m pytest tests/test_factory.py

# Native battleaxe execution using installed host dependencies.
bin/sugarbin run --host bx --env ambient -- cargo test -p sugar-cli

# Managed battleaxe execution in a capability image.
bin/sugarbin run \
  --host bx \
  --env docker:z3 \
  --needs sugar \
  -- python -m pytest

# Cargo-oriented compatibility surface.
bin/sugarbin cargo --host bx --env docker:core -- test -p sugar-cli

# Explicit artifact production on the selected host.
bin/sugarbin build --host bx --env docker:core --profile release

# Explain resolution without executing.
bin/sugarbin explain --host bx --env docker:z3 --needs sugar
```

`--host` defaults to `local`. `--env` defaults to `ambient`. The platform
defaults to the native platform reported by the selected execution route.

## Execution Flow

For every `run`, `cargo`, or `build` request, `sugarbin`:

1. Resolves the selected host and environment.
2. Verifies that their native platform satisfies any explicit platform
   constraint.
3. Synchronizes the checkout when the host is remote, preserving the
   repo-relative working directory.
4. Resolves each binary named by `--needs`.
5. Fetches a matching stamped artifact when available.
6. Builds and publishes only missing artifacts using the selected environment.
7. Injects resolved artifacts into the execution environment and sets stable
   paths such as `SUGAR_BIN`.
8. Executes the requested command unconditionally.
9. Streams stdout and stderr and returns the command's real exit status.
10. Performs explicitly requested sync-back operations after success.

A binary cache hit may skip compilation. It never skips the command or tests.
Docker layer reuse is an implementation detail and never represents a cached
test verdict.

## Docker Capability Graph

The managed Docker system expresses capabilities rather than one permanent
mega-image. The minimum declared versions are:

```text
Rust/Cargo 1.96.0
Python 3.12.13
Black 26.5.1
Pyright 1.1.411
b3sum 1.8.1
```

These minimum tools form `sugar/core`; they are available in every managed
Docker execution. Additional capabilities include pinned Z3, Coq, scientific
Python packages, Java/Maven, Node/pnpm, Vampire, and future tools. Conceptual
layers are:

```text
sugar/core
sugar/python-scientific
sugar/solver-z3
sugar/solver-coq
sugar/java
sugar/node
sugar/vampire
```

Docker cannot combine completed images dynamically, so checked-in declarations
map capability closures to immutable image digests. BuildKit reuses unchanged
lower layers. Human-facing tasks select capabilities, while execution uses the
resolved image by digest.

Example task declarations:

```toml
[tasks.python-unit]
capabilities = []
binaries = []

[tasks.python-lift]
capabilities = ["solver-z3"]
binaries = ["sugar"]

[tasks.examples-gate]
capabilities = [
  "python-scientific",
  "solver-z3",
  "solver-coq",
  "java",
  "node",
  "vampire",
]
binaries = ["sugar", "sugar-ir-smt-lib"]
```

The declarations live in a checked-in build contract such as
`sugar-build.toml`. Image tags are conveniences only; the selected digest is
the durable environment identity.

## Artifact Identity

The Rust executable cache and Docker environment cache remain independent.
Changing Python or Pyright invalidates relevant images but not Rust binaries.
Changing Rust source invalidates binaries but not environment images.

A build-set identity includes:

- Rust source closure
- Cargo lockfile and workspace build inputs
- Rust and Cargo versions
- native target triple
- profile
- feature set
- relevant native build configuration
- requested package and executable set

Each executable has an individual checksum and presence record. Building one
executable cannot mark stale sibling executables valid.

Illustrative manifest:

```json
{
  "schema": 1,
  "buildSet": "blake3-512:...",
  "sourceStamp": "blake3-512:...",
  "environmentDigest": "sha256:...",
  "target": "x86_64-unknown-linux-gnu",
  "profile": "release",
  "features": [],
  "artifacts": {
    "sugar": {
      "sha256": "...",
      "path": "bin/sugar",
      "built": true,
      "executed": true
    }
  }
}
```

The stamped release Sugar binary is injected into task containers rather than
baked into every environment image. Inside a managed container it appears at a
stable location such as `/opt/sugar/bin/sugar`, with its manifest alongside it.
`PATH` and `SUGAR_BIN` point to that verified artifact. A missing or mismatched
manifest fails loudly rather than falling back to an unstamped target binary.

## Reuse of Existing Mechanisms

The refactor preserves proven behavior from `bcargo` and `brun`:

- one rsync transfer over the checked-in synchronization surface
- repo-relative working-directory preservation
- per-worktree remote roots
- stale remote-root reaping
- generated-output exclusions and tracked-file manifest
- argument and path translation
- environment forwarding
- optional sync-back
- foreign-platform binary protection
- streamed output and exact exit-code propagation

The current scripts duplicate much of this behavior. The shared behavior moves
behind the `bx` host backend owned by `sugarbin`.

## Compatibility Wrappers

`bcargo` and `brun` remain as thin host-targeted invocations during and after
migration. Their only durable policy is `host=bx`; they do not own remote
execution machinery:

```text
bcargo ARGS
  -> sugarbin cargo --host bx -- ARGS

brun -- COMMAND
  -> sugarbin run --host bx -- COMMAND
```

They may later accept an environment option that selects Docker, but they no
longer own synchronization, remote roots, dependency provisioning, binary
resolution, or command execution.

Existing environment variables remain supported during migration, including
the shelf repository, remote host, remote root, source stamp, target root,
SSH, and rsync overrides. Deprecation requires explicit replacement coverage
and focused compatibility tests.

## Failure Semantics

The broker fails before command execution when:

- a host is unknown or unavailable
- an environment is unsupported on the selected host
- an explicit platform conflicts with the selected route
- an image digest cannot be resolved or built
- a required binary cannot be fetched or built
- an artifact checksum or manifest does not match
- synchronization or path translation fails

Once execution begins, the child command owns success or failure. Its exit code
and termination signal propagate unchanged. The broker does not reinterpret a
red test as an environment success and does not reuse earlier test results.

`explain` prints host, environment, platform, capability closure, image digest,
required binaries, build-set identities, cache decisions, synchronization
root, working directory, and final command without performing execution.

## Testing Strategy

Focused contract tests pin:

- local ambient execution never invokes SSH or Docker
- bx ambient execution invokes SSH but not Docker
- bx Docker execution selects the exact image digest
- commands execute after both binary cache hits and misses
- shelf hits skip Cargo compilation
- misses build and publish once
- each executable is validated independently
- working directory, arguments, environment, and sync-back are preserved
- exit codes and signals propagate through every backend
- foreign binaries never become the local executable
- incompatible host/environment/platform combinations fail before execution
- task capability declarations resolve deterministically
- changing a Python capability does not invalidate Rust artifacts
- changing Rust build inputs does not invalidate Docker environments

Existing `bcargo` and `brun` sync-contract tests become compatibility tests for
their adapter behavior plus direct tests of the shared bx backend.

## Migration

1. Extend `sugarbin` with `run`, `cargo`, `build`, and `explain` while preserving
   its current no-subcommand resolver interface.
2. Extract the duplicated remote synchronization and execution behavior into
   the bx host backend.
3. Reimplement `bcargo` and `brun` as bx host adapters with byte-compatible
   command behavior. Environment selection remains Sugarbin policy.
4. Introduce the checked-in capability and task contract.
5. Build the minimum pinned Docker capability graph on battleaxe.
6. Add stamped artifact injection and per-executable manifests.
7. Move selected tasks from ambient bx execution to managed Docker execution.
8. Remove superseded provisioning and execution code only after compatibility
   instruments show no remaining callers.

The migration does not require all tasks to adopt Docker at once. Native local
execution, native bx execution, and managed bx Docker execution remain lawful
first-class routes.

## Non-Goals

- Caching test execution or test verdicts
- Provisioning dependencies on the local machine
- Automatically selecting a remote host from a requested platform
- Cross-compiling or emulating unsupported platforms
- Darwin universal artifacts before native executors exist for both slices
- Baking source-specific Sugar binaries into every environment image
