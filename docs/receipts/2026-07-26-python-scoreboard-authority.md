# The Python corpus board gets one denominator

**Commit:** `9a78828ee` (branch `scoreboard-authority`, base `origin/main` `8373415a5`)
**Corpus:** pandas 3.0.3, 1,421 files, `battleaxe:~/pandas303-audit/pandas`
**Pin:** `docs/ledgers/pins/pandas-3.0.3.pin.json`

## The baseline

`docs/ledgers/pandas-3.0.3-control-effect-9a78828ee.json`. 1,421 enrolled,
**1,421 terminal rows**, 55 min wall, peak RSS 12.1 GB for the whole corpus.
Zero missing, zero duplicate, zero malformed. **Red**, and it says why.

```
enrolled 1421   terminal rows 1421   completed 1416   (5 terminal defect rows)
functions 27451                      construct-clean 22550

R_construction                    4     construction panics            0
R_desugar                      9694     desugar construction panics  502
R_backend_defects                 5     desugar defects               40
R_unresolvable_dispatch (#6329)   0     factoring gaps                13
timeouts                          0     controlEffectStableZero    False
```

### The two quantities, side by side — this is the whole point

```
site coverage   site:with-statement 7663    site:with-item 7673
ΔR              With-attributable construction R: 2
                (ContextManagerResolutionConstructionGap 1, UnsupportedWithBindingTarget 1)
```

**7,663 With sites. Two construction-R occurrences.** The `4125 / 811 / 85`
partition is neither of these numbers, and could not be reproduced by either,
because it was a name-derived split of a third thing. Total construction R over
the whole corpus is **4**.

### With residual, bucketed structurally

```
5737  gap:unrecognized:opaque-call-target:func      17  derived-contract
 715  gap:dynamic-export                            17  gap:unrecognized:non-manager-result:BlockValue
 709  gap:unrecognized:opaque-call-target:cast      14  gap:unrecognized:artifact-module-absent
  24  gap:unrecognized:target-outside-binding        7  gap:no-derived-contract
```

Two things fall out of this table that a name-table classifier could not have
shown. **`dynamic-export` is now 715 measured rows** rather than 780 aborted
files — the decode fix turned a fatal into a number. And the vocabulary is
dominated by `gap:unrecognized:*`, meaning `WithConstructionGapKind`'s closed
enum covers a small fraction of the resolution kinds actually produced. The
`parse` fallback preserves each wire kind instead of crashing or collapsing it,
which is the `dynamic-export` fix generalized — but the gap between the declared
vocabulary and the live one is itself a finding.

### What is red, and whose

- **502 desugar construction panics** — top owner
  `ContractConditionalConstructionV1.and_then` (283), then `IfExpSugar._join`
  (46), `collection ListValue` (41). Construction-law None arms: red, and never
  semantic R.
- **13 `ExitSetFactoringGap`** survive #6336, at named sites
  (`core/arrays/datetimelike.py:1397`, `:1461`, `core/generic.py:13403`).
  Partition testimony did not close all of them. Reported as observed; the
  prediction was zero.
- **5 terminal defect rows** — 3 are one backend defect,
  `spans.LineTable.line_col` reporting `offset 55069 outside 0..27637` on large
  test files; 2 are `SourceCallBindingGap: unconsumed call actual`.
- **0 construction panics and 0 timeouts** across 1,421 files.

## Why this exists

Two measurements were quoted against each other as one frontier. An AST-shape
site census read `With 4125/811/85`. The construction-R ledger for the same
period read `assertion 3 / resource 104 / other 4`. Both were correct
measurements of different things against different denominators, and the
difference between them was read as motion.

So the authority now states its denominator before it states any number.

## The two quantities

| | question it answers | where |
|---|---|---|
| **site coverage** | how many AST sites have this shape | `astSitePrevalence`, every key prefixed `site:` |
| **ΔR** | how many authenticated occurrences failed to construct or desugar | `R_construction`, `R_desugar` |

Prevalence is a denominator and is **never** called R. Lifting a capability
moves ΔR and leaves prevalence untouched — the `with` statements are still
there afterwards. A capability succeeded only when ΔR falls **without another
axis rising**.

## Corpus identity: an assumption converted into a measurement

