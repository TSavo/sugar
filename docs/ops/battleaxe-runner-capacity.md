# Battleaxe runner capacity (MAX_RUNNERS=10 + memory floor)

## Why 10 (not 25)

| Seats | RAM demand (~3.4GB each) | On 62GB host |
| --- | ---: | --- |
| 25 | ~85GB | **137%** → thrash (2026-08-02: AnonPages 57GB, MemFree 1GB, load 138) |
| **10** | **~34GB** | **~28GB headroom** for recensus / floors / walls / sshd |

Heavy work is single-process or k=8 — never needed 25 seats. There is **no
MIN_RUNNERS**; the pool is demand-driven (spawn on queue, reaper on idle).

## Memory law (not a guess)

Autoscaler refuses to spawn when:

`MemAvailable - RUNNER_ESTIMATED_MB < RUNNER_MEMORY_FLOOR_MB`

Defaults: floor **28672 MiB** (28 GiB), estimate **3482 MiB** (~3.4GB).

Same shape as the measurement load gate: a resource with no meter overfills.

## Apply on battleaxe (when WSL is confirmed back — once)

Do **not** SSH while WSL is restarting. When joe says battleaxe is up:

```bash
cd /home/tsavo/.github/runner-autoscaler
# Pull wopr-network/.github branch with host_memory + config, or rsync from Mac:
#   /Users/tsavo/.github/runner-autoscaler  (has the patch)

# Count + memory env (effect on next compose start — one bounce only):
grep -q '^MAX_RUNNERS=' .env && sed -i 's/^MAX_RUNNERS=.*/MAX_RUNNERS=10/' .env \
  || echo 'MAX_RUNNERS=10' >> .env
grep -q '^RUNNER_MEMORY_FLOOR_MB=' .env || echo 'RUNNER_MEMORY_FLOOR_MB=28672' >> .env
grep -q '^RUNNER_ESTIMATED_MB=' .env || echo 'RUNNER_ESTIMATED_MB=3482' >> .env

docker compose up -d --build autoscaler
```

If `bin/start.sh` regenerates `.env` from vault only, ensure it preserves or
re-emits `MAX_RUNNERS=10` and the memory floor vars.

Do not raise `MAX_RUNNERS` without re-running the RAM arithmetic and keeping
the memory floor.
