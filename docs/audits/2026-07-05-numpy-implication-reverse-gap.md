# Numpy implication reverse-gap census

Part of #3503. This is the reverse gap behind the first numpy implication
edges: pre-bearing contracts that have no incoming call edge in the current
wall report.

## Receipt

Worktree branch: `codex/reverse-gap-drain`

Report command:

```sh
./implementations/rust/target/debug/sugar lift --report --json /tmp/numpy-wall-reverse-gap/numpy > /tmp/numpy-reverse-gap-rebased.json
```

Report counts on current `origin/main` after rebase:

| Measure | Count |
| --- | ---: |
| contracts | 1567 |
| pre-bearing contracts | 24 |
| call edges | 736 |
| resolved call edges | 12 |
| dangling call edges | 724 |
| unique pre-bearing targets with incoming edges | 2 |
| implication mementos | 11 |
| reverse-gap pre-bearing contracts | 22 |

The two pre-bearing targets with incoming edges are
`_core.getlimits.finfo.__new__` and `lib._npyio_impl.load`.

## Conclusion

There are zero joinable identity gaps in this slice: no reverse-gap contract has
both an existing production call edge and only a missing declared-identity
bridge. Therefore the implication count remains 11 in this PR. The residue is
still useful: it divides into assertion-surface gaps, non-call protocol/property
shapes, nested/internal helper contracts, and genuinely uncalled private
functions.

## Reverse-gap table

`call-edge target evidence` is from the emitted `callEdges` ledger, not raw
text search. A raw vendor-test mention without a call-edge is not joinable by
the implication pass yet.

