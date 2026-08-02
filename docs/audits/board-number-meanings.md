# Board numbers: one name, one meaning

**Law:** construct, or panic. Counts on the sealed board name **one thing each**.  
A number that secretly means several things is the same defect as
`functionsTotal` wearing population + enumerated + clean.

## Already split (the original lie)

| Name | Meaning | One door |
| --- | --- | --- |
| **functionsPopulation** (`functionsTotal` back-compat) | How many functions **exist** on the pin | `seal_functions_population_v1` |
| **functionsEnumerated** | How many the construction door **processed** | `seal_functions_enumerated_v1` |
| **functionsConstructClean** | How many were **clean** (or refused — never defaulted) | `seal_functions_clean_v1` |
| **functionsUnaccounted** | population − enumerated (derived at compose) | `board_fields_from_sealed_facts` |

## Files unit (distinct quantities)

| Name | Meaning |
| --- | --- |
| **filesEnrolled** | exist on the pin |
| **filesTerminal** | we processed (got a row) |
| **filesCompleted** | constructed |
| **filesPanicked** | terminal but did not construct |
| **filesMissing** | enrolled, no terminal row |

Aliases of enrolled only: `filesTotal`, `enrolledFiles`, `populationSize`.

## Residual counts (quantities, not failure kinds)

| Name | Meaning |
| --- | --- |
| **R_construction_panics** | `len(constructionPanics)` |
| **R_desugar_construction_panics** | desugar-phase panics only |
| **R_cm_constructed** / **R_cm_unconstructed** | with-items that constructed vs not |

### Dropped — kinds wearing counts (do not re-seal)

| Was | Why dropped |
| --- | --- |
| **R_desugar_defects** | “Defect” = Exception path vs ConstructionPanic — a **kind of failure**, not a second quantity. Under the law, failed construction is panic. |
| **R_desugar_owed_work** (typed-refusal) | Outcome label for SugarNotWritten rows in a mixed R_desugar bag — **kind of row**, not a separate physical count of enrolled work. |
| **R_desugar_accounted_semantics** (constructed-effect) | Successful desugar products (Incomplete/effect) counted as residual — **not unwritten work at all**. The 7.6× lie. |
| **R** / **R_construction** family bag | Sum of heterogeneous owner tags as one residual. |
| Bare **R_desugar** bag | Sum of refusal + effect rows as one remaining-work number. |

## Rule

Before sealing a field: is this a **quantity that exists regardless of failure labels**
(enrolled vs terminal, constructed vs panicked), or a **kind of failure**?
Ship only the first.
