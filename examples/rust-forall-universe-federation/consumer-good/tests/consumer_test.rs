// CONSUMER (good twin): asserts the TRUE value at a point the vendor never
// named (x=5). The floor-derived universe is independent-KIND testimony, so
// the claim is DISCHARGED (see #3445 Part-2 ruling) -- not merely refused.
use blockfmt::block_width;

#[test]
fn consumer_asserts_block_width_at_5() {
    assert_eq!(block_width(5), 64);
}
