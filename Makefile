# Sugar: top-level orchestrator
#
# Each kit owns its native build tool; this Makefile is glue, not a build
# system. `make ci` runs the acid test: drop sugar into a project and
# prove correctness with zero code changes.
#
# Mainline targets:
#   make help: print this help
#   make ci: check-cargo-entrypoint + the acid test + showcase receipts
#   make test-all: the acid test -- test-rust + test-python
#
# `test-rust` runs the rust workspace (including the crate-pair inheritance
# E2E) and exercises the active kit RPC surfaces; `test-python`
# runs the python lifter/emit kits including the numpy proof. Other per-language suites
# (test-csharp / test-c / ...) exist but are not part of the gate.

.DEFAULT_GOAL := help

PYTHON ?= python3
PYTHON := $(shell command -v '$(PYTHON)' 2>/dev/null || printf '%s\n' '$(PYTHON)')
LOCAL_BIN ?= /tmp/sugar-local-bin
BCARGO ?= $(CURDIR)/bin/bcargo
CARGO_LOCAL ?= cargo
RUSTFLAGS ?= -D warnings
PYTHON_KIT_VENV ?= /tmp/sugar-python-kit-env
PYTHON_KIT_BIN := $(PYTHON_KIT_VENV)/bin
PYTHON_KIT := $(PYTHON_KIT_BIN)/python
PYTHON_KIT_PIP := $(PYTHON_KIT) -m pip
PYTHON_FORMAT_PATHS ?= implementations/python
BCARGO_PYTHON_VENV ?= /tmp/sugar-bcargo-python-kit-env
BCARGO_PYTHON_BIN := $(BCARGO_PYTHON_VENV)/bin
BCARGO_PYTHON := $(BCARGO_PYTHON_BIN)/python
BCARGO_PYTHON_ENV_STAMP := $(BCARGO_PYTHON_VENV)/.sugar-python-kits.stamp
PYTHON_KIT_EDITABLES = \
	-e implementations/python/libsugar-py \
	-e implementations/python/sugar-emit-python-hypothesis \
	-e implementations/python/sugar-emit-python-pytest \
	-e implementations/python/sugar-emit-python-unittest \
	-e implementations/python/sugar-build-witness \
	-e implementations/python/sugar-lift-py-pytest-witness \
	-e implementations/python/sugar-lift-py-tests \
	-e implementations/python/sugar-lift-python-source
ifeq ($(CI),)
ifeq ($(USE_BCARGO),0)
CARGO ?= $(CARGO_LOCAL)
else
CARGO ?= $(BCARGO)
endif
else
CARGO ?= $(CARGO_LOCAL)
endif
BCARGO_ACTIVE := $(filter bcargo,$(notdir $(firstword $(CARGO))))
CARGO_SYNC_BINS = $(if $(BCARGO_ACTIVE),$(CARGO) $(foreach bin,$(1),--sync-bin $(bin)),$(CARGO))
export PATH := $(LOCAL_BIN):$(PATH)
export RUSTFLAGS

.PHONY: help
help:
	@echo "Sugar: top-level orchestrator"
	@echo ""
	@echo "Mainline:"
	@echo "  make ci             check-cargo-entrypoint + the acid test + showcase receipts"
	@echo "  make test-all       the acid test: test-rust + test-python"
	@echo "  make test-showcases run the checked-in end-to-end showcase receipts"
	@echo "  make test-real-python-kit-lsp  real pandas kit through LSP (battleaxe; skip=red)"
	@echo "  make test-3809-dod-scoreboard  consolidated #3809 DoD (warm+LSP+golden; skip=red)"
	@echo "  make examples-gate  run public example smoke scripts against the ratchet fixture"
	@echo ""
	@echo "Per-language build:"
	@echo "  make build-rust     cargo build --release (workspace)"
	@echo "  make build-python   pip-install Python realize kits and shim packages"
	@echo "  make build-<lang>   cpp / csharp / c"
	@echo ""
	@echo "Per-language test:"
	@echo "  make test-rust  test-python   (the proven provers)"
	@echo "  make numpy-wall                build and ratchet-check the NumPy lift wall"
	@echo "  make pandas-wall               build and ratchet-check the pandas lift wall"
	@echo "  make test-python-format       Black check for implementations/python"
	@echo "  make test-<lang>              csharp / php / c"
	@echo "  make test-compiler-warning-de compiler-warning delta-epsilon instrument"
	@echo ""
	@echo "Self-lift experiments:"
	@echo "  make self-lift-canonicalizer  run sugar-lift against the canonicalizer crate"
	@echo ""
	@echo "Maintenance:"
	@echo "  make setup-git-hooks wire committed Git hooks into this clone"
	@echo "  make test-git-hooks  test committed Git hooks"
	@echo "  make clean          remove build artifacts"

