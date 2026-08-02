# Measurement conditions (the law)

> **A measurement must testify to its own conditions.**
> Quiet box, exclusive lease, correct corpus.
> Any one missing and the number is a guess wearing a receipt.

This is not style guidance. It is the only reason a wall-clock, residual, or
board number may be cited. The incidents below are the argument; the three
gates are the instrument. Nobody will remember the night in a month — this
file is how the law outlives it.

## The law

A number taken from a correctness instrument is **not evidence** unless the
run can show, in its own stderr and artifacts:

1. **The box was quiet** when the work started (and load after is recorded).
2. **No other quiet-gated measurement held the box** while it ran.
3. **The corpus is the authenticated pin**, not whatever was on system python.

If any of those three cannot be shown, do not cite the number. Do not put it
in a PR, a bisect, a merge hold, or a fleet comparison. Re-run under the
gates, or treat the work as unmeasured.

## What each gate cost us (2026-08-02)

### No load gate → fake speed

The Mac is 8 cores and was carrying the agent fleet (load average ~13.84, ~30
python processes). The same commit read **2.82s** and **6.46s** an hour apart
because wall-clock was taken on a contended laptop. That noise manufactured a
**fake ~87% serial regression** and a **fake single-file 3×**, which drove a
**merge hold** and a **four-way bisect** — pure contention, not code.

**Gate:** `SUGAR_BX_REQUIRE_QUIET=1` on `bin/brun`. Sample remote load1 under
the lease; refuse **exit 76** if over ceiling. Print load **before and after**.

### No exclusive lease → measuring each other

Six agents fired battleaxe measurements at once. Each load check could pass
while another run was mid-flight; each timed the others. Contention moved from
the Mac to the 32-core box without anyone noticing.

**Gate:** exclusive remote flock
`/var/tmp/sugar-bx-timing-measurement.lease` while quiet is armed. Queue or
refuse **exit 77**. Load is sampled **under** the lease, not before grab.

### No corpus pin → wrong pandas

Battleaxe **system python** has carried **pandas 2.3.3 (1415 files)**. The
authenticated pin is **pandas 3.0.3 (1421 files)**
(`docs/ledgers/pins/pandas-3.0.3.pin.json`). Five agents were about to report
numbers against the wrong corpus. A “correctness” comparison across two pandas
versions would have shown **phantom regressions and phantom fixes** with
confident receipts. Blonde caught it from ENOENT on files that exist only on
3.0.3.

**Gate:** under the lease, after load, run `tools/bx_corpus_pin_gate.py`
against `.venv-py312` + the banked pin; refuse **exit 78** on version/fileCount
mismatch. Recensus pin/aggregate refuse is also **exit 78**. Never measure with
system python.

## The three exits

| Exit | Name | Meaning |
| --- | --- | --- |
| **76** | host-not-quiet | load1 over ceiling under lease — not a slow measurement |
| **77** | timing-lease-busy | another quiet-gated measurement holds the exclusive lease |
| **78** | corpus-pin-mismatch | wrong distribution/version/fileCount (e.g. 2.3.3/1415 ≠ 3.0.3/1421) |

Exit **0** is necessary but not sufficient. A green exit without the receipt
fields below is still a guess.

## What a measurement receipt must carry

Every citable wall-clock or board body for a fleet timing run must include, at
minimum:

| Field | Where | Proves |
| --- | --- | --- |
| **load1 before** | stderr: `bx-load-gate phase=before … lease=held` | box quiet at start |
| **load1 after** | stderr: `bx-load-gate phase=after …` | load context after work |
| **lease held** | stderr: `bx-timing-lease phase=acquired` / `lease=held` | exclusive run |
| **corpus pin** | stderr: `bx-corpus-pin phase=ok` (version, distribution) | right package identity |
| **file count** | pin line / pin JSON summary (e.g. 1421) | right population size |
| **tip SHA** | recensus `--commit` / receipt `commit` / measured tip | which code was measured |

Optional but preferred: expected **aggregate hash** from the banked pin (printed
on pin-ok), host name, and `nproc`. JSON result bodies should not be cited
without the matching stderr gate lines from the same run.

## CI recensus

Human `bin/brun` timing uses all three gates. The control-effect recensus
workflow (`.github/workflows/control-effect-recensus.yml`, LPT k=8 + compose)
**must** run the **corpus pin gate** on **plan and every shard job** before
minting plan or partial bodies — **exit 78** if the runner is not pandas
**3.0.3 / 1421** (`tools/bx_corpus_pin_gate.py` + banked pin). Shard measure
also passes `--require-corpus-pin` into `control_effect_recensus` (second belt).

A sealed board against the wrong pin is worse than no board — it carries a
receipt.

**Load (76) and lease (77) are not wired in CI** until runner topology is
proven: the matrix may already be multi-box (lease would only serialize
same-host seats). Pin is mandatory either way. If topology later proves a
shared box, add lease under the same quiet discipline as brun.

## How to obey (human timing)

- Invoke **`bin/brun` by path** from the repo root.
- Always arm quiet: `SUGAR_BX_REQUIRE_QUIET=1`.
- Always measure with **`.venv-py312/bin/python`** after bootstrap (or a remote
  checkout already proven by exit-0 pin gate).
- Canonical shapes: **`docs/contributing/battleaxe-timing.md`**.

## Forbidden

- Wall-clock or residual numbers from the Mac under agent load.
- Concurrent quiet-gated runs that skip the lease.
- System python / unpinned site-packages as the corpus.
- Citing a JSON artifact without load, lease, pin, file count, and tip SHA
  (for brun timing); citing a CI board without pin gate green.
- Inventing a second remote harness next to `bin/brun`.
- CI plan/shard that mints artifacts before the corpus pin gate.

---

*Banked after the 2026-08-02 measurement night. The gates exist because each
failure produced a confident wrong number. Do not delete a gate without a
stronger substrate that still makes the illegal measurement unrepresentable.*
