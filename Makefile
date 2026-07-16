# Sugar: top-level orchestrator
#
# Each kit owns its native build tool; this Makefile is glue, not a build
# system. `make ci` runs the acid test: drop sugar into a project and
# prove correctness with zero code changes.
#
# Mainline targets:
#   make help: print this help
#   make ci: the acid test + showcase receipts
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
	@echo "  make ci             the acid test + showcase receipts"
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
	@echo "  make assertion-lift-frontier   run the explicit recursive assertion_lift frontier ratchet"
	@echo "  make check-resident-ownership  Lane B: unbounded process-lifetime cache census (R→0)"
	@echo "  make check-showcase-kit-preflight  Lane A: showcase kit import contracts (A1→0)"
	@echo "  make check-lift-manifest-pythonpath  Lane A: lift_rpc PYTHONPATH + bind_rpc --rpc census"
	@echo "  make wall-progress            Lane B: score partial wall run → progress.json"
	@echo "  make showcase-verdict-scoreboard  Lane A: classify showcase log → A2 residue"
	@echo "  make showcase-bulk-refuse-class   Lane A: prove/durable vacuity parity instrument"
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
	rm -rf $(PYTHON_KIT_VENV)
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

# Lane B instrument (explicit): unbounded process-lifetime cache decorators.
# Stays red while R>0. Do not re-enter default `make ci` until R=0.
# See docs/analysis/ci-whack-a-mole-course-2026-07-15.md.
.PHONY: check-resident-ownership
check-resident-ownership:
	$(PYTHON) tools/resident_ownership_census.py --self-test
	$(PYTHON) tools/resident_ownership_census.py

# Lane A instrument: showcase kit imports under declared contracts.
# Prerequisite of test-showcases so missing kits fail with a named A1, not a
# refuse-cascade three minutes later.
.PHONY: check-showcase-kit-preflight
check-showcase-kit-preflight:
	$(PYTHON) tools/showcase_kit_preflight.py --self-test
	$(PYTHON) tools/showcase_kit_preflight.py

# Lane A instrument: showcase lift manifests must put sugar-lift-python-source
# on PYTHONPATH for sugar_lift_py_tests launches, and bind_rpc must pass --rpc.
.PHONY: check-lift-manifest-pythonpath
check-lift-manifest-pythonpath:
	$(PYTHON) tools/check_lift_manifest_pythonpath.py --self-test
	$(PYTHON) tools/check_lift_manifest_pythonpath.py

# Lane B instrument 3: partial wall progress receipt (not a product gate).
# Score transport.jsonl + wall.txt → progress.json. Incomplete is measured.
# Self-test always runs; scoring requires a wall artifact (set WALL_DIR/LOGS_DIR
# or run after make pandas-wall / download a CI artifact).
.PHONY: wall-progress
wall-progress:
	$(PYTHON) tools/wall_progress_scoreboard.py --self-test
	@wall_dir="$${WALL_DIR:-.sugar/$${WALL:-pandas}-wall}"; \
	logs_dir="$${LOGS_DIR:-.sugar/$${WALL:-pandas}-wall-logs}"; \
	if [ -d "$$wall_dir" ] || [ -d "$$logs_dir" ]; then \
	  $(PYTHON) tools/wall_progress_scoreboard.py \
	    --wall "$${WALL:-pandas}" \
	    --wall-dir "$$wall_dir" \
	    --logs-dir "$$logs_dir" \
	    --output "$${WALL_PROGRESS_OUT:-$$wall_dir/progress.json}" \
	    $${WALL_EXIT:+--exit-code $$WALL_EXIT}; \
	else \
	  echo "wall-progress: self-test only (no $$wall_dir / $$logs_dir; set WALL_DIR/LOGS_DIR to score a run)"; \
	fi

# Lane A instrument A2: classify test-showcases / CI log residue.
# Requires SHOWCASE_LOG=path (or --from-log). Self-test always runs.
.PHONY: showcase-verdict-scoreboard
showcase-verdict-scoreboard:
	$(PYTHON) tools/showcase_verdict_scoreboard.py --self-test
	$(PYTHON) tools/showcase_bulk_refuse_class.py --self-test
	@if [ -n "$${SHOWCASE_LOG:-}" ]; then \
	  $(PYTHON) tools/showcase_verdict_scoreboard.py \
	    --from-log "$$SHOWCASE_LOG" \
	    $${SHOWCASE_VERDICT_OUT:+--output $$SHOWCASE_VERDICT_OUT}; \
	elif [ -n "$${SHOWCASE_LOG_DIR:-}" ]; then \
	  $(PYTHON) tools/showcase_verdict_scoreboard.py \
	    --from-dir "$$SHOWCASE_LOG_DIR" \
	    $${SHOWCASE_VERDICT_OUT:+--output $$SHOWCASE_VERDICT_OUT}; \
	else \
	  echo "showcase-verdict-scoreboard: self-test only (set SHOWCASE_LOG=path to score a run)"; \
	fi

