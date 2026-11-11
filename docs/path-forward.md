# Path forward: the finish line (owned by advisor)

**Owner:** advisor.
**Scope:** the Python lifter on the pinned pandas 3.0.3 corpus (1421 files). Nothing else is on this plan.
**Replaces:** plan v1 of 2026-08-01 (Phases 0 to 4). See "What changed" at the end.

## The nine steps: the one way a Python file becomes a proof

Confirmed by the project owner, 2026-11-11: "It's a good umbrella, steps one through nine. That's what we're after. Everything that falls outside of steps one through nine is the cancer."

1. **Start the kit.** `sugar mint` drives the Python kit through one RPC method, `sugar.enumerate`.
2. **List the files** as content-addressed mementos. No parsing.
3. **Resolve imports before construction.** The kit lists the imported names it needs contracts for. The linker answers each from the proofs in `.sugar/imports/` (a contract with its CIDs and return term, or a named gap) and binds the table back into the kit.
4. **Parse into the node tree.** One node class per construct.
5. **Construct.** `node.sugar()`: each node builds its sugar from its children's, or refuses by name. A function body is first rewritten by temporal substitution (`FunctionDef._construct_sugar`), and that rewrite is part of the one way.
6. **Reduce.** `sugar.desugar(ctx)` to outcomes (completions and halts) holding values. A function body gives its universe (contract rows). An assert gives a fact. A call stands as the coordinate `call:<name>(<arg terms>)`, or substitutes actuals into a bound contract's return term.
7. **Emit edges.** The caller's claim, candidate target contracts, and a call edge with no target contract yet. An edge carries a `target_symbol`; the term `call:<name>(<arg terms>)` is what stands inside the formulas.
8. **Package** the rows into a content-addressed `.proof`.
9. **Prove.** Compile, join each edge's `target_symbol` to the imported contract whose `bridgeSourceSymbol` is the same string, conjoin, and the solver decides.

One way means: open once, construct once, reduce once, and every row is read off that one reduction.

Known violations of the way itself, recorded so they are not mistaken for part of it: a node's sugar reads a context table (`TreeConstructionContextV1`) that readers outside the tree fill; a second whole lifter (`lifter.py`) still runs on every mint (#7767); and the emitter emits rows only for a function that is a single completion, so no Python test reaches the solver (#7766).

Every plan row and every open issue below carries the step it belongs to. Anything the code does that belongs to no step is a deletion.

## Read this first: what the finish line below does and does not show

Written 2026-11-11. The "Done" recorded below on 2026-11-09 stands as a record of what was measured. It is not the finish.

**How the project works.** A lifter turns source into a proof file. Proof files plug together: one from the Python lifter, one from another lifter, staged in `.sugar/imports/`, and the solver decides the combined claim. A call to something this proof does not contain is an edge with a target symbol nothing has answered yet; a proof that answers it binds it.

**Two invariants, set by the project owner.**

1. **It compiles all the way.** Every rule is shown by a twin through the real solver: a truthful source that comes back `sat`, and the same source with one thing falsified that comes back `unsat`.
2. **One of each.** One lifter. One flooring mechanism. One temporal rewrite mechanism. No special cases, and no language detection: something the lifter does not have is not bridged, whatever the reason. A second way of doing something the lifter already does is the defect.

**What the board counts.** The board's door builds each function's tree and never reduces it (`roll_call.discharge` calls `.sugar()` and not `.desugar()`). "Completed" there means every node of the file built its tree or refused by name. It does not mean the function bodies were evaluated, and it is not a proof.

