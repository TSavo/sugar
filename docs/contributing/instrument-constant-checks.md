# Instrument constant-checks (the law)

> **A check that can only return one answer is not a check.**
> It is a constant dressed as a judgment.
> Delete it, or give it a second honest answer.

Sibling to `docs/contributing/measurement-conditions.md` (a number without quiet /
lease / pin is a guess). This law is one level down: even under good
conditions, an **instrument whose shape admits only one outcome** cannot
measure. It can only ratify.

## The law

An instrument (type assertion, door, ground, ratio, roster, walk status) is a
**check** only if, for the case under test, at least two answers are
representable and the instrument can return the wrong one when the world is
wrong.

If the domain, codomain, default, or arithmetic makes every other answer
unrepresentable, the thing is a **constant**. Constants look like checks in
code review and on boards. They are worse than no instrument: they mint
**unearned health** or a **confident wrong residual**.

The constant need not be `True`. Tonight the wrong constants were also
`foreign-target`, `not a term`, `clean = 1.0`, `0 functions`, and `fast`.

## Tonight's four hierarchy lies (fit this frame)

| mass | lie | the constant | what a real check needs |
| ---: | --- | --- | --- |
| **122** | ConstructedTerm base missing — type said a spread was not a term | Type closed before construction's codomain: legal spreads had only one answer (**not a term**) | Type / trait that admits what construction actually produces (`SpreadCollectionSugar` is a term) |
| **24** | `require_target_pattern` wrong door — empty enrollment dressed as foreign-target | Door had no **empty** outcome; empty always became **foreign-target** | A door that can report "no pattern enrolled" without inventing a foreign target |
| **6** | GuardedBinding wrong kind — called `.sugar()` on a binding state | Kind hierarchy treated binding state as sugar-bearing; no second answer "not sugar territory" until loud wrong-kind | Dispatch/type that refuses `.sugar()` on binding state as unconstructable, not as a late AttributeError |
| **7** | `If.substitute` slot recomputed — foreign address for the same condition | Recompute from a rewritten test **cannot** preserve identity; "same condition?" only answers **foreign** | Carry the authenticated slot; identity is a value, not a recomputed judgment |

All four are hierarchy / construction lies. All four share the shape: the
instrument could not say the true alternative. They are not four different
bug classes; they are one class wearing four costumes.

**Narrower true version (if someone tries to widen past tonight):** the law is
not "every bug is a constant check." It is: when a **typed door, kind test,
ground, or ratio** is used as a residual or health instrument, and its
observable has only one inhabitated outcome for the live case, that instrument
is lying by construction. Fix the codomain (or the carry), not the count.

## Three instruments reporting unearned health (same shape)

| lie | the constant | what a real check needs |
| --- | --- | --- |
| Zero-function rosters from a `TypeError` that erased the whole file | Error path collapses population to **0**; empty roster reads as nothing-wrong | Error must preserve or refuse the authenticated function denominator, not delete it |
| `clean%` that could only ever read **1.0** | Numerator defaults toward denominator, or blind rows contribute 0 to both num and denom — ratio is structurally one | Refuse the ratio when unaccounted/blind mass exists (`cleanRatioRefused`); never mint 1.0 from collapse |
| A "fast" walk that was fast because **159 files aborted in milliseconds** | Walk status treated abort-as-done as success; wall-clock only answers **fast** | Status must distinguish completed construction from abort; speed without population is not speed |

These are the measurement-facing face of the same law. Measurement conditions
(quiet / lease / pin) stop you from citing a number taken under the wrong
world. This law stops you from citing a number produced by an instrument that
**cannot fail in the way the world fails**.

## How to apply

Before trusting a residual bucket, a clean ratio, a ground, or a type-narrowing
"check":

1. **Name the second answer.** What would red look like for this instrument on
   this case? If you cannot name it, you have a constant.
2. **Prefer unrepresentable over audited.** A type that cannot construct the
   illegal shape beats a ratio that promises to stay honest. Climb the
   enforcement ladder; do not add a second constant to watch the first.

## Forbidden

- Shipping a ground whose `holds()` is always `True` as if it discriminated.
- Dressing empty enrollment as a foreign residual because the door has no empty.
- Narrowing a type so legal construction is unrepresentable, then counting the
  refuse as kit incomplete.
- Minting `clean% = 1.0` when the denominator was collapsed, blinded, or equal
  by construction to the numerator.
- Calling wall-clock "progress" when the work aborted the population.

---

*Banked after the 2026-08-02 hierarchy / measurement night. The four residual
masses and three unearned-health instruments are the argument. The sentence is
the law. Do not retire this file into folklore — when a new constant-check
appears, add a row, then delete the constant.*
