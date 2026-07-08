// CONSUMER (bad twin): asserts a LIE about the same real serde_json callsite
// the vendor .proof swore. `sugar prove` conjoins the vendor's sworn equality
// with this contradictory fact and the consistency check goes UNSAT ->
// unsatisfied (red squiggle at the assert line).
#[test]
fn consumer_asserts_serde_json_write_bool_row() {
    let s = serde_json::to_string(&true).unwrap();

    assert_eq!(s, "false");
}
