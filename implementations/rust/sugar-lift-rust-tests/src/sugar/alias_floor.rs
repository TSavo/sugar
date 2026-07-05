// SPDX-License-Identifier: MIT OR Apache-2.0

//! Alias floor skeleton for #3482.
//!
//! The walker emits events; the alias value owns the identity answer. This
//! slice only wires provenance-known mutable places. Copy/severance and opaque
//! provenance are later campaign slices.

use std::fs;
use std::process::Command;
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

static COPY_PROBE_COUNTER: AtomicU64 = AtomicU64::new(0);

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) struct AliasFloor {
    place: Place,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) enum Place {
    Scalar(String),
    Element {
        base: String,
        index: usize,
    },
    Slice {
        base: String,
        start: usize,
        len: usize,
    },
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) enum AliasFloorResult {
    ReducedValue(AliasReducedValue),
    TypedEffect(AliasTypedEffect),
    #[cfg(any())]
    PlantedResultTooth,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) enum AliasReducedValue {
    BoundAlias(AliasFloor),
    Read(AliasRead),
    WriteTarget(AliasWriteTarget),
    BaseIdentity(String),
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) enum AliasRead {
    Scalar(String),
    Element { base: String, index: usize },
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) enum AliasWriteTarget {
    Scalar { base: String },
    Element { base: String, index: usize },
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) enum AliasTypedEffect {
    UnroutableAliasShape {
        event: AliasEvent,
        place: Place,
    },
    UnknownSeverance {
        place: Place,
        reason: String,
    },
    UnknownMutation {
        place: Place,
        cause: AliasMutationCause,
    },
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) enum CopySeveranceFact {
    Copy,
    NotCopy { diagnostic: String },
    UnknownSeverance { reason: String },
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum AliasEvent {
    Read,
    WriteThrough,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) enum AliasMutationCause {
    UntrackableRhs { lhs: String, rhs: String },
}

impl AliasFloor {
    pub(crate) fn new(place: Place) -> Self {
        Self { place }
    }

    pub(crate) fn scalar(base: impl Into<String>) -> Self {
        Self::new(Place::Scalar(base.into()))
    }

    pub(crate) fn element(base: impl Into<String>, index: usize) -> Self {
        Self::new(Place::Element {
            base: base.into(),
            index,
        })
    }

    pub(crate) fn slice(base: impl Into<String>, start: usize, len: usize) -> Self {
        Self::new(Place::Slice {
            base: base.into(),
            start,
            len,
        })
    }

    pub(crate) fn bind(self) -> AliasFloorResult {
        AliasFloorResult::ReducedValue(AliasReducedValue::BoundAlias(self))
    }

    pub(crate) fn read(&self) -> AliasFloorResult {
        match &self.place {
            Place::Scalar(base) => AliasFloorResult::ReducedValue(AliasReducedValue::Read(
                AliasRead::Scalar(base.clone()),
            )),
            Place::Element { base, index } => {
                AliasFloorResult::ReducedValue(AliasReducedValue::Read(AliasRead::Element {
                    base: base.clone(),
                    index: *index,
                }))
            }
            Place::Slice { .. } => {
                AliasFloorResult::TypedEffect(AliasTypedEffect::UnroutableAliasShape {
                    event: AliasEvent::Read,
                    place: self.place.clone(),
                })
            }
        }
    }

    pub(crate) fn read_index(&self, index: usize) -> AliasFloorResult {
        match &self.place {
            Place::Slice { base, start, len } if index < *len => {
                AliasFloorResult::ReducedValue(AliasReducedValue::Read(AliasRead::Element {
                    base: base.clone(),
                    index: start + index,
                }))
            }
            _ => AliasFloorResult::TypedEffect(AliasTypedEffect::UnroutableAliasShape {
                event: AliasEvent::Read,
                place: self.place.clone(),
            }),
        }
    }

    pub(crate) fn write_through(&self) -> AliasFloorResult {
        match &self.place {
            Place::Scalar(base) => AliasFloorResult::ReducedValue(AliasReducedValue::WriteTarget(
                AliasWriteTarget::Scalar { base: base.clone() },
            )),
            Place::Element { base, index } => AliasFloorResult::ReducedValue(
                AliasReducedValue::WriteTarget(AliasWriteTarget::Element {
                    base: base.clone(),
                    index: *index,
                }),
            ),
            Place::Slice { .. } => {
                AliasFloorResult::TypedEffect(AliasTypedEffect::UnroutableAliasShape {
                    event: AliasEvent::WriteThrough,
                    place: self.place.clone(),
                })
            }
        }
    }

    pub(crate) fn write_index(&self, index: usize) -> AliasFloorResult {
        match &self.place {
            Place::Slice { base, start, len } if index < *len => AliasFloorResult::ReducedValue(
                AliasReducedValue::WriteTarget(AliasWriteTarget::Element {
                    base: base.clone(),
                    index: start + index,
                }),
            ),
            _ => AliasFloorResult::TypedEffect(AliasTypedEffect::UnroutableAliasShape {
                event: AliasEvent::WriteThrough,
                place: self.place.clone(),
            }),
        }
    }

    pub(crate) fn consume(&self) -> AliasFloorResult {
        match &self.place {
            Place::Scalar(base) | Place::Element { base, .. } | Place::Slice { base, .. } => {
                AliasFloorResult::ReducedValue(AliasReducedValue::BaseIdentity(base.clone()))
            }
        }
    }

    pub(crate) fn unknown_mutation(&self, cause: AliasMutationCause) -> AliasFloorResult {
        AliasFloorResult::TypedEffect(AliasTypedEffect::UnknownMutation {
            place: self.place.clone(),
            cause,
        })
    }

    pub(crate) fn unknown_severance(&self, reason: String) -> AliasFloorResult {
        AliasFloorResult::TypedEffect(AliasTypedEffect::UnknownSeverance {
            place: self.place.clone(),
            reason,
        })
    }
}

impl Place {
    pub(crate) fn base(&self) -> &str {
        match self {
            Place::Scalar(base) | Place::Element { base, .. } | Place::Slice { base, .. } => base,
        }
    }
}

pub(crate) fn probe_copy_severance_for_expr(
    visible_prelude: &str,
    expr_src: &str,
) -> CopySeveranceFact {
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_nanos())
        .unwrap_or_default();
    let dir = std::env::temp_dir().join(format!(
        "sugar-copy-severance-{}-{nonce}-{}",
        std::process::id(),
        COPY_PROBE_COUNTER.fetch_add(1, Ordering::Relaxed)
    ));
    if let Err(err) = fs::create_dir_all(&dir) {
        return CopySeveranceFact::UnknownSeverance {
            reason: format!("could not create rustc Copy probe directory: {err}"),
        };
    }

    let src_path = dir.join("copy_probe.rs");
    let bin_path = dir.join("copy_probe_bin");
    let source = format!(
        r#"#![allow(dead_code, unused_variables, unused_imports)]
{visible_prelude}

fn assert_copy<T: Copy>(_: &T) {{}}

fn main() {{
    let x = {expr_src};
    assert_copy(&x);
}}
"#
    );
    if let Err(err) = fs::write(&src_path, source) {
        let _ = fs::remove_dir_all(&dir);
        return CopySeveranceFact::UnknownSeverance {
            reason: format!("could not write rustc Copy probe: {err}"),
        };
    }

    let output = Command::new("rustc")
        .arg("--edition=2021")
        .arg("--error-format=json")
        .arg(&src_path)
        .arg("-o")
        .arg(&bin_path)
        .output();
    let _ = fs::remove_dir_all(&dir);

    let output = match output {
        Ok(output) => output,
        Err(err) => {
            return CopySeveranceFact::UnknownSeverance {
                reason: format!("could not invoke rustc Copy probe: {err}"),
            };
        }
    };
    if output.status.success() {
        return CopySeveranceFact::Copy;
    }

    let stderr = String::from_utf8_lossy(&output.stderr);
    diagnose_copy_probe_failure(&stderr)
}

