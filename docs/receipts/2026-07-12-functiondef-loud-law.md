# #4167 — unowned FunctionDef refuses loud

Date: 2026-07-12

## Law repair

`audit_lift_file` previously filtered each discovered `FunctionDef` through
`FunctionDefSugar.owns` / `TestFunctionDefSugar.owns` before calling the factory.
A default-argument function therefore took the `continue` branch and emitted no
IR, no audit gap, and no `factoryWalk` row. The repair removes that pre-dispatch
filter. Every discovered function now enters `build_node`; an unowned shape takes
the factory's typed `FactoryPanic` None arm, which the audit door projects as an
unresolved `factoryWalk` row with `verdict=gap`.

This change does not expand recognition. `FunctionDefSugar.owns` still excludes
default/decorated forms.

## Regression

Bad twin:

```python
def hidden(x=1):
    assert x == 1
```

Before the production change, the focused regression failed with `len(gaps) ==
0`. After the change it records one `FunctionDef` / `statement` gap at
`default_arg.py:1:0`, plus one unresolved `factoryWalk` row whose verdict is
`gap`.

The ordinary owned twin still selects `FunctionDefSugar` and emits IR.

## Verification

```text
SUGAR_BIN=/opt/data/sugar/implementations/rust/target/release/sugar \
pytest -q \
  tests/test_audit_frontier.py::test_unowned_default_arg_function_def_refuses_loud_in_factory_walk \
  tests/test_audit_frontier.py::test_owned_ordinary_function_def_still_lifts \
  tests/test_factory_walk_lane.py \
  tests/test_function_def_sugar.py

..........                                                               [100%]
10 passed in 0.52s
```

A practical pandas 3.0.3 slice used
`pandas/core/tools/timedeltas.py`. AST accounting found 6 definitions excluded
by the current default/vararg/kwarg/decorator ownership shape. Before this patch
the pre-dispatch filter silently skipped all 6; after this patch the same file
reports exactly 6 `FunctionDef` gaps (6 total gaps): a measured increase from 0
to 6 on the slice.

The completed official post-#4166 artifact is 131,967 `factoryWalk` rows with
11,586 truthful gaps. An exact pandas 3.0.3 census over all 1,421 Python files,
using the production `FunctionDefSugar.owns` / `TestFunctionDefSugar.owns`
predicates at the removed pre-dispatch seam, found 23,387 owned and **4,877
unowned `FunctionDef` nodes**. Thus this systemic visibility family is exactly
**0 -> 4,877**: zero rows before because the branch silently continued, and one
typed factory gap per node after because every node enters `build_node`.

A full local wall rerun was attempted with the documented `make pandas-wall`
target and the available release binary. It exceeded the 600-second execution
budget; its surviving diagnostic retry then encountered the known cross-file
module-global poisoning frontier (`'str' object does not support the context
manager protocol`). Therefore the 11,586 baseline comes from the existing
completed official artifact, while the actual production rerun claim is the
focused 0 -> 6 slice above; no fabricated full post-patch total is claimed.
