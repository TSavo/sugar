#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp="$(mktemp -d)"
holder=""
trap '[[ -z "$holder" ]] || kill "$holder" 2>/dev/null || true; rm -rf "$tmp"' EXIT

cat >"$tmp/dpkg-query" <<'EOF'
#!/usr/bin/env bash
printf 'installed\n'
EOF
cat >"$tmp/sudo" <<'EOF'
#!/usr/bin/env bash
echo "sudo must not run for an installed package" >&2
exit 97
EOF
chmod +x "$tmp/dpkg-query" "$tmp/sudo"

# Reproduce the old failure: a cancelled apt descendant can retain this lock.
# The installed-package fast path must be independent of that stale owner.
flock /tmp/sugar-ci-apt.lock sleep 30 &
holder=$!
sleep 0.1

output="$(PATH="$tmp:$PATH" timeout 3 "$root/tools/ci-apt-install.sh" b3sum)"
grep -Fqx 'ci-apt: already installed: b3sum' <<<"$output"

echo "ci-apt installed-package fast path: PASS"

# ---------------------------------------------------------------------------
# The failure that made main unreadable: dpkg-query reports b3sum absent
# because it was acquired through cargo, so the script entered apt for a
# dependency that was already satisfied and then died on a stale lists lock.
# PATH availability is the question the build actually asks.
# ---------------------------------------------------------------------------

shadow="$tmp/shadow"
mkdir -p "$shadow"
for cmd in bash env dirname sed head grep ps sleep seq flock; do
  target="$(command -v "$cmd")"
  ln -sf "$target" "$shadow/$cmd"
done

cat >"$shadow/dpkg-query" <<'EOF'
#!/usr/bin/env bash
exit 1
EOF
cat >"$shadow/sudo" <<'EOF'
#!/usr/bin/env bash
echo "sudo must not run: b3sum is acquirable without apt" >&2
exit 97
EOF
chmod +x "$shadow/dpkg-query" "$shadow/sudo"

# Arm A: dpkg says absent, but b3sum is on PATH. No apt, no cargo.
cat >"$shadow/b3sum" <<'EOF'
#!/usr/bin/env bash
echo "b3sum 1.8.1"
EOF
cat >"$shadow/cargo" <<'EOF'
#!/usr/bin/env bash
echo "cargo must not run: b3sum is already on PATH" >&2
exit 96
EOF
chmod +x "$shadow/b3sum" "$shadow/cargo"

output="$(timeout 5 env PATH="$shadow" "$root/tools/ci-apt-install.sh" b3sum)"
grep -Fqx 'ci-apt: already on PATH: b3sum' <<<"$output"

echo "ci-apt PATH-satisfied fast path (dpkg blind to cargo install): PASS"

# Arm B: dpkg says absent and b3sum is not on PATH. Acquisition must go to
# crates.io at the sugar-build.toml pin, never to apt.
rm -f "$shadow/b3sum"
cat >"$shadow/cargo" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >"$SUGAR_TEST_CARGO_LOG"
EOF
chmod +x "$shadow/cargo"

pin="$(sed -n 's/^b3sum[[:space:]]*=[[:space:]]*"\([^"]*\)".*/\1/p' "$root/sugar-build.toml" | head -1)"
[[ -n "$pin" ]] || { echo "sugar-build.toml lost its b3sum pin" >&2; exit 1; }

timeout 5 env SUGAR_TEST_CARGO_LOG="$tmp/cargo.log" PATH="$shadow" \
  "$root/tools/ci-apt-install.sh" b3sum >/dev/null
grep -Fqx "install b3sum --locked --version $pin" "$tmp/cargo.log"

echo "ci-apt b3sum acquired from crates.io at the sugar-build.toml pin, apt untouched: PASS"

# Arm C (discrimination): a package with no non-apt door must still reach apt
# and must still fail loudly rather than silently succeeding.
status=0
timeout 30 env SUGAR_CI_APT_ATTEMPTS=2 PATH="$shadow" \
  "$root/tools/ci-apt-install.sh" z3 >/dev/null 2>"$tmp/z3.err" || status=$?
[[ "$status" -ne 0 ]] || { echo "apt-only package must not report success behind a failing sudo" >&2; exit 1; }
grep -Fq '::error::apt unavailable for z3' "$tmp/z3.err"

echo "ci-apt apt-only package still fails loudly: PASS"
