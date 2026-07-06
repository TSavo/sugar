# Pandas Re-Export Idioms

Part of #3503. This is the source-side identity mapping receipt for pandas pre-bearing contracts. It extends the public re-export measurement from `docs/audits/pandas-implication-potential.*`; the report side remains blocked by construction gaps.

## Summary

| item | value |
| --- | ---: |
| `preBearingContracts` | `68` |
| `beforeRemapped` | `0` |
| `afterRemapped` | `41` |
| `unmapped` | `27` |
| `directMappings` | `3` |
| `memberMappings` | `38` |

## Idiom Counts

| idiom | count | examples |
| --- | ---: | --- |
| `pandas.api package namespace` | 8 | `core.arrays.base.ExtensionArray._rank` -> `pandas.api.extensions.ExtensionArray._rank`<br>`core.arrays.base.ExtensionArray.view` -> `pandas.api.extensions.ExtensionArray.view`<br>`core.groupby.generic.DataFrameGroupBy._aggregate_frame` -> `pandas.api.typing.DataFrameGroupBy._aggregate_frame` |
| `subpackage __init__ namespace` | 17 | `core.arrays.arrow.array.ArrowExtensionArray._dt_tz_convert` -> `pandas.arrays.ArrowExtensionArray._dt_tz_convert`<br>`core.arrays.arrow.array.ArrowExtensionArray._round_temporally` -> `pandas.arrays.ArrowExtensionArray._round_temporally`<br>`core.arrays.masked.BaseMaskedArray._rank` -> `pandas.core.arrays.BaseMaskedArray._rank` |
| `top-level __init__ aggregator chain` | 16 | `core.arrays.categorical.Categorical._rank` -> `pandas.Categorical._rank`<br>`core.frame.DataFrame.map` -> `pandas.DataFrame.map`<br>`core.frame.DataFrame.to_stata` -> `pandas.DataFrame.to_stata` |
| `unmapped` | 27 | `core.apply.Apply.apply_list_or_dict_like`<br>`core.arrays._mixins.NDArrayBackedExtensionArray.value_counts`<br>`core.arrays.datetimelike.DatetimeLikeArrayMixin._accumulate` |

## Acceptance Table

