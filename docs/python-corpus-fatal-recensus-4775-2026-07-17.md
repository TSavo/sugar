# Python fatal-frontier recensus for #4775 (2026-07-17)

## Measurement boundary

- Live snapshot: `b4ee8c01228ba1e9ac1720d701d548fbb2861da6`
- Earlier comparison snapshot: `1b1104ecc830772612ddc7c16760404c029b9d37`
- Python 3.14.4, NumPy 2.5.1, pandas 3.0.3, black 26.5.1
- Worktree-local virtual environment; no shared mint environment was modified
- Instrument:
  `implementations/python/sugar-lift-py-tests/scripts/corpus_fatal_triage.py`

Both packages were divided into small deterministic shards (NumPy 16, pandas
32) and run sequentially. Each assertion-bearing file ran in its own child
process. No partial payload was counted after an exception, panic, signal, or
timeout.

This is a bounded recensus, not a zero threshold. The discovery boundary was
10 seconds per child because the host was under sustained multi-fleet load.
The full vector below is exact at that boundary. Serial 120-second replay was
then sampled until two consecutive pandas files exceeded even that larger
ceiling; continuing all 293 replays would have monopolized the host for hours.
Consequently, the owner ranking is an exact ranking of the 245 files that
reached a typed `FactoryPanic`, and a lower bound on the whole live owner mass.
The 293 timeout rows remain loud and unassigned rather than being guessed into
owners.

## Corpus arithmetic

| Axis | NumPy + pandas |
|---|---:|
| Python files | **1,828** |
| Assertions in AST census | **20,769** |
| Files with assertions | **1,032** |
| Completed within 10 seconds | **481** |
| Typed `FactoryPanic` within 10 seconds | **245** |
| Bare exception within 10 seconds | **13** |
| Provisional timeout at 10 seconds | **293** |

`481 + 245 + 13 + 293 = 1,032`: every assertion-bearing file has exactly one
bounded terminal. There were zero parent crashes, native signals, or transport
disconnects. In the 120-second serial sample,
`pandas/tests/io/formats/test_to_string.py` and
`pandas/tests/reshape/merge/test_multi.py` both still exceeded the ceiling.

## Ranked live typed owners

These are files whose first terminal at the snapshot was a typed construction
panic. Counts exclude the 293 loud timeout rows and therefore are lower bounds.

| Rank | Owner | Files | Representative loci |
|---:|---|---:|---|
| 1 | `TemporalContext` | **64** | `numpy/_core/tests/test_api.py`; `numpy/_core/tests/test_array_coercion.py` |
| 1 | `RuntimeEffect` evidence door | **64** | `numpy/_core/tests/test_defchararray.py`; `numpy/f2py/func2subr.py` |
| 3 | `RaiseSugar` | **13** | `numpy/lib/_format_impl.py`; `pandas/compat/_optional.py` |
| 4 | `FunctionCallable` | **12** | `numpy/_core/tests/test_einsum.py`; `numpy/_core/tests/test_overrides.py` |
| 5 | `WithSugar` | **11** | `numpy/_core/tests/test_deprecations.py`; `pandas/tests/config/test_config.py` |
| 6 | `python.factory` | **6** | `numpy/_core/tests/test_custom_dtypes.py`; `numpy/_core/tests/test_errstate.py` |
| 6 | `bitwise_and` | **6** | `numpy/_core/tests/test_regression.py`; `pandas/tests/frame/test_query_eval.py` |
| 8 | `multiply` | **5** | `pandas/tests/frame/test_stack_unstack.py`; `pandas/tests/plotting/common.py` |
| 8 | `bitwise_xor` | **5** | `numpy/_core/tests/test_numeric.py`; `pandas/tests/frame/test_logical_ops.py` |
| 8 | `bitwise_invert` | **5** | `pandas/tests/arrays/test_datetimes.py`; `pandas/tests/frame/methods/test_clip.py` |
| 11 | `setitem` | **4** | `numpy/_core/tests/test_casting_unittests.py`; `pandas/core/sorting.py` |
| 11 | `divide` | **4** | `numpy/_core/tests/test_umath.py`; `pandas/tests/arithmetic/test_string.py` |
| 11 | `WhileSugar` | **4** | `pandas/io/formats/css.py`; `pandas/tests/test_nanops.py` |
| 14 | `add` | **3** | `numpy/_core/tests/test_datetime.py`; `pandas/tests/scalar/test_nat.py` |
| 14 | `SourceFragment` | **3** | `numpy/random/tests/test_random.py`; `numpy/random/tests/test_randomstate.py` |

