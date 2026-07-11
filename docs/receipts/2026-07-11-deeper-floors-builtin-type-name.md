# Deeper floors — BuiltinTypeNameSugar

## Shape
`Name` ∈ closed builtin/type set (`bytes`, `int`, `str`, …) before `NameSugar`.

## Interface
`comes_before=("NameSugar",)` · desugar → `python:type("<name>")` SymbolicValue.

## Unlocked
| Source | Before | After |
|--------|--------|-------|
| `assert isinstance(b'ab', bytes)` | refuse-loud (TemporalContext unbound `bytes`) | **lifted+cited** |
| Unbound user name | panic | still panic (correct) |

## itsdangerous sdist suite (honest)
Still **lifted=0 / refused=57 / silent=0** — test modules bind `pytest` / fixtures;
those Names correctly TemporalContext-panic. Floor works; suite residue is other bindings.

## Tests
`test_builtin_type_name_sugar.py` — 4 passed