# --- Per-language builds -----------------------------------------------------

# Build every kit's binaries. Useful before `make conformance` or before
# running `sugar lift`/`sugar mint` (which subprocess kit lifters at lift
# time). Each kit's build target is independent; failures stay isolated.
.PHONY: build-all
build-all: build-rust build-python

.PHONY: build-rust
build-rust:
	$(call CARGO_SYNC_BINS,sugar sugar-lift) build --release --manifest-path implementations/rust/Cargo.toml
	bin/sugarbin --profile release >/dev/null

.PHONY: build-rust-cli
build-rust-cli:
	bin/sugarbin --profile release >/dev/null

.PHONY: build-csharp
build-csharp:
	dotnet build implementations/csharp/Sugar.sln --configuration Release --nologo

.PHONY: build-c
build-c:
	$(MAKE) -C implementations/c/sugar-ir all
	$(MAKE) -C implementations/c/sugar-lift all
	$(MAKE) -C implementations/c/sugar-lift-core all
	$(MAKE) -C implementations/c/sugar-lift-c-sparse all
	$(MAKE) -C implementations/c/sugar-lift-c-kernel-doc all
	$(MAKE) -C implementations/c/sugar-lift-c-assertions all
	$(MAKE) -C implementations/c/sugar-realize-c-core all
	$(MAKE) -C implementations/c/sugar-lsp-c all

.PHONY: build-python
build-python:
	$(PYTHON) -m venv $(PYTHON_KIT_VENV)
	$(PYTHON_KIT_PIP) install --quiet --upgrade pip
	# The rust integration suite spawns the python lifter over RPC
	# (python3 -m sugar_lift_py_tests...). Install the lift packages into the
	# same interpreter so those cross-language tests find it.
	$(PYTHON_KIT_PIP) install --quiet --no-cache-dir \
		blake3 \
		pandas \
		-e implementations/python/sugar-build-witness \
		-e implementations/python/sugar-lift-py-tests \
		-e implementations/python/sugar-lift-python-source \
		-e implementations/python/sugar-lift-py-pytest-witness

.PHONY: bcargo-python-kit-env
bcargo-python-kit-env: $(BCARGO_PYTHON_ENV_STAMP)

