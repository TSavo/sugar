# Pandas Gap Census

Part of #3503. This is the shared pandas wall payload for sibling drain lanes; it is a census and work-list, not a recognizer change.

## Render Receipt

| item | value |
| --- | --- |
| command | `/Users/tsavo/.cache/sugar/binaries/sugar-darwin-x86_64-release-blake3-512_71db7fb178cb95914ca9f45266f5de5551d88e74b12a3cf0080cbd696dceffb7bf228affcf3a0bc5ddc190050cd12929982f626670fdb9efccad96ce2b490091 lift --report --json /Users/tsavo/.cache/sugar/python-panic-audit-workspaces/e14a41e91240eb8f3232be7fb66e9b4999a19aee9458c920644ea3213f201ad7/pandas` |
| exit code | `2` |
| runtime | `511.13s` |
| pandas version | `3.0.3` |
| cached workspace | `/Users/tsavo/.cache/sugar/python-panic-audit-workspaces/e14a41e91240eb8f3232be7fb66e9b4999a19aee9458c920644ea3213f201ad7/pandas` |
| Python files | `1421` |
| stdout bytes / SHA-256 | `0` / `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| stderr bytes / SHA-256 | `113919` / `554e254980365bfd35b576cd4edf6cc90315c4919b22069b5221008574cba7ca` |
| sugar binary | `/Users/tsavo/.cache/sugar/binaries/sugar-darwin-x86_64-release-blake3-512_71db7fb178cb95914ca9f45266f5de5551d88e74b12a3cf0080cbd696dceffb7bf228affcf3a0bc5ddc190050cd12929982f626670fdb9efccad96ce2b490091` |
| binary file receipt | `/Users/tsavo/.cache/sugar/binaries/sugar-darwin-x86_64-release-blake3-512_71db7fb178cb95914ca9f45266f5de5551d88e74b12a3cf0080cbd696dceffb7bf228affcf3a0bc5ddc190050cd12929982f626670fdb9efccad96ce2b490091: Mach-O 64-bit executable x86_64` |

The prior frontier note expected 65 rows. This current-main re-render produced 68 audit-only construction gaps; this document preserves the live payload rather than smoothing it to the older number.

## R Vector

| bucket | count |
| --- | ---: |
| `Constructor` | 1 |
| `Floor` | 49 |
| `ProofIR` | 1 |
| `Sugar` | 17 |
| **Total** | **68** |

## Shape Templates

| id | bucket | count | template | examples | closest precedent |
| --- | --- | ---: | --- | --- | --- |
| `pandas-gap-01-floor-membershipassertionsugar-arrayliteral-contains-symbolicvalue-contains-item-floor` | `Floor` | 10 | owner `MembershipAssertionSugar`; observed `ArrayLiteral.contains(SymbolicValue)`; requested `contains item floor`; replacement `add contains support for ArrayLiteral with SymbolicValue` | `pandas/core/apply.py:1652:8` (label `pandas/core/apply.py`)<br>`pandas/core/arrays/_ranges.py:127:4` (label `pandas/core/arrays/_ranges.py`) | ContainsOperation currently handles ArrayLiteral.contains(TermValue) and symbolic/string/set contains at operations/contains_operation.py:35-100; ArrayLiteral dispatches contains_with at floor/array_literal.py:53-54. |
| `pandas-gap-02-sugar-python-factory-generatorexp-term` | `Sugar` | 8 | owner `python.factory`; observed `GeneratorExp`; requested `term`; replacement `create sugar_lift_py_tests.sugar.generator_exp.generator_exp_sugar` | `pandas/io/pytables.py:4124:18` (label `pandas/io/pytables.py`)<br>`pandas/tests/arrays/sparse/test_constructors.py:80:13` (label `pandas/tests/arrays/sparse/test_constructors.py`) | Factory gaps are raised by factory/build.py:125-142; grammar_ledger.py:369-372 classifies GeneratorExp as lazy sequence-universe debt. |
| `pandas-gap-03-floor-arrayliteralsugar-dictliteralvalue-array-element-floor` | `Floor` | 6 | owner `ArrayLiteralSugar`; observed `DictLiteralValue`; requested `array element floor`; replacement `add ArrayLiteral element floor for DictLiteralValue` | `pandas/tests/frame/methods/test_to_dict.py:37:28` (label `pandas/tests/frame/methods/test_to_dict.py`)<br>`pandas/tests/groupby/test_groupby.py:2150:20` (label `pandas/tests/groupby/test_groupby.py`) | ArrayLiteral item admissibility is declared at floor/array_literal.py:17-22; DictLiteralValue is a non-FOL support carrier with to_term/project_callsite at floor/dict_literal_value.py:13-47. |
| `pandas-gap-04-floor-binopsugar-stringvalue-termvalue-binary-operator-operand-floor` | `Floor` | 5 | owner `BinOpSugar`; observed `StringValue*TermValue`; requested `binary operator operand floor`; replacement `add BinaryOperatorOperation support for StringValue * TermValue` | `pandas/tests/indexes/multi/test_formats.py:201:40` (label `pandas/tests/indexes/multi/test_formats.py`)<br>`pandas/tests/io/formats/test_format.py:273:25` (label `pandas/tests/io/formats/test_format.py`) | BinaryOperatorOperation handles TermValue, SymbolicValue, StringValue equality, ArrayLiteral/TupleLiteral repeat, and gaps at operations/binary_operator_operation.py:52-113 and :243-267. |
| `pandas-gap-05-floor-builtincallsugar-stringvalue-dunder-floatdunder-string-builtin-method-floor` | `Floor` | 5 | owner `BuiltinCallSugar`; observed `StringValue.__float__`; requested `string builtin method floor`; replacement `add StringValue method floor for `__float__`` | `pandas/tests/arrays/string_/test_string.py:55:56` (label `pandas/tests/arrays/string_/test_string.py`)<br>`pandas/tests/indexes/period/test_indexing.py:783:15` (label `pandas/tests/indexes/period/test_indexing.py`) | BuiltinCallSugar maps float() to __float__ at sugar/builtin_call_sugar.py:351-367; StringValue only owns __int__ and __format__ at floor/string_value.py:21-40. |
| `pandas-gap-06-sugar-python-factory-compare-term` | `Sugar` | 5 | owner `python.factory`; observed `Compare`; requested `term`; replacement `create sugar_lift_py_tests.sugar.compare.compare_sugar` | `pandas/tests/api/test_api.py:555:14` (label `pandas/tests/api/test_api.py`)<br>`pandas/tests/arrays/categorical/test_indexing.py:318:17` (label `pandas/tests/arrays/categorical/test_indexing.py`) | ComparisonAssertionSugar and ChainedComparisonAssertionSugar own assertion compares; ObjectRichComparisonTermSugar is the existing term-compare precedent at sugar/object_rich_comparison_term_sugar.py:27-92. |
| `pandas-gap-07-floor-stringsubscriptsugar-dictliteralvalue-subscript-with` | `Floor` | 4 | owner `StringSubscriptSugar`; observed `DictLiteralValue`; requested `subscript_with`; replacement `add subscript_with to DictLiteralValue or emit a real effect` | `pandas/tests/frame/test_query_eval.py:180:61` (label `pandas/tests/frame/test_query_eval.py`)<br>`pandas/tests/scalar/test_na_scalar.py:54:11` (label `pandas/tests/scalar/test_na_scalar.py`) | SubscriptOperation has String/Array/Tuple/Object/Symbolic arms at operations/subscript_operation.py:41-108; DictLiteralValue currently has no subscript_with arm at floor/dict_literal_value.py:13-47. |
| `pandas-gap-08-floor-membershipassertionsugar-tupleliteralvalue-contains-with` | `Floor` | 3 | owner `MembershipAssertionSugar`; observed `TupleLiteralValue`; requested `contains_with`; replacement `add contains_with to TupleLiteralValue or emit a real effect` | `pandas/core/interchange/from_dataframe.py:332:4` (label `pandas/core/interchange/from_dataframe.py`)<br>`pandas/tests/io/test_sql.py:382:4` (label `pandas/tests/io/test_sql.py`) | TupleLiteralValue dispatches binary/subscript/materialize/project but no contains_with at floor/tuple_literal_value.py:22-50; ContainsOperation is the membership precedent. |
| `pandas-gap-09-floor-attributesugar-callsitevalue-attribute-with` | `Floor` | 2 | owner `AttributeSugar`; observed `CallSiteValue`; requested `attribute_with`; replacement `add attribute_with to CallSiteValue or emit a real effect` | `pandas/tests/arrays/integer/test_construction.py:171:11` (label `pandas/tests/arrays/integer/test_construction.py`)<br>`pandas/tests/tseries/offsets/test_offsets.py:950:11` (label `pandas/tests/tseries/offsets/test_offsets.py`) | AttributeLookupOperation owns ObjectValue attribute semantics at operations/attribute_lookup_operation.py:28-78; CallSiteValue can force/project calls at floor/call_site_value.py:37-142 but has no attribute_with arm. |
| `pandas-gap-10-floor-binopsugar-arrayliteral-arrayliteral-binary-operator-operand-floor` | `Floor` | 2 | owner `BinOpSugar`; observed `ArrayLiteral+ArrayLiteral`; requested `binary operator operand floor`; replacement `add BinaryOperatorOperation support for ArrayLiteral + ArrayLiteral` | `pandas/tests/frame/test_stack_unstack.py:883:23` (label `pandas/tests/frame/test_stack_unstack.py`)<br>`pandas/tests/window/test_groupby.py:856:23` (label `pandas/tests/window/test_groupby.py`) | ArrayLiteral dispatches binary_operator_with at floor/array_literal.py:35-36; BinaryOperatorOperation currently only repeats arrays by TermValue or reports symbolic repeat effects at operations/binary_operator_operation.py:107-113. |
| `pandas-gap-11-floor-binopsugar-symbolicvalue-stringvalue-binary-operator-operand-floor` | `Floor` | 2 | owner `BinOpSugar`; observed `SymbolicValue+StringValue`; requested `binary operator operand floor`; replacement `add BinaryOperatorOperation support for SymbolicValue + StringValue` | `pandas/tests/arithmetic/test_object.py:291:17` (label `pandas/tests/arithmetic/test_object.py`)<br>`pandas/tests/indexes/datetimes/methods/test_tz_convert.py:59:41` (label `pandas/tests/indexes/datetimes/methods/test_tz_convert.py`) | BinaryOperatorOperation supports SymbolicValue with TermValue/SymbolicValue and StringValue equality only at operations/binary_operator_operation.py:87-98. |
| `pandas-gap-12-floor-mapsugar-symbolicvalue-map-with` | `Floor` | 2 | owner `MapSugar`; observed `SymbolicValue`; requested `map_with`; replacement `add map_with to SymbolicValue or emit a real effect` | `pandas/tests/io/formats/style/test_style.py:520:12` (label `pandas/tests/io/formats/style/test_style.py`)<br>`pandas/tests/series/methods/test_map.py:278:13` (label `pandas/tests/series/methods/test_map.py`) | MapSugar requires a LambdaCallable mapper then dispatches map_with at sugar/map_sugar.py:59-78; ArrayLiteral maps via CallableMapOperation at operations/callable_map_operation.py:10-28. |
| `pandas-gap-13-floor-literal-call-report-kw-float-format-lambdacallable-project-this-floor-value-to-a-term` | `Floor` | 2 | owner `literal_call_report kw:float_format`; observed `LambdaCallable`; requested `project this floor value to a term`; replacement `write more Floor: implement LambdaCallable.to_term` | `LambdaCallable` (label `pandas/tests/frame/methods/test_to_csv.py`)<br>`LambdaCallable` (label `pandas/tests/io/formats/test_to_csv.py`) | literal_call_report projects keyword values through floor_to_term at factory/literal_call_report.py:1660; LambdaCallable intentionally only applies a body, with no to_term, at floor/lambda_callable.py:11-31. |
| `pandas-gap-14-constructor-attributesugar-t-a-constructor-bound-field` | `Constructor` | 1 | owner `AttributeSugar`; observed `T.a`; requested `constructor-bound field`; replacement `bind `self.a` in `T.__init__`, define `__getattr__` on `T`, or add the floor that owns this attribute` | `pandas/tests/base/test_constructors.py:110:15` (label `pandas/tests/base/test_constructors.py`) | AttributeLookupOperation reports constructor-bound field gaps when ObjectValue lacks the field and __getattr__ at operations/attribute_lookup_operation.py:39-78. |
| `pandas-gap-15-floor-callsugar-stringvalue-format-string-builtin-method-floor` | `Floor` | 1 | owner `CallSugar`; observed `StringValue.format`; requested `string builtin method floor`; replacement `add StringValue method floor for `format`` | `pandas/tests/io/formats/style/test_html.py:833:11` (label `pandas/tests/io/formats/style/test_html.py`) | Builtin format() routes to __format__ at sugar/builtin_call_sugar.py:288-348 and StringValue owns __format__; method-call .format currently reaches StringValue.call_method_with at floor/string_value.py:21-40. |
| `pandas-gap-16-floor-membershipassertionsugar-importaliasvalue-contains-with` | `Floor` | 1 | owner `MembershipAssertionSugar`; observed `ImportAliasValue`; requested `contains_with`; replacement `add contains_with to ImportAliasValue or emit a real effect` | `pandas/core/arrays/arrow/extension_types.py:66:8` (label `pandas/core/arrays/arrow/extension_types.py`) | ContainsOperation is the membership dispatch precedent at operations/contains_operation.py:35-100; ImportAliasValue exposes to_term/subscript but no contains_with. |
| `pandas-gap-17-floor-stringsubscriptsugar-arrayliteral-1-bounds-safe-sequence-subscript` | `Floor` | 1 | owner `StringSubscriptSugar`; observed `ArrayLiteral[-1]`; requested `bounds-safe sequence subscript`; replacement `add bounds-safe projection support for ArrayLiteral` | `pandas/tests/config/test_config.py:366:15` (label `pandas/tests/config/test_config.py`) | SubscriptOperation sequence projection currently accepts only 0 <= index < len(items) and gaps otherwise at operations/subscript_operation.py:111-137. |
| `pandas-gap-18-floor-subscriptassignsugar-symbolicvalue-setitem-with` | `Floor` | 1 | owner `SubscriptAssignSugar`; observed `SymbolicValue`; requested `setitem_with`; replacement `add setitem_with to SymbolicValue or emit a real effect` | `pandas/tests/copy_view/test_methods.py:1503:8` (label `pandas/tests/copy_view/test_methods.py`) | SetItemOperation owns array/object assignment at operations/setitem_operation.py:33-87; SymbolicValue has no setitem_with arm. |
| `pandas-gap-19-floor-unaryopsugar-callsitevalue-unary-operator-with` | `Floor` | 1 | owner `UnaryOpSugar`; observed `CallSiteValue`; requested `unary_operator_with`; replacement `add unary_operator_with to CallSiteValue or emit a real effect` | `pandas/tests/scalar/timedelta/test_timedelta.py:521:35` (label `pandas/tests/scalar/timedelta/test_timedelta.py`) | UnaryOperatorOperation handles TermValue/SymbolicValue only at operations/unary_operator_operation.py:26-47; CallSiteValue can be forced/projected at floor/call_site_value.py:37-142. |
| `pandas-gap-20-floor-unaryopsugar-py-invert-termvalue-unary-operator-floor` | `Floor` | 1 | owner `UnaryOpSugar`; observed `py.invert(TermValue)`; requested `unary operator floor`; replacement `add UnaryOperatorOperation support for py.invert on TermValue` | `pandas/tests/computation/test_eval.py:583:62` (label `pandas/tests/computation/test_eval.py`) | UnaryOperatorOperation handles py.pos and py.neg for TermValue/SymbolicValue, then gaps at operations/unary_operator_operation.py:26-55. |
| `pandas-gap-21-proofir-proofir-scope-postcondition-illegal-free-var-s-os-free-vars-only-from-declared-formals-p` | `ProofIR` | 1 | owner `proofir.scope.PostCondition`; observed `illegal free var(s): os`; requested `free vars only from declared formals plus out`; replacement `declare the variable in the contract scope or remove it from the formula` | `proofir-construction-law` (label `pandas/tests/io/test_html.py`) | PostCondition and ClosedFormula enforce allowed variables at proofir/scope/__init__.py:77-91 and :348-359. |
| `pandas-gap-22-sugar-python-factory-assign-statement` | `Sugar` | 1 | owner `python.factory`; observed `Assign`; requested `statement`; replacement `create sugar_lift_py_tests.sugar.assign.assign_sugar` | `pandas/tests/frame/methods/test_info.py:199:4` (label `pandas/tests/frame/methods/test_info.py`) | AssignSugar exists for single-name assignment at sugar/assign_sugar.py:14-37; this row is a factory-selection gap for the statement shape in context. |
| `pandas-gap-23-sugar-python-factory-namedexpr-term` | `Sugar` | 1 | owner `python.factory`; observed `NamedExpr`; requested `term`; replacement `create sugar_lift_py_tests.sugar.named_expr.named_expr_sugar` | `pandas/tests/extension/uuid/test_uuid.py:83:41` (label `pandas/tests/extension/uuid/test_uuid.py`) | grammar_ledger.py:358 names NamedExpr as walrus-tail debt; factory/build.py:125-142 raises the missing sugar row. |
| `pandas-gap-24-sugar-python-factory-unaryop-term` | `Sugar` | 1 | owner `python.factory`; observed `UnaryOp`; requested `term`; replacement `create sugar_lift_py_tests.sugar.unary_op.unary_op_sugar` | `pandas/tests/indexes/datetimes/test_indexing.py:80:15` (label `pandas/tests/indexes/datetimes/test_indexing.py`) | UnaryOpSugar owns supported unary term sites at sugar/unary_op_sugar.py:20-64; this row is the factory fall-through for an unsupported unary shape. |
| `pandas-gap-25-sugar-python-factory-literal-call-callsite-arg-call-unliftable-liftablecallarg` | `Sugar` | 1 | owner `python.factory.literal-call`; observed `callsite-arg:Call-unliftable`; requested `LiftableCallArg`; replacement `lift this call-arg shape (e.g. nested arrays, mixed-type lists): AddSugar operand must reduce to TermValue` | `tests/internals/test_internals.py:1182:20` (label `pandas/tests/internals/test_internals.py`) | literal_call_report requires call arguments to project through floor_to_term and emits this gap at factory/literal_call_report.py:1605-1616; AddSugar keeps the TermValue operand law at sugar/add_sugar.py:56. |

## Full Gap List

The machine-readable companion fixture at `docs/audits/pandas-gap-census.json` carries every row with label, blame, audit status, and template id. The list below mirrors the 68 rows for review.

### `pandas-gap-01-floor-membershipassertionsugar-arrayliteral-contains-symbolicvalue-contains-item-floor` (Floor, 10)

- `pandas/core/apply.py`; blame `pandas/core/apply.py:1652:8`; observed `ArrayLiteral.contains(SymbolicValue)`; requested `contains item floor`
- `pandas/core/arrays/_ranges.py`; blame `pandas/core/arrays/_ranges.py:127:4`; observed `ArrayLiteral.contains(SymbolicValue)`; requested `contains item floor`
- `pandas/core/arrays/datetimelike.py`; blame `pandas/core/arrays/datetimelike.py:1366:8`; observed `ArrayLiteral.contains(SymbolicValue)`; requested `contains item floor`
- `pandas/core/arrays/datetimes.py`; blame `pandas/core/arrays/datetimes.py:2618:4`; observed `ArrayLiteral.contains(SymbolicValue)`; requested `contains item floor`
- `pandas/core/arrays/period.py`; blame `pandas/core/arrays/period.py:1036:8`; observed `ArrayLiteral.contains(SymbolicValue)`; requested `contains item floor`
- `pandas/core/arrays/timedeltas.py`; blame `pandas/core/arrays/timedeltas.py:1127:4`; observed `ArrayLiteral.contains(SymbolicValue)`; requested `contains item floor`
- `pandas/core/generic.py`; blame `pandas/core/generic.py:11780:8`; observed `ArrayLiteral.contains(SymbolicValue)`; requested `contains item floor`
- `pandas/core/groupby/ops.py`; blame `pandas/core/groupby/ops.py:959:8`; observed `ArrayLiteral.contains(SymbolicValue)`; requested `contains item floor`
- `pandas/core/missing.py`; blame `pandas/core/missing.py:254:4`; observed `ArrayLiteral.contains(SymbolicValue)`; requested `contains item floor`
- `pandas/io/excel/_util.py`; blame `pandas/io/excel/_util.py:80:4`; observed `ArrayLiteral.contains(SymbolicValue)`; requested `contains item floor`

### `pandas-gap-02-sugar-python-factory-generatorexp-term` (Sugar, 8)

- `pandas/io/pytables.py`; blame `pandas/io/pytables.py:4124:18`; observed `GeneratorExp`; requested `term`
- `pandas/tests/arrays/sparse/test_constructors.py`; blame `pandas/tests/arrays/sparse/test_constructors.py:80:13`; observed `GeneratorExp`; requested `term`
- `pandas/tests/dtypes/test_generic.py`; blame `pandas/tests/dtypes/test_generic.py:98:23`; observed `GeneratorExp`; requested `term`
- `pandas/tests/dtypes/test_inference.py`; blame `pandas/tests/dtypes/test_inference.py:152:5`; observed `GeneratorExp`; requested `term`
- `pandas/tests/frame/test_constructors.py`; blame `pandas/tests/frame/test_constructors.py:2573:22`; observed `GeneratorExp`; requested `term`
- `pandas/tests/interchange/test_spec_conformance.py`; blame `pandas/tests/interchange/test_spec_conformance.py:132:14`; observed `GeneratorExp`; requested `term`
- `pandas/tests/io/formats/test_to_string.py`; blame `pandas/tests/io/formats/test_to_string.py:262:18`; observed `GeneratorExp`; requested `term`
- `pandas/tests/plotting/frame/test_frame_color.py`; blame `pandas/tests/plotting/frame/test_frame_color.py:239:25`; observed `GeneratorExp`; requested `term`

### `pandas-gap-03-floor-arrayliteralsugar-dictliteralvalue-array-element-floor` (Floor, 6)

- `pandas/tests/frame/methods/test_to_dict.py`; blame `pandas/tests/frame/methods/test_to_dict.py:37:28`; observed `DictLiteralValue`; requested `array element floor`
- `pandas/tests/groupby/test_groupby.py`; blame `pandas/tests/groupby/test_groupby.py:2150:20`; observed `DictLiteralValue`; requested `array element floor`
- `pandas/tests/io/json/test_json_table_schema.py`; blame `pandas/tests/io/json/test_json_table_schema.py:66:16`; observed `DictLiteralValue`; requested `array element floor`
- `pandas/tests/io/json/test_json_table_schema_ext_dtype.py`; blame `pandas/tests/io/json/test_json_table_schema_ext_dtype.py:50:16`; observed `DictLiteralValue`; requested `array element floor`
- `pandas/tests/io/json/test_normalize.py`; blame `pandas/tests/io/json/test_normalize.py:601:16`; observed `DictLiteralValue`; requested `array element floor`
- `pandas/tests/scalar/timestamp/test_formats.py`; blame `pandas/tests/scalar/timestamp/test_formats.py:145:40`; observed `DictLiteralValue`; requested `array element floor`

### `pandas-gap-04-floor-binopsugar-stringvalue-termvalue-binary-operator-operand-floor` (Floor, 5)

- `pandas/tests/indexes/multi/test_formats.py`; blame `pandas/tests/indexes/multi/test_formats.py:201:40`; observed `StringValue*TermValue`; requested `binary operator operand floor`
- `pandas/tests/io/formats/test_format.py`; blame `pandas/tests/io/formats/test_format.py:273:25`; observed `StringValue*TermValue`; requested `binary operator operand floor`
- `pandas/tests/io/formats/test_to_html.py`; blame `pandas/tests/io/formats/test_to_html.py:957:25`; observed `StringValue*TermValue`; requested `binary operator operand floor`
- `pandas/tests/io/json/test_pandas.py`; blame `pandas/tests/io/json/test_pandas.py:680:25`; observed `StringValue*TermValue`; requested `binary operator operand floor`
- `pandas/tests/tslibs/test_parse_iso8601.py`; blame `pandas/tests/tslibs/test_parse_iso8601.py:74:39`; observed `StringValue*TermValue`; requested `binary operator operand floor`

### `pandas-gap-05-floor-builtincallsugar-stringvalue-dunder-floatdunder-string-builtin-method-floor` (Floor, 5)

- `pandas/tests/arrays/string_/test_string.py`; blame `pandas/tests/arrays/string_/test_string.py:55:56`; observed `StringValue.__float__`; requested `string builtin method floor`
- `pandas/tests/indexes/period/test_indexing.py`; blame `pandas/tests/indexes/period/test_indexing.py:783:15`; observed `StringValue.__float__`; requested `string builtin method floor`
- `pandas/tests/indexes/timedeltas/test_indexing.py`; blame `pandas/tests/indexes/timedeltas/test_indexing.py:109:28`; observed `StringValue.__float__`; requested `string builtin method floor`
- `pandas/tests/libs/test_hashtable.py`; blame `pandas/tests/libs/test_hashtable.py:546:16`; observed `StringValue.__float__`; requested `string builtin method floor`
- `pandas/tests/scalar/interval/test_contains.py`; blame `pandas/tests/scalar/interval/test_contains.py:36:29`; observed `StringValue.__float__`; requested `string builtin method floor`

### `pandas-gap-06-sugar-python-factory-compare-term` (Sugar, 5)

- `pandas/tests/api/test_api.py`; blame `pandas/tests/api/test_api.py:555:14`; observed `Compare`; requested `term`
- `pandas/tests/arrays/categorical/test_indexing.py`; blame `pandas/tests/arrays/categorical/test_indexing.py:318:17`; observed `Compare`; requested `term`
- `pandas/tests/dtypes/test_dtypes.py`; blame `pandas/tests/dtypes/test_dtypes.py:974:19`; observed `Compare`; requested `term`
- `pandas/tests/indexes/categorical/test_indexing.py`; blame `pandas/tests/indexes/categorical/test_indexing.py:405:17`; observed `Compare`; requested `term`
- `pandas/tests/indexes/test_base.py`; blame `pandas/tests/indexes/test_base.py:1082:17`; observed `Compare`; requested `term`

### `pandas-gap-07-floor-stringsubscriptsugar-dictliteralvalue-subscript-with` (Floor, 4)

- `pandas/tests/frame/test_query_eval.py`; blame `pandas/tests/frame/test_query_eval.py:180:61`; observed `DictLiteralValue`; requested `subscript_with`
- `pandas/tests/scalar/test_na_scalar.py`; blame `pandas/tests/scalar/test_na_scalar.py:54:11`; observed `DictLiteralValue`; requested `subscript_with`
- `pandas/tests/scalar/timestamp/test_timestamp.py`; blame `pandas/tests/scalar/timestamp/test_timestamp.py:397:15`; observed `DictLiteralValue`; requested `subscript_with`
- `pandas/tests/tslibs/test_liboffsets.py`; blame `pandas/tests/tslibs/test_liboffsets.py:138:61`; observed `DictLiteralValue`; requested `subscript_with`

### `pandas-gap-08-floor-membershipassertionsugar-tupleliteralvalue-contains-with` (Floor, 3)

- `pandas/core/interchange/from_dataframe.py`; blame `pandas/core/interchange/from_dataframe.py:332:4`; observed `TupleLiteralValue`; requested `contains_with`
- `pandas/tests/io/test_sql.py`; blame `pandas/tests/io/test_sql.py:382:4`; observed `TupleLiteralValue`; requested `contains_with`
- `pandas/tests/tseries/offsets/test_year.py`; blame `pandas/tests/tseries/offsets/test_year.py:338:4`; observed `TupleLiteralValue`; requested `contains_with`

### `pandas-gap-09-floor-attributesugar-callsitevalue-attribute-with` (Floor, 2)

- `pandas/tests/arrays/integer/test_construction.py`; blame `pandas/tests/arrays/integer/test_construction.py:171:11`; observed `CallSiteValue`; requested `attribute_with`
- `pandas/tests/tseries/offsets/test_offsets.py`; blame `pandas/tests/tseries/offsets/test_offsets.py:950:11`; observed `CallSiteValue`; requested `attribute_with`

### `pandas-gap-10-floor-binopsugar-arrayliteral-arrayliteral-binary-operator-operand-floor` (Floor, 2)

- `pandas/tests/frame/test_stack_unstack.py`; blame `pandas/tests/frame/test_stack_unstack.py:883:23`; observed `ArrayLiteral+ArrayLiteral`; requested `binary operator operand floor`
- `pandas/tests/window/test_groupby.py`; blame `pandas/tests/window/test_groupby.py:856:23`; observed `ArrayLiteral+ArrayLiteral`; requested `binary operator operand floor`

### `pandas-gap-11-floor-binopsugar-symbolicvalue-stringvalue-binary-operator-operand-floor` (Floor, 2)

- `pandas/tests/arithmetic/test_object.py`; blame `pandas/tests/arithmetic/test_object.py:291:17`; observed `SymbolicValue+StringValue`; requested `binary operator operand floor`
- `pandas/tests/indexes/datetimes/methods/test_tz_convert.py`; blame `pandas/tests/indexes/datetimes/methods/test_tz_convert.py:59:41`; observed `SymbolicValue+StringValue`; requested `binary operator operand floor`

### `pandas-gap-12-floor-mapsugar-symbolicvalue-map-with` (Floor, 2)

- `pandas/tests/io/formats/style/test_style.py`; blame `pandas/tests/io/formats/style/test_style.py:520:12`; observed `SymbolicValue`; requested `map_with`
- `pandas/tests/series/methods/test_map.py`; blame `pandas/tests/series/methods/test_map.py:278:13`; observed `SymbolicValue`; requested `map_with`

### `pandas-gap-13-floor-literal-call-report-kw-float-format-lambdacallable-project-this-floor-value-to-a-term` (Floor, 2)

- `pandas/tests/frame/methods/test_to_csv.py`; blame `LambdaCallable`; observed `LambdaCallable`; requested `project this floor value to a term`
- `pandas/tests/io/formats/test_to_csv.py`; blame `LambdaCallable`; observed `LambdaCallable`; requested `project this floor value to a term`

### `pandas-gap-14-constructor-attributesugar-t-a-constructor-bound-field` (Constructor, 1)

- `pandas/tests/base/test_constructors.py`; blame `pandas/tests/base/test_constructors.py:110:15`; observed `T.a`; requested `constructor-bound field`

### `pandas-gap-15-floor-callsugar-stringvalue-format-string-builtin-method-floor` (Floor, 1)

- `pandas/tests/io/formats/style/test_html.py`; blame `pandas/tests/io/formats/style/test_html.py:833:11`; observed `StringValue.format`; requested `string builtin method floor`

### `pandas-gap-16-floor-membershipassertionsugar-importaliasvalue-contains-with` (Floor, 1)

- `pandas/core/arrays/arrow/extension_types.py`; blame `pandas/core/arrays/arrow/extension_types.py:66:8`; observed `ImportAliasValue`; requested `contains_with`

### `pandas-gap-17-floor-stringsubscriptsugar-arrayliteral-1-bounds-safe-sequence-subscript` (Floor, 1)

- `pandas/tests/config/test_config.py`; blame `pandas/tests/config/test_config.py:366:15`; observed `ArrayLiteral[-1]`; requested `bounds-safe sequence subscript`

### `pandas-gap-18-floor-subscriptassignsugar-symbolicvalue-setitem-with` (Floor, 1)

- `pandas/tests/copy_view/test_methods.py`; blame `pandas/tests/copy_view/test_methods.py:1503:8`; observed `SymbolicValue`; requested `setitem_with`

### `pandas-gap-19-floor-unaryopsugar-callsitevalue-unary-operator-with` (Floor, 1)

- `pandas/tests/scalar/timedelta/test_timedelta.py`; blame `pandas/tests/scalar/timedelta/test_timedelta.py:521:35`; observed `CallSiteValue`; requested `unary_operator_with`

### `pandas-gap-20-floor-unaryopsugar-py-invert-termvalue-unary-operator-floor` (Floor, 1)

- `pandas/tests/computation/test_eval.py`; blame `pandas/tests/computation/test_eval.py:583:62`; observed `py.invert(TermValue)`; requested `unary operator floor`

### `pandas-gap-21-proofir-proofir-scope-postcondition-illegal-free-var-s-os-free-vars-only-from-declared-formals-p` (ProofIR, 1)

- `pandas/tests/io/test_html.py`; blame `proofir-construction-law`; observed `illegal free var(s): os`; requested `free vars only from declared formals plus out`

### `pandas-gap-22-sugar-python-factory-assign-statement` (Sugar, 1)

- `pandas/tests/frame/methods/test_info.py`; blame `pandas/tests/frame/methods/test_info.py:199:4`; observed `Assign`; requested `statement`

### `pandas-gap-23-sugar-python-factory-namedexpr-term` (Sugar, 1)

- `pandas/tests/extension/uuid/test_uuid.py`; blame `pandas/tests/extension/uuid/test_uuid.py:83:41`; observed `NamedExpr`; requested `term`

### `pandas-gap-24-sugar-python-factory-unaryop-term` (Sugar, 1)

- `pandas/tests/indexes/datetimes/test_indexing.py`; blame `pandas/tests/indexes/datetimes/test_indexing.py:80:15`; observed `UnaryOp`; requested `term`

### `pandas-gap-25-sugar-python-factory-literal-call-callsite-arg-call-unliftable-liftablecallarg` (Sugar, 1)

- `pandas/tests/internals/test_internals.py`; blame `tests/internals/test_internals.py:1182:20`; observed `callsite-arg:Call-unliftable`; requested `LiftableCallArg`
