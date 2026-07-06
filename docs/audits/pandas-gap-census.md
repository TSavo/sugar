# Pandas Gap Census

Part of #3503. This is the shared pandas wall payload for sibling drain lanes; it is a census and work-list, not a recognizer change.

## Render Receipt

| field | value |
| --- | --- |
| command | `/Users/tsavo/.cache/sugar/binaries/sugar-darwin-x86_64-release-blake3-512_f831b190795697a4338ff05350cdf77237f6ec75590a1d1d5089dbf76abcda78728a3b6c2cbcc7afefd6d03553234603bf77e0b6b8f11164dafd92884ab065a8 lift --report --json /Users/tsavo/.cache/sugar/python-panic-audit-workspaces/9f13130e1dc95bc1ece2da57a2e6ff0cd2f30d308615e0193365baefefebc754/pandas` |
| exit code | `2` |
| runtime | `631.66s` |
| pandas version | `3.0.3` |
| cached workspace | `/Users/tsavo/.cache/sugar/python-panic-audit-workspaces/9f13130e1dc95bc1ece2da57a2e6ff0cd2f30d308615e0193365baefefebc754/pandas` |
| Python files | `1421` |
| stdout bytes / SHA-256 | `0` / `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| stderr bytes / SHA-256 | `9722` / `c1629ff4f79639a85decb417f72f8b4050ecaad69cf47bd9ca6b847c89479063` |
| sugar binary | `/Users/tsavo/.cache/sugar/binaries/sugar-darwin-x86_64-release-blake3-512_f831b190795697a4338ff05350cdf77237f6ec75590a1d1d5089dbf76abcda78728a3b6c2cbcc7afefd6d03553234603bf77e0b6b8f11164dafd92884ab065a8` |
| binary file receipt | `/Users/tsavo/.cache/sugar/binaries/sugar-darwin-x86_64-release-blake3-512_f831b190795697a4338ff05350cdf77237f6ec75590a1d1d5089dbf76abcda78728a3b6c2cbcc7afefd6d03553234603bf77e0b6b8f11164dafd92884ab065a8: Mach-O 64-bit executable x86_64` |

This refresh was run after the ArrayLiteral.contains(SymbolicValue) drain and current main through the pandas floor/string/guard-precondition drains. The current main-tip audit-only wall produced the 4-row payload below.

## R Vector

| bucket | count |
| --- | ---: |
| `Constructor` | 1 |
| `Floor` | 2 |
| `Sugar` | 1 |
| **Total** | **4** |

## Delta vs Previous 68-Row Census

| class | rows |
| --- | ---: |
| Previous total | 68 |
| Old rows still present | 0 |
| Old rows drained | 68 |
| Newly exposed rows | 4 |
| Current total | 4 |

| template | previous | current | delta | disposition |
| --- | ---: | ---: | ---: | --- |
| `pandas-gap-01-floor-membershipassertionsugar-arrayliteral-contains-symbolicvalue-contains-item-floor` | 10 | 0 | -10 | drained |
| `pandas-gap-02-sugar-python-factory-generatorexp-term` | 8 | 0 | -8 | drained |
| `pandas-gap-03-floor-arrayliteralsugar-dictliteralvalue-array-element-floor` | 6 | 0 | -6 | drained |
| `pandas-gap-04-floor-binopsugar-stringvalue-termvalue-binary-operator-operand-floor` | 5 | 0 | -5 | drained |
| `pandas-gap-05-floor-builtincallsugar-stringvalue-dunder-floatdunder-string-builtin-method-floor` | 5 | 0 | -5 | drained |
| `pandas-gap-06-sugar-python-factory-compare-term` | 5 | 0 | -5 | drained |
| `pandas-gap-07-floor-stringsubscriptsugar-dictliteralvalue-subscript-with` | 4 | 0 | -4 | drained |
| `pandas-gap-08-floor-membershipassertionsugar-tupleliteralvalue-contains-with` | 3 | 0 | -3 | drained |
| `pandas-gap-09-floor-attributesugar-callsitevalue-attribute-with` | 2 | 0 | -2 | drained |
| `pandas-gap-10-floor-binopsugar-arrayliteral-arrayliteral-binary-operator-operand-floor` | 2 | 0 | -2 | drained |
| `pandas-gap-11-floor-binopsugar-symbolicvalue-stringvalue-binary-operator-operand-floor` | 2 | 0 | -2 | drained |
| `pandas-gap-12-floor-mapsugar-symbolicvalue-map-with` | 2 | 0 | -2 | drained |
| `pandas-gap-13-floor-literal-call-report-kw-float-format-lambdacallable-project-this-floor-value-to-a-term` | 2 | 0 | -2 | drained |
| `pandas-gap-14-constructor-attributesugar-t-a-constructor-bound-field` | 1 | 0 | -1 | drained |
| `pandas-gap-15-floor-callsugar-stringvalue-format-string-builtin-method-floor` | 1 | 0 | -1 | drained |
| `pandas-gap-16-floor-membershipassertionsugar-importaliasvalue-contains-with` | 1 | 0 | -1 | drained |
| `pandas-gap-17-floor-stringsubscriptsugar-arrayliteral-1-bounds-safe-sequence-subscript` | 1 | 0 | -1 | drained |
| `pandas-gap-18-floor-subscriptassignsugar-symbolicvalue-setitem-with` | 1 | 0 | -1 | drained |
| `pandas-gap-19-floor-unaryopsugar-callsitevalue-unary-operator-with` | 1 | 0 | -1 | drained |
| `pandas-gap-20-floor-unaryopsugar-py-invert-termvalue-unary-operator-floor` | 1 | 0 | -1 | drained |
| `pandas-gap-21-proofir-proofir-scope-postcondition-illegal-free-var-s-os-free-vars-only-from-declared-formals-p` | 1 | 0 | -1 | drained |
| `pandas-gap-22-sugar-python-factory-assign-statement` | 1 | 0 | -1 | drained |
| `pandas-gap-23-sugar-python-factory-namedexpr-term` | 1 | 0 | -1 | drained |
| `pandas-gap-24-sugar-python-factory-unaryop-term` | 1 | 0 | -1 | drained |
| `pandas-gap-25-sugar-python-factory-literal-call-callsite-arg-call-unliftable-liftablecallarg` | 1 | 0 | -1 | drained |
| `pandas-gap-26-constructor-builtincallsugar-t-dunder-dirdunder-constructor-bound-method` | 0 | 1 | +1 | new |
| `pandas-gap-27-sugar-python-factory-assert-statement` | 0 | 1 | +1 | new |
| `pandas-gap-28-floor-binopsugar-stringvalue-plus-symbolicvalue-binary-operator-operand-floor` | 0 | 1 | +1 | new |
| `pandas-gap-29-floor-binopsugar-stringvalue-plus-stringvalue-binary-operator-operand-floor` | 0 | 1 | +1 | new |

## Shape Templates

| id | bucket | count | template | examples | closest precedent |
| --- | --- | ---: | --- | --- | --- |
| `pandas-gap-26-constructor-builtincallsugar-t-dunder-dirdunder-constructor-bound-method` | `Constructor` | 1 | owner `BuiltinCallSugar`; observed `T.__dir__`; requested `constructor-bound method`; replacement `define `__dir__` on `T` or add the floor that owns this method` | `tests/base/test_constructors.py:113:29` (label `tests/base/test_constructors.py`) | BuiltinCallSugar maps dir() to __dir__ at sugar/builtin_call_sugar.py:362-364; ObjectValue reports constructor-bound method gaps when the target method is absent at floor/object_value.py:293-300. |
| `pandas-gap-27-sugar-python-factory-assert-statement` | `Sugar` | 1 | owner `python.factory`; observed `Assert`; requested `statement`; replacement `create sugar_lift_py_tests.sugar.assert.assert_sugar` | `tests/io/formats/style/test_html.py:922:8` (label `tests/io/formats/style/test_html.py`) | Assertion-specific sugars own Assert nodes (truthy/comparison/membership/etc.) under sugar/*.py; factory/literal_call_report.py:878-900 handles derived assertion context, and factory/build.py:125-142 raises the remaining factory fall-through. |
| `pandas-gap-28-floor-binopsugar-stringvalue-plus-symbolicvalue-binary-operator-operand-floor` | `Floor` | 1 | owner `BinOpSugar`; observed `StringValue+SymbolicValue`; requested `binary operator operand floor`; replacement `add BinaryOperatorOperation support for StringValue + SymbolicValue` | `tests/io/json/test_pandas.py:1510:19` (label `tests/io/json/test_pandas.py`) | BinaryOperatorOperation already owns string equality and symbolic term arithmetic at operations/binary_operator_operation.py:52-113; this row is the remaining mixed string/symbolic concatenation floor. |
| `pandas-gap-29-floor-binopsugar-stringvalue-plus-stringvalue-binary-operator-operand-floor` | `Floor` | 1 | owner `BinOpSugar`; observed `StringValue+StringValue`; requested `binary operator operand floor`; replacement `add BinaryOperatorOperation support for StringValue + StringValue` | `tests/tslibs/test_parse_iso8601.py:74:39` (label `tests/tslibs/test_parse_iso8601.py`) | BinaryOperatorOperation owns string equality and array/tuple repeats at operations/binary_operator_operation.py:52-113; this row is the remaining string concatenation floor. |

## Full Gap List

The machine-readable companion fixture at `docs/audits/pandas-gap-census.json` carries every row with label, blame, audit status, and template id. The list below mirrors the 4 rows for review.

### `pandas-gap-26-constructor-builtincallsugar-t-dunder-dirdunder-constructor-bound-method` (Constructor, 1)

- `tests/base/test_constructors.py`; blame `tests/base/test_constructors.py:113:29`; observed `T.__dir__`; requested `constructor-bound method`

### `pandas-gap-27-sugar-python-factory-assert-statement` (Sugar, 1)

- `tests/io/formats/style/test_html.py`; blame `tests/io/formats/style/test_html.py:922:8`; observed `Assert`; requested `statement`

### `pandas-gap-28-floor-binopsugar-stringvalue-plus-symbolicvalue-binary-operator-operand-floor` (Floor, 1)

- `tests/io/json/test_pandas.py`; blame `tests/io/json/test_pandas.py:1510:19`; observed `StringValue+SymbolicValue`; requested `binary operator operand floor`

### `pandas-gap-29-floor-binopsugar-stringvalue-plus-stringvalue-binary-operator-operand-floor` (Floor, 1)

- `tests/tslibs/test_parse_iso8601.py`; blame `tests/tslibs/test_parse_iso8601.py:74:39`; observed `StringValue+StringValue`; requested `binary operator operand floor`
