# First honest whole-package baseline for the Python kit (2026-07-25)

Pin: `origin/main` @ `ca9a7bc94` ("Stop collecting the hash-pinned lift corpus as
sugar-lift-py-tests' own tests", #6260).

## Why this exists

Until #6260, `implementations/python/sugar-lift-py-tests` **could not be swept as
a package at all**. Collection aborted on
`tests/vendor/itsdangerous-2.2.0/test_serializer.py` with
`ModuleNotFoundError: itsdangerous`, so every "regression N green" claim about
this package came from targeted file invocations that dodged the abort. The
package holds most of the law twins and had never been run whole.

This receipt is the first whole-package run. **The artifact is the sorted set of
failed node IDs, not a count.** Future regression claims diff against these files;
they do not compare against a remembered number.

## Artifacts

| Package | Node-ID set | Summary |
|---|---|---|
| `sugar-lift-py-tests` | [`2026-07-25-sugar-lift-py-tests.failed-node-ids.txt`](2026-07-25-sugar-lift-py-tests.failed-node-ids.txt) | `131 failed, 1009 passed, 12 skipped, 5 errors in 912.14s` |
| `sugar-source-tree` | [`2026-07-25-sugar-source-tree.failed-node-ids.txt`](2026-07-25-sugar-source-tree.failed-node-ids.txt) | `16 failed, 485 passed, 5 skipped in 8.66s` |

The `sugar-lift-py-tests` set has **136 entries**: the 131 `FAILED` node IDs plus
the 5 `ERROR at setup of …` node IDs in `tests/test_lift_coverage_harness.py`,
which share one module-scoped `statistics_report` fixture. A setup error is a red
node; it is enrolled.

`sugar-source-tree` reproduces the previously reported figure byte-identically —
the same 16 loop-unroll / comprehension / slice family reds.

## Invocation

```
cd implementations/python
SRC=$(for d in sugar-*/src; do echo -n "$PWD/$d:"; done)
cd <package>                       # package is rootdir; a flat cross-package
                                   # invocation yields spurious fixture
                                   # ModuleNotFoundErrors
env PYTHONPATH="$SRC" python3 -m pytest tests -q -p no:cacheprovider -rf
```

Environment: the package's declared test extras
(`pip install -e implementations/python/sugar-lift-py-tests[test]`), which since
#6260 include `numpy` and `pandas` alongside `pytest`/`black`/`pyright`/
`itsdangerous`. Both packages were swept in the identical environment.

## Composition of the 136

Top loci:

```
  30  tests/test_numpy_literal_call_sibling_red.py
  23  tests/test_enumerate_rpc.py
  10  tests/test_lift_coverage_harness.py      (5 FAILED + 5 setup ERROR)
   8  tests/test_numpy_pandas_panic_audit.py
   8  tests/test_binary_handoff_policy.py
   6  tests/test_try_sat_unsat.py
   6  tests/test_object_field_flow_acceptance.py
   4  tests/test_bound_var_memoization.py
```

The dominant assertion text across the reds is the roll-call minority report
firing as designed — `Name registered but never answered the roll call` and its
`Param` / `Attribute` / `Constant` / `Call` / `Tuple` / `Assign` siblings. These
are product output, not harness noise.

Five reds are stale source references — tests naming files that no longer exist:

```
src/sugar_lift_py_tests/lib.py
src/sugar_lift_py_tests/factory/literal_call_report.py
src/sugar_lift_py_tests/sugar/call_sugar.py
src/sugar_lift_py_tests/sugar/install_source_dig.py
src/sugar_lift_py_tests/sugar/statement_function_def_sugar.py
```

**Notable absence:** the ~20 expected reds in
`tests/test_sole_path_manager_construction.py` /
`tests/test_source_call_preconstruction.py` (formal-read-through-class-`__init__`,
`BindingCoordinateRefSugar`) do **not** appear in this set. Whatever that lane is
measuring, it is not red at this pin under this environment.

## Protocol for the next claim

```
clean parent + declared test environment -> sorted failed node IDs
merged head  + identical environment     -> sorted failed node IDs
report additions and removals, not only counts
```

A count that matches while the identities differ is a regression wearing a
matching number.
