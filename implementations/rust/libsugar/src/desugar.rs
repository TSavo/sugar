// SPDX-License-Identifier: MIT OR Apache-2.0

use std::collections::{BTreeMap, BTreeSet};
use std::fmt;
use std::fs;
use std::path::Path;

use serde::{Deserialize, Serialize};
use serde_json::Value as JsonValue;
use sugar_ir_types::{IrTerm, Sort};

use crate::canonical::serializable_jcs;
use crate::SugarError;

const MAX_REWRITE_STEPS: usize = 10_000;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RefusalKind {
    NonConfluentDesugaringSet,
    NonTerminatingDesugaringSet,
    InvalidDesugaringEquation,
    WpPreservationNotDischarged,
}

impl RefusalKind {
    pub fn as_str(&self) -> &'static str {
        match self {
            RefusalKind::NonConfluentDesugaringSet => "non-confluent-desugaring-set",
            RefusalKind::NonTerminatingDesugaringSet => "non-terminating-desugaring-set",
            RefusalKind::InvalidDesugaringEquation => "invalid-desugaring-equation",
            RefusalKind::WpPreservationNotDischarged => "wp-preservation-not-discharged",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Refusal {
    pub kind: RefusalKind,
    pub message: String,
    pub equations: Vec<String>,
}

impl Refusal {
    pub fn new(kind: RefusalKind, message: impl Into<String>, equations: Vec<String>) -> Self {
        Self {
            kind,
            message: message.into(),
            equations,
        }
    }

    pub fn kind(&self) -> &'static str {
        self.kind.as_str()
    }
}

impl fmt::Display for Refusal {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}: {}", self.kind.as_str(), self.message)
    }
}

impl std::error::Error for Refusal {}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct WpObligation {
    #[serde(default)]
    pub kind: String,
    pub status: String,
    #[serde(default)]
    pub method: Option<String>,
    #[serde(flatten)]
    pub extra: BTreeMap<String, JsonValue>,
}

#[derive(Debug, Clone)]
pub struct DesugarRule {
    pub fn_name: String,
    lhs: EquationTerm,
    rhs: EquationTerm,
    pub wp_obligation: WpObligation,
}

impl DesugarRule {
    pub fn from_json_value(value: JsonValue) -> std::result::Result<Self, Refusal> {
        Self::try_from_json_value(value)?.ok_or_else(|| {
            Refusal::new(
                RefusalKind::InvalidDesugaringEquation,
                "equation is not tagged as a desugaring equation",
                vec![],
            )
        })
    }

    pub fn try_from_json_value(value: JsonValue) -> std::result::Result<Option<Self>, Refusal> {
        let object = value.as_object().ok_or_else(|| {
            Refusal::new(
                RefusalKind::InvalidDesugaringEquation,
                "equation memento must be a JSON object",
                vec![],
            )
        })?;

        if string_field(object, "kind") != Some("equation") {
            return Ok(None);
        }

        let fn_name = required_string(object, "fn_name")?;
        let role = string_field(object, "role");
        if !matches!(role, Some("desugaring") | Some("macro-expansion")) {
            return Ok(None);
        }

        let direction = string_field(object, "direction").ok_or_else(|| {
            Refusal::new(
                RefusalKind::InvalidDesugaringEquation,
                format!("{fn_name} is missing direction"),
                vec![fn_name.clone()],
            )
        })?;
        if direction != "left-to-right" && direction != "desugar" {
            return Err(Refusal::new(
                RefusalKind::InvalidDesugaringEquation,
                format!("{fn_name} has unsupported direction {direction:?}"),
                vec![fn_name],
            ));
        }

        // A `pre` side-condition gates the rewrite; the rewriter does not yet
        // evaluate side-conditions, so a non-trivially-true `pre` must be
        // refused rather than silently ignored (which would fire the rule
        // unconditionally). Refuse, don't ignore.
        if let Some(pre) = object.get("pre") {
            if !is_trivially_true(pre) {
                return Err(Refusal::new(
                    RefusalKind::InvalidDesugaringEquation,
                    format!(
                        "{fn_name} has a non-trivial `pre` side-condition; \
                         conditional desugaring equations are not yet supported"
                    ),
                    vec![fn_name],
                ));
            }
        }

        let post = object
            .get("post")
            .and_then(JsonValue::as_object)
            .ok_or_else(|| {
                Refusal::new(
                    RefusalKind::InvalidDesugaringEquation,
                    format!("{fn_name} is missing post equation"),
                    vec![fn_name.clone()],
                )
            })?;
        if string_field(post, "kind") != Some("equation") {
            return Err(Refusal::new(
                RefusalKind::InvalidDesugaringEquation,
                format!("{fn_name} post.kind must be equation"),
                vec![fn_name],
            ));
        }

        let lhs = EquationTerm::from_json(post.get("lhs").ok_or_else(|| {
            Refusal::new(
                RefusalKind::InvalidDesugaringEquation,
                format!("{fn_name} post is missing lhs"),
                vec![fn_name.clone()],
            )
        })?)?;
        let rhs = EquationTerm::from_json(post.get("rhs").ok_or_else(|| {
            Refusal::new(
                RefusalKind::InvalidDesugaringEquation,
                format!("{fn_name} post is missing rhs"),
                vec![fn_name.clone()],
            )
        })?)?;

        let wp_obligation = extract_wp_obligation(object, &fn_name)?;
        if wp_obligation.status != "discharged" {
            return Err(Refusal::new(
                RefusalKind::WpPreservationNotDischarged,
                format!(
                    "{fn_name} wp-preservation obligation is not discharged: {}",
                    wp_obligation.status
                ),
                vec![fn_name],
            ));
        }

        Ok(Some(Self {
            fn_name,
            lhs,
            rhs,
            wp_obligation,
        }))
    }