$(BCARGO_PYTHON_ENV_STAMP): Makefile $(wildcard implementations/python/*/pyproject.toml)
	$(PYTHON) -m venv $(BCARGO_PYTHON_VENV)
	$(BCARGO_PYTHON) -m pip install --quiet --upgrade pip
	# pandas is required so the real-kit LSP gate (and witness pandas corpus)
	# can RUN on battleaxe; a skip there is a red, not a green.
	$(BCARGO_PYTHON) -m pip install --quiet --no-cache-dir pytest pandas $(PYTHON_KIT_EDITABLES)
	mkdir -p $(dir $(BCARGO_PYTHON_ENV_STAMP))
	touch $(BCARGO_PYTHON_ENV_STAMP)

# --- Mint targets ------------------------------------------------------------

# Each mint target builds its peer + dispatches via a `--kit=<alias>` entry
# declared in `.sugar/config.toml`. The CLI does not carry a built-in kit
# list; aliases resolve to project roots and lift manifests from config.
# The CLI drives the kit's lift-protocol RPC, collects contracts, signs the
# attestation, and writes it to $(SELF_CONTRACTS_ATTEST_DIR)/<lang>.json.
# All 11 kits use the same uniform pipeline; no language-native mint binaries.
#
# For kits whose lifter binary is not yet installed, mint produces an
# empty-set attestation (contractSetCid = BLAKE3-512 of JCS("[]")).
# The attestation is still verified; a missing lifter surfaces as a known gap.

.PHONY: check-cargo-entrypoint
check-cargo-entrypoint:
	tools/check-cargo-entrypoint.sh

.PHONY: check-lift-refusal-vocabulary
check-lift-refusal-vocabulary:
	tools/check-lift-refusal-vocabulary.py
	tools/check-lift-refusal-vocabulary.py --self-test

.PHONY: numpy-wall
numpy-wall:
	python3 tools/numpy_wall.py

.PHONY: pandas-wall
pandas-wall:
	python3 tools/pandas_wall.py

.PHONY: setup-git-hooks
setup-git-hooks:
	@test -x hooks/pre-commit || (echo "missing executable hook: hooks/pre-commit" >&2; exit 1)
	git config core.hooksPath hooks
	@echo "core.hooksPath=hooks"

.PHONY: test-git-hooks
test-git-hooks:
	hooks/tests/pre-commit-format.sh

.PHONY: test-compiler-warning-de
test-compiler-warning-de:
	CARGO="$(CARGO)" tests/compiler_warning_delta_epsilon.sh --epsilon "$${SUGAR_WARNING_DE_EPSILON:-compiler_warnings=0}"

.PHONY: test-rust
# The rust integration tests register per-language carriers via
# `register_with_platform_semantics`, which spawns the target kit binary
# over JSON-RPC (PEP 1.7.0) to fetch the PlatformSemanticsDeclaration.
test-rust: build-python
	@failed=""; \
	PATH="$(PYTHON_KIT_BIN):$$PATH" \
	  $(CARGO) test --no-fail-fast --release --manifest-path implementations/rust/Cargo.toml \
	  || failed="$$failed implementations/rust"; \
	if [ -n "$$failed" ]; then echo "test-rust FAIL:$$failed"; exit 1; fi

.PHONY: test-csharp
test-csharp: build-csharp
	dotnet test implementations/csharp/Sugar.sln --nologo --verbosity quiet

.PHONY: test-c
test-c: build-c
	@failed=""; \
	$(MAKE) -C implementations/c/sugar-ir test || failed="$$failed sugar-ir"; \
	$(MAKE) -C implementations/c/sugar-lift test || failed="$$failed sugar-lift"; \
	$(MAKE) -C implementations/c/sugar-lift-core test || failed="$$failed sugar-lift-core"; \
	$(MAKE) -C implementations/c/sugar-lift-c-sparse test || failed="$$failed sugar-lift-c-sparse"; \
	$(MAKE) -C implementations/c/sugar-lift-c-kernel-doc test || failed="$$failed sugar-lift-c-kernel-doc"; \
	$(MAKE) -C implementations/c/sugar-lift-c-assertions test || failed="$$failed sugar-lift-c-assertions"; \
	$(MAKE) -C implementations/c/sugar-realize-c-core test || failed="$$failed sugar-realize-c-core"; \
	$(MAKE) -C implementations/c/sugar-lift-composition test || failed="$$failed sugar-lift-composition"; \
	$(MAKE) -C implementations/c/sugar-lsp-c test || failed="$$failed sugar-lsp-c"; \
	if [ -n "$$failed" ]; then echo "test-c FAIL:$$failed"; exit 1; fi

.PHONY: test-python
test-python: build-python
	@failed=""; \
	sugar_bin="$$(bin/sugarbin --profile release)" || exit $$?; \
	(cd implementations/python/sugar-lift-py-tests && \
		python3 -m venv .venv && \
		. .venv/bin/activate && \
		python -m pip install --quiet -e . pytest numpy pandas scikit-learn pyright==1.1.411 && \
		SUGAR_BIN="$$sugar_bin" pytest) || failed="$$failed sugar-lift-py-tests"; \
	(cd implementations/python/sugar-emit-python-pytest && \
		python3 -m venv .venv && \
		. .venv/bin/activate && \
		python -m pip install --quiet -e . pytest && \
		pytest) || failed="$$failed sugar-emit-python-pytest"; \
	(cd implementations/python/sugar-lift-python-source && \
		python3 -m venv .venv && \
		. .venv/bin/activate && \
		python -m pip install --quiet -e ../sugar-lift-py-tests -e . pytest blake3 numpy pandas && \
		SUGAR_BIN="$$sugar_bin" pytest) || failed="$$failed sugar-lift-python-source"; \
	(cd implementations/python/sugar-lift-py-pytest-witness && \
		python3 -m venv .venv && \
		. .venv/bin/activate && \
		python -m pip install --quiet -e ../sugar-lift-py-tests -e . pytest pynacl blake3 cbor2 && \
		SUGAR_BIN="$$sugar_bin" pytest) || failed="$$failed sugar-lift-py-pytest-witness"; \
	(cd implementations/python/sugar-build-witness && \
		python3 -m venv .venv && \
		. .venv/bin/activate && \
		python -m pip install --quiet -e ../sugar-lift-py-tests -e . pytest pynacl blake3 cbor2 && \
		SUGAR_BIN="$$sugar_bin" pytest) || failed="$$failed sugar-build-witness"; \
	if [ -n "$$failed" ]; then echo "test-python FAIL:$$failed"; exit 1; fi

.PHONY: test-python-format
test-python-format:
	$(PYTHON) -m venv $(PYTHON_KIT_VENV)
	$(PYTHON_KIT_PIP) install --quiet --upgrade pip
	$(PYTHON_KIT_PIP) install --quiet --no-cache-dir -e implementations/python/sugar-lift-py-tests[test]
	$(PYTHON_KIT) -m black --check $(PYTHON_FORMAT_PATHS)

.PHONY: test-php
test-php:
	cd implementations/php && composer install && composer test

# The acid test: the two suites that actually prove real code with zero
# changes. `test-rust` runs the rust workspace (including the crate-pair
# inheritance E2E) and exercises the python realize kits over RPC;
# `test-python` runs the python kit including the numpy proof. NON-FAIL-FAST:
# both run regardless of prior failure; results summarize at the end.
.PHONY: check-no-concept-name
check-no-concept-name:
	@if git grep -n -E 'concept_name|conceptName' -- implementations/; then \
	  echo "check-no-concept-name FAIL: concept_name/conceptName must not appear under implementations/"; \
	  exit 1; \
	fi

.PHONY: test-all
test-all: check-no-concept-name
	@failed=""; \
	for s in test-rust test-python; do \
	  echo ""; \
	  echo "==== $$s ===="; \
	  $(MAKE) $$s || failed="$$failed $$s"; \
	done; \
	echo ""; \
	if [ -n "$$failed" ]; then \
	  echo "==== test-all FAIL:$$failed ===="; \
	  exit 1; \
	fi; \
	echo "==== test-all: PASS ===="

SHOWCASE_RUNS = \
	examples/numpy-showcase/run.sh \
	examples/pandas-showcase/run.sh \
	examples/sklearn-showcase/run.sh \
	examples/serde-json-showcase/run.sh \
	examples/regex-showcase/run.sh \
	examples/build-witness-showcase/run.sh \
	examples/rust-witness-showcase/run.sh \
	examples/rust-test-assertion-consistency/run.sh \
	examples/rust-regex-membership/run.sh \
	examples/std-core-showcase/run.sh \
	examples/std-core-bodyguard-precondition/run.sh \
	examples/tokio-effect-consistency/run.sh \
	examples/tokio-await-implication-edge/run.sh \
	examples/tokio-channel-implication-edge/run.sh \
	examples/tokio-mutex-implication-edge/run.sh \
	examples/polars-showcase/run.sh \
	examples/numpy-attribute-safety-showcase/run.sh \
	examples/numpy-vendor/run.sh \
	examples/std-core-string-predicates/run.sh \
	examples/python-bodyguard-precondition/run.sh \
	examples/python-guard-shapes/run.sh \
	examples/python-urlsafe-seam/run.sh \
	examples/python-literal-base64/run.sh \
	examples/python-literal-base20/run.sh \
	examples/python-base64-federation/run.sh \
	examples/itsdangerous-token-padding/run-logo-receipt.sh \
	examples/stdlib-base64-padding/run-logo-receipt.sh \
	examples/hashlib-sha256-hexdigest/run-logo-receipt.sh \
	examples/stdlib-base32-padding/run-logo-receipt.sh \
	examples/itsdangerous-token-padding/run.sh \
	examples/forall-vampire-showcase/run.sh \
	examples/url-showcase/run.sh \
	examples/semver-showcase/run.sh \
	examples/base64-showcase/run.sh \
	examples/uuid-showcase/run.sh \
	examples/itertools-showcase/run.sh \
	examples/num-integer-showcase/run.sh \
	examples/bitflags-showcase/run.sh \
	examples/forall-loop-showcase/run.sh \
	examples/java-assertion-consistency/run.sh \
	examples/java-forall-loop/run.sh \
	examples/java-testng-consistency/run.sh \
	examples/java-codec-universe/run.sh \
	examples/java-urlsafe-seam/run.sh \
	examples/java-b64-strong/run.sh \
	examples/java-b64-tails/run.sh \
	examples/java-abs-universe/run.sh \
	examples/java-bound-federation/run.sh \
	examples/java-abs-bound/run.sh \
	examples/java-callbind-consistency/run.sh \
	examples/java-instance-universe/run.sh \
	examples/java-voltron/run.sh \
	examples/java-abs-flagship/run.sh \
	examples/java-panama-bridge/run.sh \
	examples/java-abs-model/run.sh \
	examples/java-mt-reference/run.sh \
	examples/java-crc32-universe/run.sh \
	examples/java-pattern-regex/run.sh

EXAMPLES_GATE_EXPECTATIONS ?= docs/audits/examples_gate_expectations.json
EXAMPLES_GATE_EXTENDED_EXPECTATIONS ?= docs/audits/examples_gate_extended_expectations.json
EXAMPLES_GATE_SUMMARY ?= .out/examples-gate-summary.json
EXAMPLES_GATE_EXTENDED_SUMMARY ?= .out/examples-gate-extended-summary.json
EXAMPLES_GATE_LOG_DIR ?= .out/examples-gate-logs
EXAMPLES_GATE_EXTENDED_LOG_DIR ?= .out/examples-gate-extended-logs
EXAMPLES_GATE_TIMEOUT_SECONDS ?= 3600
EXAMPLES_GATE_EXTENDED_TIMEOUT_SECONDS ?= 3600
EXAMPLES_GATE_NICE ?= 10

.PHONY: test-examples-gate-tooth
test-examples-gate-tooth:
	$(PYTHON) tests/examples_gate_test.py

.PHONY: examples-gate
examples-gate:
	$(PYTHON) tools/examples_gate.py \
	  --suite smoke \
	  --expectations $(EXAMPLES_GATE_EXPECTATIONS) \
	  --summary-json $(EXAMPLES_GATE_SUMMARY) \
	  --log-dir $(EXAMPLES_GATE_LOG_DIR) \
	  --timeout-seconds $(EXAMPLES_GATE_TIMEOUT_SECONDS) \
	  --nice $(EXAMPLES_GATE_NICE)

.PHONY: examples-gate-extended
examples-gate-extended:
	$(PYTHON) tools/examples_gate.py \
	  --suite extended \
	  --expectations $(EXAMPLES_GATE_EXTENDED_EXPECTATIONS) \
	  --summary-json $(EXAMPLES_GATE_EXTENDED_SUMMARY) \
	  --log-dir $(EXAMPLES_GATE_EXTENDED_LOG_DIR) \
	  --timeout-seconds $(EXAMPLES_GATE_EXTENDED_TIMEOUT_SECONDS) \
	  --nice $(EXAMPLES_GATE_NICE)

.PHONY: test-showcases
test-showcases:
	@set -e; \
	if [ "$${SHOWCASES_ON_REMOTE:-0}" != "1" ] && [ "$$(uname -s)" != "Linux" ] && [ "$${USE_BCARGO:-1}" != "0" ]; then \
	  echo "==== test-showcases on battleaxe via bcargo ===="; \
	  $(BCARGO) build --manifest-path implementations/rust/Cargo.toml \
	    -p sugar-walk --bin sugar-walk-rpc \
	    -p sugar-lift-rust-cargo-test-witness --bin witness_rpc \
	    -p sugar-lift-rust-cargo-test-witness --bin discharge_cli \
	    -p sugar-lift-rust-tests --bin rust_test_assertions_rpc >/dev/null || exit $$?; \
	  remote_host="$${BCARGO_REMOTE_HOST:-battleaxe}"; \
	  remote_tag="$$(printf '%s' "$$(pwd -P)" | shasum 2>/dev/null | cut -c1-12)"; \
	  remote_tag="$${remote_tag:-default}"; \
	  remote_root="$${BCARGO_REMOTE_ROOT:-/home/tsavo/remote/sugar-bcargo-$$remote_tag}"; \
	  remote_repo="$$remote_root/sugar"; \
	  remote_cmd="cd $$(printf '%q' "$$remote_repo") && SHOWCASES_ON_REMOTE=1 USE_BCARGO=0 POLARS_SHOWCASE_ON_REMOTE=1 POLARS_SHOWCASE_SKIP_LOCAL_BUILD=1 NUMPY_ATTR_SHOWCASE_ON_REMOTE=1 NUMPY_ATTR_SHOWCASE_SKIP_LOCAL_BUILD=1 make test-showcases"; \
	  ssh -o BatchMode=yes "$$remote_host" "bash -lc $$(printf '%q' "$$remote_cmd")"; \
	  exit $$?; \
	fi; \
	bin/sugarbin --profile release >/dev/null || exit $$?; \
	failed=""; \
	for s in $(SHOWCASE_RUNS); do \
	  echo ""; \
	  echo "==== $$s ===="; \
	  "$$s" || failed="$$failed $$s"; \
	done; \
	echo ""; \
	if [ -n "$$failed" ]; then \
	  echo "==== test-showcases FAIL:$$failed ===="; \
	  exit 1; \
	fi; \
	echo "==== test-showcases: PASS ===="

# --- CI alias ----------------------------------------------------------------

.PHONY: self-attest
# Dogfood the coarse supply-chain pin on sugar's OWN artifacts, driven by a
# config/manifest (`sugar-release.toml`) -- the declared set of what sugar
# ships -- NOT a hardcoded per-artifact flag. The artifact rail
# (`verify --artifact`, binaryCid match) is sound + fail-closed, but a gate
# nothing arms is a silence read wrong: the manifest-driven producer
# (`package release`) mints the binaryCid receipts or the perimeter is inert.
# Attest from the manifest, then re-verify against the pinned receipts --
# producer -> gate, on the very tool doing the gating.
self-attest: build-rust
	@set -e; \
	sugar_bin="$$(bin/sugarbin --profile release)"; \
	tmp=$$(mktemp -d); \
	"$$sugar_bin" package release --manifest sugar-release.toml --receipts $$tmp; \
	"$$sugar_bin" package release --manifest sugar-release.toml --receipts $$tmp --verify-only; \
	echo "self-attest: PASS (manifest artifacts pinned + verified)"; \
	rm -rf $$tmp

# Pin-and-assert gate over the rust stdlib coretests accounting sweep. Runs the
# HERMETIC sweep (no --dissolve -> deterministic: no nightly harness compiles, no
# per-file dissolution cap) and asserts the result EXACTLY equals the pinned
# snapshot (implementations/rust/coretests-invariants.json). CI goes red when a
# commit fails to move the numbers as it claimed (a drain that didn't drain, a
# regression, a silent drop, or a corpus change). Corpus = rust $(CORETESTS_RUST_VER)
# coretests via rust-src, pinned independent of the runner's default stable so the
# assertion-multiset CID stays stable. Self-provisions the toolchain (idempotent).
CORETESTS_RUST_VER ?= 1.96.0
CORETESTS_SOURCE_AUDIT_CORPUS ?= examples/rust-coretests-report/corpus

.PHONY: coretests-source-audit
coretests-source-audit:
	@set -e; \
	if [ "$${CORETESTS_SOURCE_AUDIT_ON_REMOTE:-0}" != "1" ] && [ "$$(uname -s)" != "Linux" ] && [ "$${USE_BCARGO:-1}" != "0" ]; then \
	  echo "==== coretests-source-audit on battleaxe via bcargo ===="; \
	  $(BCARGO) build --manifest-path implementations/rust/Cargo.toml \
	    -p sugar-lift-rust-tests --bin rust_test_assertions_rpc >/dev/null || exit $$?; \
	  remote_host="$${BCARGO_REMOTE_HOST:-battleaxe}"; \
	  remote_tag="$$(printf '%s' "$$(pwd -P)" | shasum 2>/dev/null | cut -c1-12)"; \
	  remote_tag="$${remote_tag:-default}"; \
	  remote_root="$${BCARGO_REMOTE_ROOT:-/home/tsavo/remote/sugar-bcargo-$$remote_tag}"; \
	  remote_repo="$$remote_root/sugar"; \
	  remote_cmd="cd $$(printf '%q' "$$remote_repo") && CORETESTS_SOURCE_AUDIT_ON_REMOTE=1 USE_BCARGO=0 Z3=$${Z3:-/usr/bin/z3} make coretests-source-audit"; \
	  ssh -o BatchMode=yes "$$remote_host" "bash -lc $$(printf '%q' "$$remote_cmd")"; \
	  exit $$?; \
	fi; \
	sugar_bin="$$(bin/sugarbin --profile release)" || exit $$?; \
	$(CARGO_LOCAL) build --manifest-path implementations/rust/Cargo.toml --release \
	  -p sugar-lift-rust-tests --bin rust_test_assertions_rpc >/dev/null || exit $$?; \
	bin_dir="$$(pwd -P)/implementations/rust/target/release"; \
	corpus="$(CORETESTS_SOURCE_AUDIT_CORPUS)"; \
	manifest_dir="$$corpus/.sugar/lift/rust-test-assertions"; \
	sed "s|@BIN_DIR@|$$bin_dir|g" "$$manifest_dir/manifest.toml.in" > "$$manifest_dir/manifest.toml"; \
	echo "==== coretests-source-audit: panic-armed source totality ===="; \
	cd "$$corpus"; \
	RUST_LOG=error NO_COLOR=1 CLICOLOR=0 TERM=dumb "$$sugar_bin" lift --report --report-summary

.PHONY: coretests-invariants
coretests-invariants:
	@set -e; \
	rustup toolchain install $(CORETESTS_RUST_VER) --component rust-src --profile minimal 2>/dev/null || true; \
	$(CARGO_LOCAL) build --manifest-path implementations/rust/Cargo.toml --release -p sugar-lift-rust-tests --bin coretests_sweep; \
	CORPUS="$$(rustc +$(CORETESTS_RUST_VER) --print sysroot)/lib/rustlib/src/rust/library/coretests/tests"; \
	implementations/rust/target/release/coretests_sweep "$$CORPUS" --rustc-cfg > /tmp/coretests-hermetic.out; \
	python3 scripts/check-coretests-invariants.py /tmp/coretests-hermetic.out implementations/rust/coretests-invariants.json

# Real python/pandas kit through sugar-lsp --in-process (PyCon demo path).
# Same battleaxe family as the witness corpus (bcargo/brun + remote kit env).
# Implementation lives in scripts/test-real-python-kit-lsp.sh so skip=red and
# the RAN receipt assertion stay shell-testable without Makefile quoting pain.
# Standalone leg; the consolidated #3809 scoreboard also runs this path.
.PHONY: test-real-python-kit-lsp
test-real-python-kit-lsp:
	@bash scripts/test-real-python-kit-lsp.sh

# Consolidated #3809 DoD scoreboard (ONE gated receipt):
#   warm_solve FS=0 + byte-identical + timing (#3923)
#   real-kit LSP RAN / lie→UNSAT / truth→clear (#3934/#3936)
#   golden NDJSON conversation byte-identical (#3938)
# Extends existing targets; does not reimplement their assertions.
# Wired into `make ci` in place of the narrower test-real-python-kit-lsp alone
# so the full acceptance story is one recomputable gate (LSP still covered).
.PHONY: test-3809-dod-scoreboard
test-3809-dod-scoreboard:
	@bash scripts/test-3809-dod-scoreboard.sh

.PHONY: ci
ci: check-cargo-entrypoint check-lift-refusal-vocabulary test-python-format test-all test-showcases test-3809-dod-scoreboard self-attest coretests-source-audit coretests-invariants
	@echo ""
	@echo "==== ci: PASS ===="

# --- Self-lift experiments ---------------------------------------------------
#
# `make self-lift-canonicalizer` runs `sugar-lift` against the
# canonicalizer crate as-is and writes the resulting `.proof` plus a
# human-readable lift-report under `.sugar/self-lifts/canonicalizer/`.
# This is NOT part of the conformance gate; it's a separate experiment
# that surfaces what the auto-lifter can/can't reach on real first-party
# source. Idempotent: re-running with the same source produces the same
# CID (default seed [0x42; 32]). Drift means either the source moved or
# the lifter changed; in either case, inspect lift-report.txt.

SUGAR_LIFT := implementations/rust/target/release/sugar-lift
SELF_LIFT_DIR := .sugar/self-lifts/canonicalizer

.PHONY: self-lift-canonicalizer
self-lift-canonicalizer: build-rust
	@echo ">> self-lifting sugar-canonicalizer"
	@mkdir -p $(SELF_LIFT_DIR)
	@rm -f $(SELF_LIFT_DIR)/blake3-512_*.proof
	@out=$$($(SUGAR_LIFT) \
		--workspace implementations/rust/sugar-canonicalizer \
		--target-dir $(SELF_LIFT_DIR) --quiet); \
	  echo "  cid: $$out"; \
	  test -f $(SELF_LIFT_DIR)/$$out.proof || \
	    (echo "FAIL: lifter did not write $(SELF_LIFT_DIR)/$$out.proof" && exit 1); \
	  echo "  proof: $(SELF_LIFT_DIR)/$$out.proof"
	@echo "  report: $(SELF_LIFT_DIR)/lift-report.txt"

# --- Cleanup -----------------------------------------------------------------

.PHONY: clean
clean:
	$(CARGO_LOCAL) clean --manifest-path implementations/rust/Cargo.toml
	rm -rf implementations/cpp/target
	rm -rf implementations/csharp/Sugar.*/bin implementations/csharp/Sugar.*/obj
	rm -rf node_modules
	rm -f implementations/*/blake3-512_*.proof
	rm -f blake3-512_*.proof
