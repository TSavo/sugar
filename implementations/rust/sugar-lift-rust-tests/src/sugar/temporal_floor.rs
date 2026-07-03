// SPDX-License-Identifier: Apache-2.0

use std::cell::RefCell;
use std::collections::BTreeMap;
use std::fmt;

/// The temporal floor is the only owner allowed to mint occurrence aliases.
///
/// Members describe rewrites; the single operation is "alias this rewrite into
/// the timeless formula universe." The private mint functions below preserve the
/// pre-S2 wire names byte-for-byte while making combinator-local naming
/// unrepresentable.
#[derive(Debug, Default)]
pub(crate) struct TemporalFloor {
    consuming_occurrence: RefCell<BTreeMap<String, usize>>,
}

impl Clone for TemporalFloor {
    fn clone(&self) -> Self {
        Self {
            consuming_occurrence: RefCell::new(self.consuming_occurrence.borrow().clone()),
        }
    }
}

impl TemporalFloor {
    pub(crate) fn alias<D>(&self, doorway: D) -> Result<D::Alias, TemporalFloorRefusal>
    where
        D: TemporalDoorway,
    {
        doorway.alias_through(self)
    }

    pub(crate) fn reset_statement(&self) {
        self.consuming_occurrence.borrow_mut().clear();
    }

    fn mint_curry_occurrence<'a>(
        &self,
        doorway: CurryDoorway<'a>,
    ) -> Result<CurryOccurrence<'a>, TemporalFloorRefusal> {
        if doorway.family.is_empty() {
            return Err(TemporalFloorRefusal::new(
                "missing standing",
                "TemporalFloor",
                "curry doorway carried an empty family",
                "construct CurryDoorway with the combinator family that owns this rewrite",
            ));
        }
        Ok(CurryOccurrence {
            family: doorway.family,
            ordinal: doorway.ordinal,
        })
    }

    fn mint_consuming_rewrite_alias(
        &self,
        doorway: ConsumingRewriteDoorway<'_>,
    ) -> Result<Option<ConsumingRewriteAlias>, TemporalFloorRefusal> {
        if doorway.name.is_empty() {
            return Err(TemporalFloorRefusal::new(
                "missing standing",
                "TemporalFloor",
                "rewrite doorway carried an empty iterator name",
                "route the versioned iterator receiver name into ConsumingRewriteDoorway",
            ));
        }
        let mut map = self.consuming_occurrence.borrow_mut();
        let count = map.entry(doorway.name.to_string()).or_insert(0);
        let prior = *count;
        *count += 1;
        if prior == 0 {
            Ok(None)
        } else {
            Ok(Some(ConsumingRewriteAlias {
                name: format!("{}@adv{}", doorway.name, prior),
            }))
        }
    }

    fn mint_binding_alias<'a>(
        &self,
        doorway: BindDoorway<'a>,
    ) -> Result<TemporalBinding, TemporalFloorRefusal> {
        if doorway.name.is_empty() {
            return Err(TemporalFloorRefusal::new(
                "missing standing",
                "TemporalFloor",
                "bind doorway carried an empty name",
                "route the freshly bound temporal name into BindDoorway",
            ));
        }
        Ok(TemporalBinding {
            name: doorway.name.to_string(),
            value: doorway.name.to_string(),
            doorway: TemporalDoorwayKind::Bind,
        })
    }

    fn mint_rewrite_alias<'a>(
        &self,
        doorway: RewriteDoorway<'a>,
    ) -> Result<TemporalBinding, TemporalFloorRefusal> {
        if doorway.name.is_empty() {
            return Err(TemporalFloorRefusal::new(
                "missing standing",
                "TemporalFloor",
                "rewrite doorway carried an empty name",
                "route the rewritten temporal name into RewriteDoorway",
            ));
        }
        Ok(TemporalBinding {
            name: doorway.name.to_string(),
            value: format!("{}@def{}", doorway.name, doorway.version),
            doorway: TemporalDoorwayKind::Rewrite,
        })
    }
}

pub(crate) trait TemporalDoorway {
    type Alias;

    fn alias_through(self, floor: &TemporalFloor) -> Result<Self::Alias, TemporalFloorRefusal>;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) struct BindDoorway<'a> {
    name: &'a str,
}

impl<'a> BindDoorway<'a> {
    pub(crate) fn new(name: &'a str) -> Self {
        Self { name }
    }
}

impl<'a> TemporalDoorway for BindDoorway<'a> {
    type Alias = TemporalBinding;

    fn alias_through(self, floor: &TemporalFloor) -> Result<Self::Alias, TemporalFloorRefusal> {
        floor.mint_binding_alias(self)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) struct RewriteDoorway<'a> {
    name: &'a str,
    version: usize,
}