fn diagnose_copy_probe_failure(stderr: &str) -> CopySeveranceFact {
    let mut coded_errors = Vec::new();
    for line in stderr.lines() {
        let Ok(value) = serde_json::from_str::<serde_json::Value>(line) else {
            continue;
        };
        if value.get("level").and_then(|level| level.as_str()) != Some("error") {
            continue;
        }
        let Some(code) = value
            .get("code")
            .and_then(|code| code.get("code"))
            .and_then(|code| code.as_str())
        else {
            continue;
        };
        let message = value
            .get("message")
            .and_then(|message| message.as_str())
            .unwrap_or_default()
            .to_string();
        let rendered = value
            .get("rendered")
            .and_then(|rendered| rendered.as_str())
            .unwrap_or_default()
            .to_string();
        coded_errors.push((code.to_string(), message, rendered));
    }

    let missing_local_copy_evidence = coded_errors.len() == 1
        && coded_errors[0].0 == "E0277"
        && coded_errors[0].2.contains("assert_copy")
        && coded_errors[0].2.contains("consider annotating")
        && coded_errors[0].2.contains("#[derive(Copy)]");
    let only_copy_bound_failure = coded_errors.len() == 1
        && coded_errors[0].0 == "E0277"
        && coded_errors[0].1.contains("Copy")
        && coded_errors[0].2.contains("assert_copy")
        && coded_errors[0]
            .2
            .contains("the trait `Copy` is not implemented")
        && !missing_local_copy_evidence;

    if only_copy_bound_failure {
        CopySeveranceFact::NotCopy {
            diagnostic: coded_errors[0].2.clone(),
        }
    } else if missing_local_copy_evidence {
        CopySeveranceFact::UnknownSeverance {
            reason: "rustc Copy probe reached assert_copy but the source-owned Copy impl was not \
                     visible to the probe; refusing to collapse missing testimony into NotCopy"
                .to_string(),
        }
    } else {
        let codes = coded_errors
            .iter()
            .map(|(code, _, _)| code.as_str())
            .collect::<Vec<_>>()
            .join(",");
        let summary = if codes.is_empty() {
            stderr.lines().take(8).collect::<Vec<_>>().join("\n")
        } else {
            format!("rustc Copy probe failed before Copy could be adjudicated: {codes}")
        };
        CopySeveranceFact::UnknownSeverance { reason: summary }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn copy_trait_probe_reads_visible_copy_impl() {
        let fact =
            probe_copy_severance_for_expr("#[derive(Copy, Clone)] struct Token(i32);", "Token(5)");

        assert_eq!(fact, CopySeveranceFact::Copy);
    }

    #[test]
    fn copy_trait_probe_manual_impl_visibility_is_load_bearing() {
        let fact = probe_copy_severance_for_expr(
            "#[derive(Clone)] struct Token(i32); impl Copy for Token {}",
            "Token(5)",
        );

        assert_eq!(fact, CopySeveranceFact::Copy);
    }

    #[test]
    fn copy_trait_probe_distinguishes_visible_not_copy_from_unknown() {
        let fact = probe_copy_severance_for_expr("struct Token(String);", "Token(String::new())");

        match fact {
            CopySeveranceFact::NotCopy { diagnostic } => {
                assert!(
                    diagnostic.contains("E0277") && diagnostic.contains("assert_copy"),
                    "NotCopy must be backed by the assert_copy E0277 diagnostic: {diagnostic}"
                );
            }
            other => panic!("visible non-Copy type must be NotCopy, got {other:?}"),
        }
    }

    #[test]
    fn copy_trait_probe_missing_impl_visibility_is_unknown_severance() {
        let fact = probe_copy_severance_for_expr("struct Token(i32);", "Token(5)");

        match fact {
            CopySeveranceFact::UnknownSeverance { reason } => {
                assert!(
                    reason.contains("Copy impl was not visible"),
                    "local all-Copy-shaped type without visible impl must refuse safe: {reason}"
                );
            }
            other => {
                panic!("missing visible Copy impl must not collapse to NotCopy, got {other:?}")
            }
        }
    }

    #[test]
    fn unresolved_copy_probe_is_unknown_severance_not_move() {
        let fact = probe_copy_severance_for_expr("", "Token(5)");

        match fact {
            CopySeveranceFact::UnknownSeverance { reason } => {
                assert!(
                    reason.contains("E0425") || reason.contains("unresolved"),
                    "missing type/impl visibility must stay unknown, got: {reason}"
                );
            }
            other => panic!("missing Copy fact must not collapse to NotCopy, got {other:?}"),
        }
    }
}
