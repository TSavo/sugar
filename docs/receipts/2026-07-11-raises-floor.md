# Raises floor — RaiseSugar + PytestRaisesWithSugar + InOpSugar

## Doctrine
Option A: `with pytest.raises(T)` states inv `pytest.raises(T)` (Stated at with locus).
Panic still correct for unfinished pieces. Silent illegal.

## Shipped
1. **RaiseSugar** — `raise` → `RaiseValue` (routeable; rest dropped)
2. **PytestRaisesWithSugar** — owns `with pytest.raises(...) [as x]`; inv + body; **as binds after with**
3. **RaisesWithValue** — frame floor for inv + body + extend_scope
4. **InOpSugar** — `"msg" in str(exc)` → `py.in` predicate
5. **ir.py_raises** — `pytest.raises` atom

## Suite (itsdangerous sdist)
| | before | after |
|--|-------:|------:|
| lifted | 15 | **28** |
| refused | 42 | **29** |
| silent | 0 | **0** |

Message-in-str after raises: **lifted**.
