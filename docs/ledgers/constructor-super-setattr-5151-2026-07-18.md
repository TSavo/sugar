# ConstructorCallSugar residual: exact super-setattr

Measured against pandas 3.0.3 and NumPy 2.5.1 on the #5189 stacked head.

## Validated starting vector

All nine #5121 `ConstructorCallSugar` representatives remained live before
this change:

| file | observed |
| --- | --- |
| `pandas/core/_numba/extensions.py` | `IndexType.__init__ contains Assign` |
| `pandas/core/arrays/period.py` | `PeriodArray.__init__ contains If` |
| `pandas/io/parquet.py` | `PyArrowImpl.__init__ contains Expr` |
| `pandas/io/sql.py` | `SQLDatabase.__init__ contains ImportFrom` |
| `pandas/tests/tslibs/test_conversion.py` | `SubDatetime(datetime)` |
| `pandas/io/clipboard/__init__.py` | `CheckedCall.__init__ contains Expr` |
| `pandas/tests/scalar/timestamp/test_arithmetic.py` | `SubDatetime(datetime)` |
| `numpy/lib/tests/test_stride_tricks.py` | `VerySimpleSubClass(np.ndarray)` |
| `pandas/core/arrays/arrow/array.py` | `ArrowExtensionArray.__init__ contains If` |

`IndexType` is already owned by #5094 and is excluded from this slice. No
#5126 locus remains in the nine-file vector.

## Construction

`SourceFragment.initializer_call_site` recognizes the exact
`super().__setattr__("ground-name", value)` statement and emits typed
`super_setattr` testimony. The constructor-scoped
`ConstructorInitializerCallSugar` claim reduces the value in the real
initializer context and constructs the corresponding `self.<name>` scope
rebind.

Non-ground names, wrong arity, keywords, and non-exact `super` calls remain
loud. No effect constructor or empty-success arm was added.

## Named representative replay

| file | before | after |
| --- | --- | --- |
| `pandas/io/clipboard/__init__.py` | `ConstructorCallSugar / CheckedCall.__init__ contains Expr` | `TemporalContext / paste` |

Conservation:

| destination | count |
| --- | ---: |
| completed | 0 |
| advanced to distinct loud owner | 1 |
| still `ConstructorCallSugar` | 8 |
| silent | 0 |

After excluding the already-owned `IndexType` locus, the unowned
`ConstructorCallSugar` residual moves from 8 to 7.

