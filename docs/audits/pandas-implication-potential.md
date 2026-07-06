# Pandas Implication Potential

Part of #3503. This audit measures the pandas precondition side and records the current production-report boundary for the call-edge side. It does not add or change recognizers.

## Receipt

| item | value |
| --- | --- |
| repo head | `098a1a7259864038525b2fe2ed623d7c1239b9f7` |
| pandas version | `3.0.3` |
| cached workspace | `/Users/tsavo/.cache/sugar/python-panic-audit-workspaces/2d2b1bc3aa2ab1effb2ea6358d3ec88ed0d18f06f6d248654db7f0d15d0c07ae/pandas` |
| sugar binary | `/Users/tsavo/.cache/sugar/binaries/sugar-darwin-x86_64-release-blake3-512_f831b190795697a4338ff05350cdf77237f6ec75590a1d1d5089dbf76abcda78728a3b6c2cbcc7afefd6d03553234603bf77e0b6b8f11164dafd92884ab065a8` |
| binary file receipt | `/Users/tsavo/.cache/sugar/binaries/sugar-darwin-x86_64-release-blake3-512_f831b190795697a4338ff05350cdf77237f6ec75590a1d1d5089dbf76abcda78728a3b6c2cbcc7afefd6d03553234603bf77e0b6b8f11164dafd92884ab065a8: Mach-O 64-bit executable x86_64` |
| report command | `/Users/tsavo/.cache/sugar/binaries/sugar-darwin-x86_64-release-blake3-512_f831b190795697a4338ff05350cdf77237f6ec75590a1d1d5089dbf76abcda78728a3b6c2cbcc7afefd6d03553234603bf77e0b6b8f11164dafd92884ab065a8 lift --report --json /Users/tsavo/.cache/sugar/python-panic-audit-workspaces/2d2b1bc3aa2ab1effb2ea6358d3ec88ed0d18f06f6d248654db7f0d15d0c07ae/pandas` |
| report exit | `2` |
| report runtime | `574.62s` |
| stdout bytes / SHA-256 | `0` / `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| stderr bytes / SHA-256 | `28525` / `0ef7523b004d0c4fd258b6852401dab1b0ea37925e0ff2357c4d3c331a9f216e` |

## Result

- Source-lifter inventory: `69` function contracts, `68` pre-bearing contracts.
- Production report JSON: unavailable; the command returns JSON-RPC error `audit-only construction gaps` before emitting call edges.
- Blocking frontier in this run: `15` construction-gap rows across `5` templates.
- Implication join result: not measurable yet. There is no first pandas implication line to quote because the report graph is not emitted.
- Identity finding: source-side public re-export enrichment now remaps `41/68` pre-bearing contracts; the remaining `27` are classified internal-only below.
- Public spelling enrichment: `41/68` contracts now carry vendor-declared public spellings. The tail has `0` additional remaps because no remaining row has a non-private package `__init__.py` or `pandas.api.*` public alias.

## Blocking Templates

| count | kind | owner | observed | requested |
| ---: | --- | --- | --- | --- |
| 11 | `Floor` | `MembershipAssertionSugar` | `ArrayLiteral.contains(SymbolicValue)` | `contains item floor` |
| 1 | `Constructor` | `BuiltinCallSugar` | `T.__dir__` | `constructor-bound method` |
| 1 | `Floor` | `BinOpSugar` | `StringValue+StringValue` | `binary operator operand floor` |
| 1 | `Floor` | `BinOpSugar` | `StringValue+SymbolicValue` | `binary operator operand floor` |
| 1 | `Sugar` | `python.factory` | `Assert` | `statement` |

## Pre-Bearing Contract Table

Every row below has a substantive source-lifted precondition. `call-edge status` is uniformly `report-json-unavailable` in this audit because the production report did not emit the call-edge graph.

| # | contract | public spelling | source-side disposition | locus | call-edge status | implication minted |
| ---: | --- | --- | --- | --- | --- | --- |
| 1 | `core.apply.Apply.apply_list_or_dict_like` | `core.apply.Apply.apply_list_or_dict_like` | `internal-only` | `core/apply.py:703:1` | `report-json-unavailable` | `false` |
| 2 | `core.arrays._mixins.NDArrayBackedExtensionArray.value_counts` | `core.arrays._mixins.NDArrayBackedExtensionArray.value_counts` | `internal-only` | `core/arrays/_mixins.py:468:1` | `report-json-unavailable` | `false` |
| 3 | `core.arrays.arrow.array.ArrowExtensionArray._round_temporally` | `pandas.arrays.ArrowExtensionArray._round_temporally` | `public-remapped` | `core/arrays/arrow/array.py:3150:1` | `report-json-unavailable` | `false` |
| 4 | `core.arrays.arrow.array.ArrowExtensionArray._dt_tz_convert` | `pandas.arrays.ArrowExtensionArray._dt_tz_convert` | `public-remapped` | `core/arrays/arrow/array.py:3263:1` | `report-json-unavailable` | `false` |
| 5 | `core.arrays.base.ExtensionArray.view` | `pandas.api.extensions.ExtensionArray.view` | `public-remapped` | `core/arrays/base.py:2018:1` | `report-json-unavailable` | `false` |
| 6 | `core.arrays.base.ExtensionArray._rank` | `pandas.api.extensions.ExtensionArray._rank` | `public-remapped` | `core/arrays/base.py:2610:1` | `report-json-unavailable` | `false` |
| 7 | `core.arrays.categorical.Categorical._rank` | `pandas.Categorical._rank` | `public-remapped` | `core/arrays/categorical.py:2123:1` | `report-json-unavailable` | `false` |
| 8 | `core.arrays.datetimelike.DatetimeLikeArrayMixin._sub_datetimelike_scalar` | `core.arrays.datetimelike.DatetimeLikeArrayMixin._sub_datetimelike_scalar` | `internal-only` | `core/arrays/datetimelike.py:1163:1` | `report-json-unavailable` | `false` |
| 9 | `core.arrays.datetimelike.DatetimeLikeArrayMixin._sub_datetime_arraylike` | `core.arrays.datetimelike.DatetimeLikeArrayMixin._sub_datetime_arraylike` | `internal-only` | `core/arrays/datetimelike.py:1182:1` | `report-json-unavailable` | `false` |
| 10 | `core.arrays.datetimelike.DatetimeLikeArrayMixin._add_timedelta_arraylike` | `core.arrays.datetimelike.DatetimeLikeArrayMixin._add_timedelta_arraylike` | `internal-only` | `core/arrays/datetimelike.py:1250:1` | `report-json-unavailable` | `false` |
| 11 | `core.arrays.datetimelike.DatetimeLikeArrayMixin._accumulate` | `core.arrays.datetimelike.DatetimeLikeArrayMixin._accumulate` | `internal-only` | `core/arrays/datetimelike.py:1387:1` | `report-json-unavailable` | `false` |
| 12 | `core.arrays.datetimelike.TimelikeOps.as_unit` | `core.arrays.datetimelike.TimelikeOps.as_unit` | `internal-only` | `core/arrays/datetimelike.py:2010:1` | `report-json-unavailable` | `false` |
| 13 | `core.arrays.datetimelike.TimelikeOps.interpolate` | `core.arrays.datetimelike.TimelikeOps.interpolate` | `internal-only` | `core/arrays/datetimelike.py:2538:1` | `report-json-unavailable` | `false` |
| 14 | `core.arrays.masked.BaseMaskedArray._rank` | `pandas.core.arrays.BaseMaskedArray._rank` | `public-remapped` | `core/arrays/masked.py:1124:1` | `report-json-unavailable` | `false` |
| 15 | `core.arrays.sparse.array.SparseArray.fillna` | `pandas.arrays.SparseArray.fillna` | `public-remapped` | `core/arrays/sparse/array.py:796:1` | `report-json-unavailable` | `false` |
| 16 | `core.arrays.string_.BaseStringArray.view` | `core.arrays.string_.BaseStringArray.view` | `internal-only` | `core/arrays/string_.py:602:1` | `report-json-unavailable` | `false` |
| 17 | `core.base.SelectionMixin.__getitem__` | `core.base.SelectionMixin.__getitem__` | `internal-only` | `core/base.py:216:1` | `report-json-unavailable` | `false` |
| 18 | `core.common.require_length_match` | `core.common.require_length_match` | `internal-only` | `core/common.py:596:1` | `report-json-unavailable` | `false` |
| 19 | `core.computation.expr.BaseExprVisitor.visit_Module` | `core.computation.expr.BaseExprVisitor.visit_Module` | `internal-only` | `core/computation/expr.py:422:1` | `report-json-unavailable` | `false` |
| 20 | `core.computation.pytables.UnaryOp.prune` | `core.computation.pytables.UnaryOp.prune` | `internal-only` | `core/computation/pytables.py:418:1` | `report-json-unavailable` | `false` |
| 21 | `core.dtypes.common._get_dtype` | `core.dtypes.common._get_dtype` | `internal-only` | `core/dtypes/common.py:1624:1` | `report-json-unavailable` | `false` |
| 22 | `core.frame.DataFrame.to_stata` | `pandas.DataFrame.to_stata` | `public-remapped` | `core/frame.py:2665:1` | `report-json-unavailable` | `false` |
| 23 | `core.frame.DataFrame.map` | `pandas.DataFrame.map` | `public-remapped` | `core/frame.py:12494:1` | `report-json-unavailable` | `false` |
| 24 | `core.generic.NDFrame._rename` | `core.generic.NDFrame._rename` | `internal-only` | `core/generic.py:1002:1` | `report-json-unavailable` | `false` |
| 25 | `core.generic.NDFrame.pct_change` | `core.generic.NDFrame.pct_change` | `internal-only` | `core/generic.py:11434:1` | `report-json-unavailable` | `false` |
| 26 | `core.groupby.generic.DataFrameGroupBy._aggregate_frame` | `pandas.api.typing.DataFrameGroupBy._aggregate_frame` | `public-remapped` | `core/groupby/generic.py:2385:1` | `report-json-unavailable` | `false` |
| 27 | `core.groupby.groupby.GroupBy.pct_change` | `pandas.core.groupby.GroupBy.pct_change` | `public-remapped` | `core/groupby/groupby.py:5741:1` | `report-json-unavailable` | `false` |
| 28 | `core.groupby.ops.WrappedCythonOp._validate_axis` | `core.groupby.ops.WrappedCythonOp._validate_axis` | `internal-only` | `core/groupby/ops.py:525:1` | `report-json-unavailable` | `false` |
| 29 | `core.indexers.objects.VariableOffsetWindowIndexer.get_window_bounds` | `pandas.api.indexers.VariableOffsetWindowIndexer.get_window_bounds` | `public-remapped` | `core/indexers/objects.py:296:1` | `report-json-unavailable` | `false` |
| 30 | `core.indexes.api.union_indexes` | `core.indexes.api.union_indexes` | `internal-only` | `core/indexes/api.py:185:1` | `report-json-unavailable` | `false` |
| 31 | `core.indexes.base.Index.dropna` | `pandas.Index.dropna` | `public-remapped` | `core/indexes/base.py:2780:1` | `report-json-unavailable` | `false` |
| 32 | `core.indexes.base.Index._validate_sort_keyword` | `pandas.Index._validate_sort_keyword` | `public-remapped` | `core/indexes/base.py:2994:1` | `report-json-unavailable` | `false` |
| 33 | `core.indexes.base.Index._check_indexing_method` | `pandas.Index._check_indexing_method` | `public-remapped` | `core/indexes/base.py:3840:1` | `report-json-unavailable` | `false` |
| 34 | `core.indexes.base.Index._get_fill_indexer_searchsorted` | `pandas.Index._get_fill_indexer_searchsorted` | `public-remapped` | `core/indexes/base.py:3937:1` | `report-json-unavailable` | `false` |
| 35 | `core.indexes.base.Index.get_slice_bound` | `pandas.Index.get_slice_bound` | `public-remapped` | `core/indexes/base.py:6912:1` | `report-json-unavailable` | `false` |
| 36 | `core.indexes.base._validate_join_method` | `core.indexes.base._validate_join_method` | `internal-only` | `core/indexes/base.py:7998:1` | `report-json-unavailable` | `false` |
| 37 | `core.indexes.category.CategoricalIndex.reindex` | `pandas.CategoricalIndex.reindex` | `public-remapped` | `core/indexes/category.py:420:1` | `report-json-unavailable` | `false` |
| 38 | `core.indexes.multi.MultiIndex._reorder_ilevels` | `pandas.MultiIndex._reorder_ilevels` | `public-remapped` | `core/indexes/multi.py:3020:1` | `report-json-unavailable` | `false` |
| 39 | `core.indexes.multi.MultiIndex._partial_tup_index` | `pandas.MultiIndex._partial_tup_index` | `public-remapped` | `core/indexes/multi.py:3384:1` | `report-json-unavailable` | `false` |
| 40 | `core.indexes.period.PeriodIndex._disallow_mismatched_indexing` | `pandas.PeriodIndex._disallow_mismatched_indexing` | `public-remapped` | `core/indexes/period.py:516:1` | `report-json-unavailable` | `false` |
| 41 | `core.internals.blocks.check_ndim` | `core.internals.blocks.check_ndim` | `internal-only` | `core/internals/blocks.py:2273:1` | `report-json-unavailable` | `false` |
| 42 | `core.internals.managers.SingleBlockManager.get_slice` | `pandas.core.internals.SingleBlockManager.get_slice` | `public-remapped` | `core/internals/managers.py:2161:1` | `report-json-unavailable` | `false` |
| 43 | `core.resample.TimeGrouper.__init__` | `pandas.api.typing.TimeGrouper` | `public-remapped` | `core/resample.py:2385:1` | `report-json-unavailable` | `false` |
| 44 | `core.resample._asfreq_compat` | `core.resample._asfreq_compat` | `internal-only` | `core/resample.py:3124:1` | `report-json-unavailable` | `false` |
| 45 | `core.reshape.pivot.crosstab` | `pandas.crosstab` | `public-remapped` | `core/reshape/pivot.py:919:1` | `report-json-unavailable` | `false` |
| 46 | `core.tools.times.to_time` | `core.tools.times.to_time` | `internal-only` | `core/tools/times.py:23:1` | `report-json-unavailable` | `false` |
| 47 | `core.window.ewm.ExponentialMovingWindow.var` | `pandas.api.typing.ExponentialMovingWindow.var` | `public-remapped` | `core/window/ewm.py:746:1` | `report-json-unavailable` | `false` |
| 48 | `core.window.ewm.ExponentialMovingWindow.cov` | `pandas.api.typing.ExponentialMovingWindow.cov` | `public-remapped` | `core/window/ewm.py:795:1` | `report-json-unavailable` | `false` |
| 49 | `core.window.ewm.ExponentialMovingWindow.corr` | `pandas.api.typing.ExponentialMovingWindow.corr` | `public-remapped` | `core/window/ewm.py:887:1` | `report-json-unavailable` | `false` |
| 50 | `core.window.ewm.OnlineExponentialMovingWindow.__init__` | `core.window.ewm.OnlineExponentialMovingWindow.__init__` | `internal-only` | `core/window/ewm.py:1018:1` | `report-json-unavailable` | `false` |
| 51 | `core.window.rolling.BaseWindow._apply_tablewise` | `core.window.rolling.BaseWindow._apply_tablewise` | `internal-only` | `core/window/rolling.py:491:1` | `report-json-unavailable` | `false` |
| 52 | `core.window.rolling.RollingAndExpandingMixin.cov` | `core.window.rolling.RollingAndExpandingMixin.cov` | `internal-only` | `core/window/rolling.py:1857:1` | `report-json-unavailable` | `false` |
| 53 | `core.window.rolling.RollingAndExpandingMixin.corr` | `core.window.rolling.RollingAndExpandingMixin.corr` | `internal-only` | `core/window/rolling.py:1904:1` | `report-json-unavailable` | `false` |
| 54 | `io.formats.excel.ExcelFormatter._num2excel` | `pandas.io.formats.excel.ExcelFormatter._num2excel` | `public-remapped` | `io/formats/excel.py:878:1` | `report-json-unavailable` | `false` |
| 55 | `io.formats.info.SeriesInfo.render` | `pandas.io.formats.info.SeriesInfo.render` | `public-remapped` | `io/formats/info.py:365:1` | `report-json-unavailable` | `false` |
| 56 | `io.parsers.python_parser.PythonParser._alert_malformed` | `pandas.io.parsers.python_parser.PythonParser._alert_malformed` | `public-remapped` | `io/parsers/python_parser.py:946:1` | `report-json-unavailable` | `false` |
| 57 | `io.parsers.readers.read_fwf` | `pandas.read_fwf` | `public-remapped` | `io/parsers/readers.py:1479:1` | `report-json-unavailable` | `false` |
| 58 | `io.pytables.read_hdf` | `pandas.read_hdf` | `public-remapped` | `io/pytables.py:320:1` | `report-json-unavailable` | `false` |
| 59 | `io.pytables.HDFStore.append` | `pandas.HDFStore.append` | `public-remapped` | `io/pytables.py:1290:1` | `report-json-unavailable` | `false` |
| 60 | `io.pytables.GenericFixed.validate_read` | `pandas.io.pytables.GenericFixed.validate_read` | `public-remapped` | `io/pytables.py:3033:1` | `report-json-unavailable` | `false` |
| 61 | `io.sql.to_sql` | `pandas.io.sql.to_sql` | `public-remapped` | `io/sql.py:742:1` | `report-json-unavailable` | `false` |
| 62 | `io.stata.StataValueLabel.__init__` | `pandas.io.stata.StataValueLabel.__init__` | `public-remapped` | `io/stata.py:581:1` | `report-json-unavailable` | `false` |
| 63 | `io.stata.StataNonCatValueLabel.__init__` | `pandas.io.stata.StataNonCatValueLabel.__init__` | `public-remapped` | `io/stata.py:698:1` | `report-json-unavailable` | `false` |
| 64 | `io.stata.StataStrLWriter.__init__` | `pandas.io.stata.StataStrLWriter.__init__` | `public-remapped` | `io/stata.py:3203:1` | `report-json-unavailable` | `false` |
| 65 | `plotting._matplotlib.hist._grouped_plot` | `pandas.plotting._matplotlib.hist._grouped_plot` | `public-remapped` | `plotting/_matplotlib/hist.py:294:1` | `report-json-unavailable` | `false` |
| 66 | `plotting._matplotlib.style._get_colors_from_color` | `pandas.plotting._matplotlib.style._get_colors_from_color` | `public-remapped` | `plotting/_matplotlib/style.py:192:1` | `report-json-unavailable` | `false` |
| 67 | `tseries.holiday.AbstractHolidayCalendar.holidays` | `pandas.tseries.holiday.AbstractHolidayCalendar.holidays` | `public-remapped` | `tseries/holiday.py:496:1` | `report-json-unavailable` | `false` |
| 68 | `util._validators._check_arg_length` | `util._validators._check_arg_length` | `internal-only` | `util/_validators.py:31:1` | `report-json-unavailable` | `false` |

## Unmapped Tail Classification

All 27 tail rows are category (a): internal-only in the source-side identity map. They may still receive implications from same-module/internal call edges once the report graph renders, but they do not have a vendor-declared public spelling for consumer-facing re-export joins.

| # | contract | disposition | evidence |
| ---: | --- | --- | --- |
| 1 | `core.apply.Apply.apply_list_or_dict_like` | `internal-only` | internal class method; `Apply` is defined in `core.apply` with no exact or owner public import declaration. |
| 2 | `core.arrays._mixins.NDArrayBackedExtensionArray.value_counts` | `internal-only` | internal mixin method; owner imports are `_testing` or internal `core.*` consumers only. |
| 3 | `core.arrays.datetimelike.DatetimeLikeArrayMixin._accumulate` | `internal-only` | internal mixin method; owner imports are `_testing.asserters` and internal `tseries.frequencies` only. |
| 4 | `core.arrays.datetimelike.DatetimeLikeArrayMixin._add_timedelta_arraylike` | `internal-only` | internal mixin method; owner imports are `_testing.asserters` and internal `tseries.frequencies` only. |
| 5 | `core.arrays.datetimelike.DatetimeLikeArrayMixin._sub_datetime_arraylike` | `internal-only` | internal mixin method; owner imports are `_testing.asserters` and internal `tseries.frequencies` only. |
| 6 | `core.arrays.datetimelike.DatetimeLikeArrayMixin._sub_datetimelike_scalar` | `internal-only` | internal mixin method; owner imports are `_testing.asserters` and internal `tseries.frequencies` only. |
| 7 | `core.arrays.datetimelike.TimelikeOps.as_unit` | `internal-only` | internal subclass method; `TimelikeOps` has no public import declaration. |
| 8 | `core.arrays.datetimelike.TimelikeOps.interpolate` | `internal-only` | internal subclass method; `TimelikeOps` has no public import declaration. |
| 9 | `core.arrays.string_.BaseStringArray.view` | `internal-only` | internal base-class method; owner imports are internal string/pytables consumers only. |
| 10 | `core.base.SelectionMixin.__getitem__` | `internal-only` | internal mixin method; owner imports are internal groupby/resample/window consumers only. |
| 11 | `core.common.require_length_match` | `internal-only` | internal utility; module is imported as internal `com` helper, not as a public function spelling. |
| 12 | `core.computation.expr.BaseExprVisitor.visit_Module` | `internal-only` | internal visitor method; owner imports are computation internals and tests only. |
| 13 | `core.computation.pytables.UnaryOp.prune` | `internal-only` | internal computation method; no exact or owner public import declaration. |
| 14 | `core.dtypes.common._get_dtype` | `internal-only` | private helper by name; no public import declaration. |
| 15 | `core.generic.NDFrame._rename` | `internal-only` | internal base-class method; `NDFrame` is imported by internal/type modules, but pandas does not declare `NDFrame` as a public owner spelling. |
| 16 | `core.generic.NDFrame.pct_change` | `internal-only` | internal base-class method; `NDFrame` is imported by internal/type modules, but pandas does not declare `NDFrame` as a public owner spelling. |
| 17 | `core.groupby.ops.WrappedCythonOp._validate_axis` | `internal-only` | internal operation helper; owner imports are internal array/groupby consumers only. |
| 18 | `core.indexes.api.union_indexes` | `internal-only` | internal API helper; exact imports are internal construction/concat consumers, not a package public alias. |
| 19 | `core.indexes.base._validate_join_method` | `internal-only` | private helper by name; no public import declaration. |
| 20 | `core.internals.blocks.check_ndim` | `internal-only` | internal blocks validator; imported by `core.internals.api`, but not exported by a public package alias. |
| 21 | `core.resample._asfreq_compat` | `internal-only` | private helper by name; imported only by tests outside its defining module. |
| 22 | `core.tools.times.to_time` | `internal-only` | internal conversion helper; imported by internal arrays/indexes modules and tests, with no top-level `pandas.to_time` declaration. |
| 23 | `core.window.ewm.OnlineExponentialMovingWindow.__init__` | `internal-only` | internal EWM subclass constructor; no public owner import declaration. |
| 24 | `core.window.rolling.BaseWindow._apply_tablewise` | `internal-only` | internal base-window method; owner imports are internal typing/apply/EWM consumers only. |
| 25 | `core.window.rolling.RollingAndExpandingMixin.corr` | `internal-only` | internal mixin method; owner imports are internal expanding-window consumers only. |
| 26 | `core.window.rolling.RollingAndExpandingMixin.cov` | `internal-only` | internal mixin method; owner imports are internal expanding-window consumers only. |
| 27 | `util._validators._check_arg_length` | `internal-only` | private utility by name; no public import declaration. |

## Notes

- The source-side identity rule remains exact: only vendor-authored same-package imports rooted at non-private package `__init__.py` public aliases establish public spellings.
- Internal module imports, test imports, type-checking imports, private names, and dynamic `__getattr__` shims do not create consumer-facing public identities.
- The tail classification found no deeper declared public idiom to add in this lane, so the remap count stays `41/68`.

## Next Lane Spec

The next implication-potential measurement needs a report run that emits call edges. On this receipt the first blocker is `ArrayLiteral.contains(SymbolicValue)` membership construction, followed by two string binary-operation floors, one constructor-bound method row, and one assertion statement sugar row. Once those lower to report rows, re-run this audit and replace the `report-json-unavailable` call-edge statuses with resolved/dangling/none and minted yes/no.

The machine-readable companion is `docs/audits/pandas-implication-potential.json`.
