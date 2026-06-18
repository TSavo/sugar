#!/usr/bin/env bash
# Shared stdlib showcase solver/compiler wiring.
#
# Keep solver selection declarative: generated projects get a normal
# `.sugar/config.toml` portfolio plus `.sugar/ir-compilers/*/manifest.toml`
# compiler manifests. The CLI/verifier then discover the whole path from data.

write_sugar_ir_compiler_manifests() {
  local project="$1"
  local bin_dir="$2"

  mkdir -p \
    "$project/.sugar/ir-compilers/smt-lib" \
    "$project/.sugar/ir-compilers/coq" \
    "$project/.sugar/ir-compilers/lean" \
    "$project/.sugar/ir-compilers/maude"

  cat > "$project/.sugar/ir-compilers/smt-lib/manifest.toml" <<TOML
name = "smt-lib-reference"
version = "0.1.0"
protocol_version = "sugar-ir-compiler/1"
command = ["$bin_dir/sugar-ir-smt-lib"]
working_dir = "."
dialects = ["smt-lib-v2.6"]
TOML

  cat > "$project/.sugar/ir-compilers/coq/manifest.toml" <<TOML
name = "coq-reference"
version = "0.1.0"
protocol_version = "sugar-ir-compiler/1"
command = ["$bin_dir/sugar-ir-coq"]
working_dir = "."
dialects = ["coq"]
TOML

  cat > "$project/.sugar/ir-compilers/lean/manifest.toml" <<TOML
name = "lean4-mathlib-reference"
version = "0.1.0"
protocol_version = "sugar-ir-compiler/1"
command = ["$bin_dir/sugar-ir-lean"]
working_dir = "."
dialects = ["lean"]
TOML

  cat > "$project/.sugar/ir-compilers/maude/manifest.toml" <<TOML
name = "maude-equational-reference"
version = "0.1.0"
protocol_version = "sugar-ir-compiler/1"
command = ["$bin_dir/sugar-ir-maude"]
working_dir = "."
dialects = ["maude"]
TOML
}

append_sugar_solver_portfolio() {
  local config="$1"
  local repo="$2"
  local z3="${SUGAR_SOLVER_Z3:-z3}"
  local cvc5="${SUGAR_SOLVER_CVC5:-cvc5}"
  local vampire="${SUGAR_SOLVER_VAMPIRE:-vampire}"
  local coq="${SUGAR_SOLVER_COQ:-coqc}"
  local lean="${SUGAR_SOLVER_LEAN:-lake}"
  local maude="${SUGAR_SOLVER_MAUDE:-maude}"
  local ceta="${SUGAR_SOLVER_CETA:-ceta}"
  local aprove="${SUGAR_SOLVER_APROVE:-aprove}"
  local csi="${SUGAR_SOLVER_CSI:-csi}"

  cat >> "$config" <<TOML

[solvers]
mode = "first-wins"
portfolio = ["maude", "z3", "cvc5", "vampire", "coq", "lean"]

[solvers.maude]
binary = "$maude"
ir_compiler = "maude"
timeout_seconds = 30
version = "3.x"
ceta_gate = true
ceta_binary = "$ceta"
termination_prover = "$aprove"
confluence_checker = "$csi"

[solvers.z3]
binary = "$z3"
ir_compiler = "smt-lib-v2.6"
flags = ["-smt2", "-in"]
timeout_seconds = 30
version = "4.x"

[solvers.cvc5]
binary = "$cvc5"
ir_compiler = "smt-lib-v2.6"
flags = ["--lang=smt2", "--produce-models"]
timeout_seconds = 30
version = "1.x"

[solvers.vampire]
binary = "$vampire"
ir_compiler = "smt-lib-v2.6"
flags = ["--input_syntax", "smtlib2", "--output_mode", "smtcomp"]
timeout_seconds = 30
version = "5.x"

[solvers.coq]
binary = "$coq"
ir_compiler = "coq"
timeout_seconds = 60
version = "8.x"

[solvers.lean]
binary = "$lean"
ir_compiler = "lean"
timeout_seconds = 60
version = "4.x"
lake_project = "$repo/tools/portfolio/lean-mathlib"
TOML
}
