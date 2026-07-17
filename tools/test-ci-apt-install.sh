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
