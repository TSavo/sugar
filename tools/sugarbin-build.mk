# Content-addressed construction rule for bin/sugarbin.
#
# sugarbin resolves the BLAKE3 build-input closure and the remote shelf. Make
# owns the local dependency question: an addressed output either exists or it
# must be constructed. Cargo remains the Rust compiler and incremental engine.

SHELL := bash
.SHELLFLAGS := -eu -o pipefail -c

ifndef SUGARBIN_OUTPUT
$(error SUGARBIN_OUTPUT is required)
endif
ifndef SUGARBIN_TARGET_DIR
$(error SUGARBIN_TARGET_DIR is required)
endif
ifndef SUGARBIN_MANIFEST
$(error SUGARBIN_MANIFEST is required)
endif
ifndef SUGARBIN_PACKAGE
$(error SUGARBIN_PACKAGE is required)
endif
ifndef SUGARBIN_BINARY
$(error SUGARBIN_BINARY is required)
endif
ifndef SUGARBIN_BUILD_STAMP
$(error SUGARBIN_BUILD_STAMP is required)
endif
ifndef SUGARBIN_MONOREPO_HEAD
$(error SUGARBIN_MONOREPO_HEAD is required)
endif

SUGARBIN_CARGO ?= cargo
SUGARBIN_PROFILE ?= debug

ifeq ($(SUGARBIN_PROFILE),release)
SUGARBIN_PROFILE_ARG := --release
SUGARBIN_INCREMENTAL := 0
else ifeq ($(SUGARBIN_PROFILE),debug)
SUGARBIN_PROFILE_ARG :=
SUGARBIN_INCREMENTAL := 1
else
$(error SUGARBIN_PROFILE must be debug or release)
endif

# rustc wrappers that cache whole-crate outputs (sccache) refuse to run at all
# under incremental compilation: "incremental compilation is prohibited: Unset
# CARGO_INCREMENTAL to continue." A wrapper configured in the developer's
# ~/.cargo/config.toml therefore makes every incremental build fail outright.
# Incremental is this file's deliberate choice for debug, so the incremental
# build drops the wrapper for its own invocation instead of losing incremental.
# Non-incremental builds leave the developer's wrapper untouched.
ifeq ($(SUGARBIN_INCREMENTAL),1)
SUGARBIN_WRAPPER_ENV := CARGO_BUILD_RUSTC_WRAPPER= RUSTC_WRAPPER=
else
SUGARBIN_WRAPPER_ENV :=
endif

.PHONY: sugarbin-build
sugarbin-build:
	mkdir -p "$(SUGARBIN_TARGET_DIR)"
	CARGO_TARGET_DIR="$(SUGARBIN_TARGET_DIR)" \
	CARGO_INCREMENTAL="$(SUGARBIN_INCREMENTAL)" \
	$(SUGARBIN_WRAPPER_ENV) \
	SUGAR_BUILD_STAMP="$(SUGARBIN_BUILD_STAMP)" \
	SUGAR_BUILD_GIT_HEAD="$(SUGARBIN_MONOREPO_HEAD)" \
	"$(SUGARBIN_CARGO)" build --locked \
	  --manifest-path "$(SUGARBIN_MANIFEST)" \
	  -p "$(SUGARBIN_PACKAGE)" --bin "$(SUGARBIN_BINARY)" \
	  $(SUGARBIN_PROFILE_ARG)
	test -x "$(SUGARBIN_OUTPUT)"
