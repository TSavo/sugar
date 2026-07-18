# Raise-expression outcome receipt (#5145)

## Boundary

Measured on Python 3.12.3 with NumPy 2.5.1 and pandas 3.0.3 in the private
battleaxe worktree `/home/tsavo/remote/fatal-corpus-raise-sugar-5145`.
The control is current main `0a5e0b794`; the candidate is this branch.

RaiseSugar consumes reduced outcomes. A source-backed helper may reduce to an
exact exception, an already-raised exceptional exit, or a qualified native
exception constructor. The last case is constructed only after the
install-source oracle imports the exact export and proves that it is an
exception class. Runtime-selected and opaque exception identities remain loud.
No RuntimeEffect constructor or empty-success arm was added.

## Named representative replay

| Representative | Current main | Candidate | Movement |
| --- | --- | --- | --- |
| `pandas/core/indexes/period.py:389:12` | `RaiseSugar(CallSiteValue)` | completed, 11 IR rows | completed |
| `pandas/core/indexes/base.py:541:12` | `RaiseSugar(GuardedValue)` | `RaiseSugar(CallSiteValue)` | loud remains loud |
| `numpy/f2py/tests/test_symbolic.py:1070:4` | `RaiseSugar(CallSiteValue)` | `RaiseSugar(CallSiteValue)` | loud remains loud |
| `pandas/tests/test_errors.py:65:8` | `RaiseSugar(CallSiteValue)` | `RaiseSugar(CallSiteValue)` | loud remains loud |

Conservation: 4 live terminals become 1 completed + 3 loud + 0 silent.

The remaining pandas rows select their exception callable at runtime. The
NumPy row remains opaque at its installed-source boundary. None is relabeled
as an effect.

## Discrimination and witness

The focused suite covers:

- source helper returning an exact exception;
- source helper ending at an oracle-proven qualified native exception class;
- exception-expression evaluation that raises before the outer raise;
- guarded faces with the same exact exceptional terminal;
- opaque runtime-selected callable staying a named `RaiseSugar` panic;
- file-backed truthful and lying witness twins.

```text
10 passed in 40.24s
```

The fresh witness verdicts are truthful SAT and lying UNSAT. The lying twin
therefore refutes the constructed claim.

## Floor and pins

Pinned Black 26.5.1 reports all three Python files unchanged. The direct
claim-mass tripwire uses the local release binary rather than the sugarbin
shelf:

```text
5 passed in 29.44s
CLAIM_MASS_EXIT=0
```

No claim-mass pin moved, and no effect constructor site changed.
