// CONSUMER (bad twin): lies about a point the vendor never named. No vendor
// assertion mentions x=3; only the lifted universe (from the staged .proof)
// covers it. z3 instantiates the forall at 3 -> block_width(3)==64,
// contradicting this claim -> UNSAT -> unsatisfied at THIS line.
use blockfmt::block_width;

#[test]
fn consumer_asserts_block_width_at_3() {
    assert_eq!(block_width(3), 128);
}