# Lane A: bulk-crate refuse class (prove/durable vacuity parity).
.PHONY: showcase-bulk-refuse-class
showcase-bulk-refuse-class:
	$(PYTHON) tools/showcase_bulk_refuse_class.py --self-test
	@if [ -n "$${SHOWCASE_RECEIPT:-}" ]; then \
	  $(PYTHON) tools/showcase_bulk_refuse_class.py --from-receipt "$$SHOWCASE_RECEIPT"; \
	elif [ -n "$${SHOWCASE_RECEIPT_DIR:-}" ]; then \
	  $(PYTHON) tools/showcase_bulk_refuse_class.py --from-dir "$$SHOWCASE_RECEIPT_DIR"; \
	fi

.PHONY: numpy-wall
numpy-wall:
	python3 tools/numpy_wall.py

.PHONY: pandas-wall
pandas-wall:
	python3 tools/pandas_wall.py

# This frontier intentionally launches the known-red assertion_lift target in a
# nested cargo process. Keep it explicit: ordinary test-rust/make ci must not pay
# for the serial recursive census. Select the multiset ratchet exactly so the
# report-only duplicate and stable-zero target remain separate instruments.
.PHONY: assertion-lift-frontier
assertion-lift-frontier: build-python
	PATH="$(PYTHON_KIT_BIN):$$PATH" $(CARGO) test --release \
		--manifest-path implementations/rust/Cargo.toml \
		-p sugar-lift-rust-tests \
		--test assertion_lift_frontier \
		assertion_lift_frontier_matches_expected_multiset -- \
		--ignored --exact --nocapture

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
	  $(CARGO) build --workspace --bins --manifest-path implementations/rust/Cargo.toml \
	  || failed="$$failed implementations/rust-build"; \
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
		rm -rf .venv && \
		python3 -m venv .venv && \
		. .venv/bin/activate && \
		python -m pip install --quiet -e ../sugar-lift-python-source -e '.[test]' numpy pandas scikit-learn && \
		SUGAR_BIN="$$sugar_bin" pytest) || failed="$$failed sugar-lift-py-tests"; \
	(cd implementations/python/sugar-emit-python-pytest && \
		rm -rf .venv && \
		python3 -m venv .venv && \
		. .venv/bin/activate && \
		python -m pip install --quiet -e . pytest && \
		pytest) || failed="$$failed sugar-emit-python-pytest"; \
	(cd implementations/python/sugar-lift-python-source && \
		rm -rf .venv && \
		python3 -m venv .venv && \
		. .venv/bin/activate && \
		python -m pip install --quiet -e ../sugar-lift-py-tests -e . pytest blake3 numpy pandas && \
		SUGAR_BIN="$$sugar_bin" pytest) || failed="$$failed sugar-lift-python-source"; \
	(cd implementations/python/sugar-lift-py-pytest-witness && \
		rm -rf .venv && \
		python3 -m venv .venv && \
		. .venv/bin/activate && \
		python -m pip install --quiet -e ../sugar-lift-py-tests -e . pytest pynacl blake3 cbor2 && \
		SUGAR_BIN="$$sugar_bin" pytest) || failed="$$failed sugar-lift-py-pytest-witness"; \
	(cd implementations/python/sugar-build-witness && \
		rm -rf .venv && \
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
	examples/zlib-crc32/run-logo-receipt.sh \
	examples/binascii-hexlify/run-logo-receipt.sh \
	examples/hmac-compare-digest/run-logo-receipt.sh \
	examples/stdlib-base32-padding/run-logo-receipt.sh \
	examples/struct-calcsize/run-logo-receipt.sh \
	examples/hashlib-md5-digest-size/run-logo-receipt.sh \
	examples/uuid-bytes-length/run-logo-receipt.sh \
	examples/hashlib-sha256-digest-length/run-logo-receipt.sh \
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
test-showcases: check-showcase-kit-preflight check-lift-manifest-pythonpath
	@set -e; \
	shard_count="$${SHOWCASE_SHARD_COUNT:-1}"; \
	shard_index="$${SHOWCASE_SHARD_INDEX:-0}"; \
	case "$$shard_count:$$shard_index" in *[!0-9:]*|:*|*:) echo "invalid showcase shard $$shard_index/$$shard_count" >&2; exit 2;; esac; \
	if [ "$$shard_count" -lt 1 ] || [ "$$shard_index" -ge "$$shard_count" ]; then echo "invalid showcase shard $$shard_index/$$shard_count" >&2; exit 2; fi; \
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
	for b in sugar-ir-smt-lib sugar-ir-lean sugar-ir-coq sugar-ir-maude sugar-walk-rpc rust_test_assertions_rpc witness_rpc discharge_cli; do \
	  bin/sugarbin --profile debug --bin "$$b" >/dev/null || exit $$?; \
	done; \
	bin/sugarbin --profile release >/dev/null || exit $$?; \
	failed=""; \
	showcase_ordinal=0; \
	selected=0; \
	for s in $(SHOWCASE_RUNS); do \
		ordinal="$$showcase_ordinal"; showcase_ordinal=$$((showcase_ordinal + 1)); \
		if [ $$((ordinal % shard_count)) -ne "$$shard_index" ]; then continue; fi; \
		selected=$$((selected + 1)); \
		echo ""; \
		echo "==== [showcase shard $$shard_index/$$shard_count] $$s ===="; \
		"$$s" || failed="$$failed $$s"; \
	done; \
	echo ""; \
	echo "==== showcase shard $$shard_index/$$shard_count selected=$$selected ===="; \
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
self-attest:
	@set -e; \
	sugar_bin="$$(bin/sugarbin --profile release)"; \
	bin/sugarbin --profile release --bin sugar-lift >/dev/null; \
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