| # | contract | before | after | idiom | mapping kind | locus |
| ---: | --- | --- | --- | --- | --- | --- |
| 1 | `core.arrays.base.ExtensionArray._rank` | `core.arrays.base.ExtensionArray._rank` | `pandas.api.extensions.ExtensionArray._rank` | `pandas.api package namespace` | `member` | `core/arrays/base.py:2610:1` |
| 2 | `core.arrays.base.ExtensionArray.view` | `core.arrays.base.ExtensionArray.view` | `pandas.api.extensions.ExtensionArray.view` | `pandas.api package namespace` | `member` | `core/arrays/base.py:2018:1` |
| 3 | `core.groupby.generic.DataFrameGroupBy._aggregate_frame` | `core.groupby.generic.DataFrameGroupBy._aggregate_frame` | `pandas.api.typing.DataFrameGroupBy._aggregate_frame` | `pandas.api package namespace` | `member` | `core/groupby/generic.py:2385:1` |
| 4 | `core.indexers.objects.VariableOffsetWindowIndexer.get_window_bounds` | `core.indexers.objects.VariableOffsetWindowIndexer.get_window_bounds` | `pandas.api.indexers.VariableOffsetWindowIndexer.get_window_bounds` | `pandas.api package namespace` | `member` | `core/indexers/objects.py:296:1` |
| 5 | `core.resample.TimeGrouper.__init__` | `core.resample.TimeGrouper.__init__` | `pandas.api.typing.TimeGrouper` | `pandas.api package namespace` | `member` | `core/resample.py:2385:1` |
| 6 | `core.window.ewm.ExponentialMovingWindow.corr` | `core.window.ewm.ExponentialMovingWindow.corr` | `pandas.api.typing.ExponentialMovingWindow.corr` | `pandas.api package namespace` | `member` | `core/window/ewm.py:887:1` |
| 7 | `core.window.ewm.ExponentialMovingWindow.cov` | `core.window.ewm.ExponentialMovingWindow.cov` | `pandas.api.typing.ExponentialMovingWindow.cov` | `pandas.api package namespace` | `member` | `core/window/ewm.py:795:1` |
| 8 | `core.window.ewm.ExponentialMovingWindow.var` | `core.window.ewm.ExponentialMovingWindow.var` | `pandas.api.typing.ExponentialMovingWindow.var` | `pandas.api package namespace` | `member` | `core/window/ewm.py:746:1` |
| 9 | `core.arrays.arrow.array.ArrowExtensionArray._dt_tz_convert` | `core.arrays.arrow.array.ArrowExtensionArray._dt_tz_convert` | `pandas.arrays.ArrowExtensionArray._dt_tz_convert` | `subpackage __init__ namespace` | `member` | `core/arrays/arrow/array.py:3263:1` |
| 10 | `core.arrays.arrow.array.ArrowExtensionArray._round_temporally` | `core.arrays.arrow.array.ArrowExtensionArray._round_temporally` | `pandas.arrays.ArrowExtensionArray._round_temporally` | `subpackage __init__ namespace` | `member` | `core/arrays/arrow/array.py:3150:1` |
| 11 | `core.arrays.masked.BaseMaskedArray._rank` | `core.arrays.masked.BaseMaskedArray._rank` | `pandas.core.arrays.BaseMaskedArray._rank` | `subpackage __init__ namespace` | `member` | `core/arrays/masked.py:1124:1` |
| 12 | `core.arrays.sparse.array.SparseArray.fillna` | `core.arrays.sparse.array.SparseArray.fillna` | `pandas.arrays.SparseArray.fillna` | `subpackage __init__ namespace` | `member` | `core/arrays/sparse/array.py:796:1` |
| 13 | `core.groupby.groupby.GroupBy.pct_change` | `core.groupby.groupby.GroupBy.pct_change` | `pandas.core.groupby.GroupBy.pct_change` | `subpackage __init__ namespace` | `member` | `core/groupby/groupby.py:5741:1` |
| 14 | `core.internals.managers.SingleBlockManager.get_slice` | `core.internals.managers.SingleBlockManager.get_slice` | `pandas.core.internals.SingleBlockManager.get_slice` | `subpackage __init__ namespace` | `member` | `core/internals/managers.py:2161:1` |
| 15 | `io.formats.excel.ExcelFormatter._num2excel` | `io.formats.excel.ExcelFormatter._num2excel` | `pandas.io.formats.excel.ExcelFormatter._num2excel` | `subpackage __init__ namespace` | `member` | `io/formats/excel.py:878:1` |
| 16 | `io.formats.info.SeriesInfo.render` | `io.formats.info.SeriesInfo.render` | `pandas.io.formats.info.SeriesInfo.render` | `subpackage __init__ namespace` | `member` | `io/formats/info.py:365:1` |
| 17 | `io.parsers.python_parser.PythonParser._alert_malformed` | `io.parsers.python_parser.PythonParser._alert_malformed` | `pandas.io.parsers.python_parser.PythonParser._alert_malformed` | `subpackage __init__ namespace` | `member` | `io/parsers/python_parser.py:946:1` |
| 18 | `io.pytables.GenericFixed.validate_read` | `io.pytables.GenericFixed.validate_read` | `pandas.io.pytables.GenericFixed.validate_read` | `subpackage __init__ namespace` | `member` | `io/pytables.py:3033:1` |
| 19 | `io.sql.to_sql` | `io.sql.to_sql` | `pandas.io.sql.to_sql` | `subpackage __init__ namespace` | `member` | `io/sql.py:742:1` |
| 20 | `io.stata.StataNonCatValueLabel.__init__` | `io.stata.StataNonCatValueLabel.__init__` | `pandas.io.stata.StataNonCatValueLabel.__init__` | `subpackage __init__ namespace` | `member` | `io/stata.py:698:1` |
| 21 | `io.stata.StataStrLWriter.__init__` | `io.stata.StataStrLWriter.__init__` | `pandas.io.stata.StataStrLWriter.__init__` | `subpackage __init__ namespace` | `member` | `io/stata.py:3203:1` |
| 22 | `io.stata.StataValueLabel.__init__` | `io.stata.StataValueLabel.__init__` | `pandas.io.stata.StataValueLabel.__init__` | `subpackage __init__ namespace` | `member` | `io/stata.py:581:1` |
| 23 | `plotting._matplotlib.hist._grouped_plot` | `plotting._matplotlib.hist._grouped_plot` | `pandas.plotting._matplotlib.hist._grouped_plot` | `subpackage __init__ namespace` | `member` | `plotting/_matplotlib/hist.py:294:1` |
| 24 | `plotting._matplotlib.style._get_colors_from_color` | `plotting._matplotlib.style._get_colors_from_color` | `pandas.plotting._matplotlib.style._get_colors_from_color` | `subpackage __init__ namespace` | `member` | `plotting/_matplotlib/style.py:192:1` |
| 25 | `tseries.holiday.AbstractHolidayCalendar.holidays` | `tseries.holiday.AbstractHolidayCalendar.holidays` | `pandas.tseries.holiday.AbstractHolidayCalendar.holidays` | `subpackage __init__ namespace` | `member` | `tseries/holiday.py:496:1` |
| 26 | `core.arrays.categorical.Categorical._rank` | `core.arrays.categorical.Categorical._rank` | `pandas.Categorical._rank` | `top-level __init__ aggregator chain` | `member` | `core/arrays/categorical.py:2123:1` |
| 27 | `core.frame.DataFrame.map` | `core.frame.DataFrame.map` | `pandas.DataFrame.map` | `top-level __init__ aggregator chain` | `member` | `core/frame.py:12494:1` |
| 28 | `core.frame.DataFrame.to_stata` | `core.frame.DataFrame.to_stata` | `pandas.DataFrame.to_stata` | `top-level __init__ aggregator chain` | `member` | `core/frame.py:2665:1` |
| 29 | `core.indexes.base.Index._check_indexing_method` | `core.indexes.base.Index._check_indexing_method` | `pandas.Index._check_indexing_method` | `top-level __init__ aggregator chain` | `member` | `core/indexes/base.py:3840:1` |
| 30 | `core.indexes.base.Index._get_fill_indexer_searchsorted` | `core.indexes.base.Index._get_fill_indexer_searchsorted` | `pandas.Index._get_fill_indexer_searchsorted` | `top-level __init__ aggregator chain` | `member` | `core/indexes/base.py:3937:1` |
| 31 | `core.indexes.base.Index._validate_sort_keyword` | `core.indexes.base.Index._validate_sort_keyword` | `pandas.Index._validate_sort_keyword` | `top-level __init__ aggregator chain` | `member` | `core/indexes/base.py:2994:1` |
| 32 | `core.indexes.base.Index.dropna` | `core.indexes.base.Index.dropna` | `pandas.Index.dropna` | `top-level __init__ aggregator chain` | `member` | `core/indexes/base.py:2780:1` |
| 33 | `core.indexes.base.Index.get_slice_bound` | `core.indexes.base.Index.get_slice_bound` | `pandas.Index.get_slice_bound` | `top-level __init__ aggregator chain` | `member` | `core/indexes/base.py:6912:1` |
| 34 | `core.indexes.category.CategoricalIndex.reindex` | `core.indexes.category.CategoricalIndex.reindex` | `pandas.CategoricalIndex.reindex` | `top-level __init__ aggregator chain` | `member` | `core/indexes/category.py:420:1` |
| 35 | `core.indexes.multi.MultiIndex._partial_tup_index` | `core.indexes.multi.MultiIndex._partial_tup_index` | `pandas.MultiIndex._partial_tup_index` | `top-level __init__ aggregator chain` | `member` | `core/indexes/multi.py:3384:1` |
| 36 | `core.indexes.multi.MultiIndex._reorder_ilevels` | `core.indexes.multi.MultiIndex._reorder_ilevels` | `pandas.MultiIndex._reorder_ilevels` | `top-level __init__ aggregator chain` | `member` | `core/indexes/multi.py:3020:1` |
| 37 | `core.indexes.period.PeriodIndex._disallow_mismatched_indexing` | `core.indexes.period.PeriodIndex._disallow_mismatched_indexing` | `pandas.PeriodIndex._disallow_mismatched_indexing` | `top-level __init__ aggregator chain` | `member` | `core/indexes/period.py:516:1` |
| 38 | `core.reshape.pivot.crosstab` | `core.reshape.pivot.crosstab` | `pandas.crosstab` | `top-level __init__ aggregator chain` | `direct` | `core/reshape/pivot.py:919:1` |
| 39 | `io.parsers.readers.read_fwf` | `io.parsers.readers.read_fwf` | `pandas.read_fwf` | `top-level __init__ aggregator chain` | `direct` | `io/parsers/readers.py:1479:1` |
| 40 | `io.pytables.HDFStore.append` | `io.pytables.HDFStore.append` | `pandas.HDFStore.append` | `top-level __init__ aggregator chain` | `member` | `io/pytables.py:1290:1` |
| 41 | `io.pytables.read_hdf` | `io.pytables.read_hdf` | `pandas.read_hdf` | `top-level __init__ aggregator chain` | `direct` | `io/pytables.py:320:1` |
| 42 | `core.apply.Apply.apply_list_or_dict_like` | `core.apply.Apply.apply_list_or_dict_like` | `core.apply.Apply.apply_list_or_dict_like` | `unmapped` | `` | `core/apply.py:703:1` |
| 43 | `core.arrays._mixins.NDArrayBackedExtensionArray.value_counts` | `core.arrays._mixins.NDArrayBackedExtensionArray.value_counts` | `core.arrays._mixins.NDArrayBackedExtensionArray.value_counts` | `unmapped` | `` | `core/arrays/_mixins.py:468:1` |
| 44 | `core.arrays.datetimelike.DatetimeLikeArrayMixin._accumulate` | `core.arrays.datetimelike.DatetimeLikeArrayMixin._accumulate` | `core.arrays.datetimelike.DatetimeLikeArrayMixin._accumulate` | `unmapped` | `` | `core/arrays/datetimelike.py:1387:1` |
| 45 | `core.arrays.datetimelike.DatetimeLikeArrayMixin._add_timedelta_arraylike` | `core.arrays.datetimelike.DatetimeLikeArrayMixin._add_timedelta_arraylike` | `core.arrays.datetimelike.DatetimeLikeArrayMixin._add_timedelta_arraylike` | `unmapped` | `` | `core/arrays/datetimelike.py:1250:1` |
| 46 | `core.arrays.datetimelike.DatetimeLikeArrayMixin._sub_datetime_arraylike` | `core.arrays.datetimelike.DatetimeLikeArrayMixin._sub_datetime_arraylike` | `core.arrays.datetimelike.DatetimeLikeArrayMixin._sub_datetime_arraylike` | `unmapped` | `` | `core/arrays/datetimelike.py:1182:1` |
| 47 | `core.arrays.datetimelike.DatetimeLikeArrayMixin._sub_datetimelike_scalar` | `core.arrays.datetimelike.DatetimeLikeArrayMixin._sub_datetimelike_scalar` | `core.arrays.datetimelike.DatetimeLikeArrayMixin._sub_datetimelike_scalar` | `unmapped` | `` | `core/arrays/datetimelike.py:1163:1` |
| 48 | `core.arrays.datetimelike.TimelikeOps.as_unit` | `core.arrays.datetimelike.TimelikeOps.as_unit` | `core.arrays.datetimelike.TimelikeOps.as_unit` | `unmapped` | `` | `core/arrays/datetimelike.py:2010:1` |
| 49 | `core.arrays.datetimelike.TimelikeOps.interpolate` | `core.arrays.datetimelike.TimelikeOps.interpolate` | `core.arrays.datetimelike.TimelikeOps.interpolate` | `unmapped` | `` | `core/arrays/datetimelike.py:2538:1` |
| 50 | `core.arrays.string_.BaseStringArray.view` | `core.arrays.string_.BaseStringArray.view` | `core.arrays.string_.BaseStringArray.view` | `unmapped` | `` | `core/arrays/string_.py:602:1` |
| 51 | `core.base.SelectionMixin.__getitem__` | `core.base.SelectionMixin.__getitem__` | `core.base.SelectionMixin.__getitem__` | `unmapped` | `` | `core/base.py:216:1` |
| 52 | `core.common.require_length_match` | `core.common.require_length_match` | `core.common.require_length_match` | `unmapped` | `` | `core/common.py:596:1` |
| 53 | `core.computation.expr.BaseExprVisitor.visit_Module` | `core.computation.expr.BaseExprVisitor.visit_Module` | `core.computation.expr.BaseExprVisitor.visit_Module` | `unmapped` | `` | `core/computation/expr.py:422:1` |
| 54 | `core.computation.pytables.UnaryOp.prune` | `core.computation.pytables.UnaryOp.prune` | `core.computation.pytables.UnaryOp.prune` | `unmapped` | `` | `core/computation/pytables.py:418:1` |
| 55 | `core.dtypes.common._get_dtype` | `core.dtypes.common._get_dtype` | `core.dtypes.common._get_dtype` | `unmapped` | `` | `core/dtypes/common.py:1624:1` |
| 56 | `core.generic.NDFrame._rename` | `core.generic.NDFrame._rename` | `core.generic.NDFrame._rename` | `unmapped` | `` | `core/generic.py:1002:1` |
| 57 | `core.generic.NDFrame.pct_change` | `core.generic.NDFrame.pct_change` | `core.generic.NDFrame.pct_change` | `unmapped` | `` | `core/generic.py:11434:1` |
| 58 | `core.groupby.ops.WrappedCythonOp._validate_axis` | `core.groupby.ops.WrappedCythonOp._validate_axis` | `core.groupby.ops.WrappedCythonOp._validate_axis` | `unmapped` | `` | `core/groupby/ops.py:525:1` |
| 59 | `core.indexes.api.union_indexes` | `core.indexes.api.union_indexes` | `core.indexes.api.union_indexes` | `unmapped` | `` | `core/indexes/api.py:185:1` |
| 60 | `core.indexes.base._validate_join_method` | `core.indexes.base._validate_join_method` | `core.indexes.base._validate_join_method` | `unmapped` | `` | `core/indexes/base.py:7998:1` |
| 61 | `core.internals.blocks.check_ndim` | `core.internals.blocks.check_ndim` | `core.internals.blocks.check_ndim` | `unmapped` | `` | `core/internals/blocks.py:2273:1` |
| 62 | `core.resample._asfreq_compat` | `core.resample._asfreq_compat` | `core.resample._asfreq_compat` | `unmapped` | `` | `core/resample.py:3124:1` |
| 63 | `core.tools.times.to_time` | `core.tools.times.to_time` | `core.tools.times.to_time` | `unmapped` | `` | `core/tools/times.py:23:1` |
| 64 | `core.window.ewm.OnlineExponentialMovingWindow.__init__` | `core.window.ewm.OnlineExponentialMovingWindow.__init__` | `core.window.ewm.OnlineExponentialMovingWindow.__init__` | `unmapped` | `` | `core/window/ewm.py:1018:1` |
| 65 | `core.window.rolling.BaseWindow._apply_tablewise` | `core.window.rolling.BaseWindow._apply_tablewise` | `core.window.rolling.BaseWindow._apply_tablewise` | `unmapped` | `` | `core/window/rolling.py:491:1` |
| 66 | `core.window.rolling.RollingAndExpandingMixin.corr` | `core.window.rolling.RollingAndExpandingMixin.corr` | `core.window.rolling.RollingAndExpandingMixin.corr` | `unmapped` | `` | `core/window/rolling.py:1904:1` |
| 67 | `core.window.rolling.RollingAndExpandingMixin.cov` | `core.window.rolling.RollingAndExpandingMixin.cov` | `core.window.rolling.RollingAndExpandingMixin.cov` | `unmapped` | `` | `core/window/rolling.py:1857:1` |
| 68 | `util._validators._check_arg_length` | `util._validators._check_arg_length` | `util._validators._check_arg_length` | `unmapped` | `` | `util/_validators.py:31:1` |

## Notes

- The helper accepts only same-package imports declared by pandas source: relative imports or absolute `pandas.*` imports. Imports from other packages do not establish identity.
- Private public spellings such as `pandas._testing.*` are not used as canonical bridge spellings.
- A public owner re-export also carries member contracts by exact owner identity. For classes, the existing constructor rule is preserved: `Class.__init__` and `Class.__new__` map to the class symbol itself.
- Aliased from-imports and literal `__all__` star hops are pinned by focused tests even though the current 68-row pandas pre-bearing set does not require them.
