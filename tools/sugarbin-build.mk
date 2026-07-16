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

.PHONY: sugarbin-build
sugarbin-build:
	mkdir -p "$(SUGARBIN_TARGET_DIR)"
	CARGO_TARGET_DIR="$(SUGARBIN_TARGET_DIR)" \
	CARGO_INCREMENTAL="$(SUGARBIN_INCREMENTAL)" \
	SUGAR_BUILD_STAMP="$(SUGARBIN_BUILD_STAMP)" \
	SUGAR_BUILD_GIT_HEAD="$(SUGARBIN_BUILD_STAMP)" \
	"$(SUGARBIN_CARGO)" build --locked \
	  --manifest-path "$(SUGARBIN_MANIFEST)" \
	  -p "$(SUGARBIN_PACKAGE)" --bin "$(SUGARBIN_BINARY)" \
	  $(SUGARBIN_PROFILE_ARG)
	test -x "$(SUGARBIN_OUTPUT)"
