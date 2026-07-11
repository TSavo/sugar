# Deeper floors — remaining 52 cut

## Shipped
1. **ClassDef method walk** — `test_*` methods inside classes enter `audit_lift_file`
2. **KeywordCallSugar** — `f(a=1)` / `recv.m(a=1)` coordinates (no `**kwargs`)
3. **BuiltinTypeNameSugar** — expanded exceptions (`NotImplementedError`, …)
4. **BuiltinModuleNameSugar** — freezegun, secrets, …

## itsdangerous sdist suite
| | prior (#4116) | now |
|--|-------------:|----:|
| lifted | 5 | **15** |
| refused | 52 | **42** |
| silent | 0 | **0** |

Notable: `test_signer.py` 0→**7** lifted. `test_timed.py` still refuse-heavy (freezegun/`with`/fixture stack).

## Law
Silent illegal. Panic/refuse for unfinished floors.
