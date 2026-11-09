# Path forward: the finish line (owned by advisor)

**Owner:** advisor.
**Scope:** the Python lifter on the pinned pandas 3.0.3 corpus (1421 files). Nothing else is on this plan.
**Replaces:** plan v1 of 2026-08-01 (Phases 0 to 4). See "What changed" at the end.

## Done

Done is one pass of the corpus, on one commit of `main`, in which both of these hold:

1. **Every file ends in a terminal.** A terminal is one of two things: the file was constructed, or it was refused by a panic that names what is missing. Nothing is skipped silently and the denominator is the full 1421.
2. **Nothing ends any other way.** Native crashes, timeouts, bare exceptions and silent or unaccounted files are all zero.

The board from that pass is committed under `docs/ledgers/`. That commit is the finish.

A named refusal is a finished outcome, not a defect. The README already says so: "What a kit can't see is reported honestly as an effect, residue, or refusal". The refusals on the final board are the published residue. Constructing more of them is later work with its own plan.

## Why this ends

The worklist is the set of files that fail condition 2. It is finite, and each entry closes in one of two ways: construct the thing, or refuse it by name. Writing a construct can expose the next unwritten one, but that one arrives as a named refusal, which is already a terminal. The list grows only if a change breaks a file that used to end in a terminal.

Plan v1 also required construction panics to be zero, on the same pin, held across two consecutive boards. Under that rule every construct that got written exposed the next one, so the count had no way to reach zero.

## How work is chosen

1. Take the worklist from the most recent board: the files that crashed, timed out, raised a bare exception, or went unaccounted.
2. Pick one. Reproduce it on that one file, locally. Fix it so the file constructs or refuses by name. Add the test. Merge.
3. Repeat until the list is empty, then run the corpus pass that checks Done.

No step waits on CI. A full corpus pass checks the finish line and refreshes the worklist. It never gates the next fix, and nobody waits on one.

## Rules for every change

These were campaign-wide criteria in plan v1. They are now conditions on each pull request, checked when it merges. They are not counts to drive to zero across the corpus.

- **Construct or panic.** An unwritten construct refuses by a panic that names what is missing.
- **One mechanism.** No spelling match, swallow, or fabricated value stands in for a constructor.
- **Both twins.** A new construct or refusal ships with a truthful test and a lying test.

## Off plan

Anything that does not shrink the worklist or run the final pass is off plan. Say **OFF-PLAN** before starting it. That includes:

- Java and Rust work.
- Examples and example gates.
- CI and runner plumbing.
- New instruments, auditors or re-ranking exercises.
- Constructing a refusal that already has a name.

## Standing

| Date | Commit | Event |
|---|---|---|
| 2026-09-24 | `20cf4ede1` | Last board that completed (run 35993411797). 1421 files: 1197 constructed, 223 refused by name, 1 over the 300 s ceiling. 0 files missing, 0 functions unaccounted. |
| 2026-11-09 | `67033f579` | Plan v2 written. No board has completed since 2026-09-24. The process-floor run (native crashes, bare exceptions, timeouts) last succeeded on 2026-07-26 (run 30203371734). |

### Worklist

From the 2026-09-24 board. Refresh it on the next corpus pass.

1. `pandas/core/groupby/generic.py`: constructing the class at line 189 exceeds the 300 s ceiling.
2. Native crashes and bare exceptions: not measured since 2026-07-26.

### Residue on that board

Named refusals. These are not worklist.

| Files | Refusing owner |
|---|---|
| 218 | `With._construct_sugar` ("no contract ref: runtime-selected") |
| 3 | `SymbolicValue.attribute` |
| 1 | `roll_call.discharge` |
| 1 | `BuiltinSemanticCallable.python.super` |

## What changed from plan v1

| Plan v1 | Now |
|---|---|
| Construction panics must be zero | A named refusal is a terminal and is published as residue |
| Zero must hold across two consecutive boards | One pass on one commit |
| Phases 0 to 4, each waiting on a CI measurement (first step: runs 30720169468 and 30720199631 from 2026-08-01) | Deleted |
| "No local pytest"; CI is the only path | Reproduce and fix locally; CI does not gate work |
| Second mechanisms and twins counted campaign-wide (criteria 4 and 5) | Per-change rules |

Plan v1 is in git history at `67033f579:docs/path-forward.md`. Two files still cite its section numbers and are historical: `docs/measurement-machinery-audit.md` and the docstring of `tools/compose_commit_measurement.py`.