| Contract | Public/test spelling evidence | Call-edge target evidence | Verdict |
| --- | --- | --- | --- |
| `_array_api_info.__array_namespace_info__.default_dtypes` | `_core/tests/test_array_api_info.py:26` assigns `info.default_dtypes()`; `:34` calls it in `pytest.raises`. `info` is built at `:5` by `np.__array_namespace_info__()`. | No `call:default_dtypes`, `call:info.default_dtypes`, or `call:numpy.__array_namespace_info__` edge. | assertion-surface / receiver-dataflow gap, not identity-drainable |
| `_array_api_info.__array_namespace_info__.dtypes` | `_core/tests/test_array_api_info.py:38`, `:82`, `:84`, `:88`, `:104`, `:109` call `info.dtypes(...)`; `info` is built at `:5`. | No `call:dtypes`, `call:info.dtypes`, or `call:numpy.__array_namespace_info__` edge. | assertion-surface / receiver-dataflow gap, not identity-drainable |
| `_core._internal._promote_fields` | No vendor-test call found. | No matching call edge. | genuinely uncalled by asserting vendor tests |
| `_core._ufunc_config.setbufsize` | `_core/tests/test_umath.py:4963`, `:4965`, `:4970`, `:4974`, `:4978`; `_core/tests/test_regression.py:1052`, `:1055` call `np.setbufsize`. Public declaration chain is `_ufunc_config.__all__` -> `numeric.py` star import -> `_core.__all__` -> `numpy.__all__`. | No `call:numpy.setbufsize` edge. | raw calls exist, but no implication-source call edge yet |
| `_core._ufunc_config.errstate.__enter__` | Many `with np.errstate(...)` and `@np.errstate(...)` uses, e.g. `_core/tests/test_errstate.py:20`, `:69`, `:77`. | No context-manager `__enter__` call edge. | context-manager/protocol shape gap |
| `_core.numeric.binary_repr.<locals>.err_if_insufficient` | `_core/tests/test_numeric.py:2029` and following call `np.binary_repr`; `_core/tests/test_multiarray.py:11349`, `:11351` call `np.binary_repr` in `pytest.raises`. | No `call:numpy.binary_repr` edge, and the pre-bearing contract is a local nested helper, not the public function. | nested-helper precondition, not identity-drainable |
| `_core.records.format_parser._parseFormats` | Only production call found: `_core/records.py:118`. | No matching call edge. | internal helper, genuinely uncalled by asserting vendor tests |
| `_core.records.record.__setattr__` | No direct vendor-test call to `record.__setattr__`; apparent `record(...)` hits are unrelated helpers. | No matching call edge. | protocol/magic-method shape gap |
| `_core.records.fromstring` | `_core/tests/test_multiarray.py:164`, `:177` call `np._core.records.fromstring`. Other `fromstring` call edges are `numpy.f2py.symbolic.fromstring`, a different function. | No `call:numpy._core.records.fromstring` or `call:numpy.rec.fromstring` edge; `call:numpy.f2py.symbolic.fromstring` has 55 edges but is not this contract. | raw calls exist, but no matching assertion call edge |
| `_core.records.fromfile` | `_core/tests/test_records.py:97`, `:104` call `np.rec.fromfile`; `:357` calls `np._core.records.fromfile`. | No `call:numpy.rec.fromfile` or `call:numpy._core.records.fromfile` edge. | raw calls exist, but no implication-source call edge yet |
| `f2py.f2py2e.validate_modulename` | Only production calls found: `f2py/f2py2e.py:465`, `:688`. | No matching call edge. | internal helper, genuinely uncalled by asserting vendor tests |
| `fft._pocketfft._raw_fft` | Only production calls found inside `fft/_pocketfft.py`. | No matching call edge. | internal helper, genuinely uncalled by asserting vendor tests |
| `lib._format_impl.magic` | Mentions in `lib/tests/test_format.py:91`-`:108` are doctest text; executable tests call `read_magic`, not `magic`. | No matching call edge. | doctest-only mention, no asserting call edge |
| `lib._function_base_impl._quantile_ureduce_func` | Only production callback reference found: `lib/_function_base_impl.py:4523`. | No matching call edge. | internal callback, genuinely uncalled by asserting vendor tests |
| `lib._npyio_impl._ensure_ndmin_ndarray_check_param` | Only production calls found: `lib/_npyio_impl.py:809`, `:956`, `:1952`. | No matching call edge. | internal helper, genuinely uncalled by asserting vendor tests |
| `ma.core.MaskedArray.mT` | Property access appears in `ma/tests/test_arrayobject.py:13`, `:19`, `:40` and `_core/tests/test_ufunc.py:861`. | No call edge because this is a property access, not a call. | property/protocol shape gap |
| `ma.core.power` | `ma/tests/test_core.py:4659`, `:4660`, `:4663`, `:4667` use imported `power`; emitted `call:numpy.power` edges in the report refer to the generic ufunc in `_core/tests/test_half.py`, not masked-array `ma.core.power`. | No `call:power`, `call:numpy.ma.power`, or `call:ma.core.power` edge. | raw masked-array calls exist, but no matching assertion call edge |
| `polynomial.set_default_printstyle` | `polynomial/tests/test_printing.py:19`, `:103`, `:190`, `:256`, `:259`, `:263`, and others call `poly.set_default_printstyle`. | No `call:numpy.polynomial.set_default_printstyle`, `call:poly.set_default_printstyle`, or `call:set_default_printstyle` edge. | stateful helper calls exist, but no implication-source call edge |
| `polynomial._polybase.ABCPolyBase._str_term_unicode` | Only production calls found in `polynomial/_polybase.py:341`, `:345`. | No matching call edge. | internal method, genuinely uncalled by asserting vendor tests |
| `polynomial._polybase.ABCPolyBase._str_term_ascii` | Only production calls found in `polynomial/_polybase.py:340`, `:346`. | No matching call edge. | internal method, genuinely uncalled by asserting vendor tests |
| `polynomial._polybase.ABCPolyBase._repr_latex_term` | Only production call found in `polynomial/_polybase.py:476`. | No matching call edge. | internal method, genuinely uncalled by asserting vendor tests |
| `polynomial.polyutils.trimcoef` | `polynomial/tests/test_polyutils.py:39`, `:41`, `:42`, `:43` call `pu.trimcoef` through `assert_raises` / `assert_equal`. | No `call:numpy.polynomial.polyutils.trimcoef`, `call:pu.trimcoef`, or `call:trimcoef` edge. | helper-assertion callsite shape gap |

## Bucket summary

| Bucket | Count | Rows |
| --- | ---: | --- |
| Joinable identity gaps with an existing call edge | 0 | none |
| Raw/assertion calls exist, but no implication-source call edge is emitted | 8 | `default_dtypes`, `dtypes`, `setbufsize`, records `fromstring`, records `fromfile`, `ma.core.power`, `set_default_printstyle`, `trimcoef` |
| Protocol/property/context-manager shapes | 3 | `errstate.__enter__`, `record.__setattr__`, `MaskedArray.mT` |
| Nested/local helper behind an outer public function | 1 | `binary_repr.<locals>.err_if_insufficient` |
| Doctest-only mention | 1 | `lib._format_impl.magic` |
| Genuinely uncalled internal/private helpers | 9 | `_promote_fields`, `_parseFormats`, `validate_modulename`, `_raw_fft`, `_quantile_ureduce_func`, `_ensure_ndmin_ndarray_check_param`, `_str_term_unicode`, `_str_term_ascii`, `_repr_latex_term` |

The next implication-growth lane should start with the rows in the raw/assertion
bucket whose source shape is already vendor-authored, especially `info.dtypes`
receiver dataflow and `assert_equal` / `assert_raises` helper-call edges. The
bridge resolver should not map by leaf similarity: `numpy.power` and
`numpy.f2py.symbolic.fromstring` are explicit negative examples.
