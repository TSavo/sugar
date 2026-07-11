# Deeper floors — Call==Name, imports, pytest, parametrized testimony

## Shipped
1. **Module import temporal seeding** in `audit_lift_file` — `import` / `from … import` bind `python:module` / `python:from_import` terms for every def in the file.
2. **BuiltinModuleNameSugar** — closed module Name set (`pytest`, `sys`, …) before NameSugar.
3. **TestFunctionDefSugar owns** — allow decorators (`@pytest.mark.parametrize`); body remains testimony; decorator not fabricated.
4. **Call==Name assign** regression — `got = claimed(); assert got == 1` lifts under `test_*`.

## itsdangerous sdist suite
| | before | after |
|--|-------:|------:|
| lifted | 0 | **5** |
| refused | 57 | **52** |
| silent | 0 | **0** |

`test_encoding.py` alone: **5/5 lifted**.

## Law
Panic still correct for unimplemented. Silent remains illegal.
