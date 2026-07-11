# Residual last-8 drain

## Suite (itsdangerous 2.2.0 sdist)
| | lifted | refuse | silent |
|--|--------|--------|--------|
| start of residual lane | 49 | 8 | 0 |
| **now** | **55** | **2** | **0** |

## Shipped
- IfExpSugar (py.if_exp coordinate for symbolic cond)
- BareReturnSugar (`return` → NoneValue)
- AttributeAssignSugar (`e.payload = …`)
- StarredSugar (`*args`)
- Call/MethodCall `**kwargs` coordinates
- FunctionDef binds *args/**kwargs formals
- Try except-arm returns → GuardedReturn (tail after try still reduces)

## Residual 2
1. `test_skip_keys` assert after try/except bare-return (IR still empty — further try/block)
2. `isinstance(exc_info.value.date_signed, datetime)` — pytest.raises temporal bind