# Full-corpus `lift --report` is one RPC over ~1.4k loci. Kit hang detector
# defaults to 120s; this target sets SUGAR_LIFT_RESPONSE_TIMEOUT_SECS=900.
# Keep the recipe as ONE shell (`\` continuations): bare comment lines between
# `cd` and the lift start a new make shell and drop `sugar_bin` (Error 127).
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
	  remote_cmd="cd $$(printf '%q' "$$remote_repo") && CORETESTS_SOURCE_AUDIT_ON_REMOTE=1 USE_BCARGO=0 Z3=$${Z3:-/usr/bin/z3} SUGAR_LIFT_RESPONSE_TIMEOUT_SECS=$${SUGAR_LIFT_RESPONSE_TIMEOUT_SECS:-900} make coretests-source-audit"; \
	  ssh -o BatchMode=yes "$$remote_host" "bash -lc $$(printf '%q' "$$remote_cmd")"; \
	  exit $$?; \
	fi; \
	sugar_bin="$$(bin/sugarbin --profile release)" || exit $$?; \
	bin/sugarbin --profile release --bin rust_test_assertions_rpc >/dev/null || exit $$?; \
	bin_dir="$$(pwd -P)/implementations/rust/target/release"; \
	corpus="$(CORETESTS_SOURCE_AUDIT_CORPUS)"; \
	manifest_dir="$$corpus/.sugar/lift/rust-test-assertions"; \
	sed "s|@BIN_DIR@|$$bin_dir|g" "$$manifest_dir/manifest.toml.in" > "$$manifest_dir/manifest.toml"; \
	echo "==== coretests-source-audit: panic-armed source totality ===="; \
	cd "$$corpus"; \
	SUGAR_LIFT_RESPONSE_TIMEOUT_SECS="$${SUGAR_LIFT_RESPONSE_TIMEOUT_SECS:-900}" \
	  RUST_LOG=error NO_COLOR=1 CLICOLOR=0 TERM=dumb \
	  "$$sugar_bin" lift --report --report-summary

.PHONY: coretests-invariants
coretests-invariants:
	@set -e; \
	rustup toolchain install $(CORETESTS_RUST_VER) --component rust-src --profile minimal 2>/dev/null || true; \
	coretests_sweep="$$(bin/sugarbin --profile release --bin coretests_sweep)" || exit $$?; \
	CORPUS="$$(rustc +$(CORETESTS_RUST_VER) --print sysroot)/lib/rustlib/src/rust/library/coretests/tests"; \
	"$$coretests_sweep" "$$CORPUS" --rustc-cfg > /tmp/coretests-hermetic.out; \
	python3 scripts/check-coretests-invariants.py /tmp/coretests-hermetic.out implementations/rust/coretests-invariants.json

# Real python/pandas kit through sugar-lsp --in-process (PyCon demo path).
# Same battleaxe family as the witness corpus. Its legacy ambient interpreter
# is explicit; bcargo/brun do not provision one.
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
# Explicit battleaxe instrument: run this target when recomputing the full
# acceptance story; ordinary `make ci` must not pay for real-Pandas LSP twice.
.PHONY: test-3809-dod-scoreboard
test-3809-dod-scoreboard:
	@bash scripts/test-3809-dod-scoreboard.sh

.PHONY: ci
# `test-all` is an explicit development frontier, not a release gate: it runs
# the full Rust workspace and Python corpus, including intentionally red audits,
# ratchets, and battleaxe instruments. Keep default CI diagnostic by composing
# only focused receipts whose red result names one actionable contract.
ci: check-lift-refusal-vocabulary test-python-format test-showcases self-attest coretests-source-audit coretests-invariants
	@echo ""
	@echo "==== ci: PASS ===="

.PHONY: ci-core
# The non-showcase portion of the acid test. GitHub Actions runs this beside
# deterministic showcase shards; `ci` remains the one-command local surface.
ci-core: check-lift-refusal-vocabulary test-python-format self-attest coretests-source-audit coretests-invariants
	@echo ""
	@echo "==== ci-core: PASS ===="

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
