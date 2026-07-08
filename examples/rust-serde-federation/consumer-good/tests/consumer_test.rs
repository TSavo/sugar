// CONSUMER (good twin): asserts the SAME exact serde_json vendor row the
// staged .proof swears. sugar prove conjoins the vendor's sworn fact with
// this consumer fact; they agree -> refused (stated cannot corroborate
// stated), never green-DISCHARGE, but never a contradiction either.
#[test]
fn consumer_asserts_serde_json_write_bool_row() {
    let s = serde_json::to_string(&true).unwrap();

    assert_eq!(s, "true");
}
