# Python corpus recensus for #3732 (2026-07-16)

## Provenance and method

- Measured Sugar source tree: `eef57507899b55725dcce0cf20c97086c6051ef5`
- Current-main tip at publication: `5ffd44180bd467047eee37123af69bc2a2dda138`
  (the intervening commit adds only `.github/workflows/issue-claim-labels.yml`;
  there is no source, corpus, dependency, or instrument delta)
- Corpus: NumPy 2.5.1 and pandas 3.0.3 from an isolated worktree virtualenv
- Corpus size: 1,828 Python files (407 NumPy, 1,421 pandas)
- Source-refusal instrument:
  `implementations/python/sugar-lift-python-source/scripts/corpus_recensus.py`
- Factory/universe instrument:
  `implementations/python/sugar-lift-py-tests/scripts/corpus_factory_recensus.py`
- Factory pass: AST-census every file; production-lift only the 1,032 files that
  contain assertions. Each file gets 30 seconds. A timeout remains a failed
  file; it is not converted to success or a partial report. The deterministic
  pandas file list was split into four disjoint shards whose totals sum to
  1,421.

The source-refusal pass completed over all 1,828 files. The factory pass does
not fail open: 577 assertion-bearing files failed loudly and therefore emitted
no partial report. Universe-gap counts below are witnessed rows from completed
reports and are explicitly lower bounds, not estimates for the censored files.

## Stale-front corrections

| Front | Stale work order | Current main | Correction / disposition |
|---|---:|---:|---|
| #3262 decorator refusal | 8,993 | **8,971** | **-22**. Shapes: 8,953 opaque user/third-party, 16 stdlib/contextlib/functools, 2 NumPy-namespaced. The 22 cache-family rows already drained; the remainder is the recorded honest stop-line. |
| #3263 callee-subscript refusal | 30 | **30** | **0**. All 30 remain genuine dynamic-subscript dispatch; zero statically resolvable generic instantiations. |
| #3264 non-literal default | 245 | **243** | **-2**. Shapes: Attribute 154, Name 59, List 15, Dict 7, Call 7, Lambda 1. The two actually pinnable rows drained; the remaining 243 are the measured membrane. |
| #3467 deferred NumPy literal-call ops | 2 ops (`divide`, `equal`) | **1 op (`equal`)** | **-1 op**. `divide` drained. `numpy.equal` is still absent from the current literal-call reducer and remains subject to the issue's warrant/one-collapse re-derivation. This is an operation-ledger count, not a corpus refusal-row count. |

Full current source-refusal histogram:

| Kind | Count |
|---|---:|
| async-refused | 3 |
| callee-binop-refused | 97 |
| callee-boolop-refused | 2 |
| callee-call-refused | 7 |
| callee-compare-refused | 162 |
| callee-constant-refused | 297 |
| callee-dict-refused | 23 |
| callee-ifexp-refused | 2 |
| callee-joinedstr-refused | 33 |
| callee-set-refused | 1 |
| callee-subscript-refused | 30 |
| callee-unaryop-refused | 8 |
| decorator-refused | 8,971 |
| enum-pin-boundary | 50 |
| for-else-refused | 6 |
| generator-refused | 91 |
| global-nonlocal-refused | 37 |
| match-refused | 14 |
| multi-target-assign-refused | 73 |
| non-literal-default | 243 |
| value-pin-boundary | 499 |

## Factory and universe frontier

| Axis | NumPy | pandas | Total |
|---|---:|---:|---:|
| Python files | 407 | 1,421 | **1,828** |
| Assertions in AST census | 3,226 | 17,543 | **20,769** |
| Files with assertions | 142 | 890 | **1,032** |
| Assertion-bearing files completed | 45 | 410 | **455** |
| Assertion-bearing files failed loudly | 97 | 480 | **577** |
| Universe-absence FactoryGap rows witnessed | 368 | 3,949 | **4,317** |
| All red factory-walk rows witnessed | 368 | 3,963 | **4,331** |
| Facts emitted by completed files | 596 | 5,443 | **6,039** |

Failure types across the 577 failed assertion-bearing files:

| Failure | Files |
|---|---:|
| FactoryPanic | 567 |
| FileLiftTimeout (30 seconds) | 4 |
| KeyError | 4 |
| RecursionError | 1 |
| RuntimeError | 1 |

The universe row is new visibility from #3896. It is not a verifier acceptance
count and it does not replace the verifier's final refusal. On completed files,
each row is the typed `python.factory` absence testimony naming the callee,
source location, missing recipe, and retirement paths. The 4,317 total must be
read as `R_universe >= 4,317` because current main refuses 577 files before a
complete report exists. Reporting 4,317 as the whole corpus total would repeat
the old silent-frontier error.

## Reproduction

From an isolated editable install with NumPy 2.5.1 and pandas 3.0.3:

```sh
python implementations/python/sugar-lift-python-source/scripts/corpus_recensus.py

python implementations/python/sugar-lift-py-tests/scripts/corpus_factory_recensus.py numpy --compact

for shard in 0 1 2 3; do
  python implementations/python/sugar-lift-py-tests/scripts/corpus_factory_recensus.py \
    pandas --shard-count 4 --shard-index "$shard" --compact
done
```

The four pandas shard file totals are 356 + 355 + 355 + 355 = 1,421. Their
counts are summed, never averaged. No recognizer, verifier, timeout, or refusal
behavior was weakened for this recensus.

Part of #3732.
