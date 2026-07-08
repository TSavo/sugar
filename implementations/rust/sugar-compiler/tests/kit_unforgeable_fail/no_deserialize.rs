// `Kit` derives no `serde::Deserialize`: a `Value` can never be cast into
// a `Kit`.
fn main() {
    let _kit: sugar_compiler::kit::Kit =
        serde_json::from_str("{}").expect("Kit must not be Deserialize");
}
