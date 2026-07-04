// SPDX-License-Identifier: MIT OR Apache-2.0
//
// outlives.rs: C.9 region-quantifier composition + substitution.
// Implements `compose_region_demands` per protocol/specs/2026-05-05-outlives-kernel-axioms.md §4.

use std::collections::HashMap;

/// A region fact: `r_a` outlives `r_b` (r_a lives at least as long as r_b).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RegionFact {
    pub longer: String,
    pub shorter: String,
}

/// Summarizes a caller's region knowledge: explicit Outlives facts from
/// the contract's `region_facts` field, plus the implicit axioms.
#[derive(Debug, Clone, Default)]
pub struct RegionGraph {
    facts: Vec<RegionFact>,
    regions: Vec<String>,
}

impl RegionGraph {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn add_fact(&mut self, longer: &str, shorter: &str) {
        self.facts.push(RegionFact {
            longer: longer.to_string(),
            shorter: shorter.to_string(),
        });
        self.regions.push(longer.to_string());
        self.regions.push(shorter.to_string());
    }

    pub fn add_region(&mut self, region: &str) {
        if !self.regions.contains(&region.to_string()) {
            self.regions.push(region.to_string());
        }
    }

    /// Check whether `a` outlives `b` under the three kernel axioms:
    ///   1. Reflexivity: a == b → true
    ///   2. Direct fact: a → b edge in the graph
    ///   3. 'static top: any region outlives 'static
    ///   4. Transitivity: a → ... → b via graph edges (DFS)
    pub fn check(&self, a: &str, b: &str) -> DischargeOutcome {
        // Axiom 1: reflexivity
        if a == b {
            return DischargeOutcome::Discharged;
        }

        // Axiom 3: 'static top: any region outlives 'static
        // When b is 'static, a always outlives it.
        if b == "'static" || a == "'static" {
            return DischargeOutcome::Discharged;
        }

        // Axiom 2: direct fact
        if self.facts.iter().any(|f| f.longer == a && f.shorter == b) {
            return DischargeOutcome::Discharged;
        }

        // Axiom 4: transitivity via DFS reachability
        if self.reachable(a, b, &mut Vec::new()) {
            return DischargeOutcome::Discharged;
        }

        DischargeOutcome::Refused {
            a: a.to_string(),
            b: b.to_string(),
        }
    }

    fn reachable(&self, from: &str, to: &str, visited: &mut Vec<String>) -> bool {
        if from == to {
            return true;
        }
        if visited.contains(&from.to_string()) {
            return false;
        }
        visited.push(from.to_string());
        self.facts
            .iter()
            .filter(|f| f.longer == from)
            .any(|f| self.reachable(&f.shorter, to, visited))
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum DischargeOutcome {
    Discharged,
    Refused { a: String, b: String },
}

/// Build a region substitution from callee formal regions to caller actual regions.
/// Maps each callee formal region name → caller actual region name.
pub fn build_region_subst(
    callee_formal_regions: &[Option<String>],
    caller_actual_regions: &[Option<String>],
) -> HashMap<String, String> {
    let mut subst = HashMap::new();
    for (formal, actual) in callee_formal_regions
        .iter()
        .zip(caller_actual_regions.iter())
    {
        if let (Some(f), Some(a)) = (formal, actual) {
            subst.insert(f.clone(), a.clone());
        }
    }
    subst
}

/// Compose region demands: substitute callee's region predicates,
/// then discharge each against the caller's region graph.
/// Returns Ok(()) if all demands discharge, or Err(list of undischarged pairs).
pub fn compose_region_demands(
    caller_graph: &RegionGraph,
    callee_pre_outlives: &[(String, String)],
    region_subst: &HashMap<String, String>,
) -> Result<(), Vec<(String, String)>> {
    let mut failures = Vec::new();
    for (callee_a, callee_b) in callee_pre_outlives {
        let a = region_subst
            .get(callee_a)
            .map(|s| s.as_str())
            .unwrap_or(callee_a.as_str());
        let b = region_subst
            .get(callee_b)
            .map(|s| s.as_str())
            .unwrap_or(callee_b.as_str());
        if matches!(caller_graph.check(a, b), DischargeOutcome::Refused { .. }) {
            failures.push((a.to_string(), b.to_string()));
        }
    }
    if failures.is_empty() {
        Ok(())
    } else {
        Err(failures)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_succeeds() {
        let g = RegionGraph::new();
        assert!(compose_region_demands(&g, &[], &HashMap::new()).is_ok());
    }

    #[test]
    fn substitution_then_reflexivity() {
        let g = RegionGraph::new();
        let subst = HashMap::from([("'a".to_string(), "'x".to_string())]);
        assert!(
            compose_region_demands(&g, &[("'a".to_string(), "'a".to_string())], &subst).is_ok()
        );
    }

    #[test]
    fn substitution_then_static_top() {
        let g = RegionGraph::new();
        let subst = HashMap::from([
            ("'a".to_string(), "'static".to_string()),
            ("'b".to_string(), "'x".to_string()),
        ]);
        assert!(
            compose_region_demands(&g, &[("'a".to_string(), "'b".to_string())], &subst).is_ok()
        );
    }

    #[test]
    fn substitution_then_caller_fact() {
        let mut g = RegionGraph::new();
        g.add_fact("'x", "'y");
        let subst = HashMap::from([
            ("'a".to_string(), "'x".to_string()),
            ("'b".to_string(), "'y".to_string()),
        ]);
        assert!(
            compose_region_demands(&g, &[("'a".to_string(), "'b".to_string())], &subst).is_ok()
        );
    }

    #[test]
    fn refuse_when_unrelated() {
        let g = RegionGraph::new();
        let subst = HashMap::from([
            ("'a".to_string(), "'x".to_string()),
            ("'b".to_string(), "'y".to_string()),
        ]);
        let r = compose_region_demands(&g, &[("'a".to_string(), "'b".to_string())], &subst);
        assert_eq!(r, Err(vec![("'x".to_string(), "'y".to_string())]));
    }

    #[test]
    fn substitution_then_transitivity() {
        let mut g = RegionGraph::new();
        g.add_fact("'x", "'y");
        g.add_fact("'y", "'z");
        let subst = HashMap::from([
            ("'a".to_string(), "'x".to_string()),
            ("'b".to_string(), "'z".to_string()),
        ]);
        assert!(
            compose_region_demands(&g, &[("'a".to_string(), "'b".to_string())], &subst).is_ok()
        );
    }

    #[test]
    fn collects_multiple_failures() {
        let g = RegionGraph::new();
        let subst = HashMap::new();
        let demands = vec![
            ("'a".to_string(), "'b".to_string()),
            ("'c".to_string(), "'d".to_string()),
            ("'e".to_string(), "'e".to_string()), // reflexivity: succeeds
        ];
        let r = compose_region_demands(&g, &demands, &subst);
        assert!(r.is_err());
        assert_eq!(r.unwrap_err().len(), 2);
    }

    #[test]
    fn reflexivity_self() {
        let g = RegionGraph::new();
        assert!(matches!(g.check("'a", "'a"), DischargeOutcome::Discharged));
    }

    #[test]
    fn static_top_anything() {
        let g = RegionGraph::new();
        assert!(matches!(
            g.check("'any", "'static"),
            DischargeOutcome::Discharged
        ));
    }

    #[test]
    fn direct_fact_succeeds() {
        let mut g = RegionGraph::new();
        g.add_fact("'x", "'y");
        assert!(matches!(g.check("'x", "'y"), DischargeOutcome::Discharged));
    }
}
