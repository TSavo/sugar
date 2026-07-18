# Timeout and Singleton Fatal Residual Design

## Scope

Issue #5194 owns the five bounded timeout rows plus the singleton
`RuntimeEffect` and `python.factory` rows measured at
`8282ce99031a5e00fba3012cc1ce99b46fd58e67`. Replaying the seven files
single-lane at current-main pin
`bd1833b771c1b139b727c5303ad1e7420f589c45` gives:

- `numpy/tests/test_public_api.py`: timeout at 300 seconds;
- `pandas/io/stata.py`: completes at 120 seconds (slow-only);
- `pandas/tests/frame/test_block_internals.py`: timeout at 300 seconds;
- `pandas/tests/io/test_stata.py`: timeout at 300 seconds;
- `numpy/_core/tests/test_multiarray.py`: timeout at 300 seconds;
- `pandas/core/generic.py`: typed `RuntimeEffect`;
- `pandas/tests/test_register_accessor.py`: typed `python.factory`.

The four surviving timeouts remain loud. No timeout bound, completion rule, or
failure classification changes in this lane. If PR #5191 merges before final
verification, rebase and replay these four rows to measure whether its
iterative list-comprehension collection retires any of them.

## Runtime-effect disposition

`pandas/core/generic.py` evaluates `_shared_docs = {**_shared_docs}`. Installed
source has already resolved `_shared_docs` to:

`ImportAliasValue(resolved_value=DictValue(entries=()))`.

The dict-unpack result is therefore lift-time decidable. Minting
`DictUnpackRuntimeEffect` is a mislabeled gap: perfect machinery would merge
the resolved `DictValue`. `DictLiteralSugar` will delegate an
`ImportAliasValue` with a resolved value to that value before its existing
`DictValue` merge. An alias without a resolved mapping remains on the existing
sealed `DictUnpackRuntimeEffect` door. There is no ground-value effect,
empty-success fallback, or quiet `None` arm.

## Factory disposition and recognizer

`pandas/tests/test_register_accessor.py` contains:

`@pd.api.extensions.register_series_accessor("bad") class Bad: ...`

The pandas accessor registrar returns the same class after registration. The
existing factory recognizer
`sugar_constructors.class_decorators_preserve_identity` already authenticates
known identity-preserving decorator exports. Extend it to:

1. authenticate module aliases from source imports;
2. recognize the qualified pandas exports
   `pandas.api.extensions.register_series_accessor`,
   `register_dataframe_accessor`, and `register_index_accessor`;
3. allow `ClassDefSugar` to own a decorated class only when this recognizer
   proves every decorator identity-preserving.

Unknown decorators, class-replacing decorators, dynamic decorator receivers,
and metaclass keywords remain unowned and produce the existing loud
`python.factory` panic. No inline AST `isinstance` chain or new `_is_*` /
`_matches_*` predicate is introduced.

## Alternatives rejected

- A new decorated-class sugar duplicates `ClassDefSugar` and creates a second
  recognition owner.
- A catalog-level special case matches syntax instead of authenticating the
  decorator contract.
- Treating all decorators as identity-preserving would quiet genuine
  class-replacement semantics.

## Receipts

- Single-lane 30→120→300-second replay for all five timeout rows.
- Named replays for the dict-unpack and accessor-decorated class rows, with
  stdout/stderr written to files and only aggregate owner tags printed.
- Unit discrimination:
  resolved dict alias constructs; unresolved alias remains a typed runtime
  effect; authenticated pandas registrar constructs; unknown decorator remains
  a loud factory panic.
- Seven-input conservation with `silent=0`.
- Direct claim-mass tripwire against a provenance-matched local release binary.
- Fresh truthful/lying witness for the accessor-decorated class path.

The PR is draft, non-closing, says `Part of #5194`, and is not merged.