    fn lhs_root(&self) -> Option<&str> {
        self.lhs.root_op_name()
    }
}

#[derive(Debug, Clone)]
pub struct DesugaringSet {
    rules: Vec<DesugarRule>,
}

impl DesugaringSet {
    pub fn new(mut rules: Vec<DesugarRule>) -> std::result::Result<Self, Refusal> {
        rules.sort_by(|a, b| a.fn_name.cmp(&b.fn_name));
        certify_termination(&rules)?;
        certify_confluence(&rules)?;
        Ok(Self { rules })
    }

    pub fn rules(&self) -> &[DesugarRule] {
        &self.rules
    }

    pub fn non_core_ops(
        &self,
        term: &IrTerm,
        core_ops: &BTreeSet<String>,
    ) -> std::result::Result<BTreeSet<String>, Refusal> {
        let mut found = BTreeSet::new();
        collect_non_core_ops(term, core_ops, &mut found);
        Ok(found)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct DesugarOutput {
    pub normal_form: IrTerm,
    pub canonical_bytes: Vec<u8>,
    pub cid: String,
    pub applied_rules: Vec<String>,
    pub wp_obligations: Vec<WpObligation>,
}

pub fn load_desugaring_rules_from_dir(
    path: &Path,
) -> std::result::Result<Vec<DesugarRule>, Refusal> {
    let entries = fs::read_dir(path).map_err(|e| {
        Refusal::new(
            RefusalKind::InvalidDesugaringEquation,
            format!("read {}: {e}", path.display()),
            vec![],
        )
    })?;
    let mut rules = Vec::new();
    for entry in entries {
        let entry = entry.map_err(|e| {
            Refusal::new(
                RefusalKind::InvalidDesugaringEquation,
                format!("read {} entry: {e}", path.display()),
                vec![],
            )
        })?;
        let file_name = entry.file_name();
        let file_name = file_name.to_string_lossy();
        if !file_name.starts_with("eq_") || !file_name.ends_with(".spec.json") {
            continue;
        }
        let bytes = fs::read(entry.path()).map_err(|e| {
            Refusal::new(
                RefusalKind::InvalidDesugaringEquation,
                format!("read {}: {e}", entry.path().display()),
                vec![],
            )
        })?;
        let value: JsonValue = serde_json::from_slice(&bytes).map_err(|e| {
            Refusal::new(
                RefusalKind::InvalidDesugaringEquation,
                format!("parse {}: {e}", entry.path().display()),
                vec![],
            )
        })?;
        if let Some(rule) = DesugarRule::try_from_json_value(value)? {
            rules.push(rule);
        }
    }
    rules.sort_by(|a, b| a.fn_name.cmp(&b.fn_name));
    Ok(rules)
}

pub fn desugar(set: &DesugaringSet, term: IrTerm) -> std::result::Result<DesugarOutput, Refusal> {
    let mut current = term;
    let mut applied_rules = Vec::new();
    let mut wp_obligations = Vec::new();

    for _ in 0..MAX_REWRITE_STEPS {
        let (next, applied) = rewrite_once_innermost(set, current)?;
        if let Some(applied) = applied {
            applied_rules.push(applied.rule_name);
            wp_obligations.push(applied.wp_obligation);
            current = next;
        } else {
            let canonical = serializable_jcs(&next).map_err(refusal_from_error)?;
            let cid = sugar_canonicalizer::blake3_512_of(canonical.as_bytes());
            return Ok(DesugarOutput {
                normal_form: next,
                canonical_bytes: canonical.into_bytes(),
                cid,
                applied_rules,
                wp_obligations,
            });
        }
    }

    Err(Refusal::new(
        RefusalKind::NonTerminatingDesugaringSet,
        format!("desugar exceeded {MAX_REWRITE_STEPS} rewrite steps"),
        applied_rules,
    ))
}

fn refusal_from_error(error: SugarError) -> Refusal {
    Refusal::new(
        RefusalKind::InvalidDesugaringEquation,
        error.to_string(),
        vec![],
    )
}

#[derive(Debug, Clone)]
struct AppliedRewrite {
    rule_name: String,
    wp_obligation: WpObligation,
}

fn rewrite_once_innermost(
    set: &DesugaringSet,
    term: IrTerm,
) -> std::result::Result<(IrTerm, Option<AppliedRewrite>), Refusal> {
    match term {
        IrTerm::Ctor { name, args } => {
            let mut next_args = Vec::with_capacity(args.len());
            let mut iter = args.into_iter();
            while let Some(arg) = iter.next() {
                let (next_arg, applied) = rewrite_once_innermost(set, arg)?;
                next_args.push(next_arg);
                if applied.is_some() {
                    next_args.extend(iter);
                    return Ok((
                        IrTerm::Ctor {
                            name,
                            args: next_args,
                        },
                        applied,
                    ));
                }
            }

            let rebuilt = IrTerm::Ctor {
                name,
                args: next_args,
            };
            for rule in &set.rules {
                if let Some(bindings) = match_lhs(rule, &rebuilt) {
                    let replacement = rule.rhs.substitute(&bindings, &rule.fn_name)?;
                    return Ok((
                        replacement,
                        Some(AppliedRewrite {
                            rule_name: rule.fn_name.clone(),
                            wp_obligation: rule.wp_obligation.clone(),
                        }),
                    ));
                }
            }
            Ok((rebuilt, None))
        }
        IrTerm::Lambda {
            param_name,
            param_sort,
            body,
        } => {
            let (next_body, applied) = rewrite_once_innermost(set, *body)?;
            Ok((
                IrTerm::Lambda {
                    param_name,
                    param_sort,
                    body: Box::new(next_body),
                },
                applied,
            ))
        }
        IrTerm::Let { bindings, body } => {
            let mut next_bindings = Vec::with_capacity(bindings.len());
            let mut iter = bindings.into_iter();
            while let Some(binding) = iter.next() {
                let (bound_term, applied) = rewrite_once_innermost(set, binding.bound_term)?;
                next_bindings.push(sugar_ir_types::LetBinding {
                    name: binding.name,
                    bound_term,
                });
                if applied.is_some() {
                    next_bindings.extend(iter);
                    return Ok((
                        IrTerm::Let {
                            bindings: next_bindings,
                            body,
                        },
                        applied,
                    ));
                }
            }
            let (next_body, applied) = rewrite_once_innermost(set, *body)?;
            Ok((
                IrTerm::Let {
                    bindings: next_bindings,
                    body: Box::new(next_body),
                },
                applied,
            ))
        }
        IrTerm::Var { .. } | IrTerm::Const { .. } => Ok((term, None)),
    }
}

fn match_lhs(rule: &DesugarRule, term: &IrTerm) -> Option<BTreeMap<String, IrTerm>> {
    let mut bindings = BTreeMap::new();
    if match_pattern(&rule.lhs, term, &mut bindings) {
        Some(bindings)
    } else {
        None
    }
}

fn match_pattern(
    pattern: &EquationTerm,
    term: &IrTerm,
    bindings: &mut BTreeMap<String, IrTerm>,
) -> bool {
    match pattern {
        EquationTerm::Var { name } => match bindings.get(name) {
            Some(bound) => bound == term,
            None => {
                bindings.insert(name.clone(), term.clone());
                true
            }
        },
        EquationTerm::Const { value, sort } => match term {
            IrTerm::Const {
                value: term_value,
                sort: term_sort,
            } => term_value == value && term_sort == sort,
            _ => false,
        },
        EquationTerm::Unit => matches!(
            term,
            IrTerm::Ctor { name, args } if (name == "unit" || name.ends_with(":unit")) && args.is_empty()
        ),
        EquationTerm::Op { name, args } => match term {
            IrTerm::Ctor {
                name: term_name,
                args: term_args,
            } => {
                names_alias(name, term_name)
                    && args.len() == term_args.len()
                    && args
                        .iter()
                        .zip(term_args.iter())
                        .all(|(p, t)| match_pattern(p, t, bindings))
            }
            _ => false,
        },
    }
}

fn certify_termination(rules: &[DesugarRule]) -> std::result::Result<(), Refusal> {
    let mut roots = Vec::new();
    for rule in rules {
        let Some(root) = rule.lhs_root() else {
            return Err(Refusal::new(
                RefusalKind::InvalidDesugaringEquation,
                format!("{} lhs root must be an op", rule.fn_name),
                vec![rule.fn_name.clone()],
            ));
        };
        roots.push((rule.fn_name.clone(), root.to_string()));
    }

    let mut graph: BTreeMap<String, BTreeSet<String>> = BTreeMap::new();
    for (fn_name, root) in &roots {
        let rule = rules
            .iter()
            .find(|candidate| candidate.fn_name == *fn_name)
            .expect("root table came from rules");
        let rhs_ops = rule.rhs.op_names();
        let mut edges = BTreeSet::new();
        for (_, candidate_root) in &roots {
            if rhs_ops.iter().any(|op| names_alias(op, candidate_root)) {
                edges.insert(candidate_root.clone());
            }
        }
        graph.insert(root.clone(), edges);
    }

    let mut visiting = BTreeSet::new();
    let mut visited = BTreeSet::new();
    for (_, root) in &roots {
        if has_cycle(root, &graph, &mut visiting, &mut visited) {
            let equations = roots
                .iter()
                .filter(|(_, candidate_root)| graph_reaches(candidate_root, root, &graph))
                .map(|(fn_name, _)| fn_name.clone())
                .collect();
            return Err(Refusal::new(
                RefusalKind::NonTerminatingDesugaringSet,
                format!("desugaring rule dependency graph contains a cycle at {root}"),
                equations,
            ));
        }
    }

    Ok(())
}

fn has_cycle(
    node: &str,
    graph: &BTreeMap<String, BTreeSet<String>>,
    visiting: &mut BTreeSet<String>,
    visited: &mut BTreeSet<String>,
) -> bool {
    if visited.contains(node) {
        return false;
    }
    if !visiting.insert(node.to_string()) {
        return true;
    }
    for next in graph.get(node).into_iter().flatten() {
        if has_cycle(next, graph, visiting, visited) {
            return true;
        }
    }
    visiting.remove(node);
    visited.insert(node.to_string());
    false
}

fn graph_reaches(start: &str, target: &str, graph: &BTreeMap<String, BTreeSet<String>>) -> bool {
    let mut stack = vec![start.to_string()];
    let mut seen = BTreeSet::new();
    while let Some(node) = stack.pop() {
        if !seen.insert(node.clone()) {
            continue;
        }
        if node == target {
            return true;
        }
        if let Some(nexts) = graph.get(&node) {
            stack.extend(nexts.iter().cloned());
        }
    }
    false
}

fn certify_confluence(rules: &[DesugarRule]) -> std::result::Result<(), Refusal> {
    for (idx, left) in rules.iter().enumerate() {
        for right in rules.iter().skip(idx + 1) {
            if patterns_unify(&left.lhs, &right.lhs) && left.rhs != right.rhs {
                return Err(Refusal::new(
                    RefusalKind::NonConfluentDesugaringSet,
                    format!(
                        "{} and {} have overlapping left-hand patterns",
                        left.fn_name, right.fn_name
                    ),
                    vec![left.fn_name.clone(), right.fn_name.clone()],
                ));
            }

            if left.lhs.contains_unifiable_subpattern(&right.lhs)
                || right.lhs.contains_unifiable_subpattern(&left.lhs)
            {
                return Err(Refusal::new(
                    RefusalKind::NonConfluentDesugaringSet,
                    format!(
                        "{} and {} have nested left-hand-pattern overlap",
                        left.fn_name, right.fn_name
                    ),
                    vec![left.fn_name.clone(), right.fn_name.clone()],
                ));
            }
        }
    }
    Ok(())
}

fn patterns_unify(left: &EquationTerm, right: &EquationTerm) -> bool {
    match (left, right) {
        (EquationTerm::Var { .. }, _) | (_, EquationTerm::Var { .. }) => true,
        (EquationTerm::Unit, EquationTerm::Unit) => true,
        (
            EquationTerm::Const {
                value: left_value,
                sort: left_sort,
            },
            EquationTerm::Const {
                value: right_value,
                sort: right_sort,
            },
        ) => left_value == right_value && left_sort == right_sort,
        (
            EquationTerm::Op {
                name: left_name,
                args: left_args,
            },
            EquationTerm::Op {
                name: right_name,
                args: right_args,
            },
        ) => {
            names_alias(left_name, right_name)
                && left_args.len() == right_args.len()
                && left_args
                    .iter()
                    .zip(right_args.iter())
                    .all(|(left_arg, right_arg)| patterns_unify(left_arg, right_arg))
        }
        _ => false,
    }
}

#[derive(Debug, Clone, PartialEq)]
enum EquationTerm {
    Var {
        name: String,
    },
    Op {
        name: String,
        args: Vec<EquationTerm>,
    },
    Const {
        value: JsonValue,
        sort: Sort,
    },
    Unit,
}

impl EquationTerm {
    fn from_json(value: &JsonValue) -> std::result::Result<Self, Refusal> {
        let object = value.as_object().ok_or_else(|| {
            Refusal::new(
                RefusalKind::InvalidDesugaringEquation,
                "equation term must be a JSON object",
                vec![],
            )
        })?;
        let kind = string_field(object, "kind").ok_or_else(|| {
            Refusal::new(
                RefusalKind::InvalidDesugaringEquation,
                "equation term is missing kind",
                vec![],
            )
        })?;
        match kind {
            "var" => Ok(EquationTerm::Var {
                name: required_string(object, "name")?,
            }),
            "op" | "ctor" => {
                let name = required_string(object, "name")?;
                let args = object
                    .get("args")
                    .and_then(JsonValue::as_array)
                    .ok_or_else(|| {
                        Refusal::new(
                            RefusalKind::InvalidDesugaringEquation,
                            format!("op {name} is missing args"),
                            vec![],
                        )
                    })?
                    .iter()
                    .map(EquationTerm::from_json)
                    .collect::<std::result::Result<Vec<_>, _>>()?;
                Ok(EquationTerm::Op { name, args })
            }
            "const" => {
                let sort = object
                    .get("sort")
                    .map(parse_sort)
                    .transpose()?
                    .unwrap_or_else(|| Sort::Primitive {
                        name: "Any".to_string(),
                    });
                let value = object.get("value").cloned().ok_or_else(|| {
                    Refusal::new(
                        RefusalKind::InvalidDesugaringEquation,
                        "const term is missing value",
                        vec![],
                    )
                })?;
                Ok(EquationTerm::Const { value, sort })
            }
            "unit" => Ok(EquationTerm::Unit),
            _ => Err(Refusal::new(
                RefusalKind::InvalidDesugaringEquation,
                format!("unsupported equation term kind {kind:?}"),
                vec![],
            )),
        }
    }

    fn substitute(
        &self,
        bindings: &BTreeMap<String, IrTerm>,
        rule_name: &str,
    ) -> std::result::Result<IrTerm, Refusal> {
        match self {
            EquationTerm::Var { name } => bindings.get(name).cloned().ok_or_else(|| {
                Refusal::new(
                    RefusalKind::InvalidDesugaringEquation,
                    format!("{rule_name} rhs references unbound variable {name}"),
                    vec![rule_name.to_string()],
                )
            }),
            EquationTerm::Op { name, args } => Ok(IrTerm::Ctor {
                name: name.clone(),
                args: args
                    .iter()
                    .map(|arg| arg.substitute(bindings, rule_name))
                    .collect::<std::result::Result<Vec<_>, _>>()?,
            }),
            EquationTerm::Const { value, sort } => Ok(IrTerm::Const {
                value: value.clone(),
                sort: sort.clone(),
            }),
            EquationTerm::Unit => Ok(IrTerm::Ctor {
                name: "unit".to_string(),
                args: vec![],
            }),
        }
    }

    fn root_op_name(&self) -> Option<&str> {
        match self {
            EquationTerm::Op { name, .. } => Some(name),
            EquationTerm::Var { .. } | EquationTerm::Const { .. } | EquationTerm::Unit => None,
        }
    }

    fn op_names(&self) -> BTreeSet<String> {
        let mut names = BTreeSet::new();
        self.collect_op_names(&mut names);
        names
    }

    fn collect_op_names(&self, names: &mut BTreeSet<String>) {
        if let EquationTerm::Op { name, args } = self {
            names.insert(name.clone());
            for arg in args {
                arg.collect_op_names(names);
            }
        }
    }

    fn contains_unifiable_subpattern(&self, needle: &EquationTerm) -> bool {
        match self {
            EquationTerm::Op { args, .. } => args.iter().any(|arg| match arg {
                EquationTerm::Var { .. } => false,
                _ => patterns_unify(arg, needle) || arg.contains_unifiable_subpattern(needle),
            }),
            EquationTerm::Var { .. } | EquationTerm::Const { .. } | EquationTerm::Unit => false,
        }
    }
}

fn parse_sort(value: &JsonValue) -> std::result::Result<Sort, Refusal> {
    if let Some(object) = value.as_object() {
        if string_field(object, "kind") == Some("ctor") {
            return Ok(Sort::Primitive {
                name: required_string(object, "name")?,
            });
        }
    }
    serde_json::from_value(value.clone()).map_err(|e| {
        Refusal::new(
            RefusalKind::InvalidDesugaringEquation,
            format!("const sort is invalid: {e}"),
            vec![],
        )
    })
}

fn collect_non_core_ops(term: &IrTerm, core_ops: &BTreeSet<String>, found: &mut BTreeSet<String>) {
    match term {
        IrTerm::Ctor { name, args } => {
            if !core_ops.contains(name) {
                found.insert(name.clone());
            }
            for arg in args {
                collect_non_core_ops(arg, core_ops, found);
            }
        }
        IrTerm::Lambda { body, .. } => collect_non_core_ops(body, core_ops, found),
        IrTerm::Let { bindings, body } => {
            for binding in bindings {
                collect_non_core_ops(&binding.bound_term, core_ops, found);
            }
            collect_non_core_ops(body, core_ops, found);
        }
        IrTerm::Var { .. } | IrTerm::Const { .. } => {}
    }
}

fn extract_wp_obligation(
    object: &serde_json::Map<String, JsonValue>,
    fn_name: &str,
) -> std::result::Result<WpObligation, Refusal> {
    let obligation = object
        .get("obligations")
        .and_then(JsonValue::as_object)
        .and_then(|obligations| {
            obligations
                .get("wp_preservation")
                .or_else(|| obligations.get("wp-preservation"))
                .or_else(|| obligations.get("wpPreservation"))
        })
        .or_else(|| object.get("wp_preservation"))
        .or_else(|| object.get("wp-preservation"))
        .or_else(|| object.get("wpPreservation"))
        .ok_or_else(|| {
            Refusal::new(
                RefusalKind::WpPreservationNotDischarged,
                format!("{fn_name} is missing wp-preservation obligation"),
                vec![fn_name.to_string()],
            )
        })?;

    serde_json::from_value(obligation.clone()).map_err(|e| {
        Refusal::new(
            RefusalKind::InvalidDesugaringEquation,
            format!("{fn_name} wp-preservation obligation is invalid: {e}"),
            vec![fn_name.to_string()],
        )
    })
}

fn required_string(
    object: &serde_json::Map<String, JsonValue>,
    field: &str,
) -> std::result::Result<String, Refusal> {
    string_field(object, field)
        .map(ToOwned::to_owned)
        .ok_or_else(|| {
            Refusal::new(
                RefusalKind::InvalidDesugaringEquation,
                format!("missing string field {field}"),
                vec![],
            )
        })
}

fn string_field<'a>(
    object: &'a serde_json::Map<String, JsonValue>,
    field: &str,
) -> Option<&'a str> {
    object.get(field).and_then(JsonValue::as_str)
}

/// `true` iff `value` is the trivially-true atomic predicate
/// `{"kind":"atomic","name":"true","args":[]}` (the only `pre` form the
/// rewriter can honour without side-condition evaluation).
fn is_trivially_true(value: &JsonValue) -> bool {
    value
        .as_object()
        .map(|o| {
            string_field(o, "kind") == Some("atomic")
                && string_field(o, "name") == Some("true")
                && o.get("args")
                    .and_then(JsonValue::as_array)
                    .map_or(true, |a| a.is_empty())
        })
        .unwrap_or(false)
}

fn names_alias(left: &str, right: &str) -> bool {
    left == right
        || (!left.contains(':') && left == unqualified(right))
        || (!right.contains(':') && right == unqualified(left))
}

fn unqualified(name: &str) -> &str {
    name.rsplit_once(':').map_or(name, |(_, suffix)| suffix)
}
