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
            value: format!("{}@def{}", doorway.name, doorway.version),
        })
    }
}

pub(crate) trait TemporalDoorway {
    type Alias;

    fn alias_through(self, floor: &TemporalFloor) -> Result<Self::Alias, TemporalFloorRefusal>;
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

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct TemporalBinding {
    value: String,
}

impl TemporalBinding {
    pub(crate) fn value(&self) -> &str {
        &self.value
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum IterProvenance {
    Derived,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct IterStanding {
    member: &'static str,
    count: usize,
}

impl IterStanding {
    pub(crate) fn new(
        member: &'static str,
        _provenance: IterProvenance,
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
        Ok(Self { member, count })
    }

    pub(crate) fn member(&self) -> &'static str {
        self.member
    }

    pub(crate) fn count(&self) -> usize {
        self.count
    }
}

pub(crate) trait IterFloorMember {
    fn standing(&self) -> Result<IterStanding, TemporalFloorRefusal>;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) struct CollectionIterMember {
    member: &'static str,
    count: usize,
}

impl CollectionIterMember {
    pub(crate) fn derived(count: usize) -> Self {
        Self {
            member: "DerivedCollection",
            count,
        }
    }
}

impl IterFloorMember for CollectionIterMember {
    fn standing(&self) -> Result<IterStanding, TemporalFloorRefusal> {
        IterStanding::new(self.member, IterProvenance::Derived, Some(self.count))
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

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) struct AdapterOutputIterMember {
    member: &'static str,
    count: usize,
}

impl AdapterOutputIterMember {
    fn new(member: &'static str, count: usize) -> Self {
        Self { member, count }
    }

    pub(crate) fn filter(count: usize) -> Self {
        Self::new("FilterOutput", count)
    }

    pub(crate) fn filter_map(count: usize) -> Self {
        Self::new("FilterMapOutput", count)
    }

    pub(crate) fn chain(count: usize) -> Self {
        Self::new("ChainOutput", count)
    }

    pub(crate) fn zip(count: usize) -> Self {
        Self::new("ZipOutput", count)
    }

    pub(crate) fn enumerate(count: usize) -> Self {
        Self::new("EnumerateOutput", count)
    }

    pub(crate) fn take(count: usize) -> Self {
        Self::new("TakeOutput", count)
    }

    pub(crate) fn skip(count: usize) -> Self {
        Self::new("SkipOutput", count)
    }

    pub(crate) fn take_while(count: usize) -> Self {
        Self::new("TakeWhileOutput", count)
    }

    pub(crate) fn skip_while(count: usize) -> Self {
        Self::new("SkipWhileOutput", count)
    }

    pub(crate) fn inspect(count: usize) -> Self {
        Self::new("InspectOutput", count)
    }
}

impl IterFloorMember for AdapterOutputIterMember {
    fn standing(&self) -> Result<IterStanding, TemporalFloorRefusal> {
        IterStanding::new(self.member, IterProvenance::Derived, Some(self.count))
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
pub(crate) struct AdapterFloorOutput<T> {
    items: Vec<T>,
    standing: IterStanding,
}

impl<T> AdapterFloorOutput<T> {
    pub(crate) fn into_items(self) -> Vec<T> {
        self.items
    }

    pub(crate) fn standing(&self) -> &IterStanding {
        &self.standing
    }
}

#[derive(Clone, Copy, Debug)]
pub(crate) struct CountedAdapterFloor {
    operation: &'static str,
    output_member: fn(usize) -> AdapterOutputIterMember,
    iter: IterFloor,
}

impl CountedAdapterFloor {
    pub(crate) fn new(
        operation: &'static str,
        output_member: fn(usize) -> AdapterOutputIterMember,
    ) -> Self {
        Self {
            operation,
            output_member,
            iter: IterFloor,
        }
    }

    pub(crate) fn derived_operand(
        &self,
        count: usize,
    ) -> Result<IterStanding, TemporalFloorRefusal> {
        self.iter.alias(&CollectionIterMember::derived(count))
    }

    pub(crate) fn output<T>(
        &self,
        items: Vec<T>,
    ) -> Result<AdapterFloorOutput<T>, TemporalFloorRefusal> {
        let standing = self.iter.alias(&(self.output_member)(items.len()))?;
        Ok(AdapterFloorOutput { items, standing })
    }

    pub(crate) fn assert_input_count(
        &self,
        operand: &IterStanding,
        actual: usize,
    ) -> Result<(), TemporalFloorRefusal> {
        if operand.count() == actual {
            return Ok(());
        }
        Err(TemporalFloorRefusal::new(
            "count mismatch",
            "IteratorAdapterFloor",
            format!(
                "{} operand standing had {} tick(s), real adapter visited {} tick(s)",
                self.operation,
                operand.count(),
                actual
            ),
            "route adapter operands through the iter floor standing that measured this sequence",
        ))
    }

    pub(crate) fn assert_output_count(
        &self,
        operand: &IterStanding,
        expected: usize,
        actual: usize,
    ) -> Result<(), TemporalFloorRefusal> {
        if expected == actual {
            return Ok(());
        }
        Err(TemporalFloorRefusal::new(
            "count mismatch",
            "IteratorAdapterFloor",
            format!(
                "{} operand standing had {} tick(s), expected {} output tick(s), real adapter produced {} tick(s)",
                self.operation,
                operand.count(),
                expected,
                actual
            ),
            "let the real stdlib adapter measure the output count and record that standing",
        ))
    }
}

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub(crate) struct FoldFloor {
    iter: IterFloor,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct FoldTick<E> {
    emission: E,
}

impl<E> FoldTick<E> {
    pub(crate) fn emission(&self) -> &E {
        &self.emission
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct FoldFloorOutput<A, E> {
    final_accumulator: A,
    ticks: Vec<FoldTick<E>>,
}

impl<A, E> FoldFloorOutput<A, E> {
    pub(crate) fn final_accumulator(&self) -> &A {
        &self.final_accumulator
    }

    pub(crate) fn ticks(&self) -> &[FoldTick<E>] {
        &self.ticks
    }
}

impl FoldFloor {
    pub(crate) fn derived_operand(
        &self,
        count: usize,
    ) -> Result<IterStanding, TemporalFloorRefusal> {
        self.iter.alias(&CollectionIterMember::derived(count))
    }

    pub(crate) fn desugar<I, T, A, E, F>(
        &self,
        temporal: &TemporalFloor,
        operand: IterStanding,
        accumulator_name: &str,
        init: A,
        items: I,
        mut step: F,
    ) -> Result<FoldFloorOutput<A, E>, TemporalFloorRefusal>
    where
        I: IntoIterator<Item = T>,
        A: Clone,
        F: FnMut(usize, &A, T, &TemporalBinding) -> (E, A),
    {
        if accumulator_name.is_empty() {
            return Err(TemporalFloorRefusal::new(
                "missing standing",
                "FoldFloor",
                "fold accumulator doorway carried an empty name",
                "route the closure accumulator binding into the fold floor",
            ));
        }

        let (accumulator, ticks) =
            items
                .into_iter()
                .enumerate()
                .fold(Ok((init, Vec::new())), |state, (idx, item)| {
                    state.and_then(|(accumulator, mut ticks)| {
                        let alias =
                            temporal.alias(RewriteDoorway::new(accumulator_name, idx + 1))?;
                        let (emission, next_accumulator) = step(idx, &accumulator, item, &alias);
                        ticks.push(FoldTick { emission });
                        Ok((next_accumulator, ticks))
                    })
                })?;

        if ticks.len() != operand.count() {
            return Err(TemporalFloorRefusal::new(
                "count mismatch",
                "FoldFloor",
                format!(
                    "operand standing had {} tick(s), real fold produced {} tick(s)",
                    operand.count(),
                    ticks.len()
                ),
                "route fold operands through the iter floor standing that measured this sequence",
            ));
        }

        Ok(FoldFloorOutput {
            final_accumulator: accumulator,
            ticks,
        })
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
    fn iter_floor_counts_map_output_as_derived() {
        let floor = IterFloor;
        let standing = floor.alias(&MapOutputIterMember::new(2)).unwrap();

        assert_eq!(standing.member(), "MapOutput");
        assert_eq!(standing.count(), 2);
    }

    #[test]
    fn iter_floor_counts_adapter_outputs_as_derived() {
        let floor = IterFloor;
        let members = [
            floor.alias(&AdapterOutputIterMember::filter(2)).unwrap(),
            floor
                .alias(&AdapterOutputIterMember::filter_map(3))
                .unwrap(),
            floor.alias(&AdapterOutputIterMember::chain(4)).unwrap(),
            floor.alias(&AdapterOutputIterMember::zip(5)).unwrap(),
            floor.alias(&AdapterOutputIterMember::enumerate(6)).unwrap(),
            floor.alias(&AdapterOutputIterMember::take(7)).unwrap(),
            floor.alias(&AdapterOutputIterMember::skip(8)).unwrap(),
            floor
                .alias(&AdapterOutputIterMember::take_while(9))
                .unwrap(),
            floor
                .alias(&AdapterOutputIterMember::skip_while(10))
                .unwrap(),
            floor.alias(&AdapterOutputIterMember::inspect(11)).unwrap(),
        ];

        assert_eq!(members[0].member(), "FilterOutput");
        assert_eq!(members[1].member(), "FilterMapOutput");
        assert_eq!(members[2].member(), "ChainOutput");
        assert_eq!(members[3].member(), "ZipOutput");
        assert_eq!(members[4].member(), "EnumerateOutput");
        assert_eq!(members[5].member(), "TakeOutput");
        assert_eq!(members[6].member(), "SkipOutput");
        assert_eq!(members[7].member(), "TakeWhileOutput");
        assert_eq!(members[8].member(), "SkipWhileOutput");
        assert_eq!(members[9].member(), "InspectOutput");
        assert_eq!(members[9].count(), 11);
    }

    #[test]
    fn iter_floor_missing_standing_refuses_loudly() {
        let err = IterStanding::new("ArrayLiteral", IterProvenance::Derived, None)
            .expect_err("missing member count refuses");
        let msg = err.to_string();

        assert!(msg.contains("crime=missing standing"));
        assert!(msg.contains("owner=IterFloor"));
        assert!(msg.contains("shape=ArrayLiteral carried no finite member count"));
        assert!(msg.contains("replacement=construct IterStanding"));
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

    #[test]
    fn fold_floor_threads_accumulator_through_rewrite_doorway() {
        let temporal = TemporalFloor::default();
        let floor = FoldFloor::default();
        let operand = floor.derived_operand(3).unwrap();

        let out = floor
            .desugar(
                &temporal,
                operand,
                "acc",
                0i32,
                [1, 2, 3],
                |_, acc, item, alias| {
                    (
                        format!("{} == {} + {}", alias.value(), acc, item),
                        acc + item,
                    )
                },
            )
            .expect("fold floor desugars through temporal floor rewrites");

        assert_eq!(*out.final_accumulator(), 6);
        assert_eq!(
            out.ticks()
                .iter()
                .map(|tick| tick.emission())
                .collect::<Vec<_>>(),
            vec![
                "acc@def1 == 0 + 1",
                "acc@def2 == 1 + 2",
                "acc@def3 == 3 + 3"
            ]
        );
    }

    #[test]
    fn fold_accumulator_curry_doorway_would_collapse_the_rewrite_chain() {
        let floor = TemporalFloor::default();
        let first_rewrite = floor.alias(RewriteDoorway::new("acc", 1)).unwrap();
        let second_rewrite = floor.alias(RewriteDoorway::new("acc", 2)).unwrap();
        let first_curry = floor.alias(CurryDoorway::new("acc", 0)).unwrap();
        let second_curry = floor.alias(CurryDoorway::new("acc", 0)).unwrap();

        assert_ne!(
            first_rewrite.value(),
            second_rewrite.value(),
            "fold accumulators must rewrite into a tick-indexed chain"
        );
        assert_eq!(
            first_curry.suffix(),
            second_curry.suffix(),
            "using curry for the accumulator would freeze all ticks to one symbol"
        );
        assert_ne!(first_rewrite.value(), first_curry.suffix());
        assert_ne!(second_rewrite.value(), second_curry.suffix());
    }

    #[test]
    fn fold_floor_refuses_operand_without_iter_standing() {
        let err = IterStanding::new("FoldInput", IterProvenance::Derived, None)
            .expect_err("missing fold operand standing refuses");
        let msg = err.to_string();

        assert!(msg.contains("crime=missing standing"));
        assert!(msg.contains("owner=IterFloor"));
        assert!(msg.contains("shape=FoldInput carried no finite member count"));
        assert!(msg.contains("replacement=construct IterStanding"));
    }
}