Three digests, all computed from the same bytes and the same enumerator
(`SourceTree(root).paths()`), on the **battleaxe Linux / python3.12** corpus:

```
aggregate    bbb70a76f4032eda3362102c8bd872ca769b6f8143a91f60a36374fa1066b76c
contentOnly  a1155ae27c10a1828ac6a02b890a8b1ee23881a5f78c3d6265f02a63065ca77d
pathBound    04b67544e3628d25d1b20653558fb2c702a870ae3f97bc8492a9f70f854a9c31
files        1421
```

`contentOnly` and `pathBound` are the two conventions already circulating in
existing receipts, computed on **macOS / python3.14**. Both reproduce exactly.
The corpora are byte-identical across the interpreter gap. This was previously
assumed; it is now measured.

Our own `aggregate` differs from both because it additionally binds
distribution and version — the identical file set claimed as two different
pandas versions must not compare equal.

**Every pin states its convention in prose beside the digest.** A bare digest is
not checkable across agents, and convention drift was once mistaken for a
corpus difference.

## `m ** k` was eating the box — measured, not assumed

`core/arrays/arrow/array.py` (3286 lines), same file, same corpus, same
instrument. Only the commit differs:

| | pre-fix `06fefd9aa` | post-fix `517496571` |
|---|---|---|
| peak RSS | 31.1 GB, still climbing | **542 MB** (`/usr/bin/time -v`) |
| outcome | never finished the file | `done files=1/1` |
| wall | 50+ min, killed | 23:03, of which ~15 min is the one-time demand build |
| RSS shape | exponential | 39 MB flat, then 199 → 388 → 535, **stable** |

The bounded tail is the load-bearing observation. A smaller number could be
luck; a flat tail is the mechanism. This is #6324 / #6333 — `IfExpSugar` built a
two-completed-arm partition that reached `ExitSet.sequence` without passing
through `factor_completed`, distributing `m` completed arms across `k` operands
into `m ** k`. It presented here as memory rather than wall clock.

The pre-fix run consumed a shared machine: available memory on battleaxe fell
to zero and ssh stopped answering for about ten minutes.

## Two false greens caught

**1. A verdict that was arithmetically correct and wrong.** The bounded probe
returned `controlEffectStableZero: true` on a run that **exited 1**. Both were
right: the term is the defined conjunction (completed denominator ∧ timeouts ∧
construction panics ∧ factoring gaps — all zero), and the run was red on
`desugarConstructionPanics = 2`, an axis the conjunction does not cover.

The conjunction was **not** widened. It is a defined term and silently widening
it would be its own dishonesty. Instead the result states its own colour —
`red` and `redReasons`, derived from the same condition that colours the exit —
so no reader needs to know which axes the term happens to cover.

**2. `$?` after a pipeline is the last stage's status.** Three test runs were
read as passing because the command was piped:

```bash
bin/bpytest ... | tail -20     # $? is tail's. A red run reads green.
```

It is not that `tail` is dangerous; it is that **any** `| tail`, `| head`,
`| grep` on a measurement command discards the verdict. Capture the status
before piping, or set `-o pipefail`. `bpytest` itself propagates correctly
(measured `EXIT=2` on a failing run).

Both belong to the same family as everything else found here: a red that
arrives as green because the channel carrying it was replaced.

## An arm that cannot import its dispatch target is unwritten

#6329 was filed as five `perform_operation` call sites. The recognizer finds
**26 broken promises across 11 files**, every one confirmed by real import,
zero false positives. The missing targets are whole **modules** — a moved layer
whose callers were never updated:

```
11  sugar.floor_terms (floor_to_term)     2  sugar.install_source_dig
 4  sugar.for_sugar                       1  each: sugar.block_sugar,
 3  operations (perform_operation)              operations.binary_operator_operation,
 2  operations.perform_operation                sugar (builtin_dunder_call_sugar),
                                                lift_rpc (lift_file_payload)
```

All are function-local imports, so nothing fails until the arm is reached, and
reaching one raises `ImportError` — not a panic, not a typed refusal, not in any
family the census buckets. The row comes back short and nothing says so.

