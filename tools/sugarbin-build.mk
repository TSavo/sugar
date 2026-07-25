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

# sccache refuses to run at all under incremental compilation ("incremental
# compilation is prohibited: Unset CARGO_INCREMENTAL to continue"), and the
# repo's own advice in ~/.cargo/config.toml is that it cannot cache incremental
# builds anyway. A wrapper configured there therefore makes every debug build
# fail outright rather than merely go uncached. Drop the wrapper for the
# incremental profile: nothing is lost, because there was no caching to lose.
ifeq ($(SUGARBIN_INCREMENTAL),1)
SUGARBIN_RUSTC_WRAPPER_ARG := CARGO_BUILD_RUSTC_WRAPPER=""
else
SUGARBIN_RUSTC_WRAPPER_ARG :=
endif

.PHONY: sugarbin-build
sugarbin-build:
	mkdir -p "$(SUGARBIN_TARGET_DIR)"
	$(SUGARBIN_RUSTC_WRAPPER_ARG) \
	CARGO_TARGET_DIR="$(SUGARBIN_TARGET_DIR)" \
	CARGO_INCREMENTAL="$(SUGARBIN_INCREMENTAL)" \
	SUGAR_BUILD_STAMP="$(SUGARBIN_BUILD_STAMP)" \
	SUGAR_BUILD_GIT_HEAD="$(SUGARBIN_MONOREPO_HEAD)" \
	"$(SUGARBIN_CARGO)" build --locked \
	  --manifest-path "$(SUGARBIN_MANIFEST)" \
	  -p "$(SUGARBIN_PACKAGE)" --bin "$(SUGARBIN_BINARY)" \
	  $(SUGARBIN_PROFILE_ARG)
	test -x "$(SUGARBIN_OUTPUT)"
