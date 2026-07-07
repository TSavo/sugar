// The vendor's LAW, sworn as a bounded loop. `sugar mint` lifts this to the
// universe `forall x in 0..8. block_width(x) == 64` -- NO per-point vector for
// x=3 or x=5 exists anywhere in this crate.
use blockfmt::block_width;

#[test]
fn block_width_is_64_for_all_levels() {
    for x in 0..8 {
        assert_eq!(block_width(x), 64);
    }
}
