#!/usr/bin/env bash
set -euo pipefail

repo="${1:?usage: sugarbin_artifact_manifest.sh REPO_ROOT}"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/target/release" "$tmp/cache"
: >"$tmp/cargo.log"
: >"$tmp/child.log"

cat >"$tmp/bin/rustc" <<'SH'
#!/usr/bin/env bash
cat <<'EOF'
rustc 1.96.0 (fake 2026-01-01)
binary: rustc
commit-hash: fake
host: x86_64-unknown-linux-gnu
release: 1.96.0
LLVM version: 22.0.0
EOF
SH
cat >"$tmp/bin/cargo" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == -vV ]]; then
  cat <<'EOF'
cargo 1.96.0 (fake 2026-01-01)
release: 1.96.0
commit-hash: fake
commit-date: 2026-01-01
host: x86_64-unknown-linux-gnu
libgit2: 1.9.0
libcurl: 8.12.0
ssl: OpenSSL 3.5.0
os: Linux 6.1.0 [64-bit]
EOF
  exit 0
fi
printf '%s\n' "$*" >>"$SUGARBIN_FAKE_CARGO_LOG"
binary=""
while [[ $# -gt 0 ]]; do
  if [[ "$1" == --bin ]]; then binary="$2"; shift 2; else shift; fi
done
cat >"$SUGAR_BINARY_TARGET_ROOT/release/$binary" <<EOF
#!/usr/bin/env bash
printf '%s\\n' '$binary' >>'$SUGARBIN_FAKE_CHILD_LOG'
EOF
chmod +x "$SUGAR_BINARY_TARGET_ROOT/release/$binary"
SH
chmod +x "$tmp/bin/rustc" "$tmp/bin/cargo"

export PATH="$tmp/bin:$PATH"
export SUGARBIN_FAKE_CARGO_LOG="$tmp/cargo.log"
export SUGARBIN_FAKE_CHILD_LOG="$tmp/child.log"
export SUGAR_BINARY_CARGO="$tmp/bin/cargo"
export SUGAR_BINARY_TARGET_ROOT="$tmp/target"
export SUGAR_BINARY_CACHE_DIR="$tmp/cache"
export SUGAR_BINARY_SOURCE_STAMP="blake3-512:$(printf '1%.0s' {1..128})"
export SUGAR_BINARY_NO_SHELF=1 SUGAR_BINARY_PUBLISH=0

# SUGAR_BIN is a single-binary override. A differently requested executable
# must resolve from SUGAR_BINARY_DIR rather than aliasing to sugar.
mkdir -p "$tmp/injected"
printf '#!/usr/bin/env bash\nexit 0\n' >"$tmp/injected/sugar" \
  && chmod +x "$tmp/injected/sugar"
printf '#!/usr/bin/env bash\nexit 0\n' >"$tmp/injected/sugar-ir-smt-lib" \
  && chmod +x "$tmp/injected/sugar-ir-smt-lib"
resolved="$(SUGAR_BIN="$tmp/injected/sugar" SUGAR_BINARY_DIR="$tmp/injected" \
  "$repo/bin/sugarbin" --bin sugar-ir-smt-lib)"
[[ "$resolved" == "$tmp/injected/sugar-ir-smt-lib" ]] || {
  echo "SUGAR_BIN shadowed a different requested executable: $resolved" >&2; exit 1;
}
cp "$tmp/injected/sugar" "$tmp/injected/custom-sugar-path"
resolved="$(SUGAR_BIN="$tmp/injected/custom-sugar-path" "$repo/bin/sugarbin" --bin sugar)"
[[ "$resolved" == "$tmp/injected/custom-sugar-path" ]] || {
  echo "custom SUGAR_BIN override stopped applying to sugar: $resolved" >&2; exit 1;
}

# A stale sibling must not be blessed by building another executable.
printf '#!/usr/bin/env bash\nexit 99\n' >"$tmp/target/release/sugar-ir-smt-lib"
chmod +x "$tmp/target/release/sugar-ir-smt-lib"
"$repo/bin/sugarbin" --bin sugar >/dev/null
"$repo/bin/sugarbin" --bin sugar-ir-smt-lib >/dev/null
[[ "$(wc -l <"$tmp/cargo.log" | tr -d ' ')" == 2 ]] || {
  echo 'stale sibling was accepted under another executable identity' >&2; exit 1;
}
python3 - "$tmp/target/release/sugar.sugarbin.json" <<'PY'
import json, sys
with open(sys.argv[1]) as f: data = json.load(f)
required = {"schema", "binary", "package", "sourceStamp", "buildIdentity", "platform",
            "targetTriple", "profile", "features", "rustc", "cargo", "sha256", "built", "executed"}
assert set(data) == required
assert data["binary"] == "sugar" and data["package"] == "sugar-cli"
assert data["buildIdentity"].startswith("blake3-512:")
assert data["cargo"].startswith("cargo 1.96.0")
assert "\nrelease: 1.96.0\n" in data["cargo"]
assert "\nhost: x86_64-unknown-linux-gnu\n" in data["cargo"]
assert data["built"] is True and data["executed"] is False
PY

# A valid manifest is a cache hit, but cache hits skip compilation only.
: >"$tmp/cargo.log"; : >"$tmp/child.log"
"$repo/bin/sugarbin" run --needs sugar -- "$tmp/target/release/sugar"
[[ ! -s "$tmp/cargo.log" ]] || { echo 'cache hit compiled' >&2; exit 1; }
[[ "$(wc -l <"$tmp/child.log" | tr -d ' ')" == 1 ]] || { echo 'cache hit skipped child command' >&2; exit 1; }

# Corruption is rejected loudly before execution and repaired by one build.
printf '\n# mutation\n' >>"$tmp/target/release/sugar"
: >"$tmp/cargo.log"; : >"$tmp/child.log"
"$repo/bin/sugarbin" run --needs sugar -- "$tmp/target/release/sugar" 2>"$tmp/corrupt.err"
grep -Fq 'artifact checksum mismatch' "$tmp/corrupt.err"
[[ "$(wc -l <"$tmp/cargo.log" | tr -d ' ')" == 1 ]] || { echo 'corruption did not rebuild exactly once' >&2; exit 1; }
[[ "$(wc -l <"$tmp/child.log" | tr -d ' ')" == 1 ]] || { echo 'corruption skipped or duplicated child' >&2; exit 1; }

# build resolves every requested executable without executing either.
: >"$tmp/child.log"
"$repo/bin/sugarbin" build --needs sugar,sugar-ir-smt-lib
[[ ! -s "$tmp/child.log" ]] || { echo 'build executed an artifact' >&2; exit 1; }

# Separate shelf identity directories are coalesced into one truthful run PATH.
python3 - "$tmp/target/release" "$tmp/cache" <<'PY'
import json, pathlib, shutil, sys
target, cache = map(pathlib.Path, sys.argv[1:])
for binary in ("sugar", "sugar-ir-smt-lib"):
    manifest = target / f"{binary}.sugarbin.json"
    data = json.loads(manifest.read_text())
    name = f"{binary}-{data['platform']}-{data['profile']}-{data['buildIdentity'].replace(':', '_')}"
    cell = cache / name
    cell.mkdir(parents=True)
    shutil.copy2(target / binary, cell / binary)
    shutil.copy2(manifest, cell / f"{binary}.sugarbin.json")
    (target / binary).unlink()
    manifest.unlink()
PY
cat >"$tmp/bin/gh" <<'SH'
#!/usr/bin/env bash
exit 1
SH
chmod +x "$tmp/bin/gh"
export SUGAR_BINARY_NO_SHELF=0
: >"$tmp/cargo.log"; : >"$tmp/child.log"
"$repo/bin/sugarbin" run --needs sugar,sugar-ir-smt-lib -- true
[[ ! -s "$tmp/cargo.log" ]] || { echo 'valid local cache required working gh' >&2; exit 1; }

cat >"$tmp/bin/gh" <<'SH'
#!/usr/bin/env bash
if [[ "${1:-} ${2:-}" == "repo view" ]]; then printf 'TSavo/sugar\n'; exit 0; fi
exit 1
SH
chmod +x "$tmp/bin/gh"
export SUGAR_BINARY_NO_SHELF=0
: >"$tmp/cargo.log"; : >"$tmp/child.log"
"$repo/bin/sugarbin" run --needs sugar,sugar-ir-smt-lib -- bash -c '
  test "$(dirname "$SUGAR_BIN")" = "$SUGAR_BINARY_DIR"
  test "$(basename "$SUGAR_BIN")" = sugar
  test -x "$SUGAR_BINARY_DIR/sugar"
  test -x "$SUGAR_BINARY_DIR/sugar-ir-smt-lib"
  sugar
  sugar-ir-smt-lib
  printf "%s\n" command >>"$SUGARBIN_FAKE_CHILD_LOG"
'
[[ ! -s "$tmp/cargo.log" ]] || { echo 'multi-need shelf hit compiled' >&2; exit 1; }
[[ "$(grep -c '^sugar$' "$tmp/child.log")" == 1 ]] || { echo 'sugar did not run exactly once by name' >&2; exit 1; }
[[ "$(grep -c '^sugar-ir-smt-lib$' "$tmp/child.log")" == 1 ]] || { echo 'sugar-ir-smt-lib did not run exactly once by name' >&2; exit 1; }
[[ "$(grep -c '^command$' "$tmp/child.log")" == 1 ]] || { echo 'child command did not run exactly once' >&2; exit 1; }

# The bx route performs resolution on bx and never pulls the Linux executable
# into the caller's target directory.
cat >"$tmp/bin/ssh" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$SUGARBIN_FAKE_SSH_LOG"
exit 0
SH
cat >"$tmp/bin/rsync" <<'SH'
#!/usr/bin/env bash
printf '%s\n' "$*" >>"$SUGARBIN_FAKE_RSYNC_LOG"
exit 0
SH
chmod +x "$tmp/bin/ssh" "$tmp/bin/rsync"
: >"$tmp/ssh.log"; : >"$tmp/rsync.log"
(cd "$repo/implementations/rust" &&
  SUGARBIN_FAKE_SSH_LOG="$tmp/ssh.log" SUGARBIN_FAKE_RSYNC_LOG="$tmp/rsync.log" \
  BCARGO_SSH="$tmp/bin/ssh" BCARGO_RSYNC="$tmp/bin/rsync" \
  BCARGO_REMOTE_ROOT=/home/tsavo/remote/sugarbin-artifact-manifest-test \
  "$repo/bin/sugarbin" run --host bx --needs sugar,sugar-ir-smt-lib -- true)
grep -Fq 'bin/sugarbin --platform' "$tmp/ssh.log"
grep -Fq -- '--bin "$b"' "$tmp/ssh.log"
grep -Fq 'SUGAR_BINARY_DIR=' "$tmp/ssh.log"
grep -Fq 'sugar-ir-smt-lib' "$tmp/ssh.log"
! grep -Eq 'target/(release|debug)/sugar.*:' "$tmp/rsync.log"

echo 'PASS: sugarbin per-executable artifact manifests'