**Dead or live, with evidence.** A probe of exactly the shapes that dispatch to
the three `call_site_value` arms — `f(x)[0]`, `f(x) + 1`, `-f(x)` — through the
real census door measured 4 functions, 4 construct-clean, **no arm reached**.
Not reached by the construction+desugar door. Floor-evaluation drivers are not
settled and are not this instrument's to settle.

`tests/test_dispatch_targets_resolve.py` is **RED and must stay red** until
those 26 are written or deleted. Anyone who relaxes the check deletes the only
thing that can see this class.

## Rulings

**Vendor name tables are gone.** `cmMembranes` bucketed With residual by a
hard-coded list of pandas leaf names (`raises`, `ensure_clean`,
`option_context`). That grants a semantic category from spelling: the board
moved when pandas renamed something and stayed still when another project used
the same shape under a different name. Replaced by `cmResolutions`, bucketed by
authenticated resolution gap kind.

This **drops the assertion-vs-resource split**, which is the correct outcome.
The census owner independently disclosed the same defect in their own work: the
disposition split `3625 + 500 = 4125` is name-derived. Two agents reached the
same conclusion from opposite directions. The baseline classifies With
structurally or reports the partition as unavailable; it never republishes a
name-derived split as construction-R.

**The denominator is not a magic constant.** `reconcile_pandas_floors.py` had
`--expected-files` defaulting to `1415` while the docs said `1421`. The default
is removed; the reconciler now requires exactly one of `--corpus-pin` (derive
from the content-addressed pin) or `--expected-files` (own it explicitly).
Neither means asserting nothing; both means two sources of truth.

**Three scopes, three names for stableZero.** The corpus verdict stays with
`reconcile_pandas_floors.py`, which already merges five floors and enforces one
identical manifest CID and file list. This floor states
`controlEffectStableZero` — its own terms only. It is **not** added to the
shared `floor_summary`, which would make every floor separately claim a corpus
property it cannot see. `desugar_repro.py` keeps its reproducer-level verdict.

**A matching count is not an identity.** The docs-era 1421-file boards are
marked non-authoritative in place. Their file count matches the current pin;
nothing in them records which pandas bytes were walked, so they cannot be
differenced against a current measurement.

## The shell this deletes

`tests/test_one_authoritative_scoreboard.py` is a recognizer, not a checklist.
It finds every module emitting an R quantity — structurally, by `R`/`R_*` keys
in built payloads and printed lines — and requires each to declare
`SCOREBOARD_AUTHORITY`, with exactly one `True`. **29 modules were emitting R.**

`census.py` already *declared* the authority in its own docstring and shipped
the bare-`SourceFile.from_path` defect anyway. A checklist would have caught
nothing.

Retirement path: when a capability makes an axis unrepresentable, its
instrument is deleted and leaves this recognizer on its own.

## Bounded runs are the full run

Measuring one file **required** `--corpus-root`, and the row it produced **is**
the full-run row. The repair proved itself in use, not only in its tooth.

Previously a single-file corpus set `workspace_root = path.parent`, so the
demand table was derived from a different tree and the same file resolved its
`with` statements differently alone than in the corpus. Teeth pin both faces:
identical rows under the same root, different identity under a different root,
and refusal when no root is given.

## Operational notes

- **Run ssh-direct with an explicit `PYTHONPATH`.** `pytest.ini` sets only
  `--import-mode=importlib`, so every runner must supply the path. `bin/bpytest`
  routes through the managed image, whose declared closure omitted
  `sugar-source-tree` (#6334 fixed the declaration; #6335 tracks the unbuilt
  image and is parked).
- **A collection error makes whole files vanish rather than fail loudly** — a
  run under a broken `PYTHONPATH` does not report red, it reports a *smaller
  denominator*. Same family as the silently-shrinking-denominator class, and
  the reason the prevalence-versus-R separation matters.
- **Lease at the host path** `/home/tsavo/.cache/sugar/binaries`.
  `/home/runner/...` is the in-container path. Never `/var/tmp` on battleaxe —
  it is per-container, which is how two heavy jobs once overlapped with a
  0.0007s wait.
- **The measurement watcher halts the run itself** if available memory drops
  below 6 GB, logging `SELF-HALT`. It bounds the blast radius, not the work: it
  skips no file, degrades no row, and cannot make a red read green, because a
  halted run has an incomplete denominator, which is already red.
