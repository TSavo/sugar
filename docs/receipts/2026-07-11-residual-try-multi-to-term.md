# Residual refuse drain (itsdangerous sdist)

## Before → After
| | stated | lifted | refused | silent |
|--|--------|--------|---------|--------|
| before | 57 | 34 | 23 | 0 |
| **after** | 57 | **49** | **8** | 0 |

## Wins
- **test_encoding.py** 5/5 lifted
- **test_signer.py** 15/15 lifted
- **test_serializer** 5→15; **test_timed** 14/15

## Shipped
1. TrySugar multi-type `except (A, B)`
2. ListValue / DictValue / ClassValue `to_term`
3. Install-source attachable: AugAssign / Try / If terminal; dig builds base64_* / want_bytes

## Residual 8
- loads_unsafe / load / load_unsafe tuple faces
- `{(): 1}` skipkeys / cast+ternary IO
- isinstance(exc.date_signed, datetime)