**What is true on main today.** `examples/python-base64-federation/run.sh`, the project in one script, fails at its first `sugar mint` (#7759). No change merged since the board has a twin through the solver. A review found ten places where the lifter has two doors where there should be one (#7757).

**The plan** is on #7661, "Plan: collapse to one": the federation example runs first, then each second door is collapsed, in order. Files are expected to change state as that happens; a file count is not the goal.

## Done

Done is one pass of the corpus, on one commit of `main`, in which both of these hold:

1. **Every file ends in a terminal.** A terminal is one of two things: the file was constructed, or it was refused by a panic that names what is missing. Nothing is skipped silently and the denominator is the full 1421.
2. **Nothing ends any other way.** Native crashes, timeouts, bare exceptions and silent or unaccounted files are all zero.

The board from that pass is committed under `docs/ledgers/`. That commit is the finish.

A named refusal is a finished outcome, not a defect. The README already says so: "What a kit can't see is reported honestly as an effect, residue, or refusal". The refusals on the final board are the published residue. Constructing them is the next line: see "Next line: the residue" below.

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
- Anything the lifter does that belongs to none of the nine steps above. That is not work to plan; it is a deletion.
- Example polish and showcase output. (Examples that mint and prove, such as `examples/python-base64-federation`, are not off plan: they are the acceptance test. Listing all examples here on 2026-11-09 was wrong.)
- CI and runner plumbing.
- New instruments, auditors or re-ranking exercises.
- Constructing a refusal that is not on the residue line below.

## Standing

| Date | Commit | Event |
|---|---|---|
| 2026-09-24 | `20cf4ede1` | Last board that completed (run 35993411797). 1421 files: 1197 constructed, 223 refused by name, 1 over the 300 s ceiling. 0 files missing, 0 functions unaccounted. |
| 2026-11-09 | `67033f579` | Plan v2 written. No board has completed since 2026-09-24. The process-floor run (native crashes, bare exceptions, timeouts) last succeeded on 2026-07-26 (run 30203371734). |
| 2026-11-09 | `5ed7a85fc` | A one-file run costs one file: the provisional demand door resolves one source at a time. `core/arrays/categorical.py` alone seals in 3.8 s; before, every run first derived the whole-corpus table (6+ minutes). |
| 2026-11-09 | on `5ed7a85fc` | `pandas/core/groupby/generic.py` constructs. Alone it ends completed, 65 of 65 functions, 0 gaps, 0 construction panics, in 17 to 27 s. Cause of the ceiling: `FunctionDef._owns_yield` walked the constructed DAG as a tree (5.1 million visits for 197 statements). One-file measurement, not a board. |
| 2026-11-09 | `c4cef9904` | **Done.** One corpus pass on this commit of `main`. 1421 files enrolled, 1421 terminal: 1203 constructed, 218 refused by name. 0 over the 300 s ceiling, 0 native crashes, 0 bare exceptions, 0 instrument failures, 0 files missing. 28264 functions enumerated, 0 unaccounted. Board: `docs/ledgers/pandas-3.0.3-control-effect-c4cef9904.json`. |

How that pass ran: 96 seats (`--slice i/96`), 28 at a time, 244 s for the seats and 14 s for the join, on one 32-thread box. Six seats were cut by the runner's own 90 s cap, which is not the product's 300 s per-file ceiling, leaving 8 files without rows; those seats were re-run in place (checkpoint resume) in 11 s and the 8 files ended in terminals. The board records this under `ledgerReduction.passRun`.

The board itself reports `red`: its stable-zero rule counts the 218 named refusals as defects. That is plan v1's rule. Under the done line above a named refusal is a finished outcome.

### Worklist

Ten files, from the corpus pass on `b4a4516cb` (all 1421 files; ledger `docs/ledgers/pandas-3.0.3-residue-line-b4a4516cb.json`). The 2026-11-09 board left this list empty; changes since then broke files that used to end in a terminal. Everything here comes before the residue line.

1. ~~`pandas/core/groupby/generic.py`: constructing the class at line 189 exceeds the 300 s ceiling.~~ Closed 2026-11-09. On the board it ends completed.
2. ~~Native crashes and bare exceptions: not measured since 2026-07-26.~~ Measured by the 2026-11-09 pass: every one of 96 seats exited 0, every file has a row, and every row that is not a completion is a panic of a named refusal class.
3. ~~`pandas/tests/io/excel/test_writers.py`: ended in a BackendDefect with no terminal on `7abebcdae` (#7673).~~ Closed 2026-11-11. On `b4a4516cb` it ends in a named refusal.
4. Four files have no terminal on `b4a4516cb`. #7712: `io/orc.py`, `tests/io/test_common.py` and `_testing/contexts.py` end in a BackendDefect inside `pandas/io/common.py`, introduced by `8d36276df` (#7709). #7713: `core/_numba/extensions.py` ends in a raw target-pattern gap, introduced by `cd7672eb2` (#7707). Each was a named refusal on `110626c00`.
5. Four files end completed with a `with` left unconstructed (#7699): `tests/indexing/test_loc.py`, `tests/series/indexing/test_setitem.py`, `plotting/_matplotlib/__init__.py`, `plotting/_matplotlib/boxplot.py`. They are not counted as complete.
6. Two files that completed on the board end in a named refusal now (#7676): `core/internals/construction.py`, `tests/io/parser/test_multi_thread.py`.

Also open and ahead of the residue line, though not a file without a terminal: one file's answer depends on what ran before it in the same process (#7678), and the first one-file run after some merges takes over 100 s (#7694).

### Residue on the final board

Named refusals: the published residue. Constructing them is the next line, below.

| Files | Refusing owner | What is missing |
|---|---|---|
| 156 | `With._construct_sugar` | No contract ref for the context manager: runtime-selected 76, dynamic-export 35, source-body-gap 25, no-derived-contract 12, call-closure-over-bound 4, artifact-module-absent 3, partition-member-unauthenticated 1 |
| 21 | `construct_manager_behavior returned object` | Callsite body for an unresolved source call |
| 20 | `CollectingReporter.present_construction` | A constructed-value category for `builtins.object` |
| 17 | `truth` | `ImportMemberValue` standing as a condition |
| 2 | `SymbolicValue.attribute` | Receiver type or member semantics for an attribute read |
| 1 | `roll_call.discharge` | Bounded construction depth (a `RecursionError` refused by name) |
| 1 | `BuiltinSuperValue.call_method_value` | The next class in the MRO for `super()` |

The committed board is the sealed board with its bulk witness sections replaced in place by their size and sha256 (the sealed board is 154 MB; the ledger is 0.5 MB). Every count, every identity and all 218 refusals are kept. `ledgerReduction.omitted` lists what was left out.

## Next line: the residue

Tracked in #7661. The issues are the worklist: work is picked from them, and a PR says which one it is part of.

**The list.** The 218 files in the residue table above, as they stood on the board at `c4cef9904`. The list is fixed at those files. It does not grow.

**Done.**

1. Every one of the 218 files is ticked (a one-file run on `main` ends completed) or struck (the refusal is the correct final answer for that file, with the reason written down in its issue).
2. Then one corpus pass on one commit of `main`, with the board committed under `docs/ledgers/`.

**Why this ends.** The count is files. Constructing one gap in a file and meeting the next one does not move the count; only a file completing does. Counting gaps is plan v1's rule, and that count could not reach zero.

**Rule for every PR on this line.** It says `Part of #N` for one of the issues below and names the board file it was reproduced on. It says whether that file now completes, or what it stops at next. A PR that names no board file is not on this line.

A file is complete when the board's door ends `completed` with no `with` left unconstructed.

| Issue | Refusal | Files | Complete on `b4a4516cb` | Left |
|---|---|---|---|---|
| #7663 | `With` has no contract ref: runtime-selected | 76 | 54 | 22 |
| #7664 | `With` has no contract ref: dynamic-export | 35 | 25 | 10 |
| #7665 | `With` has no contract ref: source-body-gap | 25 | 1 | 24 |
| #7666 | `With` has no contract ref: the four smaller kinds | 20 | 1 | 19 |
| #7667 | `construct_manager_behavior returned object` | 21 | 19 | 2 |
| #7668 | No constructed-value category for `builtins.object` | 20 | 19 | 1 |
| #7669 | `ImportMemberValue` standing as a condition (`truth`) | 17 | 17 | 0 |
| #7670 | The four single-owner refusals | 4 | 1 | 3 |
| | **Total** | **218** | **137** | **81** |

The state of each of the 218 files on `b4a4516cb` is in `docs/ledgers/pandas-3.0.3-residue-line-b4a4516cb.json`. The live count between commits of this file is on #7661.

### Standing on the residue line

| Date | Commit | Remaining | Event |
|---|---|---|---|
| 2026-11-09 | `c4cef9904` | 218 | Board. |
| 2026-11-10 | `7abebcdae` | 147 | Every one of the 218 files run once, one file per run (225 s, 14 at a time). 71 complete. 146 end in a named refusal: 129 the same refusal as on the board, 17 a different one. 1 has no terminal (#7673). Before this run, 90 PRs had merged since the board (#7576 to #7660) with none tied to an issue. |
| 2026-11-11 | `b4a4516cb` | 81 | One corpus pass, all 1421 files, 96 seats, every seat exit 0, 557 s. Corpus: 1338 complete, 75 named refusals, 4 complete with a `with` unconstructed (#7699), 4 with no terminal (#7712: three files, from #7709; #7713: one file, from #7707). Of the 218: 137 complete, 73 named refusals, 4 unconstructed-`with`, 4 no terminal. Off the list, 2 files that completed on the board are refused (#7676). |

## What changed from plan v1

| Plan v1 | Now |
|---|---|
| Construction panics must be zero | A named refusal is a terminal and is published as residue |
| Zero must hold across two consecutive boards | One pass on one commit |
| Phases 0 to 4, each waiting on a CI measurement (first step: runs 30720169468 and 30720199631 from 2026-08-01) | Deleted |
| "No local pytest"; CI is the only path | Reproduce and fix locally; CI does not gate work |
| Second mechanisms and twins counted campaign-wide (criteria 4 and 5) | Per-change rules |

Plan v1 is in git history at `67033f579:docs/path-forward.md`. Two files still cite its section numbers and are historical: `docs/measurement-machinery-audit.md` and the docstring of `tools/compose_commit_measurement.py`.
