#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
HOOK="$ROOT/hooks/pre-commit"

if [ ! -x "$HOOK" ]; then
  echo "missing executable hook: $HOOK" >&2
  exit 1
fi

TMPDIR="$(mktemp -d)"
trap 'rm -rf "$TMPDIR"' EXIT

write_minimal_repo() {
  local repo="$1"
  mkdir -p "$repo/implementations/rust/fixture/src" "$repo/hooks"
  cp "$HOOK" "$repo/hooks/pre-commit"
  chmod +x "$repo/hooks/pre-commit"
  cat > "$repo/implementations/rust/Cargo.toml" <<'TOML'
[workspace]
members = ["fixture"]
resolver = "2"
TOML
  cat > "$repo/implementations/rust/fixture/Cargo.toml" <<'TOML'
[package]
name = "fmt-hook-fixture"
version = "0.1.0"
edition = "2021"
TOML
  cat > "$repo/implementations/rust/fixture/src/lib.rs" <<'RS'
pub fn fixture() -> i32 {
    0
}
RS
  (
    cd "$repo"
    git init -q
    git config user.name "Hook Test"
    git config user.email "hook-test@example.com"
    git add implementations/rust/Cargo.toml implementations/rust/fixture/Cargo.toml implementations/rust/fixture/src/lib.rs
    git -c commit.gpgsign=false commit -q -m init
    git config core.hooksPath hooks
  )
}

expect_blob() {
  local repo="$1"
  local path="$2"
  local expected="$3"
  local actual="$TMPDIR/blob"
  (
    cd "$repo"
    git show "HEAD:$path" > "$actual"
  )
  printf '%s' "$expected" | diff -u - "$actual"
}

commit_in_repo() {
  local repo="$1"
  local message="$2"
  shift 2
  (
    cd "$repo"
    git -c commit.gpgsign=false commit -m "$message" "$@"
  )
}

repo="$TMPDIR/repo"
write_minimal_repo "$repo"

(
  cd "$repo"
  cat > implementations/rust/fixture/src/sample.rs <<'RS'
pub fn sample( )->i32{1}
RS
  git add implementations/rust/fixture/src/sample.rs
)
commit_in_repo "$repo" "format staged rust" >"$TMPDIR/pre-commit-format-sample.out" 2>&1
expect_blob "$repo" implementations/rust/fixture/src/sample.rs $'pub fn sample() -> i32 {\n    1\n}\n'

(
  cd "$repo"
  cat > implementations/rust/fixture/src/clean.rs <<'RS'
pub fn clean() -> i32 {
    2
}
RS
  git add implementations/rust/fixture/src/clean.rs
)
commit_in_repo "$repo" "clean rust passes" >"$TMPDIR/pre-commit-format-clean.out" 2>&1
expect_blob "$repo" implementations/rust/fixture/src/clean.rs $'pub fn clean() -> i32 {\n    2\n}\n'

(
  cd "$repo"
  cat > implementations/rust/fixture/src/unstaged.rs <<'RS'
pub fn unstaged( )->i32{3}
RS
  cat > README.md <<'MD'
notes
MD
  git add README.md
)
commit_in_repo "$repo" "no staged rust no op" >"$TMPDIR/pre-commit-format-norust.out" 2>&1
grep -q 'pub fn unstaged( )->i32{3}' "$repo/implementations/rust/fixture/src/unstaged.rs"

(
  cd "$repo"
  cat > implementations/rust/fixture/src/partial.rs <<'RS'
pub fn staged() -> i32 {
    1
}

pub fn keep() -> i32 {
    2
}
RS
  git add implementations/rust/fixture/src/partial.rs
  git -c commit.gpgsign=false commit -q -m "partial base"

  cat > implementations/rust/fixture/src/partial.rs <<'RS'
pub fn staged( )->i32{1}

pub fn keep() -> i32 {
    2
}
RS
  git add implementations/rust/fixture/src/partial.rs
  cat > implementations/rust/fixture/src/partial.rs <<'RS'
pub fn staged( )->i32{1}

pub fn keep( )->i32{2}
RS
)
# Partially staged Rust must hard-fail (do not skip): unformatted staged hunks
# would otherwise land while the hook stays silent.
if commit_in_repo "$repo" "refuse partial staging" >"$TMPDIR/pre-commit-format-partial.out" 2>&1; then
  echo "expected pre-commit to refuse partially staged Rust" >&2
  cat "$TMPDIR/pre-commit-format-partial.out" >&2
  exit 1
fi
grep -q "has unstaged edits" "$TMPDIR/pre-commit-format-partial.out"
# Commit aborted: HEAD still the last full commit; worktree still has unstaged keep().
expect_blob "$repo" implementations/rust/fixture/src/partial.rs $'pub fn staged() -> i32 {\n    1\n}\n\npub fn keep() -> i32 {\n    2\n}\n'
grep -q 'pub fn keep( )->i32{2}' "$repo/implementations/rust/fixture/src/partial.rs"
# Drop the leftover staged partial so the next case is isolated.
(
  cd "$repo"
  git restore --source=HEAD --staged --worktree implementations/rust/fixture/src/partial.rs
)

(
  cd "$repo"
  mkdir -p generated/rust
  cat > generated/rust/outside.rs <<'RS'
pub fn outside( )->i32{4}
RS
  git add generated/rust/outside.rs
)
commit_in_repo "$repo" "skip outside workspace rust" >"$TMPDIR/pre-commit-format-outside.out" 2>&1
grep -q "skipping Rust file outside the cargo workspace: generated/rust/outside.rs" "$TMPDIR/pre-commit-format-outside.out"
expect_blob "$repo" generated/rust/outside.rs $'pub fn outside( )->i32{4}\n'

echo "pre-commit format hook tests passed"