impl<'a> RewriteDoorway<'a> {
    pub(crate) fn new(name: &'a str, version: usize) -> Self {
        Self { name, version }
    }
}

impl<'a> TemporalDoorway for RewriteDoorway<'a> {
    type Alias = TemporalBinding;

    fn alias_through(self, floor: &TemporalFloor) -> Result<Self::Alias, TemporalFloorRefusal> {
        floor.mint_rewrite_alias(self)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) struct CurryDoorway<'a> {
    family: &'a str,
    ordinal: usize,
}

impl<'a> CurryDoorway<'a> {
    pub(crate) fn new(family: &'a str, ordinal: usize) -> Self {
        Self { family, ordinal }
    }
}

impl<'a> TemporalDoorway for CurryDoorway<'a> {
    type Alias = CurryOccurrence<'a>;

    fn alias_through(self, floor: &TemporalFloor) -> Result<Self::Alias, TemporalFloorRefusal> {
        floor.mint_curry_occurrence(self)
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) struct ConsumingRewriteDoorway<'a> {
    name: &'a str,
}

impl<'a> ConsumingRewriteDoorway<'a> {
    pub(crate) fn new(name: &'a str) -> Self {
        Self { name }
    }
}

impl<'a> TemporalDoorway for ConsumingRewriteDoorway<'a> {
    type Alias = Option<ConsumingRewriteAlias>;

    fn alias_through(self, floor: &TemporalFloor) -> Result<Self::Alias, TemporalFloorRefusal> {
        floor.mint_consuming_rewrite_alias(self)
    }
}

/// A finite-domain occurrence context for a term-floor curry.
///
/// This value has no public field constructor: the temporal floor is the only
/// aliasing authority for curry occurrence names.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) struct CurryOccurrence<'a> {
    family: &'a str,
    ordinal: usize,
}

