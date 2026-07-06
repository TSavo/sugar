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
- Identity finding: not yet a pandas re-export miss; the bridge cannot be evaluated until the report exposes call edges.
- Public spelling enrichment: `0/68` pre-bearing contracts remapped through the current source re-export map, so the table below carries canonical source spellings until a report-edge join can prove otherwise.

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

| # | contract | public spelling | locus | call-edge status | implication minted |
| ---: | --- | --- | --- | --- | --- |
| 1 | `core.apply.Apply.apply_list_or_dict_like` | `core.apply.Apply.apply_list_or_dict_like` | `core/apply.py:703:1` | `report-json-unavailable` | `false` |
| 2 | `core.arrays._mixins.NDArrayBackedExtensionArray.value_counts` | `core.arrays._mixins.NDArrayBackedExtensionArray.value_counts` | `core/arrays/_mixins.py:468:1` | `report-json-unavailable` | `false` |
| 3 | `core.arrays.arrow.array.ArrowExtensionArray._round_temporally` | `core.arrays.arrow.array.ArrowExtensionArray._round_temporally` | `core/arrays/arrow/array.py:3150:1` | `report-json-unavailable` | `false` |
| 4 | `core.arrays.arrow.array.ArrowExtensionArray._dt_tz_convert` | `core.arrays.arrow.array.ArrowExtensionArray._dt_tz_convert` | `core/arrays/arrow/array.py:3263:1` | `report-json-unavailable` | `false` |
| 5 | `core.arrays.base.ExtensionArray.view` | `core.arrays.base.ExtensionArray.view` | `core/arrays/base.py:2018:1` | `report-json-unavailable` | `false` |
| 6 | `core.arrays.base.ExtensionArray._rank` | `core.arrays.base.ExtensionArray._rank` | `core/arrays/base.py:2610:1` | `report-json-unavailable` | `false` |
| 7 | `core.arrays.categorical.Categorical._rank` | `core.arrays.categorical.Categorical._rank` | `core/arrays/categorical.py:2123:1` | `report-json-unavailable` | `false` |
| 8 | `core.arrays.datetimelike.DatetimeLikeArrayMixin._sub_datetimelike_scalar` | `core.arrays.datetimelike.DatetimeLikeArrayMixin._sub_datetimelike_scalar` | `core/arrays/datetimelike.py:1163:1` | `report-json-unavailable` | `false` |
| 9 | `core.arrays.datetimelike.DatetimeLikeArrayMixin._sub_datetime_arraylike` | `core.arrays.datetimelike.DatetimeLikeArrayMixin._sub_datetime_arraylike` | `core/arrays/datetimelike.py:1182:1` | `report-json-unavailable` | `false` |
| 10 | `core.arrays.datetimelike.DatetimeLikeArrayMixin._add_timedelta_arraylike` | `core.arrays.datetimelike.DatetimeLikeArrayMixin._add_timedelta_arraylike` | `core/arrays/datetimelike.py:1250:1` | `report-json-unavailable` | `false` |
| 11 | `core.arrays.datetimelike.DatetimeLikeArrayMixin._accumulate` | `core.arrays.datetimelike.DatetimeLikeArrayMixin._accumulate` | `core/arrays/datetimelike.py:1387:1` | `report-json-unavailable` | `false` |
| 12 | `core.arrays.datetimelike.TimelikeOps.as_unit` | `core.arrays.datetimelike.TimelikeOps.as_unit` | `core/arrays/datetimelike.py:2010:1` | `report-json-unavailable` | `false` |
| 13 | `core.arrays.datetimelike.TimelikeOps.interpolate` | `core.arrays.datetimelike.TimelikeOps.interpolate` | `core/arrays/datetimelike.py:2538:1` | `report-json-unavailable` | `false` |
| 14 | `core.arrays.masked.BaseMaskedArray._rank` | `core.arrays.masked.BaseMaskedArray._rank` | `core/arrays/masked.py:1124:1` | `report-json-unavailable` | `false` |
| 15 | `core.arrays.sparse.array.SparseArray.fillna` | `core.arrays.sparse.array.SparseArray.fillna` | `core/arrays/sparse/array.py:796:1` | `report-json-unavailable` | `false` |
| 16 | `core.arrays.string_.BaseStringArray.view` | `core.arrays.string_.BaseStringArray.view` | `core/arrays/string_.py:602:1` | `report-json-unavailable` | `false` |
| 17 | `core.base.SelectionMixin.__getitem__` | `core.base.SelectionMixin.__getitem__` | `core/base.py:216:1` | `report-json-unavailable` | `false` |
| 18 | `core.common.require_length_match` | `core.common.require_length_match` | `core/common.py:596:1` | `report-json-unavailable` | `false` |
| 19 | `core.computation.expr.BaseExprVisitor.visit_Module` | `core.computation.expr.BaseExprVisitor.visit_Module` | `core/computation/expr.py:422:1` | `report-json-unavailable` | `false` |
| 20 | `core.computation.pytables.UnaryOp.prune` | `core.computation.pytables.UnaryOp.prune` | `core/computation/pytables.py:418:1` | `report-json-unavailable` | `false` |
| 21 | `core.dtypes.common._get_dtype` | `core.dtypes.common._get_dtype` | `core/dtypes/common.py:1624:1` | `report-json-unavailable` | `false` |
| 22 | `core.frame.DataFrame.to_stata` | `core.frame.DataFrame.to_stata` | `core/frame.py:2665:1` | `report-json-unavailable` | `false` |
| 23 | `core.frame.DataFrame.map` | `core.frame.DataFrame.map` | `core/frame.py:12494:1` | `report-json-unavailable` | `false` |
| 24 | `core.generic.NDFrame._rename` | `core.generic.NDFrame._rename` | `core/generic.py:1002:1` | `report-json-unavailable` | `false` |
| 25 | `core.generic.NDFrame.pct_change` | `core.generic.NDFrame.pct_change` | `core/generic.py:11434:1` | `report-json-unavailable` | `false` |
| 26 | `core.groupby.generic.DataFrameGroupBy._aggregate_frame` | `core.groupby.generic.DataFrameGroupBy._aggregate_frame` | `core/groupby/generic.py:2385:1` | `report-json-unavailable` | `false` |
| 27 | `core.groupby.groupby.GroupBy.pct_change` | `core.groupby.groupby.GroupBy.pct_change` | `core/groupby/groupby.py:5741:1` | `report-json-unavailable` | `false` |
| 28 | `core.groupby.ops.WrappedCythonOp._validate_axis` | `core.groupby.ops.WrappedCythonOp._validate_axis` | `core/groupby/ops.py:525:1` | `report-json-unavailable` | `false` |
| 29 | `core.indexers.objects.VariableOffsetWindowIndexer.get_window_bounds` | `core.indexers.objects.VariableOffsetWindowIndexer.get_window_bounds` | `core/indexers/objects.py:296:1` | `report-json-unavailable` | `false` |
| 30 | `core.indexes.api.union_indexes` | `core.indexes.api.union_indexes` | `core/indexes/api.py:185:1` | `report-json-unavailable` | `false` |
| 31 | `core.indexes.base.Index.dropna` | `core.indexes.base.Index.dropna` | `core/indexes/base.py:2780:1` | `report-json-unavailable` | `false` |
| 32 | `core.indexes.base.Index._validate_sort_keyword` | `core.indexes.base.Index._validate_sort_keyword` | `core/indexes/base.py:2994:1` | `report-json-unavailable` | `false` |
| 33 | `core.indexes.base.Index._check_indexing_method` | `core.indexes.base.Index._check_indexing_method` | `core/indexes/base.py:3840:1` | `report-json-unavailable` | `false` |
| 34 | `core.indexes.base.Index._get_fill_indexer_searchsorted` | `core.indexes.base.Index._get_fill_indexer_searchsorted` | `core/indexes/base.py:3937:1` | `report-json-unavailable` | `false` |
| 35 | `core.indexes.base.Index.get_slice_bound` | `core.indexes.base.Index.get_slice_bound` | `core/indexes/base.py:6912:1` | `report-json-unavailable` | `false` |
| 36 | `core.indexes.base._validate_join_method` | `core.indexes.base._validate_join_method` | `core/indexes/base.py:7998:1` | `report-json-unavailable` | `false` |
| 37 | `core.indexes.category.CategoricalIndex.reindex` | `core.indexes.category.CategoricalIndex.reindex` | `core/indexes/category.py:420:1` | `report-json-unavailable` | `false` |
| 38 | `core.indexes.multi.MultiIndex._reorder_ilevels` | `core.indexes.multi.MultiIndex._reorder_ilevels` | `core/indexes/multi.py:3020:1` | `report-json-unavailable` | `false` |
| 39 | `core.indexes.multi.MultiIndex._partial_tup_index` | `core.indexes.multi.MultiIndex._partial_tup_index` | `core/indexes/multi.py:3384:1` | `report-json-unavailable` | `false` |
| 40 | `core.indexes.period.PeriodIndex._disallow_mismatched_indexing` | `core.indexes.period.PeriodIndex._disallow_mismatched_indexing` | `core/indexes/period.py:516:1` | `report-json-unavailable` | `false` |
| 41 | `core.internals.blocks.check_ndim` | `core.internals.blocks.check_ndim` | `core/internals/blocks.py:2273:1` | `report-json-unavailable` | `false` |
| 42 | `core.internals.managers.SingleBlockManager.get_slice` | `core.internals.managers.SingleBlockManager.get_slice` | `core/internals/managers.py:2161:1` | `report-json-unavailable` | `false` |
| 43 | `core.resample.TimeGrouper.__init__` | `core.resample.TimeGrouper.__init__` | `core/resample.py:2385:1` | `report-json-unavailable` | `false` |
| 44 | `core.resample._asfreq_compat` | `core.resample._asfreq_compat` | `core/resample.py:3124:1` | `report-json-unavailable` | `false` |
| 45 | `core.reshape.pivot.crosstab` | `core.reshape.pivot.crosstab` | `core/reshape/pivot.py:919:1` | `report-json-unavailable` | `false` |
| 46 | `core.tools.times.to_time` | `core.tools.times.to_time` | `core/tools/times.py:23:1` | `report-json-unavailable` | `false` |
| 47 | `core.window.ewm.ExponentialMovingWindow.var` | `core.window.ewm.ExponentialMovingWindow.var` | `core/window/ewm.py:746:1` | `report-json-unavailable` | `false` |
| 48 | `core.window.ewm.ExponentialMovingWindow.cov` | `core.window.ewm.ExponentialMovingWindow.cov` | `core/window/ewm.py:795:1` | `report-json-unavailable` | `false` |
| 49 | `core.window.ewm.ExponentialMovingWindow.corr` | `core.window.ewm.ExponentialMovingWindow.corr` | `core/window/ewm.py:887:1` | `report-json-unavailable` | `false` |
| 50 | `core.window.ewm.OnlineExponentialMovingWindow.__init__` | `core.window.ewm.OnlineExponentialMovingWindow.__init__` | `core/window/ewm.py:1018:1` | `report-json-unavailable` | `false` |
| 51 | `core.window.rolling.BaseWindow._apply_tablewise` | `core.window.rolling.BaseWindow._apply_tablewise` | `core/window/rolling.py:491:1` | `report-json-unavailable` | `false` |
| 52 | `core.window.rolling.RollingAndExpandingMixin.cov` | `core.window.rolling.RollingAndExpandingMixin.cov` | `core/window/rolling.py:1857:1` | `report-json-unavailable` | `false` |
| 53 | `core.window.rolling.RollingAndExpandingMixin.corr` | `core.window.rolling.RollingAndExpandingMixin.corr` | `core/window/rolling.py:1904:1` | `report-json-unavailable` | `false` |
| 54 | `io.formats.excel.ExcelFormatter._num2excel` | `io.formats.excel.ExcelFormatter._num2excel` | `io/formats/excel.py:878:1` | `report-json-unavailable` | `false` |
| 55 | `io.formats.info.SeriesInfo.render` | `io.formats.info.SeriesInfo.render` | `io/formats/info.py:365:1` | `report-json-unavailable` | `false` |
| 56 | `io.parsers.python_parser.PythonParser._alert_malformed` | `io.parsers.python_parser.PythonParser._alert_malformed` | `io/parsers/python_parser.py:946:1` | `report-json-unavailable` | `false` |
| 57 | `io.parsers.readers.read_fwf` | `io.parsers.readers.read_fwf` | `io/parsers/readers.py:1479:1` | `report-json-unavailable` | `false` |
| 58 | `io.pytables.read_hdf` | `io.pytables.read_hdf` | `io/pytables.py:320:1` | `report-json-unavailable` | `false` |
| 59 | `io.pytables.HDFStore.append` | `io.pytables.HDFStore.append` | `io/pytables.py:1290:1` | `report-json-unavailable` | `false` |
| 60 | `io.pytables.GenericFixed.validate_read` | `io.pytables.GenericFixed.validate_read` | `io/pytables.py:3033:1` | `report-json-unavailable` | `false` |
| 61 | `io.sql.to_sql` | `io.sql.to_sql` | `io/sql.py:742:1` | `report-json-unavailable` | `false` |
| 62 | `io.stata.StataValueLabel.__init__` | `io.stata.StataValueLabel.__init__` | `io/stata.py:581:1` | `report-json-unavailable` | `false` |
| 63 | `io.stata.StataNonCatValueLabel.__init__` | `io.stata.StataNonCatValueLabel.__init__` | `io/stata.py:698:1` | `report-json-unavailable` | `false` |
| 64 | `io.stata.StataStrLWriter.__init__` | `io.stata.StataStrLWriter.__init__` | `io/stata.py:3203:1` | `report-json-unavailable` | `false` |
| 65 | `plotting._matplotlib.hist._grouped_plot` | `plotting._matplotlib.hist._grouped_plot` | `plotting/_matplotlib/hist.py:294:1` | `report-json-unavailable` | `false` |
| 66 | `plotting._matplotlib.style._get_colors_from_color` | `plotting._matplotlib.style._get_colors_from_color` | `plotting/_matplotlib/style.py:192:1` | `report-json-unavailable` | `false` |
| 67 | `tseries.holiday.AbstractHolidayCalendar.holidays` | `tseries.holiday.AbstractHolidayCalendar.holidays` | `tseries/holiday.py:496:1` | `report-json-unavailable` | `false` |
| 68 | `util._validators._check_arg_length` | `util._validators._check_arg_length` | `util/_validators.py:31:1` | `report-json-unavailable` | `false` |

## Next Lane Spec

The next implication-potential measurement needs a report run that emits call edges. On this receipt the first blocker is `ArrayLiteral.contains(SymbolicValue)` membership construction, followed by two string binary-operation floors, one constructor-bound method row, and one assertion statement sugar row. Once those lower to report rows, re-run this audit and replace the `report-json-unavailable` call-edge statuses with resolved/dangling/none and minted yes/no.

The machine-readable companion is `docs/audits/pandas-implication-potential.json`.
