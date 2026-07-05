// SPDX-License-Identifier: MIT OR Apache-2.0
//
// Formula rewriting and proof tactics.
//
// Before invoking the solver, the verifier applies proof tactics to
// reduce or eliminate the obligation:
//
//   1. Contrapositive: if P → Q is proven, then ¬Q → ¬P is free.
//   2. Sub-formula weakening: if parts of the antecedent are already
//      verified, remove them from the obligation.
//   3. NNF normalization: push negations inward for canonical structure.
//
// These tactics are sound (preserve logical equivalence) and
// complete (don't change the verdict). They only reduce solver load.

use serde_json::Value as Json;

/// Proof tactic result.
pub enum TacticResult {
    /// The obligation was completely discharged by a tactic.
    Discharged { reason: String },
    /// The obligation was reduced to a simpler form.
    Reduced { new_formula: Json, reason: String },
    /// No tactic applied.
    NoChange,
}

/// Try to discharge or reduce an obligation using proof tactics.
///
/// The obligation is an implication: postA → preB (as a formula).
/// We try:
///   1. Direct implication lookup
///   2. Contrapositive: check if preB → postA is proven
///   3. Sub-formula weakening
pub fn apply_tactics(obligation: &Json, pool: &crate::types::MementoPool) -> TacticResult {
    // Tactic 1: Direct implication
    // (Handled by caller via pool.verify_implication)

    // Tactic 2: Contrapositive
    if let Some(result) = try_contrapositive(obligation, pool) {
        return result;
    }

    // Tactic 3: Sub-formula weakening
    if let Some(result) = try_weaken(obligation, pool) {
        return result;
    }

    TacticResult::NoChange
}

/// Contrapositive tactic: if the obligation is ¬Q → ¬P, check if P → Q is proven.
///
/// Logical equivalence: (P → Q) ↔ (¬Q → ¬P)
/// If P → Q is in the pool, then ¬Q → ¬P is discharged for free.
fn try_contrapositive(obligation: &Json, pool: &crate::types::MementoPool) -> Option<TacticResult> {
    // Check if obligation has shape: implies(¬Q, ¬P)
    let (not_q, not_p) = match obligation {
        Json::Object(obj) if obj.get("kind")?.as_str()? == "implies" => {
            let ops = obj.get("operands")?.as_array()?;
            if ops.len() != 2 {
                return None;
            }
            (ops.first()?, ops.get(1)?)
        }
        _ => return None,
    };

    // Check if not_q is actually a negation
    let q = match not_q {
        Json::Object(obj) if obj.get("kind")?.as_str()? == "not" => {
            let ops = obj.get("operands")?.as_array()?;
            ops.first()?
        }
        _ => return None,
    };

    // Check if not_p is actually a negation
    let p = match not_p {
        Json::Object(obj) if obj.get("kind")?.as_str()? == "not" => {
            let ops = obj.get("operands")?.as_array()?;
            ops.first()?
        }
        _ => return None,
    };

    // Build P → Q and check if it's in the pool
    let p_implies_q = Json::Object({
        let mut m = serde_json::Map::new();
        m.insert("kind".to_string(), Json::String("implies".to_string()));
        m.insert(
            "operands".to_string(),
            Json::Array(vec![p.clone(), q.clone()]),
        );
        m
    });

    let p_implies_q_cid = crate::types::compute_formula_cid(&p_implies_q);

    if let Some(memento) = pool.verify_by_hash(&p_implies_q_cid) {
        return Some(TacticResult::Discharged {
            reason: format!(
                "contrapositive: {} → {} proven (memento {})",
                formula_summary(p),
                formula_summary(q),
                short_cid(memento.cid().as_str())
            ),
        });
    }

    None
}