impl CurryOccurrence<'_> {
    pub(crate) fn suffix(&self) -> String {
        format!("#{}{}", self.family, self.ordinal + 1)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct ConsumingRewriteAlias {
    name: String,
}

impl ConsumingRewriteAlias {
    pub(crate) fn into_name(self) -> String {
        self.name
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum TemporalDoorwayKind {
    Bind,
    Rewrite,
    Curry,
}

impl TemporalDoorwayKind {
    pub(crate) fn parse(name: &str) -> Result<Self, TemporalFloorRefusal> {
        match name {
            "bind" => Ok(Self::Bind),
            "rewrite" => Ok(Self::Rewrite),
            "curry" => Ok(Self::Curry),
            other => Err(TemporalFloorRefusal::new(
                "unknown doorway",
                "TemporalFloor",
                format!("doorway `{other}`"),
                "use one of: bind, rewrite, curry",
            )),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct TemporalBinding {
    name: String,
    value: String,
    doorway: TemporalDoorwayKind,
}

impl TemporalBinding {
    pub(crate) fn name(&self) -> &str {
        &self.name
    }

    pub(crate) fn value(&self) -> &str {
        &self.value
    }

    pub(crate) fn doorway(&self) -> TemporalDoorwayKind {
        self.doorway
    }
}

#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub(crate) struct TemporalContext {
    bindings: Vec<TemporalBinding>,
}

impl TemporalContext {
    pub(crate) fn bind(&self, binding: TemporalBinding) -> Self {
        let mut bindings = self.bindings.clone();
        bindings.push(binding);
        Self { bindings }
    }

    pub(crate) fn value_for(&self, name: &str) -> Result<&TemporalBinding, TemporalFloorRefusal> {
        self.bindings
            .iter()
            .rev()
            .find(|binding| binding.name() == name)
            .ok_or_else(|| {
                TemporalFloorRefusal::new(
                    "resolution miss",
                    "TemporalContext",
                    format!("no temporal binding for `{name}`"),
                    "thread the binding through TemporalContext::bind before resolving it",
                )
            })
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum IterProvenance {
    Literal,
    Stated,
    Derived,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct IterStanding {
    member: &'static str,
    provenance: IterProvenance,
    count: usize,
}

impl IterStanding {
    pub(crate) fn new(
        member: &'static str,
        provenance: IterProvenance,
        count: Option<usize>,
    ) -> Result<Self, TemporalFloorRefusal> {
        let Some(count) = count else {
            return Err(TemporalFloorRefusal::new(
                "missing standing",
                "IterFloor",
                format!("{member} carried no finite member count"),
                "construct IterStanding with the member's own count before aliasing it",
            ));
        };
        Ok(Self {
            member,
            provenance,
            count,
        })
    }

    pub(crate) fn member(&self) -> &'static str {
        self.member
    }

    pub(crate) fn provenance(&self) -> IterProvenance {
        self.provenance
    }

    pub(crate) fn count(&self) -> usize {
        self.count
    }
}

pub(crate) trait IterFloorMember {
    fn standing(&self) -> Result<IterStanding, TemporalFloorRefusal>;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) struct LiteralIterMember {
    member: &'static str,
    count: usize,
}

impl LiteralIterMember {
    pub(crate) fn array(count: usize) -> Self {
        Self {
            member: "ArrayLiteral",
            count,
        }
    }

    pub(crate) fn tuple(count: usize) -> Self {
        Self {
            member: "TupleLiteral",
            count,
        }
    }

    pub(crate) fn string_chars(count: usize) -> Self {
        Self {
            member: "StringLiteral.chars",
            count,
        }
    }

    pub(crate) fn string_bytes(count: usize) -> Self {
        Self {
            member: "StringLiteral.bytes",
            count,
        }
    }

    pub(crate) fn range(count: usize) -> Self {
        Self {
            member: "RangeLiteral",
            count,
        }
    }
}

impl IterFloorMember for LiteralIterMember {
    fn standing(&self) -> Result<IterStanding, TemporalFloorRefusal> {
        IterStanding::new(self.member, IterProvenance::Literal, Some(self.count))
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) struct CollectionIterMember {
    member: &'static str,
    provenance: IterProvenance,
    count: usize,
}

impl CollectionIterMember {
    pub(crate) fn stated(count: usize) -> Self {
        Self {
            member: "StatedCollection",
            provenance: IterProvenance::Stated,
            count,
        }
    }

    pub(crate) fn derived(count: usize) -> Self {
        Self {
            member: "DerivedCollection",
            provenance: IterProvenance::Derived,
            count,
        }
    }
}

impl IterFloorMember for CollectionIterMember {
    fn standing(&self) -> Result<IterStanding, TemporalFloorRefusal> {
        IterStanding::new(self.member, self.provenance, Some(self.count))
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) struct MapOutputIterMember {
    count: usize,
}

impl MapOutputIterMember {
    pub(crate) fn new(count: usize) -> Self {
        Self { count }
    }
}

impl IterFloorMember for MapOutputIterMember {
    fn standing(&self) -> Result<IterStanding, TemporalFloorRefusal> {
        IterStanding::new("MapOutput", IterProvenance::Derived, Some(self.count))
    }
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub(crate) struct IterFloor;

impl IterFloor {
    pub(crate) fn alias<M>(&self, member: &M) -> Result<IterStanding, TemporalFloorRefusal>
    where
        M: IterFloorMember,
    {
        member.standing()
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct TemporalFloorRefusal {
    crime: &'static str,
    owner: &'static str,
    shape: String,
    replacement: &'static str,
}

impl TemporalFloorRefusal {
    fn new(
        crime: &'static str,
        owner: &'static str,
        shape: impl Into<String>,
        replacement: &'static str,
    ) -> Self {
        Self {
            crime,
            owner,
            shape: shape.into(),
            replacement,
        }
    }
}

impl fmt::Display for TemporalFloorRefusal {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "temporal floor refusal: crime={}; owner={}; shape={}; replacement={}",
            self.crime, self.owner, self.shape, self.replacement
        )
    }
}

impl std::error::Error for TemporalFloorRefusal {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn curry_doorway_mints_existing_suffix_bytes_only_through_floor() {
        let floor = TemporalFloor::default();
        let occurrence = floor
            .alias(CurryDoorway::new("map", 1))
            .expect("curry doorway aliases through floor");

        assert_eq!(occurrence.suffix(), "#map2");
    }

    #[test]
    fn consuming_rewrite_preserves_existing_adv_bytes() {
        let floor = TemporalFloor::default();

        assert_eq!(
            floor
                .alias(ConsumingRewriteDoorway::new("it@def5"))
                .expect("first occurrence records standing"),
            None
        );
        assert_eq!(
            floor
                .alias(ConsumingRewriteDoorway::new("it@def5"))
                .expect("second occurrence aliases"),
            Some(ConsumingRewriteAlias {
                name: "it@def5@adv1".to_string(),
            })
        );
    }

    #[test]
    fn doorway_kinds_are_closed_and_unknown_refuses_loudly() {
        let err = TemporalDoorwayKind::parse("freeze").expect_err("unknown doorway refuses");
        let msg = err.to_string();

        assert!(msg.contains("crime=unknown doorway"));
        assert!(msg.contains("owner=TemporalFloor"));
        assert!(msg.contains("shape=doorway `freeze`"));
        assert!(msg.contains("replacement=use one of: bind, rewrite, curry"));
    }

    #[test]
    fn temporal_context_resolves_by_reverse_scan_only() {
        let floor = TemporalFloor::default();
        let first = floor
            .alias(BindDoorway::new("x"))
            .expect("bind doorway aliases");
        let second = floor
            .alias(RewriteDoorway::new("x", 1))
            .expect("rewrite doorway aliases");

        let ctx = TemporalContext::default().bind(first).bind(second);
        let resolved = ctx.value_for("x").expect("latest binding resolves");

        assert_eq!(resolved.value(), "x@def1");
        assert_eq!(resolved.doorway(), TemporalDoorwayKind::Rewrite);
    }

    #[test]
    fn temporal_context_miss_is_floor_kind_gap() {
        let err = TemporalContext::default()
            .value_for("missing")
            .expect_err("missing temporal binding refuses");
        let msg = err.to_string();

        assert!(msg.contains("crime=resolution miss"));
        assert!(msg.contains("owner=TemporalContext"));
        assert!(msg.contains("shape=no temporal binding for `missing`"));
        assert!(msg.contains("replacement=thread the binding through TemporalContext::bind"));
    }

    #[test]
    fn iter_floor_literal_and_collection_members_report_count_with_provenance() {
        let floor = IterFloor;
        let members = [
            floor.alias(&LiteralIterMember::array(2)).unwrap(),
            floor.alias(&LiteralIterMember::tuple(3)).unwrap(),
            floor.alias(&LiteralIterMember::string_chars(4)).unwrap(),
            floor.alias(&LiteralIterMember::string_bytes(5)).unwrap(),
            floor.alias(&LiteralIterMember::range(6)).unwrap(),
            floor.alias(&CollectionIterMember::stated(7)).unwrap(),
            floor.alias(&CollectionIterMember::derived(8)).unwrap(),
        ];

        assert_eq!(members[0].member(), "ArrayLiteral");
        assert_eq!(members[0].provenance(), IterProvenance::Literal);
        assert_eq!(members[0].count(), 2);
        assert_eq!(members[5].provenance(), IterProvenance::Stated);
        assert_eq!(members[6].provenance(), IterProvenance::Derived);
    }

    #[test]
    fn iter_floor_counts_map_output_as_derived() {
        let floor = IterFloor;
        let standing = floor.alias(&MapOutputIterMember::new(2)).unwrap();

        assert_eq!(standing.member(), "MapOutput");
        assert_eq!(standing.provenance(), IterProvenance::Derived);
        assert_eq!(standing.count(), 2);
    }

    #[test]
    fn iter_floor_missing_standing_refuses_loudly() {
        let err = IterStanding::new("ArrayLiteral", IterProvenance::Literal, None)
            .expect_err("missing member count refuses");
        let msg = err.to_string();

        assert!(msg.contains("crime=missing standing"));
        assert!(msg.contains("owner=IterFloor"));
        assert!(msg.contains("shape=ArrayLiteral carried no finite member count"));
        assert!(msg.contains("replacement=construct IterStanding"));
    }

    #[test]
    fn wrong_doorway_is_observably_a_different_theory() {
        let floor = TemporalFloor::default();
        let bound = floor.alias(BindDoorway::new("x")).unwrap();
        let rewritten = floor.alias(RewriteDoorway::new("x", 1)).unwrap();
        let curry = floor.alias(CurryDoorway::new("x", 0)).unwrap();

        assert_ne!(bound.value(), rewritten.value());
        assert_ne!(bound.value(), curry.suffix());
        assert_ne!(rewritten.value(), curry.suffix());
    }

    #[test]
    fn rebind_must_not_freeze_through_curry_doorway() {
        let floor = TemporalFloor::default();
        let first_rewrite = floor.alias(RewriteDoorway::new("x", 1)).unwrap();
        let second_rewrite = floor.alias(RewriteDoorway::new("x", 2)).unwrap();

        assert_ne!(
            first_rewrite.value(),
            second_rewrite.value(),
            "rewrite doorway must split rebinding names so x_1 == x_2 cannot be manufactured"
        );

        let frozen_first = floor.alias(CurryDoorway::new("x", 0)).unwrap();
        let frozen_second = floor.alias(CurryDoorway::new("x", 0)).unwrap();

        assert_eq!(
            frozen_first.suffix(),
            frozen_second.suffix(),
            "curry doorway freezes the callee symbol; using it for a rebind would collapse distinct versions"
        );
        assert_ne!(first_rewrite.value(), frozen_first.suffix());
        assert_ne!(second_rewrite.value(), frozen_second.suffix());
    }
}