Two-file owners: `unary_plus`, `unary_minus`, `subtract`,
`install_source_dig`, `floor_divide`, `delitem`, `ForSugar.static_unfold`,
`ForElseSugar`, and `AttributeSugar`.

One-file owners: `subscript`, `power`, `append_with`,
`WithSugar manager result`, `ImportAliasValue`, `FormatDunderCallSugar`,
`ForSugar`, `FloorValue.test_python_type`, `CallSugar`,
`AttributeDeleteSugar`, plus seven locus-named owners that need normalization
to a stable family before dispatch.

## Suppression audit: completed runtime effects

Classification law: an effect is honest only when perfect lift-time machinery
would still need Python runtime state. A constructible shape routed to an
effect remains live frontier mass.

| Effect | Files | Occurrences | Classification |
|---|---:|---:|---|
| `SubscriptStoreRuntimeEffect` | **67** | 182 | **Mixed / audit required.** Symbolic key/index and runtime receiver identity are genuine; the repeated “non-name receiver whose post-state cannot be rebound” arm describes missing heap/post-state construction and is live construct-or-panic mass. |
| `GetattrRuntimeEffect` | **66** | 143 | Genuine only for a runtime attribute name or opaque receiver; the sealed runtime-operand door rejects ground names. |
| `ConditionalExpressionRuntimeEffect` | **63** | 99 | Genuine runtime branch selection. |
| `CallResultTypeRuntimeEffect` | **43** | 89 | Genuine while the call result type is runtime-only. |
| `SequenceRepetitionRuntimeEffect` | **25** | 35 | Genuine runtime `__index__`/length; concrete counts are constructed. |
| `PowerRuntimeEffect` | **8** | 26 | Genuine runtime `__pow__` dispatch. |
| `SubtractRuntimeEffect` | **5** | 7 | Genuine runtime data-model dispatch after concrete floors fail. |
| `ConstructorRuntimeEffect` | **2** | 5 | **Suspicious live bucket.** Reasons cite unresolved inherited `__new__`/`__init__`; class ancestry is structurally discoverable, so this is construct-or-panic unless the selected class itself is runtime-only. |

Smaller emitted classes (`SubscriptResultRuntimeEffect`,
`SequenceConcatenationRuntimeEffect`, `DynamicTypeOperandRuntimeEffect`,
`AttributeStoreRuntimeEffect`, `ContextManagerExitRuntimeEffect`,
`SequenceUnpackRuntimeEffect`, and `DictUnpackRuntimeEffect`) carry
runtime-selected operands in the sampled testimony. They remain subject to the
same per-arm test; the class name alone is not an acquittal.

`NonlocalMutationRuntimeEffect` was a confirmed mislabeled gap (#4783). It
emitted no completed-corpus mass in this pass and is absent after #4789/#4804:
`nonlocal` is construct-or-panic, and every remaining effect constructor must
pass the sealed `RuntimeOperand` evidence door and its ground wrong twin.

## Retired and moved fronts

The old July 16 ranking is not a pick list. At snapshot `b4ee8c012`:

- `ListValue` concrete repetition, `MethodChainSugar`,
  `ConstructorCallSugar`, and `NonlocalMutationRuntimeEffect` are absent as
  terminal owners.
- the 256-file `python.factory / Match` front and the 57-file
  `bitwise_or` front from the `1b1104ecc` comparison run are absent.
- `TemporalContext` moved from 82 observed typed terminals to 64, but remains
  the largest named construction family.
- `append_with`, `multiply`, `divide`, `add`, `subtract`, `power`, and
  `subscript` have residual or newly exposed loci; closing an earlier
  representative issue did not prove global owner-zero.

Main continued moving after the measurement snapshot. In particular, merges
after `b4ee8c012` construct explicit exception causes, opaque callsite
bitwise-xor, source filenames, warning exits, nested continuing paths, string
subtraction, kwargs expansions, and mapping deletion. Those rows must be
replayed before assigning work; this document records the commit boundary
explicitly so a worker never treats a landed front as current merely because
it appears above.

## Dispatch rule

Pick from a verified-live exact fingerprint, not from the historical family
count alone. Re-run its named representative on current main; if it is retired,
comment/close the tracking issue rather than shipping a no-op. If it advances,
record the next loud owner. Runtime-effect candidates additionally must answer:
would perfect lift-time machinery still be unable to decide the operand? If
not, the only lawful dispositions are construction or a typed factory panic.
