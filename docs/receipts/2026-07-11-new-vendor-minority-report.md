# Handoff N — New-vendor Minority Report

**Date:** 2026-07-11  
**Method:** `lift_file_payload` + `account_lift_coverage` + `census_paths`  
**Raw:** `docs/receipts/2026-07-11-new-vendor-minority-report.json`

Vendors not previously gallery-audited (itsdangerous covered under O).

## Summary table

| vendor | stated | silent (Crime 1) | bodies | forged (Crime 2) | status |
|--------|-------:|-----------------:|-------:|-----------------:|--------|
| **requests** 2.34.2 | 16 | **16** | 267 | 0 | **RED Crime 1** |
| **datetime** (stdlib) | 45 | **45** | 184 | 0 | **RED Crime 1** |
| **csv** (stdlib) | 0 | 0 | 17 | 0 | green crimes (voiceless only) |

## Detail

### requests

| | |
|--|--:|
| files ok | 19/19 |
| stated | 16 |
| lifted+cited | 0 |
| refused-loud | 0 |
| **silently_unaccounted (Crime 1)** | **16** |
| bodies (census) | 267 |
| dig_floors | 0 |
| **forged_warrant (Crime 2)** | **0** |
| census_disagreement files | 16 |
| Crime 1 gate | **RED** |
| Crime 2 gate | GREEN |

Silent sample:

| file | line | preview |
|------|-----:|--------|
| `__init__.py` | 66 | `assert urllib3_version_list != ["dev"]  # Verify urllib3 isn't install `|
| `__init__.py` | 76 | `assert major >= 1 `|
| `__init__.py` | 78 | `assert minor >= 21 `|
| `__init__.py` | 85 | `assert (3, 0, 2) <= (major, minor, patch) < (8, 0, 0) `|
| `__init__.py` | 90 | `assert (2, 0, 0) <= (major, minor, patch) < (4, 0, 0) `|
| `_internal_utils.py` | 46 | `assert isinstance(u_string, str) `|
| `adapters.py` | 375 | `assert _is_prepared(req) `|
| `adapters.py` | 481 | `assert _is_prepared(request) `|
| `adapters.py` | 581 | `assert _is_prepared(request) `|
| `adapters.py` | 659 | `assert _is_prepared(request) `|
| `cookies.py` | 46 | `assert _is_prepared(request) `|
| `sessions.py` | 317 | `assert _is_prepared(original_request) `|
| `sessions.py` | 318 | `assert _is_prepared(prepared_request) `|
| `sessions.py` | 350 | `assert _is_prepared(prepared_request) `|
| `sessions.py` | 637 | `assert _is_prepared(prep) `|
| `sessions.py` | 770 | `assert _is_prepared(request) `|

### csv

| | |
|--|--:|
| files ok | 1/1 |
| stated | 0 |
| lifted+cited | 0 |
| refused-loud | 0 |
| **silently_unaccounted (Crime 1)** | **0** |
| bodies (census) | 17 |
| dig_floors | 0 |
| **forged_warrant (Crime 2)** | **0** |
| census_disagreement files | 1 |
| Crime 1 gate | GREEN |
| Crime 2 gate | GREEN |

### datetime

| | |
|--|--:|
| files ok | 1/1 |
| stated | 45 |
| lifted+cited | 0 |
| refused-loud | 0 |
| **silently_unaccounted (Crime 1)** | **45** |
| bodies (census) | 184 |
| dig_floors | 0 |
| **forged_warrant (Crime 2)** | **0** |
| census_disagreement files | 1 |
| Crime 1 gate | **RED** |
| Crime 2 gate | GREEN |

Silent sample:

| file | line | preview |
|------|-----:|--------|
| `datetime.py` | 53 | `assert 1 <= month <= 12, month `|
| `datetime.py` | 60 | `assert 1 <= month <= 12, 'month must be in 1..12' `|
| `datetime.py` | 65 | `assert 1 <= month <= 12, 'month must be in 1..12' `|
| `datetime.py` | 67 | `assert 1 <= day <= dim, ('day must be in 1..%d' % dim) `|
| `datetime.py` | 78 | `assert _DI4Y == 4 * 365 + 1 `|
| `datetime.py` | 82 | `assert _DI400Y == 4 * _DI100Y + 1 `|
| `datetime.py` | 86 | `assert _DI100Y == 25 * _DI4Y - 1 `|
| `datetime.py` | 131 | `assert n == 0 `|
| `datetime.py` | 137 | `assert leapyear == _is_leap(year) `|
| `datetime.py` | 144 | `assert 0 <= n < _days_in_month(year, month) `|
| `datetime.py` | 243 | `assert '%' not in zreplace `|
| `datetime.py` | 274 | `assert len_dtstr > 7 `|
| `datetime.py` | 328 | `assert len(dtstr) in (7, 8, 10) `|
| `datetime.py` | 504 | `assert name in ("utcoffset", "dst") `|
| `datetime.py` | 618 | `assert daysecondswhole == int(daysecondswhole)  # can't overflow `|
| `datetime.py` | 620 | `assert days == int(days) `|
| `datetime.py` | 625 | `assert isinstance(daysecondsfrac, float) `|
| `datetime.py` | 626 | `assert abs(daysecondsfrac) <= 1.0 `|
| `datetime.py` | 627 | `assert isinstance(d, int) `|
| `datetime.py` | 628 | `assert abs(s) <= 24 * 3600 `|



## Indictments

- Crime 1 requests: https://github.com/TSavo/sugar/issues/4103
- Crime 1 datetime: https://github.com/TSavo/sugar/issues/4104
- No Crime 2 indictments (`forged_warrant=0` all three)

## Reading

- **requests / datetime:** stated claims exist and are **entirely un-audited** (lifted=0) → Crime 1 RED.
- **csv:** no asserts; Minority is voiceless bodies + census_disagreement only (same class as itsdangerous).
- Prosecute by making vendor asserts testify — never fabricate claims for bodies.
