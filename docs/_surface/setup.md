# Setup, Install, Build & Run

Welcome to Sugar. This page maps the real, runnable surface for setting up a development environment, building from source, installing binaries, and running the demonstrations.

## Quick Start

From clone to first demo:

```sh
# 1. Install system dependencies (macOS example; see table below for Ubuntu)
brew install rust python@3.12 node@22 pnpm openssl@3 nlohmann-json

# 2. Build the CLI
cargo install --path implementations/rust/sugar-cli

# 3. Run a demo
cd examples/numpy-vendor && ./run.sh
```

---

## System Dependencies

The build supports **11 host languages** (Rust, Go, C++, TypeScript, C#, Python, Java, Ruby, Zig, Swift, C). All are optional; pick the languages you care about. The only hard requirements are Rust (the canonical CLI implementation) and Python 3.12 (kit RPC).

| Package | macOS (Homebrew) | Ubuntu / Debian | Purpose |
|---------|------------------|-----------------|---------|
| **Rust stable** | `rustup install stable` | `rustup install stable` | Canonical CLI, all Rust kits, conformance harness |
| **Python 3.12** | `brew install python@3.12` | `sudo apt install python3.12 python3-pip` | Python kit, test lifting, pip venv provisioning |
| **Node 22 + pnpm** | `brew install node@22 pnpm` | `nodesource` apt repo + `npm i -g pnpm` | TypeScript kit, emitter plugins |
| **.NET 10 SDK** | `brew install --cask dotnet-sdk` | Microsoft `packages-microsoft-prod` apt repo | C# kit |
| **OpenSSL 3** | `brew install openssl@3` | `sudo apt install libssl-dev` | Crypto (ed25519, blake3 build) |
| **nlohmann-json** | `brew install nlohmann-json` | `sudo apt install nlohmann-json3-dev` | C++ IR compiler |
| **BLAKE3** | vendored at `tools/blake3-vendored` | vendored at `tools/blake3-vendored` | Hashing; Apache-2.0 C source (no system install needed) |
| **z3** (solver) | `brew install z3` | `sudo apt install z3` | SMT solver (default backend; others optional) |
| **Java 21** | via `jenv` or `brew install java21` | `sudo apt install openjdk-21-jdk` | Java kit, Maven |
| **Maven** | `brew install maven` | `sudo apt install maven` | Java multi-module projects |
| **Clang** (C++) | via Xcode Command Line Tools | `sudo apt install clang` | C++ build and link |

**Optional solvers** (added to portfolio if found in PATH; `make ci` exercises all):
- **z3** (SMT-LIB-v2.6) — default
- **cvc5** (SMT-LIB-v2) — `brew install cvc5`
- **Vampire** (SMT-LIB-v2 mode) — prebuilt binary or build from source
- **Maude** (term rewrite) — `brew install maude`
- **Coq** (dependent types) — `brew install coq`
- **Lean 4** (mathlib) — via `elan` (Lean version manager)

---

## Building from Source

### Per-Language Builds

Each implementation is independent; build only what you need:

```sh
# Rust workspace + CLI (always required for canonical verifier)
cargo install --path implementations/rust/sugar-cli

# Python kits (test lifting, hypothesis, pytest witness, source binding)
cd implementations/python && pip install -e .

# TypeScript (Node.js emitters, realize kits)
cd implementations/typescript && pnpm install && pnpm build

# C++ (IR compilers for SMT-LIB, Lean, Coq, Maude)
cd implementations/cpp && make

# C# kits
cd implementations/csharp && dotnet build Sugar.sln --configuration Release

# Java (Maven multi-module)
cd implementations/java && mvn install

# Zig, Ruby, Swift — follow their project `Makefile` or README
```

### Top-Level Orchestration: `make`

The `Makefile` at the repo root is the single source of truth. It coordinates cross-language builds and gates:

```sh
make help              # print available targets
make ci                # conformance + solver dispatch + all language test suites
make build-all         # build all kit binaries (Rust, Python, Go, C++, C#, Java)
make test-all          # test-rust + test-python (the proven provers)
make conformance       # cross-kit conformance harness (catalog CIDs must match pinned)
make clean             # remove all build artifacts
```

**Key targets for development:**

```sh
make build-rust        # cargo build --release (Rust workspace)
make build-python      # pip-install Python kits into /tmp/sugar-python-kit-env
make test-rust         # test Rust workspace; spawns Python kit over RPC
make test-python       # test Python kit (lifting, witness, numpy proofs)
make conformance       # verify every kit's mint output matches pinned CID
make self-attest       # run sugar on itself (self-application)
make coretests-source-audit   # Rust std library assertion audit
```

---

## The `bcargo` Wrapper

Local Mac development is straightforward: `cargo build` works. But **CI and multikit workflows** run on Linux (battleaxe, a remote WSL2 box at 192.168.1.239). The `bcargo` wrapper syncs the repo, runs cargo remotely, and pulls binaries back locally, ensuring **Linux/CI parity** without needing Docker.

**Usage:**

```sh
# Use bcargo like cargo, but remotely:
bin/bcargo build --release
bin/bcargo --sync-bin sugar test --release --manifest-path implementations/rust/Cargo.toml

# For single-solver dev (macOS), use cargo directly:
cargo build --release
```

**Environment variables** (all optional; defaults work for most workflows):

| Variable | Default | Purpose |
|----------|---------|---------|
| `BCARGO_REMOTE_HOST` | `battleaxe` | SSH alias for remote build machine |
| `BCARGO_REMOTE_ROOT` | `/home/tsavo/remote/sugar-bcargo-<hash>` | Scratch dir on remote; per-worktree to avoid collisions |
| `BCARGO_PYTHON_ENV` | `1` | Provision Python kit environment on remote (set `0` to skip) |
| `BCARGO_CLEAN_REMOTE_ROOT` | `never` | `never`, `success`, or `always` cleanup remote dir after build |
| `BCARGO_SSH` | `ssh` | SSH binary override (for testing) |
| `BCARGO_RSYNC` | `rsync` | rsync binary override (for testing) |
| `CI` | (unset) | When set to `1`, forces local cargo instead of bcargo (GitHub Actions sets this) |
| `USE_BCARGO` | `1` | When `0`, use local cargo even outside CI |

**Note:** Stale binaries are a known trap (build on Mac, it works; run in CI, it fails). Always use `bcargo --sync-bin` or CI=1 to ensure parity.

---

## Environment Variables for Build and Runtime

### Python Kit Provisioning

```sh
# Makefile variable to override Python venv location
PYTHON_KIT_VENV=/custom/path make test-rust

# Environment to provision Python env for bcargo (remote builds)
BCARGO_PYTHON_ENV=1 bcargo test --release
```

### Lift and Plugin Dispatch

```sh
# Override Python interpreter for kit dispatch
PYTHON=/usr/bin/python3.11 make test-rust

# Plugin stderr control (suppress verbose plugin output)
SUGAR_PLUGIN_STDERR=null sugar mint ...

# Lean source resolution (Tier 2b receiver type)
SUGAR_RESOLVE_ORACLE=rust-analyzer sugar ...
```

### Solver Configuration

```sh
# Override default solver portfolio (first-wins mode)
# The .sugar/config.toml portfolio field is the canonical location
[solvers]
mode = "first-wins"
portfolio = ["z3", "cvc5", "vampire", "maude", "coq", "lean"]
```

---

## Installation: The `sugar` Binary

The canonical CLI is the Rust binary `sugar`. Install it globally:

```sh
cargo install --path implementations/rust/sugar-cli
sugar --help    # verify installed
sugar verify-protocol  # check protocol catalog CID
```

Alternatively, use the binary from the repo without installing:

```sh
implementations/rust/target/release/sugar mint --help
```

---

## Running the Demos

Every example has a `run.sh` that does the full lift-prove-verify cycle end to end. Start here:

```sh
# Numpy vendor: ship a .proof + witness for 2900 functions (no code changes)
cd examples/numpy-vendor && ./run.sh

# Rust coretests audit: 6377 assertions, 74.8% discharged
cd examples/rust-coretests-report && ./run.sh SUBDIR=iter

# Java Commons Codec: cross-language composition demo
cd examples/java-commons-codec-crc32 && ./run.sh

# Python-only: pytest witness + consumer verification
cd examples/numpy-showcase && ./run.sh
```

**Key discovery:** if a demo has a `run.sh`, it runs end to end today. If not, it's in-progress. The demos are the honest picture of what works.

---

## Conformance Harness

The **conformance gate** is the law: every kit mints its own self-contracts under a foundation key. Every minted package must hash to a CID pinned in the protocol catalog. CI fails if any kit drifts.

```sh
# Local conformance gate (requires ALL kits to be built)
make build-all
make conformance

# Or via top-level CI gate
make ci          # runs: conformance + test-all
```

**What it checks:**
1. Catalog re-derives every spec CID from spec bytes; fails on drift.
2. Every kit mints its self-contracts; pinned CIDs must match.
3. Proof protocol fixtures under `protocol/conformance/proof-protocol/` are verified.
4. Bug Zoo exhibits (`menagerie/bug-zoo/`) verify proof equivalence and link bundles.

Conformance failure is non-negotiable: a red harness blocks PRs.

---

## Python Kit Environment Provisioning

For standalone runs or CI integration, the Python kits are installed into a venv. This happens automatically during `make test-rust`, but you can manage it manually:

```sh
# Create a Python kit environment (used by Rust tests to dispatch Python lifters)
$(PYTHON) -m venv /tmp/sugar-python-kit-env
/tmp/sugar-python-kit-env/bin/pip install --quiet --no-cache-dir \
  blake3 \
  -e implementations/python/sugar-build-witness \
  -e implementations/python/sugar-lift-py-tests \
  -e implementations/python/sugar-lift-python-source \
  -e implementations/python/sugar-lift-py-pytest-witness

# Then use it:
PATH=/tmp/sugar-python-kit-env/bin:$PATH sugar mint --project examples/numpy-vendor
```

**Note:** The Makefile variables `PYTHON_KIT_VENV` and `BCARGO_PYTHON_VENV` control these paths; defaults are `/tmp/sugar-python-kit-env` and `/tmp/sugar-bcargo-python-kit-env`.

---

## Multi-Solver Portfolio

Sugar's verifier runs a first-wins solver portfolio (§7 of `protocol/specs/2026-05-02-multi-solver-protocol-v2.md`). If a solver is missing from PATH, it is skipped gracefully.

**Portfolio order** (from `.sugar/config.toml`):
1. **Maude** (term rewriting, termination + confluence checks)
2. **Z3** (SMT-LIB-v2.6, default, fastest on most problems)
3. **CVC5** (SMT-LIB-v2, alternate)
4. **Vampire** (SMT-LIB-v2, resolution-based)
5. **Coq** (dependent types, via coqc)
6. **Lean 4** (mathlib, via lake)

**Single-solver dev setup** (macOS only Z3):

```sh
brew install z3
cargo build --release
# Verify passes with z3 alone
```

**Full portfolio** (in CI):

```sh
sudo apt-get install z3 cvc5 maude coq
# Vampire + Lean installed separately; see CI workflow
make ci    # exercises all solvers
```

---

## CI and GitHub Actions

Sugar runs on **self-hosted Linux runners** (via GitHub Actions) and macOS (Swift only). The CI workflow is at `.github/workflows/ci.yml`.

**What CI does:**
1. Runs `make ci` (conformance + test-rust + test-python + showcase verifications).
2. Installs full solver portfolio (z3, cvc5, maude, vampire, coq, lean).
3. Caches Rust and Python artifacts.
4. Logs to stdout for debugging.

**Running locally, CI-style** (approximate):

```sh
# Install full solver portfolio
brew install z3 cvc5 maude coq    # macOS
# or
sudo apt-get install z3 cvc5 maude coq     # Ubuntu

# Run the gate
CI=1 make ci    # CI=1 forces local cargo instead of bcargo
```

---

## Troubleshooting

### "sugar binary not found"

```sh
# Install it
cargo install --path implementations/rust/sugar-cli

# Or use it from the build directory
implementations/rust/target/release/sugar --help
```

### "Python kit not found" (Rust tests fail)

```sh
# The Makefile auto-provisions this, but if it's missing:
make build-python
# Or manually:
python3 -m venv /tmp/sugar-python-kit-env
/tmp/sugar-python-kit-env/bin/pip install -e implementations/python/sugar-lift-py-tests
```

### "z3 not found"

```sh
# Install solver
brew install z3    # macOS
# or
sudo apt-get install z3    # Ubuntu

# Verify it's in PATH
which z3
z3 --version
```

### "Conformance failed: CID mismatch"

The conformance harness has caught a real implementation drift. This is not a false alarm:

```sh
# Check which kit failed
make conformance 2>&1 | grep -A5 "mismatch"

# Rebuild that kit and re-run
make build-<lang>   # e.g., build-rust
make conformance
```

### "stale binary" (macOS works, CI fails)

Use `bcargo --sync-bin` or set `CI=1`:

```sh
# Option 1: sync binary back from remote
bcargo --sync-bin sugar build --release

# Option 2: local cargo only (if you have Linux parity)
CI=1 cargo build --release
```

---

## Next Steps

- **First run:** Pick a demo and run its `./run.sh`.
- **Build from source:** See [docs/contributing/build.md](docs/contributing/build.md).
- **Write a lift adapter:** See [docs/contributing/writing-a-lift-adapter/](docs/contributing/writing-a-lift-adapter/).
- **Learn the vocabulary:** See [SHARED-LANGUAGE.md](SHARED-LANGUAGE.md).
- **Read the papers:** Start at [docs/papers/01-whitepaper.md](docs/papers/01-whitepaper.md).

---

## Platform Notes

### macOS

- Rust builds locally; Python, Go, and other tools use Homebrew.
- For CI parity (Linux), use `bcargo` or `CI=1 cargo ...`.
- Swift builds only on macOS; excluded from conformance harness on Linux.

### Linux (battleaxe / CI)

- All builds run natively.
- Python, Go, Rust, C++, Java, C# all supported.
- Swift skipped.
- Full solver portfolio available (z3, cvc5, maude, vampire, coq, lean).

### Windows (WSL2)

- Build in WSL2 as Linux. If using `bcargo`, set `BCARGO_REMOTE_HOST=localhost` and mount the repo.

---

## See Also

- [docs/contributing/build.md](docs/contributing/build.md) — detailed per-language build commands and dependencies
- [docs/contributing/overview.md](docs/contributing/overview.md) — contributor on-ramp (kit authorship, adapter writing, releases)
- [examples/](examples/) — runnable demonstrations across all supported languages
- [protocol/specs/2026-05-02-multi-solver-protocol-v2.md](protocol/specs/2026-05-02-multi-solver-protocol-v2.md) — solver portfolio spec
- [.github/workflows/ci.yml](.github/workflows/ci.yml) — CI configuration (system deps, full test matrix)
