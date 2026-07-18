# Module loader prefix TemporalContext design

## Validated frontier

At current main `08fa21e4a4ef51002ba208f80be8cd68f7e39879`, with Python
3.12.3, NumPy 2.5.1, and pandas 3.0.3, the five #5121 representatives
contain four files and nine `owner=TemporalContext` terminals.

Two files now reach `importlib.__init__` and fail on `__file__`. The prior
`_imp` dependency is constructed; the next missing evidence is the module
loader execution prefix.

## Construction

Python binds `__file__` before executing a source-backed module. The existing
`_module_import_temporal` catalog already constructs that binding from the
authenticated filename. Install-source function reconstruction uses the same
preserved source and filename testimony but currently starts from an empty
temporal.

Extract the loader-prefix binding into one factory-owned helper used by both
module traversal and install-source reconstruction. Install-source
reconstruction binds only loader names actually demanded by the selected
function/declaration dependency closure. No AST classifier is added.

## Loud boundary

Only FunctionDefs carrying complete `_sugar_source`, `_sugar_file`, and
qualified `_sugar_bridge_name` provenance may receive loader bindings.
Untagged or mismatched functions remain loud at `TemporalContext(__file__)`.
No RuntimeEffect or empty-success path is introduced.

## Evidence

- Discrimination: tagged source-backed function receives its exact `__file__`;
  the untagged twin remains a loud `FactoryPanic`.
- Fresh witness: imported module returns its loader filename; truthful
  equality is SAT and the wrong twin is UNSAT.
- Named replay: all five #5121 representatives are rerun, with completed,
  advanced-loud, unchanged-loud, and silent mass reported.