/// Sub-formula weakening: if parts of the antecedent are verified,
/// remove them from the obligation.
///
/// If obligation is (P₁ ∧ P₂) → Q and P₁ is verified, reduce to P₂ → Q.
/// If obligation is P → (Q₁ ∨ Q₂) and Q₁ is verified, discharge entirely.
fn try_weaken(obligation: &Json, pool: &crate::types::MementoPool) -> Option<TacticResult> {
    let (antecedent, consequent) = match obligation {
        Json::Object(obj) if obj.get("kind")?.as_str()? == "implies" => {
            let ops = obj.get("operands")?.as_array()?;
            if ops.len() != 2 {
                return None;
            }
            (ops.first()?, ops.get(1)?)
        }
        _ => return None,
    };

    // Try to weaken the antecedent (remove verified conjuncts)
    let weakened_ant = weaken_formula(antecedent, pool);

    // Try to strengthen the consequent (check if any disjunct is verified)
    if is_formula_verified(consequent, pool) {
        return Some(TacticResult::Discharged {
            reason: "weakening: consequent already verified".to_string(),
        });
    }

    // If antecedent was weakened, rebuild the obligation
    if let Some(new_ant) = weakened_ant {
        if is_trivially_true(&new_ant) {
            return Some(TacticResult::Discharged {
                reason: "weakening: antecedent reduced to true".to_string(),
            });
        }

        let new_obligation = Json::Object({
            let mut m = serde_json::Map::new();
            m.insert("kind".to_string(), Json::String("implies".to_string()));
            m.insert(
                "operands".to_string(),
                Json::Array(vec![new_ant, consequent.clone()]),
            );
            m
        });

        return Some(TacticResult::Reduced {
            new_formula: new_obligation,
            reason: "weakening: removed verified sub-formulas from antecedent".to_string(),
        });
    }

    None
}

/// Remove verified sub-formulas from a formula.
/// Returns Some(reduced) if anything was removed, None otherwise.
fn weaken_formula(formula: &Json, pool: &crate::types::MementoPool) -> Option<Json> {
    match formula {
        Json::Object(obj) => {
            let kind = obj.get("kind")?.as_str()?;
            match kind {
                "and" => {
                    let ops = obj.get("operands")?.as_array()?;
                    let mut new_ops = Vec::new();
                    for op in ops {
                        if !is_formula_verified(op, pool) {
                            new_ops.push(op.clone());
                        }
                    }
                    if new_ops.is_empty() {
                        // All conjuncts verified → true
                        Some(Json::Object({
                            let mut m = serde_json::Map::new();
                            m.insert("kind".to_string(), Json::String("atomic".to_string()));
                            m.insert("name".to_string(), Json::String("true".to_string()));
                            m.insert("args".to_string(), Json::Array(vec![]));
                            m
                        }))
                    } else if new_ops.len() == ops.len() {
                        None // nothing removed
                    } else if new_ops.len() == 1 {
                        Some(new_ops.into_iter().next().unwrap())
                    } else {
                        Some(Json::Object({
                            let mut m = serde_json::Map::new();
                            m.insert("kind".to_string(), Json::String("and".to_string()));
                            m.insert("operands".to_string(), Json::Array(new_ops));
                            m
                        }))
                    }
                }
                _ => None,
            }
        }
        _ => None,
    }
}

/// Check if a formula (or any of its sub-formulas) is verified in the pool.
fn is_formula_verified(formula: &Json, pool: &crate::types::MementoPool) -> bool {
    let cid = crate::types::compute_formula_cid(formula);
    pool.verify_by_hash(&cid).is_some()
}

/// Check if a formula is trivially true.
fn is_trivially_true(formula: &Json) -> bool {
    match formula {
        Json::Object(obj) => match get_str(obj, "kind") {
            Some("atomic") => matches!(get_str(obj, "name"), Some("true")),
            _ => false,
        },
        _ => false,
    }
}

/// Short CID for display (first 16 chars).
fn short_cid(cid: &str) -> String {
    if cid.len() > 16 {
        format!("{}…", &cid[..16])
    } else {
        cid.to_string()
    }
}

/// Helper: safely get a string from a JSON object.
fn get_str<'a>(obj: &'a serde_json::Map<String, Json>, key: &str) -> Option<&'a str> {
    obj.get(key)?.as_str()
}

/// Human-readable summary of a formula (for diagnostics).
fn formula_summary(formula: &Json) -> String {
    match formula {
        Json::Object(obj) => {
            let kind = get_str(obj, "kind").unwrap_or("?");
            match kind {
                "atomic" => {
                    let name = get_str(obj, "name").unwrap_or("?");
                    name.to_string()
                }
                "var" => {
                    let name = get_str(obj, "name").unwrap_or("?");
                    format!("var({})", name)
                }
                "const" => {
                    let val = obj.get("value").unwrap_or(&Json::Null);
                    format!("const({})", val)
                }
                "forall" | "exists" | "choice" => {
                    let name = get_str(obj, "name").unwrap_or("?");
                    format!("{} {}", kind, name)
                }
                "and" | "or" | "implies" => {
                    let count = obj
                        .get("operands")
                        .and_then(|v| v.as_array())
                        .map(|v| v.len())
                        .unwrap_or(0);
                    format!("{}({} ops)", kind, count)
                }
                "not" => "not".to_string(),
                "lambda" | "let" => kind.to_string(),
                _ => kind.to_string(),
            }
        }
        _ => "?".to_string(),
    }
}
