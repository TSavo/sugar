# Worker brief: vendor attribute access as a coordinate (`df.shape`, `arr.ndim`, `df.empty`)

**Task:** make `receiver.attr` lift to the coordinate `call:<attr>(<receiver>)`, euf-keyed and grounded by the vendor's sworn assertion — exactly the shape method calls already have — instead of the current location-keyed `py.attr(receiver, "attr")`, which does not discriminate lies.

**Base:** `main` (post #3900 len-coordinate + #3903 hermeticity; the suite is hermetic, solo-first discipline still applies).

**This is soundness work, not cosmetics.** See the discrimination gap below.

## Why this matters (the wall + the model)
The numpy/pandas wall is vendor operations: `df.shape == (0, 0)`, `s.mean() == 2.5`, `arr.ndim == 1`, `df.empty == True`. These are **opaque-only** — the lift cannot compute `df.shape`; only the vendor's test swears its value ("vendor tests ARE the spec"). So each is a coordinate with **no `computed` value** (unlike `len([1,2,3])`, which folds to 3). The grounding is 100% the sworn assertion. This is the frontier the whole coordinate model was built for: a coordinate for `df.shape` and `df2.shape` sharing structure so a vendor law `df == df2` threads through by congruence.

## Current state — VERIFIED (do not take on faith; reproduce with the probe below)
Lifting on `main`:

| source | comparison-left node | emitted | verdict |
|---|---|---|---|
| `np.array([1,2,3]).sum() == 6` | `Call` (method) | `sum#euf#c:call:sum(c:call:numpy.array(c:array(i:1,i:2,i:3)))::assertion` → `call:sum(...) == 6` | ✓ coordinate-keyed euf; discriminates |
| `pd.DataFrame().shape == (0,0)` | `Attribute` | contract `t::t::assert:3:4::assertion`, inv `py.attr[call:pandas.DataFrame(), "shape"] == tuple(0,0)` | ✗ location-keyed, `py.attr` |
| `pd.DataFrame().empty == True` | `Attribute` | same `py.attr` shape | ✗ |

**The discrimination gap (the soundness hole):** two assertions about the *same* attribute get DIFFERENT contract names because they key on assert location, not the coordinate:
```
def t_true(): assert pd.DataFrame().shape == (0, 0)   -> t::t_true::assert:3:4::assertion
def t_lie():  assert pd.DataFrame().shape == (1, 1)   -> t::t_lie::assert:5:4::assertion
```
They never share a euf key → they never conjoin → **a lying `df.shape == (1,1)` does NOT refute a truthful `df.shape == (0,0)`.** Contrast method calls, which share `call:sum(...)` and refute correctly. Closing this by euf-keying attributes on `call:<attr>(receiver)` is the point of the task.

### Reproduce (paste-ready)
```
cd implementations/python/sugar-lift-py-tests
uv run --no-project --python 3.14 --with blake3 --with pynacl --with cbor2 --with-editable . python - <<'PY'
import sugar_lift_py_tests
from sugar_lift_py_tests.lib import lift_source
src="import pandas as pd\ndef t_true():\n    assert pd.DataFrame().shape == (0, 0)\ndef t_lie():\n    assert pd.DataFrame().shape == (1, 1)\n"
for r in lift_source("t.py", src).payload.ir: print(getattr(r,"name","?"))
PY
```
Before: two `...assert:N:4::assertion` names. Done-when: both are `shape#euf#c:call:shape(c:call:pandas.DataFrame())::assertion` (one shared coordinate key).

## The change — route `receiver.attr` through the callsite-euf path
The method path already does exactly what we want; attributes fall out because `_callee_name` only recognizes `Call`. Extend the recognition so an `Attribute` comparison-left is treated as the unary coordinate `call:<attr>(<receiver>)` and emitted through the same euf machinery.

Concrete locations (`factory/literal_call_report.py`):
1. `_lift_assert` resolves `comparison_left` then calls `_callee_name(comparison_left, ...)`. For an `Attribute` node this returns `None`, dropping to `_non_call_equality_lhs_gap` (the generic `py.attr` path). **Add an attribute recognizer** parallel to `_callee_name`: for `comparison_left.observed == "Attribute"`, produce the coordinate head `<attr-name>` and the receiver term.
2. Route it through the **same emitter** method calls use (`_lift_callsite_assertion` / `_emit_euf_fact`), building `CallTerm("<attr-name>", [<receiver-term>])` so the contract is `<attr>#euf#c:call:<attr>(c:<receiver>)::assertion` and the euf key is the coordinate. Receiver term = the lifted receiver (`call:pandas.DataFrame()` etc.), the same way the method path carries its receiver.
3. **Opaque-only: never a `computed` value, never a companion.** An attribute is not foldable; the coordinate is grounded solely by the sworn RHS. Do NOT invent a value (that would be the axiom-fabrication mistake from #3898).
4. **Delete / retire the `py.attr` production** for the assertion-LHS attribute path so there is ONE door (no dual `py.attr` vs `call:<attr>`). Find `py.attr` in the attribute-access floor path (`operations/attribute_lookup_operation.py` / the symbolic `attribute_with` / `attribute_symbolic`) — replace the assertion-relevant emission with the coordinate. If `py.attr` is also used in non-assertion contexts, scope the change so the LHS-of-`==` attribute becomes a coordinate; leave unrelated attribute uses only if they are genuinely a different concern (name it if so).

### Naming decision (make once, up front)
`call:<attr>(receiver)` uses the bare attribute name as the coordinate head (`call:shape`, `call:empty`). This mirrors methods (`call:sum`). Confirm the bare-name head is right vs a type-qualified head (`call:DataFrame.shape`) — bare-name matches the existing method convention and lets `df.shape` and `df2.shape` share the head with the receiver in the arg (congruence works). Recommend bare-name; if you diverge, say why.

## Method calls: leave alone, but PROVE unchanged
`arr.sum() == 6` already produces the right coordinate. Do not touch that path. Add a regression assertion that its euf name is unchanged so the attribute change doesn't perturb it.

## Definition of done (exact, checkable)
1. **Coordinate + euf key:** `pd.DataFrame().shape == (0,0)` lifts to a contract named `shape#euf#c:call:shape(c:call:pandas.DataFrame())::assertion` with inv `= [call:shape(call:pandas.DataFrame()), tuple(0,0)]`. (Adjust exact spelling to match the euf naming helper, but it MUST be coordinate-keyed on `call:shape(...)`, not location-keyed, and MUST NOT contain `py.attr`.)
2. **Discrimination (the soundness DoD):** a witness pair — truthful `assert A() == v` where `A()` returns `df.shape` and the vendor swears `v`, lying `== wrong` — runs through the real solver: **truthful → sat, lying → unsat (refuted).** Add these as seeds in `test_sugar_witness_instruments.py` (the `_call_return_pair`/residue family is the pattern). A lying attribute assertion refuting is the core proof this task worked.
3. **No `py.attr` on the assertion-LHS attribute path** (grep the emitted IR for the probe cases: zero `py.attr`).
4. **Opaque-only:** no `computed`, no derived companion emitted for attributes (they are not foldable). Confirm by inspecting the emitted IR — only the sworn euf fact, no `call:shape(...) == N` derived row.
5. **Methods unchanged:** `arr.sum()` euf name byte-identical to `main` (regression assertion).
6. **Corpus green:** solo-first, then aggregate zero `lie->sat`; numpy/pandas totality gate stays green (attribute access is everywhere in numpy/pandas tests — expect to surface a few construction gaps; drain or file each); battleaxe witness corpus (`bin/bpytest test_witness_verify test_sugar_witness_instruments test_witness_oracle` after `cargo build --workspace --bins`) fully green.
7. **Golden re-bless:** any existing test asserting the `py.attr` shape is updated to the coordinate shape (and its intent preserved — it should now assert the coordinate + discrimination, not the old `py.attr`).

## Hard rules
- **Soundness first:** the discrimination DoD (#2) is the whole point. If a lying attribute assertion does not refute, the task is not done, regardless of green elsewhere.
- **Opaque-only, never fabricate a value** (no `computed`, no companion, no `out >= 0`-style axiom — that was #3898's killed mistake).
- **One door:** delete the `py.attr` assertion path; do not leave both resolvable.
- **Solo-first verification** (hermetic suite as of #3903, but discipline holds); never trust an aggregate run as the only signal.
- pytest: `--import-mode=importlib`, prime `import sugar_lift_py_tests.factory; import sugar_lift_py_tests.context` before `pytest.main`. Deps: `blake3 pynacl cbor2 numpy pandas scikit-learn pytest`, editable `sugar-lift-py-tests`.

## What to read
- #3900 as the euf template: `factory/literal_call_report.py` (`_lift_assert`, `_callee_name`, `_lift_callsite_assertion`, `_emit_euf_fact`, `canonical_euf_callsite_name`) — the method/callsite path you extend to attributes.
- `operations/attribute_lookup_operation.py` + the symbolic `attribute_with` / `attribute_symbolic` — where `py.attr` is produced (to retire on the assertion path).
- `test_sugar_witness_instruments.py` — the residue/witness seed pattern for the discrimination DoD.
- This session's briefs under `docs/superpowers/specs/2026-07-0[89]-*` for the coordinate model and the "opaque-only, vendor-sworn" doctrine.
