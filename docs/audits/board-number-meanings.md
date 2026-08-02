# Board numbers: one name, one meaning

**Law:** construct, or panic. Counts on the sealed board name **one thing each**.  
A number that secretly means several things is the same defect as
`functionsTotal` wearing population + enumerated + clean.

## Already split (the original lie)

| Name | Meaning | One door |
| --- | --- | --- |
| **functionsPopulation** (`functionsTotal` back-compat) | How many functions **exist** on the pin (AST / population) | `seal_functions_population_v1` |
| **functionsEnumerated** | How many the construction door **processed** (roster) | `seal_functions_enumerated_v1` |
| **functionsConstructClean** | How many were **clean** (or refused — never defaulted) | `seal_functions_clean_v1` |
| **functionsUnaccounted** | population − enumerated (derived at compose) | `board_fields_from_sealed_facts` |

Those nearly sealed as one figure. They are three sealed facts.

## Files unit (same shape, was three names for one slot)

| Name | Meaning |
| --- | --- |
| **filesEnrolled** | How many files **exist** on the pin |
| **filesTerminal** | How many we **processed** (got a terminal row) |
| **filesCompleted** | How many **constructed** |
| **filesPanicked** | How many terminals **panicked** (not constructed) |
| **filesMissing** | Enrolled with **no** terminal row |

Aliases (same meaning as enrolled — not a fourth fact): `filesTotal`,
`enrolledFiles`, `populationSize`.

## Residual counts (not kind taxonomies)

| Name | Meaning |
| --- | --- |
| **R_construction_panics** | `len(constructionPanics)` — construction failed loud |
| **R_desugar_construction_panics** | desugar-phase panics only |
| **R_desugar_defects** | desugar defects only |
| **R_desugar_owed_work** / **R_desugar_accounted_semantics** | desugar partition parts when present |
| **R_cm_constructed** / **R_cm_unconstructed** | with-items that constructed vs not |
| **R_defects** | `len(defects)` |

**Deleted as sole residual:** bag totals that summed heterogeneous family tables
into one `R` / `R_construction` / bare `R_desugar` and looked like a single
remaining-work number. Family tables may still appear for owner detail; they
are **not** the residual counter.

## Rule for the next agent

Before sealing a new board field:

1. Name **one** meaning in the field name.  
2. Point at **one** place that computes it.  
3. If two meanings share a spelling, **split** — do not document the overload.
