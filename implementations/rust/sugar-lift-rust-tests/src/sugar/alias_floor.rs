// SPDX-License-Identifier: Apache-2.0

//! Alias floor skeleton for #3482.
//!
//! The walker emits events; the alias value owns the identity answer. This
//! slice only wires provenance-known mutable places. Copy/severance and opaque
//! provenance are later campaign slices.

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
    UnknownMutation {
        place: Place,
        cause: AliasMutationCause,
    },
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum AliasEvent {
    Bind,
    Read,
    WriteThrough,
    Consume,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) enum AliasMutationCause {
    UntrackableRhs { lhs: String, rhs: String },
    OpaqueCall { site: String },
    IteratorConsumption { method: String },
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
}

impl AliasTypedEffect {
    pub(crate) fn place(&self) -> &Place {
        match self {
            AliasTypedEffect::UnroutableAliasShape { place, .. }
            | AliasTypedEffect::UnknownMutation { place, .. } => place,
        }
    }

    pub(crate) fn base(&self) -> &str {
        self.place().base()
    }
}

impl Place {
    pub(crate) fn base(&self) -> &str {
        match self {
            Place::Scalar(base) | Place::Element { base, .. } | Place::Slice { base, .. } => base,
        }
    }
}
